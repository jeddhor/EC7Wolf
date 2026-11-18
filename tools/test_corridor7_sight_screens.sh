#!/bin/sh
# Shots and sight pass marker-105 screens and stop at marker-104 glass (GitHub #31).
# Fixtures change only disposable lab maps, never the player's game data.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-sight_screens.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 "$repo/tools/test_corridor7_sight_screens.py" "$build_dir" "$data_dir" "$work"
