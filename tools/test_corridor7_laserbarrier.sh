#!/bin/sh

# Regression test: the infrared laser barrier is the game's own artwork lit by
# the rotating DAC ramp -- not a drawing special case.
#
# Corridor 7's "Infrared Invisible Barrier" (map objects 28/84, the C006 rods
# and the C062 energy ring) is painted entirely in palette indices 232-239, one
# of the four eight-entry ramps the released game rotates continuously. Those
# entries are black in the base palette and a 32/69/105/142/178/219/255/0 red
# sweep under infrared, which is the whole effect: invisible in normal vision,
# and crawling with energy under the visor because the rotation walks the sweep
# along artwork whose indices already climb the ramp.
#
# This is worth pinning because the failure mode is to "improve" it. A previous
# version replaced the sprite with a hashed white dissolve, which threw away
# both the travelling sweep along the rods and the ring's shape. So this checks
# what only the real mechanism can produce:
#
#   * under infrared, several hundred pixels in ALL of the ramp's distinct
#     levels, with no single level dominating -- a gradient, not a fill;
#   * that the pattern MOVES as the ramp rotates;
#   * in normal vision, not one ramp pixel anywhere -- the barrier is invisible;
#   * the same in the software renderer and in OpenGL.
#
# The scene is the MAP01 corridor pinch at (35,19), viewed from three tiles
# west. The barrier is walk-through, so a warp puts the view on it directly.
#
# Usage: test_corridor7_laserbarrier.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi
for tool in xvfb-run convert; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'required command is missing: %s\n' "$tool" >&2; exit 1; }
done

work=$(mktemp -d /tmp/ec7wolf-laser.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

printf 'Vid_MaxFPS = 0;\n' >"$work/cfg"

# shot RENDERER VISORMODE FRAME OUTPPM
shot() {
	_r=$1; _v=$2; _f=$3; _o=$4
	if [ "$_r" = software ]; then
		_capture="--capture-file $work/shot.png"
	else
		_capture="--capture-glframe $work/shot.ppm"
	fi
	rm -f "$work/shot.png" "$work/shot.ppm"
	( cd "$data_dir"
	  export SDL_AUDIODRIVER=dummy
	  export SDL_VIDEODRIVER=x11
	  # shellcheck disable=SC2086
	  timeout 180s xvfb-run -a "$build_dir/ec7wolf" --data CO7 --no-upscale \
		--config "$work/cfg" --savedir "$work" --nowait --tedlevel MAP01 --skill 2 \
		--vid-renderer "$_r" --capture-rngseed 1 \
		--capture-warp 32 19 0 --capture-visormode "$_v" \
		--capture-frame "$_f" $_capture --capture-maxframes 60
	) >"$work/run.log" 2>&1 || true
	if [ -s "$work/shot.png" ]; then
		convert "$work/shot.png" -depth 8 "ppm:$_o"
	elif [ -s "$work/shot.ppm" ]; then
		convert "$work/shot.ppm" -depth 8 "ppm:$_o"
	else
		printf 'FAIL: %s renderer captured no frame (visor %s, frame %s)\n' "$_r" "$_v" "$_f" >&2
		tail -20 "$work/run.log" >&2
		exit 1
	fi
}

# Four infrared frames rather than two. The ramp advances every other TIC, and a
# capture is scheduled by rendered FRAME: with the frame rate uncapped the GL
# renderer can draw all of a short frame span inside one phase, which made a
# two-frame version pass under software and fail under OpenGL on the same build.
# Spreading the shots over most of the run means the clock has to move.
for renderer in software opengl; do
	for f in 16 28 40 52; do
		shot "$renderer" 2 "$f" "$work/$renderer.ir.$f.ppm"
	done
	shot "$renderer" 0 30 "$work/$renderer.normal.ppm"

	python3 - "$renderer" "$work/$renderer.normal.ppm" \
		"$work/$renderer.ir.16.ppm" "$work/$renderer.ir.28.ppm" \
		"$work/$renderer.ir.40.ppm" "$work/$renderer.ir.52.ppm" <<'PY'
import sys, collections

# The infrared DAC's levels for ramp positions 0-5. 142 and 255 are left out on
# purpose: infrared gives those same values to the 24-39 and 240-247 ramps, so
# they cannot identify a barrier pixel. The rest appear nowhere else.
RAMP = {(32,0,0), (69,0,0), (105,0,0), (178,0,0), (219,0,0)}

def read_ppm(path):
	data = open(path, "rb").read()
	fields, pos = [], 0
	while len(fields) < 4:
		while pos < len(data) and data[pos:pos+1].isspace():
			pos += 1
		if data[pos:pos+1] == b"#":
			while data[pos:pos+1] not in (b"\n", b""):
				pos += 1
			continue
		start = pos
		while pos < len(data) and not data[pos:pos+1].isspace():
			pos += 1
		fields.append(data[start:pos])
	pos += 1
	w, h = int(fields[1]), int(fields[2])
	return w, h, data[pos:pos + w*h*3]

def barrier_pixels(path):
	"""{(x,y): level} for every ramp pixel above the status bar."""
	w, h, px = read_ppm(path)
	found = {}
	for y in range(int(h * 0.78)):
		row = y * w * 3
		for x in range(w):
			o = row + x*3
			c = (px[o], px[o+1], px[o+2])
			if c in RAMP:
				found[(x, y)] = c
	return found

renderer, normal = sys.argv[1:3]
shots = [barrier_pixels(p) for p in sys.argv[3:]]

n = barrier_pixels(normal)
if n:
	sys.exit("FAIL[%s]: %d barrier-ramp pixels in normal vision; the barrier must be invisible"
		% (renderer, len(n)))

for i, a in enumerate(shots):
	if len(a) < 600:
		sys.exit("FAIL[%s]: shot %d has only %d barrier pixels under infrared; the barrier is "
			"either not drawn at all or its ramp colours have been overpainted"
			% (renderer, i, len(a)))
	levels = collections.Counter(a.values())
	if len(levels) < len(RAMP):
		sys.exit("FAIL[%s]: shot %d shows %d of %d ramp levels; it is not lit by the rotating ramp"
			% (renderer, i, len(levels), len(RAMP)))
	top = levels.most_common(1)[0][1]
	if top > len(a) * 0.6:
		sys.exit("FAIL[%s]: shot %d is %d%% one colour; it is filled, not swept"
			% (renderer, i, top * 100 // len(a)))

first = shots[0]
moved = max(sum(1 for p, c in first.items() if s.get(p) != c) for s in shots[1:])
if moved < len(first) // 5:
	sys.exit("FAIL[%s]: at most %d of %d barrier pixels changed across the run; the ramp is not rotating"
		% (renderer, moved, len(first)))

print("  %-8s %d px, %d levels, %d%% swept across the run, 0 px in normal vision"
	% (renderer, len(first), len(collections.Counter(first.values())),
	   moved * 100 // len(first)))
PY
done

printf 'PASS: the infrared laser barrier is drawn as artwork lit by the rotating DAC ramp.\n'
