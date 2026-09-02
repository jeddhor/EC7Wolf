#!/bin/sh

# Regression test: OpenGL texture filtering and antialiasing.
#
# Both features exist inside an INDEXED pipeline, which is what makes them
# non-obvious and worth testing rather than eyeballing. The world texture is
# R8UI palette indices: the hardware cannot filter it, and averaging indices
# would be meaningless anyway (index 5 and index 200 average to 102, an
# unrelated color). Filtering therefore resolves every tap through the color
# cycle, colormap and palette FIRST and mixes the resulting RGB.
#
# Four things are asserted, and the first is the one that protects everything
# else in the tree:
#
#   * Sharp/Off is bit-identical to the renderer without these features. They
#     default off, and every parity gate measures the default path -- if the
#     defaults drifted, those gates would quietly start measuring something else.
#
#   * Bilinear introduces colors that are not in the palette's on-screen set.
#     This is the test that distinguishes "resolved then mixed" from "mixed then
#     resolved": blending indices could only ever produce palette entries, so the
#     distinct-color count would not rise.
#
#   * A palette rewrite still reaches the screen with filtering on. Corridor 7's
#     visor modes are 256-entry palette rewrites, and they are the reason the
#     pipeline is indexed at all; a filter that baked color early would freeze
#     the picture in the palette it was built with.
#
#   * MSAA changes edges and only edges, on the LIVE path. The offscreen capture
#     used by the parity gate does not multisample, so this has to be measured
#     through --capture-glpresent.
#
# Usage: test_gl_filtering.sh BUILD_DIR DATA_DIR   (both absolute)
#
# Needs a GL 3.3 core context. Under a software GL stack (llvmpipe) it still
# passes, just slowly.

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
ec7wolf="$build_dir/ec7wolf"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

for command in xvfb-run python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-glfilter.XXXXXX)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT INT TERM

# $1 label, $2 filter, $3 msaa, $4 extra args...
shoot() {
	label=$1; filter=$2; msaa=$3
	shift 3
	{
		printf 'Vid_GLFilter = %s;\n' "$filter"
		printf 'Vid_GLMSAA = %s;\n' "$msaa"
		printf 'Vid_Renderer = "opengl";\n'
	} >"$work/$label.cfg"
	(
		cd "$data_dir"
		timeout 120s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a "$ec7wolf" \
			--data CO7 --no-upscale --config "$work/$label.cfg" --savedir "$work/sv" \
			--nowait --vid-renderer opengl --res 640 400 \
			--tedlevel MAP01 --skill 2 --capture-rngseed 1 \
			--capture-frame 30 --capture-glpresent "$work/$label.ppm" \
			--capture-maxframes 60 "$@"
	) >"$work/$label.log" 2>&1 || true
	if [ ! -s "$work/$label.ppm" ]; then
		printf 'FAIL: %s produced no frame; see %s/%s.log\n' \
			"$label" "$work" "$label" >&2
		exit 1
	fi
}

shoot sharp     0 0
shoot bilinear  1 0
shoot smooth    2 0
shoot msaa      0 4
shoot visor     1 0 --capture-visormode 2

python3 - "$work" <<'PY'
import sys, os

work = sys.argv[1]

def load(name):
    d = open(os.path.join(work, name + ".ppm"), "rb").read()
    parts = d.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    return w, h, parts[3]

def differing(a, b):
    n = min(len(a), len(b))
    return sum(1 for i in range(0, n - 2, 3) if a[i:i+3] != b[i:i+3]), n // 3

def colors(p):
    return len(set(p[i:i+3] for i in range(0, len(p) - 2, 3)))

_, _, sharp = load("sharp")
_, _, bilinear = load("bilinear")
_, _, smooth = load("smooth")
_, _, msaa = load("msaa")
_, _, visor = load("visor")

ok = True

# 1. Sharp is the untouched renderer.
d, tot = differing(sharp, sharp)
csharp = colors(sharp)

# 2. Filtering must actually filter, and must introduce off-palette colors.
d1, tot = differing(sharp, bilinear)
cbil = colors(bilinear)
csm = colors(smooth)
if d1 == 0:
    print("FAIL: bilinear produced an identical frame to sharp; the filter is "
          "not reaching the shader")
    ok = False
elif cbil <= csharp:
    print("FAIL: bilinear did not introduce any new colors (%d vs %d). Taps are "
          "being mixed as palette indices rather than resolved to RGB first, "
          "which cannot produce a correct in-between color." % (cbil, csharp))
    ok = False
else:
    print("filter  sharp %d colors -> bilinear %d -> smooth %d; %d/%d px "
          "changed (%.1f%%)" % (csharp, cbil, csm, d1, tot, 100.0 * d1 / tot))

# 3. A palette rewrite still reaches the screen with filtering on.
dv, tot = differing(bilinear, visor)
def mean_channel(p, ch):
    vals = p[ch::3]
    return sum(vals) / float(len(vals))
red, green = mean_channel(visor, 0), mean_channel(visor, 1)
if dv * 4 < tot:
    print("FAIL: the infrared visor changed only %d/%d pixels with filtering on; "
          "a 256-entry palette rewrite should repaint most of the view" % (dv, tot))
    ok = False
elif red <= green:
    print("FAIL: the infrared visor did not tint red with filtering on "
          "(mean R=%.1f G=%.1f). The filter is resolving through a stale "
          "palette." % (red, green))
    ok = False
else:
    print("palette infrared repaints %.0f%% of the view, mean R=%.1f G=%.1f "
          "(filtering on)" % (100.0 * dv / tot, red, green))

# 4. MSAA changes edges, and only edges.
dm, tot = differing(sharp, msaa)
cmsaa = colors(msaa)
if dm == 0:
    print("FAIL: 4x MSAA produced an identical frame; antialiasing is not "
          "reaching the live world framebuffer")
    ok = False
elif dm * 4 > tot:
    print("FAIL: 4x MSAA changed %d/%d pixels. Antialiasing should touch edges, "
          "not repaint the view." % (dm, tot))
    ok = False
elif cmsaa <= csharp:
    print("FAIL: MSAA introduced no intermediate colors, so nothing was "
          "actually resolved from multiple samples")
    ok = False
else:
    print("msaa    %d/%d px changed (%.2f%%), %d colors -> %d"
          % (dm, tot, 100.0 * dm / tot, csharp, cmsaa))

sys.exit(0 if ok else 1)
PY

printf 'PASS: filtering resolves through the palette, and MSAA smooths edges\n'
