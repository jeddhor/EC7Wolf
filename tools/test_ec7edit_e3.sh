#!/bin/sh

# Regression test: EC7Edit's document model, undo and project file hold.
#
# Milestone E3 of docs/corridor7-level-editor.md. Two of these checks are the
# reason the milestone exists:
#
#   * ten thousand mixed operations -- paint, rename, undo, redo, gesture
#     boundaries -- run against an independent reference model, compared as
#     they go. An undo that recomputed instead of remembering would pass every
#     hand-written test and fail this one;
#   * the atomic save is failed on purpose at each of its eleven stages, and
#     the file left behind must parse and be either the old project or the new
#     one. A durable save is easy to write and impossible to believe without
#     breaking it deliberately.
#
# Data-free: no Corridor 7, no build, no display.
#
# Usage: test_ec7edit_e3.sh [PYTHON]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

[ -d "$editor/ec7edit_core" ] || { printf 'SKIP: no editor/ec7edit_core yet\n'; exit 0; }

find_python() {
	if [ "$#" -ge 1 ] && [ -n "$1" ]; then printf '%s\n' "$1"; return; fi
	if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; return; fi
	if command -v uv >/dev/null 2>&1; then
		managed=$(uv python find 3.12 2>/dev/null || true)
		[ -n "$managed" ] && [ -x "$managed" ] && { printf '%s\n' "$managed"; return; }
	fi
	command -v python3 2>/dev/null || true
}

python=$(find_python "${1:-}")
[ -n "$python" ] || { printf 'SKIP: no python3\n'; exit 0; }

status=0
check() {
	message=$1
	shift
	if "$@" >/dev/null 2>&1; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

work=$(mktemp -d /tmp/ec7edit-e3.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
export PYTHONPATH="$editor"

printf 'Unit tests\n'
for suite in test_document test_commands test_transforms test_project; do
	file="$editor/tests/unit/$suite.py"
	[ -f "$file" ] || { printf '  FAIL %s is missing\n' "$suite"; status=1; continue; }
	start=$(date +%s)
	if output=$("$python" "$file" 2>&1); then
		printf '  ok   %-16s %-14s %ss\n' "$suite" \
			"$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]*' | head -1)" \
			"$(( $(date +%s) - start ))"
	else
		printf '  FAIL %s\n' "$suite"
		printf '%s\n' "$output" | tail -25 | sed 's/^/    /'
		status=1
	fi
done

printf '\nThe headless project path, end to end\n'
# A synthetic archive, so this needs no game data: create, import, edit the
# words directly, save, reopen, export, and read the WAD back.
"$python" - "$work" <<'PYEOF' && ok=1 || ok=0
import sys
from pathlib import Path

from ec7edit_core.archive import MapRecord, encode_archive
from ec7edit_core.commands import History, paint_cells
from ec7edit_core.document import MapDocument
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.project import load_project, new_project, save_project
from ec7edit_core.wad import build_preview_wad, read_preview_wad

work = Path(sys.argv[1])
archive = work / "source.c7map"
records = [
    MapRecord(n + 1, NativeName.from_text(f"SYNTH{n}"),
              MapPlanes(8, 8, tuple(tuple((p * 7 + c + n) % 300 for c in range(64))
                                    for p in range(3))))
    for n in range(3)
]
archive.write_bytes(encode_archive(records))
before = archive.read_bytes()

project = new_project("Gate")
for record in records[:2]:
    project = project.added(MapDocument.from_record(record))

history = History()
document = project.maps[0]
project = history.do(project, paint_cells(document, 0, [(x, 0) for x in range(8)], 42,
                                          gesture="stroke"))
assert history.depth == 1, "a stroke must be one undo step"
painted = project.map_by_uuid(document.uuid).planes.planes[0][:8]
assert painted == (42,) * 8, painted

path = work / "gate.ec7project"
save_project(project, path)
reopened = load_project(path)
assert len(reopened) == 2
assert reopened.maps[0].planes.planes == project.maps[0].planes.planes, "planes changed on reopen"
assert not reopened.dirty

blob = build_preview_wad([(d.lump_name, d.to_record()) for d in reopened.maps])
(work / "gate.wad").write_bytes(blob)
pairs = read_preview_wad(blob)
assert [m for m, _ in pairs] == ["MAP01", "MAP02"], pairs
assert pairs[0][1].planes.planes[0][:8] == (42,) * 8, "the edit did not reach the export"

undone = history.undo(project)
assert undone.map_by_uuid(document.uuid).planes.planes == document.planes.planes

assert archive.read_bytes() == before, "the source archive was written to"
print("  ok   create, import, edit, save, reopen, export, read back")
PYEOF
[ "$ok" -eq 1 ] || { printf '  FAIL the headless path did not complete\n'; status=1; }

printf '\nThe CLI\n'
check "project-new creates a project" \
	"$python" -m ec7edit_core project-new --output "$work/cli.ec7project" --name Gate
check "project-inspect reads it back" \
	"$python" -m ec7edit_core project-inspect "$work/cli.ec7project"
check "project-import brings a map in" \
	"$python" -m ec7edit_core project-import "$work/source.c7map" \
		--project "$work/cli.ec7project" --map 2
check "project-export writes a preview WAD" \
	"$python" -m ec7edit_core project-export "$work/cli.ec7project" \
		--output "$work/cli.wad"
check "the exported WAD reads back" "$python" -c "
import sys
from ec7edit_core.wad import read_preview_wad
pairs = read_preview_wad(open('$work/cli.wad', 'rb').read())
sys.exit(0 if len(pairs) == 1 else 1)"

printf '\nA project file is inspectable and diffable\n'
check "it is JSON" "$python" -c "
import json; json.load(open('$work/gate.ec7project'))"
check "plane words are integers, not an opaque blob" \
	sh -c "! grep -qE 'base64|\"[A-Za-z0-9+/]{200,}\"' '$work/gate.ec7project'"
check "saving twice is byte-identical" sh -c "
	'$python' -c \"
from ec7edit_core.project import load_project, save_project
p = load_project('$work/gate.ec7project')
save_project(p, '$work/again.ec7project')\" && cmp -s '$work/gate.ec7project' '$work/again.ec7project'"

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E3 document model intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
