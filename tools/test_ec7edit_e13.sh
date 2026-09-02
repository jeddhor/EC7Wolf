#!/bin/sh

# Regression test: a campaign made of somebody else's art actually plays.
#
# Milestone E13 of docs/corridor7-level-editor.md. Everything before it ships
# Corridor 7's own content; this is the first time the editor writes a pack
# holding art the game never had, and the first time a map word means something
# no translator in the repository defines.
#
# The resource pack is built HERE, out of a PNG this script writes byte by
# byte. Not borrowed from the workspace: a gate that depends on a file
# somebody happens to have is a gate that passes on one machine.
#
# What is asserted, in the order a failure would matter:
#
#   1. The editor can say what is in a pack, and refuses one it should not
#      open -- a name escaping the archive, Corridor 7's own data smuggled in.
#   2. Attaching one allocates a map word, and attaching again does not move
#      it. That is the property everything else rests on: a word is written
#      into map data, so a word that moved would silently change what a map
#      spawns, with the map file unchanged and looking correct.
#   3. The pack is a pk3 laid out the way the engine reads one, with the maps
#      under maps/ as embedded WADs -- a root marker is followed by MAPINFO
#      once the archive is sorted, and the engine refuses it.
#   4. The engine spawns the custom actor at the tiles the editor placed it,
#      from ONE file with no other --file beside it.
#   5. Stock MAP01 is unchanged with the pack loaded. Additive placement is
#      the whole design; a pack that quietly alters the base game is the thing
#      this is built to avoid.
#   6. Nothing of Corridor 7's is in the built pack.
#
# Needs the archive and a display. Skipped without them.
#
# Usage: test_ec7edit_e13.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

. "$repo/tools/xvfb_common.sh"

command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }
[ -f "$editor/ec7edit_core/resources.py" ] || {
	printf 'SKIP: no resource packs yet\n'; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data\n'; exit 0; }

status=0
work=$(mktemp -d /tmp/ec7wolf-e13.XXXXXX)
game=""
cleanup() {
	[ -n "$game" ] && kill "$game" 2>/dev/null
	xvfb_stop 2>/dev/null || true
	[ "$status" -eq 0 ] && rm -rf "$work" || printf '  logs kept in %s\n' "$work"
}
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

say()  { printf '  %-5s %s\n' "$1" "$2"; }
fail() { printf '  %-5s %s\n' "FAIL" "$1" >&2; status=1; }

ec7edit() { ( cd "$editor" && PYTHONPATH="$editor" python3 -m ec7edit_core "$@" ); }

# --- 1. a resource pack, made here ------------------------------------------
printf '\nReading a resource pack\n'
PYTHONPATH="$editor" python3 - "$work" <<'PY' || { printf 'FAIL: could not build the fixture\n' >&2; exit 1; }
import struct
import sys
import zlib
import zipfile
from pathlib import Path

work = Path(sys.argv[1])


def png(width: int, height: int, rgb: tuple) -> bytes:
    """A solid PNG, written here rather than drawn by a library.

    The engine has to load this as a sprite, so it must be a real file -- and
    the gate must not need Pillow or Qt to produce one.
    """
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


DECORATE = """\
// A test actor: stands still, is visible, and does nothing else.
actor EC7TestBloom : C7Rodex replaces C7Rodex
{
    health 40
    speed 0, 0
    states
    {
    Spawn:
        TBLM A -1
        stop
    }
}
"""

with zipfile.ZipFile(work / "bloom.pk3", "w") as archive:
    archive.writestr("DECORATE", DECORATE)
    archive.writestr("sprites/TBLMA0.png", png(24, 40, (200, 40, 160)))
    archive.writestr("previews/sheet.png", png(8, 8, (0, 0, 0)))
    archive.writestr("docs/brief.md", "notes the author kept\n")

# One that must be refused: a name that climbs out of the archive.
with zipfile.ZipFile(work / "hostile.pk3", "w") as archive:
    archive.writestr("sprites/TBLMA0.png", png(4, 4, (0, 0, 0)))
    archive.writestr("../../../etc/passwd", "root\n")

# And one carrying Corridor 7's own data.
with zipfile.ZipFile(work / "retail.pk3", "w") as archive:
    archive.writestr("sprites/TBLMA0.png", png(4, 4, (0, 0, 0)))
    archive.writestr("MAPTEMP.CO7", b"\0" * 64)
print("  ..   built bloom.pk3, hostile.pk3 and retail.pk3")
PY

if ec7edit resource-inspect "$work/bloom.pk3" >"$work/inspect.txt" 2>&1 &&
	grep -q "EC7TestBloom" "$work/inspect.txt" &&
	grep -q "sprite TBLM" "$work/inspect.txt"; then
	say ok "it reads the actor, what it inherits, and the sprite it draws"
else
	fail "resource-inspect did not describe the pack"
	cat "$work/inspect.txt" >&2
fi

for bad in hostile retail; do
	if ec7edit resource-inspect "$work/$bad.pk3" >"$work/$bad.txt" 2>&1; then
		fail "$bad.pk3 was accepted; it should not have been"
	else
		say ok "$bad.pk3 is refused: $(sed -n 's/^error: //p' "$work/$bad.txt" |
			cut -c1-60 | head -1)"
	fi
