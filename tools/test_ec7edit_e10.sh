#!/bin/sh

# Regression test: the editor's Snapshot is an exact engine frame of the map it
# says it is, and never a picture of nothing.
#
# Milestone E10 of docs/corridor7-level-editor.md. The Snapshot exists because
# the alternative -- a second renderer written in Python -- would be a second
# authority on what Corridor 7 looks like, and the moment the two disagreed the
# editor would be lying. So the picture comes from the engine.
#
# What can go wrong, and is therefore asserted:
#
#   1. A camera in a wall or off the map. The engine draws it without
#      complaining and the editor caches the result, so it is refused twice --
#      by the editor before launch, and by the engine against the map that
#      actually loaded.
#   2. A blank frame. This project has already shipped a gate that passed while
#      comparing a black frame nobody had looked at; a snapshot that is one
#      flat color is a failure however cleanly the process exited.
#   3. A shot that is not reproducible. It is anchored to a simulation tic
#      rather than a frame, because how many frames pass in a tic depends on
#      how busy the machine is -- so the same request must give the same bytes.
#   4. Options misread as filenames. E10 allows zero "could not stat" lines,
#      and every option the editor uses is exercised here at once.
#
# Needs the archive and a display. Skipped without them.
#
# Usage: test_ec7edit_e10.sh BUILD_DIR DATA_DIR   (both absolute)

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
[ -f "$editor/ec7edit_core/snapshot.py" ] || { printf 'SKIP: no snapshot yet\n'; exit 0; }
grep -q "capture-snapshot" "$repo/src/r_capture.cpp" 2>/dev/null || {
	printf 'SKIP: this build has no snapshot capture\n'; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data\n'; exit 0; }

status=0
work=$(mktemp -d /tmp/ec7wolf-e10.XXXXXX)
cleanup() { [ "$status" -eq 0 ] && rm -rf "$work" || printf '  logs kept in %s\n' "$work"; }
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

say() { printf '  %-5s %s\n' "$1" "$2"; }

lab="$work/lab"
mkdir -p "$lab"
# The build's OWN pk3 -- the engine resolves ec7wolf.pk3 from the working
# directory first, and a stale one there is a silent false pass.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done

source_hash=$(sha256sum "$data_dir/MAPTEMP.CO7" | cut -d' ' -f1)

# The editor's own arguments, so this tests what the editor actually sends
# rather than a hand-written copy of it that can drift.
args=$(cd "$editor" && OUT="$lab/snap.png" python3 - <<'PY'
import os, sys
sys.path.insert(0, ".")
from ec7edit_core.snapshot import Camera, snapshot_arguments
print(" ".join(snapshot_arguments(Camera(15, 31, 90), os.environ["OUT"])))
PY
)

shoot() { # $1 label  $2.. extra args
	label=$1
	shift
	set +e
	(
		cd "$lab"
		timeout 120s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 800x600x24' ./ec7wolf \
			--data CO7 --nowait --tedlevel MAP01 --skill 2 \
			--config "$work/$label.cfg" --savedir "$work/$label.saves" \
			--capture-rngseed 1 "$@"
	) >"$work/$label.log" 2>&1
	set -e
}

# --- 1. a real snapshot ---------------------------------------------------
shoot good $args
result=$(grep "^Capture: snapshot " "$work/good.log" | head -1 || true)
if [ -n "$result" ] && [ -s "$lab/snap.png" ]; then
	say "ok" "the engine drew and reported one: ${result#Capture: snapshot }"
else
	say "FAIL" "no snapshot was produced; see $work/good.log"
	status=1
fi

# The camera has to reach the result line, or the editor cannot tell which
# picture it is holding.
case $result in
	*"camera=15,31,90"*) say "ok" "the chosen tile and angle are in the result" ;;
	*) say "FAIL" "the result line does not carry the camera: $result"; status=1 ;;
esac

