#!/bin/sh

# Regression test: a campaign can carry and play its own cinematic.
#
# Milestone E14 of docs/corridor7-level-editor.md. The CD's three animations
# sit in a directory beside the game data because that is where the disc leaves
# them, and until this the engine looked nowhere else -- so a campaign could
# not have an ending of its own however it was packaged.
#
# Two halves, and the gate proves both because either alone is worthless:
#
#   1. The EDITOR writes FLIC the engine can read. Checked against the engine's
#      own decoder rather than the editor's idea of one: --flictest prints an
#      FNV-1a checksum of every decoded frame, and this computes the same
#      checksum over the frames that went in. Every frame must match, byte for
#      byte, or the encoder is producing something that merely looks like an
#      animation.
#
#      That check earns its keep. FLIC's two compression chunks use OPPOSITE
#      sign conventions -- BRUN's positive count is a run, LC's is literals --
#      and writing BRUN's convention into LC produces a file whose first frame
#      is perfect and whose every later frame is noise. Frame checksums caught
#      it; a file that "plays" would not have.
#
#   2. The ENGINE finds it in a loaded resource. A pk3 carrying
#      video/NAME.CO7, a campaign ending on it, and no video directory on disk
#      at all -- so if it plays, it played from the pack.
#
# Needs the archive and a display. Skipped without them.
#
# Usage: test_ec7edit_e14.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

. "$repo/tools/xvfb_common.sh"

