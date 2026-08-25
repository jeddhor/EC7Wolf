#!/bin/sh

# Regression test: the touch controls reach the simulation.
#
# Milestone 5 of docs/android.md. Not "the buttons are drawn" -- they were drawn
# for a while without doing anything -- but that pressing each one changes the
# thing it is supposed to change, read out of the game's own state.
#
# The assertions come from --capture-verbs, which prints a line whenever any of
# Corridor 7's verbs moves. Screenshots cannot do this job: the level's textures
# animate on their own, so two frames of a completely idle game differ in nearly
# every pixel, and a diff proves nothing either way.
#
# What it is guarding against:
#
#   * The overlay not being drawn at all. From the Phase 11 GL cutover until M5,
#     frameControls was only called from the SDL_Renderer path, which the GL
#     backend replaced -- so on a device with no keyboard there were no controls.
#   * The overlay drawing but not reaching the game, which is what a stale GL
#     context, or an unbound array buffer, or a lost tap all look like.
#   * A tap being too short to see. Touch events arrive on the event thread and
#     the game samples buttons once a tic; a quick tap starts and ends inside
#     one of those gaps. On a keyboard nobody presses a key for four
#     milliseconds. On a touchscreen that is how people press things.
#
# Usage: test_android_controls.sh [BUILDS_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
builds=${1:-$(cd "$root/.." && pwd)/builds}

SDK=${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}
ADB=$(command -v adb 2>/dev/null || echo "$SDK/platform-tools/adb")
[ -x "$ADB" ] || { printf 'SKIP: no adb under %s\n' "$SDK"; exit 0; }
apk=$(ls "$builds"/android-arm64-v8a/ec7wolf.apk 2>/dev/null | head -1)
[ -n "$apk" ] || { printf 'SKIP: no arm64 APK; run tools/build_android.sh\n'; exit 0; }

if [ -n "${ANDROID_SERIAL:-}" ]; then serial=$ANDROID_SERIAL
else serial=$("$ADB" devices 2>/dev/null | awk '$2 == "device" { print $1 }' | head -1); fi
[ -n "$serial" ] || { printf 'SKIP: no Android device attached\n'; exit 0; }
adb() { "$ADB" -s "$serial" "$@"; }
[ "$(adb get-state 2>/dev/null || true)" = "device" ] ||
	{ printf 'SKIP: device %s is not ready\n' "$serial"; exit 0; }
if adb shell dumpsys window 2>/dev/null | grep -q 'mDreamingLockscreen=true'; then
	printf 'SKIP: %s is locked\n' "$serial"; exit 0
fi

