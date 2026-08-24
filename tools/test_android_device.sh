#!/bin/sh

# Regression test: the engine runs on a real Android phone.
#
# Milestone 3 of docs/android.md, and the one that proves the whole idea. The
# APK gate reads the archive back and says a phone would accept it; this one
# installs it on a phone that is actually attached, drives the launcher, and
# reads the result off the screen.
#
# What it is guarding against, all of which produce an APK that installs and
# then does nothing useful:
#
#   * The GL renderer not coming up. The desktop build falls back to software
#     when the context is not what it asked for, and on a phone that fallback
#     would be invisible -- the game would just be slow. This asserts the
#     OpenGL backend by name.
#   * An exception unwinding out of native code into the JNI trampoline. The
#     touch controls initialised on whichever thread pushed the SDL resize
#     event, which is the Java main thread and has no GL context; the texture
#     loader threw, and there is no handler anywhere above it. It crashed at
#     0xebad8084 with a one-frame backtrace. Any fatal signal fails this gate.
#   * The engine reaching the title screen and going no further. Loading the
#     data, starting the game loop and drawing a level are three separate
#     things, so all three are checked.
#
# Needs the commercial data already on the phone under the launcher's game
# directory; it is a data-owning gate and skips cleanly everywhere else.
#
# Usage: test_android_device.sh [BUILDS_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
builds=${1:-$(cd "$root/.." && pwd)/builds}

SDK=${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}
ADB=$(command -v adb 2>/dev/null || echo "$SDK/platform-tools/adb")
[ -x "$ADB" ] || { printf 'SKIP: no adb under %s\n' "$SDK"; exit 0; }

apk=$(ls "$builds"/android-arm64-v8a/ec7wolf.apk 2>/dev/null | head -1)
[ -n "$apk" ] || { printf 'SKIP: no arm64 APK; run tools/build_android.sh\n'; exit 0; }

# One attached device, or ANDROID_SERIAL to pick among several.
if [ -n "${ANDROID_SERIAL:-}" ]; then
	serial=$ANDROID_SERIAL
else
	serial=$("$ADB" devices 2>/dev/null | awk '$2 == "device" { print $1 }' | head -1)
fi
[ -n "$serial" ] || { printf 'SKIP: no Android device attached\n'; exit 0; }

adb() { "$ADB" -s "$serial" "$@"; }

state=$(adb get-state 2>/dev/null || true)
[ "$state" = "device" ] || { printf 'SKIP: device %s is %s\n' "$serial" "${state:-unreachable}"; exit 0; }

# A locked phone shows the keyguard instead of the game, and every screenshot
# below would be of the lock screen.
if adb shell dumpsys window 2>/dev/null | grep -q 'mDreamingLockscreen=true'; then
	printf 'SKIP: %s is locked; unlock it and run again\n' "$serial"
	exit 0
fi

pkg=com.beloko.wolf3dhg
shots=$(mktemp -d)
trap 'rm -rf "$shots"' EXIT INT TERM

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

model=$(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')
release=$(adb shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
printf 'The phone\n'
printf '  ..   %s, Android %s (%s)\n' "$model" "$release" "$serial"

printf '\nInstalling\n'
result=$(adb install -r "$apk" 2>&1 | tr -d '\r' | grep -E 'Success|Failure' | head -1)
printf '  ..   %s\n' "${result:-no answer}"
check "the phone accepted the APK" test "$result" = "Success"
[ "$status" -eq 0 ] || { printf '\nFAIL: see above.\n'; exit 1; }

# The launcher's own widgets, found by resource id rather than by position:
# this phone is 3120x1440 and the next one will not be.
tap_widget() {
	id=$1
	adb shell uiautomator dump /sdcard/ec7-ui.xml >/dev/null 2>&1 || return 1
	adb shell cat /sdcard/ec7-ui.xml 2>/dev/null | tr '>' '\n' |
		grep "id/$id" | grep -o 'bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' | head -1 |
		tr -cs '0-9' ' ' | {
			read -r x1 y1 x2 y2
			[ -n "${y2:-}" ] || return 1
			adb shell input tap $(( (x1 + x2) / 2 )) $(( (y1 + y2) / 2 ))
		}
}

printf '\nStarting a level\n'
adb shell am force-stop "$pkg" >/dev/null 2>&1 || true
adb shell am start -n "$pkg/com.beloko.wolf3d.EntryActivity" >/dev/null 2>&1
sleep 5

# --tedlevel goes in the launcher's extra-args box; the Game activity is not
# exported, so this is the only way in from outside the app. "input text" turns
# %s into a space and rejects a leading "--" as its own option terminator, which
# is why the argument is written this way.
check "the launcher came up" tap_widget extra_args_edittext
sleep 1
adb shell input text '%s--tedlevel%sMAP01' >/dev/null 2>&1
sleep 1
adb shell input keyevent 111 >/dev/null 2>&1   # dismiss the keyboard
sleep 1

adb logcat -c >/dev/null 2>&1 || true
check "the launcher started the game" tap_widget start_full
sleep 25

log=$shots/logcat.txt
adb logcat -d > "$log" 2>/dev/null || true

engine_said() { grep -q "$1" "$log"; }

printf '\nWhat the engine did\n'
check "it found the Corridor 7 data" engine_said 'adding ec7wolf.pk3'
check "it chose the OpenGL renderer" engine_said 'Renderer: using OpenGL renderer'
check "it reached the game loop" engine_said 'DemoLoop: Starting the game loop'
check "it loaded MAP01" engine_said 'MAP01 - Corridor 7 Level 1'
check "nothing crashed" test "$(grep -c 'Fatal signal' "$log")" -eq 0

printf '\nWhat the phone drew\n'
shot=$shots/screen.png
adb exec-out screencap -p > "$shot" 2>/dev/null || true
check "a screenshot came back" test -s "$shot"

if [ -s "$shot" ] && command -v python3 >/dev/null 2>&1; then
	# A black frame is what a renderer that came up and drew nothing looks
	# like, and it is the failure a screenshot is here to catch.
	verdict=$(python3 - "$shot" <<'PY'
import sys
try:
	from PIL import Image
except ImportError:
	print("SKIP no pillow"); raise SystemExit
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
raw = im.resize((160, 90)).tobytes()
px = [raw[i] + raw[i + 1] + raw[i + 2] for i in range(0, len(raw), 3)]
lit = sum(1 for v in px if v > 60)
print("%dx%d %d%% lit" % (w, h, 100 * lit // len(px)))
PY
)
	printf '  ..   %s\n' "$verdict"
	case $verdict in
		"SKIP no pillow") : ;;
		*) lit=${verdict##* }; lit=${verdict%\% lit}; lit=${lit##* }
		   check "the frame is not black" test "$lit" -ge 20 ;;
	esac
fi

adb shell am force-stop "$pkg" >/dev/null 2>&1 || true

if [ "$status" -eq 0 ]; then
	printf '\nPASS\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
