#!/bin/sh

# Build the Android native libraries.
#
# Milestone 0 of docs/android.md. Produces libec7wolf.so, and the SDL libraries
# it needs, for every ABI asked for.
#
# Three things about this build are not obvious and cost time to rediscover:
#
#   * It needs a *native* build first. Cross-compiling cannot run the tools it
#     has to run -- zipdir builds the pk3 -- so a host build exports them and
#     the Android configure imports that file. Without it CMake stops with
#     "include could not find requested file: IMPORTFILE-NOTFOUND", which does
#     not mention tools, cross-compiling, or what to do about it.
#   * SDL, SDL_mixer and SDL_net come from deps/, fetched by
#     fetch_android_deps.sh. SDL in particular must be there rather than
#     anywhere else: the launcher reads SDL's Java glue through a symlink into
#     deps/SDL, and Java and native SDL of different vintages fail at runtime
#     rather than at build time.
#   * SDL_mixer's codecs are turned off except the ones built into it. FLAC,
#     Opus, MOD and WavPack all want sources under deps/SDL_mixer/external that
#     nothing fetches, and Corridor 7 needs none of them: its digitised sound
#     is decoded by the engine, its music is synthesised by the engine's OPL,
#     and the CD soundtrack is Ogg Vorbis, which stb_vorbis handles with no
#     external dependency at all.
#
# Usage: build_android.sh [ABI...]      (default: arm64-v8a x86_64)

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
builds=$(cd "$root/.." && pwd)/builds

SDK=${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}
API=${ANDROID_API:-21}

[ -d "$SDK" ] || { printf 'No Android SDK at %s; set ANDROID_SDK_ROOT\n' "$SDK" >&2; exit 1; }

