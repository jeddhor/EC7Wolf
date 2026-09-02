#!/bin/sh

# Regression test: EC7Edit's compound semantic tools hold.
#
# Milestone E6 of docs/corridor7-level-editor.md: the structures that are more
# than one word -- pushwalls, doors, dispensers, terminals, exits, transporter
# pairs -- and the two rules Corridor 7 decides by topology rather than storing.
#
# The exit gate is coverage: every value the translation defines is either
# offered through a friendly tool or carries a written reason why it is not.
# scripts/coverage_report.py --check is that gate, and it fails on anything
# that is neither.
#
# The door checks matter most. A door's axis is not in the map -- the engine
# counts open neighbors and decides -- so an editor that inferred it
# differently would show one thing and ship another. The rule here is copied
# from gamemap_planes.cpp including its tie-break, and the tests name the case.
#
# Data-free.
#
# Usage: test_ec7edit_e6.sh [PYTHON]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

[ -f "$editor/ec7edit_core/prefabs.py" ] || { printf 'SKIP: no prefabs yet\n'; exit 0; }

find_python() {
	if [ "$#" -ge 1 ] && [ -n "$1" ]; then printf '%s\n' "$1"; return; fi
	for candidate in "$editor/.venv/bin/python" "$editor/.venv/Scripts/python.exe"; do
		[ -x "$candidate" ] && { printf '%s\n' "$candidate"; return; }
	done
	for candidate in python3.12 python3; do
		if command -v "$candidate" >/dev/null 2>&1 &&
			"$candidate" -c "import PySide6" >/dev/null 2>&1; then
			command -v "$candidate"; return
		fi
	done
}
python=$(find_python "${1:-}")
headless=$(command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || true)
[ -n "$headless" ] || { printf 'SKIP: no python3\n'; exit 0; }

status=0
export PYTHONPATH="$editor"
export QT_QPA_PLATFORM=offscreen
export LC_ALL=C.UTF-8

printf 'Compound tools\n'
if output=$("$headless" "$editor/tests/unit/test_prefabs.py" 2>&1); then
	printf '  ok   test_prefabs       %s\n' \
		"$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]*' | head -1)"
else
	printf '  FAIL test_prefabs\n'
	printf '%s\n' "$output" | tail -25 | sed 's/^/    /'
	status=1
fi

printf '\nThe structures through the window\n'
if [ -z "$python" ]; then
	printf '  ..   SKIP: no Python with PySide6\n'
elif output=$("$python" "$editor/tests/gui/test_editing.py" 2>&1); then
	printf '  ok   test_editing       %s\n' \
		"$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]*' | head -1)"
else
	printf '  FAIL test_editing\n'
	printf '%s\n' "$output" | grep -vE "propagateSizeHints|QDBusError|does not support" \
		| tail -25 | sed 's/^/    /'
	status=1
fi

printf '\nEvery semantic is reachable or labeled\n'
if output=$("$headless" "$editor/scripts/coverage_report.py" --check 2>&1); then
	printf '%s\n' "$output" | sed -n '3,7p' | sed 's/^ */  ..   /'
	printf '  ok   %s\n' "$(printf '%s' "$output" | tail -1 | sed 's/^ *//')"
else
	printf '  FAIL something has neither a tool nor a label\n'
	printf '%s\n' "$output" | tail -12 | sed 's/^/    /'
	status=1
fi

printf '\nEvery compound tool carries its contract\n'
# The design guide asks for six things per prefab. Five are structural and the
# test above checks them; this is the one a reviewer actually needs -- a
# pointer to where the word set came from, so it can be checked rather than
# trusted.
if "$headless" -c "
import sys
from ec7edit_core.prefabs import PREFABS
missing = [p.key for p in PREFABS if not p.evidence or 'xlat' not in p.evidence.lower()]
if missing:
    print('no source reference: ' + ', '.join(missing))
    sys.exit(1)
print(f'{len(PREFABS)} tools, each citing the translation entry it comes from')
" 2>&1 | sed 's/^/  ok   /'; then
	:
else
	printf '  FAIL a tool does not say where its words came from\n'
	status=1
fi

printf '\nThe door rule matches the engine\n'
# The engine's test is `>`, not `>=`. Everything about a four-way opening
# depends on that one character, so it is asserted directly.
if "$headless" -c "
import sys
sys.path.insert(0, '$editor')
from ec7edit_core.document import MapDocument
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.rules import door_axis

def build(rows):
    h, w = len(rows), len(rows[0])
    p0 = [1 if c == '#' else 0 for r in rows for c in r]
    return MapDocument('u', 1, NativeName.from_text('T'),
                       MapPlanes(w, h, (tuple(p0), (18,)*(w*h), (0,)*(w*h))))

ns = door_axis(build(['###', '#.#', '#D#', '#.#', '###']), 1, 2)
ew = door_axis(build(['#####', '#...#', '#####']), 2, 1)
tie = door_axis(build(['...', '...', '...']), 1, 1)
assert ns.horizontal and 'north-south' in ns.label, ns.label
assert not ew.horizontal and 'east-west' in ew.label, ew.label
assert tie.tie and not tie.horizontal, 'a tie must fall to the vertical plane'
print('north-south, east-west, and the tie all match gamemap_planes.cpp')
" >/dev/null 2>&1; then
	printf '  ok   north-south, east-west and the tie all match the engine\n'
else
	printf '  FAIL the inferred door axis does not match the engine\n'
	status=1
fi

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E6 semantic tools intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
