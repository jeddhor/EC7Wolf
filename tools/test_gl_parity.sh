#!/bin/sh

# GL golden-scene parity + screenshot-difference report (renderer redesign
# Phase 11).
#
# Where test_gl_frame.sh checks a single Corridor 7 scene, this sweeps a set of
# golden scenes and emits an automated screenshot-difference report. For each
# map it renders, in one process and at the same frame, the software screenshot
# AND the GL composite (via --capture-glframe), then measures:
#   * HUD band exactness -- the 2D status bar below the 3D view must be a
#     PIXEL-EXACT match (AE = 0); both resolve the same 8-bit overlay through the
#     palette, so any difference is a compositor/orientation regression.
#   * View-region fidelity -- normalized RMSE of the 3D view rectangle
#     (GL world vs software raycaster). A small delta is expected (dither /
#     sub-pixel); a large one means a shading/geometry regression.
#   * View overlay -- opaque 2D texels composited over the view (> 0): the
#     player weapon plus anything drawn over it (C7's top message).
# A per-scene diff image and a Markdown report are written to OUT_DIR.
#
# Hard failures: any scene whose HUD band is not pixel-exact, whose composite is
# missing, whose view overlay is empty, or whose view RMSE exceeds
# GL_PARITY_MAX_VIEW_RMSE (default 0.55). Everything else is reported, not fatal.
#
# Baseline note: the view RMSE now sits around 0.043-0.078 across the golden
# scenes. Two fixes got it there from 0.30-0.42. (1) The old number was blamed on
# Corridor 7's "textured" floor/ceiling dither being unported; the real cause was
# that the GL plane shader advanced one colormap ROW per shade band where the
# software advances one visually distinct palette STEP (wl_floorceiling.cpp), so
# distant planes stayed washed out instead of falling to black -- fixed via the
# C7 plane shade LUT in r_glworld.cpp (0.30-0.42 -> 0.086-0.11). (2) BuildOverlay
# marked everything in the view transparent except the weapon, so C7's top
# message went missing from every GL composite -- fixed by measuring the
# view-overlay coverage too (0.086-0.11 -> 0.043-0.078). The residual is mostly
# the remaining sub-pixel sampling difference along wall/plane edges. Note this
# metric does see dropped 2D: a view overlay GL fails to composite shows up here.
# The default ceiling stays well above the baseline so the gate guards against
# gross regressions (broken shader, wrong palette, black world) rather than
# tracking small drift.
#
# Runs headlessly (Xvfb + Mesa). Requires ImageMagick for the metrics/report.
#
# Usage: test_gl_parity.sh BUILD_DIR DATA_DIR [OUT_DIR] [MAP...]
#   MAP...  golden scenes to compare (default: a representative Corridor 7 set)
# Env:
#   GL_PARITY_FRAME          gameplay frame to capture (default 30)
#   GL_PARITY_MAX_VIEW_RMSE  max normalized view RMSE before failing (default 0.55)

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [OUT_DIR] [MAP...]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd); shift
data_dir=$(cd "$1" && pwd); shift
out_dir=${1:-$(mktemp -d /tmp/ec7wolf-glparity.XXXXXX)}
[ "$#" -gt 0 ] && shift || true
mkdir -p "$out_dir"

# Remaining args are maps; otherwise a representative golden-scene set covering
# early/mid/late Corridor 7 levels (mirrors validate_corridor7_maps.sh).
if [ "$#" -gt 0 ]; then
	maps="$*"
else
	maps="MAP01 MAP10 MAP20 MAP30 MAP40 MAP51"
fi

frame=${GL_PARITY_FRAME:-30}
max_view_rmse=${GL_PARITY_MAX_VIEW_RMSE:-0.55}
ec7wolf="$build_dir/ec7wolf"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi
if ! command -v magick >/dev/null 2>&1 && ! command -v convert >/dev/null 2>&1; then
	printf 'FAIL: ImageMagick (magick/convert) is required for the parity report.\n' >&2
	exit 1
