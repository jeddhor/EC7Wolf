#!/bin/sh

# Regression test: a player can install the game without developer tools.
#
# Milestone 4 of docs/android.md. The device gate proves the engine runs; this
# one proves somebody who is not us can get the game onto a phone, because
# every other path we have used relies on adb push, and since Android 11 the
# app's own external directory is invisible to file managers and to MTP.
#
# The app is wiped with "pm clear" first, so this starts where a fresh install
# starts: no data, no config, no saved iwad choice. The zip is pushed to
# Downloads, which is the one thing a player does for themselves.
#
# What it is guarding against:
#
#   * Launching with no data. The launcher used to start the game whatever was
#     on disk, and a player with no data got a black screen and no reason.
#   * An incomplete required-file list. Corridor 7 keeps its palette inside
#     CORR7CD.EXE -- file_vswap.cpp reads C7PAL out of it at 0x2FFC0 -- so an
#     import of the seven .CO7 files reports success and then the engine
#     rejects the install with "Can not find base game data", naming five
#     extensions that have nothing to do with Corridor 7.
#   * The CD extras going to the wrong place. The cinematics and the ripped
#     soundtrack live in subdirectories of their own and are useless in the
#     game directory.
#
# Usage: test_android_import.sh [BUILDS_DIR]

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
else # -F'\t': adb delimits with a tab, and a wireless serial can contain a
	# space -- "adb-XXXX-YYYY (2)._adb-tls-connect._tcp". Splitting on
	# whitespace puts "(2)._adb-tls-connect._tcp" in $2, the test for "device"
	# fails, and every gate reports that no device is attached while one is.
	serial=$("$ADB" devices 2>/dev/null | awk -F'\t' '$2 == "device" { print $1 }' | head -1); fi
[ -n "$serial" ] || { printf 'SKIP: no Android device attached\n'; exit 0; }

adb() { "$ADB" -s "$serial" "$@"; }
[ "$(adb get-state 2>/dev/null || true)" = "device" ] ||
	{ printf 'SKIP: device %s is not ready\n' "$serial"; exit 0; }
if adb shell dumpsys window 2>/dev/null | grep -q 'mDreamingLockscreen=true'; then
	printf 'SKIP: %s is locked\n' "$serial"; exit 0
fi

# The player's own copy of the game. Built here from whatever data directory
# this checkout is testing against, because it can never be committed.
data=${EC7WOLF_DATA:-$(cd "$root/.." && pwd)/builds/release}
missing=
for f in AUDIOHED.CO7 AUDIOT.CO7 MAPTEMP.CO7 VGADICT.CO7 VGAHEAD.CO7 \
         VGAGRAPH.CO7 GFXTILES.CO7 CORR7CD.EXE; do
	[ -f "$data/$f" ] || missing="$missing $f"
done
[ -z "$missing" ] || { printf 'SKIP: no game data in %s (missing:%s)\n' "$data" "$missing"; exit 0; }

pkg=org.ec7wolf.EC7Wolf
B=/storage/emulated/0/Android/data/$pkg/files/Corridor7/FULL
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

# Find a widget by resource id and tap its middle. Resource ids rather than
# coordinates: this phone is 3120x1440 and the next one will not be.
# uiautomator refuses to dump while anything on screen is animating, and it
# says so on stderr and leaves the previous dump in place. Reading that stale
# file is how a check comes to be made against the screen before last, which
# looks exactly like a real failure. Delete first, and retry.
snapshot() {
	i=0
	while [ $i -lt 6 ]; do
		adb shell rm -f /sdcard/ec7-ui.xml >/dev/null 2>&1
		adb shell uiautomator dump /sdcard/ec7-ui.xml >/dev/null 2>&1
		if adb shell ls /sdcard/ec7-ui.xml >/dev/null 2>&1; then
			adb shell cat /sdcard/ec7-ui.xml 2>/dev/null > "$work/ui.xml"
			[ -s "$work/ui.xml" ] && return 0
		fi
		sleep 2; i=$((i + 1))
	done
	return 1
}

