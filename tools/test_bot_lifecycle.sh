#!/bin/sh

# Regression test: a bot dies, asks to come back, and comes back.
#
# Milestone B2 of docs/multiplayer-bots-and-server.md. This covers the two exit
# criteria the roam and door gates do not: "dies, and respawns through input",
# and "it never mutates actor state outside commands".
#
# Respawning is not a thing a bot can be seen to do by watching it happen,
# because the engine respawns a dead player eventually whether or not anybody
# asks. a_playerpawn.cpp returns a player to the world when
#
#     RespawnEligible <= TimeCount && buttonstate[bt_use]     -- 70 tics, or
#     RespawnEligible + 100 <= TimeCount                      -- 170 tics
#
# so a bot that pressed nothing still comes back, always a hundred tics late
# and never by its own doing. The latency is therefore the measurement: ~70
# tics means the press did it, ~170 means the engine gave up waiting. Measured
# both ways -- as shipped it is 72; with the press disabled it is 171.
#
# The last check is a source check, and deliberately so. Section 11.6's rule is
# that a brain produces commands and touches nothing else: no writing angle, no
# nudging position, no calling Door_Open. That is what makes a bot a player
# rather than a puppet, it is what keeps two machines agreeing, and it is not
# observable from outside a single run -- a bot that cheated once, quietly,
# would pass every behavioural test here. Zandronum's bots write
# m_pPlayer->mo->angle directly; that is the counter-example this rule exists
# against.
#
# Usage: test_bot_lifecycle.sh BUILD_DIR DATA_DIR

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

printf 'A bot that dies and comes back\n'

# --- the discipline, before anything runs ----------------------------------
#
# Assignments to a pawn's own fields from inside the brain. Comparisons and the
# command struct are fine; "pawn->angle =" is not.
writes=$(grep -nE '(pawn|mo|players\[[^]]*\]\.mo)->[A-Za-z_]+ *= [^=]' \
	"$here/../src/g_bot.cpp" 2>/dev/null | wc -l)
if [ "${writes:-0}" -ne 0 ]; then
	printf '  ..   in src/g_bot.cpp:\n'
	grep -nE '(pawn|mo|players\[[^]]*\]\.mo)->[A-Za-z_]+ *= [^=]' \
		"$here/../src/g_bot.cpp" | head -4 | sed 's/^/         /'
fi
check "the brain writes no actor state, only commands" test "${writes:-0}" -eq 0

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-life.XXXXXX)
. "$here/xvfb_common.sh"

display=:195
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

map=MAP53
slot=1
kill_at=300
tics=800

run() {  # run TAG
	mkdir -p "$work/$1-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 200 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$1.cfg" --savedir "$work/$1-saves" \
		--capture-rngseed 1 \
		--capture-kill-slot "$slot" "$kill_at" \
		--capture-bots "$work/$1.bots" \
		--capture-maxtics "$tics" \
		--tedlevel "$map" --skill 2 --battle --bots 1 ) >"$work/$1.log" 2>&1 || true
}

field() {  # field TAG KEY
	sed -n "s/.*Capture: bots .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" | tail -1
}

run a
if [ ! -s "$work/a.bots" ]; then
	printf '  FAIL the bot left no account of itself\n'
	sed 's/\x08//g' "$work/a.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
	exit 1
fi

died=$(awk '$3=="behavior" && $4=="dead" {print $1; exit}' "$work/a.bots")
back=$(awk '$3=="behavior" && $4=="spawn" {print $1; exit}' "$work/a.bots")
respawns=$(field a respawns)
presses=$(field a respawnpresses)
latency=$(( ${back:-0} - ${died:-0} ))

printf '  ..   killed at %s, dead at %s, back at %s -- %s tics, %s press(es)\n' \
	"$kill_at" "${died:-?}" "${back:-?}" "$latency" "${presses:-?}"

check "it noticed it was dead" test -n "${died:-}" -a "${died:-0}" -ge "$kill_at"
check "it came back" test "${respawns:-0}" -eq 1
check "it asked to, by pressing use" test "${presses:-0}" -ge 1

# The whole point. 70 tics is the press; 170 is the engine giving up on it.
# Anything at or past 100 means the press did nothing and the bot is being
# returned to the world by a timer it does not control.
check "and came back on its own press, not on the engine's timer" \
	test "$latency" -gt 0 -a "$latency" -lt 100

# A route is chosen for the place a bot was standing. Coming back somewhere
# else and walking the old one is a bot heading for a waypoint that belonged to
# a previous life.
newroute=$(awk -v t="${back:-0}" '$1+0 >= t && $3=="route"' "$work/a.bots" | wc -l)
resumed=$(awk -v t="${back:-0}" '$1+0 >= t && $3=="behavior" && $4=="roam"' \
	"$work/a.bots" | wc -l)
check "it planned a fresh route rather than resuming a dead one" \
	test "${newroute:-0}" -ge 1
check "and went back to roaming" test "${resumed:-0}" -ge 1

run b
d1=$(field a brain)
d2=$(field b brain)
printf '  ..   brain digests %s and %s\n' "${d1:-?}" "${d2:-?}"
check "two runs of one death think the same thoughts" \
	test -n "${d1:-}" -a "${d1:-x}" = "${d2:-y}"

if [ "$status" -eq 0 ]; then
	printf 'PASS: a bot dies, asks to come back, and comes back.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
