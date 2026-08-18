#!/bin/sh

# Regression test: the FLIC decoder that plays the CD cinematics.
#
# The engine cannot start without the commercial Corridor 7 data, so every other
# gate that drives it needs a machine that owns the game. This one does not:
# --flictest decodes an animation and prints a per-frame checksum before any
# game data is opened, which makes the decoder the one part of the cinematics
# that can be gated anywhere, including on a hosted CI runner.
#
# The animation is built here rather than shipped, for two reasons. The real
# ones are 27 MB of commercial video that can never be committed. And a
# generated file lets the test compute what every frame MUST contain, in Python,
# from the chunks it just wrote -- so this is two independent implementations
# agreeing on the pixels, not a decoder compared against its own last output.
#
# Exercised: FLI_COLOR256, FLI_BRUN, FLI_LC, FLI_SS2 and FLI_BLACK, which is
# every chunk type the three shipped cinematics use.
#
# Usage: test_corridor7_flic.sh BUILD_DIR [DATA_DIR]

set -eu

if [ "$#" -lt 1 ]; then
	printf 'usage: %s BUILD_DIR [DATA_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi

work=$(mktemp -d /tmp/ec7wolf-flic.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

python3 - "$work/synthetic.flc" "$work/expected.txt" <<'PY'
import struct, sys

W, H = 320, 200
out_path, expect_path = sys.argv[1], sys.argv[2]

FLI_COLOR256, FLI_SS2, FLI_LC, FLI_BLACK, FLI_BRUN = 4, 7, 12, 13, 15

def chunk(kind, payload):
    return struct.pack("<IH", len(payload) + 6, kind) + payload

def frame(chunks):
    body = b"".join(chunks)
    return struct.pack("<IHHHHHH", len(body) + 16, 0xF1FA, len(chunks), 0, 0, 0, 0) + body

# --- the reference image, maintained alongside the chunks that produce it ----
pixels = bytearray(W * H)
palette = [(0, 0, 0)] * 256
frames_expected = []

def snapshot():
    image = 2166136261
    for b in pixels:
        image = ((image ^ b) * 16777619) & 0xFFFFFFFF
    pal = 2166136261
    for (r, g, b) in palette:
        for c in (r, g, b):
            pal = ((pal ^ c) * 16777619) & 0xFFFFFFFF
    frames_expected.append((image, pal))

frames = []

# 1. A palette and a flat BRUN fill of index 5.
pal_payload = struct.pack("<H", 1) + bytes([0, 0])
for i in range(256):
    pal_payload += bytes([i, 255 - i, (i * 7) & 0xFF])
brun = b""
for _ in range(H):
    # Packet count, then runs covering 320 pixels. A BRUN count is a SIGNED
    # byte -- positive repeats the next value, negative copies that many
    # literals -- so a run cannot exceed 127 and 320 needs three of them.
    brun += bytes([3, 127, 5, 127, 5, 66, 5])
frames.append(frame([chunk(FLI_COLOR256, pal_payload), chunk(FLI_BRUN, brun)]))
for i in range(256):
    palette[i] = (i, 255 - i, (i * 7) & 0xFF)
for i in range(W * H):
    pixels[i] = 5
snapshot()

# 2. FLI_LC: on lines 10..12, skip 4 pixels then write six literal bytes.
lit = bytes([1, 2, 3, 4, 5, 6])
lc = struct.pack("<HH", 10, 3)
for _ in range(3):
    lc += bytes([1, 4, 6]) + lit          # 1 packet: skip 4, copy 6
frames.append(frame([chunk(FLI_LC, lc)]))
for y in range(10, 13):
    pixels[y * W + 4: y * W + 10] = lit
snapshot()

# 3. FLI_SS2: line 20 gets one packet -- skip 8, then two literal words.
ss2 = struct.pack("<H", 21)              # 21 lines described
for _ in range(20):
    ss2 += struct.pack("<H", 0)          # 20 lines with zero packets
ss2 += struct.pack("<H", 1) + bytes([8, 2, 0x11, 0x22, 0x33, 0x44])
frames.append(frame([chunk(FLI_SS2, ss2)]))
pixels[20 * W + 8: 20 * W + 12] = bytes([0x11, 0x22, 0x33, 0x44])
snapshot()

# 4. FLI_SS2 again, with an RLE word packet: line 21, skip 0, repeat a word 5x.
ss2 = struct.pack("<H", 22)
for _ in range(21):
    ss2 += struct.pack("<H", 0)
ss2 += struct.pack("<H", 1) + bytes([0, 0xFB, 0xAA, 0xBB])   # -5 -> 5 words
frames.append(frame([chunk(FLI_SS2, ss2)]))
pixels[21 * W: 21 * W + 10] = bytes([0xAA, 0xBB] * 5)
snapshot()

# 5. FLI_BLACK: everything back to index 0, palette untouched.
frames.append(frame([chunk(FLI_BLACK, b"")]))
for i in range(W * H):
    pixels[i] = 0
snapshot()

body = b"".join(frames)
header = bytearray(128)
struct.pack_into("<IHHHHHH", header, 0, 128 + len(body), 0xAF12, len(frames), W, H, 8, 3)
struct.pack_into("<I", header, 16, 50)   # 50 ms/frame
open(out_path, "wb").write(bytes(header) + body)

with open(expect_path, "w") as f:
    for n, (image, pal) in enumerate(frames_expected, 1):
        f.write("frame %d image %08x palette %08x\n" % (n, image, pal))
print("  built a %d-frame synthetic animation exercising 5 chunk types"
      % len(frames))
PY

"$build_dir/ec7wolf" --flictest "$work/synthetic.flc" >"$work/actual.txt" 2>&1 || {
	printf 'FAIL: the decoder rejected the synthetic animation\n' >&2
	cat "$work/actual.txt" >&2
	exit 1
}

grep '^frame ' "$work/actual.txt" >"$work/actual-frames.txt" || true

if ! diff -u "$work/expected.txt" "$work/actual-frames.txt" >"$work/diff.txt"; then
	printf 'FAIL: the decoder disagrees with the reference image\n' >&2
	cat "$work/diff.txt" >&2
	exit 1
fi

printf '  %s frames decoded exactly as constructed\n' \
	"$(wc -l < "$work/expected.txt" | tr -d ' ')"

# A truncated animation has to be refused rather than played half way: the
# header's size field against the real length is what catches a bad rip.
head -c 200 "$work/synthetic.flc" >"$work/truncated.flc"
if "$build_dir/ec7wolf" --flictest "$work/truncated.flc" >/dev/null 2>&1; then
	printf 'FAIL: a truncated animation was accepted\n' >&2
	exit 1
fi
printf '  a truncated animation is refused\n'

printf 'PASS: the FLIC decoder reproduces every chunk type exactly.\n'
