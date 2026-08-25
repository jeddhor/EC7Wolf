#!/bin/sh

# Fetch the sources the Android build needs and this repository does not carry.
#
# SDL, SDL_mixer and SDL_net, and only for Android. The desktop builds link the system SDL2, so
# the source is not otherwise needed -- and at 79MB it is not worth committing
# for one platform. The version is pinned to the one the desktop build uses, so
# that a bug found on a phone can be reproduced on a workstation.
#
# It lands at deps/SDL because that is where ECWolf's Android support expects
# it: android-libs/launcher/src/org/libsdl/app is a symlink into
# deps/SDL/android-project/..., which is how the SDL Java glue is kept in step
# with the native library it talks to. Two SDLs of different vintages in one
# APK fail at runtime, in the JNI, with nothing useful in the log.
#
# Usage: fetch_android_deps.sh [--force]

set -eu

# Pinned to exactly what the desktop build links, so that a bug found on a
# phone can be reproduced on a workstation instead of being blamed on a version
# difference nobody wrote down.
SDL_TAG=release-2.32.10
SDL_MIXER_TAG=release-2.8.1
SDL_NET_TAG=release-2.2.0

# The Vorbis encoder, for turning a disc image's audio tracks into the
# soundtrack files the engine plays (docs/android.md M6.5). Only the encoder is
# new: this project's SDL_mixer decodes Ogg with stb_vorbis, which cannot write
# one. Both are BSD-licensed.
OGG_TAG=v1.3.5
VORBIS_TAG=v1.3.7

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(cd "$here/.." && pwd)
dest="$root/deps/SDL"

fetch() {  # fetch NAME TAG REPO
	_name=$1; _tag=$2; _repo=$3
	_dest="$root/deps/$_name"

	if [ -d "$_dest" ]; then
		if [ "$force" = yes ]; then
			printf 'removing existing %s\n' "$_dest"
			rm -rf "$_dest"
		else
			_have=$(cd "$_dest" && git describe --tags 2>/dev/null || echo unknown)
			printf '%-12s already present (%s)\n' "$_name" "$_have"
			return 0
		fi
	fi

	printf '%-12s fetching %s\n' "$_name" "$_tag"
	git clone --quiet --depth 1 --branch "$_tag" "$_repo" "$_dest"
}

command -v git >/dev/null 2>&1 || { printf 'git is required\n' >&2; exit 1; }

force=no
[ "${1:-}" = "--force" ] && force=yes

fetch SDL       "$SDL_TAG"       https://github.com/libsdl-org/SDL.git
fetch SDL_mixer "$SDL_MIXER_TAG" https://github.com/libsdl-org/SDL_mixer.git
fetch SDL_net   "$SDL_NET_TAG"   https://github.com/libsdl-org/SDL_net.git
fetch ogg       "$OGG_TAG"       https://github.com/xiph/ogg.git
fetch vorbis    "$VORBIS_TAG"    https://github.com/xiph/vorbis.git

# The one thing that has to be true afterwards, checked rather than assumed:
# the launcher reaches SDL's Java glue through a symlink into deps/SDL, and a
# missing target there is a build that fails much later and less clearly.
link="$root/android-libs/launcher/src/org/libsdl/app"
if [ ! -e "$link/SDLActivity.java" ]; then
	printf 'FAIL: %s still does not resolve after fetching\n' "$link" >&2
	exit 1
fi
printf 'ok: the launcher can see SDLActivity.java\n'

# vorbisenc is the whole reason vorbis is fetched, and it is a separate source
# file that some configurations leave out.
if [ ! -f "$root/deps/vorbis/lib/vorbisenc.c" ]; then
	printf 'FAIL: deps/vorbis has no vorbisenc.c; the encoder would be missing\n' >&2
	exit 1
fi
printf 'ok: the Vorbis encoder is present\n'
