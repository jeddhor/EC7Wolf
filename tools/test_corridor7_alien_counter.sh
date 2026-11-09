#!/bin/sh
# Burst kills, save reconciliation, and actual elevator clearance. Fixtures
# change only disposable maps/actor definitions, never the player's game data.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-counter.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 "$repo/tools/test_corridor7_alien_counter.py" "$build_dir" "$data_dir" "$work"
