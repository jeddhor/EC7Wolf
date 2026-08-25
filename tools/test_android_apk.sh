#!/bin/sh

# Regression test: the APK is one a phone would accept and could run.
#
# Milestone 2 of docs/android.md.
#
# Everything here is read back out of the finished archive rather than taken on
# trust from the build, because every failure this is guarding against produces
# an APK that builds perfectly and then fails on the device:
#
#   * A targetSdkVersion below the floor Android enforces at install time. The
#     manifest said 22, which no phone since Android 14 will accept.
#   * A missing native library. libec7wolf.so needs SDL2, SDL2_mixer and
#     SDL2_net; the packaging step copied only two of the five, and nothing
#     checks a native dependency until the loader goes looking for it at launch.
#   * A library the Java asks for by a name nobody built. Game.java loaded
#     "ecwolf"; this fork builds ec7wolf.
#   * One architecture. An APK with only x86_64 in it installs on an emulator
#     and not on a phone.
#   * An unsigned or badly signed archive, which will not install at all.
#
# Usage: test_android_apk.sh [BUILDS_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
builds=${1:-$(cd "$root/.." && pwd)/builds}

SDK=${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}
BUILD_TOOLS=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
[ -n "$BUILD_TOOLS" ] || { printf 'SKIP: no build-tools under %s\n' "$SDK"; exit 0; }

AAPT="$BUILD_TOOLS/aapt"
APKSIGNER="$BUILD_TOOLS/apksigner"
[ -x "$AAPT" ] || { printf 'SKIP: no aapt in %s\n' "$BUILD_TOOLS"; exit 0; }

apk=$(ls "$builds"/android-*/ec7wolf.apk 2>/dev/null | head -1)
[ -n "$apk" ] || { printf 'SKIP: no APK; run tools/build_android.sh\n'; exit 0; }

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

badging=$("$AAPT" dump badging "$apk" 2>/dev/null)
contents=$(unzip -l "$apk" 2>/dev/null)

printf 'The archive\n'
printf '  ..   %s (%s)\n' "$(basename "$apk")" "$(du -h "$apk" | cut -f1)"

target=$(printf '%s\n' "$badging" | sed -n "s/^targetSdkVersion:'\([0-9]*\)'.*/\1/p")
minsdk=$(printf '%s\n' "$badging" | sed -n "s/^sdkVersion:'\([0-9]*\)'.*/\1/p")
printf '  ..   minSdk %s, targetSdk %s\n' "$minsdk" "$target"

# Android's install-time floor has been rising since Android 14 blocked
# anything below 23. 24 is the floor as of Android 15; well above it is the
# only sensible place to be, and this asserts a margin rather than the floor
# itself so that the next rise does not silently break installs.
check "targetSdk is well clear of the install-time floor" test "$target" -ge 30
# The NDK will not build below 21, so anything lower here means the manifest
# and the libraries disagree about what they support.
check "minSdk matches what the NDK can build" test "$minsdk" -ge 21

printf '\nArchitectures\n'
native=$(printf '%s\n' "$badging" | sed -n "s/^native-code: //p" | tr -d "'")
printf '  ..   %s\n' "$native"
for abi in arm64-v8a x86_64; do
	case " $native " in
		*" $abi "*) printf '  ok   %s is in there\n' "$abi" ;;
		*) printf '  FAIL %s is missing\n' "$abi"; status=1 ;;
	esac
done

printf '\nNative libraries\n'
# Exactly the set libec7wolf.so needs. Checked per architecture, because
# adding a second ABI to an existing archive is a separate step and half a set
# is the shape that mistake takes.
for abi in arm64-v8a x86_64; do
	missing=""
	for lib in libec7wolf.so libtouchcontrols.so libSDL2.so libSDL2_mixer.so libSDL2_net.so; do
		printf '%s\n' "$contents" | grep -q "lib/$abi/$lib" || missing="$missing $lib"
	done
	if [ -z "$missing" ]; then
		printf '  ok   %s has all five\n' "$abi"
	else
		printf '  FAIL %s is missing:%s\n' "$abi" "$missing"
		status=1
	fi
done

# The name the Java actually asks for, read from the Java rather than assumed.
# These two have already disagreed once.
wanted=$(sed -n 's/.*nativeLibraryDir + "\/\(lib[A-Za-z0-9_]*\.so\)".*/\1/p' \
	"$root/android-libs/launcher/src/com/beloko/idtech/wolf3d/Game.java" | head -1)
if [ -n "$wanted" ]; then
	printf '  ..   Game.java loads %s\n' "$wanted"
	if printf '%s\n' "$contents" | grep -q "lib/arm64-v8a/$wanted"; then
		printf '  ok   which is in the archive\n'
	else
		printf '  FAIL which is not in the archive\n'
		status=1
	fi
fi

printf '\nContents\n'
check "the game data pk3 is packaged" sh -c "printf '%s\n' \"$contents\" | grep -q 'assets/ec7wolf.pk3'"
check "there is compiled Java" sh -c "printf '%s\n' \"$contents\" | grep -q 'classes.dex'"

launchable=$(printf '%s\n' "$badging" | sed -n "s/^launchable-activity: name='\([^']*\)'.*/\1/p")
printf '  ..   launches %s\n' "$launchable"
check "something is launchable" test -n "$launchable"

