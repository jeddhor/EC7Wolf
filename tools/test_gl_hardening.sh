#!/bin/sh

# GL hardening: debug output + resource-leak checks over repeated map loads
# (renderer redesign Phase 11).
#
# Exercises the live OpenGL renderer's hardening instrumentation. For each of a
# set of Corridor 7 maps it runs a full live-GL session (SDLFB GL window ->
# per-frame GPU world + 2D composite -> clean shutdown) with GL debug output
# enabled (--gl-debug), and asserts on every run:
#   * the OpenGL renderer went live (not the software fallback),
#   * the KHR_debug callback installed (or was cleanly reported unavailable),
#   * NO GL errors and NO HIGH-severity GL debug messages were emitted,
#   * shutdown reports a balanced GL object ledger -- "0 leaked GL objects" --
#     i.e. every persistent/per-present GL object was freed and the per-map
#     texture caches were released.
# Sweeping several maps repeats the renderer init -> cache build -> teardown
# lifecycle, so a per-map leak or a cache that is not invalidated on map change
# surfaces as a nonzero balance.
#
# Runs headlessly (Xvfb + Mesa creates a real GL window). ImageMagick not needed.
#
# Usage: test_gl_hardening.sh BUILD_DIR DATA_DIR [MAP...]

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP...]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd); shift
data_dir=$(cd "$1" && pwd); shift
ec7wolf="$build_dir/ec7wolf"

if [ "$#" -gt 0 ]; then
	maps="$*"
else
	maps="MAP01 MAP20 MAP40"
fi

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

cfg=$(mktemp -d /tmp/glhard-cfg.XXXXXX)
save=$(mktemp -d /tmp/glhard-save.XXXXXX)
logdir=$(mktemp -d /tmp/glhard-log.XXXXXX)
cleanup() { rm -rf "$cfg" "$save" "$logdir"; }
trap cleanup EXIT HUP INT TERM

n_pass=0
n_fail=0
saw_debug=0

for map in $maps; do
	log="$logdir/$map.log"
	set +e
	(
		cd "$data_dir"
		timeout 120s env SDL_AUDIODRIVER=dummy xvfb-run -a "$ec7wolf" \
			--data CO7 --config "$cfg/$map.cfg" --savedir "$save" \
			--nowait --tedlevel "$map" --skill 2 --vid-renderer opengl \
			--gl-debug --capture-rngseed 1 --capture-frame 20 \
			--capture-maxframes 45
	) >"$log" 2>&1
	rc=$?
	set -e

	fail=""
	if [ "$rc" -ne 0 ]; then
		fail="exited rc=$rc"
	elif ! grep -q "Renderer: using OpenGL renderer." "$log"; then
		fail="did not go live (software fallback)"
	elif ! grep -q "GL live: 0 leaked GL objects (balanced" "$log"; then
		fail="unbalanced GL object ledger (leak)"
	elif grep -q "^GL error " "$log"; then
		fail="GL error(s) emitted: $(grep -c '^GL error ' "$log")"
	elif grep -q "GL debug \[HIGH\]" "$log"; then
		fail="HIGH-severity GL debug message(s)"
	fi

	# The KHR_debug path must have run (installed, or cleanly noted unavailable).
	if grep -q "GL debug: KHR_debug callback installed" "$log" ||
		grep -q "GL debug: GL_KHR_debug unavailable" "$log"; then
		saw_debug=1
	fi

	if [ -z "$fail" ]; then
		n_pass=$((n_pass + 1))
		printf 'PASS: %-6s live GL, debug clean, GL objects balanced.\n' "$map"
	else
		n_fail=$((n_fail + 1))
		printf 'FAIL: %-6s %s; see %s\n' "$map" "$fail" "$log" >&2
	fi
done

if [ "$saw_debug" -ne 1 ]; then
	printf 'FAIL: GL debug path never ran (KHR_debug neither installed nor reported).\n' >&2
	exit 1
fi

if [ "$n_fail" -ne 0 ]; then
	printf 'FAIL: %s of %s map(s) failed hardening checks.\n' \
		"$n_fail" "$((n_pass + n_fail))" >&2
	exit 1
fi

printf 'PASS: %s map(s) passed live-GL debug + resource-leak hardening.\n' "$n_pass"
exit 0
