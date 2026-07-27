#!/bin/sh

# Regression test: Corridor 7's aliens patrol, and the ones placed as sentries
# do not.
#
# The maps carry hand-authored patrol routes as turning-point markers, and the
# translator used to discard all of them. The failure was invisible from a
# screenshot and almost invisible in play: a patrolling alien walks in its spawn
# direction until something blocks it, and then SelectPathDir sets dir = nodir
# and A_Chase stops on that, permanently. The result looks exactly like a
# stationary sentry that ignores the player, so the bug reads as "the AI is
# generic" rather than as a broken route.
#
# Both halves are asserted, because either alone passes for the wrong reason:
#
#   * a patrol-placed alien is still moving at the end of the run and never
#     reaches nodir. Distance alone is not enough -- the broken build also
#     covered ten tiles before it wedged, it just never turned.
#
#   * a stand-placed alien has not moved. If patrols were "fixed" by making
#     everything wander, the sentries the maps deliberately place would move
#     too, and the floor would play completely differently.
#
# MAP01 is used because it is the floor the discrepancy was first reported on:
# its elevator corridor holds a probe whose route runs south and then turns west
# along row 41, and in the broken build it sat at the south end of that corridor
# for the rest of the level.
#
# Usage: test_corridor7_ai.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi

for command in xvfb-run python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-ai.XXXXXX)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT INT TERM

# The game is run from a directory holding the build's OWN pk3. ECWolf resolves
# ec7wolf.pk3 from the working directory first, so running the fresh binary with
# the data directory as cwd silently tests whatever pk3 was last installed
# there -- and every part of this test lives in the pk3 (the translator entry
# that spawns the turning points). This has produced false passes before.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$work/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && ln -s "$f" "$work/" || true
done

# Long enough for the MAP01 probe to walk the nine tiles to its first turning
# point (about 1150 tics) and then keep going well past it.
(
	cd "$work"
	timeout 600s env SDL_AUDIODRIVER=dummy \
		xvfb-run -a -s "-screen 0 640x400x24" ./ec7wolf \
		--data CO7 --nowait --vid-renderer software --res 640 400 \
		--config "$work/cfg" --savedir "$work/sv" \
		--tedlevel MAP01 --skill 2 --capture-rngseed 12345 \
		--capture-actors "$work/trace.txt" --capture-maxtics 2600
) >"$work/run.log" 2>&1 || true

if [ ! -s "$work/trace.txt" ]; then
	printf 'FAIL: no actor trace was produced; see %s/run.log\n' "$work" >&2
	exit 1
fi

python3 - "$work/trace.txt" <<'PY'
import sys
from collections import defaultdict

tics = defaultdict(list)
for line in open(sys.argv[1]):
    if line.startswith("#"):
        continue
    p = line.split()
    tics[int(p[0])].append(p[1:])

if not tics:
    print("FAIL: the trace has no tics in it")
    sys.exit(1)

order = sorted(tics)
count = len(tics[order[0]])
# Actors are emitted in a stable iteration order, so a row index is one actor
# for as long as the population is unchanged. Tics where something died or
# spawned are skipped rather than guessed at.
tracks = [[] for _ in range(count)]
for t in order:
    row = tics[t]
    if len(row) != count:
        continue
    for i, r in enumerate(row):
        tracks[i].append((t, r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4])))

NODIR = 8
ok = True
patrols = stands = 0

for tr in tracks:
    name = tr[0][1]
    pathing = tr[0][5]
    tiles = {(x, y) for _, _, x, y, _, _ in tr}
    wedged = [t for t, _, _, _, d, _ in tr if d == NODIR]

    if pathing:
        patrols += 1
        if wedged:
            print("FAIL: patrolling %s reached nodir at tic %d and stopped -- "
                  "it ran out of route, which is what a missing turning point "
                  "looks like" % (name, wedged[0]))
            ok = False
        elif len(tiles) < 4:
            print("FAIL: patrolling %s only ever occupied %d tile(s); it is "
                  "not walking its route" % (name, len(tiles)))
            ok = False
        else:
            print("patrol  %-12s covered %2d tiles, never wedged" % (name, len(tiles)))
    else:
        stands += 1
        if len(tiles) > 1:
            print("FAIL: stand-placed %s wandered across %d tiles; sentries are "
                  "placed deliberately and must hold their post" % (name, len(tiles)))
            ok = False
        else:
            print("sentry  %-12s held its post" % name)