widget_bounds() {
	snapshot || return 1
	tr '>' '\n' < "$work/ui.xml" | grep "$1" |
		grep -o 'bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' | head -1 | tr -cs '0-9' ' '
}
tap_match() {
	set -- $(widget_bounds "$1")
	[ -n "${4:-}" ] || return 1
	adb shell input tap $(( ($1 + $3) / 2 )) $(( ($2 + $4) / 2 ))
}
status_text() {
	snapshot || return 1
	tr '>' '\n' < "$work/ui.xml" |
		grep 'id/data_status_textview' | grep -o 'text="[^"]*"' | head -1
}
play_enabled() {
	snapshot || return 1
	tr '>' '\n' < "$work/ui.xml" | grep 'id/start_full' | grep -q 'enabled="true"'
}
play_disabled() { ! play_enabled; }
on_phone() { adb shell ls "$1" >/dev/null 2>&1; }
absent_on_phone() { ! on_phone "$1"; }
# The status text is compared through a file: it is a whole paragraph of the
# app's own prose and must never be pasted into a shell command.
says() { grep -q "$1" "$work/status.txt"; }

# The screen is whatever it is; swipes are derived from it.
size=$(adb shell wm size 2>/dev/null | sed -n 's/.*: *\([0-9]*\)x\([0-9]*\).*/\1 \2/p' | head -1)
set -- $size
short=${1:-1440}; long=${2:-3120}
# Landscape: the wide edge is across.
screen_w=$long; screen_h=$short
[ "$screen_w" -ge "$screen_h" ] || { screen_w=$short; screen_h=$long; }
swipe_x=$((screen_w / 2))
swipe_from=$((screen_h * 5 / 6))
swipe_to=$((screen_h / 4))

printf 'A phone with nothing on it\n'
printf '  ..   %s (%s)\n' "$(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')" "$serial"
adb install -r "$apk" >/dev/null 2>&1
adb shell pm clear "$pkg" >/dev/null 2>&1
check "the app has no data at all" \
	absent_on_phone "/storage/emulated/0/Android/data/$pkg/files/Corridor7/FULL/MAPTEMP.CO7"

printf '\nThe player brings a zip\n'
zip=$work/Corridor7.zip
( cd "$data" && zip -qr "$zip" . -i '*.CO7' 'CORR7CD.EXE' 'video/*' 'cdaudio/*' ) 2>/dev/null ||
	{ printf 'SKIP: zip is not installed\n'; exit 0; }
printf '  ..   %s\n' "$(du -h "$zip" | cut -f1)"
adb push "$zip" /sdcard/Download/Corridor7.zip >/dev/null 2>&1
check "it is in Downloads, where a download goes" \
	on_phone /sdcard/Download/Corridor7.zip

printf '\nThe launcher, before importing\n'
adb shell am start -n "$pkg/com.beloko.wolf3d.EntryActivity" >/dev/null 2>&1
sleep 5
tap_match 'text="OK"' >/dev/null 2>&1 || true    # the first-run dialog
sleep 2
status_text > "$work/status.txt" 2>/dev/null || : > "$work/status.txt"
printf '  ..   %s\n' "$(cut -c1-72 "$work/status.txt")"
check "it says the data is missing" says 'not found'
# The whole point: no launching into a black screen.
check "it will not start the game" play_disabled
# CORR7CD.EXE has to be named, or a player supplies seven files and is stuck.
check "it asks for CORR7CD.EXE, not just the .CO7 files" says 'CORR7CD.EXE'

