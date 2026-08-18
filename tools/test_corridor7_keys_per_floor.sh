#!/bin/sh

# Regression test: the RED and BLUE access cards are per-floor.
#
# Corridor 7 makes you find the ACCESS GRANTED switch again on every level, so
# the cards must not survive a floor change. They are Key subclasses, and Key
# sets inventory.interhubamount 0 precisely so StripInventory drops them at the
# transition -- but statics.txt used to override that back to 1, which carried
# both cards into every subsequent level and unlocked its doors for free.
#
# The check is driven off the capture log's "cards" field rather than the status
# bar, because the W+A+X cheat that grants the cards also fills health, ammo and
# armour: a pixel diff of the bar cannot isolate the cards from the rest.
#
# Two runs, because a run captures one frame: the first confirms the cheat
# actually grants the cards (without it the second run would pass even if the
# cards were never given), the second exercises the transition.
#
# Usage: test_corridor7_keys_per_floor.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

. "$(dirname "$0")/xvfb_common.sh"

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
display=:107
work=$(mktemp -d /tmp/ec7wolf-keys.XXXXXX)

cleanup() {
	[ -n "${game:-}" ] && kill "$game" 2>/dev/null || true
	[ -n "${xvfb:-}" ] && kill "$xvfb" 2>/dev/null || true
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

# Run from a scratch directory holding the game data and the pk3 that was just
# BUILT. BaseDataPaths starts with ".", so an ec7wolf.pk3 sitting beside the
# data files wins over the build directory's -- and if the installed copy is
# stale, the test silently measures the old definitions and passes against a
# broken build. Hard-linking the data keeps this cheap; the pk3 is copied so the
# freshly built one is unambiguously the only candidate.
#
# Every data file comes across, not just *.CO7: the iwad's MustContain list
# includes C7PAL, and the palette is extracted from CORR7CD.EXE, so a directory
# holding only the .CO7 archives is not recognised as a game data set at all.
run_dir="$work/run"
mkdir -p "$run_dir"
for f in "$data_dir"/*; do
	[ -f "$f" ] || continue
	case "$(basename "$f")" in
		ec7wolf|ec7wolf.pk3|ec7wolf.cfg) continue ;;
	esac
	ln -f "$f" "$run_dir/" 2>/dev/null || cp "$f" "$run_dir/"
done
cp "$build_dir/ec7wolf.pk3" "$run_dir/ec7wolf.pk3"

xvfb_start "$display" "$work/xvfb.log" 900x600x24 || exit 1

# Runs the game with the equipment cheat held down early, and echoes the last
# "cards" field the capture harness logged.
#   $1 label   $2 frame to shoot   $3.. extra engine arguments
run_with_cheat() {
	label=$1; frame=$2; shift 2
	(
		cd "$run_dir"
		env DISPLAY="$display" SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 stdbuf -oL -eL \
			"$build_dir/ec7wolf" --data CO7 --no-upscale --nowait --normal --tedlevel MAP01 \
			--vid-renderer software --res 640 400 \
			--capture-rngseed 1 --capture-frame "$frame" \
			--capture-file "$work/$label.png" --capture-maxframes 2000 \
			"$@" \
			--config "$work/cfg" --savedir "$work/sv" >"$work/$label.log" 2>&1 &
		echo $! >"$work/pid"
	)
	sleep 5
	game=$(cat "$work/pid")

	win=$(DISPLAY=$display xdotool search --name "EC7Wolf" 2>/dev/null | tail -1 || true)
	if [ -z "$win" ]; then
		printf 'FAIL: no game window appeared; see %s/%s.log\n' "$work" "$label" >&2
		exit 1
	fi

	# W+A+X grants full equipment including both access cards. It must be held:
	# the poll samples the three keys together, and a tap can land between polls.
	DISPLAY=$display xdotool keydown --window "$win" w keydown --window "$win" a \
		keydown --window "$win" x
	sleep 2
	DISPLAY=$display xdotool keyup --window "$win" w keyup --window "$win" a \
		keyup --window "$win" x

	# The tally screen blocks on input, so it has to be cleared for the run to
	# reach the next level. Harmless when there is no transition.
	i=0
	while [ $i -lt 10 ]; do
		DISPLAY=$display xdotool key --window "$win" space
		sleep 1
		i=$((i+1))
	done
	sleep 6

	grep -o "map [A-Z0-9]* player ([0-9-]*,[0-9-]*) cards [RB-][RB-]" "$work/$label.log" |
		tail -1
}

granted=$(run_with_cheat granted 400)
if [ -z "$granted" ]; then
	printf 'FAIL: the run never reported a cards field; see %s/granted.log\n' "$work" >&2
	exit 1
fi
case "$granted" in
	*"cards RB") ;;
	*)
		printf 'FAIL: the cheat did not grant both access cards on MAP01 (%s).\n' "$granted" >&2
		printf '      Without that the transition check below proves nothing.\n' >&2
		exit 1
		;;
esac
printf 'PASS: W+A+X grants both access cards (%s)\n' "$granted"

carried=$(run_with_cheat carried 900 --capture-exitlevel 400)
if [ -z "$carried" ]; then
	printf 'FAIL: the run never reached the next level; see %s/carried.log\n' "$work" >&2
	tail -n 5 "$work/carried.log" >&2 || true
	exit 1
fi
case "$carried" in
	"map MAP02 "*) ;;
	*)
		printf 'FAIL: expected to arrive on MAP02, got: %s\n' "$carried" >&2
		exit 1
		;;
esac
case "$carried" in
	*"cards --") ;;
	*)
		printf 'FAIL: access cards survived the floor change (%s).\n' "$carried" >&2
		printf '      They are per-floor: Key sets inventory.interhubamount 0 so\n' >&2
		printf '      StripInventory drops them. Check statics.txt is not overriding it.\n' >&2
		exit 1
		;;
esac
printf 'PASS: access cards do not survive the floor change (%s)\n' "$carried"