done

# --- 2. attaching, and the word staying put ---------------------------------
printf '\nAllocating a map word\n'
ec7edit project-new --output "$work/garden.ec7project" --name Garden >/dev/null

PYTHONPATH="$editor" python3 - "$work" <<'PY' || exit 1
import sys
from pathlib import Path

from ec7edit_core.campaign import Campaign, CampaignEntry, Route
from ec7edit_core.document import MapDocument, new_uuid
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.project import load_project, save_project

work = Path(sys.argv[1])
W = H = 20
walls = [1] * (W * H)
objects = [0] * (W * H)
for y in range(1, H - 1):
    for x in range(1, W - 1):
        walls[y * W + x] = 256
at = lambda x, y: y * W + x
objects[at(3, 3)] = 19          # player start
walls[at(3, 2)] = 63            # a way out
objects[at(15, 15)] = 216       # a stock C7Rodex, the class the pack replaces

path = work / "garden.ec7project"
project = load_project(path).added(MapDocument(
    uuid=new_uuid(), slot=61, native_name=NativeName.from_text("Garden"),
    planes=MapPlanes(W, H, (tuple(walls), tuple(objects), tuple([0] * (W * H))))))
project = project.with_campaign(Campaign(
    title="Garden Trial", key="G", entries=(
        CampaignEntry(61, "The Garden", next=Route(None), intermission=False),
    )).to_json())
save_project(project, path)
PY

ec7edit resource-add "$work/garden.ec7project" "$work/bloom.pk3" \
	>"$work/attach.txt" 2>&1 || { fail "resource-add failed"; cat "$work/attach.txt" >&2; }
word=$(sed -n 's/^  object word \([0-9]*\).*/\1/p' "$work/attach.txt" | head -1)
if [ -n "$word" ]; then
	say ok "EC7TestBloom was given object word $word"
else
	fail "no word was allocated"
	cat "$work/attach.txt" >&2
	exit 1
fi

ec7edit resource-add "$work/garden.ec7project" "$work/bloom.pk3" \
	>"$work/attach2.txt" 2>&1 || true
