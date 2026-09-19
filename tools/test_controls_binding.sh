#!/bin/sh

# Regression test: rebinding a control from the controls screen.
#
# This was broken for as long as the menu shell has existed and nobody noticed,
# because the part that still worked was the part most people use.
#
# The stock binder asks for one device at a time, and which one is a static
# column that Left and Right move. The old Wolfenstein menu drew those three
# columns, so the player could see which was selected. This shell shows every
# binding a control has on one row ("w / JS34"), and draws no columns at all --
# so the column became invisible state. Enter always asked for a keyboard key,
# a gamepad press did nothing whatever, and the prompt was drawn in the bitmap
# font at the old menu's coordinates, over a screen that looks nothing like it.
# A player with a controller in their hands could not rebind it, and could not
# dismiss the box either, because Escape was the only way out.
#
# The binder now asks for any device at once: whatever is pressed is what gets
# bound. This gate drives the real menu to the real screen and checks the
# result in the written configuration file rather than on the screen, because
# what matters is the binding, not the pixels.
#
# **The gamepad press itself is not tested here.** Injecting one needs a
# virtual input device, and on a developer's machine the real controller is
# already /dev/input/js0 and would be the one the engine opened. What is
# tested is everything around it: that the prompt appears, that a press binds,
# that cancel leaves the binding alone, that clear removes it, and that
# rebinding the keyboard leaves the joystick binding on the same row untouched
# -- which is the specific thing the old column model got wrong.
#
# Usage: test_controls_binding.sh BUILD_DIR DATA_DIR

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

