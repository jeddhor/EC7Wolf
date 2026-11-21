#!/bin/sh
# HUD card cycling, the visor after death and the quicksave slot (GitHub #41,
# #44, #45, #46). Runs the game in its own Xvfb display; never touches the
# player's saves or configuration.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-ui_fixes.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a -s "-screen 0 640x400x24" python3 "$repo/tools/test_corridor7_ui_fixes.py" \
	"$build_dir" "$data_dir" "$work/w"
