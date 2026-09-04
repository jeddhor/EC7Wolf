#!/bin/sh

# Regression test: a bot opens the door in its way, and only that door.
#
# Milestone B2, step 5, of docs/multiplayer-bots-and-server.md, section 12.4.
#
# A door is the first boundary the follower cannot simply walk through. It has
# to be approached on a face that opens, faced squarely, operated by pressing
# use exactly as a person does, waited on while the panel slides, and crossed
# only once the collision path agrees it is open.
#
# What is checked:
#
#   * a bot routed through a door opens it and arrives on the far side;
#   * a bot routed to the near side of the same door does NOT touch it, which
#     is what separates a door protocol from a bot that presses use constantly;
#   * the same match twice produces the same brain; and
#   * no step the graph offered was refused by the world.
#
# Two facts about the shipped arenas shape this gate, and both were measured
# rather than assumed:
#
#   * there is exactly one door in all eight of them -- MAP51 at tile (25,38),
#     one cell out of 960. A roaming bot priced against a 600-cost edge does
#     not find that cell in a match, so the goal is named rather than rolled.
#     Everything downstream of the goal is the ordinary follower.
#   * battle players spawn holding both access cards, so the lock on that door
#     is satisfied through the same possession check a human passes. Verified
#     directly: at spawn a battle player reports "cards RB" where a single
#     player reports "cards --". The bot gets no exception, and if that ever
#     changes this gate fails rather than quietly testing an unlocked door.
#
# Usage: test_bot_doors.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-doors.XXXXXX)
. "$here/xvfb_common.sh"

display=:194
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

tics=1400
map=MAP51
# The door, and the cells either side of it. It opens along Y, so these are the
# two faces that open; approaching on any other is what the graph refuses to
# build an edge for.
door_x=25
door_y=38
far_y=39
near_y=37

run() {  # run TAG GOAL_X GOAL_Y
	mkdir -p "$work/$1-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 200 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$1.cfg" --savedir "$work/$1-saves" \
		--capture-rngseed 1 \
		--capture-bot-goal "$2" "$3" \
		--capture-bots "$work/$1.bots" \
		--capture-players "$work/$1.players" \
		--capture-maxtics "$tics" \
		--tedlevel "$map" --skill 2 --battle --bots 1 ) >"$work/$1.log" 2>&1 || true
}

field() {  # field TAG KEY
	sed -n "s/.*Capture: bots .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" | tail -1
}

printf 'A door, opened the way a person opens one\n'

# --- through it ------------------------------------------------------------
run far "$door_x" "$far_y"
if [ ! -s "$work/far.bots" ]; then
	printf '  FAIL the bot left no account of itself\n'
	sed 's/\x08//g' "$work/far.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
	exit 1
fi

doors=$(field far doors)
failed=$(field far doorsfailed)
arrived=$(field far arrived)
refused=$(field far refused)
presses=$(grep -c 'door-press' "$work/far.bots" 2>/dev/null || true)
printf '  ..   routed past the door: doors %s, failed %s, arrived %s, refused %s, %s press(es)\n' \
	"${doors:-?}" "${failed:-?}" "${arrived:-?}" "${refused:-?}" "${presses:-0}"

check "it opened the door in its way" test "${doors:-0}" -ge 1
check "and reached the far side" test "${arrived:-0}" -ge 1
check "without the world refusing a step the graph offered" test "${refused:-0}" -eq 0
check "and without giving up on a door it could open" test "${failed:-0}" -eq 0

# Pressing use on an open door shuts it again -- Door_Open hands an existing
# door to Reactivate -- so a protocol that pulses instead of waiting toggles
# the door forever and never crosses. One press per door is what waiting looks
# like from outside; a handful is tolerable, a hundred is the toggling bug.
check "by pressing use a few times, not by holding it down" \
	test "${presses:-0}" -ge 1 -a "${presses:-0}" -le 4

# --- and not through it ----------------------------------------------------
run near "$door_x" "$near_y"
ndoors=$(field near doors)
narrived=$(field near arrived)
npresses=$(grep -c 'door-press' "$work/near.bots" 2>/dev/null || true)
printf '  ..   routed to the near side: doors %s, arrived %s, %s press(es)\n' \
	"${ndoors:-?}" "${narrived:-?}" "${npresses:-0}"

check "a bot with no door to open reached its goal" test "${narrived:-0}" -ge 1
check "and left the door alone" test "${ndoors:-0}" -eq 0 -a "${npresses:-0}" -eq 0

# --- the same match twice --------------------------------------------------
run far2 "$door_x" "$far_y"
d1=$(field far brain)
d2=$(field far2 brain)
printf '  ..   brain digests %s and %s\n' "${d1:-?}" "${d2:-?}"
check "two runs of one match think the same thoughts" \
	test -n "${d1:-}" -a "${d1:-x}" = "${d2:-y}"

if [ "$status" -eq 0 ]; then
	printf 'PASS: the bot opens the door in its way, and only that one.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