printf '\nImporting\n'
#
# Handed straight to the app as an intent rather than driven through the system
# file picker. That is not a shortcut around the feature: "open with EC7Wolf" is
# how somebody imports a download from their browser or a file manager, and it
# is a real path a player takes. It is also the only one a test can drive --
# this tablet's DocumentsUI ignores injected input entirely, in either view
# mode, by tap or by held press or by DPAD, so a gate resting on it tests
# nothing but Google's UI on a good day.
#
# The URI has to come from MediaStore: adb cannot mint a content:// URI, but it
# can look one up for a file it just put in Downloads, and --grant-read-uri-permission
# is what lets the app read it.
adb shell am force-stop "$pkg" >/dev/null 2>&1 || true
mediaid=$(adb shell "content query --uri content://media/external/downloads --projection _id:_display_name" 2>/dev/null |
	grep -i "$(basename "$zip")" | grep -oE '_id=[0-9]+' | cut -d= -f2 | head -1)
if [ -z "$mediaid" ]; then
	adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
		-d "file:///sdcard/Download/$(basename "$zip")" >/dev/null 2>&1 || true
	sleep 5
	mediaid=$(adb shell "content query --uri content://media/external/downloads --projection _id:_display_name" 2>/dev/null |
		grep -i "$(basename "$zip")" | grep -oE '_id=[0-9]+' | cut -d= -f2 | head -1)
fi
check "the archive has a content URI to hand over" test -n "$mediaid"
[ -n "$mediaid" ] || { printf '\nFAIL: see above.\n'; exit 1; }

adb logcat -c >/dev/null 2>&1 || true
adb shell am start -a android.intent.action.VIEW -t application/zip \
	-d "content://media/external/downloads/$mediaid" --grant-read-uri-permission \
	-n "$pkg/com.beloko.wolf3d.EntryActivity" >/dev/null 2>&1
# Importing is not instant -- a zip of loose files is seconds, a disc image is
# minutes because it is unpacked and then the soundtrack is encoded. Wait for
# the thing that says it worked rather than for a fixed time.
wait_for_data() {
	i=0
	while [ $i -lt 120 ]; do
		on_phone "$B/MAPTEMP.CO7" && return 0
		sleep 3
		i=$((i + 1))
	done
	return 1
}
check "the app accepted the archive and imported it" wait_for_data

# The import reports itself in a dialog, which sits over the status text the
# next checks read.
tap_match 'text="OK"' >/dev/null 2>&1 || true
sleep 2

printf '\nThe launcher, after importing\n'
status_text > "$work/status.txt" 2>/dev/null || : > "$work/status.txt"
printf '  ..   %s\n' "$(cut -c1-72 "$work/status.txt")"
check "it says the data is there" says 'Ready to play'
check "it will start the game now" play_enabled

check "the executable came across too" on_phone "$B/CORR7CD.EXE"
# The extras are only useful in their own directories.
check "the cinematics went into video/" on_phone "$B/video/SEQTHREE.CO7"
check "the soundtrack went into cdaudio/" on_phone "$B/cdaudio/track03.ogg"
no_partials() { ! adb shell find "$B" -name '*.part' 2>/dev/null | grep -q part; }
check "no half-written files were left behind" no_partials

printf '\nPlaying it\n'
tap_match 'id/extra_args_edittext' >/dev/null 2>&1; sleep 1
adb shell input text '%s--tedlevel%sMAP01' >/dev/null 2>&1; sleep 1
hide_keyboard; sleep 1
adb logcat -c >/dev/null 2>&1 || true
tap_match 'id/start_full' >/dev/null 2>&1
sleep 28

log=$work/logcat.txt
adb logcat -d > "$log" 2>/dev/null || true
said() { grep -q "$1" "$log"; }
check "it loaded MAP01 from the imported data" said 'MAP01 - Corridor 7 Level 1'
check "it found the imported cinematics" said 'Cinematics: 3 of 3'
check "it found the imported soundtrack" said 'CD audio: 4 of 4'
check "nothing crashed" test "$(grep -c 'Fatal signal' "$log")" -eq 0

adb shell am force-stop "$pkg" >/dev/null 2>&1 || true
adb shell rm -f /sdcard/Download/Corridor7.zip >/dev/null 2>&1 || true

if [ "$status" -eq 0 ]; then printf '\nPASS\n'; else printf '\nFAIL: see above.\n'; fi
exit "$status"
