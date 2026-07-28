#!/bin/sh

# GL video-mode-change verification (renderer redesign Phase 11).
#
# Every live GL resource -- shaders, palette/colormap/LUT textures, the world
# FBO, the per-map index texture caches -- belongs to the window's GL context.
# A video mode change destroys that context: V_SetResolution deletes the SDLFB
# (whose destructor deletes the context) and builds a new one. Toggling
# fullscreen goes the same way, because VL_SetFullscreen swaps screenWidth and
# screenHeight to the fullscreen or windowed pair, which almost always changes
# the resolution and so takes the recreate branch rather than reusing the
# window. Object names from the dead context are meaningless in its
# replacement, so without an explicit teardown the compositor draws with dead
# handles and presents a black window until the game is restarted.
#
# This drives that path headlessly with --capture-vidmode, which performs the
# same mode change the Display menu does, then captures the frame the live GL
# renderer presents afterwards. For each case it asserts:
#   * the OpenGL renderer went live (not the software fallback),
#   * the presented frame is at the NEW mode's size and is not black,
#   * its 2D HUD/status-bar band matches a software run that switched mode
#     identically, pixel-for-pixel,
#   * the GL object ledger still balances at exit, so the mid-run teardown and
#     rebuild neither leaked nor double-freed.
#
# Cases: shrink, grow, two switches in one run (the second exercises tearing
# down a context that was itself built after a previous teardown), and a switch
# with the Corridor 7 visor on. The visor case matters because it is the one
# reported from play: Alt+Enter also delivered Enter, so the mode change happened
# with extralight pinned high, and the GL plane shade table's "which firstShade
# is loaded" cache used to be a function-local static. It outlived the texture,
# so the rebuilt table (always firstShade 5) was never refilled and the planes
# were shaded for the wrong extralight.
#
# Runs headlessly (Xvfb + Mesa creates a real GL window and reads it back).
# Requires ImageMagick for the HUD band comparison.
#
# Usage: test_gl_modeswitch.sh BUILD_DIR DATA_DIR [MAP] [OUT_DIR]

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP] [OUT_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
map=${3:-MAP01}
out_dir=${4:-$(mktemp -d /tmp/ec7wolf-glmode.XXXXXX)}
ec7wolf="$build_dir/ec7wolf"
mkdir -p "$out_dir"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi
if ! command -v magick >/dev/null 2>&1 && ! command -v convert >/dev/null 2>&1; then
	printf 'FAIL: ImageMagick (magick/convert) is required.\n' >&2
	exit 1
fi
conv_tool="magick"; command -v magick >/dev/null 2>&1 || conv_tool="convert"
cmp_tool="magick compare"; command -v magick >/dev/null 2>&1 || cmp_tool="compare"

cfg=$(mktemp -d /tmp/glmode-cfg.XXXXXX)
save=$(mktemp -d /tmp/glmode-save.XXXXXX)
cleanup() { rm -rf "$cfg" "$save"; }
trap cleanup EXIT HUP INT TERM

# The Xvfb screen must be at least as large as the biggest mode used below.
screen_geom="1024x768x24"
capture_frame=40
n_fail=0

# run_case NAME "SWITCH_ARGS..." EXPECT_W EXPECT_H
run_case() {
	name=$1; switches=$2; expw=$3; exph=$4
	gl="$out_dir/$name.gl.ppm"
	swpng="$out_dir/$name.sw.png"
	sw="$out_dir/$name.sw.ppm"
	log="$out_dir/$name.log"

	# Live GL, switching mode mid-run.
	set +e
	# shellcheck disable=SC2086
	(
		cd "$data_dir"
		timeout 180s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a -s "-screen 0 $screen_geom" \
			"$ec7wolf" --data CO7 --no-upscale --config "$cfg/$name.gl.cfg" --savedir "$save" \
			--nowait --tedlevel "$map" --skill 2 --vid-renderer opengl \
			--capture-rngseed 1 $switches \
			--capture-frame "$capture_frame" --capture-glpresent "$gl" \
			--capture-maxframes $((capture_frame + 20))
	) >"$log" 2>&1
	rc=$?
	set -e

	if [ "$rc" -ne 0 ] || [ ! -s "$gl" ]; then
		printf 'FAIL: %-10s live GL run produced no frame (rc=%s); see %s\n' \
			"$name" "$rc" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi
	if ! grep -q "Renderer: using OpenGL renderer." "$log"; then
		printf 'FAIL: %-10s OpenGL renderer fell back to software; see %s\n' \
			"$name" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi

	w=$($conv_tool "$gl" -format "%w" info:)
	h=$($conv_tool "$gl" -format "%h" info:)
	if [ "$w" != "$expw" ] || [ "$h" != "$exph" ]; then
		printf 'FAIL: %-10s presented %sx%s, expected the new mode %sx%s; see %s\n' \
			"$name" "$w" "$h" "$expw" "$exph" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi

	# The whole point: after the mode change the window must not be black. Use
	# the mean rather than a pixel count so a frame that is merely very dark
	# still fails.
	mean=$($conv_tool "$gl" -colorspace gray -format "%[fx:int(mean*1000)]" info:)
	if [ "$mean" -le 5 ] 2>/dev/null; then
		printf 'FAIL: %-10s presented a black frame after the mode change (mean=%s/1000); see %s\n' \
			"$name" "$mean" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi

	# Software reference, switching mode identically.
	set +e
	# shellcheck disable=SC2086
	(
		cd "$data_dir"
		timeout 180s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a -s "-screen 0 $screen_geom" \
			"$ec7wolf" --data CO7 --no-upscale --config "$cfg/$name.sw.cfg" --savedir "$save" \
			--nowait --tedlevel "$map" --skill 2 \
			--capture-rngseed 1 $switches \
			--capture-frame "$capture_frame" --capture-file "$swpng" \
			--capture-maxframes $((capture_frame + 20))
	) >>"$log" 2>&1
	set -e

	if [ ! -s "$swpng" ]; then
		printf 'FAIL: %-10s no software reference frame; see %s\n' "$name" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi
	$conv_tool "$swpng" "$sw"

	# The status bar is the bottom 40 of the 200-row virtual screen; it is pure
	# 2D resolved through the palette by both renderers, so it must be identical.
	band_h=$((h * 40 / 200))
	band_y=$((h - band_h))
	diffpx=$($cmp_tool -metric AE -crop "${w}x${band_h}+0+${band_y}" \
		"$sw" "$gl" null: 2>&1 | sed -n 's/^\([0-9]*\).*/\1/p')
	diffpx=${diffpx:-999999}
	if [ "$diffpx" -ne 0 ] 2>/dev/null; then
		printf 'FAIL: %-10s HUD band differs from software by %s px after the mode change; see %s\n' \
			"$name" "$diffpx" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi

	# The teardown must free exactly what it built: a mid-run rebuild that leaked
	# or double-freed shows up in the exit ledger.
	if ! grep -q "GL live: 0 leaked GL objects" "$log"; then
		printf 'FAIL: %-10s GL object ledger did not balance across the mode change; see %s\n' \
			"$name" "$log" >&2
		n_fail=$((n_fail + 1)); return
	fi

	printf 'PASS: %-10s %sx%s after the mode change, HUD pixel-exact, ledger balanced.\n' \
		"$name" "$w" "$h"
}

run_case shrink  "--capture-vidmode 320 200 10"                           320 200
run_case grow    "--capture-vidmode 800 600 10"                           800 600
run_case twice   "--capture-vidmode 320 200 10 --capture-vidmode 640 480 25" 640 480
run_case visor   "--capture-extralight 20 --capture-vidmode 320 200 10"    320 200

printf '\nOutputs in %s\n' "$out_dir"
if [ "$n_fail" -eq 0 ]; then
	printf 'PASS: live GL survives video mode changes (context teardown + rebuild).\n'
	exit 0
fi
printf 'FAIL: %s mode-change case(s) failed.\n' "$n_fail" >&2
exit 1
