#!/bin/sh

# Regression test: a player can leave the waiting screen.
#
# Reported from play: once you were on "host a game", nothing got you off it.
# Escape did nothing on the desktop, and on a phone the back button reached the
# same nothing, so the only way out of a game nobody joined was to kill it.
#
# The cause was structural rather than a missed key. The connect loops live in
# the network code and call back into the menu only to *draw*; the return value
# of that callback was discarded at all eight call sites, and the drawing
# function never read the keyboard. There was no path by which a keypress could
# have been noticed, which is why pressing Escape harder did not help.
#
# The test drives the menu the way a player does -- New Mission, down to
# Multiplayer, Start as a host -- because that is the screen that was reported,
# and because keys only reach the game once the menu is up. (Under bare Xvfb a
# game still inside Net::Init, as --host puts it, receives no key events at all
# even with X focus on its window and SDL reporting keyboard focus. That is a
# harness limit, not the bug, and it is why this gate does not take the shorter
# --host route to the same loop.)
#
# The assertion is a screenshot comparison rather than the menu cursor: the
# waiting screen is drawn in the same shell with the same yellow heading, so
# menu_cursor.py finds a cursor on that too and cannot tell the two apart.
#
# What this gate deliberately does NOT cover is the other half of the same
# report -- that on a phone the address field could not be typed into, and that
# fixing it exposed a second fault where a burst of characters arrived as one.
# An attempt to cover it here passed against deliberately broken code: xdotool
# with no delay still spreads its key events across several frames, so the
# desktop never sees the burst an on-screen keyboard delivers. That fix is
# verified on a device instead, and a check that cannot fail is worse than no
# check at all.
#
# Usage: test_multiplayer_cancel.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdotool import python3; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
python3 -c 'import PIL' 2>/dev/null || { printf 'SKIP: PIL is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-mpcancel.XXXXXX)
. "$here/xvfb_common.sh"
. "$here/menu_common.sh"
display=:176
port=5041
xvfb_start "$display" "$work/xvfb.log" 1280x800x24 || exit 1
cleanup() {
	kill_pids "${game_pid:-}"
	xvfb_stop
	if [ -n "${KEEP_WORK:-}" ]; then printf '\nkept: %s\n' "$work"; else rm -rf "$work"; fi
}
trap cleanup EXIT INT TERM

status=0
check() {
	message=$1
	shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# windowfocus, not windowactivate: there is no window manager under bare Xvfb,
# so activate fails with "claims not to support _NET_ACTIVE_WINDOW" and the
# keystroke goes to the root window instead of the game.

# Screens are 1280x800, but the two being told apart share a backdrop, a
# heading rule and a typeface -- only the text column changes. Measured, that
# is about 13,000 pixels between the setup screen and the waiting screen, and
# 0 between the setup screen and itself, because neither animates. 4,000 sits
# in the middle of a gap that wide.
pixels_differing() {  # pixels_differing A B
	compare -metric AE "$1" "$2" null: 2>&1 | tr -d '\n' | sed 's/ .*//' | sed 's/[^0-9].*//'
}

differs_a_lot() {
	_n=$(pixels_differing "$1" "$2")
	[ -n "$_n" ] || return 1
	printf '  ..   %s pixels changed on entering the wait\n' "$_n"
	[ "$_n" -gt 4000 ]
}

looks_the_same() {
	_n=$(pixels_differing "$1" "$2")
	[ -n "$_n" ] || return 1
	printf '  ..   %s pixels differ from the setup screen afterwards\n' "$_n"
	[ "$_n" -lt 4000 ]
}


# These menus animate between screens, and a capture taken mid-transition has
# no settled cursor on it. Waiting for one is not the same as sleeping longer:
# it costs nothing when the screen is already up, and it does not run out on a
# machine that is busy.

# Walking down wraps to the first row, which is how the top is reached without
# assuming how many rows there are or where the cursor started.


printf 'A player who decides to host\n'
(
	cd "$data_dir"
	DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	timeout 180 "$build_dir/ec7wolf" --data CO7 --res 1280 800 --nowait \
		--config "$work/game.cfg" --savedir "$work/saves" --port "$port" \
		>"$work/game.log" 2>&1
) &
game_pid=$!

# Wait for the window, then let it settle. Two cleverer versions of this were
# wrong: polling the screen ends early because menu_cursor.py finds a cursor in
# the intro cinematic's artwork, and polling the log never ends at all, because
# stdout is block-buffered into a file and the line being waited for is still
# sitting in the buffer.
_i=0
while [ "$_i" -lt 60 ]; do
	window=$(DISPLAY=$display xdotool search --onlyvisible --name EC7Wolf 2>/dev/null | head -1)
	[ -n "${window:-}" ] && break
	kill -0 "$game_pid" 2>/dev/null || {
		printf '  FAIL the game exited before opening a window\n'
		tail -10 "$work/game.log" | sed 's/^/       /'
		exit 1
	}
	sleep 1
	_i=$((_i + 1))
done
[ -n "${window:-}" ] || { printf '  FAIL the game never opened a window\n'; exit 1; }
sleep 10

# Escape until a menu is actually on screen. A fixed pair of presses is lost
# entirely if the game is still loading when the first one goes out, and then
# nothing that follows can work.
menu_open Escape || { printf '  FAIL the game never reached a menu\n'; exit 1; }
menu_press Return 2.5          # New Mission -> the rank ladder
menu_walk_to_bottom "Multiplayer" || exit 1
menu_press Return 2.5          # -> the multiplayer setup screen

check "the setup screen is a menu" test "$(menu_cursor_row)" -ge 0

# The screen opens on "Join a game" with the cursor on Server address, and
# Start with an empty address only raises the "enter an address" prompt -- so
# the role has to be turned over to Host first, or this gate tests that guard
# instead of the waiting screen. Role is two rows up from where the cursor
# starts, which is the one place on this screen worth counting rather than
# walking: walking needs a wrap, and a wrap needs the disabled rows to behave,
# which is more assumption than two Ups.
# Verified, not timed: a dropped Up leaves the cursor a row off and the Left
# below then changes a different setting, which fails later and somewhere else.
menu_press_moved Up || { printf '  FAIL the menu did not move up to Role\n'; exit 1; }
menu_press_moved Up || { printf '  FAIL the menu did not move up to Role\n'; exit 1; }
# Verified by its effect, like the two Ups above. A dropped Left leaves the role
# on "Join", and Start then raises the "enter an address" prompt instead of
# hosting -- which fails four assertions later, describing the waiting screen
# rather than the key that never arrived.
DISPLAY=$display import -window root "$work/role-before.png" 2>/dev/null || true
menu_press_until Left menu_screen_changed "$work/role-before.png" 40 || {
	printf '  FAIL the role never changed from Join to Host\n'; exit 1; }
DISPLAY=$display import -window root "$work/role.png" 2>/dev/null || true

menu_walk_to_bottom "Start" || exit 1

# The setup screen as the player last saw it. Coming back to something that
# looks like this is what "got out of the waiting screen" means, and it is a
# stronger claim than "a menu is on screen": the waiting screen is drawn in the
# same shell, with the same yellow heading, so menu_cursor.py finds a cursor on
# that too and cannot tell the two apart.
DISPLAY=$display import -window root "$work/setup-before.png" 2>/dev/null || true
# The engine says when it is hosting, so that is what the press waits for
# rather than a number of seconds.
menu_press_until Return grep -q "Waiting for" "$work/game.log" || true

printf '\nWaiting for a player who never comes\n'
check "it is hosting" grep -q "Waiting for" "$work/game.log"
DISPLAY=$display import -window root "$work/waiting.png" 2>/dev/null || true
check "the waiting screen replaced the setup screen" \
	differs_a_lot "$work/setup-before.png" "$work/waiting.png"

printf '\nEscape\n'
menu_press Escape 4
DISPLAY=$display import -window root "$work/after-escape.png" 2>/dev/null || true

check "it went back to the setup screen" \
	looks_the_same "$work/setup-before.png" "$work/after-escape.png"
check "the game is still running" kill -0 "$game_pid"


if [ "$status" -eq 0 ]; then
	printf '\nPASS\n'
else
	printf '\nFAIL: see above.\n'
	DISPLAY=$display import -window root "$work/failed.png" 2>/dev/null || true
	[ -n "${KEEP_WORK:-}" ] || printf '       rerun with KEEP_WORK=1 to keep screenshots\n'
fi
exit "$status"
