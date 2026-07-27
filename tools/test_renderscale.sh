#!/bin/sh

# Regression test: vid_renderscale draws a smaller frame and shows it full size.
#
# The setting exists so that a filter like xBRZ has somewhere to scale into. At
# Native the frame is the window, and enlarging it only for the window to shrink
# it straight back is a no-op that costs a frame of work -- which is exactly what
# xBRZ did before this existed. So the two halves are tested separately, because
# either one alone can pass while the feature is broken:
#
#   * the game really renders smaller. Taken from the engine's own frame capture,
#     which dumps the 8-bit framebuffer, so it measures the render size directly
#     rather than inferring it from how the result looks.
#
#   * the result still fills the window. A frame that renders at 640x400 and is
#     then shown at 640x400 in the corner of a 1280x800 window would satisfy the
#     first check perfectly. So the window is grabbed from X and its edges are
#     checked for the black margin that letterboxing or a corner-drawn frame
#     leaves behind.
#
# Both renderers are covered: they stretch the frame by completely different
# means -- SDL_RenderSetLogicalSize on the software path, the GL blit in
# R_GLLivePresent -- and only one of them shares any code with the other.
#
# Native is checked too, against a reference grab made at the same window size,
# to prove the default path is untouched by any of it.
#
# Usage: test_renderscale.sh BUILD_DIR DATA_DIR   (both absolute)

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

for command in import xvfb-run python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-renderscale.XXXXXX)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT INT TERM

WIN_W=1280
WIN_H=800

failed=0

# $1 renderer, $2 scale, $3 tag. Leaves $work/$3.png (the window) and
# $work/$3-frame.png (the framebuffer, at whatever size the game rendered it).
run() {
	renderer=$1; scale=$2; tag=$3
	{
		printf 'Vid_xBRZ = 0;\n'
		printf 'Vid_RenderScale = %s;\n' "$scale"
		printf 'Vid_Renderer = "%s";\n' "$renderer"
		printf 'Vid_FullScreen = 0;\n'
		printf 'WindowedScreenWidth = %s;\n' "$WIN_W"
		printf 'WindowedScreenHeight = %s;\n' "$WIN_H"
	} >"$work/$tag.cfg"

	# The screen is the window size so a root grab is exactly the window, with
	# no window manager present to place or decorate anything.
	RS_DATA=$data_dir RS_BIN=$ec7wolf RS_WORK=$work RS_TAG=$tag \
	RS_RENDERER=$renderer RS_W=$WIN_W RS_H=$WIN_H \
	xvfb-run -a -s "-screen 0 ${WIN_W}x${WIN_H}x24" sh -c '
		cd "$RS_DATA"
		export SDL_AUDIODRIVER=dummy
		# A level is started because the frame counter only advances once one is
		# running, and the frame dump is how the render size gets measured.
		"$RS_BIN" --data CO7 --nowait --vid-renderer "$RS_RENDERER" \
			--config "$RS_WORK/$RS_TAG.cfg" --savedir "$RS_WORK/sv-$RS_TAG" \
			--res "$RS_W" "$RS_H" --tedlevel MAP01 --skill 2 \
			--capture-frame 2 --capture-file "$RS_WORK/$RS_TAG-frame.png" \
			--capture-maxframes 1000000 \
			>"$RS_WORK/$RS_TAG.log" 2>&1 &
		pid=$!
		sleep 22
		import -window root "$RS_WORK/$RS_TAG.png"
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	' || true

	if [ ! -s "$work/$tag.png" ]; then
		printf 'FAIL: %s produced no window grab; see %s/%s.log\n' \
			"$tag" "$work" "$tag" >&2
		failed=1
		return 1
	fi
	return 0
}

