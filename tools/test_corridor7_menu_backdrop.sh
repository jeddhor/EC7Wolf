#!/bin/sh

# Regression test: the main menu builds its own backdrop from the game data.
#
# The splash behind the menu is VGA chunk 6, upscaled at runtime. Doing it that
# way is the whole point -- the art is commercial, so a pre-upscaled copy could
# not be distributed, while reading it out of the player's own data files
# distributes nothing. This guards that it keeps working, because the failure
# mode is quiet: the menu would simply go black for everyone who has no
# c7menu.pk3 installed, and every other test in the suite would still pass.
#
# Two runs, against a data directory that deliberately has no override:
#
#   1. Without c7menu.pk3 the art must be there and must be art -- many colours,
#      not a flat fill and not the black the menu falls back to.
#   2. With a synthetic c7menu.pk3 the art must become that instead. This is not
#      only an override test: it is what proves run 1 was drawing the generated
#      backdrop, rather than an override that had leaked in from somewhere.
#
# Usage: test_corridor7_menu_backdrop.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

for command in import xdotool xvfb-run python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-menubg.XXXXXX)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT INT TERM

# A data directory of symlinks, so the real one keeps whatever the player has
# installed there -- including the c7menu.pk3 this test must not see. CORR7CD.EXE
# is not optional: the game palette is read out of it, and without it startup
# stalls before a window ever appears.
mkdir -p "$work/data"
for f in "$data_dir"/*.CO7 "$data_dir/CORR7CD.EXE" "$data_dir/ec7wolf.pk3"; do
	[ -e "$f" ] || continue
	ln -s "$f" "$work/data/$(basename "$f")"
done

# The override for run 2: a solid magenta backdrop, which no scene in the real
# art resembles, so "did the override win" needs no tolerance to answer.
python3 - "$work/override.png" <<'PY'
import sys
from PIL import Image
Image.new("RGB", (320, 200), (255, 0, 255)).save(sys.argv[1])
PY
(cd "$work" && python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("c7menu.pk3", "w")
z.write("override.png", "graphics/C7MENUBG.png")
z.close()
PY
)

shoot() { # $1 output png
	out=$1
	# Root screen sized to the game window, so grabbing the root grabs exactly
	# the frame and the crop below needs no window geometry to be correct.
	xvfb-run -a -s "-screen 0 960x600x24" sh -c '
		cd "$MB_DATA"
		export SDL_AUDIODRIVER=dummy
		export SDL_VIDEODRIVER=x11
		"$MB_BUILD/ec7wolf" --data CO7 --no-upscale --nowait --vid-renderer software \
			--res 960 600 --config "$MB_WORK/cfg" --savedir "$MB_WORK/sv" \
			>"$MB_WORK/run.log" 2>&1 &
		pid=$!
		sleep 10
		# Past the title pages and into the menu. Two presses, because the first
		# only interrupts whichever page is showing.
		xdotool key --clearmodifiers Escape; sleep 1
		xdotool key --clearmodifiers Escape; sleep 2
		import -window root "$MB_SHOT"
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	'
	if [ ! -s "$out" ]; then
		printf 'FAIL: no menu screenshot; see %s/run.log\n' "$work" >&2
		exit 1
	fi
}

export MB_BUILD="$build_dir" MB_WORK="$work" MB_DATA="$work/data"

MB_SHOT="$work/generated.png"; export MB_SHOT
shoot "$work/generated.png"

mv "$work/c7menu.pk3" "$work/data/c7menu.pk3"
MB_SHOT="$work/overridden.png"; export MB_SHOT
shoot "$work/overridden.png"

python3 - "$work/generated.png" "$work/overridden.png" <<'PY'
import sys
from PIL import Image

# Only the left third is measured. The menu fades its backdrop to black from
# 38% of the width and covers the right with the item list, so this is the band
# where the art is shown unaltered.
def art(path):
    im = Image.open(path).convert("RGB")
    im = im.crop((0, 0, im.size[0]//3, im.size[1]))
    raw = im.tobytes()
    return [tuple(raw[i:i+3]) for i in range(0, len(raw), 3)]

gen_px, ovr_px = art(sys.argv[1]), art(sys.argv[2])

gen_colors = len(set(gen_px))
dark = sum(1 for r, g, b in gen_px if r < 16 and g < 16 and b < 16)
magenta = sum(1 for r, g, b in ovr_px if r > 100 and b > 100 and g < 100)

print("generated backdrop: %d distinct colours, %.0f%% near-black"
      % (gen_colors, 100.0*dark/len(gen_px)))
print("override backdrop: %.0f%% magenta" % (100.0*magenta/len(ovr_px)))

failed = False

# Real art, upscaled and requantised, lands in dozens of palette entries. A
# black fallback would be 1, and a flat fill or a solid colour only a handful.
if gen_colors < 32:
    print("FAIL: the backdrop uses only %d colours. The menu is not drawing the "
          "upscaled splash -- most likely it fell back to a black screen."
          % gen_colors)
    failed = True

if dark > 0.8*len(gen_px):
    print("FAIL: %.0f%% of the backdrop is black. The generated splash is not "
          "reaching the screen." % (100.0*dark/len(gen_px)))
    failed = True

if magenta < 0.9*len(ovr_px):
    print("FAIL: only %.0f%% of the backdrop is the override colour. Either "
          "c7menu.pk3 no longer wins, or the run above was never using the "
          "generated backdrop in the first place." % (100.0*magenta/len(ovr_px)))
    failed = True

sys.exit(1 if failed else 0)
PY

printf 'PASS: the menu builds its backdrop from the game data, and an override still wins\n'
