#!/bin/sh

# Regression test: the Intruder Alert is a noise, not a summons (GitHub #24).
#
# CORR7CD.EXE's alarm panel (14bfd) sets DS:b3d7 -- the noise flag a gunshot
# sets -- for one frame, and its SightPlayer (136e1) decides who reacts. This
# port used to wake every live monster on the floor at once instead, including
# aliens behind closed doors and every ambusher and boss. The lab built by
# make_corridor7_alarm_lab.py separates the cases the native rule
# distinguishes; every alien in it faces away from the player and stands out of
# automatic-sight range, so only noise can reach it:
#
#   quiet     no alarm. Nothing may wake, or the lab is broken and the other
#             runs prove nothing.
#   classic   the alarm under the DOS rule. The alien in the player's room
#             reacts; the one behind the closed door does not; no ambusher
#             reacts sooner than the native minimum delay of 32 tics, and they
#             do not all react.
#   map-wide  the optional rule: the noise passes every door, so the alien
#             behind the door reacts too. Ambushers are judged exactly as under
#             the classic rule -- boss or not, an ambush is not blanket-woken.
#   loaded    a save made under the map-wide rule, loaded by a player whose own
#             setting is classic: the rule belongs to the game, not the menu.
#   gunfire   two seconds of gunfire under the classic rule, then silence.
#             Ambushers are not deaf: each noisy frame is a 25-in-256 draw for
#             a delayed wake, so some come looking -- never within 32 tics of
#             the first shot, and some long after the last one, when nothing
#             but their own countdown can have brought them.
#
# Usage: test_corridor7_intruder_alert.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d /tmp/ec7wolf-alarm.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

lab="$work/lab"
mkdir -p "$lab" "$work/saves"
# The build's own pk3, for the reason test_corridor7_hearing.sh gives: one
# sitting in the data directory would silently be tested instead.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done
python3 "$here/make_corridor7_alarm_lab.py" \
	"$data_dir/MAPTEMP.CO7" "$lab/MAPTEMP.CO7" >/dev/null

run() { # $1 = tag, $2 = alert rule (0/1), $3 = tics, $4... = extra flags
	tag=$1 rule=$2 tics=$3
	shift 3
	printf 'C7IntruderAlert = %s;\n' "$rule" >"$work/$tag.cfg"
	(
		cd "$lab"
		timeout 300s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 640x400x24' ./ec7wolf \
			--data CO7 --no-upscale --nowait --vid-renderer software --res 320 200 \
			--config "$work/$tag.cfg" --savedir "$work/saves" \
			--tedlevel MAP01 --skill 2 --capture-rngseed 12345 \
			--capture-health 100000 --capture-actors "$work/$tag.txt" \
			--capture-maxtics "$tics" "$@"
	) >"$work/$tag.log" 2>&1 || true
	if [ ! -s "$work/$tag.txt" ]; then
		printf 'FAIL: the %s run produced no actor trace; see %s/%s.log\n' \
			"$tag" "$work" "$tag" >&2
		exit 1
	fi
}

# The alarm is raised by holding Use at the terminal for tics 35-37.
run quiet 0 400 &
run classic 0 400 --capture-use 35 3 &
run mapwide 1 400 --capture-save 20 mapwide.ec7 --capture-use 35 3 &
run gunfire 0 3000 --capture-hold-button attack 35 140 --capture-ammo &
wait
run loaded 0 400 --capture-load 5 mapwide.ec7 --capture-use 35 3

status=0
python3 - "$work" <<'PY' || status=$?
import sys
from collections import defaultdict
from pathlib import Path

work = Path(sys.argv[1])
# The first tic any noise can have been made, on the actor log's clock. The
# loaded run's clock jumps at the load (tic 5), and its alarm comes after it.
ALARM = {"quiet": 35, "classic": 35, "mapwide": 35, "gunfire": 35, "loaded": 5}
MIN_DELAY = 32      # (0 + 1) << 5: the shortest native ambush delay
failed = False

def wakes(tag):
    """The tic each alien reacted, keyed by the tile it started on. A standing
    alien does not move until it reacts, so its tile on the tic before it
    entered attack mode is its starting tile -- which holds across a loaded
    save, where the actor list is rebuilt and positions in it may change."""
    rows = defaultdict(list)
    for line in (work / f"{tag}.txt").read_text().splitlines():
        if line.startswith("#"):
            continue
        f = line.split()
        if f[1] == "C7Rodex":
            rows[int(f[0])].append(f)
    tics = sorted(rows)
    start = [(int(r[2]), int(r[3])) for r in rows[tics[0]]]
    woke, seen, prev = {}, set(), None
    for t in tics:
        cur = rows[t]
        if prev is not None and len(prev) == len(cur):
            for i, (a, b) in enumerate(zip(prev, cur)):
                if a[6] == "0" and b[6] == "1" and i not in seen:
                    seen.add(i)
                    woke.setdefault((int(a[2]), int(a[3])), t)
        prev = cur
    return start, woke

def check(ok, message):
    global failed
    print(("  ok  " if ok else "FAIL ") + message)
    failed |= not ok

NEAR, DOOR = (4, 32), (16, 32)
for tag in ("quiet", "classic", "mapwide", "loaded", "gunfire"):
    aliens, woke = wakes(tag)
    ambush = [a for a in aliens if a[0] <= 3 and a != NEAR]
    if len(ambush) != 27 or NEAR not in aliens or DOOR not in aliens:
        check(False, f"{tag}: the lab did not load as built "
              f"({len(ambush)} ambushers)")
        continue
    early = sorted(t for a, t in woke.items() if a in ambush and t < ALARM[tag] + MIN_DELAY)
    late = sorted(t for a, t in woke.items() if a in ambush)
    if tag == "quiet":
        check(not woke, f"quiet: nothing woke without noise ({len(woke)} did)")
        continue
    if tag != "gunfire":
        check(NEAR in woke, f"{tag}: the alien in the player's room reacted "
              f"(tic {woke.get(NEAR, 'never')})")
        heard_door = tag in ("mapwide", "loaded")
        check((DOOR in woke) == heard_door,
              f"{tag}: the alien behind the closed door "
              + ("reacted" if heard_door else "slept")
              + f" (tic {woke.get(DOOR, 'never')})")
        check(len(late) < len(ambush),
              f"{tag}: the ambushers were not all woken ({len(late)} of {len(ambush)})")
    else:
        check(len(late) > 0, f"gunfire: ambushers are not deaf -- {len(late)} of "
              f"{len(ambush)} came looking, first at tic {late[0] if late else 'never'}")
        # The gun falls silent at tic 175; give the last shot's reactions a
        # generous margin, after which only a countdown can wake anything.
        silent = [t for t in late if t > 175 + MIN_DELAY]
        check(len(silent) > 0, f"gunfire: ambushers' delays ran out in silence "
              f"({len(silent)} came looking after tic {175 + MIN_DELAY})")
    check(not early, f"{tag}: no ambusher reacted within {MIN_DELAY} tics of the "
          f"first noise (early: {early})")

for tag, rule in (("classic", "classic"), ("mapwide", "map-wide")):
    log = (work / f"{tag}.log").read_text()
    check(f"Corridor 7 intruder alert rule: {rule}" in log,
          f"{tag}: the game started under the {rule} rule")
check("Capture: loaded snapshot" in (work / "loaded.log").read_text(),
      "loaded: the map-wide save was loaded")

sys.exit(1 if failed else 0)
PY
[ "$status" -eq 0 ] && printf 'PASS: the intruder alert is a noise heard by the native rules\n'
exit "$status"
