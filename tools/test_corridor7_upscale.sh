#!/bin/sh

# Regression test: the upscaled asset pack is used when it is installed, rejected
# when it is incomplete, and switchable back to the stock art.
#
# The pack is built here rather than shipped, for the same reason the game never
# ships one: everything in it derives from the player's commercial data files.
# It is built with fake_upscaler.py, a nearest-neighbor stand-in for
# Real-ESRGAN, because none of what this checks depends on the upscale being any
# good -- only on the pack being found, validated, applied and undone.
#
# Walls only, which keeps the build to seconds and is enough: walls are the one
# group that carries both cases the engine has to get right, the ordinary opaque
# page and the masked page whose transparency lives in an index the PNG cannot
# store. A masked wall that lost its holes would come back as a solid block, and
# the opacity count the GL world logs is what says whether it did.
#
# Cases:
#   1. no pack             -- the reference frame, and nothing said about it
#   2. complete pack       -- accepted, all 256 walls replaced, filter raised
#   3. pack, switched off  -- byte-identical to case 1
#   4. incomplete pack     -- rejected by name, not merely counted, and the art
#                             left alone rather than half replaced
#
# Case 3 is the one that would quietly rot: it is the only case where the game
# has to put a texture back, and a build that leaked the replacement would still
# look right on every screen the player had not visited yet.
#
# Usage: test_corridor7_upscale.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
tools_dir=$(cd "$(dirname "$0")" && pwd)

if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi
if ! command -v xvfb-run >/dev/null 2>&1; then
	printf 'required command is missing: xvfb-run\n' >&2
	exit 1
fi

