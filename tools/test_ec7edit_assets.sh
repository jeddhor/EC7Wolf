#!/bin/sh

# Regression test: EC7Edit decodes the real Corridor 7 assets.
#
# Milestone E2 of docs/corridor7-level-editor.md, owned-data half. The
# synthetic tests prove the decoders match the documented format; this proves
# the format is the one the shipped files are actually in, which no generated
# fixture can.
#
# Nothing retail is written, printed, or committed. The assertions are counts,
# a pixel digest, and a coverage figure -- facts about the data rather than the
# data itself. The digest is recomputed each run and compared with the previous
# stage of the same run, never with a constant baked into this file, since a
# constant derived from commercial data is still derived from it.
#
# Usage: test_ec7edit_assets.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
data_dir=$(cd "$2" && pwd)

for name in CORR7CD.EXE GFXTILES.CO7 MAPTEMP.CO7; do
	[ -f "$data_dir/$name" ] || { printf 'SKIP: no %s in %s\n' "$name" "$data_dir"; exit 0; }
done
command -v python3 >/dev/null 2>&1 || { printf 'SKIP: no python3\n'; exit 0; }

before=$(python3 -c "
import hashlib, pathlib, sys
h = hashlib.sha256()
for name in sorted(pathlib.Path(sys.argv[1]).glob('*.CO7')):
    h.update(name.read_bytes())
h.update((pathlib.Path(sys.argv[1]) / 'CORR7CD.EXE').read_bytes())
print(h.hexdigest())" "$data_dir")

PYTHONPATH="$repo/editor" python3 - "$data_dir" "$repo" <<'PYEOF'
import hashlib
import sys
from collections import Counter
from pathlib import Path

from ec7edit_core.archive import parse_archive
from ec7edit_core.assets import (
    average_color, encode_png, extract_vga, is_blank, load_palette,
    parse_gfx_header, sprite_rgba, wall_rgb,
)
from ec7edit_core.catalog import load_catalog

data = Path(sys.argv[1])
repo = Path(sys.argv[2])
status = 0


def ok(message):
    print(f"  ok   {message}")


def note(message):
    print(f"  ..   {message}")


def fail(message):
    global status
    print(f"  FAIL {message}")
    status = 1


print("The palette")
palette = load_palette((data / "CORR7CD.EXE").read_bytes())
ok(f"{len(palette) // 3} entries read from the executable")
if len(set(palette)) < 32:
    fail("the palette is suspiciously flat")
else:
    ok(f"{len(set(zip(palette[0::3], palette[1::3], palette[2::3])))} distinct colors")

print("\nWalls and sprites")
gfx = (data / "GFXTILES.CO7").read_bytes()
header = parse_gfx_header(gfx)
note(f"{header.chunk_count} chunks: {header.sprite_start} walls, "
     f"{header.sound_start - header.sprite_start} sprites")

digest = hashlib.sha256()
walls = blank_walls = 0
for index in header.wall_pages():
    page = header.chunk(gfx, index)
    if len(page) < 64 * 64:
        continue
    rgb = wall_rgb(page, palette)
    digest.update(rgb)
    walls += 1
    blank_walls += is_blank(rgb, channels=3)
if walls < 200:
    fail(f"only {walls} wall pages decoded")
else:
    ok(f"{walls} wall pages decoded, {blank_walls} of them blank")

sprites = failures = 0
for index in header.sprite_pages():
    page = header.chunk(gfx, index)
    try:
        digest.update(sprite_rgba(page, palette))
        sprites += 1
    except Exception:
        failures += 1
if failures:
    fail(f"{failures} sprite pages did not decode")
else:
    ok(f"{sprites} sprite pages decoded, none refused")
note(f"pixel digest {digest.hexdigest()[:16]}")

# A PNG of a real page must be encodable; that is the whole thumbnail path.
sample = wall_rgb(header.chunk(gfx, 0), palette)
png = encode_png(64, 64, sample, alpha=False)
if png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100:
    ok(f"a wall thumbnail encodes ({len(png)} bytes, average {average_color(sample)})")
else:
    fail("the thumbnail did not encode")

print("\nVGAGRAPH")
try:
    pictures = extract_vga(
        (data / "VGADICT.CO7").read_bytes(),
        (data / "VGAHEAD.CO7").read_bytes(),
        (data / "VGAGRAPH.CO7").read_bytes(),
        palette,
    )
    if len(pictures) < 50:
        fail(f"only {len(pictures)} pictures decoded")
    else:
        ok(f"{len(pictures)} pictures decoded, largest "
           f"{max(p.width for p in pictures)}x{max(p.height for p in pictures)}")
except FileNotFoundError:
    note("no VGAGRAPH set here")

print("\nThe catalog against the shipped maps")
catalog = load_catalog(repo / "editor" / "resources" / "editor_catalog.json")
archive = parse_archive((data / "MAPTEMP.CO7").read_bytes())

plane0 = Counter()
plane1 = Counter()
for record in archive:
    plane0.update(record.planes.planes[0])
    plane1.update(record.planes.planes[1])

unknown0 = sorted(v for v in plane0 if v and catalog.for_value(0, v) is None)
unknown1 = sorted(v for v in plane1 if v and catalog.for_value(1, v) is None)
note(f"{len(archive)} maps, {len(plane0)} distinct plane-0 values, "
     f"{len(plane1)} distinct plane-1 values")

if unknown0:
    fail(f"plane-0 values in the shipped maps with no catalog entry: {unknown0[:20]}")
else:
    ok("every plane-0 value used by the shipped maps has an entry")
if unknown1:
    fail(f"plane-1 values in the shipped maps with no catalog entry: {unknown1[:20]}")
else:
    ok("every plane-1 value used by the shipped maps has an entry")

# A sprite the catalog points at has to exist in the artwork, or the palette
# would show a hole where an alien should be.
missing = [
    entry.key for entry in catalog
    if entry.sprite is not None
    and not (0 <= header.sprite_start + entry.sprite < header.sound_start)
]
if missing:
    fail(f"{len(missing)} entries name a sprite page outside GFXTILES: {missing[:5]}")
else:
    ok("every catalog sprite reference is inside the artwork")

sys.exit(status)
PYEOF
result=$?

after=$(python3 -c "
import hashlib, pathlib, sys
h = hashlib.sha256()
for name in sorted(pathlib.Path(sys.argv[1]).glob('*.CO7')):
    h.update(name.read_bytes())
h.update((pathlib.Path(sys.argv[1]) / 'CORR7CD.EXE').read_bytes())
print(h.hexdigest())" "$data_dir")

printf '\nThe data was only read\n'
if [ "$before" = "$after" ]; then
	printf '  ok   sha256 over the data set is unchanged\n'
else
	printf '  FAIL the game data changed during the run\n'
	result=1
fi

if [ "$result" -eq 0 ]; then
	printf '\nPASS: the real assets decode.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$result"
