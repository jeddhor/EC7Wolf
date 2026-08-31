#!/bin/sh

# Regression test: EC7Edit's persistence and export do not lose or leak work.
#
# Milestone E8 of docs/corridor7-level-editor.md. The exit gate is a round
# trip: import all sixty owned maps, save and reopen the project, export both
# output forms, reparse them, and prove every retail source byte is unchanged.
#
# Four properties, each of which fails invisibly:
#
#   1. the project survives a round trip. Save, reopen, compare every plane of
#      every map. A serializer that drops plane 2 or reorders anything is
#      discovered here rather than by somebody's lost work.
#   2. a private full-archive export replaces the maps it was told to and
#      copies the rest through untouched. This is the one that could quietly
#      rewrite fifty-nine maps to save one: the encoder is byte-exact against
#      the original TED5 output, and re-encoding with nothing replaced has to
#      give back the same file it read.
#   3. the source is never written. Not by import, not by export, not by
#      anything -- checked by hashing it before and after.
#   4. a shareable preview WAD carries only the maps asked for.
#
# Needs the archive. Skipped without it; it never prints map content.
#
# Usage: test_ec7edit_e8.sh [DATA_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"
data=${1:-}

command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }
grep -q "def replace_records" "$editor/ec7edit_core/archive.py" 2>/dev/null || {
	printf 'SKIP: no full-archive export yet\n'; exit 0; }

status=0
say() { printf '  %-5s %s\n' "$1" "$2"; }

# --- the unit and GUI halves ---------------------------------------------
if (cd "$editor" && QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=x11 python3 -m pytest \
	tests/unit/test_project.py tests/unit/test_archive.py tests/unit/test_wad.py \
	tests/unit/test_paths.py -q >/tmp/ec7edit-e8-unit.log 2>&1); then
	say "ok" "project, archive, WAD and path units pass"
else
	say "FAIL" "see /tmp/ec7edit-e8-unit.log"
	status=1
fi

if (cd "$editor" && QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=x11 python3 -m pytest \
	tests/gui/test_shell.py -q >/tmp/ec7edit-e8-gui.log 2>&1); then
	say "ok" "save, save-a-copy, external change, autosave and recovery"
else
	say "FAIL" "see /tmp/ec7edit-e8-gui.log"
	status=1
fi

# --- the owned-data round trip -------------------------------------------
if [ -z "$data" ] || [ ! -f "$data/MAPTEMP.CO7" ]; then
	say "..." "owned-data round trip skipped: no MAPTEMP.CO7 given"
	[ "$status" -eq 0 ] && printf 'PASS: E8 persistence and export (data-free half)\n'
	exit "$status"
fi

before=$(sha256sum "$data/MAPTEMP.CO7" | cut -d' ' -f1)

if (cd "$editor" && MAPTEMP="$data/MAPTEMP.CO7" python3 - <<'PY'
import hashlib, os, sys, tempfile
sys.path.insert(0, ".")
from pathlib import Path

from ec7edit_core.archive import encode_archive, parse_archive, read_archive, replace_records
from ec7edit_core.document import MapDocument, ProjectDocument, SourceReference
from ec7edit_core.project import load_project, save_project
from ec7edit_core.wad import build_preview_wad, read_preview_wad

source = Path(os.environ["MAPTEMP"])
archive = read_archive(source)
count = len(archive.records)

# 1. every map imports, and a re-encode of what was read is the same file.
if replace_records(archive, {}) != source.read_bytes():
    print("FAIL: re-encoding an untouched archive did not reproduce it")
    raise SystemExit(1)

# 2. all sixty into a project, saved and reopened, plane for plane.
project = ProjectDocument.create()
for record in archive.records:
    project = project.added(MapDocument.from_record(
        record, source=SourceReference(str(source), "0" * 64, record.number)))
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "all.ec7project"
    save_project(project, path)
    back = load_project(path)
    if len(back) != count:
        print(f"FAIL: {count} maps in, {len(back)} out")
        raise SystemExit(1)
    for original, reopened in zip(project.maps, back.maps):
        if original.planes.planes != reopened.planes.planes:
            print(f"FAIL: {original.lump_name} changed across a save and reopen")
            raise SystemExit(1)
        if original.native_name.raw != reopened.native_name.raw:
            print(f"FAIL: {original.lump_name} lost its exact name bytes")
            raise SystemExit(1)

    # 3. a private full archive with one slot replaced: that slot changed,
    #    every other one is identical to what came in.
    swapped = replace_records(archive, {1: archive.by_number(2)})
    rebuilt = parse_archive(swapped)
    if rebuilt.by_number(1).planes.planes != archive.by_number(2).planes.planes:
        print("FAIL: the replaced slot does not hold the map it was given")
        raise SystemExit(1)
    for number in range(2, count + 1):
        if rebuilt.by_number(number).planes.planes != archive.by_number(number).planes.planes:
            print(f"FAIL: map {number} was disturbed by replacing map 1")
            raise SystemExit(1)

    # 4. a preview WAD holds what it was given and nothing else.
    chosen = [d for d in project.maps[:3]]
    blob = build_preview_wad([(d.lump_name, d.to_record()) for d in chosen])
    names = [name for name, _ in read_preview_wad(blob)]
    if names != [d.lump_name for d in chosen]:
        print(f"FAIL: the preview WAD holds {names}")
        raise SystemExit(1)

print(f"{count} maps: imported, saved, reopened, re-encoded and exported")
PY
) >/tmp/ec7edit-e8-corpus.log 2>&1; then
	say "ok" "$(cat /tmp/ec7edit-e8-corpus.log)"
else
	say "FAIL" "$(cat /tmp/ec7edit-e8-corpus.log)"
	status=1
fi

after=$(sha256sum "$data/MAPTEMP.CO7" | cut -d' ' -f1)
if [ "$before" = "$after" ]; then
	say "ok" "the source archive is byte-for-byte unchanged"
else
	say "FAIL" "THE SOURCE ARCHIVE WAS MODIFIED"
	status=1
fi

[ "$status" -eq 0 ] && printf 'PASS: E8 persistence, import and export\n'
exit "$status"