# --- 2. it must be a world, not a blank frame ----------------------------
if (cd "$editor" && SNAP="$lab/snap.png" python3 - <<'PY'
import os, sys
sys.path.insert(0, ".")
from ec7edit_core.snapshot import looks_like_a_world
raise SystemExit(0 if looks_like_a_world(os.environ["SNAP"]) else 1)
PY
); then
	say "ok" "the PNG holds a rendered world rather than a flat frame"
else
	say "FAIL" "the snapshot is blank -- the failure this check exists for"
	status=1
fi

# --- 3. the same request gives the same bytes ----------------------------
mv "$lab/snap.png" "$lab/first.png"
shoot again $args
if cmp -s "$lab/first.png" "$lab/snap.png"; then
	say "ok" "the same camera and tic give byte-identical output"
else
	say "FAIL" "two identical requests produced different pictures"
	status=1
fi

# A different camera must give a different picture, or the first check would
# pass on a renderer that ignores the camera entirely.
turned=$(printf '%s' "$args" | sed 's/--capture-warp 15 31 90/--capture-warp 15 31 270/')
mv "$lab/snap.png" "$lab/north.png"
shoot turned $turned
if cmp -s "$lab/north.png" "$lab/snap.png"; then
	say "FAIL" "turning the camera changed nothing; the camera is not reaching the view"
	status=1
else
	say "ok" "turning the camera changes the picture"
fi

# --- 4. cameras that cannot produce a picture ----------------------------
for bad in "999 999 0:outside this" "0 0 0:inside a wall" "banana 31 90:finite numbers"; do
	camera=${bad%%:*}
	want=${bad##*:}
	# NOT `label`: shoot() assigns that itself, so reusing the name here made
	# the second reference point at a file nothing had written.
	tag="bad$(printf '%s' "$camera" | tr ' .' '__')"
	rm -f "$lab/bad.png"
	# shellcheck disable=SC2086
	shoot "$tag" --vid-renderer software --res 640 400 --no-upscale \
		--capture-warp $camera --capture-snapshot "$lab/bad.png" 20
	if grep -q "$want" "$work/$tag.log"; then
		say "ok" "camera '$camera' refused: $want"
	else
		say "FAIL" "camera '$camera' was not refused; see $work/$tag.log"
		status=1
	fi
done

# --- 5. nothing was misread as a resource path ---------------------------
misparsed=$(cat "$work"/*.log | grep -c "Could not stat" || true)
if [ "$misparsed" -eq 0 ]; then
	say "ok" "no capture or render option was misread as a resource path"
else
	say "FAIL" "$misparsed option(s) reached the wad loader:"
	grep -h "Could not stat" "$work"/*.log | sort -u | sed 's/^/         /'
	status=1
fi

# --- 6. the editor keys its cache on everything that matters -------------
if (cd "$editor" && python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from ec7edit_core.snapshot import Camera, snapshot_key

base = dict(engine=__file__, pk3=__file__, data_fingerprint="fp",
            export_digest="abc", camera=Camera(1, 2, 0))
first = snapshot_key(**base)
for name, value in (("export_digest", "def"), ("data_fingerprint", "other"),
                    ("camera", Camera(1, 2, 90))):
    changed = dict(base); changed[name] = value
    if snapshot_key(**changed) == first:
        print(f"the cache key ignores {name}")
        raise SystemExit(1)
PY
); then
	say "ok" "the cache key changes with the map, the data and the camera"
else
	say "FAIL" "the cache key ignores something that changes the picture"
	status=1
fi

# --- 7. the retail data is untouched -------------------------------------
if [ "$source_hash" = "$(sha256sum "$data_dir/MAPTEMP.CO7" | cut -d' ' -f1)" ]; then
	say "ok" "the source archive is byte-for-byte unchanged"
else
	say "FAIL" "THE SOURCE ARCHIVE WAS MODIFIED"
	status=1
fi

[ "$status" -eq 0 ] && printf 'PASS: E10 exact snapshot\n'
exit "$status"
