#!/bin/sh

# Exercise the same title-to-menu path used by the packaged launcher. This is
# deliberately separate from test_corridor7.sh, which jumps directly to a map.

set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
	printf 'usage: %s CORRIDOR7_RELEASE_DIR [LOG_FILE]\n' "$0" >&2
	exit 2
fi

release_dir=$(cd "$1" && pwd)
log_file=${2:-"$release_dir/corridor7-startup.log"}

for required in ecwolf ecwolf.pk3 run-corridor7.sh MAPTEMP.CO7 VGAGRAPH.CO7 GFXTILES.CO7; do
	if [ ! -e "$release_dir/$required" ]; then
		printf 'required release file is missing: %s\n' "$release_dir/$required" >&2
		exit 1
	fi
done

for command in convert import stdbuf xvfb-run xdotool; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required startup-test command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

config_dir=$(mktemp -d /tmp/ecwolf-corridor7-startup.XXXXXX)
config_file="$config_dir/ecwolf.cfg"
savedir="$config_dir/savegames"
mkdir -p "$savedir"
cleanup() {
	rm -rf "$config_dir"
}
trap cleanup EXIT HUP INT TERM

export C7_RELEASE_DIR="$release_dir"
export C7_STARTUP_LOG="$log_file"
export C7_CONFIG_FILE="$config_file"
export C7_SAVE_DIR="$savedir"
export C7_TITLE_SHOT="$config_dir/title.png"
export C7_MENU_SHOT="$config_dir/menu.png"

set +e
xvfb-run -a sh -c '
	cd "$C7_RELEASE_DIR"
	pid=0
	cleanup_child() {
		if [ "$pid" -gt 0 ]; then
			kill "$pid" 2>/dev/null || true
			wait "$pid" 2>/dev/null || true
		fi
	}
	trap cleanup_child EXIT HUP INT TERM

	# First use the launcher exactly as a player does. After the title duration,
	# the screen must contain a non-black Corridor 7 credit page. The original
	# regression spun through an empty intermission and remained solid black.
	env SDL_AUDIODRIVER=dummy \
		ECWOLF_CONFIG="$C7_CONFIG_FILE" ECWOLF_SAVEDIR="$C7_SAVE_DIR" \
		stdbuf -oL -eL ./run-corridor7.sh \
		>"$C7_STARTUP_LOG" 2>&1 &
	pid=$!
	attempt=0
	while ! grep -q "DemoLoop: Starting the game loop" "$C7_STARTUP_LOG"; do
		kill -0 "$pid" 2>/dev/null || exit 10
		attempt=$((attempt + 1))
		[ "$attempt" -lt 100 ] || exit 11
		sleep 0.1
	done

	window=""
	attempt=0
	while [ -z "$window" ]; do
		window=$(xdotool search --pid "$pid" --onlyvisible 2>/dev/null | sed -n "1p")
		attempt=$((attempt + 1))
		[ "$attempt" -lt 50 ] || exit 12
		[ -n "$window" ] || sleep 0.1
	done
	sleep 9
	import -window "$window" "$C7_TITLE_SHOT"
	[ "$(convert "$C7_TITLE_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 15
	cleanup_child
	pid=0

	# Then enter the menu deterministically and start a new game. This checks
	# that the packaged menu is rendered, accepts input, and reaches MAP01.
	env SDL_AUDIODRIVER=dummy \
		ECWOLF_CONFIG="$C7_CONFIG_FILE" ECWOLF_SAVEDIR="$C7_SAVE_DIR" \
		stdbuf -oL -eL ./run-corridor7.sh --nowait \
		>>"$C7_STARTUP_LOG" 2>&1 &
	pid=$!
	attempt=0
	while [ "$(grep -c "DemoLoop: Starting the game loop" "$C7_STARTUP_LOG")" -lt 2 ]; do
		kill -0 "$pid" 2>/dev/null || exit 16
		attempt=$((attempt + 1))
		[ "$attempt" -lt 100 ] || exit 17
		sleep 0.1
	done
	window=""
	attempt=0
	while [ -z "$window" ]; do
		window=$(xdotool search --pid "$pid" --onlyvisible 2>/dev/null | sed -n "1p")
		attempt=$((attempt + 1))
		[ "$attempt" -lt 50 ] || exit 18
		[ -n "$window" ] || sleep 0.1
	done
	xdotool windowfocus --sync "$window"
	sleep 1
	import -window "$window" "$C7_MENU_SHOT"
	[ "$(convert "$C7_MENU_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 19
	# New Game -> selected rank starts MAP01.
	xdotool key Return
	sleep 1
	xdotool key Return

	attempt=0
	while ! grep -q "MAP01 - Corridor 7 Level 1" "$C7_STARTUP_LOG"; do
		kill -0 "$pid" 2>/dev/null || exit 13
		attempt=$((attempt + 1))
		[ "$attempt" -lt 100 ] || exit 14
		sleep 0.1
	done
	cleanup_child
	pid=0
' 
status=$?
set -e

if [ "$status" -ne 0 ]; then
	printf 'Corridor 7 packaged startup test failed (%d); see %s\n' "$status" "$log_file" >&2
	exit 1
fi

if grep -Eqi 'parser error|fatal error|segmentation fault|assertion.*failed' "$log_file"; then
	printf 'A startup/runtime failure was logged; see %s\n' "$log_file" >&2
	exit 1
fi

printf 'Corridor 7 packaged startup test passed; log: %s\n' "$log_file"
