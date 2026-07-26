#!/bin/sh

# Regression test: the sign-off page fills the window at any resolution.
#
# Corridor 7 does not cut straight to DOS -- it holds VGA chunk 13, the alien
# standing in the lit doorway, then fades out. That page is 320x200 art stretched
# across the whole window, and it is now upscaled first, which is what this
# guards.
#
# The specific hazard is how the draw is sized. A full-screen page used to be
# drawn through the 320x200 virtual space, which reads the texture's own
# dimensions as virtual units. That is correct only while the texture really is
# 320x200; hand it an upscaled one and the page is drawn several times too large,
# so the window shows the top-left corner of it blown up. Nothing crashes and
# nothing logs, and it is only visible in the two seconds before the game exits.
#
# So the property asserted is the one that actually defines "stretched to fill":
# the page must look the same whatever the resolution. Captured at two sizes and
# reduced to a common one, the two must agree. Sized wrongly they cannot -- each
# resolution picks a different upscale factor, so each would show a differently
# sized crop of the corner.
#
# Usage: test_corridor7_exit_screen.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

for command in import xdotool xvfb-run python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-exitscreen.XXXXXX)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT INT TERM

# Symlinks, so the real data directory keeps whatever the player installed there.
# CORR7CD.EXE is not optional: the palette is read out of it, and without it
# startup stalls before a window ever appears.
mkdir -p "$work/data"
for f in "$data_dir"/*.CO7 "$data_dir/CORR7CD.EXE" "$data_dir/ec7wolf.pk3"; do
	[ -e "$f" ] || continue
	ln -s "$f" "$work/data/$(basename "$f")"
done

export EX_BUILD="$build_dir" EX_WORK="$work" EX_DATA="$work/data"

shoot() { # $1 width  $2 height  $3 output png
	EX_W=$1 EX_H=$2 EX_SHOT=$3
	export EX_W EX_H EX_SHOT
	xvfb-run -a -s "-screen 0 ${EX_W}x${EX_H}x24" sh -c '
		cd "$EX_DATA"
		export SDL_AUDIODRIVER=dummy
		"$EX_BUILD/ec7wolf" --data CO7 --nowait --vid-renderer software \
			--res "$EX_W" "$EX_H" --config "$EX_WORK/cfg-$EX_W" \
			--savedir "$EX_WORK/sv" >"$EX_WORK/run-$EX_W.log" 2>&1 &
		pid=$!
		sleep 10
		# Past the title pages into the menu. Two presses: the first only
		# interrupts whichever page is showing.
		xdotool key --clearmodifiers Escape; sleep 1
		xdotool key --clearmodifiers Escape; sleep 2
		# Up from the first item wraps to the last, which is Exit Building.
		# Counting downwards instead would have to know which items are
		# disabled, since those are skipped.
		xdotool key --clearmodifiers Up; sleep 1
		xdotool key --clearmodifiers Return; sleep 2
		xdotool key --clearmodifiers y; sleep 3
		import -window root "$EX_SHOT"
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	'
	if [ ! -s "$EX_SHOT" ]; then
		printf 'FAIL: no exit screen at %sx%s; see %s/run-%s.log\n' \
			"$EX_W" "$EX_H" "$work" "$EX_W" >&2
		exit 1
	fi
}

shoot 960 600 "$work/exit-960.png"
shoot 640 400 "$work/exit-640.png"

python3 - "$work/exit-960.png" "$work/exit-640.png" <<'PY'
import sys
from PIL import Image

# The two captures are reduced to the authored size before comparing, so the
# only thing being measured is whether they show the same picture.
def page(path):
    return Image.open(path).convert("L").resize((320, 200), Image.BOX)

a, b = page(sys.argv[1]), page(sys.argv[2])
ab, bb = a.tobytes(), b.tobytes()
mae = sum(abs(ab[i]-bb[i]) for i in range(len(ab)))/len(ab)

# Content check, so a pair of black frames cannot agree its way to a pass. The
# page is a lit doorway at the end of a dark corridor, so it spans a wide range.
levels = len(set(ab))
spread = max(ab) - min(ab)

print("two resolutions agree to %.2f levels of 255; page uses %d grey levels, "
      "range %d" % (mae, levels, spread))

failed = False

# Measured at 0.72 with the draw sized correctly, and at 42.95 with the virtual
# space put back, so the threshold has room for the different upscale factors
# the two resolutions pick without coming near the failure it is for.
if mae > 12.0:
    print("FAIL: the sign-off page differs by %.2f levels between resolutions. "
          "It is not being stretched to fill the window -- most likely it is "
          "drawn through the 320x200 virtual space, which reads the upscaled "
          "texture's own size as virtual units and blows it up." % mae)
    failed = True

if levels < 16 or spread < 64:
    print("FAIL: the page shows %d grey levels over a range of %d. That is not "
          "the sign-off art; the screen is blank or nearly so."
          % (levels, spread))
    failed = True

sys.exit(1 if failed else 0)
PY

printf 'PASS: the sign-off page fills the window identically at both resolutions\n'
