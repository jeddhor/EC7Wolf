#!/bin/sh

# Portal cell visibility vs. the software raycaster.
#
# The GL renderer used to get its cell-visibility set -- `spot->visible` for the
# sprite cull, AM_Visible for the automap -- as a side effect of running the
# software wall pass. render/r_visibility.cpp replaces that with a portal
# traversal, which is what finally lets the GL path stop calling into the
# raycaster at all.
#
# The two sets are NOT identical, and were never going to be: a DDA marks the
# cells a finite set of rays happens to walk through, a portal traversal marks
# what the view volume can reach. What matters is the DIRECTION of the
# difference, because the two failure modes are not equal:
#
#   * portal marks a cell the raycaster missed  -> the automap reveals a cell
#     the DOS game would have left dark. Cosmetic.
#   * portal misses a cell the raycaster marked -> ActorVisible() culls an actor
#     that should have been drawn. A monster vanishes.
#
# So the hard assertion is one-sided: **raycaster-only must be zero**, on every
# map, on every frame. The extra cells are reported, not failed, because their
# count is a property of the level geometry and not something to freeze.
#
# --vis-diff runs both traversals per frame and tallies them. Doors are forced
# part-open so the sight-passes rules for doors and pushwalls are exercised
# rather than every one of them reading as a solid wall.
#
# Usage: test_gl_visibility.sh BUILD_DIR DATA_DIR [MAP...]

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [MAP...]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
shift 2

if [ "$#" -gt 0 ]; then
	maps="$*"
else
	# A spread of geometry: the opening floor, the open-plan ones, a bonus
	# floor, and a network map (different author, different shapes).
	maps="MAP01 MAP02 MAP10 MAP20 MAP30 MAP40 MAP51"
fi

if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi
command -v xvfb-run >/dev/null 2>&1 || { printf 'required command is missing: xvfb-run\n' >&2; exit 1; }

work=$(mktemp -d /tmp/ec7wolf-vis.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
printf 'Vid_MaxFPS = 0;\n' >"$work/cfg"

fail=0
total_both=0
total_extra=0

for map in $maps; do
	( cd "$data_dir"
	  export SDL_AUDIODRIVER=dummy
	  export SDL_VIDEODRIVER=x11
	  timeout 180s xvfb-run -a "$build_dir/ec7wolf" --data CO7 --no-upscale \
		--config "$work/cfg" --savedir "$work" --nowait --tedlevel "$map" --skill 2 \
		--vid-renderer opengl --vis-diff --capture-rngseed 1 \
		--capture-open-doors 30000 --capture-maxframes 120
	) >"$work/$map.log" 2>&1 || true

	line=$(grep "Visibility diff:" "$work/$map.log" | tail -n1 || true)
	if [ -z "$line" ]; then
		printf 'FAIL[%s]: no visibility comparison was produced\n' "$map" >&2
		tail -20 "$work/$map.log" >&2
		fail=1
		continue
	fi

	frames=$(printf '%s' "$line" | sed -n 's/.*diff: \([0-9]*\) frames.*/\1/p')
	both=$(printf '%s' "$line"   | sed -n 's/.*both \([0-9]*\).*/\1/p')
	extra=$(printf '%s' "$line"  | sed -n 's/.*portal-only \([0-9]*\).*/\1/p')
	missed=$(printf '%s' "$line" | sed -n 's/.*raycaster-only \([0-9]*\).*/\1/p')

	if [ "$missed" -ne 0 ]; then
		printf 'FAIL[%s]: the portal traversal missed %s cell-frames the raycaster marked\n' \
			"$map" "$missed" >&2
		grep "VISMISS" "$work/$map.log" | head -8 >&2 || true
		fail=1
		continue
	fi

	printf '  %-6s %s frames: %s shared, %s extra revealed (+%s%%), 0 missed\n' \
		"$map" "$frames" "$both" "$extra" \
		"$(( both > 0 ? extra * 100 / both : 0 ))"
	total_both=$(( total_both + both ))
	total_extra=$(( total_extra + extra ))
done

if [ "$fail" -ne 0 ]; then
	printf 'FAIL: portal visibility is not a superset of the raycaster set.\n' >&2
	exit 1
fi

printf 'PASS: portal visibility covers the raycaster set on every map (+%s%% cells revealed overall).\n' \
	"$(( total_both > 0 ? total_extra * 100 / total_both : 0 ))"