work=$(mktemp -d /tmp/ec7wolf-upscale.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# Run from a directory holding the build's OWN pk3: ECWolf resolves ec7wolf.pk3
# from the working directory first, and running with the data directory as cwd
# silently tests whichever pk3 was last installed there.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$work/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && ln -s "$f" "$work/" || true
done

printf 'Building a test asset pack (walls, 2x, nearest neighbor)...\n'
python3 "$tools_dir/make_c7_upscaled_pk3.py" \
	--dir "$work" --out "$work/pack.pk3" --groups walls --scale 2 \
	--tool "$tools_dir/fake_upscaler.py" --models "$work" --keep-file /dev/null \
	--namemap "$tools_dir/../wadsrc/static/co7map.txt" >"$work/build.log" 2>&1 || {
		printf 'FAIL: the test pack could not be built\n' >&2
		tail -20 "$work/build.log" >&2
		exit 1
	}

# The same pack built through the shipped keep list, which is what a player gets
# by default: fewer lumps, and the kept names absent from the manifest so the
# game still sees a pack that is complete.
printf 'Building a test asset pack with the default keep list...\n'
python3 "$tools_dir/make_c7_upscaled_pk3.py" \
	--dir "$work" --out "$work/kept.pk3" --groups walls --scale 2 \
	--tool "$tools_dir/fake_upscaler.py" --models "$work" \
	--namemap "$tools_dir/../wadsrc/static/co7map.txt" >"$work/keep.log" 2>&1 || {
		printf 'FAIL: the keep-list pack could not be built\n' >&2
		exit 1
	}

# One wall page short of the manifest, which is what an upscaler that died
# partway through leaves behind.
python3 - "$work/pack.pk3" "$work/broken.pk3" <<'PY'
import sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(src) as z, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
    for info in z.infolist():
        if info.filename == "hires/c7w0005.png":
            continue
        out.writestr(info, z.read(info.filename))
PY

# The frames have to be comparable byte for byte, which means nothing in the
# scene may depend on how long startup took. The player is warped to a fixed
# tile, every door is pinned open, and the capture is taken four frames in --
# early enough that no alien has moved far and late enough that the first frame's
# setup is done. Without those, loading the pack costs enough time that frame 40
# lands on a different tic and the doors are caught mid-slide.
#
# $1 = case name, $2 = pack file to install (empty for none), $3 = config body
# Anchored to a simulation tic, not a frame.
#
# This gate compares two captures byte for byte, and --capture-frame 4 meant
# "the fourth frame drawn" -- which lands on a different TIC depending on how
# fast the machine is drawing. Two runs on a busy box therefore photographed
# two different moments, the weapon bob and the palette cycle had moved, and
# "a rejected pack changes nothing on screen" failed on a run where nothing
# was wrong. --capture-snapshot shoots at a tic, which is the same moment
# everywhere, and exits.
#
# --capture-glframe stays: its .ppm is never read, but the GL world capture
# prints how many textures carried an opacity plane, and that line is the only
# evidence the masked-wall check has. Removing it took away a check's evidence
# rather than its subject, and the check then failed with two empty numbers.
run_case() {
	name=$1
	pack=$2
	cfg=$3

	rm -f "$work/c7_assets_upscaled.pk3"
	[ -n "$pack" ] && cp "$pack" "$work/c7_assets_upscaled.pk3"
	printf '%s' "$cfg" >"$work/cfg"

	( cd "$work"
	  export SDL_AUDIODRIVER=dummy
	  export SDL_VIDEODRIVER=x11
	  timeout 180s xvfb-run -a ./ec7wolf --data CO7 --config "$work/cfg" \
		--savedir "$work" --nowait --tedlevel MAP07 --skill 2 \
		--vid-renderer software --res 640 400 --capture-rngseed 1 \
		--capture-warp 34 44 90 --capture-open-doors 65535 \
		--capture-glframe "$work/$name.gl.ppm" \
		--capture-snapshot "$work/$name.png" 5
	) >"$work/$name.log" 2>&1 || true

	if [ ! -s "$work/$name.png" ]; then
		printf 'FAIL: %s produced no frame\n' "$name" >&2
		tail -20 "$work/$name.log" >&2
		exit 1
	fi
}

# The config parser rejects an empty file, so the cases that want the default
# need a body that says nothing about the pack.
neutral_cfg='Vid_MaxFPS = 0;
'

fail=0
check() {
	if [ "$1" = "0" ]; then
		printf '  ok   %s\n' "$2"
	else
		printf '  FAIL %s\n' "$2" >&2
		fail=1
	fi
}

printf '\nCase 1: no pack installed\n'
run_case none "" "$neutral_cfg"
grep -q 'Upscale:' "$work/none.log" && check 1 'says nothing when no pack is installed' \
	|| check 0 'says nothing when no pack is installed'

printf '\nCase 2: a complete pack\n'
run_case on "$work/pack.pk3" "$neutral_cfg"
grep -q 'carries 256 images at 2x' "$work/on.log" \
	&& check 0 'accepts the pack and reports its size' || check 1 'accepts the pack and reports its size'
grep -q '256 of the game.s textures have an upscaled copy; using the upscaled art' "$work/on.log" \
	&& check 0 'replaces every wall page' || check 1 'replaces every wall page'
if cmp -s "$work/none.png" "$work/on.png"; then
	check 1 'the upscaled art actually reaches the screen'
else
	check 0 'the upscaled art actually reaches the screen'
fi

# Nearest sampling of a pack four times the game's own resolution is what makes
# it crawl: every wall is being reduced rather than magnified, and point sampling
# picks different texels as the view moves. Switching the pack on has to raise
# the filter with it, or the pack looks worse than the art it replaced.
grep -q 'texture filtering raised to Smooth' "$work/on.log" \
	&& check 0 'raises the texture filter with the pack' \
	|| check 1 'raises the texture filter with the pack'

# The masked wall pages are the ones whose transparency has to survive the trip
# through PNG, and the GL world reports how many textures came with an opacity
# plane. Losing them would turn every grate into a solid block.
masked_none=$(sed -n 's/.*uploaded [0-9]* unique index textures (\([0-9]*\) with opacity).*/\1/p' "$work/none.log" | tail -1)
masked_on=$(sed -n 's/.*uploaded [0-9]* unique index textures (\([0-9]*\) with opacity).*/\1/p' "$work/on.log" | tail -1)
if [ -n "$masked_none" ] && [ "$masked_none" = "$masked_on" ] && [ "$masked_none" != "0" ]; then
	check 0 "masked walls keep their transparency ($masked_on textures with an opacity plane)"
else
	check 1 "masked walls keep their transparency (stock $masked_none, upscaled $masked_on)"
fi

printf '\nCase 3: the same pack, switched off\n'
run_case off "$work/pack.pk3" 'Vid_UpscaledAssets = 0;
'
grep -q 'using the original art' "$work/off.log" \
	&& check 0 'honors the config and puts the art back' || check 1 'honors the config and puts the art back'
if cmp -s "$work/none.png" "$work/off.png"; then
	check 0 'the restored frame is byte-identical to having no pack at all'
else
	check 1 'the restored frame is byte-identical to having no pack at all'
fi

printf '\nCase 4: a pack built with the keep list\n'
run_case kept "$work/kept.pk3" "$neutral_cfg"
grep -q 'carries 246 images at 2x' "$work/kept.log" \
	&& check 0 'accepts a pack that deliberately covers less' \
	|| check 1 'accepts a pack that deliberately covers less'
if python3 -c "
import sys, zipfile
z = zipfile.ZipFile('$work/kept.pk3')
listed = set(z.read('c7upscal.lst').decode().split())
sys.exit(0 if 'c7w0009' not in listed and 'hires/c7w0009.png' not in z.namelist()
           and 'c7w0008' in listed else 1)
"; then
	check 0 'kept lumps are out of the pack and out of its manifest'
else
	check 1 'kept lumps are out of the pack and out of its manifest'
fi

printf '\nCase 5: an incomplete pack\n'
run_case broken "$work/broken.pk3" "$neutral_cfg"
grep -q 'is incomplete -- 1 of its 256 images are missing (c7w0005)' "$work/broken.log" \
	&& check 0 'names the missing image rather than just counting' \
	|| check 1 'names the missing image rather than just counting'
if cmp -s "$work/none.png" "$work/broken.png"; then
	check 0 'a rejected pack changes nothing on screen'
else
	check 1 'a rejected pack changes nothing on screen'
fi

printf '\n'
if [ "$fail" = "0" ]; then
	printf 'PASS: the upscaled asset pack is detected, validated and switchable.\n'
else
	printf 'FAIL: see above.\n' >&2
fi
exit "$fail"
