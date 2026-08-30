#!/bin/sh

# Regression test: EC7Edit's production codec holds.
#
# Milestone E1 of docs/corridor7-level-editor.md: the Qt-free archive, RLEW,
# PLANES and WAD codecs, the safe-output rules, and the `ec7edit` CLI. What
# this gate cannot prove -- that the engine loads what the exporter writes --
# is the separate owned-data gate test_ec7edit_override.sh.
#
# Data-free on purpose. Every input is generated, the plane words come from a
# band the retail data never uses, and nothing here needs Corridor 7, a build,
# or a display, so it belongs in the hosted CI lane.
#
# The suite runs under the reference runtime, CPython 3.12, when one can be
# found. The editor's floor is 3.10 and the development machine has 3.14, so
# without this the tested interpreter would be whatever happened to be on PATH.
#
# Usage: test_ec7edit_e1.sh [PYTHON]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

[ -d "$editor/ec7edit_core" ] || { printf 'SKIP: no editor/ec7edit_core yet\n'; exit 0; }

# The reference interpreter, in order of preference: one named on the command
# line, a system python3.12, a uv-managed 3.12, then whatever python3 is.
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

version=$("$python" -c 'import sys;print("%d.%d.%d" % sys.version_info[:3])')
reference=$("$python" -c 'import sys;print("yes" if sys.version_info[:2]==(3,12) else "no")')

status=0
check() {
	message=$1
	shift
	if "$@" >/dev/null 2>&1; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

work=$(mktemp -d /tmp/ec7edit-e1.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

export PYTHONPATH="$editor"

printf 'Runtime\n'
printf '  ..   %s (%s)\n' "$version" "$python"
if [ "$reference" = yes ]; then
	printf '  ok   the reference runtime is CPython 3.12\n'
else
	printf '  ..   not 3.12; install one with "uv python install 3.12" to test the reference\n'
fi
check "the package imports without Qt on the path" \
	"$python" -c 'import ec7edit_core, ec7edit_core.cli'
check "the language floor is met" \
	"$python" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)'

printf '\nThe core stays Qt-free\n'
# The GUI depends on the core and never the other way round. A stray import
# would make every one of these tests need a display.
check "no module imports Qt or PySide" \
	sh -c '! grep -rniE "^[[:space:]]*(import|from)[[:space:]]+(PySide|PyQt|shiboken)" "'"$editor"'/ec7edit_core"'
check "no module imports anything outside the repository" \
	sh -c '! grep -rn "tools/python" "'"$editor"'/ec7edit_core"'

printf '\nUnit tests\n'
for suite in test_rlew test_archive test_wad test_paths test_cli test_fixtures; do
	file="$editor/tests/unit/$suite.py"
	[ -f "$file" ] || { printf '  FAIL %s is missing\n' "$suite"; status=1; continue; }
	if output=$("$python" "$file" 2>&1); then
		printf '  ok   %-14s %s\n' "$suite" "$(printf '%s' "$output" | grep -o 'Ran [0-9]* test[s]*' | head -1)"
	else
		printf '  FAIL %s\n' "$suite"
		printf '%s\n' "$output" | tail -20 | sed 's/^/    /'
		status=1
	fi
done

printf '\nThe CLI, end to end on generated input\n'
"$python" "$editor/scripts/make_fixtures.py" write "$work/fix" >/dev/null 2>&1
archive="$work/fix/archive/three-maps.c7map"

check "inspect lists the maps" "$python" -m ec7edit_core inspect "$archive"
check "inspect emits parseable JSON" \
	sh -c '"'"$python"'" -m ec7edit_core inspect "'"$archive"'" --json | "'"$python"'" -m json.tool'
check "validate accepts a good archive" "$python" -m ec7edit_core validate "$archive"
check "validate rejects an empty one" \
	sh -c '! "'"$python"'" -m ec7edit_core validate "'"$work"'/fix/malformed/empty.bin"'
check "every malformed fixture is refused" sh -c '
	for f in "'"$work"'"/fix/malformed/*; do
		"'"$python"'" -m ec7edit_core validate "$f" >/dev/null 2>&1 && exit 1
	done
	exit 0'

"$python" -m ec7edit_core convert-to-preview-wad "$archive" --all \
	--output "$work/preview.wad" >/dev/null 2>&1 || {
	printf '  FAIL the preview export did not run\n'
	status=1
}
check "the preview WAD reads back as three map pairs" \
	sh -c '"'"$python"'" -c "
import sys
from ec7edit_core.wad import read_preview_wad
pairs = read_preview_wad(open(sys.argv[1], \"rb\").read())
sys.exit(0 if [m for m, _ in pairs] == [\"MAP01\", \"MAP02\", \"MAP03\"] else 1)
" "'"$work"'/preview.wad"'

# Two exports of the same input must be the same bytes, or an export digest is
# not evidence of anything.
"$python" -m ec7edit_core convert-to-preview-wad "$archive" --all \
	--output "$work/preview2.wad" >/dev/null 2>&1
check "two exports are byte-identical" cmp -s "$work/preview.wad" "$work/preview2.wad"

printf '\nThe source is never written\n'
sourcedir=$(dirname "$archive")
check "exporting onto the source is refused" \
	sh -c '! "'"$python"'" -m ec7edit_core convert-to-preview-wad "'"$archive"'" \
		--map 1 --output "'"$archive"'"'
check "an explicitly protected directory is refused" \
	sh -c '! "'"$python"'" -m ec7edit_core convert-to-preview-wad "'"$archive"'" \
		--map 1 --protect "'"$sourcedir"'" --output "'"$sourcedir"'/beside.wad"'
# A directory holding .CO7 files is game data, and is protected without being
# asked for: an export landing beside MAPTEMP.CO7 is one typo from being it.
mkdir -p "$work/gamedata"
cp "$archive" "$work/gamedata/MAPTEMP.CO7"
check "a game-data directory is protected automatically" \
	sh -c '! "'"$python"'" -m ec7edit_core convert-to-preview-wad \
		"'"$work"'/gamedata/MAPTEMP.CO7" --map 1 --output "'"$work"'/gamedata/beside.wad"'
check "no output was left in either directory" \
	sh -c '[ ! -e "'"$sourcedir"'/beside.wad" ] && [ ! -e "'"$work"'/gamedata/beside.wad" ]'

printf '\nThe lab tools run from a clean clone\n'
# Both imported a module that was never in the repository. E1 moved them onto
# the production codec; a reintroduced sys.path escape would break a fresh
# checkout without breaking anything here, so it is checked directly.
for tool in make_corridor7_ai_lab make_corridor7_mp_lab; do
	check "$tool imports only in-repository code" \
		sh -c '! grep -q "tools/python" "'"$here"'/'"$tool"'.py"'
	check "$tool compiles" "$python" -m py_compile "$here/$tool.py"
done

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E1 codec intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
