#!/bin/sh

# Regression test: the player's weapon is not eaten by a door sliding open.
#
# Under OpenGL the view model is a screen-space quad drawn through the same
# program as the world, so every uniform RenderMesh can set has to be answered
# before it is drawn. uSlide was the one that was not. A door leaf leaves it at
# 1 with the door's own slide amount, and the shader's door branch then
# discards the fragments the door has opened -- `if(open) discard;` -- and
# shifts what is left by `uv.x = fract(intercept + off)`. The weapon is carved
# away and slides sideways exactly in step with the door.
#
# It hid because the sprite pass runs after the doors and resets uSlide on its
# way past: on a floor with anything visible in it the weapon is fine, and only
# a door with an empty view behind it shows the fault. That is why this uses a
# generated corridor with a door and nothing else rather than a shipped map --
# MAP01's door does not reproduce it.
#
# Asserted by parity against the software renderer, which is unaffected. One
# process draws both -- software live for --capture-file, --capture-glframe for
# the GL composite -- so the two pictures are the same tic by construction.
# With the bug the weapon rectangle's RMSE is 0.21; without it, 0.047, which is
# the ordinary parity baseline for any frame.
#
# Usage: test_gl_viewmodel_door.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)

if ! command -v magick >/dev/null 2>&1 && ! command -v compare >/dev/null 2>&1; then
	printf 'SKIP: ImageMagick (magick/compare) is not installed\n'
	exit 0
fi
cmp_tool="magick compare"; command -v magick >/dev/null 2>&1 || cmp_tool="compare"

work=$(mktemp -d /tmp/ec7wolf-vmdoor.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# The weapon quad at --res 320 200: R_GetPlayerSpriteInfo places the 48x51
# ready frame at 132,94 and steps it at 0.805 texels per pixel, so it covers
# 60x64 pixels from there. The view itself is 320x158 at 0,0.
weapon_rect=60x64+132+94
view_rect=320x158+0+0
max_rmse=${GL_VIEWMODEL_MAX_RMSE:-0.12}
min_scene_change=0.02

# A corridor with a door six tiles east of the player and nothing else in it.
python3 "$here/make_corridor7_ai_lab.py" \
	"$data_dir/MAPTEMP.CO7" "$work/MAPTEMP.CO7" door:10 >/dev/null

for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] || continue
	case $(basename "$f") in MAPTEMP.CO7) continue ;; esac
	cp "$f" "$work/"
done
cp "$build_dir/ec7wolf.pk3" "$work/" 2>/dev/null || true

shoot() { # $1 = frame, $2 = tag
	(
		cd "$work"
		timeout 180s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 640x400x24' \
			"$build_dir/ec7wolf" --data CO7 --no-upscale --nowait \
			--res 320 200 --vid-renderer software \
			--config "$work/cfg$2" --savedir "$work/save$2" \
			--tedlevel MAP01 --skill 2 --capture-rngseed 1 \
			--capture-place 10 9.5 32.5 0 --capture-use 20 6 \
			--capture-maxframes $(($1 + 30)) --capture-frame "$1" \
			--capture-file "$work/$2.sw.png" --capture-glframe "$work/$2.gl.ppm"
	) >"$work/$2.log" 2>&1
	if [ ! -s "$work/$2.sw.png" ] || [ ! -s "$work/$2.gl.ppm" ]; then
		printf 'FAIL: %s produced no pair of frames; see %s\n' "$2" "$work/$2.log"
		return 1
	fi
}

rmse() { # $1 = crop, $2 = a, $3 = b -- the normalized figure magick parenthesises
	$cmp_tool -metric RMSE -crop "$1" "$2" "$3" null: 2>&1 |
		sed -n 's/.*(\([0-9.e-]*\)).*/\1/p'
}

status=0

# Frame 20 is before the use press lands, so the door is shut; frame 110 is
# partway through its 64-tic slide.
shoot 20 shut || exit 1
shoot 110 sliding || exit 1

for tag in shut sliding; do
	value=$(rmse "$weapon_rect" "$work/$tag.sw.png" "$work/$tag.gl.ppm")
	if [ -z "$value" ]; then
		printf 'FAIL %s: could not measure the weapon rectangle\n' "$tag"
		status=1
		continue
	fi
	if awk -v v="$value" -v m="$max_rmse" 'BEGIN{exit !(v > m)}'; then
		printf 'FAIL %s: weapon RMSE %s exceeds %s -- the GL view model does not '\
'match the software one\n' "$tag" "$value" "$max_rmse"
		status=1
	else
		printf '  ok  %-8s weapon RMSE %s (ceiling %s)\n' "$tag" "$value" "$max_rmse"
	fi
done

# The door has to have actually moved between the two frames, or both
# comparisons above are of the same shut door and this gate tests nothing.
moved=$(rmse "$view_rect" "$work/shut.sw.png" "$work/sliding.sw.png")
if [ -z "$moved" ] || awk -v v="$moved" -v m="$min_scene_change" 'BEGIN{exit !(v < m)}'; then
	printf 'FAIL: the view barely changed between the two frames (RMSE %s) -- the '\
'door did not open, so the weapon was never at risk and this gate is vacuous\n' \
		"${moved:-n/a}"
	status=1
else
	printf '  ok  the door moved between the two frames (view RMSE %s)\n' "$moved"
fi

[ "$status" -eq 0 ] && printf 'PASS: a sliding door leaves the weapon alone\n'
exit "$status"
