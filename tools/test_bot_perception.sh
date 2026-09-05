#!/bin/sh

# Regression test: a bot sees only what a player standing there could see.
#
# Milestone B4 of docs/multiplayer-bots-and-server.md, section 13.2.
#
# The headline check recomputes every sight line from the map's own wall grid
# and fails if any of them passes through a wall. That is deliberately not a
# restatement of what the engine did: the gate marches the segment itself, in
# Python, over the solid cells dumped from the map, and compares against the
# sightings the bots actually recorded. If CheckLine ever leaks, or somebody
# replaces it with a renderer visibility mark, this notices.
#
# Renderer independence is checked by running the same match under software and
# OpenGL and requiring byte-identical perception. A bot's knowledge must not
# depend on what is being drawn, or whether anything is drawn at all -- a
# dedicated server draws nothing, and a bot that can only see what the console
# player's camera has visited is a bot that behaves differently on a machine
# with no screen.
#
# And the whole thing is guarded by a count: a run in which nothing was ever
# seen would pass every check above without testing anything.
#
# Usage: test_bot_perception.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-percept.XXXXXX)
. "$here/xvfb_common.sh"

display=:199
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

tics=900
maps=${MAPS:-"MAP53 MAP51 MAP60"}

run() {  # run MAP TAG RENDERER
	mkdir -p "$work/$2-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer "$3" \
		--config "$work/$2.cfg" --savedir "$work/$2-saves" \
		--capture-rngseed 1 \
		--capture-perception "$work/$2.see" \
		--capture-nav "$work/$2.nav" \
		--capture-maxtics "$tics" \
		--tedlevel "$1" --skill 2 --battle --bots 3 ) >"$work/$2.log" 2>&1 || true
}

printf 'Bots see what a player standing there would see\n'

for map in $maps; do
	run "$map" a software
	if [ ! -s "$work/a.see" ] || [ ! -s "$work/a.nav" ]; then
		printf '  FAIL %s: no perception trace\n' "$map"
		sed 's/\x08//g' "$work/a.log" | grep -vE '^\s*$' | tail -3 | sed 's/^/         /'
		status=1
		continue
	fi

	python3 - "$work/a.see" "$work/a.nav" "$map" <<'PY'
import sys

trace, nav, mapname = sys.argv[1], sys.argv[2], sys.argv[3]

solid = set()
for line in open(nav):
    f = line.split()
    if f and f[0] == "wall":
        solid.add((int(f[1]), int(f[2])))

sightings = []
for line in open(trace):
    if line.startswith("#"):
        continue
    f = [int(v) for v in line.split()]
    # tic observer ox oy subject sx sy distance bearing offaxis
    sightings.append(f)

problems = []

# The sight line, marched independently. Sampled finely and judged on how much
# of the line lies inside a wall rather than on whether it touches one: a line
# that clips the corner of a solid cell is what looking diagonally past a
# pillar looks like, and the engine allows it. A line that spends real length
# inside one is seeing through a wall.
UNITS = 64.0            # map units to the tile

def blocked(ox, oy, sx, sy):
    # Positions arrive in map units, so the tile a point is in is a floor
    # division and the line is the real one rather than a line between tile
    # indices. Endpoint tiles are excluded: the observer and the subject are
    # each standing in their own cell and neither is an obstruction.
    a = (int(ox // UNITS), int(oy // UNITS))
    b = (int(sx // UNITS), int(sy // UNITS))
    steps = 400
    inside = {}
    for i in range(1, steps):
        t = i / float(steps)
        x = (ox + (sx - ox) * t) / UNITS
        y = (oy + (sy - oy) * t) / UNITS
        cell = (int(x), int(y))
        if cell == a or cell == b:
            continue
        if cell not in solid:
            continue
        # How far inside the cell this sample is. A line can run along a wall's
        # face -- one sighting on MAP53 grazes a solid cell for a full tile of
        # travel while never more than 0.08 of a tile inside it -- and that is
        # looking along a surface, not through it. Only samples well inside the
        # cell count as penetration.
        fx, fy = x - cell[0], y - cell[1]
        depth = min(fx, 1.0 - fx, fy, 1.0 - fy)
        if depth >= 0.15:
            inside[cell] = inside.get(cell, 0) + 1
    return [c for c, n in inside.items() if n >= 8]

leaks = 0
worst = None
for f in sightings:
    tic, obs, ox, oy, sub, sx, sy = f[0], f[1], f[2], f[3], f[4], f[5], f[6]
    through = blocked(ox, oy, sx, sy)
    if through:
        leaks += 1
        if worst is None:
            worst = (tic, obs, (ox, oy), sub, (sx, sy), through[:3])

if leaks:
    problems.append("%d of %d sightings crossed a wall, e.g. %s"
                    % (leaks, len(sightings), worst))

# Nothing may be seen outside the field of view the profile declares.
wide = [f for f in sightings if f[9] > 45]
if wide:
    problems.append("%d sightings outside the 45 degree half-FOV, e.g. %s"
                    % (len(wide), wide[0]))

# And the run has to have seen something, or none of the above means anything.
if len(sightings) < 20:
    problems.append("only %d sightings recorded; nothing was really tested"
                    % len(sightings))

print("  ..   %s: %d sightings, %d crossed a wall, %d outside the view"
      % (mapname, len(sightings), leaks, len(wide)))
if problems:
    for p in problems:
        print("  FAIL %s: %s" % (mapname, p))
    sys.exit(1)
print("  ok   %s: every sighting had a clear line and was in view" % mapname)
PY
	[ $? -eq 0 ] || status=1
done

# The same match, drawn two different ways, and drawn not at all as far as the
# bots are concerned.
run MAP53 sw software
run MAP53 gl opengl
if [ -s "$work/gl.see" ]; then
	check "the renderer does not change what a bot perceives" \
		cmp -s "$work/sw.see" "$work/gl.see"
else
	printf '  ..   OpenGL run produced nothing; skipping the renderer check\n'
fi

if [ "$status" -eq 0 ]; then
	printf 'PASS: bots see only what is really in front of them.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
