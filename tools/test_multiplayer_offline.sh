#!/bin/sh

# Regression test: a deathmatch with nobody on the other end of a wire.
#
# Milestone S3 of docs/multiplayer-bots-and-server.md.
#
# Every rule that made a game a deathmatch used to be spelled "is
# Net::InitVars.mode something other than MODE_SinglePlayer" -- whether a
# picked-up weapon stays for somebody else, whether dying puts you back in the
# arena or restarts the level, whether there is a fade, whether sound falls off
# with distance, whether the scoreboard exists. That is a question about
# sockets, and it answers wrongly in both directions the moment there is
# anything but one human per process: an offline match against bots has
# opponents and no socket, and a host sitting alone has a socket and no
# opponent.
#
# So this starts a deathmatch with no network at all and checks that the game
# agrees it is one:
#
#   * it reaches gameplay on a real arena and simulates;
#   * it opens no internet socket whatsoever, proven by strace rather than by
#     the absence of a log line; and
#   * deathmatch rules apply -- a campaign level full of aliens spawns none of
#     them under --battle, and does spawn them without it.
#
# The rules that need a second player to observe -- respawning in place rather
# than restarting, an item left behind for whoever else wants it -- are checked
# as predicates by test_multiplayer_session.sh, and become observable in S4
# when there is a second pawn to kill.
#
# Usage: test_multiplayer_offline.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-offline.XXXXXX)
. "$here/xvfb_common.sh"

display=:173
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

tics=200

# Traced when strace can trace: a log line saying nothing about networking is
# weak evidence that nothing networked happened. If ptrace is unavailable --
# containers commonly forbid it -- the run still happens and the socket check
# says it was skipped rather than quietly passing.
tracer=""
if command -v strace >/dev/null 2>&1 &&
	strace -f -e trace=socket -o /dev/null true >/dev/null 2>&1; then
	tracer=yes
fi

play() {  # play NAME MAP EXTRA...
	name=$1; map=$2; shift 2
	trace_args=""
	if [ -n "$tracer" ]; then
		set -- "$@"
		( cd "$data_dir"
		  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		  timeout 150 strace -f -e trace=socket -o "$work/$name.strace" \
			"$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
			--config "$work/$name.cfg" --savedir "$work/$name-saves" \
			--capture-rngseed 1 --capture-checksum "$work/$name.checksum" \
			--capture-actors "$work/$name.actors" \
			--capture-players "$work/$name.players" \
			--capture-maxtics "$tics" --tedlevel "$map" --skill 2 \
			"$@" ) >"$work/$name.log" 2>&1 || true
	else
		( cd "$data_dir"
		  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
			--config "$work/$name.cfg" --savedir "$work/$name-saves" \
			--capture-rngseed 1 --capture-checksum "$work/$name.checksum" \
			--capture-actors "$work/$name.actors" \
			--capture-players "$work/$name.players" \
			--capture-maxtics "$tics" --tedlevel "$map" --skill 2 \
			"$@" ) >"$work/$name.log" 2>&1 || true
	fi
	unset trace_args
}

simulated() {  # simulated NAME
	n=$(grep -c '^tic ' "$work/$1.checksum" 2>/dev/null || true)
	[ -n "$n" ] || n=0
	printf '%s' "$n"
}

# The trace is one line per living monster per tic: "tic class tilex tiley
# dir pathing attack health". Distinct class-and-tile triples, so the answer is
# how many monsters were seen rather than how many kinds of monster.
monsters() {  # monsters NAME
	if [ ! -s "$work/$1.actors" ]; then printf '0'; return; fi
	awk '$1 ~ /^[0-9]+$/ {seen[$2":"$3":"$4]=1} END {print length(seen)}' \
		"$work/$1.actors" 2>/dev/null || printf '0'
}

printf 'A deathmatch on an arena, with nothing on the other end\n'
play arena MAP53 --battle
arena_tics=$(simulated arena)
printf '  ..   %s tics simulated on MAP53\n' "$arena_tics"
check "it reached gameplay" test "$arena_tics" -ge "$tics"
check "and spawned a player" test -s "$work/arena.players"

if [ -n "$tracer" ]; then
	opened=$(grep -c 'AF_INET' "$work/arena.strace" 2>/dev/null || true)
	[ -n "$opened" ] || opened=0
	printf '  ..   %s internet sockets opened\n' "$opened"
	check "it opened no socket at all" test "$opened" -eq 0
else
	printf '  ..   strace cannot trace here; socket check skipped\n'
fi

printf '\nDeathmatch rules, applied without a network to justify them\n'
play campaign MAP01
play battle MAP01 --battle
campaign_monsters=$(monsters campaign)
battle_monsters=$(monsters battle)
printf '  ..   MAP01 held %s aliens normally, %s under --battle\n' \
	"$campaign_monsters" "$battle_monsters"
check "a campaign level normally has aliens in it" \
	test "$campaign_monsters" -gt 0
check "and a deathmatch on it has none, with no socket to prove it is one" \
	test "$battle_monsters" -eq 0
check "the deathmatch still simulated" test "$(simulated battle)" -ge "$tics"

if [ -n "$tracer" ]; then
	opened=$(grep -c 'AF_INET' "$work/battle.strace" 2>/dev/null || true)
	[ -n "$opened" ] || opened=0
	check "and opened no socket either" test "$opened" -eq 0
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: a deathmatch is a deathmatch without a wire to prove it.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