# Newest NDK and build-tools present, rather than a version pinned here that
# somebody has to update every time they run the SDK manager.
NDK=$(ls -d "$SDK"/ndk/* 2>/dev/null | sort -V | tail -1)
[ -n "$NDK" ] || { printf 'No NDK under %s/ndk\n' "$SDK" >&2; exit 1; }
BUILD_TOOLS=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
PLATFORM=$(ls -d "$SDK"/platforms/android-* 2>/dev/null | sort -V | tail -1)

abis=${*:-"arm64-v8a x86_64"}
# Building one ABI is the right thing to do while iterating on a phone -- it
# halves the cycle -- but the APK it leaves behind has only that ABI in it, and
# nothing about testing on the phone will reveal that. Say so, because the APK
# gate finding it later reads like a regression rather than a shortcut.
case " $abis " in
	*" arm64-v8a "*) case " $abis " in *" x86_64 "*) : ;;
		*) printf 'NOTE: single-ABI build; the APK will not be release-ready.\n' ;; esac ;;
	*) printf 'NOTE: single-ABI build; the APK will not be release-ready.\n' ;;
esac
# arm64-v8a is what a phone runs, so it is the ABI the APK is assembled around;
# the rest are added to it afterwards.
primary=$(printf '%s\n' $abis | head -1)

# A debug key, generated once and kept out of the repository. It signs nothing
# anybody should trust: it exists because Android will not install an unsigned
# APK, and a release key is a decision for whoever ships this rather than
# something to invent here.
keystore=${ANDROID_KEYSTORE:-$builds/ec7wolf-debug.keystore}
keyalias=${ANDROID_KEYALIAS:-ec7wolf}
keypass=${ANDROID_KEYPASS:-android}
if [ ! -f "$keystore" ]; then
	mkdir -p "$(dirname "$keystore")"
	printf 'generating a debug signing key at %s\n' "$keystore"
	keytool -genkeypair -v -keystore "$keystore" -alias "$keyalias" \
		-storepass "$keypass" -keypass "$keypass" \
		-keyalg RSA -keysize 2048 -validity 10000 \
		-dname "CN=EC7Wolf Debug, OU=None, O=None, L=None, S=None, C=None" \
		>/dev/null 2>&1
fi

if [ ! -d "$root/deps/SDL" ]; then
	printf 'deps/SDL is missing; run tools/fetch_android_deps.sh first\n' >&2
	exit 1
fi

printf 'NDK          %s\n' "$NDK"
printf 'build-tools  %s\n' "$BUILD_TOOLS"
printf 'platform     %s\n' "$PLATFORM"
printf 'ABIs         %s\n\n' "$abis"

# The host tools, once, for every ABI to import.
if [ ! -f "$builds/host-tools/ImportExecutables.cmake" ]; then
	printf '=== host tools ===\n'
	cmake -S "$root" -B "$builds/host-tools" -G Ninja \
		-DTOOLS_ONLY=ON -DCMAKE_BUILD_TYPE=Release >/dev/null
	cmake --build "$builds/host-tools" --parallel "$(nproc)" >/dev/null
fi
printf 'host tools   %s\n\n' "$builds/host-tools/ImportExecutables.cmake"

for abi in $abis; do
	out="$builds/android-$abi"
	# The log is redirected into this directory, so it has to exist before
	# CMake is the thing that would have created it.
	mkdir -p "$out"
	printf '=== %s ===\n' "$abi"
	# find_file caches a miss. A build directory first configured without the
	# SDK paths keeps ANDROID_SDK_JAR-NOTFOUND for ever afterwards, and the
	# failure surfaces much later as ninja looking for a file called
	# "ANDROID_SDK_JAR-NOTFOUND". Clearing them costs nothing and is not worth
	# discovering twice.
	if [ -f "$out/CMakeCache.txt" ]; then
		cmake -U ANDROID_SDK_JAR -U ANDROID_AAPT_BINARY -U ANDROID_D8_BINARY \
			-U ANDROID_ADB_BINARY -U ANDROID_APK_SIGNER -U ANDROID_SUPPORT_V4_JAR \
			-B "$out" >/dev/null 2>&1 || true
	fi

	cmake -S "$root" -B "$out" -G Ninja \
		-DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
		-DANDROID_ABI="$abi" \
		-DANDROID_PLATFORM="android-$API" \
		-DCMAKE_BUILD_TYPE=Release \
		-DIMPORT_EXECUTABLES="$builds/host-tools/ImportExecutables.cmake" \
		-DANDROID_SDK="$PLATFORM" \
		-DANDROID_SDK_TOOLS="$BUILD_TOOLS" \
		-DSDL2MIXER_FLAC=OFF -DSDL2MIXER_OPUS=OFF -DSDL2MIXER_MOD=OFF \
		-DSDL2MIXER_WAVPACK=OFF -DSDL2MIXER_GME=OFF -DSDL2MIXER_MIDI=OFF \
		-DSDL2MIXER_SAMPLES=OFF -DSDL2MIXER_CMD=OFF \
		-DANDROID_SIGN_KEYSTORE="$keystore" \
		-DANDROID_SIGN_KEYNAME="$keyalias" \
		-DANDROID_SIGN_STOREPASS="$keypass" \
		>"$out/configure.log" 2>&1 || {
			printf 'configure failed; tail of %s/configure.log:\n' "$out"
			tail -20 "$out/configure.log"
			exit 1
		}

	cmake --build "$out" --target engine --parallel "$(nproc)" \
		>"$out/build.log" 2>&1 || {
			printf 'build failed; errors from %s/build.log:\n' "$out"
			grep -E "error:|FAILED" "$out/build.log" | head -10
			exit 1
		}

	printf '  %s\n' "$out/src/libec7wolf.so"
done

# --- the APK -------------------------------------------------------------
#
# Built from the primary ABI, then the other ABIs' libraries are added to the
# same archive and it is signed again. CMake configures one ABI per build
# directory, so there is no single configure that can see them all; adding to
# the archive afterwards is how one APK ends up containing every architecture.

printf '\n=== apk ===\n'
primary_out="$builds/android-$primary"
cmake --build "$primary_out" --target engine-android --parallel "$(nproc)" \
	>"$primary_out/apk.log" 2>&1 || {
		printf 'apk build failed; errors from %s/apk.log:\n' "$primary_out"
		grep -viE "^--|^Adding |Deflate|Store" "$primary_out/apk.log" | tail -15
		exit 1
	}

apk="$primary_out/ec7wolf.apk"
[ -f "$apk" ] || { printf 'no apk at %s\n' "$apk" >&2; exit 1; }

for abi in $abis; do
	[ "$abi" = "$primary" ] && continue

	# Staged by hand rather than taken from the launcher's own lib directory:
	# that directory is a side effect of building the engine-android target,
	# which is only built for the primary ABI. Collecting the libraries from
	# where they were actually built is both cheaper and less mysterious than
	# building an APK per architecture to get at them.
	stage="$builds/android-$abi/apk-stage"
	rm -rf "$stage"
	mkdir -p "$stage/lib/$abi"
	for lib in \
		"$builds/android-$abi/src/libec7wolf.so" \
		"$builds/android-$abi/android-libs/TouchControls/libtouchcontrols.so" \
		"$builds/android-$abi/deps/SDL/libSDL2.so" \
		"$builds/android-$abi/deps/SDL_mixer/libSDL2_mixer.so" \
		"$builds/android-$abi/deps/SDL_net/libSDL2_net.so"
	do
		[ -f "$lib" ] || { printf '  MISSING %s\n' "$lib"; exit 1; }
		cp "$lib" "$stage/lib/$abi/"
	done

	printf '  adding %s libraries\n' "$abi"
	# aapt add takes paths relative to its working directory, and those become
	# the paths inside the archive, so this runs from the directory holding lib/.
	( cd "$stage" && "$BUILD_TOOLS/aapt" add -f "$apk" "lib/$abi"/*.so >/dev/null )
done

# Signed last, because adding to the archive invalidates whatever signature was
# on it.
"$BUILD_TOOLS/apksigner" sign --ks "$keystore" --ks-key-alias "$keyalias" \
	--ks-pass "pass:$keypass" --key-pass "pass:$keypass" "$apk" 2>/dev/null

printf '\n%s\n' "$apk"
printf 'done\n'
