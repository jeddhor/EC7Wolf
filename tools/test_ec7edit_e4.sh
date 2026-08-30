#!/bin/sh

# Regression test: EC7Edit's Qt shell holds.
#
# Milestone E4 of docs/corridor7-level-editor.md. Real widgets, real signals,
# real painting, on QT_QPA_PLATFORM=offscreen -- a GUI test that stubs the
# toolkit tests the stub, so nothing here is mocked.
#
# Data-free. Every project is synthetic and the palette runs with no artwork,
# which is also the state a first-time user is in before setup: an editor whose
# palette is empty until it finds a game is an editor nobody can start.
#
# Two checks are worth naming:
#
#   * the setup page does not run the engine binary until the user presses the
#     button. Executing a file somebody selected is a real action, and the test
#     proves it waits for a real decision;
#   * a background result that arrives after the document moved on is dropped.
#     Without that, scrolling a palette shows thumbnails from three selections
#     ago landing over the current one.
#
# Usage: test_ec7edit_e4.sh [PYTHON]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

[ -d "$editor/ec7edit_gui" ] || { printf 'SKIP: no editor/ec7edit_gui yet\n'; exit 0; }

# The reference runtime with Qt on it. editor/.venv is where "uv venv --python
# 3.12 editor/.venv && uv pip install PySide6" puts one.
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
if [ -z "$python" ]; then
	printf 'SKIP: no Python with PySide6.\n'
	printf '      uv venv --python 3.12 %s/.venv && uv pip install --python %s/.venv/bin/python PySide6\n' \
		"$editor" "$editor"
	exit 0
fi

status=0
export PYTHONPATH="$editor"
export QT_QPA_PLATFORM=offscreen
# Qt refuses a non-UTF-8 locale and switches anyway, noisily; choose one.
export LC_ALL=C.UTF-8

version=$("$python" -c 'import sys;print("%d.%d.%d" % sys.version_info[:3])')
qt=$("$python" -c 'import PySide6;print(PySide6.__version__)')
printf 'Runtime\n'
printf '  ..   Python %s, PySide6 %s, offscreen platform\n' "$version" "$qt"
case "$version" in
	3.12.*) printf '  ok   the reference runtime is CPython 3.12\n' ;;
	*) printf '  ..   not the 3.12 reference; the shell is being tested on %s\n' "$version" ;;
esac

printf '\nThe core stays independent of the GUI\n'
if grep -rn "^[[:space:]]*\(import\|from\)[[:space:]]\+ec7edit_gui" "$editor/ec7edit_core" \
	>/dev/null 2>&1; then
	printf '  FAIL ec7edit_core imports ec7edit_gui\n'
	status=1
else
	printf '  ok   ec7edit_core does not import ec7edit_gui\n'
fi
if "$python" -c "
import sys
sys.modules['PySide6'] = None
import ec7edit_core.cli, ec7edit_core.project, ec7edit_core.discovery
" >/dev/null 2>&1; then
	printf '  ok   the core imports with Qt unavailable\n'
else
	printf '  FAIL the core needs Qt to import\n'
	status=1
fi

printf '\nOffscreen GUI tests\n'
suite="$editor/tests/gui/test_shell.py"
if [ ! -f "$suite" ]; then
	printf '  FAIL the GUI suite is missing\n'
	status=1
elif output=$("$python" "$suite" 2>&1); then
	printf '  ok   %s\n' "$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]* in [0-9.]*s' | head -1)"
else
	printf '  FAIL the GUI suite did not pass\n'
	printf '%s\n' "$output" | grep -vE "propagateSizeHints|QDBusError|does not support" \
		| tail -30 | sed 's/^/    /'
	status=1
fi

printf '\nThe application starts and stops\n'
# Constructing the window is where a missing resource or a bad signal
# connection shows up, and it is not covered by testing the pieces.
if "$python" - <<'PYEOF' >/dev/null 2>&1
import sys
from ec7edit_gui.application import build_application
from ec7edit_gui.main_window import MainWindow
from ec7edit_gui.settings import Settings
from PySide6.QtCore import QSettings
import tempfile, pathlib

application = build_application([])
settings = Settings(QSettings(str(pathlib.Path(tempfile.mkdtemp()) / "s.ini"),
                              QSettings.IniFormat))
window = MainWindow(settings)
window.show()
application.processEvents()
window.pool.cancel_all()
window.pool.wait(2000)
window.close()
PYEOF
then
	printf '  ok   the window builds, shows and closes\n'
else
	printf '  FAIL the window did not start\n'
	status=1
fi

printf '\nNothing commercial in the tree\n'
# Reading the user's own files is the whole point, so the check is not about
# filenames. What must not exist is retail content *in the repository*, or a
# cache that writes decoded artwork to disk where it would outlive the session.
if git -C "$repo" ls-files editor | grep -qiE '\.(co7|exe|wad|c7map)$'; then
	printf '  FAIL a game data file is committed under editor/\n'
	status=1
else
	printf '  ok   no game data file is committed under editor/\n'
fi
if grep -rnE 'b"[A-Za-z0-9+/=]{200,}"|base64\.b64decode' "$editor/ec7edit_gui" \
	>/dev/null 2>&1; then
	printf '  FAIL the GUI carries a large embedded blob\n'
	status=1
else
	printf '  ok   the GUI embeds no binary blob\n'
fi
# Decoded artwork lives in memory for the session and nowhere else. A disk
# cache of retail pixels would be a copy of the game, with the licensing that
# implies, so the thumbnail path must never write one.
if grep -nE '\.save\(|write_bytes|open\([^)]*[\"'"'"']w' \
	"$editor/ec7edit_gui/thumbnails.py" >/dev/null 2>&1; then
	printf '  FAIL the thumbnail path writes to disk\n'
	status=1
else
	printf '  ok   decoded artwork is never written to disk\n'
fi

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E4 shell intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
