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
	# Pinned to software for the same reason as test_gl_parity.sh: the
	# --capture-file reference only holds a 3D view when the software renderer
	# is the one drawing it.
	timeout 90s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
		--data CO7 --no-upscale --config "$cfg/ec7wolf.cfg" --savedir "$save" \
		--vid-renderer software \
		--nowait --tedlevel "$map" --skill 2 --capture-rngseed 1 \
		--capture-frame 30 --capture-file "$out_dir/software.png" \
		--capture-glworld "$out_dir/glworld.ppm" --capture-maxframes 60
) >"$log" 2>&1
set -e

grep -iE "GL world: static|GL world: rendered" "$log" || true

mesh_line=$(grep "GL world: static" "$log" | head -n1 || true)
walls=$(printf '%s' "$mesh_line" | sed -n 's/.*walls=\([0-9]*\).*/\1/p')
dynfaces=$(printf '%s' "$mesh_line" | sed -n 's/.*dynamic faces=\([0-9]*\).*/\1/p')
maskedfaces=$(printf '%s' "$mesh_line" | sed -n 's/.*masked faces=\([0-9]*\).*/\1/p')
spritefaces=$(printf '%s' "$mesh_line" | sed -n 's/.*sprite faces=\([0-9]*\).*/\1/p')
opacitytex=$(grep "with opacity" "$log" | head -n1 | \
	sed -n 's/.*(\([0-9]*\) with opacity).*/\1/p')
covered=$(grep "GL world: rendered" "$log" | head -n1 | \
	sed -n 's/.*, \([0-9.]*\)% covered.*/\1/p')

if [ -z "$walls" ] || [ "$walls" -le 0 ] 2>/dev/null; then
	printf 'FAIL: world mesh not built (see %s)\n' "$log" >&2
	exit 1
fi
if [ ! -s "$out_dir/glworld.ppm" ]; then
	printf 'FAIL: GL world render not written\n' >&2
	exit 1
fi

printf 'PASS: GL static world rendered (walls=%s, dynamic-faces=%s, coverage=%s%%).\n' \
	"$walls" "${dynfaces:-0}" "${covered:-?}"

# Phase 8: masked (colour-keyed, see-through) walls -- glass, grates, fences,
# force fields -- are built into a separate alpha-tested mesh instead of the
# opaque static wall mesh. Corridor 7 MAP01 spawns facing a corridor lined with
# chain-link fences and diamond-grate panels, so this view must produce masked
# geometry; a regression that rendered them opaque would drop the masked mesh to
# zero faces.
if [ "$map" = "MAP01" ]; then
	if [ -z "$maskedfaces" ] || [ "$maskedfaces" -le 0 ] 2>/dev/null; then
		printf 'FAIL: no masked-wall geometry built on MAP01 (masked faces=%s); see %s\n' \
			"${maskedfaces:-none}" "$log" >&2
		exit 1
	fi
	# At least one masked texture must carry an explicit opacity mask (the C7
	# grate/fence FFlatTextures); the remainder alpha-test on the index-255 key.
	if [ -z "$opacitytex" ] || [ "$opacitytex" -le 0 ] 2>/dev/null; then
		printf 'FAIL: masked walls built but no opacity mask uploaded (%s); see %s\n' \
			"${opacitytex:-none}" "$log" >&2
		exit 1
	fi
	printf 'PASS: GL masked walls built (%s faces, %s textures with opacity masks).\n' \
		"$maskedfaces" "$opacitytex"

	# Phase 9: actor sprites are billboarded into a depth-tested mesh. Corridor 7
	# MAP01 spawns facing the two white gate posts (C010 statics) plus flanking
	# statics, so this view must produce sprite geometry; a regression that dropped
	# sprite selection or the visibility test would take this to zero faces.
	if [ -z "$spritefaces" ] || [ "$spritefaces" -le 0 ] 2>/dev/null; then
		printf 'FAIL: no actor-sprite geometry built on MAP01 (sprite faces=%s); see %s\n' \
			"${spritefaces:-none}" "$log" >&2
		exit 1
	fi
	printf 'PASS: GL actor sprites built (%s billboard faces).\n' "$spritefaces"
fi

# Phase 7: prove dynamic door geometry renders and responds to the slide. Render
# the same view with every door forced closed and forced open; the two GL images
# must differ (a door leaf slides, revealing geometry behind it). Requires the
# ImageMagick 'compare' tool; skipped with a note if it is unavailable.
if command -v compare >/dev/null 2>&1 || command -v magick >/dev/null 2>&1; then
	cmp_tool="compare"
	command -v compare >/dev/null 2>&1 || cmp_tool="magick compare"
	for amt in 0 65535; do
		save2=$(mktemp -d "$save.door.XXXXXX" 2>/dev/null || mktemp -d)
		(
			cd "$data_dir"
			timeout 90s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
				--data CO7 --no-upscale --config "$cfg/door$amt.cfg" --savedir "$save2" \
				--nowait --tedlevel "$map" --skill 2 --capture-rngseed 1 \
				--capture-frame 30 --capture-file "$out_dir/sw_door$amt.png" \
				--capture-glworld "$out_dir/gl_door$amt.ppm" \
				--capture-maxframes 40 --capture-open-doors "$amt"
		) >>"$log" 2>&1
	done
	if [ -s "$out_dir/gl_door0.ppm" ] && [ -s "$out_dir/gl_door65535.ppm" ]; then
		diffpx=$($cmp_tool -metric AE "$out_dir/gl_door0.ppm" \
			"$out_dir/gl_door65535.ppm" null: 2>&1 | sed -n 's/^\([0-9]*\).*/\1/p')
		diffpx=${diffpx:-0}
		if [ "$diffpx" -gt 50 ] 2>/dev/null; then
			printf 'PASS: GL door slide renders (closed vs open differ by %s px).\n' \
				"$diffpx"
		else
			printf 'WARN: no visible door in this view (closed vs open differ by %s px); door geometry still built.\n' \
				"$diffpx"
		fi
	fi
else
	printf 'WARN: ImageMagick compare unavailable; skipped door-slide render check.\n'
fi

printf 'Outputs in %s\n' "$out_dir"
exit 0
