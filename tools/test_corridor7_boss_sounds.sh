#!/bin/sh
# A boss is heard only from the player's area, as in CORR7CD.EXE (GitHub #50).
# Fixtures change only disposable lab maps, never the player's game data.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-boss_sounds.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 "$repo/tools/test_corridor7_boss_sounds.py" "$build_dir" "$data_dir" "$work"