pkg=org.ec7wolf.EC7Wolf
B=/storage/emulated/0/Android/data/$pkg/files/Corridor7/FULL
adb shell ls "$B/MAPTEMP.CO7" >/dev/null 2>&1 ||
	{ printf 'SKIP: no game data on %s; run test_android_import.sh\n' "$serial"; exit 0; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT INT TERM
# Escape closes the soft keyboard on some Android versions and does nothing on
# others -- Samsung's Android 11 IME ignores it, and the keyboard then covers
# the button the next tap is aimed at, so the tap lands on a key instead. Back
# always closes it, but back with no keyboard up navigates away, so ask first.
hide_keyboard() {
	if adb shell dumpsys input_method 2>/dev/null | grep -q 'mInputShown=true'; then
		adb shell input keyevent 4 >/dev/null 2>&1
		sleep 1
	fi
}

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# The controls live on a 26x16 grid over the whole window (ScaleX/ScaleY in
# TouchControlsConfig.h), so their positions follow the screen rather than
# being written down for one phone.
size=$(adb shell wm size 2>/dev/null | sed -n 's/.*: *\([0-9]*\)x\([0-9]*\).*/\1 \2/p' | head -1)
set -- $size
a=${1:-1440}; b=${2:-3120}
if [ "$a" -ge "$b" ]; then W=$a; H=$b; else W=$b; H=$a; fi
cell_x() { echo $(( $1 * W / 26 )); }
cell_y() { echo $(( $1 * H / 16 )); }
# Rectangles from initControls in android-jni.cpp, as (left+right)/2.
tap_attack()  { adb shell input tap "$(cell_x 43)" "$(cell_y 17)"; }   # (20,7)-(23,10) doubled
tap_visor()   { adb shell input tap "$(cell_x 49)" "$(cell_y 21)"; }   # (23,9)-(26,12)
tap_mine()    { adb shell input tap "$(cell_x 43)" "$(cell_y 23)"; }   # (20,10)-(23,13)
tap_map()     { adb shell input tap "$(cell_x 10)" "$(cell_y 2)"; }    # (4,0)-(6,2)
# Halved back: cell_x/y take doubled grid units so the midpoints stay integers.
cell_x() { echo $(( $1 * W / 52 )); }
cell_y() { echo $(( $1 * H / 32 )); }
# The move stick occupies (0,7)-(8,16); swipe upward from its middle.
swipe_move() { adb shell input swipe "$(cell_x 8)" "$(cell_y 24)" "$(cell_x 8)" "$(cell_y 17)" 400; }
# The look stick is (17,4)-(26,16); swipe across it.
swipe_look() { adb shell input swipe "$(cell_x 43)" "$(cell_y 28)" "$(cell_x 49)" "$(cell_y 28)" 400; }

printf 'The phone\n'
printf '  ..   %s, %sx%s\n' "$(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')" "$W" "$H"
adb install -r "$apk" >/dev/null 2>&1

printf '\nStarting a level with the state trace on\n'
adb shell am force-stop "$pkg" >/dev/null 2>&1 || true
adb shell am start -n "$pkg/com.beloko.wolf3d.EntryActivity" >/dev/null 2>&1
sleep 5
# Straight into a level, with mines to drop: the player starts MAP01 with none,
# and a verb that cannot be exercised cannot be tested.
#
# By resource id, not by a fraction of the screen. The launcher's own widgets
# are laid out by Android, and where they land on a 2560x1600 tablet is not
# where they land on a 3120x1440 phone.
# uiautomator will not dump while anything on screen is animating; it says so
# on stderr, leaves the previous dump in place, and a launcher that has just
# been started is animating. Delete, retry, and if it truly cannot be found say
# so -- this used to fail the "set -e" way, killing the gate with no output at
# all after the header.
tap_id() {
	i=0
	while [ $i -lt 6 ]; do
		adb shell rm -f /sdcard/ec7-ui.xml >/dev/null 2>&1
		adb shell uiautomator dump /sdcard/ec7-ui.xml >/dev/null 2>&1
		bounds=$(adb shell cat /sdcard/ec7-ui.xml 2>/dev/null | tr '>' '\n' | grep "$1" |
			grep -o 'bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' | head -1 | tr -cs '0-9' ' ')
		if [ -n "$bounds" ]; then
			set -- $bounds
			adb shell input tap $(( ($1 + $3) / 2 )) $(( ($2 + $4) / 2 ))
			return 0
		fi
		sleep 2; i=$((i + 1))
	done
	return 1
}
if ! tap_id 'id/extra_args_edittext'; then
	printf '  FAIL could not find the launcher on screen\n'
	printf '\nFAIL: see above.\n'
	exit 1
fi
sleep 2
adb shell input text '%s--tedlevel%sMAP01%s--capture-verbs%s--capture-give%sC7Mines' >/dev/null 2>&1
sleep 2
hide_keyboard
sleep 1
adb logcat -c >/dev/null 2>&1 || true
if ! tap_id 'id/start_full'; then
	printf '  FAIL could not find the Play button\n'
	printf '\nFAIL: see above.\n'
	exit 1
fi
sleep 28

trace() { adb logcat -d 2>/dev/null | grep -oE 'verbs tic=[0-9]+ .*' | tail -1; }
field() { printf '%s\n' "$2" | tr ' ' '\n' | sed -n "s/^$1=//p"; }

base=$(trace)
printf '  ..   %s\n' "${base:-(no trace)}"
check "the level is running and reporting its state" test -n "$base"
[ -n "$base" ] || { printf '\nFAIL: nothing to test against.\n'; exit 1; }

# Press one control, then say what moved. Each returns the fresh trace line.
press() { adb logcat -c >/dev/null 2>&1 || true; "$1" >/dev/null 2>&1; sleep 3; trace; }
moved() {  # moved FIELD BEFORE AFTER  -- true when that field changed
	b=$(field "$1" "$2"); a=$(field "$1" "$3")
	[ -n "$a" ] && [ "$a" != "$b" ]
}

printf '\nEach verb, and what it moved\n'

after=$(press tap_attack)
printf '  ..   fire: %s\n' "${after:-(nothing)}"
check "firing spends ammunition" moved ammo "$base" "$after"
[ -n "$after" ] && base=$after

after=$(press tap_visor)
printf '  ..   visor: %s\n' "${after:-(nothing)}"
check "the visor button changes visor mode" moved visor "$base" "$after"
[ -n "$after" ] && base=$after

after=$(press tap_map)
printf '  ..   floor map: %s\n' "${after:-(nothing)}"
check "the floor map button raises the panel" moved map "$base" "$after"
[ -n "$after" ] && base=$after

after=$(press swipe_move)
printf '  ..   move: %s\n' "${after:-(nothing)}"
check "the left stick moves the player" sh -c '
	bx=$(printf "%s\n" "$1" | tr " " "\n" | sed -n "s/^x=//p")
	by=$(printf "%s\n" "$1" | tr " " "\n" | sed -n "s/^y=//p")
	ax=$(printf "%s\n" "$2" | tr " " "\n" | sed -n "s/^x=//p")
	ay=$(printf "%s\n" "$2" | tr " " "\n" | sed -n "s/^y=//p")
	[ -n "$ax" ] && { [ "$ax" != "$bx" ] || [ "$ay" != "$by" ]; }' _ "$base" "$after"
[ -n "$after" ] && base=$after

after=$(press swipe_look)
printf '  ..   look: %s\n' "${after:-(nothing)}"
check "the right stick turns the player" moved angle "$base" "$after"
[ -n "$after" ] && base=$after

# Last, because a proximity mine dropped at your feet is a proximity mine
# dropped at your feet.
after=$(press tap_mine)
printf '  ..   mine: %s\n' "${after:-(nothing)}"
check "the mine button spends a mine" moved mines "$base" "$after"

check "nothing crashed" test "$(adb logcat -d 2>/dev/null | grep -c 'Fatal signal')" -eq 0

adb shell am force-stop "$pkg" >/dev/null 2>&1 || true
if [ "$status" -eq 0 ]; then printf '\nPASS\n'; else printf '\nFAIL: see above.\n'; fi
exit "$status"
