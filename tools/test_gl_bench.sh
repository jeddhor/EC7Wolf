#!/bin/sh

# Regression test: the renderer is still fast enough to play at the default.
#
# Milestone 7 of docs/android.md. Not a competitive benchmark -- the number
# depends entirely on the machine -- but a floor. The compositor is 90% of a
# frame at high resolutions, and a change that made it several times worse
# would otherwise only be noticed by somebody playing.
#
# The ceiling is deliberately generous. This has to pass on whatever hardware
# the suite runs on, including a shared CI box, so it is set where a frame time
# means "something is badly wrong", not "this could be tuned".
#
# Usage: test_gl_bench.sh [BUILD_DIR] [DATA_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
build=${1:-$(cd "$root/.." && pwd)/builds/release-build}
data=${2:-$(cd "$root/.." && pwd)/builds/release}

[ -x "$build/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build"; exit 0; }
[ -f "$data/MAPTEMP.CO7" ] || { printf 'SKIP: no game data in %s\n' "$data"; exit 0; }

# The shipped default, which is what a player actually gets.
W=640; H=480
CEILING_MS=33     # 30 fps; below this and something is structurally wrong

status=0
printf 'Frame time at the shipped default (%sx%s)\n' "$W" "$H"

out=$(EC7WOLF_BUILD="$build" EC7WOLF_DATA="$data" "$here/bench_gl.sh" "$W" "$H" 300 3 2>&1) || true
printf '%s\n' "$out" | sed 's/^/  /'

case $out in
	*SKIP:*) printf '%s\n' "$out"; exit 0 ;;
esac

median=$(printf '%s\n' "$out" | sed -n 's/^median \([0-9.]*\) ms.*/\1/p')
if [ -z "$median" ]; then
	printf '  FAIL nothing was measured\n'
	exit 1
fi

# Integer compare: the shell has no floats, and a tenth of a millisecond is not
# what this is deciding.
whole=${median%%.*}
if [ "${whole:-999}" -lt "$CEILING_MS" ]; then
	printf '  ok   %s ms/frame, under the %s ms ceiling\n' "$median" "$CEILING_MS"
else
	printf '  FAIL %s ms/frame is over the %s ms ceiling\n' "$median" "$CEILING_MS"
	status=1
fi

if [ "$status" -eq 0 ]; then printf '\nPASS\n'; else printf '\nFAIL: see above.\n'; fi
exit "$status"
