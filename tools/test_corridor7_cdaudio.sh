#!/bin/sh

# Regression test: the ripped CD soundtrack is found and played the way the disc
# played it, and the AdLib soundtrack is still there for anyone without it.
#
# The CD release does not assign a song to each floor. Its StartMusic
# (18b8:09cf in CORR7CD.EXE) plays the next track in a four-song playlist only
# when the previous one has already run out, so a ten-minute track carries
# across several floors and the AdLib songs are never loaded at all. That rule
# is invisible on one floor -- both a correct build and a build that restarts
# the music every level play track 3 first -- so every case here crosses a level
# boundary, and the two music cases differ only in how long the tracks are:
#
#   * short tracks: the first has finished by the time the second floor starts,
#     so the playlist advances and track 5 is heard.
#   * one long track: it is still playing, so the second floor inherits it and
#     no new track starts.
#
# A build that ignores the "still playing" test passes the first case and fails
# the second; a build that never advances passes the second and fails the first.
#
# The tally screen between floors blocks on input, so the level change has to be
# driven through a real X server with keystrokes, as test_level_transition.sh
# does.
#
# Usage: test_corridor7_cdaudio.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
display=:108

if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi

for command in Xvfb xdotool ffmpeg; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-cdaudio.XXXXXX)
cleanup() {
	[ -n "${game:-}" ] && kill "$game" 2>/dev/null || true
	[ -n "${xvfb:-}" ] && kill "$xvfb" 2>/dev/null || true
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

# Run from a directory holding the build's OWN pk3: ECWolf resolves ec7wolf.pk3
# from the working directory first, and running with the data directory as cwd
# silently tests whichever pk3 was last installed there.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$work/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && ln -s "$f" "$work/" || true
done

Xvfb "$display" -screen 0 640x400x24 >"$work/xvfb.log" 2>&1 &
xvfb=$!
sleep 2

# $1 = log name, $2 = seconds of music to synthesize into each track.
# A duration of 0 means "no cdaudio directory at all".
run_case() {
	label=$1
	seconds=$2

	rm -rf "$work/cdaudio"
	if [ "$seconds" != "0" ]; then
		mkdir "$work/cdaudio"
		# Named for their physical track number on the disc, which is what the
		# game looks for. 3, 5, 7 and 9 are the four pieces of music.
		for n in 03 05 07 09; do
			ffmpeg -hide_banner -loglevel error -y -f lavfi \
				-i "sine=frequency=440:duration=$seconds" \
				-c:a libvorbis "$work/cdaudio/track$n.ogg"
		done
	fi

	(
		cd "$work"
		env DISPLAY="$display" SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 stdbuf -oL -eL \
			./ec7wolf --data CO7 --nowait --normal --tedlevel MAP01 \
			--vid-renderer software --res 640 400 \
			--capture-rngseed 1 --capture-exitlevel 300 \
			--capture-maxframes 4000 \
			--config "$work/cfg" --savedir "$work/sv" >"$work/$label.log" 2>&1 &
		echo $! >"$work/pid"
	)
	game=$(cat "$work/pid")

	sleep 8
	win=$(DISPLAY=$display xdotool search --name "EC7Wolf" 2>/dev/null | tail -1 || true)
	if [ -z "$win" ]; then
		printf 'FAIL: no game window appeared for case %s; see %s/%s.log\n' \
			"$label" "$work" "$label" >&2
		exit 1
	fi

	# Clear the tally screen so the run reaches the second floor.
	for i in 1 2 3 4 5 6 7 8 9 10; do
		DISPLAY=$display xdotool key --window "$win" space
		sleep 1
	done
	sleep 4

	kill "$game" 2>/dev/null || true
	wait "$game" 2>/dev/null || true
	game=

	if ! grep -q "MAP02" "$work/$label.log"; then
		printf 'FAIL: case %s never reached the second floor, so nothing about\n' "$label" >&2
		printf '      crossing a level boundary was tested; see %s/%s.log\n' "$work" "$label" >&2
		exit 1
	fi
}

played() {
	grep -c "CD audio: playing track $1\." "$work/$2.log" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# 1. No soundtrack installed: say so once, and leave the AdLib music alone.
# ---------------------------------------------------------------------------

run_case none 0

if ! grep -q "CD audio: no .*cdaudio directory" "$work/none.log"; then
	printf 'FAIL: with no cdaudio directory the game said nothing about it. The\n' >&2
	printf '      player has no way to tell a missing rip from a broken one.\n' >&2
	exit 1
fi
if [ "$(grep -c "CD audio: playing" "$work/none.log")" != "0" ]; then
	printf 'FAIL: a track was played with no cdaudio directory present\n' >&2
	exit 1
fi
printf 'PASS: without a rip the game reports it and falls back to AdLib\n'

# ---------------------------------------------------------------------------
# 2. Short tracks: the first ends during the first floor, so the second floor
#    takes the next one.
# ---------------------------------------------------------------------------

run_case short 0.5

if ! grep -q "CD audio: 4 of 4 soundtrack files found" "$work/short.log"; then
	printf 'FAIL: the four track files were not found; see %s/short.log\n' "$work" >&2
	exit 1
fi
if [ "$(played 03 short)" = "0" ]; then
	printf 'FAIL: the first floor did not start the first track\n' >&2
	exit 1
fi
if [ "$(played 05 short)" = "0" ]; then
	printf 'FAIL: the first track had finished, but the second floor did not move\n' >&2
	printf '      on to the next one. The playlist never advances, so the disc\n' >&2
	printf '      would only ever be heard from track 3.\n' >&2
	exit 1
fi
printf 'PASS: a finished track hands over to the next one at the next floor\n'

# ---------------------------------------------------------------------------
# 3. One long track: still playing when the second floor starts, so it carries
#    over instead of being restarted.
# ---------------------------------------------------------------------------

run_case long 300

if [ "$(played 03 long)" != "1" ]; then
	printf 'FAIL: expected the long track to start exactly once; it started %s\n' \
		"$(played 03 long)" >&2
	exit 1
fi
if [ "$(grep -c "CD audio: playing" "$work/long.log")" != "1" ]; then
	printf 'FAIL: a second track started while the first was still playing. The\n' >&2
	printf '      soundtrack is meant to run through a floor change, not restart\n' >&2
	printf '      at every elevator.\n' >&2
	exit 1
fi
printf 'PASS: a track still playing carries across the floor change\n'
