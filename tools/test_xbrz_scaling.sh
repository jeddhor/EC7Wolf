#!/bin/sh

# Regression test: xBRZ image scaling.
#
# Two things are being asserted, and they pull in opposite directions.
#
# The filter must actually run. A scaler that silently fell back to point
# sampling would still produce an image of the right size, so "it is N times
# bigger" proves nothing on its own; the output is compared against the
# nearest-neighbour blow-up of the same frame and must differ over a real share
# of the picture, in colours that were not in the source palette at all.
#
# And it must still be the same picture. xBRZ reshapes edges, so a per-pixel
# comparison against the source is meaningless -- but box-downscaling its output
# back to the source resolution has to land very close to where it started. That
# is what separates "smoothed the frame" from "corrupted the frame", which the
# difference count above would happily pass.
#
# Finally, scaling is presentation only. The simulation checksum must not move
# when it is switched on, at any factor.
#
# Usage: test_xbrz_scaling.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
display=:109
work=$(mktemp -d /tmp/ec7wolf-xbrz.XXXXXX)

cleanup() {
	[ -n "${xvfb:-}" ] && kill "$xvfb" 2>/dev/null || true
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

Xvfb "$display" -screen 0 900x600x24 >"$work/xvfb.log" 2>&1 &
xvfb=$!
sleep 2

# One scene, captured at 320x200 so the source is the resolution the art was
# actually drawn at -- which is the case the filter exists for.
shoot() { # $1 label  $2.. extra engine arguments
	label=$1; shift
	(
		cd "$data_dir"
		timeout 120s env DISPLAY="$display" SDL_AUDIODRIVER=dummy \
			"$build_dir/ec7wolf" --data CO7 --nowait --normal --tedlevel MAP01 \
			--vid-renderer software --res 320 200 \
			--capture-rngseed 1 --capture-warp 17 31 0 \
			"$@" \
			--capture-frame 8 --capture-file "$work/$label.png" --capture-maxtics 60 \
			--config "$work/cfg" --savedir "$work/sv"
	) >"$work/$label.log" 2>&1
	if [ ! -s "$work/$label.png" ]; then
		printf 'FAIL: no capture for %s; see %s/%s.log\n' "$label" "$work" "$label" >&2
		exit 1
	fi
}

shoot plain
shoot scaled2 --capture-xbrz 2
shoot scaled4 --capture-xbrz 4

# Presentation only: the same run at every factor must fold to the same world.
base=$(sed -n 's/.*summary tics=[0-9]* frames=[0-9]* checksum=\([0-9a-f]*\).*/\1/p' "$work/plain.log")
for label in scaled2 scaled4; do
	got=$(sed -n 's/.*summary tics=[0-9]* frames=[0-9]* checksum=\([0-9a-f]*\).*/\1/p' "$work/$label.log")
	if [ "$got" != "$base" ]; then
		printf 'FAIL: checksum moved with scaling on (%s: %s, off: %s). Image scaling must be render-only.\n' \
			"$label" "$got" "$base" >&2
		exit 1
	fi
done
printf 'checksum %s unchanged at every factor\n' "$base"

python3 - "$work/plain.png" "$work/scaled2-xbrz2.png" 2 "$work/scaled4-xbrz4.png" 4 <<'PY'
import sys
from PIL import Image

# Share of the frame xBRZ must reshape relative to a plain blow-up. Measured at
# 8.8% on the MAP01 scene below; the floor leaves room for art with fewer
# diagonals without leaving room for the filter not running at all.
MIN_CHANGED_PCT = 2.0
# Box-downscaling the result has to land back on the source. Measured at 1.06
# levels of mean absolute error out of 255 -- the slack here is for a different
# scene, not for a different picture.
MAX_ROUNDTRIP_MAE = 6.0

src = Image.open(sys.argv[1]).convert("RGB")
src_colors = set(src.get_flattened_data() if hasattr(src, "get_flattened_data")
                 else src.getdata())

failed = False
args = sys.argv[2:]
for i in range(0, len(args), 2):
    path, factor = args[i], int(args[i+1])
    big = Image.open(path).convert("RGB")

    want = (src.size[0]*factor, src.size[1]*factor)
    if big.size != want:
        print("FAIL: %dx output is %dx%d, expected %dx%d"
              % (factor, big.size[0], big.size[1], want[0], want[1]))
        failed = True
        continue

    nn = src.resize(big.size, Image.NEAREST)
    bb, nb = big.tobytes(), nn.tobytes()
    total = len(bb)//3
    changed = sum(1 for j in range(0, len(bb), 3) if bb[j:j+3] != nb[j:j+3])
    pct = 100.0*changed/total

    back = big.resize(src.size, Image.BOX)
    kb, sb = back.tobytes(), src.tobytes()
    mae = sum(abs(kb[j]-sb[j]) for j in range(len(kb)))/len(kb)

    big_colors = set(big.get_flattened_data() if hasattr(big, "get_flattened_data")
                     else big.getdata())
    blended = len(big_colors - src_colors)

    print("%dx: %.1f%% of pixels reshaped, %d blended colours (source has %d), "
          "round-trip MAE %.2f" % (factor, pct, blended, len(src_colors), mae))

    if pct < MIN_CHANGED_PCT:
        print("FAIL: only %.1f%% of the %dx output differs from a nearest-neighbour "
              "blow-up. The frame was enlarged but not filtered." % (pct, factor))
        failed = True
    if blended == 0:
        print("FAIL: the %dx output uses no colour outside the source frame's own. "
              "xBRZ smooths edges by blending, so it cannot have run." % factor)
        failed = True
    if mae > MAX_ROUNDTRIP_MAE:
        print("FAIL: downscaling the %dx output back to %dx%d misses the source by "
              "%.2f levels. That is a different picture, not a smoothed one."
              % (factor, src.size[0], src.size[1], mae))
        failed = True

sys.exit(1 if failed else 0)
PY

printf 'PASS: xBRZ upscales without disturbing the simulation\n'
