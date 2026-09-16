#!/bin/sh

# Regression test: bots lay mines, pay for them, and do not blow themselves up.
#
# Milestone B7 of docs/multiplayer-bots-and-server.md, section 16.7.
#
# The engine's rules, read from the code rather than assumed. Dropping a mine
# costs one C7Mines and spawns a C7ProximityMine 40/64 of a tile ahead. It
# spends 36 tics arming. It stays inert while its *owner* is within half a
# tile and goes live for everybody -- owner included -- once they step away.
# Anything shootable within half a tile sets it off: 102 to 500 damage at a
# radius of 128 units, which is two tiles.
#
# Placement comes from the graph, not from anybody's movements: a cell with
# three or fewer ways out is a corridor or a doorway, which is map knowledge a
# player who has learned an arena also has. Section 16.7 forbids choosing
# placement from hidden enemy paths, and nothing here looks at where anyone has
# been.
#
# What keeps a bot from killing itself is mostly the engine's owner-clearance
# rule rather than anything clever here: a bot that places a mine and stays put
# never arms it. The bot's own avoidance is a route cost, which reduces
# revisits without forbidding them -- and a mine at a choke point is often on
# the only way through, which is a real tension rather than a bug.
#
# Usage: test_bot_mines.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

printf 'Mines, laid and paid for\n'

# Nothing may spawn a mine, set the count, or arm one directly. Section 16.7:
# the drop button is the only way in, and the engine owns everything after it.
banned='(Spawn\(.*Mine|C7ProximityMine|C7Mines[^"]*->amount *=|temp1 *=)'
code() { sed 's;//.*;;' "$@" | grep -vE '^\s*\*'; }
forced=$(code "$here/../src/g_bot.cpp" "$here/../src/g_combat.cpp" 2>/dev/null |
	grep -cE "$banned" || true)
if [ "${forced:-0}" -ne 0 ]; then
	code "$here/../src/g_bot.cpp" "$here/../src/g_combat.cpp" |
		grep -nE "$banned" | head -3 | sed 's/^/         /'
fi
check "the brain drops mines with the drop button and nothing else" \
	test "${forced:-0}" -eq 0

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-mines.XXXXXX)
. "$here/xvfb_common.sh"
display=:202
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

run() {  # run SEED TAG
	mkdir -p "$work/$2-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$2.cfg" --savedir "$work/$2-saves" \
		--capture-rngseed "$1" \
		--capture-give-all C7MinePack \
		--capture-bots "$work/$2.bots" \
		--capture-players "$work/$2.players" \
		--capture-nav "$work/$2.nav" \
		--capture-maxtics 2100 \
		--tedlevel MAP60 --skill 2 --battle --bots 3 ) >"$work/$2.log" 2>&1 || true
}

placed_total=0
caught_total=0
for seed in 1 5; do
	tag="s$seed"
	run "$seed" "$tag"
	placed=$(sed -n 's/.*Capture: bots .*mines=\([0-9]*\).*/\1/p' "$work/$tag.log" | tail -1)
	placed_total=$((placed_total + ${placed:-0}))
	caught=$(awk '$3=="blast" && $4=="by=C7ProximityMine" && $5=="own=0"' \
		"$work/$tag.bots" | wc -l)
	caught_total=$((caught_total + caught))
	printf '  ..   seed %s: %s mines laid\n' "$seed" "${placed:-0}"

	python3 - "$work/$tag.bots" "$work/$tag.players" "$work/$tag.nav" "$seed" <<'PY'
import sys
trace, players, nav, seed = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

mines, problems = [], []
for line in open(trace):
    f = line.split()
    if len(f) > 3 and f[2] == "mine":
        x, y = f[3].replace("at=", "").split(",")
        left = int(f[4].replace("left=", ""))
        mines.append((int(f[0]), f[1], int(x), int(y), left))

# Ammunition is spent, one per mine, and the engine is what spends it.
counts = {}
for tic, slot, x, y, left in mines:
    if slot in counts and left != counts[slot] - 1:
        problems.append("slot %s went from %d mines to %d, not one fewer"
                        % (slot, counts[slot], left))
        break
    counts[slot] = left

# Placement is a choke point: three or fewer ways out, from the graph.
degree = {}
for line in open(nav):
    f = line.split()
    if f and f[0] == "edge":
        a = (int(f[1]), int(f[2]))
        degree[a] = degree.get(a, 0) + 1
