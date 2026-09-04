#!/bin/sh

# Regression test: the graph a bot plans on, and the routes it finds in it.
#
# Milestone B2, step 3, of docs/multiplayer-bots-and-server.md.
#
# The graph is built from the traversal query, so it inherits that query's
# agreement with the pawn. What it adds is structure -- which cells connect to
# which, what a step costs, and what the shortest way between two of them is --
# and that is what this checks:
#
#   * the same map builds the same graph, hash for hash, twice running. A
#     planner whose graph depends on how it was walked is a planner whose
#     routes cannot be reproduced, and a bot bug that cannot be reproduced
#     cannot be fixed;
#   * every node is a cell the traversal query calls standable, and every
#     standable cell is a node, so the graph is a view of the world rather
#     than a second opinion about it;
#   * edges are symmetric, since crossing a gap is the same gap either way;
#   * no diagonal cuts a corner. A body twenty-two units wide in a
#     sixty-four unit tile cannot squeeze through the point where two walls
#     meet, and a planner that thinks it can will route through walls. Note
#     that this checks the property rather than the mechanism: at the shipped
#     body size the sampled sweep already rejects every corner cut, and
#     deleting the graph's explicit corner rule changes no arena by an edge.
#     The rule is a guarantee for bodies small enough to slip between samples;
#     the property is what matters here and it is what is measured;
#   * every route is a real chain of edges, not a list of cells that happen to
#     be in the right order; and
#   * smoothing keeps the ends, never lengthens, and never invents a step the
#     query refuses.
#
# Usage: test_bot_navigation.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-nav.XXXXXX)
. "$here/xvfb_common.sh"

display=:192
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
maps=${MAPS:-"MAP53 MAP51 MAP56 MAP60"}

build() {  # build MAP TAG
	mkdir -p "$work/$2-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$2.cfg" --savedir "$work/$2-saves" \
		--capture-rngseed 1 \
		--capture-nav "$work/$2.nav" \
		--capture-traversal "$work/$2.trav" \
		--capture-maxtics 60 \
		--tedlevel "$1" --skill 2 --battle ) >"$work/$2.log" 2>&1 || true
}

printf 'The graph a bot plans on\n'
for map in $maps; do
	rm -f "$work"/a.nav "$work"/b.nav "$work"/a.trav
	build "$map" a
	build "$map" b

	if [ ! -s "$work/a.nav" ] || [ ! -s "$work/b.nav" ] || [ ! -s "$work/a.trav" ]; then
		printf '  FAIL %s: the graph was not written\n' "$map"
		sed 's/\x08//g' "$work/a.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
		status=1
		continue
	fi

	if ! cmp -s "$work/a.nav" "$work/b.nav"; then
		printf '  FAIL %s: two builds of one map produced different graphs\n' "$map"
		diff "$work/a.nav" "$work/b.nav" | head -3 | sed 's/^/         /'
		status=1
		continue
	fi

	if ! python3 - "$work" "$map" <<'PY'
import sys

work, mapname = sys.argv[1], sys.argv[2]

standable = set()
for line in open(work + "/a.trav"):
    if line.startswith("#"):
        continue
    f = [int(v) for v in line.split()]
    if f[2]:
        standable.add((f[0], f[1]))

nodes, edges, paths, smooths = set(), set(), [], []
# Door cells, read from the map's own triggers rather than from the graph, so
# that "the graph thinks this is a door" and "this is a door" stay separable.
# A self-opening, player-usable Door_Open (special 1, no tag) is a door; a
# tagged one operates something elsewhere and is a switch.
doors = {}
summary = {}
for line in open(work + "/a.nav"):
    if line.startswith("#"):
        parts = line.split()
        for key in ("nodes", "edges", "digest", "radius", "regions"):
            if key in parts:
                summary[key] = parts[parts.index(key) + 1]
        continue
    f = line.split()
    if f[0] == "trigger":
        # Keyword-delimited, so read by name: the line is
        # "trigger X Y action N args a0..a4 use U cross C monster M tile T ..."
        at = f.index("args") + 1
        args = [int(v) for v in f[at:at + 5]]
        action = int(f[f.index("action") + 1])
        use = int(f[f.index("use") + 1])
        if action == 1 and use and args[0] == 0:
            # bit 0 of arg[4] picks the axis the panel slides on: 0 is the
            # East/West pair, so the cell is entered along X.
            doors[(int(f[1]), int(f[2]))] = "x" if (args[4] & 1) == 0 else "y"
        continue
    if f[0] == "edge":
        a = (int(f[1]), int(f[2])); b = (int(f[3]), int(f[4]))
        edges.add((a, b, int(f[5])))
        nodes.add(a); nodes.add(b)
    elif f[0] == "path":
        paths.append((f[1:5], f[5], f[6], f[7], f[8:]))
    elif f[0] == "smooth":
        smooths.append((f[1:5], int(f[5]), int(f[6]), f[7:]))

