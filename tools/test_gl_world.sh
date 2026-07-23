#!/bin/sh

# GL static-world render verification (renderer redesign Phase 5).
#
# Loads a Corridor 7 map, and at a chosen frame renders the software screenshot
# AND the GL static-world offscreen render of the same view. Asserts the world
# mesh was built (walls > 0) and the GL render is non-blank. Runs headlessly
# (Xvfb + Mesa is fine).
#
# Usage: test_gl_world.sh BUILD_DIR DATA_DIR [MAP] [OUT_DIR]

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP] [OUT_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
map=${3:-MAP01}
out_dir=${4:-$(mktemp -d /tmp/ec7wolf-glworld.XXXXXX)}
ec7wolf="$build_dir/ec7wolf"
mkdir -p "$out_dir"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

cfg=$(mktemp -d /tmp/glworld-cfg.XXXXXX)
save=$(mktemp -d /tmp/glworld-save.XXXXXX)
log="$out_dir/glworld.log"
cleanup() { rm -rf "$cfg" "$save"; }
trap cleanup EXIT HUP INT TERM

set +e
(
	cd "$data_dir"
	timeout 90s env SDL_AUDIODRIVER=dummy xvfb-run -a "$ec7wolf" \
		--data CO7 --config "$cfg/ec7wolf.cfg" --savedir "$save" \
		--nowait --tedlevel "$map" --skill 2 --capture-rngseed 1 \
		--capture-frame 30 --capture-file "$out_dir/software.png" \
		--capture-glworld "$out_dir/glworld.ppm" --capture-maxframes 60
) >"$log" 2>&1
set -e

grep -iE "GL world: mesh|GL world: rendered" "$log" || true

mesh_line=$(grep "GL world: mesh" "$log" || true)
walls=$(printf '%s' "$mesh_line" | sed -n 's/.*walls=\([0-9]*\).*/\1/p')
covered=$(grep "GL world: rendered" "$log" | sed -n 's/.*, \([0-9.]*\)% covered.*/\1/p')

if [ -z "$walls" ] || [ "$walls" -le 0 ] 2>/dev/null; then
	printf 'FAIL: world mesh not built (see %s)\n' "$log" >&2
	exit 1
fi
if [ ! -s "$out_dir/glworld.ppm" ]; then
	printf 'FAIL: GL world render not written\n' >&2
	exit 1
fi

printf 'PASS: GL static world rendered (walls=%s, coverage=%s%%). Outputs in %s\n' \
	"$walls" "${covered:-?}" "$out_dir"
exit 0
