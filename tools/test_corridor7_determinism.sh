#!/bin/sh

# Renderer-redesign determinism gate.
#
# Runs the deterministic capture harness (see src/r_capture.*) twice with a
# pinned RNG seed and a fixed simulation-tic budget, then asserts the two
# per-tic checksum logs are byte-identical. Because the run length is bounded by
# tics rather than rendered frames, the result is independent of wall-clock
# frame pacing and stays reproducible even under the current render-driven
# timing loop.
#
# This is THE gate that later phases (fixed-step timing, interpolation, hardware
# renderers) must keep green: interpolation and renderer changes may never alter
# the simulation, so the checksum must not move.
#
# Usage: test_corridor7_determinism.sh EC7WOLF_BUILD_DIR CORRIDOR7_DATA_DIR \
#            [MAP] [SEED] [TICS]

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 5 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP] [SEED] [TICS]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
map=${3:-MAP01}
seed=${4:-12345}
tics=${5:-500}
ec7wolf="$build_dir/ec7wolf"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

for command in xvfb-run timeout; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

workdir=$(mktemp -d /tmp/ec7wolf-determinism.XXXXXX)
cleanup() { rm -rf "$workdir"; }
trap cleanup EXIT HUP INT TERM

run_capture() {
	# $1 = output checksum path, $2 = config file to use
	save=$(mktemp -d "$workdir/save.XXXXXX")
	(
		cd "$data_dir"
		timeout 120s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
			--data CO7 --no-upscale --config "$2" --savedir "$save" \
			--nowait --tedlevel "$map" --skill 2 \
			--capture-rngseed "$seed" --capture-checksum "$1" \
			--capture-maxtics "$tics"
	) >"$1.log" 2>&1
}

printf 'Determinism gate: map=%s seed=%s tics=%s\n' "$map" "$seed" "$tics"

# Run A generates a fresh config (interpolation on by default).
run_capture "$workdir/runA.txt" "$workdir/on.cfg"
# Run B reuses the same config: proves run-to-run determinism.
run_capture "$workdir/runB.txt" "$workdir/on.cfg"

if [ ! -s "$workdir/runA.txt" ] || [ ! -s "$workdir/runB.txt" ]; then
	printf 'FAIL: capture produced no checksum output (see %s.log)\n' \
		"$workdir/runA.txt" >&2
	tail -n 20 "$workdir/runA.txt.log" >&2 || true
	exit 1
fi

summary=$(tail -n 1 "$workdir/runA.txt")

if ! diff -q "$workdir/runA.txt" "$workdir/runB.txt" >/dev/null; then
	printf 'FAIL: simulation diverged between identical runs\n' >&2
	diff "$workdir/runA.txt" "$workdir/runB.txt" | head -n 20 >&2
	exit 1
fi
printf 'PASS: run-to-run determinism (%s)\n' "$summary"

# Interpolation invariant: motion interpolation must never change the
# simulation, so an interpolation-OFF run must produce the identical checksum.
if [ -f "$workdir/on.cfg" ] && grep -q 'R_Interpolate = 1;' "$workdir/on.cfg"; then
	sed 's/R_Interpolate = 1;/R_Interpolate = 0;/' "$workdir/on.cfg" > "$workdir/off.cfg"
	run_capture "$workdir/runC.txt" "$workdir/off.cfg"
	if [ ! -s "$workdir/runC.txt" ]; then
		printf 'FAIL: interpolation-off run produced no checksum output\n' >&2
		exit 1
	fi
	if diff -q "$workdir/runA.txt" "$workdir/runC.txt" >/dev/null; then
		printf 'PASS: interpolation on/off produce identical simulation\n'
	else
		printf 'FAIL: interpolation changed the simulation (on != off)\n' >&2
		diff "$workdir/runA.txt" "$workdir/runC.txt" | head -n 20 >&2
		exit 1
	fi
else
	printf 'WARN: could not derive an interpolation-off config; skipped invariant\n'
fi

# Renderer invariant: the simulation must not depend on what is drawing it.
#
# This became a live concern at the Phase 11 cutover, when OpenGL became the
# default: the runs above now use whichever renderer a fresh config selects, so
# without this the gate would silently stop covering the other one. The two are
# not merely different draw paths -- the GL window has no SDL_Renderer, mode
# setting takes a different branch, and the frame loop's pacing differs -- and
# any of that leaking into the simulation would show up here as a divergent
# checksum rather than as something a player would notice weeks later.
if [ -f "$workdir/on.cfg" ] && grep -q 'Vid_Renderer' "$workdir/on.cfg"; then
	for renderer in software opengl; do
		sed "s/Vid_Renderer = \".*\";/Vid_Renderer = \"$renderer\";/" \
			"$workdir/on.cfg" > "$workdir/$renderer.cfg"
		run_capture "$workdir/run-$renderer.txt" "$workdir/$renderer.cfg"
		if [ ! -s "$workdir/run-$renderer.txt" ]; then
			printf 'FAIL: the %s run produced no checksum output (see %s.log)\n' \
				"$renderer" "$workdir/run-$renderer.txt" >&2
			tail -n 20 "$workdir/run-$renderer.txt.log" >&2 || true
			exit 1
		fi
	done

	if diff -q "$workdir/run-software.txt" "$workdir/run-opengl.txt" >/dev/null; then
		printf 'PASS: software and OpenGL produce identical simulation\n'
	else
		printf 'FAIL: the renderer changed the simulation (software != opengl)\n' >&2
		diff "$workdir/run-software.txt" "$workdir/run-opengl.txt" | head -n 20 >&2
		exit 1
	fi
else
	printf 'WARN: no Vid_Renderer in the generated config; skipped the renderer invariant\n'
fi

exit 0
