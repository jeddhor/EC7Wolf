# Driving EC7Wolf's menus from a gate, reliably.
#
# Three gates walk the menus with xdotool and read the cursor back off a
# screenshot. They each carried their own copy of the same helpers, and the
# copies shared a bug that made the whole suite look unreliable:
#
#     press Down 0.8    # send the key, sleep, hope
#
# A key the game had not processed within 0.8s -- or never received at all,
# because window focus had not settled -- was indistinguishable from one that
# moved nothing. The walk simply burned one of its twelve tries. The
# multiplayer setup menu has TEN rows and needs nine presses to wrap, so three
# dropped keys was the entire margin. Under a full-suite run, with several
# Xvfb servers and an engine or two competing for the machine, that margin went
# regularly: a different gate in this family failed on almost every suite run,
# always passing when re-run alone. A suite that fails randomly is a suite
# people stop reading.
#
# The fix is to stop timing and start checking. A press is not finished when a
# timer expires; it is finished when the cursor has moved. A dropped key then
# costs a retry instead of the run, and a slow machine costs seconds instead of
# a failure.
#
# Callers set: display, work, here, and (optionally) window. Everything below
# reads those, which is what the copies already did.

# Set by the caller before this is sourced. Declared here as well so it is
# obvious where the values come from, and so shellcheck does not read them as
# typos. `:=` rather than `=`, so sourcing this can never clobber a caller that
# set them first.
: "${display:=}"    # the X display the game is on
: "${work:=}"       # a scratch directory for screenshots
: "${here:=}"       # tools/, for menu_cursor.py
: "${window:=}"     # the game window, when the caller has found one

#: How long to wait for one keypress to show up on screen, in 0.15s steps.
#: Generous: this only ever elapses when the key was genuinely lost.
MENU_SETTLE_STEPS=${MENU_SETTLE_STEPS:-20}
#: How many times to re-send a key that produced no movement.
MENU_PRESS_RETRIES=${MENU_PRESS_RETRIES:-4}
#: How far to walk before deciding a menu is not wrapping. Only has to exceed
#: the longest menu; with self-verifying presses it is not a timing budget.
MENU_WALK_LIMIT=${MENU_WALK_LIMIT:-30}

#: Optional: a command the walks call each step. When it fails the walk stops
#: and says the GAME died, which is a far more useful thing to be told than
#: that a menu stopped responding.
MENU_ALIVE=${MENU_ALIVE:-}

#: The row the cursor is on, or -1 when the screen is not a settled menu. One
#: shot: this is what the press poll calls, and it must be cheap.
menu_cursor_row() {
	DISPLAY=$display import -window root "$work/menu-look.png" 2>/dev/null || true
	python3 "$here/menu_cursor.py" "$work/menu-look.png" 2>/dev/null || echo -1
}

# The same, retried. A screenshot taken during a menu fade catches the
# highlight too dim to recognise, and "no menu" is then indistinguishable from
# "not a menu" -- which is the exact failure the walks were reporting. Used
# where a wrong answer ends the walk; the press poll uses the single shot,
# because there a -1 just means "not yet".
menu_cursor_settled() {
	_c=0
	while [ "$_c" -lt 8 ]; do
		_r=$(menu_cursor_row)
		if [ "$_r" -ge 0 ]; then
			printf '%s' "$_r"
			return 0
		fi
		_c=$((_c + 1))
		sleep 0.4
	done
	printf '%s' "-1"
}

menu_send_key() {  # menu_send_key KEY
	if [ -n "${window:-}" ]; then
		DISPLAY=$display xdotool windowfocus --sync "$window" 2>/dev/null || true
	fi
	DISPLAY=$display xdotool key --clearmodifiers "$1" 2>/dev/null || true
}

