#!/bin/sh

# Take the screenshots the README uses.
#
# Reproducible on purpose: the images in docs/images are generated, not
# collected, so when the menu or the installer changes they can be regenerated
# rather than quietly going stale. Runs entirely on a virtual display, so it
# never puts a window on the developer's screen.
#
# Usage: capture_screenshots.sh BUILD_DIR DATA_DIR [OUT_DIR]

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [OUT_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
out=${3:-$repo/docs/images}
mkdir -p "$out"

work=$(mktemp -d /tmp/ec7wolf-shots.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

. "$here/xvfb_common.sh"

mkdir -p "$work/data"
for f in "$data_dir"/*.CO7 "$data_dir/CORR7CD.EXE" "$data_dir/ec7wolf.pk3"; do
	[ -e "$f" ] || continue
	ln -s "$f" "$work/data/$(basename "$f")"
done
for d in cdaudio video; do
	[ -d "$data_dir/$d" ] && ln -s "$data_dir/$d" "$work/data/$d"
done

display=:141
xvfb_start "$display" "$work/xvfb.log" 1280x800x24
trap 'kill ${game:-0} 2>/dev/null; xvfb_stop; rm -rf "$work"' EXIT INT TERM

shoot() {  # shoot NAME
	DISPLAY=$display import -window root "$out/$1.png"
	printf '  %s\n' "$out/$1.png"
}

start_game() {  # start_game EXTRA_ARGS...
	( cd "$work/data" && DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		"$build_dir/ec7wolf" --data CO7 --nowait --res 1280 800 \
		--config "$work/cfg" --savedir "$work/sv" "$@" \
		>"$work/game.log" 2>&1 & echo $! > "$work/pid" )
	game=$(cat "$work/pid")
	i=0
	while [ $i -lt 150 ]; do
		window=$(DISPLAY=$display xdotool search --pid "$game" --onlyvisible 2>/dev/null | sed -n 1p) || true
		[ -n "${window:-}" ] && break
		kill -0 "$game" 2>/dev/null || break
		i=$((i + 1)); sleep 0.2
	done
	[ -n "${window:-}" ] || { echo "the game never opened a window"; tail -5 "$work/game.log"; exit 1; }
	DISPLAY=$display xdotool windowfocus --sync "$window" 2>/dev/null || true
	DISPLAY=$display xdotool mousemove --window "$window" 20 20 2>/dev/null || true
	sleep 3
}

press() { DISPLAY=$display xdotool key --clearmodifiers "$1"; sleep "${2:-1}"; }

echo "the menu"
start_game
press Escape 1
press Escape 2
shoot menu-main
press Down 0.5
press Return 2
shoot menu-options
press Escape 1.5
kill "$game" 2>/dev/null || true
wait "$game" 2>/dev/null || true

echo "the game"
# Through the engine's own capture harness rather than by driving the menu with
# xdotool: --tedlevel with a pinned RNG seed reaches the same frame of the same
# map every time, so this screenshot is reproducible rather than whatever the
# game happened to be showing when a screenshot tool ran.
( cd "$work/data" && timeout 120 env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
	DISPLAY=$display "$build_dir/ec7wolf" \
	--data CO7 --config "$work/cfg2" --savedir "$work/sv2" --res 1280 800 \
	--nowait --tedlevel MAP01 --skill 2 --capture-rngseed 1 \
	--capture-frame 60 --capture-glframe "$work/gl.ppm" --capture-maxframes 120 \
	) >"$work/capture.log" 2>&1 || true

if [ -f "$work/gl.ppm" ]; then
	python3 - "$work/gl.ppm" "$out/gameplay.png" <<'PYEOF'
import sys
from PIL import Image
Image.open(sys.argv[1]).save(sys.argv[2])
PYEOF
	printf '  %s\n' "$out/gameplay.png"
else
	printf '  no gameplay frame was captured; see %s\n' "$work/capture.log"
fi

echo "done"
