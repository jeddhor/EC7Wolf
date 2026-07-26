#!/bin/sh

# Regression test: the inset map panel keeps working while the player stands in
# a doorway.
#
# The panel greys out any tile the player cannot currently walk to, which it
# decides with map->CheckLink() against the zone the player is standing in. A
# door belongs to no zone -- it is the link between two of them -- so a player
# halfway through a doorway had a NULL zone, CheckLink answered false for
# everything, and the whole painted window filled solid grey.
#
# Asserted by comparing the panel on the door tile against the panel on the
# floor tile beside it. Both are in the same room, so they must agree closely;
# with the bug the door tile is almost entirely solid.
#
# Usage: test_corridor7_automap_doorway.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
display=:107
work=$(mktemp -d /tmp/ec7wolf-doorway.XXXXXX)

# MAP01, read from MAPTEMP.CO7 plane 0: (16,31) is door code 254, and (15,31)
# and (17,31) are floor in zone 256 on either side of it.
door_x=16
floor_x=15
tile_y=31

cleanup() {
	[ -n "${xvfb:-}" ] && kill "$xvfb" 2>/dev/null || true
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

Xvfb "$display" -screen 0 900x600x24 >"$work/xvfb.log" 2>&1 &
xvfb=$!
sleep 2

shoot() { # $1 label  $2 tile x
	(
		cd "$data_dir"
		timeout 90s env DISPLAY="$display" SDL_AUDIODRIVER=dummy \
			"$build_dir/ec7wolf" --data CO7 --nowait --normal --tedlevel MAP01 \
			--vid-renderer software --res 640 400 \
			--capture-rngseed 1 --capture-c7map \
			--capture-warp "$2" "$tile_y" 0 \
			--capture-frame 8 --capture-file "$work/$1.png" --capture-maxtics 60 \
			--config "$work/cfg" --savedir "$work/sv"
	) >"$work/$1.log" 2>&1
	if [ ! -s "$work/$1.png" ]; then
		printf 'FAIL: no capture for %s; see %s/%s.log\n' "$1" "$work" "$1" >&2
		exit 1
	fi
}

shoot door "$door_x"
shoot floor "$floor_x"

# The panel is 64x64 at (256,0) in 320x200, so at 640x400 it is 128x128 at
# (512,0). Grey (palette 32) is "solid or unreachable"; count it in each shot.
python3 - "$work/door.png" "$work/floor.png" <<'PY'
import sys
from PIL import Image

GREY = (142, 142, 142)   # palette index 32 at the C7 palette

def grey_count(path):
    im = Image.open(path).convert("RGB").crop((512, 0, 640, 128))
    counts = dict((c, n) for n, c in im.getcolors(maxcolors=1 << 16))
    return counts.get(GREY, 0), im.width * im.height

door, total = grey_count(sys.argv[1])
floor, _ = grey_count(sys.argv[2])

# The border is grey too and is 1008 px of the 16384, so compare the excess.
BORDER = 1008
door_solid = door - BORDER
floor_solid = floor - BORDER

print("panel solid px: doorway=%d, floor beside it=%d" % (door_solid, floor_solid))

# One tile of window scroll plus the player marker moves a couple of hundred
# pixels; a collapsed zone lookup roughly doubles the solid area.
if door_solid > floor_solid * 3 // 2:
    print("FAIL: standing in the doorway greys out the map "
          "(%d solid px vs %d one tile away). The player's tile has no zone, "
          "so every CheckLink failed." % (door_solid, floor_solid))
    sys.exit(1)

print("PASS: the doorway panel matches the floor beside it "
      "(%d vs %d solid px)" % (door_solid, floor_solid))
PY
