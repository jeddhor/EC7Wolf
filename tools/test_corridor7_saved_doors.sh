#!/bin/sh
# An open force-field door stays open across a save and load (GitHub #58).
# Fixtures change only disposable lab maps, never the player's game data.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-saved_doors.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 "$repo/tools/test_corridor7_saved_doors.py" "$build_dir" "$data_dir" "$work"
