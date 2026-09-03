#!/bin/sh

# Regression test: standing in a laser barrier keeps hurting.
#
# The "Infrared Invisible Barrier" statics (map objects 28/84) are walk-through
# volumes, not walls. Their contact damage used to be applied only from TryMove,
# which is reached from Thrust -- and Thrust only runs while an input is moving
# the player. So walking into a barrier zapped once and then, if the player
# stopped, never again; and a player warped straight into one was never hurt at
# all. The player now also tests for overlap once per tic.
#
# The measurement is the LIFE gauge on the status bar, which is the only readout
# a headless run can see: DrawC7Gauge paints MIN(25, health>>2) green segments,
# so the lit width IS the health, quantised to 4 points. The player is pinned
# inside the MAP01 barrier at (35,19) and the gauge is read at intervals; it has
# to shrink monotonically and end well below where it started.
#
# Usage: test_corridor7_laserdamage.sh BUILD_DIR DATA_DIR   (both absolute)

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

work=$(mktemp -d /tmp/ec7wolf-laserdmg.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

printf 'Vid_MaxFPS = 0;\n' >"$work/cfg"

# TICS, not frames. Damage accrues per tic, and frames are not tics: how many
# frames pass in a tic depends on how busy the machine is, so the same
# --capture-frame reaches a different tic from run to run and the measurement
# window slides. An earlier version recorded the tic each frame happened to
# land on and sorted by it, which kept the readings honest but left the window
# itself drifting -- and on a loaded machine it drifted far enough to straddle
# something that made one shot read an empty gauge and the next a full one.
#
# --capture-snapshot renders at an exact simulation tic and exits, so these are
# the tics asked for on any machine. Chosen with margin: the gauge falls from
# 528 lit pixels to 288 across them, and the player is nowhere near dying.
tics="20 100 140 220 300"

for f in $tics; do
	( cd "$data_dir"
	  export SDL_AUDIODRIVER=dummy
	  export SDL_VIDEODRIVER=x11
	  timeout 180s xvfb-run -a "$build_dir/ec7wolf" --data CO7 --no-upscale \
		--config "$work/cfg" --savedir "$work" --nowait --tedlevel MAP01 --skill 2 \
		--vid-renderer software --res 640 480 --capture-rngseed 1 \
		--capture-warp 35 19 0 \
		--capture-snapshot "$work/shot.$f.png" "$f"
	) >"$work/run.$f.log" 2>&1 || true
	if [ ! -s "$work/shot.$f.png" ]; then
		printf 'FAIL: no frame captured at tic %s\n' "$f" >&2
		tail -20 "$work/run.$f.log" >&2
		exit 1
	fi
	convert "$work/shot.$f.png" -depth 8 "ppm:$work/shot.$f.ppm"
	printf '%s\n' "$f" >"$work/tic.$f"
done

frames=$tics

python3 - "$work" $frames <<'PY'
import sys

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

def life(path):
	"""Lit pixels of the LIFE gauge. Nothing else on the bar is this green."""
	w, h, px = read_ppm(path)
	n = 0
	for y in range(398, 428):
		row = y * w * 3
		for x in range(185, 255):
			o = row + x*3
			r, g, b = px[o], px[o+1], px[o+2]
			if g > 60 and g > r + 30 and g > b + 30:
				n += 1
	return n

work = sys.argv[1]
frames = [int(a) for a in sys.argv[2:]]
def tic_of(f):
	try:
		return int(open("%s/tic.%d" % (work, f)).read().strip())
	except Exception:
		return f

# Ordered by the tic each shot reached, not by the frame it was asked for.
lit = sorted(((tic_of(f), life("%s/shot.%d.ppm" % (work, f))) for f in frames))

print("  LIFE gauge: " + ", ".join("tic%d=%d" % (f, n) for f, n in lit))

if lit[0][1] == 0:
	sys.exit("FAIL: the LIFE gauge was not found; the measurement window is wrong")

for (fa, a), (fb, b) in zip(lit, lit[1:]):
	if b > a:
		sys.exit("FAIL: health went UP between tic %d and %d (%d -> %d)" % (fa, fb, a, b))

drop = lit[0][1] - lit[-1][1]
if drop < lit[0][1] // 4:
	sys.exit("FAIL: standing in the barrier cost only %d of %d gauge pixels over %d frames; "
		"contact damage is not repeating while the player holds still"
		% (drop, lit[0][1], frames[-1] - frames[0]))

steps = sum(1 for (_, a), (_, b) in zip(lit, lit[1:]) if b < a)
if steps < 3:
	sys.exit("FAIL: the gauge dropped in only %d of %d intervals; the damage is not periodic"
		% (steps, len(lit) - 1))

print("  lost %d of %d gauge pixels over %d frames, in %d separate steps"
	% (drop, lit[0][1], frames[-1] - frames[0], steps))
PY

printf 'PASS: standing in a laser barrier takes repeated contact damage.\n'
