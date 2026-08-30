#!/bin/sh

# Regression test: EC7Edit's first playable slice, end to end.
#
# Milestone E5 of docs/corridor7-level-editor.md, and its exit gate verbatim:
# import owned MAP01 read-only, paint a wall chosen from its thumbnail, place
# and configure an enemy, undo and redo both, save and reopen the project,
# export a one-map WAD, and make EC7Wolf enter that edited override -- with the
# source archive's hash unchanged.
#
# The editing half runs offscreen through the real window; the engine half runs
# under xvfb. The evidence that the edit reached the game is the player start:
# the workflow moves it, and the engine must spawn on the new tile and not the
# old one. An override that silently did nothing would land on the stock tile
# and fail, which is the whole point of choosing that as the assertion.
#
# Usage: test_ec7edit_slice.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no MAPTEMP.CO7 in %s\n' "$data_dir"; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }

find_python() {
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
python=$(find_python)
[ -n "$python" ] || { printf 'SKIP: no Python with PySide6\n'; exit 0; }
command -v xvfb-run >/dev/null 2>&1 || { printf 'SKIP: no xvfb-run\n'; exit 0; }

work=$(mktemp -d /tmp/ec7edit-slice.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
status=0

before=$(python3 -c "
import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" \
	"$data_dir/MAPTEMP.CO7")

printf 'The editing workflow\n'
if PYTHONPATH="$editor" QT_QPA_PLATFORM=offscreen LC_ALL=C.UTF-8 \
	"$python" "$editor/tests/gui/slice_workflow.py" "$data_dir" "$work" \
	>"$work/workflow.log" 2>&1; then
	grep -E '^\s+(ok|\.\.|FAIL)' "$work/workflow.log" | sed 's/^ */  /'
else
	grep -E '^\s+(ok|\.\.|FAIL)' "$work/workflow.log" | sed 's/^ */  /'
	printf '  FAIL the workflow did not complete\n'
	tail -20 "$work/workflow.log" | sed 's/^/    /'
	exit 1
fi

marker=$("$python" -c "
import json;print(json.load(open('$work/expected.json'))['marker'])")
new_start=$("$python" -c "
import json;print(*json.load(open('$work/expected.json'))['new_start'])")
old_start=$("$python" -c "
import json;print(*json.load(open('$work/expected.json'))['old_start'])")

printf '\nEC7Wolf enters the edited map\n'
# The build's own pk3 beside the binary: the engine resolves ec7wolf.pk3 from
# the working directory first, so running with the data directory as cwd would
# silently test whatever pk3 was installed there last.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$work/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && ln -s "$f" "$work/" || true
done

(
	cd "$work"
	timeout 300s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
		xvfb-run -a -s "-screen 0 320x200x24" ./ec7wolf \
		--data CO7 --no-upscale --nowait --vid-renderer software --res 320 200 \
		--config "$work/cfg" --savedir "$work/sv" \
		--tedlevel "$marker" --skill 2 --capture-rngseed 12345 \
		--capture-players "$work/spawn.txt" --capture-maxtics 4 \
		--file "$work/slice.wad"
) >"$work/engine.log" 2>&1 || true

if [ ! -s "$work/spawn.txt" ]; then
	printf '  FAIL the engine produced no player trace; see %s/engine.log\n' "$work"
	tail -15 "$work/engine.log" | sed 's/^/    /'
	exit 1
fi

spawn=$(grep -v '^#' "$work/spawn.txt" | head -1 | cut -d' ' -f3,4)
printf '  ..   stock MAP01 starts at %s\n' "$old_start"
printf '  ..   the edit moved it to %s\n' "$new_start"
printf '  ..   the engine spawned at %s\n' "$spawn"

if [ "$spawn" = "$new_start" ]; then
	printf '  ok   the engine entered the edited map\n'
else
	printf '  FAIL expected %s, got %s\n' "$new_start" "$spawn"
	status=1
fi
if [ "$spawn" = "$old_start" ]; then
	printf '  FAIL the override did nothing; this is the stock map\n'
	status=1
else
	printf '  ok   and not the stock one\n'
fi

tics=$(grep -vc '^#' "$work/spawn.txt" || true)
if [ "${tics:-0}" -ge 2 ]; then
	printf '  ok   the level ran (%s traced tics)\n' "$tics"
else
	printf '  FAIL only %s tics\n' "${tics:-0}"
	status=1
fi

printf '\nThe archive was only read\n'
after=$(python3 -c "
import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" \
	"$data_dir/MAPTEMP.CO7")
if [ "$before" = "$after" ]; then
	printf '  ok   MAPTEMP.CO7 sha256 unchanged\n'
else
	printf '  FAIL the archive changed during the run\n'
	status=1
fi

if [ "$status" -eq 0 ]; then
	printf '\nPASS: edit, save, export, play.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