command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }
[ -f "$editor/ec7edit_core/flic.py" ] || { printf 'SKIP: no FLIC writer yet\n'; exit 0; }
grep -q "FindFlicLump" "$repo/src/c7_flic.cpp" 2>/dev/null || {
	printf 'SKIP: this build cannot play a cinematic from a resource\n'; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data\n'; exit 0; }

status=0
work=$(mktemp -d /tmp/ec7wolf-e14.XXXXXX)
game=""
cleanup() {
	[ -n "$game" ] && kill "$game" 2>/dev/null
	xvfb_stop 2>/dev/null || true
	[ "$status" -eq 0 ] && rm -rf "$work" || printf '  logs kept in %s\n' "$work"
}
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

say()  { printf '  %-5s %s\n' "$1" "$2"; }
fail() { printf '  %-5s %s\n' "FAIL" "$1" >&2; status=1; }

# --- 1. frames in, cinematic out --------------------------------------------
printf '\nWriting an animation the engine can read\n'
PYTHONPATH="$editor" python3 - "$work" <<'PY' || { printf 'FAIL: frames\n' >&2; exit 1; }
import struct
import sys
import zlib
from pathlib import Path

from ec7edit_core import flic

frames = Path(sys.argv[1]) / "frames"
frames.mkdir(parents=True, exist_ok=True)


def png(width, height, rgb):
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3]
                   for y in range(height))

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# Flat bands, a moving block and a gradient: between them they use every
# encoding this writes -- runs, literals, deltas, and a whole-frame fallback.
for step in range(16):
    rgb = bytearray(flic.WIDTH * flic.HEIGHT * 3)
    for y in range(flic.HEIGHT):
        for x in range(flic.WIDTH):
            at = (y * flic.WIDTH + x) * 3
            rgb[at] = (x * 255) // flic.WIDTH
            rgb[at + 1] = 40 if (y // 25) % 2 else 200
            rgb[at + 2] = 30
    left = 10 + step * 18
    for y in range(70, 130):
        for x in range(left, min(flic.WIDTH, left + 50)):
            at = (y * flic.WIDTH + x) * 3
            rgb[at], rgb[at + 1], rgb[at + 2] = 250, 250, 40
    (frames / f"{step:04d}.png").write_bytes(png(flic.WIDTH, flic.HEIGHT, bytes(rgb)))
print(f"  ..   wrote 16 frames")
PY

( cd "$editor" && PYTHONPATH="$editor" python3 -m ec7edit_core video-encode \
	"$work/frames" --output "$work/MYENDING.CO7" --fps 14 ) >"$work/encode.txt" 2>&1 || {
	fail "video-encode failed"; cat "$work/encode.txt" >&2; exit 1; }
say ok "$(grep -o '[0-9]* frames.*kB' "$work/encode.txt" | head -1)"

"$build_dir/ec7wolf" --flictest "$work/MYENDING.CO7" >"$work/flictest.txt" 2>&1 || {
	fail "the engine could not read it"; cat "$work/flictest.txt" >&2; exit 1; }

PYTHONPATH="$editor" python3 - "$work" <<'PY' || status=1
import re
import sys
from pathlib import Path

from ec7edit_core import flic, imagery

work = Path(sys.argv[1])


def fnv(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


# The same frames, reduced the same way, so the expected checksums are
# computed from the SOURCE rather than from anything the encoder produced.
images = [imagery.read_png(p)[2] for p in sorted((work / "frames").glob("*.png"))]
palette = imagery.build_palette(images)
mapping = imagery.build_mapping(palette)
expected = [f"{fnv(imagery.quantize(rgb, mapping)):08x}" for rgb in images]

palsum = 2166136261
for red, green, blue in palette:
    for channel in (red, green, blue):
        palsum = ((palsum ^ channel) * 16777619) & 0xFFFFFFFF

got = {}
for line in (work / "flictest.txt").read_text().splitlines():
    match = re.match(r"frame (\d+) image ([0-9a-f]+) palette ([0-9a-f]+)", line)
    if match:
        got[int(match.group(1))] = (match.group(2), match.group(3))

if len(got) != len(expected):
    sys.exit(f"  FAIL  the engine decoded {len(got)} frames, {len(expected)} were written")
wrong = [index for index, want in enumerate(expected, 1)
         if got.get(index) != (want, f"{palsum:08x}")]
if wrong:
    sys.exit(f"  FAIL  {len(wrong)} of {len(expected)} frames decoded to something "
             f"other than what was encoded (first: {wrong[0]})")
print(f"  ok    all {len(expected)} frames decode byte-for-byte to the source, "
      "through the engine's own decoder")
PY

# --- 2. a campaign that carries its own ending ------------------------------
printf '\nPlaying it from a resource pack\n'
PYTHONPATH="$editor" python3 - "$work" <<'PY' || exit 1
import sys
import zipfile
from pathlib import Path

from ec7edit_core.document import MapDocument, new_uuid
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.wad import build_preview_wad

work = Path(sys.argv[1])
W = H = 16
walls = [1] * (W * H)
objects = [0] * (W * H)
for y in range(1, H - 1):
    for x in range(1, W - 1):
        walls[y * W + x] = 256
at = lambda x, y: y * W + x
objects[at(3, 3)] = 19
walls[at(3, 2)] = 63            # the elevator, right in front of the start

document = MapDocument(uuid=new_uuid(), slot=61,
                       native_name=NativeName.from_text("Finale"),
                       planes=MapPlanes(W, H, (tuple(walls), tuple(objects),
                                               tuple([0] * (W * H)))))

mapinfo = '''clearepisodes
episode "MAP61"
{
\tname = "Cinematic Trial"
\tkey = "C"
}

intermission MyEnding
{
\tFlic
\t{
\t\tName = "MYENDING"
\t}
\tGotoTitle
\t{
\t}
}

map "MAP61" "The Finale"
{
\tnext = EndSequence, "MyEnding"
\tnointermission
\tcluster = 1
}
'''

with zipfile.ZipFile(work / "finale.pk3", "w") as archive:
    archive.writestr("maps/MAP61.wad", build_preview_wad([("MAP61", document.to_record())]))
    archive.writestr("MAPINFO", mapinfo)
    archive.writestr("video/MYENDING.CO7", (work / "MYENDING.CO7").read_bytes())

# The same campaign naming an animation nothing carries, so the engine's
# report of a missing one is checked as well as its report of a found one.
missing = mapinfo.replace('"MYENDING"', '"NOSUCHFILM"')
with zipfile.ZipFile(work / "missing.pk3", "w") as archive:
    archive.writestr("maps/MAP61.wad", build_preview_wad([("MAP61", document.to_record())]))
    archive.writestr("MAPINFO", missing)
print("  ..   built finale.pk3 and missing.pk3")
PY

lab="$work/lab"
mkdir -p "$lab"
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done
# Deliberately NO video directory. If a cinematic plays, it came from the pack.
rm -rf "$lab/video"
cp "$work/finale.pk3" "$work/missing.pk3" "$lab/"

display=:184
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || {
	printf 'SKIP: no Xvfb available\n'; exit 0; }

play() { # $1 label  $2 pack  $3 what to wait for
	label=$1 pack=$2 marker=$3
	# stdbuf, because this waits for a line to APPEAR in the log. The engine's
	# stdout is a file here, so libc block-buffers it and the line that says a
	# cinematic is playing sits in the buffer until the process exits -- which
	# is after the wait has given up. The evidence was always correct and
	# always two minutes late.
	( cd "$lab"
	  exec env DISPLAY="$display" SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
		stdbuf -oL -eL ./ec7wolf --data CO7 --nowait --file "$pack" \
		--tedlevel MAP61 --skill 2 --capture-rngseed 1 --capture-maxtics 400 \
		--capture-place 10 3.5 3.5 90 --capture-use 20 6 \
		--config "$work/$label.cfg" --savedir "$work/$label.saves"
	) >"$work/$label.log" 2>&1 &
	game=$!
	# Waited for by its evidence, not by a clock: the animation runs for a
	# second or so and the victory page after it waits for a keypress.
	waited=0
	while [ "$waited" -lt 600 ]; do
		kill -0 "$game" 2>/dev/null || break
		grep -q "$marker" "$work/$label.log" 2>/dev/null && break
		sleep 0.2
		waited=$((waited + 1))
	done
	[ "$waited" -ge 600 ] && fail "$label never reported anything in two minutes"
	kill "$game" 2>/dev/null || true
	wait "$game" 2>/dev/null || true
	game=""
	sed -i 's/\x08//g' "$work/$label.log" 2>/dev/null || true
}

play finale finale.pk3 "Cinematic:"
grep -q "no .*video directory" "$work/finale.log" ||
	fail "the lab has a video directory after all; this proves nothing"
report=$(grep "^Cinematic: playing" "$work/finale.log" | head -1)
case $report in
	*"playing MYENDING from a loaded resource"*)
		say ok "${report#Cinematic: }" ;;
	*)
		fail "the campaign's own ending did not play (${report:-nothing reported})"
		tail -6 "$work/finale.log" >&2 || true ;;
esac

play missing missing.pk3 "not found"
if grep -q "Cinematic 'NOSUCHFILM' was not found" "$work/missing.log"; then
	say ok "and an ending naming an animation nothing carries says so"
else
	fail "a missing cinematic passed silently, which looks like a hung game"
fi

strays=$(cat "$work"/*.log 2>/dev/null | grep -c "Could not stat" || true)
[ "$strays" -eq 0 ] && say ok "no option was misread as a resource path" \
	|| fail "$strays 'Could not stat' line(s)"

[ "$status" -eq 0 ] && printf '\nPASS: a campaign can carry its own cinematic.\n' \
	|| printf '\nFAIL: see above.\n' >&2
exit "$status"
