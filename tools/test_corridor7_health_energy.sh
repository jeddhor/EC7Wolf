#!/bin/sh
# The health maximum and alien energy follow CORR7CD.EXE (GitHub #32, #34).
# Fixtures change only disposable lab maps, never the player's game data.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-health_energy.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 "$repo/tools/test_corridor7_health_energy.py" "$build_dir" "$data_dir" "$work"
