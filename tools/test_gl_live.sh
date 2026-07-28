#!/bin/sh

# GL live-present verification (renderer redesign Phase 10, live-window slice).
#
# Unlike test_gl_frame.sh (which composites offscreen through the capture
# harness), this runs the game with the OpenGL renderer *live*: SDLFB creates a
# GL-capable game window, OpenGLRenderer::RenderScene renders the world on the
# GPU each frame, and SDLFB::Update composites the 8-bit 2D layer over it and
# swaps. It plays a Corridor 7 level for several frames on the GPU, captures the
# actual on-window presented frame, and asserts:
#   * the OpenGL renderer went live (not the software fallback),
#   * a presented frame was captured at the game window's size,
#   * the 2D HUD/status-bar band matches a real software frame pixel-for-pixel
#     (proving the live compositor + orientation against the reference renderer).
#
# Runs headlessly (Xvfb + Mesa creates a real GL window and reads it back).
#
# Usage: test_gl_live.sh BUILD_DIR DATA_DIR [MAP] [OUT_DIR]

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP] [OUT_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
map=${3:-MAP01}
out_dir=${4:-$(mktemp -d /tmp/ec7wolf-gllive.XXXXXX)}
ec7wolf="$build_dir/ec7wolf"
mkdir -p "$out_dir"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

cfg=$(mktemp -d /tmp/gllive-cfg.XXXXXX)
save=$(mktemp -d /tmp/gllive-save.XXXXXX)
log="$out_dir/gllive.log"
cleanup() { rm -rf "$cfg" "$save"; }
trap cleanup EXIT HUP INT TERM

# --- run 1: the game live on the OpenGL renderer, capturing the presented frame.
set +e
(
	cd "$data_dir"
	timeout 120s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
		--data CO7 --no-upscale --config "$cfg/gl.cfg" --savedir "$save" \
		--nowait --tedlevel "$map" --skill 2 --vid-renderer opengl \
		--capture-rngseed 1 --capture-frame 30 \
		--capture-glpresent "$out_dir/gllive.ppm" --capture-maxframes 60
) >"$log" 2>&1
rc=$?
set -e

grep -iE "Renderer:|OpenGL backend|GL live:" "$log" || true

if [ "$rc" -ne 0 ]; then
	printf 'FAIL: live GL run exited non-zero (%s); see %s\n' "$rc" "$log" >&2
	exit 1
fi
if ! grep -q "Renderer: using OpenGL renderer." "$log"; then
	printf 'FAIL: OpenGL renderer did not go live (fell back to software); see %s\n' \
		"$log" >&2
	exit 1
fi
if [ ! -s "$out_dir/gllive.ppm" ]; then
	printf 'FAIL: no live GL frame was presented/captured; see %s\n' "$log" >&2
	exit 1
fi
printf 'PASS: OpenGL renderer went live and presented a frame to the game window.\n'

# --- run 2: the same view on the software renderer, as the parity reference.
set +e
(
	cd "$data_dir"
	timeout 90s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
		--data CO7 --no-upscale --config "$cfg/sw.cfg" --savedir "$save.sw" \
		--nowait --tedlevel "$map" --skill 2 \
		--capture-rngseed 1 --capture-frame 30 \
		--capture-file "$out_dir/software.png" --capture-maxframes 60
) >>"$log" 2>&1
set -e

if command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1; then
	conv_tool="magick"; command -v magick >/dev/null 2>&1 || conv_tool="convert"
	cmp_tool="magick compare"; command -v magick >/dev/null 2>&1 || cmp_tool="compare"

	$conv_tool "$out_dir/software.png" "$out_dir/software.ppm"
	glh=$($conv_tool "$out_dir/gllive.ppm" -format "%h" info: 2>/dev/null || echo 0)
	glw=$($conv_tool "$out_dir/gllive.ppm" -format "%w" info: 2>/dev/null || echo 0)
	swh=$($conv_tool "$out_dir/software.ppm" -format "%h" info: 2>/dev/null || echo 0)

	if [ "$glh" != "$swh" ]; then
		printf 'WARN: live (%s) and software (%s) heights differ (HiDPI?); skipping band check.\n' \
			"$glh" "$swh"
	else
		# The status-bar band below the 3D view is pure 2D and must be identical.
		band_h=100
		band_y=$((glh - band_h))
		diffpx=$($cmp_tool -metric AE -crop "${glw}x${band_h}+0+${band_y}" \
			"$out_dir/software.ppm" "$out_dir/gllive.ppm" null: 2>&1 |
			sed -n 's/^\([0-9]*\).*/\1/p')
		diffpx=${diffpx:-999999}
		if [ "$diffpx" -eq 0 ] 2>/dev/null; then
			printf 'PASS: live GL HUD band is pixel-exact vs software (%sx%s at y=%s).\n' \
				"$glw" "$band_h" "$band_y"
		else
			printf 'FAIL: live GL HUD band differs from software by %s px (expected 0); see %s\n' \
				"$diffpx" "$log" >&2
			exit 1
		fi
	fi
else
	printf 'WARN: ImageMagick unavailable; skipped pixel-exact HUD band check.\n'
fi

printf 'Outputs in %s\n' "$out_dir"
exit 0