for renderer in software opengl; do
	run "$renderer" 1 "$renderer-native" || continue
	run "$renderer" 2 "$renderer-half" || continue
	# 1/3 of 1280x800 is 426x266, which is not one of the video modes the engine
	# offers. It has to come out at exactly that anyway: a render size is a
	# framebuffer, and snapping it to the nearest listed mode -- 480x270 -- would
	# hand a 16:9 frame to a 16:10 window and stretch it.
	run "$renderer" 3 "$renderer-third" || continue

	RS_RENDERER=$renderer RS_WORK=$work RS_W=$WIN_W RS_H=$WIN_H \
	python3 - <<'PY' || failed=1
import os, sys
from PIL import Image

renderer = os.environ["RS_RENDERER"]
work = os.environ["RS_WORK"]
winW, winH = int(os.environ["RS_W"]), int(os.environ["RS_H"])
ok = True

def fail(msg):
    global ok
    print("FAIL: %s: %s" % (renderer, msg))
    ok = False

# The frame dump is written from the framebuffer, so its size is the render size.
# Native is checked as well as 1/2: it is the default every existing config is
# on, and it has to keep rendering at the full window.
for label, want in (("native", (winW, winH)),
                    ("half", (winW//2, winH//2)),
                    ("third", (winW//3, winH//3))):
    frame = os.path.join(work, "%s-%s-frame.png" % (renderer, label))
    if not os.path.exists(frame):
        fail("no frame dump at %s; the run never reached a counted frame" % label)
        continue
    got = Image.open(frame).size
    if got != want:
        fail("at %s the game rendered %dx%d, expected %dx%d -- the scale did "
             "not reach the framebuffer" % ((label,) + got + want))
    else:
        print("%s: %s renders %dx%d inside a %dx%d window"
              % (renderer, label, got[0], got[1], winW, winH))

# A frame drawn small and left small would pass the check above. The window is
# grabbed to prove the frame was stretched over it and not parked in a corner.
def margin(path):
    im = Image.open(path).convert("RGB")
    px = im.load()
    w, h = im.size
    def blank_col(x): return all(px[x, y] == (0, 0, 0) for y in range(0, h, 4))
    def blank_row(y): return all(px[x, y] == (0, 0, 0) for x in range(0, w, 4))
    left = 0
    while left < w and blank_col(left): left += 1
    right = 0
    while right < w and blank_col(w-1-right): right += 1
    top = 0
    while top < h and blank_row(top): top += 1
    bottom = 0
    while bottom < h and blank_row(h-1-bottom): bottom += 1
    return left, right, top, bottom

half = os.path.join(work, "%s-half.png" % renderer)
native = os.path.join(work, "%s-native.png" % renderer)
mh = margin(half)
mn = margin(native)

# An all-black grab -- the game having exited before the screenshot, say --
# scans to a full-width margin on every side and would then compare equal to
# another all-black grab and pass. Refuse it outright.
for path, m in ((native, mn), (half, mh)):
    if m[0] >= winW or m[2] >= winH:
        fail("%s is a blank window; nothing was on screen when it was grabbed"
             % os.path.basename(path))

# Measured against Native rather than against zero: the art itself can be dark at
# an edge, and that is not the scaler's doing. What matters is that scaling down
# the render size did not shrink the picture on screen.
for i, side in enumerate(("left", "right", "top", "bottom")):
    if mh[i] > mn[i] + 8:
        fail("at 1/2 the picture has a %d px black %s margin against %d px at "
             "Native -- the frame is not filling the window"
             % (mh[i], side, mn[i]))

print("%s: window margins native=%s half=%s" % (renderer, mn, mh))
sys.exit(0 if ok else 1)
PY
done

# The frames compared above are gameplay, which the two renderers deliberately do
# not draw identically -- that is what test_gl_parity measures, with a tolerance.
# So they are not compared against each other here; what each must do is fill its
# own window at both scales, and render at the size asked for.

if [ "$failed" -ne 0 ]; then
	exit 1
fi

printf 'PASS: the render scale shrinks the frame and still fills the window\n'