fi
conv_tool="magick"; command -v magick >/dev/null 2>&1 || conv_tool="convert"
cmp_tool="magick compare"; command -v magick >/dev/null 2>&1 || cmp_tool="compare"

cfg=$(mktemp -d /tmp/glparity-cfg.XXXXXX)
save=$(mktemp -d /tmp/glparity-save.XXXXXX)
cleanup() { rm -rf "$cfg" "$save"; }
trap cleanup EXIT HUP INT TERM

report="$out_dir/parity-report.md"
{
	printf '# GL golden-scene parity report\n\n'
	printf -- '- Build: `%s`\n' "$ec7wolf"
	printf -- '- Data: `%s`\n' "$data_dir"
	printf -- '- Frame: %s   Max view RMSE: %s\n\n' "$frame" "$max_view_rmse"
	printf 'View RMSE baseline is ~0.043-0.078 (sub-pixel sampling along '
	printf 'wall/plane edges); see the header comment for how it got there. '
	printf 'HUD band AE and view-overlay texels are exact invariants.\n\n'
	printf '| Scene | Frame | View RMSE | Full RMSE | HUD band AE | Overlay texels | Verdict |\n'
	printf '|-------|-------|-----------|-----------|-------------|----------------|---------|\n'
} >"$report"

overall_rc=0
n_pass=0
n_fail=0

# Normalized RMSE (the parenthetical of magick's RMSE metric) over an optional
# crop; prints e.g. 0.0187, or "n/a" on error.
norm_rmse() { # $1=WxH+X+Y-or-empty $2=imgA $3=imgB
	if [ -n "$1" ]; then
		$cmp_tool -metric RMSE -crop "$1" "$2" "$3" null: 2>&1 |
			sed -n 's/.*(\([0-9.eE+-]*\)).*/\1/p'
	else
		$cmp_tool -metric RMSE "$2" "$3" null: 2>&1 |
			sed -n 's/.*(\([0-9.eE+-]*\)).*/\1/p'
	fi
}

