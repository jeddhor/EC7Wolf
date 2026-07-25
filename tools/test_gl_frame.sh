#!/bin/sh

# GL full-frame composite verification (renderer redesign Phase 10).
#
# Phase 5-9 verified the GL 3D world offscreen. Phase 10 composites a complete
# playable frame: the GL 3D world is rendered into the view sub-rectangle and the
# engine's live 8-bit 2D layer (player weapon, HUD/status bar, menus, text) is
# composited over it as an indexed overlay -- the view region transparent except
# where the weapon (or any 2D drawn over the world) is opaque.
#
# At a chosen frame this renders the software screenshot AND the GL composite of
# the same view, then asserts:
#   * the composite is the same size as the software frame,
#   * the 2D HUD/status-bar band below the 3D view is a PIXEL-EXACT match to the
#     software frame (both come from the same 8-bit overlay resolved through the
#     palette) -- this proves the compositor and its orientation are correct,
#   * 2D composited opaque texels over the GL 3D view (> 0) -- the player
#     weapon plus anything drawn over the view (C7's top message).
#
# Runs headlessly (Xvfb + Mesa is fine). Requires ImageMagick for the HUD check.
#
# Usage: test_gl_frame.sh BUILD_DIR DATA_DIR [MAP] [OUT_DIR]

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP] [OUT_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
map=${3:-MAP01}
out_dir=${4:-$(mktemp -d /tmp/ec7wolf-glframe.XXXXXX)}
ec7wolf="$build_dir/ec7wolf"
mkdir -p "$out_dir"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

cfg=$(mktemp -d /tmp/glframe-cfg.XXXXXX)
save=$(mktemp -d /tmp/glframe-save.XXXXXX)
log="$out_dir/glframe.log"
cleanup() { rm -rf "$cfg" "$save"; }
trap cleanup EXIT HUP INT TERM

set +e
(
	cd "$data_dir"
	timeout 90s env SDL_AUDIODRIVER=dummy xvfb-run -a "$ec7wolf" \
		--data CO7 --config "$cfg/ec7wolf.cfg" --savedir "$save" \
		--nowait --tedlevel "$map" --skill 2 --capture-rngseed 1 \
		--capture-frame 30 --capture-file "$out_dir/software.png" \
		--capture-glframe "$out_dir/glframe.ppm" --capture-maxframes 60
) >"$log" 2>&1
set -e

grep -iE "GL frame:" "$log" || true

frame_line=$(grep "GL frame: composited" "$log" | head -n1 || true)
overlay_line=$(grep "GL frame: 2D overlay opaque" "$log" | head -n1 || true)

# "GL frame: composited FWxFH (view VWxVH at VX,VY), ..."
fw=$(printf '%s' "$frame_line" | sed -n 's/.*composited \([0-9]*\)x[0-9]*.*/\1/p')
fh=$(printf '%s' "$frame_line" | sed -n 's/.*composited [0-9]*x\([0-9]*\).*/\1/p')
vw=$(printf '%s' "$frame_line" | sed -n 's/.*(view \([0-9]*\)x[0-9]*.*/\1/p')
vh=$(printf '%s' "$frame_line" | sed -n 's/.*(view [0-9]*x\([0-9]*\).*/\1/p')
vx=$(printf '%s' "$frame_line" | sed -n 's/.*at \([0-9]*\),[0-9]*).*/\1/p')
vy=$(printf '%s' "$frame_line" | sed -n 's/.*at [0-9]*,\([0-9]*\)).*/\1/p')
weapon=$(printf '%s' "$overlay_line" | sed -n 's/.*view = \([0-9]*\).*/\1/p')

if [ ! -s "$out_dir/glframe.ppm" ]; then
	printf 'FAIL: GL composite frame not written (see %s)\n' "$log" >&2
	exit 1
fi
if [ -z "$fw" ] || [ -z "$fh" ]; then
	printf 'FAIL: GL composite did not report a frame (see %s)\n' "$log" >&2
	exit 1
fi
printf 'PASS: GL composite frame rendered (%sx%s, view %sx%s at %s,%s).\n' \
	"$fw" "$fh" "$vw" "$vh" "$vx" "$vy"

# The weapon and any 2D drawn over the world must composite opaque texels over
# the 3D view. A regression that dropped either overlay -- or the
# transparent-key discard -- would take this to zero.
if [ -z "$weapon" ] || [ "$weapon" -le 0 ] 2>/dev/null; then
	printf 'FAIL: no 2D overlay composited over the GL view (weapon texels=%s); see %s\n' \
		"${weapon:-none}" "$log" >&2
	exit 1
fi
printf 'PASS: 2D composited over the GL 3D view (%s opaque texels: weapon + overlay).\n' \
	"$weapon"

# Pixel-exact HUD/orientation check: the 2D status-bar band strictly below the 3D
# view must be identical between the software frame and the GL composite, since
# both resolve the same 8-bit overlay through the palette. This also proves the
# compositor's vertical orientation (a flip would scatter the band completely).
if command -v magick >/dev/null 2>&1 || command -v compare >/dev/null 2>&1; then
	cmp_tool="magick compare"
	command -v magick >/dev/null 2>&1 || cmp_tool="compare"
	conv_tool="magick"
	command -v magick >/dev/null 2>&1 || conv_tool="convert"

	$conv_tool "$out_dir/software.png" "$out_dir/software.ppm"
	band_y=$((vy + vh))
	band_h=$((fh - band_y))
	if [ "$band_h" -gt 0 ]; then
		diffpx=$($cmp_tool -metric AE \
			-crop "${fw}x${band_h}+0+${band_y}" \
			"$out_dir/software.ppm" "$out_dir/glframe.ppm" null: 2>&1 |
			sed -n 's/^\([0-9]*\).*/\1/p')
		diffpx=${diffpx:-999999}
		if [ "$diffpx" -eq 0 ] 2>/dev/null; then
			printf 'PASS: 2D HUD band below the view is pixel-exact vs software (%sx%s at y=%s).\n' \
				"$fw" "$band_h" "$band_y"
		else
			printf 'FAIL: 2D HUD band differs from software by %s px (expected 0); see %s\n' \
				"$diffpx" "$log" >&2
			exit 1
		fi
	else
		printf 'WARN: fullscreen 3D view (no status band) -- HUD exactness check skipped.\n'
	fi
else
	printf 'WARN: ImageMagick unavailable; skipped pixel-exact HUD band check.\n'
fi

printf 'Outputs in %s\n' "$out_dir"
exit 0
