#!/bin/sh

# Regression test: a bonus floor gives back what was carried in (GitHub #23).
#
# CORR7CD.EXE copies nine values aside when the player takes a bonus elevator
# (a14a) and copies them back when the bonus floor ends (a0f6), whether by the
# exit or by the player's health running out (13e22): health, bullets, armor,
# visor charge, alien weapon energy, and the owned and selected weapons. Ammo
# capacity and mines are not in the set, and a live DOS run confirmed that both
# keep what the bonus floor did to them. The floor setup that follows then caps
# health and ends an invulnerability sphere, as on any floor (216b4).
#
# Before this the port carried everything straight through. The runs:
#
#   warp      a bonus floor started directly, so its baseline is the starting
#             inventory; at the first tic the player is wounded and handed a
#             shotgun, an ammo capacity pack, mines, armor, alien-weapon energy
#             and a sphere. After
#             the exit the next floor must see the baseline back -- with the
#             capacity upgrade and the mines kept -- and the score must hold
#             the hit/miss page's accuracy award for 113 shots and 66 hits,
#             1160 points, exactly once.
#   elevator  MAP01 with a wound, a shotgun and armor; the secret exit; killed
#             on the bonus floor. The baseline is what came up the elevator,
#             it comes back intact, and no death ends the game.
#   saved     a save made on the bonus floor after its inventory changed,
#             loaded from a fresh game: the exit still restores the entry
#             state, which the save carries. Saves from before the entry state
#             existed take the loaded inventory as the baseline and say so.
#   routes    each of the six bonus floors leads back to its campaign floor
#             and restores on the way.
#
# The report pages wait for a key, so every run is fed one keypress every two
# seconds -- K, which nothing in play is bound to.
#
# Usage: test_corridor7_bonus_floor.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
for command in xvfb-run xdotool python3; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-bonus.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# Symlinks keep the data directory untouched; the pk3 is the build's own.
mkdir -p "$work/data"
for f in "$data_dir"/*.CO7 "$data_dir/CORR7CD.EXE"; do
	[ -e "$f" ] && ln -s "$f" "$work/data/$(basename "$f")"
done
cp "$build_dir/ec7wolf.pk3" "$work/data/"
export BF_BUILD="$build_dir" BF_WORK="$work"

play() { # $1 = tag, $2 = map, $3... = capture flags
	BF_TAG=$1 BF_MAP=$2
	shift 2
	BF_ARGS="$*"
	export BF_TAG BF_MAP BF_ARGS
	mkdir -p "$work/saves-$BF_TAG"
	timeout 300s xvfb-run -a -s '-screen 0 640x400x24' sh -c '
		cd "$BF_WORK/data"
		export SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11
		"$BF_BUILD/ec7wolf" --data CO7 --nowait --no-upscale --vid-renderer software \
			--res 320 200 --config "$BF_WORK/$BF_TAG.cfg" --savedir "$BF_WORK/saves-$BF_TAG" \
			--tedlevel "$BF_MAP" --skill 2 --capture-rngseed 7 --capture-inventory \
			$BF_ARGS >"$BF_WORK/$BF_TAG.log" 2>&1 &
		pid=$!
		n=0
		while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 30 ]; do
			sleep 2
			xdotool key --clearmodifiers k 2>/dev/null || true
			n=$((n + 1))
		done
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	' || true
}

play warp MAP41 --capture-health 37 --capture-give C7Shotgun --capture-give C7AmmoPack \
	--capture-give C7MinePack --capture-give C7BodyArmor --capture-give C7Invulnerability \
	--capture-give C7ChargePack --capture-fire 20 --capture-shots 113 66 --capture-exitlevel 140 --capture-maxtics 300 &
play elevator MAP01 --capture-health 63 --capture-give C7Shotgun --capture-give C7BodyArmor \
	--capture-secretexit 30 --capture-fire 40 --capture-kill-slot 0 150 --capture-maxtics 300 &
play saving MAP41 --capture-health 37 --capture-give C7Shotgun --capture-give C7AmmoPack \
	--capture-save 60 bonus.ec7 --capture-maxtics 80 &
wait
mkdir -p "$work/saves-saved"
cp "$work/saves-saving/bonus.ec7" "$work/saves-saved/" 2>/dev/null || true
play saved MAP01 --capture-load 5 bonus.ec7 --capture-exitlevel 100 --capture-maxtics 200 &
for map in MAP42 MAP43 MAP44 MAP45 MAP46; do
	play "route-$map" "$map" --capture-health 50 --capture-exitlevel 35 --capture-maxtics 120 &
done
wait

status=0
python3 - "$work" <<'PY' || status=$?
import re
import sys
from pathlib import Path

work = Path(sys.argv[1])
failed = False

def check(ok, message):
    global failed
    print(("  ok  " if ok else "FAIL ") + message)
    failed |= not ok

def floors(tag):
    """The inventory each level was entered with, by map."""
    seen = {}
    path = work / f"{tag}.log"
    text = path.read_text(errors="replace") if path.exists() else ""
    for line in text.splitlines():
        if not line.startswith("inventory "):
            continue
        fields = dict(f.split("=", 1) for f in line.split()[1:])
        seen.setdefault(fields["map"], fields)
    return seen, text

def amount(fields, cls):
    return int(fields[cls].split("/")[0]) if cls in fields else None

def capacity(fields, cls):
    return int(fields[cls].split("/")[1]) if cls in fields else None

# warp: everything changed after the baseline, and only the exceptions survive.
f, log = floors("warp")
after = f.get("MAP02")
check(after is not None, "warp: the bonus exit reached MAP02")
if after:
    check(after["health"] == "100", f"warp: health restored to 100 (got {after['health']})")
    check(amount(after, "C7Bullets") == 100, f"warp: bullets restored to 100 (got {amount(after, 'C7Bullets')})")
    check(capacity(after, "C7Bullets") == 700, f"warp: the capacity upgrade is kept (max {capacity(after, 'C7Bullets')})")
    check(amount(after, "C7Mines") == 25, f"warp: the mines are kept (got {amount(after, 'C7Mines')})")
    check("C7Shotgun" not in after, "warp: the shotgun found on the bonus floor is gone")
    check(not amount(after, "C7BodyArmor"), f"warp: the armor found there is gone (got {amount(after, 'C7BodyArmor')})")
    check(not amount(after, "C7Energy"), f"warp: the energy found there is gone (got {amount(after, 'C7Energy')})")
    check("C7Invulnerability" not in after, "warp: the sphere ended at the floor change")
    check(after["ready"] == "C7M16", f"warp: the M16 is back in hand (got {after['ready']})")
    check(after["score"] == "1160", f"warp: the accuracy award was paid once (score {after['score']})")

# elevator: the baseline is what came up the elevator.
f, log = floors("elevator")
entry, after = f.get("MAP41"), f.get("MAP02")
check(entry is not None and "taking the secret exit" in log, "elevator: MAP01's secret exit led to MAP41")
check("killing slot 0" in log and after is not None,
      "elevator: killed on the bonus floor, the game went on to MAP02")
if entry and after:
    for key in ("health",):
        check(after[key] == entry[key], f"elevator: {key} {after[key]} matches the entry {entry[key]}")
    for cls in ("C7Bullets", "C7BodyArmor", "C7Shotgun", "C7M16"):
        check(amount(after, cls) == amount(entry, cls),
              f"elevator: {cls} {amount(after, cls)} matches the entry {amount(entry, cls)}")
    check(after["ready"] == entry["ready"], f"elevator: {after['ready']} is in hand, as at entry")

# saved: the entry state rides in the save.
saving = (work / "saves-saving" / "bonus.ec7")
version = 0
if saving.exists():
    m = re.search(rb"ECWolf Save Version\x00[^0-9]*(\d+)", saving.read_bytes())
    version = int(m.group(1)) if m else 0
f, log = floors("saved")
after = f.get("MAP02")
check(saving.exists() and "loaded snapshot" in log and after is not None,
      "saved: a bonus-floor save was loaded and exited")
if after and version >= 1794600000:
    check(after["health"] == "100" and "C7Shotgun" not in after,
          f"saved: the exit restored the entry state the save carried "
          f"(health {after['health']}, shotgun {'kept' if 'C7Shotgun' in after else 'gone'})")
    check("predates bonus-floor entry state" not in log, "saved: the save was not treated as legacy")
elif after:
    # Save versions are commit dates, so an uncommitted tree writes the old
    # format; that is the legacy path, and it must say so and keep the load.
    print(f"  --  saved: save version {version} predates the entry state (an "
          f"uncommitted build); checking the legacy path instead")
    check("predates bonus-floor entry state" in log and after["health"] == "37",
          "saved: a legacy save takes the loaded inventory as its baseline and says so")

# routes: each bonus floor returns to its campaign floor.
for bonus, nxt in (("MAP42", "MAP06"), ("MAP43", "MAP11"), ("MAP44", "MAP16"),
                   ("MAP45", "MAP21"), ("MAP46", "MAP26")):
    f, log = floors(f"route-{bonus}")
    after = f.get(nxt)
    check(after is not None and "bonus floor ended: restored entry state" in log
          and after["health"] == "100",
          f"routes: {bonus} returns to {nxt} with its entry health "
          f"({after['health'] if after else 'not reached'})")
# MAP41 -> MAP02 is the warp run above.

sys.exit(1 if failed else 0)
PY
[ "$status" -eq 0 ] && printf 'PASS: bonus floors give back what was carried in\n'
exit "$status"
