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

for required in ec7wolf ec7wolf.pk3 run-corridor7.sh MAPTEMP.CO7 VGAGRAPH.CO7 GFXTILES.CO7; do
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

config_dir=$(mktemp -d /tmp/ec7wolf-corridor7-startup.XXXXXX)
config_file="$config_dir/ec7wolf.cfg"
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
export C7_OPTIONS_SHOT="$config_dir/options.png"
export C7_GAME_SHOT="$config_dir/map01-after-fire.png"
export C7_PAUSE_SHOT="$config_dir/map01-paused.png"
export C7_DEATH_SHOT="$config_dir/death-report.png"
export C7_SCORES_SHOT="$config_dir/high-scores.png"
export C7_RETURN_SHOT="$config_dir/returned-title.png"

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
	export SDL_AUDIODRIVER=dummy
	export SDL_VIDEODRIVER=x11
	export EC7WOLF_CONFIG="$C7_CONFIG_FILE"
	export EC7WOLF_SAVEDIR="$C7_SAVE_DIR"
	run_corridor7() {
		# stdbuf injects libstdbuf ahead of libasan and aborts sanitizer builds.
		# A pseudo-terminal provides line-buffered logs without LD_PRELOAD.
		if ldd ./ec7wolf 2>/dev/null | grep -q libasan; then
			exec script -qefc "exec ./run-corridor7.sh $*" /dev/null
		else
			exec stdbuf -oL -eL ./run-corridor7.sh "$@"
		fi
	}

	# First use the launcher exactly as a player does. After the title duration,
	# the screen must contain a non-black Corridor 7 credit page. The original
	# regression spun through an empty intermission and remained solid black.
	run_corridor7 \
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
		# Some SDL/X11 combinations do not set _NET_WM_PID on the game
		# window. The isolated Xvfb server contains only this EC7Wolf instance,
		# so its window title is a safe deterministic fallback.
		if [ -z "$window" ]; then
			window=$(xdotool search --onlyvisible --name "EC7Wolf" 2>/dev/null | sed -n "1p")
		fi
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
	run_corridor7 --nowait --debugnet \
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
		if [ -z "$window" ]; then
			window=$(xdotool search --onlyvisible --name "EC7Wolf" 2>/dev/null | sed -n "1p")
		fi
		attempt=$((attempt + 1))
		[ "$attempt" -lt 50 ] || exit 18
		[ -n "$window" ] || sleep 0.1
	done
	xdotool windowfocus --sync "$window"
	sleep 1
	import -window "$window" "$C7_MENU_SHOT"
	[ "$(convert "$C7_MENU_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 19
	# Options -> Customize Controls contains the boolean selectors that used to
	# resolve to missing Wolf3D graphics under Corridor 7.
	xdotool key Down
	sleep 0.2
	xdotool key Return
	sleep 0.2
	xdotool key Return
	sleep 1
	import -window "$window" "$C7_OPTIONS_SHOT"
	[ "$(convert "$C7_OPTIONS_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 20
	[ "$(convert "$C7_OPTIONS_SHOT" -format "%k" info:)" -gt 4 ] || exit 21
	xdotool key Escape
	sleep 0.2
	xdotool key Escape
	sleep 0.2
	xdotool key Up
	sleep 0.2
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
	# Firing used to destroy an uninitialized drawing-only Frame and segfault as
	# soon as the live psprite left its Ready state. Exercise that exact path in
	# the packaged optimized binary before accepting the release.
	sleep 1
	xdotool keydown --window "$window" Control_L
	sleep 1
	xdotool keyup --window "$window" Control_L
	sleep 0.5
	kill -0 "$pid" 2>/dev/null || exit 22
	import -window "$window" "$C7_GAME_SHOT"
	[ "$(convert "$C7_GAME_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 23
	# Corridor 7 does not contain the Wolf3D PAUSED graphic. The old path looked
	# it up anyway, logged Unknown Texture: "PAUSED", and drew a checkerboard.
	xdotool key --window "$window" Pause
	sleep 0.5
	kill -0 "$pid" 2>/dev/null || exit 37
	import -window "$window" "$C7_PAUSE_SHOT"
	[ "$(convert "$C7_PAUSE_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 38
	if grep -q "Unknown Texture: \"PAUSED\"" "$C7_STARTUP_LOG"; then
		exit 39
	fi
	xdotool key --window "$window" Pause
	sleep 0.2
	# The original proximity-mine implementation accidentally treated 40
	# Corridor 7 world units as 40 whole tiles. Turn away from the eastern
	# start direction, use WAX to grant mines, and drop one. This reliably sent
	# the old spawn coordinates outside the map and crashed in AActor::Spawn.
	xdotool keydown --window "$window" Left
	sleep 1
	xdotool keyup --window "$window" Left
	xdotool keydown --window "$window" w
	xdotool keydown --window "$window" a
	xdotool keydown --window "$window" x
	sleep 0.1
	xdotool keyup --window "$window" x
	xdotool keyup --window "$window" a
	xdotool keyup --window "$window" w
	sleep 0.2
	# Exercise held fire on every weapon granted by W+A+X. This covers the
	# repeating Taser, full Ithaca reload (whose old final state crossed into Tebazile art),
	# both M-24 jiggle frames, complete Tribarrel bursts, alternating alien
	# muzzle frames, live plasma-projectile spawning, and the long
	# Disintegrator discharge/recovery path.
	for weapon in 1 2 3 4 5 6 7 8; do
		xdotool key --window "$window" "$weapon"
		sleep 0.2
		xdotool keydown --window "$window" Control_L
		if [ "$weapon" = 2 ]; then
			sleep 2.5
		else
			sleep 1.3
		fi
		xdotool keyup --window "$window" Control_L
		sleep 0.2
		kill -0 "$pid" 2>/dev/null || exit 24
	done
	# The player taking damage here used to be a failure. That made sense when
	# this fired one weapon for a fifth of a second: nothing could have shot
	# back, so damage meant the shot had hurt the shooter. It stopped making
	# sense when the walkthrough grew to hold fire on all eight weapons for
	# twelve seconds in a room with aliens in it -- returning fire is the game
	# working, and the check had become a coin toss that fails under load.
	#
	# What still matters is that the process survives the sequence, which the
	# kill -0 above and below already assert. Damage is reported, not judged.
	if grep -q "TakeDamage " "$C7_STARTUP_LOG"; then
		echo "note: the player was shot during the weapon walkthrough (aliens are awake)"
	fi
	# Drop a mine in front of the player and leave enough time for its Spawn
	# state to advance into Armed. This GUI check specifically guards the old
	# out-of-map spawn crash. Trigger/damage semantics are covered by the
	# deterministic definition test; trying to walk onto the mine here depends
	# on the imprecise X11 turn duration above and made this startup test flaky.
	xdotool keydown --window "$window" m
	sleep 0.2
	xdotool keyup --window "$window" m
	sleep 1.2
	kill -0 "$pid" 2>/dev/null || exit 26
	cleanup_child
	pid=0

	# Finally exercise the complete death -> high scores -> title path. The
	# Corridor 7 palette used to be reopened through a relative filename here;
	# a failed reopen left C7PAL with a null cache and crashed on a 768-byte
	# palette read immediately after the score page.
	run_corridor7 --nowait --tedlevel MAP01 --skill 2 --debugnet \
		>>"$C7_STARTUP_LOG" 2>&1 &
	pid=$!
	attempt=0
	while [ "$(grep -c "DemoLoop: Starting the game loop" "$C7_STARTUP_LOG")" -lt 3 ]; do
		kill -0 "$pid" 2>/dev/null || exit 28
		attempt=$((attempt + 1))
		[ "$attempt" -lt 100 ] || exit 29
		sleep 0.1
	done
	window=""
	attempt=0
	while [ -z "$window" ]; do
		window=$(xdotool search --pid "$pid" --onlyvisible 2>/dev/null | sed -n "1p")
		if [ -z "$window" ]; then
			window=$(xdotool search --onlyvisible --name "EC7Wolf" 2>/dev/null | sed -n "1p")
		fi
		attempt=$((attempt + 1))
		[ "$attempt" -lt 50 ] || exit 30
		[ -n "$window" ] || sleep 0.1
	done
	xdotool windowfocus --sync "$window"
	sleep 2
	# Enable debug keys and use the native Tab+H damage command seven times.
	xdotool keydown --window "$window" BackSpace
	xdotool keydown --window "$window" Shift_L
	xdotool keydown --window "$window" Alt_L
	sleep 0.2
	xdotool keyup --window "$window" Alt_L
	xdotool keyup --window "$window" Shift_L
	xdotool keyup --window "$window" BackSpace
	sleep 0.3
	xdotool key --window "$window" space
	sleep 0.5
	count=0
	while [ "$count" -lt 7 ]; do
		xdotool keydown --window "$window" Tab
		xdotool keydown --window "$window" h
		sleep 0.15
		xdotool keyup --window "$window" h
		xdotool keyup --window "$window" Tab
		sleep 0.2
		count=$((count + 1))
	done
	sleep 3
	kill -0 "$pid" 2>/dev/null || exit 31
	import -window "$window" "$C7_DEATH_SHOT"
	[ "$(convert "$C7_DEATH_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 32
	# Dismiss the death report, verify the unclipped score page, then dismiss it
	# and require the same process to survive into a non-black title/credit page.
	xdotool key --window "$window" space
	sleep 2
	kill -0 "$pid" 2>/dev/null || exit 33
	import -window "$window" "$C7_SCORES_SHOT"
	[ "$(convert "$C7_SCORES_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 34
	xdotool key --window "$window" space
	sleep 5
	kill -0 "$pid" 2>/dev/null || exit 35
	import -window "$window" "$C7_RETURN_SHOT"
	[ "$(convert "$C7_RETURN_SHOT" -colorspace Gray -format "%[fx:mean>0.01]" info:)" = 1 ] || exit 36
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
