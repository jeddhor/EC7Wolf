#!/bin/sh

# Regression test: the floor objective banner is drawn in the color the DOS
# release drew it in.
#
# "Eliminate Aliens To Secure Floor" is painted as a solid stencil over the
# ceiling gradient at the top of the view. The reference is a DOSBox capture of
# the CD release on MAP01: the banner is exactly (255,255,0) there, with no
# intermediate shades, over the same bright gradient.
#
# This is worth a test because the failure is quiet and map-dependent. The
# color that was here before -- palette entry 3, (215,215,0) -- looks correct
# over the dark walls most floors open on, and only reads as dull over a bright
# background. MAP01 opens on the brightest one in the game, which is why it is
# the map pinned here.
#
# The palette holds three identical pure yellows (111, 231, 253), so the drawing
# code asks for the color rather than an index; this checks what reached the
# screen, which is the part the reference can actually speak to.
#
# Usage: test_corridor7_topmessage.sh BUILD_DIR DATA_DIR   (both absolute)

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
if ! command -v xvfb-run >/dev/null 2>&1; then
	printf 'required command is missing: xvfb-run\n' >&2
	exit 1
fi

work=$(mktemp -d /tmp/ec7wolf-topmsg.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

printf 'Vid_MaxFPS = 0;\n' >"$work/cfg"

( cd "$data_dir"
  export SDL_AUDIODRIVER=dummy
  export SDL_VIDEODRIVER=x11
  timeout 180s xvfb-run -a "$build_dir/ec7wolf" --data CO7 --no-upscale \
	--config "$work/cfg" --savedir "$work" --nowait --tedlevel MAP01 --skill 2 \
	--vid-renderer software --res 640 400 --capture-rngseed 1 \
	--capture-frame 30 --capture-file "$work/frame.png" --capture-maxframes 60
) >"$work/run.log" 2>&1 || true

if [ ! -s "$work/frame.png" ]; then
	printf 'FAIL: no frame was captured\n' >&2
	tail -20 "$work/run.log" >&2
	exit 1
fi

python3 - "$work/frame.png" <<'PY'
import sys, zlib, struct, collections

path = sys.argv[1]
data = open(path, "rb").read()
off, idat, palette = 8, b"", b""
while off + 8 <= len(data):
    length = struct.unpack_from(">I", data, off)[0]
    tag, body = data[off+4:off+8], data[off+8:off+8+length]
    if tag == b"IHDR":
        width, height, depth, color = struct.unpack(">IIBB", body[:10])
    elif tag == b"PLTE":
        palette = body
    elif tag == b"IDAT":
        idat += body
    elif tag == b"IEND":
        break
    off += 12 + length

if color != 3:
    sys.exit("FAIL: expected an indexed screenshot, got color type %d" % color)

raw = zlib.decompress(idat)
rows, prev, pos = [], bytearray(width), 0
for _ in range(height):
    filt = raw[pos]; pos += 1
    line = bytearray(raw[pos:pos+width]); pos += width
    if filt == 1:
        for x in range(1, width): line[x] = (line[x] + line[x-1]) & 255
    elif filt == 2:
        for x in range(width): line[x] = (line[x] + prev[x]) & 255
    elif filt == 3:
        line[0] = (line[0] + (prev[0] >> 1)) & 255
        for x in range(1, width): line[x] = (line[x] + ((line[x-1] + prev[x]) >> 1)) & 255
    elif filt == 4:
        for x in range(width):
            a = line[x-1] if x else 0
            b = prev[x]
            c = prev[x-1] if x else 0
            p = a + b - c
            pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
            line[x] = (line[x] + (a if (pa <= pb and pa <= pc) else (b if pb <= pc else c))) & 255
    rows.append(line); prev = line

# The banner sits at y=4..12 in the 320x200 layout; take a generous strip of the
# top of the frame and look only at what is yellow, since the rest is the
# ceiling gradient.
strip_h = max(1, height * 30 // 200)
counts = collections.Counter()
for y in range(strip_h):
    for x in range(width):
        i = rows[y][x]
        r, g, b = palette[i*3], palette[i*3+1], palette[i*3+2]
        if r > 150 and g > 150 and b < 110:
            counts[(r, g, b)] += 1

if not counts:
    sys.exit("FAIL: no banner text found in the top of the frame")

(color_seen, pixels), = counts.most_common(1)
print("  banner: %d px of rgb%s (%d distinct yellows)"
      % (pixels, color_seen, len(counts)))

if color_seen != (255, 255, 0):
    sys.exit("FAIL: the banner is rgb%s; the DOS release draws it at (255, 255, 0). "
             "Palette entry 3, (215,215,0), is the value this regressed to before."
             % (color_seen,))
if len(counts) != 1:
    sys.exit("FAIL: the banner should be a solid stencil, but %d yellows are present"
             % len(counts))
if pixels < 500:
    sys.exit("FAIL: only %d banner pixels; the message may not have been drawn" % pixels)
print("PASS: the floor objective banner matches the DOS release's full-bright yellow.")
PY
