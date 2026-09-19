#!/bin/sh

# Regression test: what may end a deathmatch round, and where the next one is.
#
# Three rules, each of which a playtest asked for:
#
# 1. The elevator does not end a battle. Seven of the eight arenas are built
#    from campaign floors and kept their elevator switch, and pressing it
#    ended the round for everybody -- a draw any player could call at any
#    moment, including the one losing. Only the frag and time limits end a
#    round now. The same press in single player must still work, or the fix
#    has broken the campaign rather than closed a loophole.
#
# 2. A time limit ends a round on the level clock, with or without frags.
#
# 3. With map cycling on, the next round is the next arena in number order,
#    wrapping after the last. Every arena's MAPINFO `next` names itself, so
#    without the setting the same arena comes round again -- which must also
#    still be true.
#
# Every condition is forced rather than waited for: an idle player and one
# bot, no frag limit, so nothing but the time limit can end a round, and the
# elevator is pressed from a fixed spot rather than walked to. MAP57 is the
# starting arena for the cycle because the arena after it is MAP60, not MAP58:
# the compendium's 58 and 59 are empty boxes, and a cycle that counted by one
# would load one. Two rounds from there also reach the wrap back to MAP51.
#
# And all of it has to hold over the network with only the host told the
# settings, since the start packet is the only way a client learns them.
#
# Usage: test_multiplayer_match_rules.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-matchrules.XXXXXX)
. "$here/xvfb_common.sh"
display=:237
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${net_pid0:-}" "${net_pid1:-}"
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

game() {  # game TAG MAP [EXTRA...]
	tag=$1; map=$2; shift 2
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 400 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed 1 --tedlevel "$map" --skill 2 "$@" ) \
		>"$work/$tag.log" 2>&1 || true
}

count() {  # count PATTERN FILE
	grep -c "$1" "$2" 2>/dev/null || true
}

# The maps each new round began on, in order.
round_maps() {
	sed -n 's/^Round [0-9]* begins:.* map=\(MAP[0-9]*\)$/\1/p' "$1" | tr '\n' ' ' |
		sed 's/ $//'
}

# --- 1. the elevator ----------------------------------------------------------

printf 'The elevator does not end a battle\n'

# MAP51's switch is wall 63 at (47,60); standing east of it facing west puts
# it in front of the player. The single-player run is the control: the same
# press on the same spot, which must still leave the floor.
game lift-battle MAP51 --battle --bots 1 \
	--capture-place 10 48.5 60.5 180 --capture-use 20 6 --capture-maxtics 300
game lift-single MAP51 \
	--capture-place 10 48.5 60.5 180 --capture-use 20 6 --capture-maxtics 300

battle_loads=$(count '^MAP51 - ' "$work/lift-battle.log")
battle_rounds=$(count '^Round [0-9]* begins' "$work/lift-battle.log")
single_loads=$(count '^MAP51 - ' "$work/lift-single.log")
printf '  ..   battle: MAP51 loaded %s time(s), %s new round(s)\n' \
	"$battle_loads" "$battle_rounds"
printf '  ..   single player: MAP51 loaded %s time(s)\n' "$single_loads"

check "pressing the elevator in a battle ends nothing" \
	test "${battle_loads:-0}" -eq 1 -a "${battle_rounds:-0}" -eq 0
check "and the same press in single player still leaves the floor" \
	test "${single_loads:-0}" -ge 2

# --- 2 and 3. the time limit, and the cycle -----------------------------------

printf '\nA time limit ends the round, and the next arena follows\n'

# One minute is 4200 tics. Two rounds and a little over.
game cycle MAP57 --battle --bots 1 --timelimit 1 --mapcycle --capture-maxtics 8700
game stay  MAP51 --battle --bots 1 --timelimit 1 --capture-maxtics 4500

limits=$(count 'The time limit was reached' "$work/cycle.log")
cycle_maps=$(round_maps "$work/cycle.log")
stay_maps=$(round_maps "$work/stay.log")
printf '  ..   cycling from MAP57: %s time limit(s), rounds began on: %s\n' \
	"$limits" "${cycle_maps:-nothing}"
printf '  ..   not cycling from MAP51: rounds began on: %s\n' "${stay_maps:-nothing}"

check "the time limit ends a round with nobody near the frag limit" \
	test "${limits:-0}" -ge 2
check "cycling goes from MAP57 to MAP60, past the two empty maps" \
	test "$(printf '%s\n' "$cycle_maps" | cut -d' ' -f1)" = "MAP60"
check "and wraps from the last arena back to MAP51" \
	test "$(printf '%s\n' "$cycle_maps" | cut -d' ' -f2)" = "MAP51"
check "without cycling, the same arena comes round again" \
	test "$stay_maps" = "MAP51"
check "and the round that follows starts clean" \
	sh -c "! grep '^Round [0-9]* begins' '$work/cycle.log' | grep -qv ':frags=0,health=100,weapons=2 1:frags=0,health=100,weapons=2 map='"

# --- 4. over the network --------------------------------------------------------

printf '\nThe host decides, and the client plays the same match\n'

# The two settings travel in the start packet. A client that did not receive
# them would carry on past the host's time limit, or load a different arena,
# and the two machines would be simulating different matches. So only the host
# is told either setting here, and the client has to end up in step anyway.
net_pid0=; net_pid1=
net() {  # net N ROLE [EXTRA...]
	n=$1; role=$2; shift 2
	mkdir -p "$work/net-$n-saves"
	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  exec timeout 400 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/net-$n.cfg" --savedir "$work/net-$n-saves" \
		--capture-rngseed 1 --tedlevel MAP57 --skill 2 --battle --net-delay 6 \
		--capture-players "$work/net-$n.tr" --capture-maxtics 4500 \
		$role "$@" ) >"$work/net-$n.log" 2>&1 &
}
net 0 "--host 2 --port 5171" --timelimit 1 --mapcycle
net_pid0=$!
sleep 3
net 1 "--port 5172 --join 127.0.0.1:5171"
net_pid1=$!
wait "$net_pid0" "$net_pid1" 2>/dev/null || true

host_limits=$(count 'The time limit was reached' "$work/net-0.log")
client_limits=$(count 'The time limit was reached' "$work/net-1.log")
host_maps=$(round_maps "$work/net-0.log")
client_maps=$(round_maps "$work/net-1.log")
printf '  ..   host: %s time limit(s), next round on %s\n' \
	"$host_limits" "${host_maps:-nothing}"
printf '  ..   client: %s time limit(s), next round on %s\n' \
	"$client_limits" "${client_maps:-nothing}"

check "the client reaches the host's time limit without being told it" \
	test "${client_limits:-0}" -ge 1 -a "${host_limits:-0}" -ge 1
check "and both machines move to the same next arena" \
	test "$host_maps" = "MAP60" -a "$client_maps" = "MAP60"
# Non-empty first: two traces that were never written compare equal too.
check "and the two machines recorded the same match, tic for tic" \
	sh -c "test -s '$work/net-0.tr' && test \$(wc -l < '$work/net-0.tr') -gt 4000 && cmp -s '$work/net-0.tr' '$work/net-1.tr'"

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: only the limits end a round, and the map cycles when asked.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