printf '\nSignature\n'
if [ -x "$APKSIGNER" ]; then
	verify=$("$APKSIGNER" verify --verbose "$apk" 2>/dev/null || true)
	for scheme in "v1 scheme" "v2 scheme"; do
		if printf '%s\n' "$verify" | grep -q "Verified using $scheme.*true"; then
			printf '  ok   signed, %s\n' "$scheme"
		else
			printf '  FAIL not signed with %s; it will not install\n' "$scheme"
			status=1
		fi
	done
else
	printf '  ..   no apksigner; signature unchecked\n'
fi

# --- the disc importer's encoder ---------------------------------------------
#
# libc7rip carries libvorbis so the disc importer can write the soundtrack, and
# it is loaded by the launcher process, which loads nothing else native. Two
# ways for that to break silently: the library not being packaged at all, and
# the JNI entry points not matching the Java class that declares them -- a
# rename on either side leaves symbols that no longer pair up, and the failure
# is an UnsatisfiedLinkError at the moment somebody tries to import a disc.
printf '\nThe disc importer\n'
case $contents in
	*libc7rip.so*) printf '  ok   libc7rip.so is packaged\n' ;;
	*) printf '  FAIL libc7rip.so is missing; a disc image cannot be ripped\n'; status=1 ;;
esac

riplib=$(mktemp -d)
if unzip -o -q -j "$apk" 'lib/arm64-v8a/libc7rip.so' -d "$riplib" 2>/dev/null &&
	[ -f "$riplib/libc7rip.so" ]; then
	for sym in nativeOpen nativeWrite nativeClose; do
		if strings "$riplib/libc7rip.so" |
			grep -q "Java_com_beloko_idtech_VorbisEncoder_$sym"; then
			printf '  ok   VorbisEncoder.%s has a native symbol\n' "$sym"
		else
			printf '  FAIL VorbisEncoder.%s has no matching native symbol\n' "$sym"
			status=1
		fi
	done
else
	printf '  ..   could not extract libc7rip.so to check its symbols\n'
fi
rm -rf "$riplib"

# --- identity ---------------------------------------------------------------
#
# Milestone 6. This was another game's app: the id was com.beloko.wolf3dhg, the
# label said ECWolf, the version said 1.0, and the icon was somebody else's.
# The manifest is generated from src/versiondefs.cmake now, and this reads the
# same file, so the check fails if either side is edited alone.
printf '\nIdentity\n'
defs=$root/src/versiondefs.cmake
want_id=$(sed -n 's/^set(PRODUCT_IDENTIFIER "\(.*\)").*/\1/p' "$defs" | head -1)
want_name=$(sed -n 's/^set(PRODUCT_NAME "\(.*\)").*/\1/p' "$defs" | head -1)
got_id=$(printf '%s\n' "$badging" | sed -n "s/^package: name='\([^']*\)'.*/\1/p")
got_label=$(printf '%s\n' "$badging" | sed -n "s/^application-label:'\([^']*\)'.*/\1/p")
got_version=$(printf '%s\n' "$badging" | sed -n "s/.*versionName='\([^']*\)'.*/\1/p")
got_code=$(printf '%s\n' "$badging" | sed -n "s/.*versionCode='\([^']*\)'.*/\1/p")
printf '  ..   %s, %s, %s (code %s)\n' "$got_id" "$got_label" "$got_version" "$got_code"

check "the application id is the project's own" test "$got_id" = "$want_id"
check "the label is the project's own name" test "$got_label" = "$want_name"
# "1.0" was the placeholder the launcher shipped with; anything derived from
# versiondefs.cmake looks like 1.0-betaN.
check "the version is a real one, not the placeholder" \
	sh -c "case \"$got_version\" in 1.0) exit 1 ;; '') exit 1 ;; *) exit 0 ;; esac"
check "the version code is monotonic, not 1" test "${got_code:-0}" -gt 1

# Every launcher density. xxhdpi and xxxhdpi postdate this launcher, and
# without them Android upscales the 96px icon onto a modern screen.
for d in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
	case $contents in
		*"drawable-$d"*ic_launcher.png*) printf '  ok   an icon for %s\n' "$d" ;;
		*) printf '  FAIL no launcher icon for %s\n' "$d"; status=1 ;;
	esac
done

# Nothing a person sees claims to be the app this was forked from. That is the
# application id, the label, and the label on the launcher entry -- deliberately
# not the entry activity's *class* name, which is still com.beloko.wolf3d.
# That is Beloko's launcher code, which this fork uses and credits in the about
# text; renaming the Java packages would churn thirty-odd files, show a player
# nothing, and make the borrowing harder to see rather than easier.
identity_lines=$(printf '%s\n' "$badging" |
	grep -E "^package:|^application-label|^application:|^launchable-activity" |
	sed "s/name='com\.beloko\.[A-Za-z0-9_.]*'//")
if printf '%s\n' "$identity_lines" | grep -qi "beloko"; then
	printf '  FAIL something a player sees still names another app\n'
	printf '%s\n' "$identity_lines" | grep -i beloko | sed 's/^/       /'
	status=1
else
	printf '  ok   nothing a player sees names another app\n'
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: an APK a phone would accept.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