again=$(PYTHONPATH="$editor" python3 -c "
import sys
from ec7edit_core.project import load_project
project = load_project('$work/garden.ec7project')
print(sorted(project.allocations)[0].split(':')[1])")
if [ "$again" = "$word" ]; then
	say ok "attaching it again leaves the word exactly where it was"
else
	fail "the word moved from $word to $again on a second attach"
fi

# --- 3 and 4. build it, and play it -----------------------------------------
printf '\nBuilding and playing the pack\n'
PYTHONPATH="$editor" python3 - "$work" "$word" <<'PY' || exit 1
import sys
from dataclasses import replace
from pathlib import Path

from ec7edit_core.planes import MapPlanes
from ec7edit_core.project import load_project, save_project

work, word = Path(sys.argv[1]), int(sys.argv[2])
path = work / "garden.ec7project"
project = load_project(path)
document = project.maps[0]
planes = [list(plane) for plane in document.planes.planes]
for x, y in ((8, 8), (12, 5), (6, 14)):
    planes[1][y * document.width + x] = word
document = document.with_planes(MapPlanes(document.width, document.height,
                                          tuple(tuple(p) for p in planes)))
save_project(replace(project, maps=(document,)), path)
print("  ..   painted three of them")
PY

ec7edit project-pack "$work/garden.ec7project" --output "$work/garden.pk3" \
	>"$work/pack.txt" 2>&1 || { fail "project-pack failed"; cat "$work/pack.txt" >&2; exit 1; }
say ok "$(head -1 "$work/pack.txt" | sed 's|.*/||')"

PYTHONPATH="$editor" python3 - "$work/garden.pk3" <<'PY' || status=1
import sys
import zipfile
from pathlib import Path

from ec7edit_core.packfile import audit_pk3

data = Path(sys.argv[1]).read_bytes()
report = audit_pk3(data)
if not report.clean:
    sys.exit("  FAIL  the pack holds " + ", ".join(report.unexpected))

names = set(report.lump_names)
for required in ("maps/MAP61.wad", "MAPINFO", "xlat/ec7edit.txt", "DECORATE",
                 "sprites/TBLMA0.png", "PACKINFO"):
    if required not in names:
        sys.exit(f"  FAIL  the pack has no {required}")
if "MAP61" in names:
    sys.exit("  FAIL  a root MAP61 marker; archive entries are sorted, so the "
             "engine would find MAPINFO after it and refuse the map")
if any(n.startswith("previews/") or n.startswith("docs/") for n in names):
    sys.exit("  FAIL  the author's own working files were shipped")
print("  ok    maps under maps/, metadata, art, and none of the author's notes")
PY

lab="$work/lab"
mkdir -p "$lab"
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done
cp "$work/garden.pk3" "$lab/"

display=:183
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || {
	printf 'SKIP: no Xvfb available\n'; exit 0; }

play() { # $1 label  $2 marker  $3.. extra
	label=$1 marker=$2
	shift 2
	( cd "$lab"
	  exec env DISPLAY="$display" SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
		./ec7wolf --data CO7 --nowait --file garden.pk3 \
		--editor-protocol 2 --editor-session e13 \
		--tedlevel "$marker" --skill 2 --capture-rngseed 1 \
		--config "$work/$label.cfg" --savedir "$work/$label.saves" "$@"
	) >"$work/$label.log" 2>&1 &
	game=$!
	wait "$game" 2>/dev/null || true
	game=""
	sed -i 's/\x08//g' "$work/$label.log" 2>/dev/null || true
}

play custom MAP61 --capture-maxtics 15 --capture-actors "$work/actors.txt"
placed=$(awk 'NR > 1 && $1 == 1 && $2 == "EC7TestBloom" {print $3","$4}' \
	"$work/actors.txt" 2>/dev/null | sort | tr '\n' ' ')
if [ "$placed" = "12,5 6,14 8,8 " ]; then
	say ok "all three spawned, at the tiles the editor placed them"
else
	fail "the custom actor spawned at '$placed', expected '12,5 6,14 8,8 '"
	tail -5 "$work/custom.log" >&2 || true
fi

# The pack's DECORATE says `replaces C7Rodex`, and the map has a stock Rodex on
# it. That combination is the one way additive placement silently fails: with
# the replacement left in, BOTH words spawn the custom actor and the original
# cannot be placed at all. The editor drops it when building, so both are here.
stock_actor=$(awk 'NR > 1 && $1 == 1 && $3 == 15 && $4 == 15 {print $2}' \
	"$work/actors.txt" 2>/dev/null | head -1)
if [ "$stock_actor" = "C7Rodex" ]; then
	say ok "and the stock C7Rodex beside them is still a C7Rodex"
else
	fail "the stock actor at (15,15) is '$stock_actor', not C7Rodex --"
	fail "  the pack's 'replaces' reached the build and swallowed it"
fi
grep -q "MAP61 - The Garden" "$work/custom.log" ||
	fail "the pack's own floor was not entered"

play stock MAP01 --capture-maxtics 15
stock=$(sed -n 's/.*marker=\([^ ]*\).*next=\([^ ]*\) secretnext=\([^ ]*\).*/\1 \2 \3/p' \
	"$work/stock.log" | head -1)
if [ "$stock" = "MAP01 MAP02 MAP41" ]; then
	say ok "with the pack loaded, stock MAP01 is still the shipped MAP01"
else
	fail "stock MAP01 resolved '$stock', expected 'MAP01 MAP02 MAP41'"
fi

strays=$(cat "$work"/*.log 2>/dev/null | grep -c "Could not stat" || true)
[ "$strays" -eq 0 ] && say ok "no option was misread as a resource path" \
	|| fail "$strays 'Could not stat' line(s)"

[ "$status" -eq 0 ] && printf '\nPASS: a pack of somebody else'"'"'s art plays.\n' \
	|| printf '\nFAIL: see above.\n' >&2
exit "$status"
