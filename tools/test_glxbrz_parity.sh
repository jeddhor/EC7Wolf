#!/bin/sh

# Regression test: the GL xBRZ shader agrees with the CPU xBRZ it was ported from.
#
# render/opengl/r_glxbrz.cpp reimplements deps/xbrz in GLSL so the OpenGL present
# path gets the same filter the software path has. A shader that got the rules
# subtly wrong -- a rotation mapped the wrong way, blend weights applied out of
# order, the colour distance idealised instead of copied -- would still produce a
# smooth, plausible-looking picture. So it is not judged by eye: the game writes
# the shader's output and the CPU filter's output for the same frame, and they
# are compared pixel for pixel.
#
# Two things are asserted, and either one alone passes for the wrong reason:
#
#   * the two outputs agree. Not exactly -- GLSL has no doubles, so a colour
#     distance that lands within a hair of a threshold can fall the other way in
#     the shader, changing that source pixel's whole block. Measured at 28 source
#     pixels in 256000 on the title page, so the bar is set well inside what a
#     real porting error would blow through, and a per-channel ceiling is checked
#     too so the disagreements have to stay small as well as rare.
#
#   * the output is actually filtered. Both paths degenerating to a plain
#     nearest-neighbour blow-up would agree perfectly. A blow-up leaves every
#     scale x scale block flat, so blended (non-flat) blocks are counted: on real
#     art roughly a third of them are.
#
# The frame compared is a full-screen 2D page, which is the only case where the
# two paths are fed identical pixels -- the 3D view is not rendered identically
# by GL and software, so a gameplay frame would measure that difference instead.
#
# Usage: test_glxbrz_parity.sh BUILD_DIR DATA_DIR [FACTOR...]   (both absolute)

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [FACTOR...]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
shift 2
factors=${*:-2 6}

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

work=$(mktemp -d /tmp/ec7wolf-glxbrz.XXXXXX)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT INT TERM

failed=0

for factor in $factors; do
	# The setting is a config value rather than a switch, so the run is given a
	# config with it already set. Vid_Renderer is pinned the same way even though
	# --vid-renderer is passed, so a stale user config cannot pull the run back to
	# software and quietly turn this into a test of nothing.
	{
		printf 'Vid_xBRZ = %s;\n' "$factor"
		printf 'Vid_Renderer = "opengl";\n'
	} >"$work/xbrz.cfg"

	# The run ends itself: the parity pair is written on the title page, and the
	# capture harness quits at the next present once the files are closed
	# (Capture::NoteArtifactComplete). The timeout is a safety net for a run that
	# never gets that far, not the normal way out -- it used to be, which cost
	# ten minutes per factor for a few seconds of work. The exit status is still
	# not checked; the artifacts are the result.
	(
		cd "$data_dir"
		timeout 120s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s "-screen 0 640x400x24" "$ec7wolf" \
			--data CO7 --config "$work/xbrz.cfg" --savedir "$work/sv" \
			--nowait --res 640 400 --vid-renderer opengl \
			--capture-glxbrz "$work/p$factor" --capture-maxframes 1
	) >"$work/run$factor.log" 2>&1 || true

	if [ ! -s "$work/p$factor-gl.png" ] || [ ! -s "$work/p$factor-cpu.png" ]; then
		printf 'FAIL: %sx produced no parity pair; see %s/run%s.log\n' \
			"$factor" "$work" "$factor" >&2
		failed=1
		continue
	fi

	python3 - "$work/p$factor-gl.png" "$work/p$factor-cpu.png" "$factor" <<'PY' || failed=1
import sys
from PIL import Image

glPath, cpuPath, factor = sys.argv[1], sys.argv[2], int(sys.argv[3])
gl = Image.open(glPath).convert("RGB")
cpu = Image.open(cpuPath).convert("RGB")

if gl.size != cpu.size:
    print("FAIL: %dx sizes differ, GL %s vs CPU %s" % (factor, gl.size, cpu.size))
    sys.exit(1)

w, h = gl.size
a, b = gl.tobytes(), cpu.tobytes()
delta = [abs(x - y) for x, y in zip(a, b)]
differing = sum(1 for i in range(0, len(a), 3)
                if delta[i] or delta[i+1] or delta[i+2])
worst = max(delta)
share = 100.0 * differing / (w * h)

# Flat scale x scale blocks are what a nearest-neighbour blow-up produces; the
# filter's blending is what makes them non-flat.
px = gl.load()
blended = total = 0
for y in range(0, h, factor):
    for x in range(0, w, factor):
        total += 1
        first = px[x, y]
        if any(px[x+i, y+j] != first
               for j in range(factor) for i in range(factor)):
            blended += 1
blendShare = 100.0 * blended / total

print("%dx: %d of %d pixels differ (%.5f%%), worst channel %d, "
      "%.1f%% of blocks blended"
      % (factor, differing, w*h, share, worst, blendShare))

ok = True
if share > 0.05:
    print("FAIL: %dx disagrees with the CPU filter on %.5f%% of pixels. That is "
          "far past float-vs-double drift -- a rule in the shader does not match "
          "the one in deps/xbrz." % (factor, share))
    ok = False
if worst > 64:
    print("FAIL: %dx has a channel off by %d. Even a marginal threshold flip "
          "moves a pixel toward a neighbouring colour, not across the palette."
          % (factor, worst))
    ok = False
if blendShare < 5.0:
    print("FAIL: %dx left %.1f%% of blocks blended. The output is a "
          "nearest-neighbour blow-up -- the shader is not filtering, and "
          "agreeing with a CPU path that also is not proves nothing."
          % (factor, blendShare))
    ok = False

sys.exit(0 if ok else 1)
PY
done

if [ "$failed" -ne 0 ]; then
	exit 1
fi

printf 'PASS: the GL xBRZ shader matches the CPU filter at every factor tested\n'