for tool in Xvfb xdotool import; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-binding.XXXXXX)
. "$here/xvfb_common.sh"
. "$here/menu_common.sh"
display=:263
xvfb_start "$display" "$work/xvfb.log" 1280x800x24 || exit 1
cleanup() {
	kill_pids "${game:-}"
	xvfb_stop
	if [ "$status" -ne 0 ] || [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

# --- restoring the defaults ---------------------------------------------------
#
# F12 puts every binding back to the scheme this installation was set up with,
# after asking. Which scheme that is cannot be worked out from the bindings --
# a player who has rebound Forward to K matches neither -- so it is recorded in
# the configuration by the installer, and this drives both cases.
restore() {  # restore STYLE EXPECTED_FORWARD
	style=$1; want=$2
	mkdir -p "$work/r$style"
	# A configuration holding only the style, exactly as the installer writes
	# it for the modern scheme. The engine fills in the rest.
	printf 'ControlStyle = %s;\n' "$style" > "$work/r$style.cfg"

	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  exec "$build_dir/ec7wolf" --data CO7 --res 1280 800 --nowait \
		--config "$work/r$style.cfg" --savedir "$work/r$style" ) \
		>"$work/r$style.log" 2>&1 &
	game=$!
	i=0
	while [ "$i" -lt 150 ]; do
		DISPLAY=$display xdotool search --pid "$game" --onlyvisible >/dev/null 2>&1 && break
		kill -0 "$game" 2>/dev/null || break
		i=$((i + 1)); sleep 0.2
	done
	sleep 3
	window=$(DISPLAY=$display xdotool search --pid "$game" --onlyvisible 2>/dev/null | sed -n 1p)

	menu_open Escape || return 1
	menu_press_moved Down || return 1
	menu_enter "the options menu" || return 1
	menu_walk_to_bottom "Controls" || return 1
	menu_enter "the controls menu" || return 1
	menu_walk_to_bottom "the last row" || return 1
	menu_press_moved Up || return 1
	menu_enter "the list of controls" || return 1

	# Change something first, so that restoring has work to do.
	menu_send_key Return; sleep 1
	menu_send_key j; sleep 1

	DISPLAY=$display import -window root "$work/r$style-before.png" 2>/dev/null || true
	menu_send_key F12
	sleep 1.5
	if ! menu_screen_changed "$work/r$style-before.png" 2000; then
		printf '  FAIL style %s: F12 asked nothing\n' "$style"
		status=1
	fi
	DISPLAY=$display import -window root "$work/r$style-asked.png" 2>/dev/null || true
	menu_send_key Return          # confirm
	sleep 1.5

	menu_press Escape 1
	menu_press Escape 1
	menu_press Escape 1
	menu_walk_to_bottom "Exit Building" || return 1
	menu_press Return 2
	menu_send_key y
	i=0
	while [ "$i" -lt 60 ] && kill -0 "$game" 2>/dev/null; do sleep 0.5; i=$((i + 1)); done
	kill_pids "$game"; game=

	got=$(sed -n 's/^Keyboard_Forward *= *\([-0-9]*\);.*/\1/p' "$work/r$style.cfg" | tail -1)
	printf '  ..   style %s: Keyboard_Forward=%s after restoring (wanted %s)\n' \
		"$style" "${got:-missing}" "$want"
	[ "${got:-missing}" = "$want" ]
}

printf 'Rebinding a control\n'

( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  exec "$build_dir/ec7wolf" --data CO7 --res 1280 800 --nowait \
	--config "$work/cfg" --savedir "$work/sv" ) >"$work/game.log" 2>&1 &
game=$!

window=
i=0
while [ "$i" -lt 150 ]; do
	window=$(DISPLAY=$display xdotool search --pid "$game" --onlyvisible 2>/dev/null | sed -n 1p) || true
	[ -n "$window" ] && break
	kill -0 "$game" 2>/dev/null || break
	i=$((i + 1)); sleep 0.2
done
[ -n "$window" ] || { printf '  FAIL the game never opened a window\n'; exit 1; }
sleep 3

alive() { kill -0 "$game" 2>/dev/null; }
MENU_ALIVE=alive

# Escape, then Options -- the rows between are disabled outside a game and the
# cursor steps over them, so this is one press rather than a count.
menu_open Escape || { printf '  FAIL no menu\n'; exit 1; }
menu_press_moved Down || exit 1
menu_enter "the options menu" || exit 1
menu_walk_to_bottom "Controls" || exit 1
menu_enter "the controls menu" || exit 1
# Customize controls sits one above the last row, so walk to the end and step
# back. Stepping back from wherever the screen opens instead wraps to the last
# row -- a boolean, which Return silently toggles rather than opening anything.
menu_walk_to_bottom "the last row of the controls menu" || exit 1
menu_press_moved Up || exit 1
menu_enter "the list of controls" || exit 1

# The list opens on Forward, and it is longer than the walk helpers will step
# through, so this uses where it opens rather than walking to it.
DISPLAY=$display import -window root "$work/before-prompt.png" 2>/dev/null || true
menu_send_key Return
sleep 1.5
check "a prompt appears when a control is activated" \
	menu_screen_changed "$work/before-prompt.png" 2000

# Bind the K key to Forward.
menu_send_key k
sleep 1

# Cancel on the next one, which must leave it alone.
menu_send_key Return
sleep 1
menu_send_key Escape
sleep 1

# And clear the row below it.
menu_press_moved Down || exit 1
menu_send_key Return
sleep 1
menu_send_key BackSpace
sleep 1.5

# Out through the menu rather than killed, so the configuration is written.
menu_press Escape 1
menu_press Escape 1
menu_press Escape 1
menu_walk_to_bottom "Exit Building" || exit 1
menu_press Return 2
menu_send_key y
i=0
while [ "$i" -lt 60 ] && alive; do sleep 0.5; i=$((i + 1)); done
check "the game exited through its own menu" sh -c "! kill -0 $game 2>/dev/null"
game=

setting() {  # setting NAME -- its value in the written config, or "missing"
	sed -n "s/^$1 *= *\([-0-9]*\);.*/\1/p" "$work/cfg" 2>/dev/null | tail -1 |
		sed 's/^$/missing/'
}

[ -s "$work/cfg" ] || { printf '  FAIL no configuration was written\n'; exit 1; }
printf '  ..   Keyboard_Forward=%s Joystick_Forward=%s\n' \
	"$(setting Keyboard_Forward)" "$(setting Joystick_Forward)"
printf '  ..   Keyboard_Backward=%s Joystick_Backward=%s Mouse_Backward=%s\n' \
	"$(setting Keyboard_Backward)" "$(setting Joystick_Backward)" \
	"$(setting Mouse_Backward)"

# 107 is the SDL keysym for K, which is what was pressed.
check "the key that was pressed is the one that got bound" \
	test "$(setting Keyboard_Forward)" = "107"
# The row's joystick binding is the thing the old column model lost track of:
# rebinding the keyboard must not disturb it. 34 is the stock binding.
check "and the gamepad binding on that row survived it" \
	test "$(setting Joystick_Forward)" = "34"
check "cancelling left the binding alone" \
	test "$(setting Keyboard_Forward)" = "107"
check "and clearing removed every binding on its row" \
	sh -c "test \"$(setting Keyboard_Backward)\" = '-1' && \
		test \"$(setting Joystick_Backward)\" = '-1' && \
		test \"$(setting Mouse_Backward)\" = '-1'"

printf '\nRestoring the defaults\n'
# 119 is W, the modern scheme's Forward. 273 is the up arrow, the original's.
# Both are checked because the whole point of recording the style is that the
# answer is not the same for every installation.
check "F12 restores the modern scheme where that is what was installed" \
	restore 0 119
check "and the original's scheme where that was" \
	restore 1 273

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: controls can be rebound, cancelled, cleared and restored.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  %s %s %s\n' "$0" "$build_dir" "$data_dir"
fi
exit "$status"
