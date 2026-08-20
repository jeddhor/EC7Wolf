#!/bin/sh

# Regression test: switching menu screens fades only the menu column.
#
# Under the Corridor 7 skin the splash art on the left is identical either side
# of a menu switch -- only the column of items changes. Dipping the whole display
# to black to swap a list of words throws away the one part of the picture that
# was never going to change, so the transition fades just the column.
#
# Two things have to hold, and a test of only one of them passes for the wrong
# reason. The art must not move: that is the point of the change, and it is
# asserted exactly, because the backdrop is a static blit and has no business
# differing by even a level. And the column must actually go dark and come back:
# without that, deleting the transition entirely would pass the first check.
#
# Usage: test_corridor7_menu_transition.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

for command in import compare xdotool xvfb-run python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-menufade.XXXXXX)
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

export MF_BUILD="$build_dir" MF_WORK="$work" MF_DATA="$work/data"

xvfb-run -a -s "-screen 0 960x600x24" sh -c '
	cd "$MF_DATA"
	export SDL_AUDIODRIVER=dummy
	export SDL_VIDEODRIVER=x11
	"$MF_BUILD/ec7wolf" --data CO7 --no-upscale --nowait --vid-renderer software \
		--res 960 600 --config "$MF_WORK/cfg" --savedir "$MF_WORK/sv" \
		>"$MF_WORK/run.log" 2>&1 &
	pid=$!
	sleep 10

	# Take the input focus explicitly. Xvfb runs with no window manager, so
	# nothing assigns focus and X leaves it as PointerRoot -- keys then go to
	# whatever the pointer happens to be over, which races with the window being
	# mapped. That is how a keypress goes missing, and a missing keypress here
	# was twice reported as a rendering regression.
	window=$(xdotool search --pid "$pid" --onlyvisible 2>/dev/null | sed -n 1p)
	if [ -z "$window" ]; then
		window=$(xdotool search --onlyvisible --name "EC7Wolf" 2>/dev/null | sed -n 1p)
	fi
	if [ -n "$window" ]; then
		xdotool windowfocus --sync "$window" 2>/dev/null || true
		xdotool mousemove --window "$window" 20 20 2>/dev/null || true
	else
		echo "no game window found to focus" >>"$MF_WORK/run.log"
	fi

	# Past the title pages into the menu. Two presses: the first only interrupts
	# whichever page is showing.
	xdotool key --clearmodifiers Escape; sleep 1
	xdotool key --clearmodifiers Escape; sleep 2
	# One Down reaches Options: the two entries between it and New Mission need a
	# game in progress and are skipped while disabled.
	xdotool key --clearmodifiers Down; sleep 0.8
	import -window root "$MF_WORK/s-00.png"

	# Sampled as fast as the grabs allow, with the keypress backgrounded, so the
	# transition is caught in progress rather than only at its endpoints.
	#
	# Retried, because the keypress can simply be lost. Under the load of a full
	# gate run this failed with the column reading identically at the start, the
	# darkest sample AND two seconds later -- the menu had not switched at all,
	# so there was no fade to photograph and the test reported "no fade is
	# happening", which is the one conclusion the evidence did not support.
	# Confirm the screen actually changed before believing anything about how it
	# changed.
	attempt=1
	switched=0
	while [ "$attempt" -le 3 ]; do
		xdotool key --clearmodifiers Return &
		for i in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18; do
			import -window root "$MF_WORK/s-$i.png"
		done
		sleep 2
		import -window root "$MF_WORK/s-99.png"
		if ! compare -metric AE "$MF_WORK/s-00.png" "$MF_WORK/s-99.png" \
			null: 2>&1 | grep -qx 0; then
			switched=1
			break
		fi
		echo "menu did not respond to Return (attempt $attempt); retrying" \
			>>"$MF_WORK/run.log"
		attempt=$((attempt + 1))
		[ -n "$window" ] && xdotool windowfocus --sync "$window" 2>/dev/null || true
		xdotool key --clearmodifiers Escape; sleep 1
		xdotool key --clearmodifiers Down; sleep 0.8
	done
	echo "$switched" >"$MF_WORK/switched"
	kill "$pid" 2>/dev/null || true
	wait "$pid" 2>/dev/null || true
'

if [ ! -s "$work/s-99.png" ]; then
	printf 'FAIL: no menu captures; see %s/run.log\n' "$work" >&2
	exit 1
fi

# If the menu never switched there is no transition to photograph, and every
# statement the analysis below would make about the fade is unfounded. Say what
# actually happened instead. This gate failed twice with "no fade is happening",
# which sent the reader looking for a rendering regression that was never there;
# the retry above was added for the same reason but still fell through to the
# analysis when all three attempts were lost.
if [ ! -s "$work/switched" ] || [ "$(cat "$work/switched")" = "0" ]; then
	printf 'FAIL: the menu never responded to Return after 3 attempts, so no\n' >&2
	printf '      transition was captured. That is an input failure in this\n' >&2
	printf '      test, not a rendering result. Last of the game log:\n' >&2
	tail -20 "$work/run.log" 2>/dev/null | sed 's/^/      /' >&2
	exit 1
fi

python3 - "$work" <<'PY'
import glob, sys
from PIL import Image

work = sys.argv[1]
shots = sorted(glob.glob("%s/s-*.png" % work))

def regions(path):
    im = Image.open(path).convert("L")
    w, h = im.size
    # The column fade starts a little left of the item labels, around 56% of the
    # width. Left of half the screen is art that must not be touched; right of
    # 56% is the column being faded.
    return im.crop((0, 0, w//2, h)).tobytes(), im.crop((int(0.56*w), 0, w, h)).tobytes()

art0, col0 = regions(shots[0])

worst_art = 0.0
bright0 = sum(1 for p in col0 if p > 60)
brights = []
for path in shots:
    art, col = regions(path)
    mae = sum(abs(a-b) for a, b in zip(art0, art))/len(art0)
    worst_art = max(worst_art, mae)
    brights.append(sum(1 for p in col if p > 60))

print("art side: worst frame differs from the first by %.3f levels of 255"
      % worst_art)
print("column lit pixels: %d at the start, %d at the darkest, %d at the end"
      % (bright0, min(brights), brights[-1]))

failed = False

# The backdrop is a static blit through a fixed fade; it has no business
# differing at all. A palette fade of the whole screen would put this in the tens.
if worst_art > 0.5:
    print("FAIL: the splash art changed by %.3f levels during the switch. The "
          "transition is fading more than the menu column -- most likely the "
          "whole-screen palette fade is back." % worst_art)
    failed = True

if bright0 < 200:
    print("FAIL: the starting menu column has only %d lit pixels, so the capture "
          "is not on a drawn menu and the rest of this proves nothing." % bright0)
    failed = True

# Without this, removing the transition altogether would pass the art check.
if min(brights) > 0.2*bright0:
    print("FAIL: the column never dropped below %d lit pixels (from %d). No fade "
          "is happening -- the screens are being swapped outright."
          % (min(brights), bright0))
    failed = True

# Measured against an absolute floor rather than against the starting count: the
# screen being switched to has its own number of rows -- Options has half what
# the main menu does -- so ending dimmer than it started is expected and says
# nothing. What must not happen is ending dark.
if brights[-1] < 500:
    print("FAIL: the column ended at %d lit pixels, far too few for a drawn "
          "menu. It faded out and never came back." % brights[-1])
    failed = True

sys.exit(1 if failed else 0)
PY

printf 'PASS: menu switches fade the column and leave the splash art standing\n'
