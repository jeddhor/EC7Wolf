#!/bin/sh

# Frame-time benchmark for the GL renderer.
#
# Runs the same level for a fixed number of frames, several times, and reports
# the median steady-state frame time. Several times because a single run is not
# a measurement: on a desktop sharing its GPU with a session, repeats of
# identical code varied by 25% here, which is larger than most of the changes
# worth making.
#
# SDL's "offscreen" video driver is used rather than Xvfb. Xvfb has no GPU
# behind it -- it gives you llvmpipe, and a full-screen shader pass on a
# software rasteriser tells you nothing about a renderer's cost. That mistake
# cost an afternoon; see docs/android.md M7.
#
# Usage: bench_gl.sh [WIDTH] [HEIGHT] [FRAMES] [RUNS]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
build=${EC7WOLF_BUILD:-$(cd "$root/.." && pwd)/builds/release-build}
data=${EC7WOLF_DATA:-$(cd "$root/.." && pwd)/builds/release}

W=${1:-1280}; H=${2:-800}; FRAMES=${3:-300}; RUNS=${4:-5}

[ -x "$build/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build"; exit 0; }
[ -f "$data/MAPTEMP.CO7" ] || { printf 'SKIP: no game data in %s\n' "$data"; exit 0; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT INT TERM

printf 'GL frame time at %sx%s, %s frames, %s runs\n' "$W" "$H" "$FRAMES" "$RUNS"

: > "$work/times"
i=1
while [ "$i" -le "$RUNS" ]; do
	( cd "$data" && SDL_VIDEODRIVER=offscreen SDL_AUDIODRIVER=dummy timeout 180 \
		"$build/ec7wolf" --res "$W" "$H" --nowait --tedlevel MAP01 --skill 2 \
		--gl-profile --config "$work/c.cfg" --savedir "$work/s" \
		--capture-maxframes "$FRAMES" >"$work/run.log" 2>&1 ) || true
	# The last block is the steady state: the first covers start-up, where no
	# world has been drawn yet and the frame is a title screen.
	ms=$(grep -oE 'GL profile: [0-9.]+ ms' "$work/run.log" | tail -1 | tr -cd '0-9.')
	present=$(grep -oE 'present [0-9.]+' "$work/run.log" | tail -1 | tr -cd '0-9.')
	if [ -n "$ms" ]; then
		printf '  run %s: %s ms/frame (present %s)\n' "$i" "$ms" "${present:-?}"
		printf '%s\n' "$ms" >> "$work/times"
	else
		printf '  run %s: no profile output\n' "$i"
	fi
	i=$((i + 1))
done

n=$(wc -l < "$work/times")
[ "$n" -gt 0 ] || { printf 'FAIL: nothing measured\n'; exit 1; }
median=$(sort -g "$work/times" | sed -n "$(( (n + 1) / 2 ))p")
best=$(sort -g "$work/times" | head -1)
worst=$(sort -g "$work/times" | tail -1)
printf 'median %s ms/frame  (best %s, worst %s, n=%s)\n' "$median" "$best" "$worst" "$n"