# These menus animate between screens, and a capture taken mid-transition has
# no settled cursor on it. Waiting for one is not the same as sleeping longer:
# it costs nothing when the screen is already up, and it does not run out on a
# machine that is busy.
menu_wait() {
	_w=0
	while [ "$_w" -lt 40 ]; do
		[ "$(menu_cursor_row)" -ge 0 ] && return 0
		sleep 0.5
		_w=$((_w + 1))
	done
	return 1
}

# Press a key and wait until the cursor actually moves, re-sending if it does
# not. Returns 1 only when the key produced no movement after every retry,
# which means the menu is not responding rather than that the machine is slow.
menu_press_moved() {  # menu_press_moved KEY
	_key=$1
	_from=$(menu_cursor_row)
	_attempt=0
	while [ "$_attempt" -lt "$MENU_PRESS_RETRIES" ]; do
		menu_send_key "$_key"
		_step=0
		while [ "$_step" -lt "$MENU_SETTLE_STEPS" ]; do
			_now=$(menu_cursor_row)
			if [ "$_now" -ge 0 ] && [ "$_now" -ne "$_from" ]; then
				return 0
			fi
			sleep 0.15
			_step=$((_step + 1))
		done
		_attempt=$((_attempt + 1))
	done
	return 1
}

# Press a key that is not expected to move the cursor -- Return, Escape -- and
# give the screen a moment to change. There is nothing to verify here, so this
# is the one place a sleep is still the honest answer.
menu_press() {  # menu_press KEY [SECONDS]
	menu_send_key "$1"
	sleep "${2:-1}"
}

# Walking down wraps to the first row, which is how the bottom is found without
# assuming how many rows there are or where the cursor started. Same going up.
menu_walk_to_bottom() {  # menu_walk_to_bottom WHAT
	_what=$1
	_prev=-1
	_try=0
	menu_wait || { printf '  FAIL no menu appeared while looking for %s\n' "$_what"; return 1; }
	while [ "$_try" -lt "$MENU_WALK_LIMIT" ]; do
		if [ -n "$MENU_ALIVE" ] && ! $MENU_ALIVE; then
			printf '  FAIL the game died while looking for %s\n' "$_what"
			return 1
		fi
		_y=$(menu_cursor_settled)
		if [ "$_y" -lt 0 ]; then
			printf '  FAIL no menu on screen while looking for %s\n' "$_what"
			return 1
		fi
		if [ "$_y" -lt "$_prev" ]; then
			menu_press_moved Up || {
				printf '  FAIL the menu stopped responding at %s\n' "$_what"; return 1; }
			printf '  ..   cursor on %s (bottom row)\n' "$_what"
			return 0
		fi
		_prev=$_y
		menu_press_moved Down || {
			printf '  FAIL the menu stopped responding while walking to %s\n' "$_what"
			return 1
		}
		_try=$((_try + 1))
	done
	printf '  FAIL never found the bottom of the menu holding %s\n' "$_what"
	return 1
}

menu_walk_to_top() {  # menu_walk_to_top WHAT
	_what=$1
	_prev=-1
	_try=0
	menu_wait || { printf '  FAIL no menu appeared while looking for %s\n' "$_what"; return 1; }
	while [ "$_try" -lt "$MENU_WALK_LIMIT" ]; do
		if [ -n "$MENU_ALIVE" ] && ! $MENU_ALIVE; then
			printf '  FAIL the game died while looking for %s\n' "$_what"
			return 1
		fi
		_y=$(menu_cursor_settled)
		if [ "$_y" -lt 0 ]; then
			printf '  FAIL no menu on screen while looking for %s\n' "$_what"
			return 1
		fi
		if [ "$_y" -lt "$_prev" ]; then
			printf '  ..   cursor on %s (top row)\n' "$_what"
			return 0
		fi
		_prev=$_y
		menu_press_moved Down || {
			printf '  FAIL the menu stopped responding while walking to %s\n' "$_what"
			return 1
		}
		_try=$((_try + 1))
	done
	printf '  FAIL never wrapped round to %s\n' "$_what"
	return 1
}
