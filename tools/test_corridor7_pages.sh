#!/bin/sh

# Regression test: the full-screen picture pages fill the window at any
# resolution.
#
# These pages -- title, credits, high scores, the status report, the sign-off
# screen with the alien in the doorway -- are 320x200 art stretched across the
# whole window, and are now upscaled first. That upscale is what this guards,
# indirectly but in the way that matters.
#
# The hazard is how a page's draw is sized. Sizing it through the 320x200 virtual
# space reads the texture's own dimensions as virtual units, which is right only
# while the texture really is 320x200; hand it an upscaled one and the page is
# drawn several times too large, so the window shows a blown-up corner of it.
# Nothing crashes and nothing logs. CA_CacheScreen avoids this by construction --
# it sizes from the texture or from the screen -- but individually placed pages
# do not, and the plates have to pass their authored size explicitly.
#
# So the property asserted is the one that actually defines "stretched to fill":
# a page must look the same whatever the resolution. Captured at two sizes and
# reduced to a common one, the two must agree. Sized wrongly they cannot -- each
# resolution picks a different upscale factor, so each would show a differently
# sized crop of the corner.
#
# Only the two pages that wait for input are measured. Title and credits run on
# timers, and the title dissolves, so sampling those at a wall-clock offset would
# compare whatever dissolve frame each run happened to land on.
#
# Usage: test_corridor7_pages.sh BUILD_DIR DATA_DIR   (both absolute)

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

work=$(mktemp -d /tmp/ec7wolf-pages.XXXXXX)
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

export PG_BUILD="$build_dir" PG_WORK="$work" PG_DATA="$work/data"

# One run per resolution collects both pages, so this costs two launches rather
# than one per page.
shoot() { # $1 width  $2 height
	PG_W=$1 PG_H=$2
	export PG_W PG_H
	xvfb-run -a -s "-screen 0 ${PG_W}x${PG_H}x24" sh -c '
		cd "$PG_DATA"
		export SDL_AUDIODRIVER=dummy
		export SDL_VIDEODRIVER=x11
		"$PG_BUILD/ec7wolf" --data CO7 --nowait --vid-renderer software \
			--res "$PG_W" "$PG_H" --config "$PG_WORK/cfg-$PG_W" \
			--savedir "$PG_WORK/sv" >"$PG_WORK/run-$PG_W.log" 2>&1 &
		pid=$!
		sleep 10
		# Past the title pages into the menu. Two presses: the first only
		# interrupts whichever page is showing.
		xdotool key --clearmodifiers Escape; sleep 1
		xdotool key --clearmodifiers Escape; sleep 2

		# Up from the first item wraps to the last (Exit Building); once more
		# reaches High Scores. Counting downwards instead would have to know
		# which items are disabled, since those are skipped.
		xdotool key --clearmodifiers Up; sleep 0.4
		xdotool key --clearmodifiers Up; sleep 0.6
		xdotool key --clearmodifiers Return; sleep 3
		import -window root "$PG_WORK/scores-$PG_W.png"
		xdotool key --clearmodifiers Escape; sleep 2

		# Back on the menu with High Scores selected; one Down reaches Exit.
		xdotool key --clearmodifiers Down; sleep 0.6
		xdotool key --clearmodifiers Return; sleep 2
		xdotool key --clearmodifiers y; sleep 3
		import -window root "$PG_WORK/exit-$PG_W.png"
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	'
	for page in scores exit; do
		if [ ! -s "$work/$page-$PG_W.png" ]; then
			printf 'FAIL: no %s page at %sx%s; see %s/run-%s.log\n' \
				"$page" "$PG_W" "$PG_H" "$work" "$PG_W" >&2
			exit 1
		fi
	done
}

shoot 960 600
shoot 640 400

python3 - "$work" <<'PY'
import sys
from PIL import Image

work = sys.argv[1]

# Each page is reduced to the authored size before comparing, so the only thing
# measured is whether the two resolutions show the same picture.
def page(path):
    return Image.open(path).convert("L").resize((320, 200), Image.BOX)

# Measured below 1.0 with the draws sized correctly, and at 42.95 with a page put
# back through the virtual space, so the threshold has room for the different
# upscale factors the two resolutions pick without coming near the failure it is
# for.
MAX_MAE = 12.0

failed = False
for name, label in (("scores", "high scores"), ("exit", "sign-off")):
    a, b = page("%s/%s-960.png" % (work, name)), page("%s/%s-640.png" % (work, name))
    ab, bb = a.tobytes(), b.tobytes()
    mae = sum(abs(ab[i]-bb[i]) for i in range(len(ab)))/len(ab)

    # Content check, so a pair of black frames cannot agree its way to a pass.
    levels = len(set(ab))
    spread = max(ab) - min(ab)

    print("%s: two resolutions agree to %.2f levels of 255; %d grey levels, "
          "range %d" % (label, mae, levels, spread))

    if mae > MAX_MAE:
        print("FAIL: the %s page differs by %.2f levels between resolutions. It "
              "is not being stretched to fill the window -- most likely its draw "
              "is sized through the 320x200 virtual space, which reads the "
              "upscaled texture's own size as virtual units." % (label, mae))
        failed = True
    if levels < 16 or spread < 64:
        print("FAIL: the %s page shows %d grey levels over a range of %d. The "
              "screen is blank or nearly so." % (label, levels, spread))
        failed = True

sys.exit(1 if failed else 0)
PY

printf 'PASS: the full-screen pages fill the window identically at both resolutions\n'
