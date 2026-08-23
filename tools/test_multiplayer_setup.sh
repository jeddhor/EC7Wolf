#!/bin/sh

# Regression test: the setup screen, pressed on before anybody has typed in it.
#
# The screen opens with Role on "Join a game" and the address empty, which is
# exactly the state a player is in the first time they open it. Pressing Start
# from there killed the process outright -- and so did setting Role to "Host a
# game" and pressing Start, which is what somebody hosting for the first time
# does and has no address to type.
#
# The cause was two deep: StartMultiplayer read and trimmed the address before
# it consulted the role, so a host went through it too; and
# FString::StripLeftRight walks off the end of an empty string, because j is a
# size_t and "j = max - 1" on a length of zero is SIZE_MAX. glibc catches the
# write and aborts. Nothing had ever called it on a string that might be empty.
#
# This reached a person on real hardware before it reached a gate, which is the
# wrong order, so here is the gate. It needs no second player and no network:
# what is under test is one instance surviving two keypresses.
#
# Usage: test_multiplayer_setup.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdotool import; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-setup.XXXXXX)
. "$here/xvfb_common.sh"

display=:153
xvfb_start "$display" "$work/xvfb.log" 1280x800x24 || exit 1
cleanup() {
	kill_pids "${game:-}"
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

# Unbuffered, so that a line printed just before an abort is not lost with the
# rest of the buffer -- which is how this crash first hid its own last words.
# exec, so that $! is the game rather than the subshell wrapping it -- xdotool
# is asked for a window belonging to this pid, and a subshell has none.
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  # No timeout wrapper: it forks, and then $! is the wrapper rather than the
  # game, so xdotool finds no window belonging to it. stdbuf execs, so it does
  # not have that problem. The cleanup trap is what stops this.
  exec stdbuf -o0 -e0 "$build_dir/ec7wolf" \
	--data CO7 --res 1280 800 --nowait \
	--config "$work/cfg" --savedir "$work/sv" >"$work/game.log" 2>&1 ) &
game=$!

window=
i=0
while [ "$i" -lt 150 ]; do
	window=$(DISPLAY=$display xdotool search --pid "$game" --onlyvisible 2>/dev/null | sed -n 1p) || true
	[ -n "$window" ] && break
	kill -0 "$game" 2>/dev/null || break
	i=$((i + 1)); sleep 0.2
done
[ -n "$window" ] || { printf 'FAIL: the game never opened a window\n'; exit 1; }
sleep 3

press() {
	DISPLAY=$display xdotool windowfocus --sync "$window" 2>/dev/null || true
	DISPLAY=$display xdotool key --clearmodifiers "$1"
	sleep "${2:-1}"
}

# Retried, because a screenshot taken during a menu fade catches the highlight
# too dim to recognise and "no menu" is then indistinguishable from "not a
# menu". Every wrong answer here costs a keystroke sent to the wrong screen.
cursor() {
	_c=0
	while [ "$_c" -lt 6 ]; do
		DISPLAY=$display import -window root "$work/nav.png" 2>/dev/null || true
		_r=$(python3 "$here/menu_cursor.py" "$work/nav.png" 2>/dev/null || echo -1)
		if [ "$_r" -ge 0 ]; then
			printf '%s' "$_r"
			return 0
		fi
		_c=$((_c + 1))
		sleep 0.4
	done
	printf '%s' "-1"
}

# Walk to the last or first row rather than counting keystrokes to it: counting
# assumes every keystroke arrives, and a measured pixel row goes stale the next
# time the screen grows one. Both ends are facts about the menu instead.
walk_to_end() {  # walk_to_end up|down WHAT
	_dir=$1; _what=$2
	if [ "$_dir" = down ]; then _prev=-1; else _prev=99999; fi
	_try=0
	while [ "$_try" -lt 12 ]; do
		if ! kill -0 "$game" 2>/dev/null; then
			printf '  FAIL the game died while looking for %s\n' "$_what"
			sed 's/\x08//g' "$work/game.log" | grep -vE '^\s*$' | tail -3 | sed 's/^/         /'
			return 1
		fi
		_y=$(cursor)
		[ "$_y" -lt 0 ] && { printf '  FAIL no menu on screen looking for %s\n' "$_what"; return 1; }
		if [ "$_dir" = down ] && [ "$_y" -lt "$_prev" ]; then press Up 0.8; return 0; fi
		if [ "$_dir" = up ] && [ "$_y" -gt "$_prev" ]; then press Down 0.8; return 0; fi
		_prev=$_y
		if [ "$_dir" = down ]; then press Down 0.8; else press Up 0.8; fi
		_try=$((_try + 1))
	done
	printf '  FAIL never found the %s of the menu holding %s\n' "$_dir" "$_what"
	return 1
}

alive() { kill -0 "$game" 2>/dev/null; }
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

press Escape 2
press Escape 3
press Return 3
walk_to_end down "Multiplayer" || exit 1
press Return 3

check "the setup screen is up" alive

printf '\nStart, on a screen nobody has typed in\n'
walk_to_end down "Start" || exit 1
press Return 3
if alive; then
	printf '  ok   it survived, and asked for an address\n'
else
	printf '  FAIL it died\n'
	sed 's/\x08//g' "$work/game.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
	status=1
	exit 1
fi

# One Escape, not two: the first dismisses the "enter an address" box, and a
# second would leave the setup screen altogether -- after which the walking
# below happily rearranges the rank ladder instead.
press Escape 2

printf '\nStart, hosting, which never has an address either\n'
walk_to_end up "Role" || exit 1
press Left 1.5
walk_to_end down "Start" || exit 1
press Return 4
sleep 3

if alive; then
	printf '  ok   it survived\n'
else
	printf '  FAIL it died\n'
	sed 's/\x08//g' "$work/game.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
	status=1
fi

# Surviving is not enough: it has to actually be hosting.
if grep -q "Waiting for . players" "$work/game.log" 2>/dev/null; then
	printf '  ok   and is waiting for players, which is what hosting looks like\n'
else
	printf '  FAIL it survived but never started listening\n'
	sed 's/\x08//g' "$work/game.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
	status=1
fi

check "and there was no abort anywhere in the run" \
	sh -c "! grep -qi 'buffer overflow\|Assertion\|Segmentation' '$work/game.log'"

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: the setup screen survives being pressed before it is filled in.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
