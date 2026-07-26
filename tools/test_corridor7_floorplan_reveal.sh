#!/bin/sh

# Regression test: the floor plan reveals the whole floor, permanently.
#
# The inset panel normally paints only a 23x24 tile window around the player,
# and greys out anything the player cannot currently walk to. The floor plan
# drops the window -- but it also has to drop the reachability gate, and that is
# what this guards. The gate is a LIVE query: CheckLink reads zoneLinks, which
# counts doors that are open at this instant, so with the gate left on the plan
# appeared to expire. Walking through a door and letting it shut behind you
# re-greyed everything beyond it, and the panel collapsed back to roughly the
# room the player was standing in.
#
# The property being asserted is that with the plan the panel is a blueprint:
# its walls depend on the level's geometry and on nothing else. Two captures
# from opposite ends of the map must therefore paint pixel-identical walls.
#
# Usage: test_corridor7_floorplan_reveal.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
display=:108
work=$(mktemp -d /tmp/ec7wolf-floorplan.XXXXXX)

# Two MAP01 tiles in different zones, at opposite ends of the level, read from
# MAPTEMP.CO7 plane 0: (17,31) is in zone 256 and (42,16) is in zone 260.
near_x=17; near_y=31
far_x=42;  far_y=16

cleanup() {
	[ -n "${xvfb:-}" ] && kill "$xvfb" 2>/dev/null || true
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

Xvfb "$display" -screen 0 900x600x24 >"$work/xvfb.log" 2>&1 &
xvfb=$!
sleep 2

shoot() { # $1 label  $2 tile x  $3 tile y  $4.. extra engine arguments
	label=$1; tx=$2; ty=$3; shift 3
	(
		cd "$data_dir"
		timeout 90s env DISPLAY="$display" SDL_AUDIODRIVER=dummy \
			"$build_dir/ec7wolf" --data CO7 --nowait --normal --tedlevel MAP01 \
			--vid-renderer software --res 640 400 \
			--capture-rngseed 1 --capture-c7map \
			--capture-warp "$tx" "$ty" 0 \
			"$@" \
			--capture-frame 8 --capture-file "$work/$label.png" --capture-maxtics 60 \
			--config "$work/cfg" --savedir "$work/sv"
	) >"$work/$label.log" 2>&1
	if [ ! -s "$work/$label.png" ]; then
		printf 'FAIL: no capture for %s; see %s/%s.log\n' "$label" "$work" "$label" >&2
		exit 1
	fi
}

shoot plan_near "$near_x" "$near_y" --capture-floorplan
shoot plan_far  "$far_x"  "$far_y"  --capture-floorplan
shoot bare_near "$near_x" "$near_y"

python3 - "$work/plan_near.png" "$work/plan_far.png" "$work/bare_near.png" <<'PY'
import sys
from PIL import Image

# Panel colours, C7 palette: index 32 is the border, the walls, and any floor
# the gate has greyed out; 48 is open floor. The rest are the overlays that are
# expected to move -- the player, the pixel trailing them, and the aliens.
GREY   = (142, 142, 142)
FLOOR  = (16, 16, 81)
BORDER = 1008 * 4        # the 1px panel border, at the 2x scale of a 640x400 shot

def pixels(path):
    # The panel is 64x64 at (256,0) in 320x200, so 128x128 at (512,0) here.
    im = Image.open(path).convert("RGB").crop((512, 0, 640, 128))
    raw = im.tobytes()
    return [tuple(raw[i:i+3]) for i in range(0, len(raw), 3)]

near, far, bare = (pixels(p) for p in sys.argv[1:4])

# Only the map itself is being compared, so pixels either capture has painted an
# overlay onto are skipped. The count is reported and capped: a large ignored
# set could hide a real difference underneath it.
overlay = [a not in (GREY, FLOOR) or b not in (GREY, FLOOR)
           for a, b in zip(near, far)]
ignored = sum(overlay)
differing = sum(1 for a, b, skip in zip(near, far, overlay)
                if not skip and (a == GREY) != (b == GREY))

near_grey = near.count(GREY)
bare_grey = bare.count(GREY)

print("grey px: plan at (17,31)=%d, plan at (42,16)=%d, no plan at (17,31)=%d"
      % (near_grey, far.count(GREY), bare_grey))
print("wall px differing between the two plan captures: %d (%d ignored as "
      "player/alien overlay)" % (differing, ignored))

failed = False

if differing:
    print("FAIL: the revealed map changes when the player moves (%d px differ). "
          "With the floor plan the panel must show the floor's geometry and "
          "nothing else -- the reachability gate is still running under it, and "
          "it re-greys rooms whenever a door shuts." % differing)
    failed = True

if ignored > 256:
    print("FAIL: %d px were ignored as overlay, far more than the player marker "
          "and a handful of aliens account for. The comparison above is not "
          "covering enough of the panel to mean anything." % ignored)
    failed = True

# 23x24 tiles is the unrevealed window, 2x2 px per tile. If the plan is working
# the painted area covers the whole 62x62 tile interior, so the walls alone
# exceed what the window could hold even if every tile in it were solid.
WINDOW_PX = 23 * 24 * 4
if near_grey - BORDER <= WINDOW_PX:
    print("FAIL: the floor plan painted %d wall px, no more than the %d the "
          "unrevealed window could hold -- the reveal is not reaching past it."
          % (near_grey - BORDER, WINDOW_PX))
    failed = True

# Positive control: without the plan the panel must be doing something else,
# otherwise the two captures above could agree for the trivial reason that the
# plan is not being applied at all.
if bare_grey == near_grey:
    print("FAIL: the panel looks identical with and without the floor plan "
          "(%d grey px). --capture-floorplan is not reaching the panel, so "
          "this test proves nothing." % near_grey)
    failed = True

sys.exit(1 if failed else 0)
PY

printf 'PASS: the floor plan reveals the whole floor regardless of position\n'
