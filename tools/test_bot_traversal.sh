#!/bin/sh

# Regression test: the query a navigator asks agrees with the game.
#
# Milestone B2, step 2, of docs/multiplayer-bots-and-server.md.
#
# A navigator has to know whether a step is possible before taking it, and the
# only honest answer comes from the code that decides whether a step actually
# succeeds. Ask a different piece of code and you get a graph that disagrees
# with the world: a route through a gap the player does not fit through, or a
# wall the planner believes in and the pawn walks straight past.
#
# So TryMove's geometry now lives in g_traversal.cpp and TryMove calls it. That
# makes agreement structural rather than hopeful -- but only for the geometry.
# CanOccupyTile and CanStepBetweenTiles are new reasoning on top of it, and
# this is what checks them:
#
#   * a player walks an arena for four hundred tics, turning as it goes, and
#     every tile it stands on must have been predicted standable;
#   * every step it actually takes between adjacent tiles must have been
#     predicted possible;
#   * the answers must be symmetric, since walking east from A to B and west
#     from B to A cross the same gap; and
#   * the body being asked about must be the real one. A zero radius fits
#     everywhere, including inside a wall, so a query that quietly lost the
#     player's width would pass every other check here; and
#   * the pawn must actually have gone somewhere, or every check above is
#     satisfied by a player who never moved.
#
# What this does NOT catch, stated rather than implied: a query that is too
# permissive. It compares what the pawn did against what the query allows, so
# it fails when the query refuses something real -- and a query that allows a
# doorway the player cannot fit through would pass. That is the failure mode
# which actually strands a navigator, and covering it needs the follower from
# step 4: a bot that tries the routes it planned and reports the ones that did
# not work. Until then the protection is structural rather than tested: the
# step check samples the whole line through CheckPositionAt, which is the same
# code the pawn obeys, rather than judging the endpoints and assuming the
# middle.
#
# Usage: test_bot_traversal.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb python3; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-traversal.XXXXXX)
. "$here/xvfb_common.sh"

display=:183
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
maps=${MAPS:-"MAP53 MAP51 MAP60"}

walk() {  # walk MAP
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/cfg" --savedir "$work/saves" \
		--capture-rngseed 1 \
		--capture-traversal "$work/map.txt" \
		--capture-players "$work/players.txt" \
		--capture-maxtics 400 --capture-forward 20 --capture-turn 20 \
		--tedlevel "$1" --skill 2 --battle ) >"$work/run.log" 2>&1 || true
}

printf 'What the query believes, against where a pawn actually goes\n'
for map in $maps; do
	rm -f "$work/map.txt" "$work/players.txt"
	mkdir -p "$work/saves"
	walk "$map"

	if [ ! -s "$work/map.txt" ] || [ ! -s "$work/players.txt" ]; then
		printf '  FAIL %s: no traversal map or no player trace\n' "$map"
		sed 's/\x08//g' "$work/run.log" | grep -vE '^\s*$' | tail -4 |
			sed 's/^/         /'
		status=1
		continue
	fi

	if ! python3 - "$work" "$map" <<'PY'
import sys

work, mapname = sys.argv[1], sys.argv[2]

occupy, steps, radius = {}, {}, None
for line in open(work + "/map.txt"):
    if line.startswith("#"):
        if "radius" in line:
            radius = int(line.split("radius")[1].split()[0])
        continue
    f = [int(v) for v in line.split()]
    occupy[(f[0], f[1])] = f[2]
    steps[(f[0], f[1])] = (f[3], f[4], f[5], f[6])   # east north west south

# Where the pawn actually was, tic by tic, so consecutive entries are steps.
path = []
for line in open(work + "/players.txt"):
    if line.startswith("#"):
        continue
    f = line.split()
    if len(f) > 4 and f[1] == "0":
        path.append((int(f[2]), int(f[3])))

problems = []

# The body has to be the real one. Zero fits everywhere, including inside a
# wall, and would make every other check here vacuous.
if not radius:
    problems.append("the query was asked about a body with no width")
elif radius < 8 or radius > 40:
    problems.append("implausible body radius %d units" % radius)

visited = set(path)
if len(visited) < 5:
    problems.append("the pawn only reached %d tiles, which proves nothing"
                    % len(visited))
impossible = [t for t in visited if occupy.get(t, 0) != 1]
if impossible:
    problems.append("stood on %d tiles the query calls impossible: %s"
                    % (len(impossible), sorted(impossible)[:5]))

# Every step actually taken between adjacent tiles must have been allowed.
DIRS = {(1, 0): 0, (0, -1): 1, (-1, 0): 2, (0, 1): 3}
refused = []
for a, b in zip(path, path[1:]):
    if a == b:
        continue
    d = (b[0] - a[0], b[1] - a[1])
    if d not in DIRS:
        continue          # diagonal; not a four-neighbour edge
    if steps.get(a, (0, 0, 0, 0))[DIRS[d]] != 1:
        refused.append((a, b))
if refused:
    problems.append("took %d steps the query refuses, e.g. %s"
                    % (len(refused), refused[:3]))

# Crossing a gap is the same gap from either side.
asym = 0
for (x, y), (e, n, w, s) in steps.items():
    if e and steps.get((x + 1, y), (0, 0, 0, 0))[2] != 1:
        asym += 1
    if s and steps.get((x, y + 1), (0, 0, 0, 0))[1] != 1:
        asym += 1
if asym:
    problems.append("%d steps possible one way and not the other" % asym)

# And the map has to be a map: all-open or all-closed means the query is not
# looking at anything.
total = len(occupy)
open_cells = sum(occupy.values())
if open_cells == 0 or open_cells == total:
    problems.append("%d of %d cells standable, which is not a map"
                    % (open_cells, total))

if problems:
    print("  FAIL %s: %s" % (mapname, "; ".join(problems)))
    sys.exit(1)

print("  ok   %s: radius %d, %d of %d cells standable, %d tiles walked, "
      "every step allowed"
      % (mapname, radius, open_cells, total, len(visited)))
PY
	then
		status=1
	fi
done

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: the navigator asks the same code the pawn obeys.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
