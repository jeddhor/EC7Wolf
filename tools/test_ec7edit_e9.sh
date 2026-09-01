#!/bin/sh

# Regression test: the editor can launch the real engine into the map it just
# exported, and can tell whether that actually happened.
#
# Milestone E9 of docs/corridor7-level-editor.md. The reason this needs a
# protocol at all is one specific failure: a preview WAD the engine cannot read
# is NOT fatal. AddFile prints "Could not stat" and returns (src/w_wad.cpp:233),
# so the engine loads the SHIPPED map of that number, plays it happily, and
# exits 0. Every outside signal -- exit code, a window appearing, a screenshot
# -- says the playtest worked. It tested the wrong map.
#
# So the assertions here are on what the engine says about itself:
#
#   1. --editor-capabilities answers with no game data and no display, and
#      names the protocol version the editor is built against.
#   2. A good launch emits the whole sequence, and the map-entry event names
#      the marker that was asked for.
#   3. A launch whose preview WAD is missing emits loaded=no -- and still exits
#      0, which is the whole point.
#   4. A map with no player start, the commonest failure of an exported map,
#      emits a fatal event carrying the engine's own words.
#   5. No editor or harness option, nor any of their values, is misread as a
#      resource path. "Could not stat --vid-renderer" was printed by every
#      run that used it; the count here is zero, and E10 depends on it.
#   6. The session nonce is not echoed anywhere except on protocol lines. If
#      it were, a gate that greps for the nonce would be satisfied by the
#      engine complaining about it.
#
# Needs the archive and a display. Skipped without them.
#
# Usage: test_ec7edit_e9.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
editor="$repo/editor"