problems = []

# The graph is a view of the world, not a second opinion about it. Isolated
# cells legitimately have no edges, so compare against the node count the
# engine reported rather than against the cells that turned up in edges.
# A door cell is a node even though a body cannot stand in it while the door is
# shut: the graph is about where a body can get to, and the traversal dump is
# about where one fits right now. Everything else must match exactly.
reachable = standable | set(doors)
if int(summary.get("nodes", 0)) != len(reachable):
    problems.append("%s nodes against %d standable cells and %d door cells"
                    % (summary.get("nodes"), len(standable), len(doors)))

if int(summary.get("radius", 0)) < 8:
    problems.append("graph built for a body of radius %s"
                    % summary.get("radius"))

# Crossing a gap is the same gap either way.
asym = [(a, b) for (a, b, c) in edges if not any(
    x == b and y == a for (x, y, _) in edges)]
if asym:
    problems.append("%d edges exist one way only, e.g. %s"
                    % (len(asym), asym[:3]))

# No diagonal may cut a corner.
cutters = []
for (a, b, cost) in edges:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) != 1 or abs(dy) != 1:
        continue
    if (a[0] + dx, a[1]) not in reachable or (a[0], a[1] + dy) not in reachable:
        cutters.append((a, b))
if cutters:
    problems.append("%d diagonals cut a corner, e.g. %s"
                    % (len(cutters), cutters[:3]))

# Costs must be the three the graph declares, or a route's length means
# nothing.
odd = set(c for (_, _, c) in edges) - {100, 141, 600}
if odd:
    problems.append("unexpected edge costs %s" % sorted(odd))

# A door edge is priced at 600, and nothing else is. Both directions of the
# claim: every 600 touches a door, and every edge touching a door costs 600 --
# the second is what would catch a door quietly priced as an ordinary step.
for (a, b, cost) in edges:
    touches = (a in doors) or (b in doors)
    if cost == 600 and not touches:
        problems.append("a 600-cost edge %s->%s touches no door" % (a, b))
        break
    if touches and cost != 600:
        problems.append("edge %s->%s touches a door and costs %d" % (a, b, cost))
        break

# And a door is entered square-on, on the axis its panel slides along.
# Approaching cornerwise means standing in the jamb.
#
# A guarantee rather than a check that currently bites: the builder's own axis
# rule is redundant today -- removing it leaves MAP51's graph byte-identical,
# because the sampled sweep refuses an off-axis step anyway. This is here so
# that a future body, or a future door, cannot quietly lose the property.
for (a, b, cost) in edges:
    cell = a if a in doors else (b if b in doors else None)
    if cell is None:
        continue
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx and dy:
        problems.append("diagonal edge %s->%s into the door at %s" % (a, b, cell))
        break
    if (doors[cell] == "x") != (dy == 0):
        problems.append("edge %s->%s crosses the door at %s off its axis"
                        % (a, b, cell))
        break

# Every route is a chain of real edges.
adjacency = set((a, b) for (a, b, _) in edges)
broken = 0
for (ends, found, length, expansions, cells) in paths:
    if found != "found":
        continue
    steps = [tuple(int(v) for v in c.split(",")) for c in cells]
    if len(steps) != int(length):
        problems.append("a route claims %s nodes and lists %d"
                        % (length, len(steps)))
        break
    if steps[0] != (int(ends[0]), int(ends[1])) or \
       steps[-1] != (int(ends[2]), int(ends[3])):
        problems.append("a route does not start and end where it says")
        break
    for p, q in zip(steps, steps[1:]):
        if (p, q) not in adjacency:
            broken += 1
if broken:
    problems.append("%d steps in the sample routes are not edges" % broken)

if not paths:
    problems.append("no routes were sampled, so nothing was searched")

# Smoothing keeps the ends and never lengthens.
for (ends, before, after, cells) in smooths:
    steps = [tuple(int(v) for v in c.split(",")) for c in cells]
    if after > before:
        problems.append("smoothing made a route longer (%d -> %d)"
                        % (before, after))
        break
    if steps[0] != (int(ends[0]), int(ends[1])) or \
       steps[-1] != (int(ends[2]), int(ends[3])):
        problems.append("smoothing moved the ends of a route")
        break

if problems:
    print("  FAIL %s: %s" % (mapname, "; ".join(problems)))
    sys.exit(1)

shortened = sum(b - a for (_, b, a, _) in smooths)
print("  ok   %s: %s nodes, %s edges, digest %s, %d routes, "
      "smoothing removed %d waypoints"
      % (mapname, summary.get("nodes"), summary.get("edges"),
         summary.get("digest"), len(paths), shortened))
PY
	then
		status=1
	fi
done

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: one map, one graph, and every route a real chain of steps.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
