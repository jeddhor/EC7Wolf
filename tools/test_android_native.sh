#!/bin/sh

# Regression test: the Android native libraries are what a phone would accept.
#
# Milestone 0 of docs/android.md.
#
# "The build produced a file" is not the claim worth checking. A cross-compile
# can produce a file for the wrong architecture, against the wrong API level,
# missing the entry point the Java side calls, or needing a library the device
# does not have -- and every one of those fails at runtime, on the device, with
# a message in logcat rather than in a build log. This checks the four things
# that can be known before installing anything.
#
# Usage: test_android_native.sh [BUILDS_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
builds=${1:-$(cd "$root/.." && pwd)/builds}

SDK=${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}
NDK=$(ls -d "$SDK"/ndk/* 2>/dev/null | sort -V | tail -1)
[ -n "$NDK" ] || { printf 'SKIP: no NDK under %s/ndk\n' "$SDK"; exit 0; }

TOOLS="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
READELF="$TOOLS/llvm-readelf"
NM="$TOOLS/llvm-nm"
[ -x "$READELF" ] || { printf 'SKIP: no llvm-readelf in the NDK\n'; exit 0; }

status=0
checked=0

check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# Libraries the device provides. Anything else has to be shipped in the APK,
# and a NEEDED entry naming something absent is a load failure at launch.
# One line on purpose: the membership test below matches on spaces, and a
# newline in this list silently stops matching whatever follows it.
system_libs="libEGL.so libGLESv1_CM.so libGLESv2.so libGLESv3.so liblog.so libm.so libdl.so libc.so libz.so libandroid.so libOpenSLES.so libaaudio.so libc++_shared.so libjnigraphics.so"

for abi in arm64-v8a x86_64; do
	so="$builds/android-$abi/src/libec7wolf.so"
	[ -f "$so" ] || continue
	checked=$((checked + 1))

	printf '%s\n' "$abi"

	# 1. The right machine. A library built for the wrong one installs happily
	#    and then fails to load.
	case "$abi" in
		arm64-v8a) want=AArch64 ;;
		x86_64)    want=X86-64 ;;
		*)         want=unknown ;;
	esac
	# readelf spells these out at length -- "Advanced Micro Devices X86-64" --
	# so this looks for the name inside the description rather than equalling it.
	machine=$("$READELF" -h "$so" | awk -F: '/Machine/ { gsub(/^ +/, "", $2); print $2 }')
	printf '  ..   built for %s\n' "$machine"
	case "$machine" in
		*"$want"*) printf '  ok   it is %s\n' "$want" ;;
		*) printf '  FAIL it is not %s\n' "$want"; status=1 ;;
	esac

	# 2. The entry point the Java side calls through SDL.
	if "$NM" --defined-only --dynamic "$so" 2>/dev/null | grep -qw SDL_main; then
		printf '  ok   it exports SDL_main\n'
	else
		printf '  FAIL it does not export SDL_main, so SDL has nothing to call\n'
		status=1
	fi

	# 3. Everything it asks the loader for is either shipped beside it or on
	#    the device.
	missing=""
	for need in $("$READELF" -d "$so" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p'); do
		case " $system_libs " in *" $need "*) continue ;; esac
		if [ ! -f "$builds/android-$abi/deps/SDL/$need" ] &&
		   [ ! -f "$builds/android-$abi/deps/SDL_mixer/$need" ] &&
		   [ ! -f "$builds/android-$abi/deps/SDL_net/$need" ] &&
		   [ ! -f "$builds/android-$abi/android-libs/TouchControls/$need" ]; then
			missing="$missing $need"
		fi
	done
	if [ -z "$missing" ]; then
		printf '  ok   every library it needs is either shipped or on the device\n'
	else
		printf '  FAIL nothing provides:%s\n' "$missing"
		status=1
	fi

	# 4. The OpenGL backend is in there.
	#
	# The goal is parity: what works on a desktop works on the phone. The build
	# is arranged to fall back to the software renderer when GL cannot be
	# found, which is the right behaviour and also a silent one -- a missing
	# GLES library or a stray find_package would produce a working build that
	# had quietly lost the renderer. Two ways of asking, because either alone
	# can be satisfied by accident.
	if "$READELF" -d "$so" | grep -q "libGLESv3.so"; then
		printf '  ok   it links GLES v3\n'
	else
		printf '  FAIL no GLES: this has fallen back to the software renderer\n'
		status=1
	fi
	glsyms=$("$NM" --defined-only "$so" 2>/dev/null | grep -ciE "GLWorld|GLRenderer|GLPalette" || true)
	[ -n "$glsyms" ] || glsyms=0
	printf '  ..   %s OpenGL backend symbols\n' "$glsyms"
	check "the OpenGL backend was compiled in" test "$glsyms" -gt 0

	# 5. Built against an API the device will run. The NDK records it in
	#    .note.android.ident, and llvm-readelf prints that note as raw bytes
	#    rather than as fields -- the API level is the first of them, little
	#    endian, so 21 appears as "15 00 00 00". Parsed rather than pattern
	#    matched on a label that is not printed, because a check that silently
	#    never runs is worse than no check: this one did exactly that until the
	#    note was looked at.
	api=$("$READELF" --notes "$so" 2>/dev/null |
		sed -n 's/.*description data: \([0-9a-f][0-9a-f]\) .*/\1/p' | head -1)
	if [ -n "$api" ]; then
		api=$((0x$api))
		printf '  ..   built for API %s\n' "$api"
		# Old enough that the phone will load it; new enough that the NDK will
		# build it. NDK r27 and later refuse anything below 21.
		check "which the NDK supports and a phone will load" \
			test "$api" -ge 21 -a "$api" -le 30
	else
		printf '  FAIL no Android API note; this may not be an NDK build at all\n'
		status=1
	fi
done

printf '\n'
if [ "$checked" -eq 0 ]; then
	printf 'SKIP: no Android builds found under %s\n' "$builds"
	exit 0
fi
if [ "$status" -eq 0 ]; then
	printf 'PASS: %s native libraries a phone would accept.\n' "$checked"
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
