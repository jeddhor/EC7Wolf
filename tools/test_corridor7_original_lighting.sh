#!/bin/sh
# Corridor 7's own shading, Lighting = Original (GitHub #57): the original's
# floor and ceiling pattern, and floor 26's walls shaded as DOS shades them.
# Fixtures change only disposable lab maps, never the player's game data.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-original_lighting.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a -s "-screen 0 640x400x24" python3 "$repo/tools/test_corridor7_original_lighting.py" "$build_dir" "$data_dir" "$work"
