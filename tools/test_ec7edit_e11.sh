#!/bin/sh

# Regression test: a generated map pack is a campaign the engine actually plays.
#
# Milestone E11 of docs/corridor7-level-editor.md. Everything before it exports
# a preview -- markers and PLANES, played in a stock slot under the stock
# level's name and routing. A pack adds generated MAPINFO, which is the first
# time the editor writes something the engine PARSES rather than reads as data.
# That is a different kind of risk, and this is where it is held down.
#
# The campaign is built here from nothing: three maps drawn by this script, in
# slots MAP61-63, which the stock Corridor 7 mapinfo does not define. That is
# deliberate on both counts. Nothing retail is in the pack, so the audit at the
# end means something; and a slot above the stock range cannot regress a
# shipped level, which is separately asserted by loading MAP01 with the pack in
# place and checking it still routes to MAP02.
#
# What is asserted:
#
#   1. The engine loads a map that exists ONLY in the pack, under the name the
#      generator gave it. MAP61 is in no archive; if lump lookup did not find
#      it the level would not exist at all.
#   2. Routing is what was generated. Not "the text says so" -- the engine
#      reports the next and secret maps it resolved from MAPINFO, and those are
#      compared against what the pack declared.
#   3. The normal exit routes. The player uses the elevator and the engine
#      enters MAP62.
#   4. The SECRET exit routes. Corridor 7 has no secret-exit tile: Exit_Normal
#      takes ex_secretlevel only when arg0 is 2, and no translator entry sets
#      that. What does is plane 1 -- gamemap_planes.cpp promotes the trigger on
#      a wall-63 cell when object 99 sits on it. So the pack's secretnext is
#      only reachable through a marker the editor has to know about, and this
#      proves the whole chain: marker, promotion, and the generated route.
#   5. The return path. MAP63's exit goes back to MAP62, which is how a bonus
#      floor rejoins a campaign.
#   6. The campaign ends. MAP62's next is EndTitle, and the engine must take
#      the victory path rather than entering another level.
#   7. Stock behaviour is unchanged with the pack loaded.
#   8. The package contains only markers, PLANES and metadata -- read back out
#      of the built file, not remembered from having written it.
#   9. Zero options misread as filenames, as E9 and E10 also require.
#
# Needs the archive and a display. Skipped without them; it never prints or
# copies retail map content.
#
# Usage: test_ec7edit_e11.sh BUILD_DIR DATA_DIR   (both absolute)

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
[ -f "$editor/ec7edit_core/campaign.py" ] || { printf 'SKIP: no map packs yet\n'; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data\n'; exit 0; }
grep -q "secretnext=" "$repo/src/c7_editorlink.cpp" 2>/dev/null || {
	printf 'SKIP: this build does not report resolved routing\n'; exit 0; }

status=0
work=$(mktemp -d /tmp/ec7wolf-e11.XXXXXX)
cleanup() { [ "$status" -eq 0 ] && rm -rf "$work" || printf '  logs kept in %s\n' "$work"; }
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

say()  { printf '  %-5s %s\n' "$1" "$2"; }
fail() { printf '  %-5s %s\n' "FAIL" "$1" >&2; status=1; }

lab="$work/lab"
mkdir -p "$lab"
# The build's OWN pk3: the engine resolves ec7wolf.pk3 from the working
# directory first, and a stale one there is a silent false pass.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done

# --- build the pack --------------------------------------------------------
#
# Through the editor's own project file and its own CLI verb, so this exercises
# what an author would actually run rather than a private path built for a test.
PYTHONPATH="$editor" python3 - "$work" <<'PY' || { printf 'FAIL: could not build the pack\n' >&2; exit 1; }
import sys
from pathlib import Path

from ec7edit_core.campaign import Campaign, CampaignEntry, Route
from ec7edit_core.document import MapDocument, ProjectDocument, new_uuid, utc_now
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.project import save_project

WIDTH = HEIGHT = 12
AREA = 256          # a real sound zone; word 0 would be no zone at all


def draw(slot, title, *, secret_elevator=False):
    """A sealed room with the player facing an elevator, and nothing else in it.

    No enemies on purpose: Exit_Normal applies Corridor 7's clearance
    percentage only when killtotal is above zero, so an empty floor lets the
    elevator answer immediately and the test measures routing rather than a
    body count.
    """
    walls = [1] * (WIDTH * HEIGHT)
    objects = [0] * (WIDTH * HEIGHT)
    for y in range(1, HEIGHT - 1):
        for x in range(1, WIDTH - 1):
            walls[y * WIDTH + x] = AREA

    at = lambda x, y: y * WIDTH + x
    objects[at(3, 3)] = 19                  # player start
    walls[at(3, 2)] = 63                    # the ordinary elevator, due north

    if secret_elevator:
        # Object 99 on a wall-63 cell is what makes a secret exit exist at all.
        walls[at(2, 3)] = 63
        objects[at(2, 3)] = 99

    return MapDocument(
        uuid=new_uuid(), slot=slot, native_name=NativeName.from_text(title),
        planes=MapPlanes(WIDTH, HEIGHT,
                         (tuple(walls), tuple(objects), tuple([0] * (WIDTH * HEIGHT)))),
    )


maps = (draw(61, "Entry", secret_elevator=True), draw(62, "Exit"), draw(63, "Bonus"))
# intermission=False on every level, because the tally screen blocks on input:
# with it on, the run stops on the tally and the level change never happens, so
# there is nothing to watch. tools/test_corridor7_keys_per_floor.sh covers the
# tally itself by clearing it with real keystrokes; what is under test here is
# where the engine goes next, and that is only observable without it.
campaign = Campaign(title="Synthetic Trial", key="S", entries=(
    CampaignEntry(61, "The Way In", next=Route(62), secret=Route(63), par=90,
                  intermission=False),
    CampaignEntry(62, "The Way Out", next=Route(None), intermission=False),
    CampaignEntry(63, "The Long Way Round", next=Route(62), intermission=False),
))

project = ProjectDocument(uuid=new_uuid(), maps=maps, name="E11 trial",
                          author="the gate", created_at=utc_now(),
                          campaign=campaign.to_json())
save_project(project, Path(sys.argv[1]) / "trial.ec7project")
PY

PYTHONPATH="$editor" python3 -m ec7edit_core project-pack "$work/trial.ec7project" \
	--output "$lab/trial.wad" --manifest "$work/trial.txt" >"$work/pack.log" 2>&1 || {
	printf 'FAIL: project-pack refused to build the pack\n' >&2
	cat "$work/pack.log" >&2
	exit 1
}
say ok "$(head -1 "$work/pack.log" | sed 's|.*/||')"

# --- run the campaign ------------------------------------------------------

# Runs the game and waits for the evidence, not for a clock.
#
# A run that reaches the end of the campaign stops at the victory page, which
# waits for a keypress nothing here can send: --capture-maxtics and
# --capture-maxframes are both checked inside the play loop, and that page is
# not in it. Waiting for such a run to exit meant waiting out the timeout,
# three times over -- this gate spent nine of its nine and a half minutes doing
# nothing at all. So it waits for the campaign-end event, which the engine
# sends before the fade for exactly this reason, and then stops the process
# itself. Every other run ends on its own tic budget and is simply waited for.
play() { # $1 label  $2 marker  $3.. extra args
	label=$1 marker=$2
	shift 2
	(
		cd "$lab"
		exec env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 640x400x24' ./ec7wolf \
			--data CO7 --nowait --file trial.wad \
			--editor-protocol 2 --editor-session e11 \
			--tedlevel "$marker" --skill 2 --capture-rngseed 1 \
			--config "$work/$label.cfg" --savedir "$work/$label.saves" "$@"
	) >"$work/$label.log" 2>&1 &
	game=$!

	_waited=0
	while [ "$_waited" -lt 900 ]; do          # 900 x 0.2s = three minutes
		kill -0 "$game" 2>/dev/null || break
		grep -q "EC7EDIT e11 campaign-end" "$work/$label.log" 2>/dev/null && break
		sleep 0.2
		_waited=$((_waited + 1))
	done
	if [ "$_waited" -ge 900 ]; then
		fail "$label neither finished nor reached an ending within three minutes"
	fi

	kill "$game" 2>/dev/null || true
	wait "$game" 2>/dev/null || true
	sed -i 's/\x08//g' "$work/$label.log" 2>/dev/null || true
}

# Every map entered, oldest first, as "MARKER next secretnext".
route() { # $1 label
	grep "EC7EDIT e11 map-entry" "$work/$1.log" 2>/dev/null |
		sed -n 's/.*marker=\([^ ]*\).*next=\([^ ]*\) secretnext=\([^ ]*\).*/\1 \2 \3/p'
}

# 1 + 2: a map that exists only in the pack, and the routing it resolved.
play resolved MAP61 --capture-maxtics 30
first=$(route resolved | head -1)
if [ "$first" = "MAP61 MAP62 MAP63" ]; then
	say ok "MAP61 exists only in the pack, and resolved next=MAP62 secretnext=MAP63"
else
	fail "MAP61 resolved '$first', expected 'MAP61 MAP62 MAP63'"
	tail -5 "$work/resolved.log" >&2 || true
fi
grep -q "MAP61 - The Way In" "$work/resolved.log" ||
	fail "the level did not take the name the generator gave it"

# The tic budgets below are bounds, not durations: the harness counter is
# monotonic across levels, an exit fires about thirty tics after the run starts,
# and each further level costs about the same again. 300 is roughly ten times
# what a two-level route needs and 400 covers three, which leaves room for a
# slow machine without spending a minute per run waiting for a counter.
#
# 3: the normal exit. Facing north from (3.5,3.5) is the ordinary elevator.
play normal MAP61 --capture-maxtics 300 --capture-place 10 3.5 3.5 90 --capture-use 20 6
if [ "$(route normal | sed -n 2p | cut -d' ' -f1)" = "MAP62" ]; then
	say ok "the elevator routes MAP61 -> MAP62, the generated next"
else
	fail "the normal exit went to '$(route normal | sed -n 2p | cut -d' ' -f1)', not MAP62"
	route normal >&2
fi

# 4: the secret exit. Facing west is the wall-63 cell carrying object 99.
play secret MAP61 --capture-maxtics 300 --capture-place 10 3.5 3.5 180 --capture-use 20 6
if [ "$(route secret | sed -n 2p | cut -d' ' -f1)" = "MAP63" ]; then
	say ok "the marker-99 elevator routes MAP61 -> MAP63, the generated secretnext"
else
	fail "the secret exit went to '$(route secret | sed -n 2p | cut -d' ' -f1)', not MAP63"
	route secret >&2
fi

# 5 and 6, from one run and in this order on purpose.
#
# The tic counter restarts with each level, so the --capture-use window at tic
# 20 comes round again on every floor: start on MAP63 and the run walks itself
# to the end of the campaign, pressing the elevator on each. That is what makes
# the ending assertion mean anything. "No further level was entered" is also
# what a press that silently did nothing looks like, so it is only evidence
# once the SAME press has been seen to work -- which is check 5, on a floor
# drawn identically to MAP62 by the same function.
play ending MAP63 --capture-maxtics 400 --capture-place 10 3.5 3.5 90 --capture-use 20 6
chain=$(route ending | cut -d' ' -f1 | tr '\n' ' ')
ended=$(sed -n 's/.*campaign-end via=\([^ ]*\).*/\1/p' "$work/ending.log" | head -1)
if [ "$chain" = "MAP63 MAP62 " ] && [ "$ended" = "EndTitle" ]; then
	say ok "MAP63 returns to MAP62, so a bonus floor rejoins the campaign"
	say ok "and MAP62's exit ends the campaign via EndTitle, not a fourth level"
else
	fail "the campaign walked '$chain' and ended via '$ended'; expected 'MAP63 MAP62 ' and EndTitle"
	route ending >&2
fi

# 7: no stock regression. MAP01 with the pack loaded is the shipped MAP01.
play stock MAP01 --capture-maxtics 30
stock=$(route stock | head -1)
if [ "$stock" = "MAP01 MAP02 MAP41" ]; then
	say ok "with the pack loaded, stock MAP01 still routes to MAP02 (secret MAP41)"
else
	fail "stock MAP01 resolved '$stock', expected 'MAP01 MAP02 MAP41'"
fi

# 9: nothing was read as a filename, in any of those runs.
strays=$(cat "$work"/*.log 2>/dev/null | grep -c "Could not stat" || true)
if [ "$strays" -eq 0 ]; then
	say ok "no option was misread as a resource path"
else
	fail "$strays 'Could not stat' line(s) across the runs"
	grep -h "Could not stat" "$work"/*.log | sort -u | head -5 >&2
fi

# --- 8: what is actually in the file ---------------------------------------
PYTHONPATH="$editor" python3 - "$lab/trial.wad" "$work/trial.txt" <<'PY' || status=1
import sys
from pathlib import Path

from ec7edit_core.campaign import audit_pack

pack = Path(sys.argv[1]).read_bytes()
report = audit_pack(pack)
if not report.clean:
    sys.exit(f"  FAIL  the pack holds {', '.join(report.unexpected)}")
if report.markers != ("MAP61", "MAP62", "MAP63"):
    sys.exit(f"  FAIL  the pack holds markers {report.markers}")

# Nothing retail may have travelled with it. The maps were drawn by this
# script, so every plane word in the file has to be one of the few this script
# writes -- a stock map's words would show up immediately.
allowed = {0, 1, 19, 63, 99, 256}
from ec7edit_core.wad import decode_planes_lump, decode_wad
for lump in decode_wad(pack):
    if lump.name != "PLANES":
        continue
    record = decode_planes_lump(lump.data)
    used = {word for plane in record.planes.planes for word in plane}
    if not used <= allowed:
        sys.exit(f"  FAIL  a map carries words this test never wrote: "
                 f"{sorted(used - allowed)[:8]}")

manifest = Path(sys.argv[2]).read_text()
for required in ("Corridor 7", "own", "MAP61", "MAPINFO"):
    if required not in manifest:
        sys.exit(f"  FAIL  the manifest never mentions {required!r}")

print(f"  ok    the package holds only markers, PLANES and metadata "
      f"({report.map_bytes} + {report.metadata_bytes} bytes)")
print("  ok    the manifest states what it is and that the player needs the game")
PY

[ "$status" -eq 0 ] && printf 'PASS: a generated pack is a campaign the engine plays.\n' \
	|| printf 'FAIL: see above.\n' >&2
exit "$status"