open_floor = [(x, y) for _, _, x, y, _ in mines if degree.get((x, y), 0) > 3]
if open_floor:
    problems.append("%d mines laid in open floor, e.g. %s (%d ways out)"
                    % (len(open_floor), open_floor[0], degree.get(open_floor[0], 0)))

# And nobody blew themselves up.
#
# Asked of the engine rather than inferred from position. A_Explode has one
# branch that knows a blast reached whoever set it off -- it has to, to stop
# the friendly-fire guard discarding the damage -- and that branch says so.
#
# This was a proximity test: a health drop of 50 or more within two tiles of a
# mine you had laid. It read a bot killed by a rocket at range 14 as a
# self-blast, because it happened to have laid a mine two tiles away 143 tics
# earlier. Mines are +SHOOTABLE, so anyone's stray shot can set one off too,
# and position cannot tell any of these apart.
# Mines only. The engine reports every blast that hurts whoever set it off,
# and a bot that splashes itself with its own plasma bolt reaches the same
# branch -- which is what this check spent three rounds blaming on mines.
selfhits, ownsplash, minehits = 0, 0, 0
for line in open(trace):
    f = line.split()
    if len(f) < 5 or f[2] != "blast":
        continue
    mine = f[3] == "by=C7ProximityMine"
    own = f[4] == "own=1"
    if mine and own:
        selfhits += 1
    elif mine:
        minehits += 1
    elif own:
        ownsplash += 1

print("  ..   seed %s: %d mines, %d in open floor, %d self-blasts, "
      "%d own-projectile splashes, %d opponents caught"
      % (seed, len(mines), len(open_floor), selfhits, ownsplash, minehits))
if selfhits:
    problems.append("%d bots were hurt by their own mines" % selfhits)
if problems:
    for p in problems:
        print("  FAIL seed %s: %s" % (seed, p))
    sys.exit(1)
print("  ok   seed %s: laid at choke points, paid for, and nobody self-blasted" % seed)
PY
	[ $? -eq 0 ] || status=1
done

check "mines were actually laid" test "$placed_total" -ge 2

# Opponent damage, arranged rather than waited for.
#
# This was pooled across the two matches above and that was still luck: it
# passed with one catch per seed, then a change to where bots stand left both
# matches with mines laid, nobody walking over them, and a check reporting that
# mines do not work. Whether a bot crosses a mine another bot happened to leave
# is the arrangement of one afternoon's wandering.
#
# So the mine is placed on a known tile, owned by the idle local player so that
# every bot is a stranger to it, and a bot is sent to that tile. What is
# being checked is that the engine wires a mine's trigger and blast to somebody
# who is not its owner -- section 16.7's "opponent damage" -- and that is a
# fact about the game rather than about the seed.
#
# One bot, and the local player killed before it can be seen. Both are here
# because a forced goal is only forced while nothing more interesting turns up:
# somebody to shoot at takes precedence over somewhere to go, which is the
# right order and is why the bot has to be alone to be led anywhere. This run
# used to have two bots and a live idle player, and it worked only because a
# bot in earshot of a firefight froze for sixty tics at a time without ever
# reaching the code that picks a target. Fixing that deafness left both bots
# fighting each other halfway to the mine and the check reporting that mines
# do not work -- the scenario had been relying on the bug. Measured: with two
# bots and a live player the goal is abandoned at tic 417 and the mine is
# never reached; alone, the bot walks onto it at tic 538.
printf '  ..   opponents caught by mines while wandering: %s\n' "$caught_total"

mkdir -p "$work/lure-saves"
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 200 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
	--vid-renderer software \
	--config "$work/lure.cfg" --savedir "$work/lure-saves" \
	--capture-rngseed 1 --bots 1 \
	--capture-mine-at 30 12 60 --capture-bot-goal 30 12 \
	--capture-kill-slot 0 40 \
	--capture-bots "$work/lure.bots" \
	--capture-maxtics 1600 \
	--tedlevel MAP60 --skill 2 --battle ) >"$work/lure.log" 2>&1 || true

placed=$(grep -c 'mine placed at 30,12' "$work/lure.log" || true)
lured=$(awk '$3=="blast" && $4=="by=C7ProximityMine" && $5=="own=0"' \
	"$work/lure.bots" | wc -l)
printf '  ..   a mine left on a tile a bot is sent to: placed %s, caught %s\n' \
	"$placed" "$lured"
check "the mine was actually placed" test "${placed:-0}" -ge 1
check "a mine is a weapon and not just an expense" test "${lured:-0}" -ge 1

if [ "$status" -eq 0 ]; then
	printf 'PASS: bots mine chokepoints without mining themselves.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