command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }
[ -f "$editor/ec7edit_core/engine_runner.py" ] || { printf 'SKIP: no editor\n'; exit 0; }
grep -q "editor-capabilities" "$repo/src/c7_editorlink.cpp" 2>/dev/null || {
	printf 'SKIP: no editor link in this build\n'; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-e9.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

status=0
say() { printf '  %-5s %s\n' "$1" "$2"; }

# --- 1. the data-free probe ----------------------------------------------
# Run from an empty directory on purpose: it must not need game data, a pk3,
# a config or a display.
if (cd "$work" && timeout 30s "$build_dir/ec7wolf" --editor-capabilities) \
	>"$work/caps.txt" 2>&1; then
	want=$(grep -c '^editor-protocol=1$' "$work/caps.txt" || true)
	if [ "$want" -eq 1 ] && grep -q '^events=.*map-entry' "$work/caps.txt"; then
		say "ok" "--editor-capabilities answers with no data present"
	else
		say "FAIL" "the capability probe did not name the protocol and its events"
		status=1
	fi
else
	say "FAIL" "--editor-capabilities did not exit cleanly: $(head -2 "$work/caps.txt")"
	status=1
fi

# The editor and the engine must agree on the number.
editor_version=$(cd "$editor" && python3 -c \
	'import sys; sys.path.insert(0, "."); from ec7edit_core.engine_runner import PROTOCOL_VERSION; print(PROTOCOL_VERSION)')
if grep -q "^editor-protocol=$editor_version\$" "$work/caps.txt"; then
	say "ok" "the editor and the engine agree on protocol $editor_version"
else
	say "FAIL" "the editor speaks protocol $editor_version and the engine does not"
	status=1
fi

# --- the lab ---------------------------------------------------------------
lab="$work/lab"
mkdir -p "$lab"
# The build's OWN pk3: the engine resolves ec7wolf.pk3 from the working
# directory first, so running from the data directory silently tests whichever
# pk3 was installed there last. That has produced false passes before.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done
[ -f "$lab/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data\n'; exit 0; }

# Two preview WADs built by the editor's own exporter: one playable, one with
# no player start.
(cd "$editor" && LAB="$lab" python3 - <<'PY'
import os, sys
sys.path.insert(0, ".")
from pathlib import Path
from ec7edit_core.document import MapDocument
from ec7edit_core.wad import build_preview_wad

lab = Path(os.environ["LAB"])
good = MapDocument.new_room(slot=1, name="E9 LAB")
Path(lab / "good.wad").write_bytes(build_preview_wad([("MAP01", good.to_record())]))
bad = MapDocument.new_room(slot=1, name="E9 NO START", with_start=False)
Path(lab / "nostart.wad").write_bytes(build_preview_wad([("MAP01", bad.to_record())]))
PY
) || { say "FAIL" "the editor could not build a preview WAD"; exit 1; }

launch() { # $1 session  $2 preview file  -> writes $work/$1.log, echoes exit code
	set +e
	(
		cd "$lab"
		timeout 90s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 640x400x24' ./ec7wolf \
			--data CO7 --no-upscale --nowait --res 320 200 \
			--vid-renderer software --config "$work/$1.cfg" \
			--savedir "$work/$1.saves" \
			--editor-protocol 1 --editor-session "$1" \
			--tedlevel MAP01 --skill 2 --capture-maxtics 25 \
			--file "$2"
	) >"$work/$1.log" 2>&1
	echo $?
	set -e
}

event() { # $1 session  $2 event name
	grep "^EC7EDIT $1 $2 " "$work/$1.log" | head -1
}

# --- 2. a good launch reaches the map ------------------------------------
code=$(launch e9good good.wad)
if [ -n "$(event e9good map-entry)" ] &&
   printf '%s' "$(event e9good preview-load)" | grep -q 'loaded=yes' &&
   printf '%s' "$(grep "^EC7EDIT e9good preview-load .*good.wad" "$work/e9good.log")" | grep -q 'loaded=yes'
then
	marker=$(event e9good map-entry | sed -n 's/.*marker=\([A-Z0-9]*\).*/\1/p')
	if [ "$marker" = "MAP01" ]; then
		say "ok" "a good launch loaded the editor's WAD and entered $marker (exit $code)"
	else
		say "FAIL" "it entered $marker, not the MAP01 it was asked for"
		status=1
	fi
else
	say "FAIL" "a good launch did not report loading the map; see $work/e9good.log"
	status=1
fi

if [ -n "$(event e9good session-result)" ]; then
	say "ok" "the session closed with a result event"
else
	say "FAIL" "the stream ended with no closing event -- indistinguishable from a hang"
	status=1
fi

# --- 3. the failure that looks like success ------------------------------
code=$(launch e9missing does-not-exist.wad)
if printf '%s' "$(grep "^EC7EDIT e9missing preview-load .*does-not-exist" "$work/e9missing.log")" |
	grep -q 'loaded=no'
then
	say "ok" "a missing preview WAD is reported as loaded=no (engine still exited $code)"
else
	say "FAIL" "a missing preview WAD was not reported; this is the failure that looks like success"
	status=1
fi

# --- 4. the commonest failure of an exported map -------------------------
code=$(launch e9nostart nostart.wad)
if printf '%s' "$(event e9nostart fatal)" | grep -qi 'player'; then
	say "ok" "a map with no player start reports a fatal event (exit $code)"
else
	say "FAIL" "no fatal event for a startless map; the editor would show a blank failure"
	status=1
fi

# --- 5. nothing is misread as a resource path ----------------------------
misparsed=0
for session in e9good e9missing e9nostart; do
	# The missing preview WAD is a genuine "could not stat"; every other one is
	# an option or a value that leaked into the wad list.
	n=$(grep "Could not stat" "$work/$session.log" | grep -cv "does-not-exist.wad" || true)
	misparsed=$((misparsed + n))
done
if [ "$misparsed" -eq 0 ]; then
	say "ok" "no launch option or value was misread as a resource path"
else
	say "FAIL" "$misparsed option(s) reached the wad loader:"
	grep -h "Could not stat" "$work"/e9*.log | grep -v "does-not-exist.wad" | sort -u | sed 's/^/         /'
	status=1
fi

# --- 6. the nonce appears only on protocol lines -------------------------
stray=$(grep -h "e9good" "$work/e9good.log" | grep -cv "^EC7EDIT e9good " || true)
if [ "$stray" -eq 0 ]; then
	say "ok" "the session nonce is echoed only on protocol lines"
else
	say "FAIL" "the nonce appears on $stray non-protocol line(s); a nonce grep would self-satisfy"
	grep -h "e9good" "$work/e9good.log" | grep -v "^EC7EDIT e9good " | head -3 | sed 's/^/         /'
	status=1
fi

# --- 7. nothing of the player's was touched ------------------------------
if [ -d "$work/e9good.saves" ] || [ -f "$work/e9good.cfg" ]; then
	say "ok" "config and saves went to the session directory"
else
	say "..." "the engine wrote no config or saves this run"
fi

[ "$status" -eq 0 ] && printf 'PASS: E9 playtest launch and engine protocol\n'
exit "$status"
