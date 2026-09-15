#!/bin/sh

# Regression test: a new deathmatch round starts clean, and bots wear what the
# host chose for them.
#
# The frag limit gate only ever checked that a limit *ends* a match. Nothing
# checked what the next round looked like, and it looked like the last one:
# the round end was handled as a single-player floor exit, which carries every
# player on to the next map with their weapons, their frag count and -- for
# whoever the final frag killed -- their corpse. The first kill of round two
# ended round two.
#
# Measured against the old behaviour before this was trusted, so it is known
# to catch it: that build started round two with a slot on one frag, a slot
# holding four weapons, and a slot on -30 health.
#
# Usage: test_multiplayer_rounds.sh BUILD_DIR DATA_DIR

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

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-rounds.XXXXXX)
. "$here/xvfb_common.sh"
display=:219
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

game() {  # game TAG [EXTRA...]
	tag=$1; shift
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed 1 \
		--tedlevel MAP60 --skill 2 --battle "$@" ) >"$work/$tag.log" 2>&1 || true
}

# --- rounds ------------------------------------------------------------------

printf 'A new round starts clean\n'

# A frag limit of one, so rounds come quickly, and a plasma rifle handed to
# every slot once at the start: if it is still held when round two begins, the
# inventory travelled.
game rounds --bots 3 --fraglimit 1 --capture-give-all C7PlasmaRifle \
	--capture-maxtics 2600

ends=$(grep -c 'reached the frag limit' "$work/rounds.log" || true)
begins=$(grep -c '^Round [0-9]* begins:' "$work/rounds.log" || true)
printf '  ..   %s round end(s), %s new round(s) begun\n' "$ends" "$begins"
grep '^Round [0-9]* begins:' "$work/rounds.log" | head -2 | sed 's/^/  ..   /'

check "a frag limit ends a round" test "${ends:-0}" -ge 1
check "and another round begins after it" test "${begins:-0}" -ge 1

python3 - "$work/rounds.log" <<'PY'
import re, sys

problems, rounds = [], 0
for line in open(sys.argv[1], errors="replace"):
    if not re.match(r"Round \d+ begins:", line):
        continue
    rounds += 1
    slots = re.findall(r"(\d+):frags=(-?\d+),health=(-?\d+),weapons=(\d+)", line)
    for slot, frags, health, weapons in slots:
        if int(frags) != 0:
            problems.append("slot %s started a round on %s frags" % (slot, frags))
        if int(health) <= 0:
            problems.append("slot %s started a round dead (%s health)" % (slot, health))
        # A marine's starting kit is the bayonet and the M16. The plasma rifle
        # everyone was given at the start of the match must not still be here.
        if int(weapons) != 2:
            problems.append("slot %s started a round holding %s weapons" % (slot, weapons))
if rounds == 0:
    problems.append("no round began, so nothing was checked")
for p in problems[:6]:
    print("  FAIL %s" % p)
sys.exit(1 if problems else 0)
PY
if [ $? -eq 0 ]; then
	printf '  ok   every slot began every new round on no frags, alive, with the starting kit\n'
else
	status=1
fi

# --- bot appearance ----------------------------------------------------------

printf '\nBots wear what the host chose\n'

classes() {  # classes TAG -> "slot=class ..." at tic 60
	awk 'NR>1 && $1==60 {printf "%s=%s ", $2, $10}' "$work/$1.players"
}

game copy --bots 2 --capture-players "$work/copy.players" --capture-maxtics 80
game gold --bots 2 --bot-class C7PlayerGold \
	--capture-players "$work/gold.players" --capture-maxtics 80
game bogus --bots 2 --bot-class NotAClass \
	--capture-players "$work/bogus.players" --capture-maxtics 80

printf '  ..   unchosen: %s\n' "$(classes copy)"
printf '  ..   gold:     %s\n' "$(classes gold)"
check "with nothing chosen, bots copy the host" \
	test "$(classes copy)" = "0=C7Player 1=C7Player 2=C7Player "
check "a chosen uniform goes on every bot and not on the host" \
	test "$(classes gold)" = "0=C7Player 1=C7PlayerGold 2=C7PlayerGold "
check "a name that is not a player class says so" \
	grep -q "'NotAClass' is not a player class" "$work/bogus.log"
check "and falls back to the host's character" \
	test "$(classes bogus)" = "0=C7Player 1=C7Player 2=C7Player "

# Both machines, because a client used to be told only the classes of the
# peers: every bot slot on its side was filled with the host's character, so
# the host saw gold marines and the client saw copies of the host.
mkdir -p "$work/h-saves" "$work/c-saves"
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
	--config "$work/h.cfg" --savedir "$work/h-saves" --capture-rngseed 1 \
	--capture-players "$work/h.players" --capture-maxtics 200 \
	--tedlevel MAP60 --skill 2 --battle --net-delay 6 \
	--host 2 --port 5321 --bots 2 --bot-class C7PlayerGold ) >"$work/h.log" 2>&1 &
host_pid=$!
sleep 3
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
	--config "$work/c.cfg" --savedir "$work/c-saves" --capture-rngseed 1 \
	--capture-players "$work/c.players" --capture-maxtics 200 \
	--tedlevel MAP60 --skill 2 --battle --net-delay 6 \
	--port 5322 --join 127.0.0.1:5321 ) >"$work/c.log" 2>&1 &
client_pid=$!
wait "$host_pid" "$client_pid" 2>/dev/null || true

printf '  ..   host:   %s\n' "$(classes h)"
printf '  ..   client: %s\n' "$(classes c)"
check "the host dresses its bots as chosen" \
	test "$(classes h)" = "0=C7Player 1=C7Player 2=C7PlayerGold 3=C7PlayerGold "
check "and the client sees the same bots" test "$(classes c)" = "$(classes h)"

if [ "$status" -eq 0 ]; then
	printf 'PASS: rounds start clean, and bots dress as they are told.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
