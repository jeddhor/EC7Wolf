#!/bin/sh

# Regression test: an EC7Edit preview WAD overrides a base map in EC7Wolf.
#
# Milestone E1 of docs/corridor7-level-editor.md. This is the one claim the
# editor cannot make from unit tests: that the file it exports is a file the
# game actually loads in place of a stock map. Everything else -- the codec,
# the WAD writer, the readback -- is only ever a prediction about this.
#
# The evidence is deliberately not "it did not crash". Three short runs:
#
#   1. stock MAP01,
#   2. stock MAP51,
#   3. MAP01 with a preview WAD holding MAP51's planes in the MAP01 slot.
#
# Run 3 must put the player where run 2 does and not where run 1 does. That is
# positive entry evidence (the level was reached and the pawn spawned) and
# positive content evidence (the geometry that spawned it came from the WAD),
# and neither can be satisfied by an override that silently did nothing.
#
# MAP51 is a network map: real retail geometry with real textures, so nothing
# here depends on the editor understanding what a wall means yet. It also
# starts the player somewhere MAP01 does not, which is the whole point.
#
# The archive is only ever read. Its digest is compared before and after.
#
# Usage: test_ec7edit_override.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)

if [ ! -x "$build_dir/ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s/ec7wolf\n' "$build_dir" >&2
	exit 1
fi
if [ ! -f "$data_dir/MAPTEMP.CO7" ]; then
	printf 'SKIP: no MAPTEMP.CO7 in %s\n' "$data_dir"
	exit 0
fi

for command in xvfb-run python3; do
	command -v "$command" >/dev/null 2>&1 || {
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	}
done

work=$(mktemp -d /tmp/ec7edit-override.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

status=0
note() { printf '  %-5s %s\n' "$1" "$2"; }
fail() { note FAIL "$1"; status=1; }

archive="$data_dir/MAPTEMP.CO7"
before=$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$archive")

# The build's own pk3 must be beside the binary: ECWolf resolves ec7wolf.pk3
# from the working directory first, so running with the data directory as cwd
# would silently test whatever pk3 was installed there last.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$work/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && ln -s "$f" "$work/" || true
done

printf 'The shipped archive survives a full re-encode\n'
# The strongest fidelity statement available: parse all 60 maps and write them
# back out. Byte-identical means the writer reproduces the original TED5
# encoder exactly, so an archive this editor rewrites differs from the one that
# shipped only where the author actually edited it. It is also how the run
# threshold of four was found -- at three, all 180 planes decode correctly and
# not one of them re-encodes to the same bytes.
if PYTHONPATH="$repo/editor" python3 - "$archive" <<'PYEOF' >"$work/reencode.log" 2>&1
import sys
from ec7edit_core.archive import parse_archive, encode_archive
raw = open(sys.argv[1], "rb").read()
archive = parse_archive(raw)
out = encode_archive(archive.records)
if out != raw:
    differing = sum(1 for a, b in zip(raw, out) if a != b)
    sys.exit(f"{len(archive)} maps: {differing} bytes differ ({len(raw)} in, {len(out)} out)")
print(f"{len(archive)} maps, {len(raw)} bytes, identical")
PYEOF
then
	note ok "$(cat "$work/reencode.log")"
else
	fail "re-encoding the archive did not reproduce it"
	sed 's/^/    /' "$work/reencode.log"
fi

printf '\nExporting MAP51 into the MAP01 slot\n'
if ! PYTHONPATH="$repo/editor" python3 -m ec7edit_core convert-to-preview-wad \
	"$archive" --map 51 --slot MAP01 --output "$work/override.wad" \
	>"$work/export.log" 2>&1; then
	fail "the export failed"
	sed 's/^/    /' "$work/export.log"
	exit 1
fi
note ok "$(wc -c <"$work/override.wad" | tr -d ' ') bytes written"

# The engine must see the override WAD after the base data, or the stock map
# wins and this test would pass by loading the thing it meant to replace.
run() {
	label=$1
	level=$2
	shift 2
	(
		cd "$work"
		timeout 300s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s "-screen 0 320x200x24" ./ec7wolf \
			--data CO7 --no-upscale --nowait --vid-renderer software --res 320 200 \
			--config "$work/cfg-$label" --savedir "$work/sv-$label" \
			--tedlevel "$level" --skill 2 --capture-rngseed 12345 \
			--capture-players "$work/$label.txt" --capture-maxtics 4 "$@"
	) >"$work/$label.log" 2>&1 || true
}

# The first data row: tic, player, tilex, tiley.
spawn() {
	grep -v '^#' "$work/$1.txt" 2>/dev/null | head -1 | cut -d' ' -f3,4
}

printf '\nThree runs\n'
run stock01 MAP01
run stock51 MAP51
run patched MAP01 --file "$work/override.wad"

for label in stock01 stock51 patched; do
	if [ ! -s "$work/$label.txt" ]; then
		fail "$label produced no player trace; see $work/$label.log"
		status=1
	fi
done
[ "$status" -eq 0 ] || { printf '\nFAIL: see above.\n'; exit 1; }

at_stock01=$(spawn stock01)
at_stock51=$(spawn stock51)
at_patched=$(spawn patched)
note .. "stock MAP01 spawns at $at_stock01"
note .. "stock MAP51 spawns at $at_stock51"
note .. "MAP01 + override spawns at $at_patched"

printf '\nThe override took effect\n'
if [ "$at_stock01" = "$at_stock51" ]; then
	fail "MAP01 and MAP51 start in the same place, so this test cannot tell them apart"
else
	note ok "the two stock maps start in different places"
fi
if [ "$at_patched" = "$at_stock51" ]; then
	note ok "the overridden MAP01 starts where MAP51 does"
else
	fail "expected $at_stock51, got $at_patched"
fi
if [ "$at_patched" = "$at_stock01" ]; then
	fail "the overridden MAP01 still starts where stock MAP01 does"
else
	note ok "and not where stock MAP01 does"
fi

# Entry evidence beyond the spawn: the level ran for the tics it was asked for.
tics=$(grep -vc '^#' "$work/patched.txt" || true)
if [ "${tics:-0}" -ge 2 ]; then
	note ok "the overridden level ran ($tics traced tics)"
else
	fail "the overridden level produced only ${tics:-0} tics"
fi

printf '\nThe source archive was not touched\n'
after=$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$archive")
if [ "$before" = "$after" ]; then
	note ok "sha256 unchanged (${before%"${before#????????????}"})"
else
	fail "the archive changed: $before -> $after"
fi

if [ "$status" -eq 0 ]; then
	printf '\nPASS: a preview WAD overrides a base map.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