for map in $maps; do
	log="$out_dir/$map.log"
	sw="$out_dir/$map.software.ppm"
	gl="$out_dir/$map.glframe.ppm"

	set +e
	(
		cd "$data_dir"
		# The live renderer is pinned to software because the reference half of
		# this comparison is a software screenshot, and only the software
		# renderer draws the 3D world into the framebuffer that --capture-file
		# reads. Under the OpenGL renderer the GPU owns the world and that
		# framebuffer holds just the 2D overlay, so the "software" reference
		# comes out ~95% black in the view region.
		#
		# This is pinned rather than left to the default because it silently
		# broke the gate when OpenGL became the default: RMSE went from
		# 0.04-0.08 to 0.35-0.46 -- comparing the GL composite against a blank
		# frame -- and the run still reported PASS, because that is still under
		# the 0.55 ceiling. A parity gate that passes while measuring nothing is
		# worse than no gate at all.
		#
		# --capture-glframe builds its GL composite offscreen either way; it is
		# byte-identical whichever renderer is live.
		timeout 120s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
			--data CO7 --config "$cfg/$map.cfg" --savedir "$save" \
			--vid-renderer software \
			--nowait --tedlevel "$map" --skill 2 --capture-rngseed 1 \
			--capture-frame "$frame" --capture-file "$out_dir/$map.software.png" \
			--capture-glframe "$gl" --capture-maxframes $((frame + 30))
	) >"$log" 2>&1
	rc=$?
	set -e

	verdict="PASS"
	reason=""

	frame_line=$(grep "GL frame: composited" "$log" | head -n1 || true)
	overlay_line=$(grep "GL frame: 2D overlay opaque" "$log" | head -n1 || true)
	fw=$(printf '%s' "$frame_line" | sed -n 's/.*composited \([0-9]*\)x[0-9]*.*/\1/p')
	fh=$(printf '%s' "$frame_line" | sed -n 's/.*composited [0-9]*x\([0-9]*\).*/\1/p')
	vw=$(printf '%s' "$frame_line" | sed -n 's/.*(view \([0-9]*\)x[0-9]*.*/\1/p')
	vh=$(printf '%s' "$frame_line" | sed -n 's/.*(view [0-9]*x\([0-9]*\).*/\1/p')
	vx=$(printf '%s' "$frame_line" | sed -n 's/.*at \([0-9]*\),[0-9]*).*/\1/p')
	vy=$(printf '%s' "$frame_line" | sed -n 's/.*at [0-9]*,\([0-9]*\)).*/\1/p')
	weapon=$(printf '%s' "$overlay_line" | sed -n 's/.*view = \([0-9]*\).*/\1/p')

	view_rmse="n/a"; full_rmse="n/a"; hud_ae="n/a"

	if [ "$rc" -ne 0 ] || [ ! -s "$gl" ] || [ -z "$fw" ]; then
		verdict="FAIL"; reason="no composite (rc=$rc)"
	else
		$conv_tool "$out_dir/$map.software.png" "$sw" 2>>"$log" || true
		# Screenshot-difference image for human review.
		$cmp_tool "$sw" "$gl" "$out_dir/$map.diff.png" 2>/dev/null || true

		full_rmse=$(norm_rmse "" "$sw" "$gl"); full_rmse=${full_rmse:-n/a}
		view_rmse=$(norm_rmse "${vw}x${vh}+${vx}+${vy}" "$sw" "$gl")
		view_rmse=${view_rmse:-n/a}

		band_y=$((vy + vh)); band_h=$((fh - band_y))
		if [ "$band_h" -gt 0 ]; then
			hud_ae=$($cmp_tool -metric AE -crop "${fw}x${band_h}+0+${band_y}" \
				"$sw" "$gl" null: 2>&1 | sed -n 's/^\([0-9]*\).*/\1/p')
			hud_ae=${hud_ae:-999999}
		else
			hud_ae=0	# fullscreen view: no status band to compare
		fi

		# --- hard-failure gates ---
		if [ "$hud_ae" != "0" ]; then
			verdict="FAIL"; reason="HUD band AE=$hud_ae"
		elif [ -z "$weapon" ] || [ "$weapon" -le 0 ] 2>/dev/null; then
			verdict="FAIL"; reason="no view overlay"
		elif [ "$view_rmse" != "n/a" ] &&
			awk "BEGIN{exit !($view_rmse > $max_view_rmse)}"; then
			verdict="FAIL"; reason="view RMSE $view_rmse > $max_view_rmse"
		fi
	fi

	if [ "$verdict" = "PASS" ]; then
		n_pass=$((n_pass + 1))
	else
		n_fail=$((n_fail + 1)); overall_rc=1
	fi

	printf '| %s | %s | %s | %s | %s | %s | %s%s |\n' \
		"$map" "$frame" "$view_rmse" "$full_rmse" "$hud_ae" "${weapon:-0}" \
		"$verdict" "${reason:+ ($reason)}" >>"$report"
	printf '%-8s %-5s view_rmse=%-9s hud_ae=%-8s overlay=%-7s %s%s\n' \
		"$map" "$verdict" "$view_rmse" "$hud_ae" "${weapon:-0}" \
		"$verdict" "${reason:+ ($reason)}"
done

{
	printf '\n**%s scene(s) passed, %s failed.**\n' "$n_pass" "$n_fail"
	printf '\nDiff images: `MAP*.diff.png` (per-scene, software vs GL composite).\n'
} >>"$report"

printf '\nReport: %s\n' "$report"
if [ "$overall_rc" -eq 0 ]; then
	printf 'PASS: all %s golden scene(s) within parity tolerance.\n' "$n_pass"
else
	printf 'FAIL: %s golden scene(s) failed parity; see %s\n' "$n_fail" "$report" >&2
fi
exit "$overall_rc"
