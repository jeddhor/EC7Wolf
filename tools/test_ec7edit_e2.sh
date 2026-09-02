#!/bin/sh

# Regression test: EC7Edit's asset decoders and semantic catalog hold.
#
# Milestone E2 of docs/corridor7-level-editor.md. Three things are guarded:
#
#   * the graphics decoders, on inputs generated to the documented format --
#     including the hostile ones, since GFXTILES and its column-post sprites
#     are made of offsets and every offset is an index into a buffer;
#   * the catalog, which is generated from the engine's own translation and
#     actor definitions and is committed. A stale one is the failure that shows
#     up as the editor describing a game the engine no longer plays, so the
#     gate regenerates and diffs;
#   * tools/c7assets.py, which is now built from those same decoders rather
#     than carrying a second copy of them. E1 found what two implementations
#     of one format cost, so this is checked the same way: rebuild and diff.
#
# Data-free. Every input is generated, and nothing here needs Corridor 7, a
# build or a display. The owned-data half is test_ec7edit_assets.sh.
#
# Usage: test_ec7edit_e2.sh [PYTHON]

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

export PYTHONPATH="$editor"

printf 'Unit tests\n'
for suite in test_assets test_catalog; do
	file="$editor/tests/unit/$suite.py"
	[ -f "$file" ] || { printf '  FAIL %s is missing\n' "$suite"; status=1; continue; }
	if output=$("$python" "$file" 2>&1); then
		printf '  ok   %-14s %s\n' "$suite" \
			"$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]*' | head -1)"
	else
		printf '  FAIL %s\n' "$suite"
		printf '%s\n' "$output" | tail -20 | sed 's/^/    /'
		status=1
	fi
done

printf '\nThe catalog matches the engine it describes\n'
if "$python" "$editor/scripts/generate_catalog.py" verify >/dev/null 2>&1; then
	printf '  ok   editor_catalog.json is current\n'
else
	printf '  FAIL editor_catalog.json is stale; run generate_catalog.py write\n'
	status=1
fi
entries=$("$python" -c "
from ec7edit_core.catalog import load_catalog
from collections import Counter
c = load_catalog('$editor/resources/editor_catalog.json')
print(len(c), ' '.join(f'{k}={v}' for k, v in sorted(Counter(e.category for e in c).items())))
" 2>/dev/null || echo "")
printf '  ..   %s\n' "${entries:-could not load the catalog}"
[ -n "$entries" ] || status=1

# An entry nobody can place is worse than no entry, so every raw value the
# translation can produce has to land on exactly one of them.
check "every translatable value resolves to one entry" "$python" -c "
import sys
from ec7edit_core.catalog import load_catalog
from ec7edit_core.xlat import read_xlat
catalog = load_catalog('$editor/resources/editor_catalog.json')
xlat = read_xlat('$repo/wadsrc/static/xlat/corridor7.txt')
missing = [v for v in xlat.thing_values() if catalog.for_value(1, v) is None]
missing += [('tile', v) for v in xlat.tiles if catalog.for_value(0, v) is None]
sys.exit(1 if missing else 0)"

check "no catalog entry carries image data" \
	sh -c "! grep -qE 'data:image|iVBOR' '$editor/resources/editor_catalog.json'"

printf '\nThe unresolved joins are reported, not hidden\n'
"$python" "$editor/scripts/generate_catalog.py" report | sed 's/^/  ..   /'

printf '\nOne decoder, not two\n'
if "$python" "$editor/scripts/build_c7assets.py" verify >/dev/null 2>&1; then
	printf '  ok   tools/c7assets.py matches the modules it is built from\n'
else
	printf '  FAIL tools/c7assets.py is stale; run build_c7assets.py write\n'
	status=1
fi
check "the built tool is valid Python" "$python" -m py_compile "$repo/tools/c7assets.py"
check "it still needs only the standard library" sh -c "
	! grep -nE '^\s*(import|from) +(PIL|numpy|requests|PySide|Qt)' '$repo/tools/c7assets.py'"
check "it is marked as generated" \
	grep -q "GENERATED FILE" "$repo/tools/c7assets.py"

# Two builds of the same sources must be the same bytes, or "rebuild and diff"
# is not a check.
work=$(mktemp -d /tmp/ec7edit-e2.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
cp "$repo/tools/c7assets.py" "$work/first"
"$python" "$editor/scripts/build_c7assets.py" write >/dev/null 2>&1
check "rebuilding is byte-for-byte reproducible" cmp -s "$work/first" "$repo/tools/c7assets.py"

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E2 decoders and catalog intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
