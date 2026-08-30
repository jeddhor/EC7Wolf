#!/bin/sh

# Regression test: EC7Edit's editing tools hold.
#
# Milestone E5 of docs/corridor7-level-editor.md: brushes, shapes, fill,
# eraser, eyedropper, selection, the inspector, the basic validator, and the
# playtest launch plan. The end-to-end proof -- edit a real map and watch the
# engine load it -- is the owned-data gate test_ec7edit_slice.sh.
#
# Data-free: synthetic maps, offscreen Qt, no engine.
#
# Usage: test_ec7edit_e5.sh [PYTHON]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

[ -d "$editor/ec7edit_gui" ] || { printf 'SKIP: no editor/ec7edit_gui yet\n'; exit 0; }

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

run_suite() {
	interpreter=$1
	name=$2
	file="$3"
	[ -f "$file" ] || { printf '  FAIL %s is missing\n' "$name"; status=1; return; }
	if output=$("$interpreter" "$file" 2>&1); then
		printf '  ok   %-18s %s\n' "$name" \
			"$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]*' | head -1)"
	else
		printf '  FAIL %s\n' "$name"
		printf '%s\n' "$output" | grep -vE "propagateSizeHints|QDBusError|does not support" \
			| tail -25 | sed 's/^/    /'
		status=1
	fi
}

printf 'Tool geometry, validation and the launch plan (no Qt)\n'
for suite in test_tools test_validation test_engine_runner; do
	run_suite "$headless" "$suite" "$editor/tests/unit/$suite.py"
done

printf '\nThe tools through the window\n'
if [ -z "$python" ]; then
	printf '  ..   SKIP: no Python with PySide6; the GUI half was not run\n'
else
	run_suite "$python" "test_editing" "$editor/tests/gui/test_editing.py"
fi

printf '\nEvery tool goes through a command\n'
# The rule that keeps undo honest: nothing writes to a document except through
# History.do. A tool that mutated planes directly would work and would be
# invisible to undo, which is the worst combination.
if grep -nE "\.planes\s*=|planes\[[0-9]\]\s*\[" "$editor/ec7edit_gui"/*.py >/dev/null 2>&1; then
	printf '  FAIL something in the GUI writes planes directly\n'
	grep -nE "\.planes\s*=|planes\[[0-9]\]\s*\[" "$editor/ec7edit_gui"/*.py | sed 's/^/    /'
	status=1
else
	printf '  ok   no GUI module writes a plane directly\n'
fi
if grep -q "history.do" "$editor/ec7edit_gui/main_window.py"; then
	printf '  ok   the window routes edits through the history\n'
else
	printf '  FAIL the window does not use the history\n'
	status=1
fi

printf '\nThe launch plan is a vector, not a shell string\n'
if grep -nE "shell=True|os\.system|subprocess\.(call|run|Popen)\([\"']" \
	"$editor/ec7edit_core/engine_runner.py" "$editor/ec7edit_gui/main_window.py" \
	>/dev/null 2>&1; then
	printf '  FAIL a command is built as a string somewhere\n'
	status=1
else
	printf '  ok   nothing builds a shell command line\n'
fi

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E5 editing tools intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
