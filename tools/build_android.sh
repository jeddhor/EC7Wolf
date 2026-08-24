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

printf '\ndone\n'