if patrols == 0:
    print("FAIL: the trace contains no patrolling alien at all, so the patrol "
          "half of this test proved nothing. Either the map changed or PATHING "
          "stopped reaching actors.")
    ok = False
if stands == 0:
    print("FAIL: the trace contains no stand-placed alien, so the sentry half "
          "of this test proved nothing.")
    ok = False

sys.exit(0 if ok else 1)
PY

printf 'PASS: patrol routes are walked and sentries hold their posts\n'

# ---------------------------------------------------------------------------
# Part two: a disguised Bandor is furniture until the player is close to it.
#
# The disguise is the whole actor. If it unfolds because a firefight happened
# somewhere else on the floor, the player never meets it disguised, and an alien
# that spends the game pretending to be a filing cabinet becomes an alien that
# stands in the open. So the assertion is a pair, on one map: an alien three
# tiles away wakes, an identical one twelve tiles away does not -- while the
# near one is shooting, which is what makes the distant one's silence mean
# something. A build with no range limit wakes both at the same tic.
#
# Built as a bare corridor rather than taken from a released floor, because on a
# real map the nearest cover, door or second alien would decide the outcome
# instead of the range.
# ---------------------------------------------------------------------------

lab="$work/lab"
mkdir -p "$lab"
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done

# Written into the lab's OWN copy. Never hand this a path in the data directory:
# it writes a whole archive, and the released maps are not replaceable.
python3 "$(dirname "$0")/make_corridor7_ai_lab.py" \
	"$data_dir/MAPTEMP.CO7" "$lab/MAPTEMP.CO7" 118:7 128:16 >/dev/null

(
	cd "$lab"
	timeout 600s env SDL_AUDIODRIVER=dummy \
		xvfb-run -a -s "-screen 0 640x400x24" ./ec7wolf \
		--data CO7 --nowait --vid-renderer software --res 640 400 \
		--config "$work/labcfg" --savedir "$work/labsv" \
		--tedlevel MAP01 --skill 2 --capture-rngseed 12345 \
		--capture-actors "$work/lab.txt" --capture-maxtics 500
) >"$work/lab.log" 2>&1 || true

if [ ! -s "$work/lab.txt" ]; then
	printf 'FAIL: the ambush lab produced no actor trace; see %s/lab.log\n' "$work" >&2
	exit 1
fi

python3 - "$work/lab.txt" <<'PY'
import sys

near_woke = far_woke = False
seen_near = seen_far = False
for line in open(sys.argv[1]):
    if line.startswith("#"):
        continue
    _, name, _, _, _, _, attack, _ = line.split()
    if name == "C7ProbeEye":
        seen_near = True
        near_woke |= attack == "1"
    elif name == "C7MorphChair":
        seen_far = True
        far_woke |= attack == "1"

ok = True
if not seen_near or not seen_far:
    print("FAIL: the lab did not contain both aliens, so nothing was compared")
    ok = False
elif not near_woke:
    print("FAIL: the near alien never engaged, so no noise was made and the "
          "distant Bandor was never actually tested")
    ok = False
elif far_woke:
    print("FAIL: the Bandor twelve tiles away unfolded anyway. Its disguise is "
          "supposed to survive a firefight happening elsewhere on the floor.")
    ok = False
else:
    print("ambush  near alien engaged; Bandor 12 tiles away stayed furniture")

sys.exit(0 if ok else 1)
PY

printf 'PASS: a distant Bandor keeps its disguise through a firefight elsewhere\n'
