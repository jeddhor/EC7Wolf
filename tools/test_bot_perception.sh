#!/bin/sh

# Regression test: a bot sees only what a player standing there could see.
#
# Milestone B4 of docs/multiplayer-bots-and-server.md, section 13.2.
#
# The headline check recomputes every sight line from the map's own wall grid
# and fails if any of them passes through a wall. That is deliberately not a
# restatement of what the engine did: the gate marches the segment itself, in
# Python, over the solid cells dumped from the map, and compares against the
# sightings the bots actually recorded. If CheckLine ever leaks, or somebody
# replaces it with a renderer visibility mark, this notices.
#
# Renderer independence is checked by running the same match under software and
# OpenGL and requiring byte-identical perception. A bot's knowledge must not
# depend on what is being drawn, or whether anything is drawn at all -- a
# dedicated server draws nothing, and a bot that can only see what the console
# player's camera has visited is a bot that behaves differently on a machine
# with no screen.
#
# And the whole thing is guarded by a count: a run in which nothing was ever
# seen would pass every check above without testing anything.
#
# Usage: test_bot_perception.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-percept.XXXXXX)
. "$here/xvfb_common.sh"

display=:199
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

tics=1400
maps=${MAPS:-"MAP53 MAP51 MAP60"}

run() {  # run MAP TAG RENDERER
	mkdir -p "$work/$2-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer "$3" \
		--config "$work/$2.cfg" --savedir "$work/$2-saves" \
		--capture-rngseed 1 \
		--capture-perception "$work/$2.see" \
		--capture-bots "$work/$2.bots" \
		--capture-nav "$work/$2.nav" \
		--capture-maxtics "$tics" \
		--tedlevel "$1" --skill 2 --battle --bots 3 ) >"$work/$2.log" 2>&1 || true
}

printf 'Bots see what a player standing there would see\n'

for map in $maps; do
	run "$map" a software
	if [ ! -s "$work/a.see" ] || [ ! -s "$work/a.nav" ]; then
		printf '  FAIL %s: no perception trace\n' "$map"
		sed 's/\x08//g' "$work/a.log" | grep -vE '^\s*$' | tail -3 | sed 's/^/         /'
		status=1
		continue
	fi

	python3 - "$work/a.see" "$work/a.nav" "$map" <<'PY'
import sys

trace, nav, mapname = sys.argv[1], sys.argv[2], sys.argv[3]

solid = set()
for line in open(nav):
    f = line.split()
    if f and f[0] == "wall":
        solid.add((int(f[1]), int(f[2])))

sightings = []
for line in open(trace):
    f = line.split()
    # A sighting line begins with the tic. Everything else in this file --
    # sound, hazard, item, damage -- begins with its own keyword, so select by
    # shape rather than by listing the others: a parser that skips the
    # keywords it knows about breaks the day a new one is added, which is
    # exactly what happened when item lines arrived.
    if not f or not f[0].isdigit():
        continue
    # tic observer ox oy subject sx sy distance bearing offaxis
    sightings.append([int(v) for v in f])

problems = []

# The sight line, marched independently. Sampled finely and judged on how much
# of the line lies inside a wall rather than on whether it touches one: a line
# that clips the corner of a solid cell is what looking diagonally past a
# pillar looks like, and the engine allows it. A line that spends real length
# inside one is seeing through a wall.
UNITS = 64.0            # map units to the tile

def blocked(ox, oy, sx, sy):
    # Positions arrive in map units, so the tile a point is in is a floor
    # division and the line is the real one rather than a line between tile
    # indices. Endpoint tiles are excluded: the observer and the subject are
    # each standing in their own cell and neither is an obstruction.
    a = (int(ox // UNITS), int(oy // UNITS))
    b = (int(sx // UNITS), int(sy // UNITS))
    steps = 400
    inside = {}
    for i in range(1, steps):
        t = i / float(steps)
        x = (ox + (sx - ox) * t) / UNITS
        y = (oy + (sy - oy) * t) / UNITS
        cell = (int(x), int(y))
        if cell == a or cell == b:
            continue
        if cell not in solid:
            continue
        # How far inside the cell this sample is. A line can run along a wall's
        # face -- one sighting on MAP53 grazes a solid cell for a full tile of
        # travel while never more than 0.08 of a tile inside it -- and that is
        # looking along a surface, not through it. Only samples well inside the
        # cell count as penetration.
        fx, fy = x - cell[0], y - cell[1]
        depth = min(fx, 1.0 - fx, fy, 1.0 - fy)
        if depth >= 0.15:
            inside[cell] = inside.get(cell, 0) + 1
    return [c for c, n in inside.items() if n >= 8]

leaks = 0
worst = None
for f in sightings:
    tic, obs, ox, oy, sub, sx, sy = f[0], f[1], f[2], f[3], f[4], f[5], f[6]
    through = blocked(ox, oy, sx, sy)
    if through:
        leaks += 1
        if worst is None:
            worst = (tic, obs, (ox, oy), sub, (sx, sy), through[:3])

if leaks:
    problems.append("%d of %d sightings crossed a wall, e.g. %s"
                    % (leaks, len(sightings), worst))

# Nothing may be seen outside the field of view the profile declares.
wide = [f for f in sightings if f[9] > 45]
if wide:
    problems.append("%d sightings outside the 45 degree half-FOV, e.g. %s"
                    % (len(wide), wide[0]))

# And the run has to have seen something, or none of the above means anything.
if len(sightings) < 20:
    problems.append("only %d sightings recorded; nothing was really tested"
                    % len(sightings))

print("  ..   %s: %d sightings, %d crossed a wall, %d outside the view"
      % (mapname, len(sightings), leaks, len(wide)))
if problems:
    for p in problems:
        print("  FAIL %s: %s" % (mapname, p))
    sys.exit(1)
print("  ok   %s: every sighting had a clear line and was in view" % mapname)
PY
	[ $? -eq 0 ] || status=1
done

# Reaction time. Section 13.3 separates detection from action: the sensor sees,
# and the decision layer is told a fifth of a second later. Read straight off
# the trace, which records the delay it chose when it sighted something and the
# tic it actually released.
run MAP53 react software
python3 - "$work/react.bots" <<'PY'
import sys, re

sighted, noticed, lost = {}, [], []
for line in open(sys.argv[1]):
    f = line.split()
    if len(f) < 4 or f[0].startswith("#"):
        continue
    tic, slot, event = int(f[0]), f[1], f[2]
    who = re.search(r"slot=(\d+)", line)
    if not who:
        continue
    key = (slot, who.group(1))
    if event == "sighted":
        promised = int(re.search(r"in=(\d+)", line).group(1))
        sighted[key] = (tic, promised)
    elif event == "noticed":
        after = int(re.search(r"after=(\d+)", line).group(1))
        noticed.append((tic, key, after, sighted.get(key)))
    elif event == "lost":
        lost.append((tic, key))

problems = []
if not noticed:
    problems.append("nothing was ever noticed; the timing was not tested")

for tic, key, after, origin in noticed:
    if origin is None:
        problems.append("slot %s noticed %s having never sighted it" % key)
        break
    seen_at, promised = origin
    if after != promised:
        problems.append("delay was %d tics, not the %d it chose" % (after, promised))
        break
    if tic - seen_at != promised:
        problems.append("released %d tics after sighting, promised %d"
                        % (tic - seen_at, promised))
        break
    # 14 base plus a spread of 7, from g_bot.cpp.
    if not (14 <= after <= 20):
        problems.append("delay %d is outside the declared 14-20 tics" % after)
        break

# len(sighted) is the number of distinct (bot, subject) pairs, because the dict
# holds only the most recent sighting for each -- not the number of sighting
# events, which is larger. Said plainly here because "8 sightings, 17 released"
# reads as impossible otherwise.
print("  ..   reaction: %d contact pairs, %d releases, delays %s"
      % (len(sighted), len(noticed),
         sorted(set(a for _, _, a, _ in noticed)) if noticed else "none"))
if problems:
    for p in problems:
        print("  FAIL reaction: %s" % p)
    sys.exit(1)
print("  ok   reaction: nothing was known before it was seen, or sooner than promised")
PY
[ $? -eq 0 ] || status=1

# Hearing. Nothing in a bot match makes a noise yet -- bots have no weapons
# until B6 -- so the scripted player fires and the bots listen.
run_fire() {
	mkdir -p "$work/hear-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/hear.cfg" --savedir "$work/hear-saves" \
		--capture-rngseed 1 --capture-fire 100 \
		--capture-perception "$work/hear.see" \
		--capture-maxtics 600 \
		--tedlevel MAP53 --skill 2 --battle --bots 3 ) >"$work/hear.log" 2>&1 || true
}
run_fire
python3 - "$work/hear.see" <<'PY'
import sys

sounds, sights = [], set()
for line in open(sys.argv[1]):
    f = line.split()
    if not f or f[0].startswith("#"):
        continue
    if f[0] == "sound":
        # sound tic listener kind band N bearing B from S range R loud L
        sounds.append(dict(tic=int(f[1]), listener=f[2], kind=f[3],
                           band=int(f[5]), bearing=int(f[7]),
                           source=int(f[9]), rng=int(f[11]), loud=int(f[13])))
    elif f[0].isdigit():
        sights.add((int(f[0]), f[1], f[4]))

problems = []
if len(sounds) < 10:
    problems.append("only %d sounds heard; hearing was not tested" % len(sounds))

# Nothing carries further than its loudness.
far = [s for s in sounds if s["rng"] > s["loud"]]
if far:
    problems.append("%d sounds heard beyond their radius, e.g. %s" % (len(far), far[0]))

# A bearing is a sector, not a direction. Sector centres are 22, 67, 112 ...
odd = [s for s in sounds if s["bearing"] % 45 != 22]
if odd:
    problems.append("%d bearings were not sector centres, e.g. %s"
                    % (len(odd), odd[0]["bearing"]))

# And a band, not a range: three values and no more.
bands = set(s["band"] for s in sounds)
if not bands <= {0, 1, 2}:
    problems.append("range bands outside 0-2: %s" % sorted(bands))

# The one that matters. A sound is attributed to a slot only when the listener
# can see that slot at that moment; hearing a gun does not tell you whose.
named = [s for s in sounds if s["source"] >= 0]
leaked = [s for s in named
          if (s["tic"], s["listener"], str(s["source"])) not in sights]
if leaked:
    problems.append("%d sounds named a source the listener could not see, e.g. %s"
                    % (len(leaked), leaked[0]))

print("  ..   hearing: %d sounds, %d named a source, bands %s"
      % (len(sounds), len(named), sorted(bands)))
if problems:
    for p in problems:
        print("  FAIL hearing: %s" % p)
    sys.exit(1)
print("  ok   hearing: heard within earshot, as a sector and a band, "
      "and named nobody it could not see")
PY
[ $? -eq 0 ] || status=1

# Laser barriers, which are invisible without the infrared visor and are the
# one thing here a bot could cheat at without ever looking odd -- it would
# simply stop walking into them.
#
# MAP51 has them; MAP53, MAP55 and MAP60 have none, so this runs on MAP51 or it
# tests nothing.
laser() {  # laser TAG [EXTRA...]
	tag=$1; shift
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed 1 \
		--capture-perception "$work/$tag.see" \
		--capture-maxtics 500 \
		--tedlevel MAP51 --skill 2 --battle --bots 3 "$@" ) >"$work/$tag.log" 2>&1 || true
}

laser blind
laser lit --capture-visor-all 3

blind_seen=$(awk '$1=="hazard" && $6=="seen"' "$work/blind.see" 2>/dev/null | wc -l)
lit_seen=$(awk '$1=="hazard" && $6=="seen"' "$work/lit.see" 2>/dev/null | wc -l)
printf '  ..   lasers: %s seen without the visor, %s with it\n' "$blind_seen" "$lit_seen"

check "the map has barriers, so this tests something" test "${lit_seen:-0}" -ge 20

# The rule, checked per observation rather than per run.
#
# "A bot with no visor sees no barriers" was a run-level claim and it expired
# the moment bots could turn the visor up themselves: a bot that walks into a
# barrier, works out it needs infrared and switches to it then sees them
# perfectly legitimately, and the run-level check called that a leak. What
# holds regardless of who is wearing what is that no single sighting ever
# happens outside infrared.
offmode=$(cat "$work/blind.see" "$work/lit.see" 2>/dev/null |
	awk '$1=="hazard" && $6=="seen" && $8!=3' | wc -l)
printf '  ..   lasers: %s sightings made outside infrared\n' "$offmode"
check "no barrier is ever seen except in infrared" test "${offmode:-1}" -eq 0

# And the honest way to find one in the dark: walk into it. Driven at a tile
# the lit run reported a barrier on, with no visor.
target=$(awk '$1=="hazard" && $6=="seen"{print $4" "$5; exit}' "$work/lit.see")
if [ -n "$target" ]; then
	tx=${target% *}; ty=${target#* }
	mkdir -p "$work/bump-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/bump.cfg" --savedir "$work/bump-saves" \
		--capture-rngseed 1 --capture-bot-goal "$tx" "$ty" \
		--capture-perception "$work/bump.see" \
		--capture-maxtics 900 \
		--tedlevel MAP51 --skill 2 --battle --bots 1 ) >"$work/bump.log" 2>&1 || true
	bumped=$(awk '$1=="hazard" && $6=="contact"' "$work/bump.see" 2>/dev/null | wc -l)
	blind_still=$(awk '$1=="hazard" && $6=="seen"' "$work/bump.see" 2>/dev/null | wc -l)
	printf '  ..   lasers: walked at (%s,%s) with no visor -- %s by contact, %s seen\n' \
		"$tx" "$ty" "$bumped" "$blind_still"
	check "walking into one in the dark is still a way to learn about it" \
		test "${bumped:-0}" -ge 1
	bumpoff=$(awk '$1=="hazard" && $6=="seen" && $8!=3' "$work/bump.see" | wc -l)
	check "and nothing was seen while the visor was off" test "${bumpoff:-1}" -eq 0

	# And then it does something about it. Section 16.7: the visor mode is
	# chosen from what is worth seeing, and reached by pressing the same zoom
	# button a player presses, burning the same charge.
	#
	# The causal chain is the check: bump into a barrier, learn one exists,
	# turn the visor up, start seeing them. A bot that had the visor on from
	# the start would show sightings with no contact before them, and a bot
	# that never turned it on would show contact and nothing after.
	pulses=$(sed -n 's/.*Capture: bots .*visor=\([0-9]*\).*/\1/p' "$work/bump.log" | tail -1)
	after=$(awk -v t="$(awk '$1=="hazard" && $6=="contact"{print $2; exit}' "$work/bump.see")" \
		'$1=="hazard" && $6=="seen" && $2 > t' "$work/bump.see" | wc -l)
	printf '  ..   lasers: %s zoom presses, %s barriers seen after the first contact\n' \
		"${pulses:-0}" "$after"
	check "it turned the visor up after learning it needed one" \
		test "${pulses:-0}" -ge 1
	check "and could then see what it could not see before" test "${after:-0}" -ge 1
fi

# The control: a map with no barriers gives no reason to spend the charge.
run MAP53 novisor software
novisor=$(sed -n 's/.*Capture: bots .*visor=\([0-9]*\).*/\1/p' "$work/novisor.log" | tail -1)
printf '  ..   lasers: %s zoom presses on a map with no barriers\n' "${novisor:-0}"
check "a bot with nothing to look for leaves the visor alone" \
	test "${novisor:-0}" -eq 0

# Item beliefs. Section 12.8: where a pickup spawns is map knowledge a player
# builds by playing an arena, and whether it is there right now is not. So a
# belief may only form about a place the bot could actually see at that moment,
# and the gate re-derives the sight line and the field of view itself rather
# than taking the engine's word.
#
# MAP60 has eleven pickups, which is why the item run uses it.
run MAP60 items software
python3 - "$work/items.see" "$work/items.nav" <<'PY'
import sys

trace, nav = sys.argv[1], sys.argv[2]
UNITS = 64.0

solid, spawns = set(), set()
for line in open(nav):
    f = line.split()
    if not f:
        continue
    if f[0] == "wall":
        solid.add((int(f[1]), int(f[2])))
    elif f[0] == "item":
        spawns.add((int(f[1]), int(f[2])))

def blocked(ox, oy, sx, sy):
    a = (int(ox // UNITS), int(oy // UNITS))
    b = (int(sx // UNITS), int(sy // UNITS))
    inside = {}
    steps = 400
    for i in range(1, steps):
        t = i / float(steps)
        x = (ox + (sx - ox) * t) / UNITS
        y = (oy + (sy - oy) * t) / UNITS
        cell = (int(x), int(y))
        if cell == a or cell == b or cell not in solid:
            continue
        fx, fy = x - cell[0], y - cell[1]
        if min(fx, 1.0 - fx, fy, 1.0 - fy) >= 0.15:
            inside[cell] = inside.get(cell, 0) + 1
    return [c for c, n in inside.items() if n >= 8]

beliefs, problems = [], []
for line in open(trace):
    f = line.split()
    if not f or f[0] != "item":
        continue
    # item tic slot ox oy tx ty category state off N
    beliefs.append(dict(tic=int(f[1]), slot=f[2], ox=int(f[3]), oy=int(f[4]),
                        tx=int(f[5]), ty=int(f[6]), cat=f[7], state=f[8],
                        off=int(f[10])))

if len(beliefs) < 4:
    problems.append("only %d beliefs formed; this tested nothing" % len(beliefs))

# Every belief is about a place the map actually puts something.
stray = [b for b in beliefs if (b["tx"], b["ty"]) not in spawns]
if stray:
    problems.append("%d beliefs about a tile with no pickup spawn, e.g. %s"
                    % (len(stray), stray[0]))

# And about a place the bot could see: in view, and with a clear line.
wide = [b for b in beliefs if b["off"] > 45]
if wide:
    problems.append("%d beliefs formed outside the field of view, e.g. %s"
                    % (len(wide), wide[0]))

through = [b for b in beliefs
           if blocked(b["ox"], b["oy"], b["tx"] * 64 + 32, b["ty"] * 64 + 32)]
if through:
    problems.append("%d beliefs formed through a wall, e.g. %s"
                    % (len(through), through[0]))

print("  ..   items: %d spawns annotated, %d beliefs, %s outside view, %s through walls"
      % (len(spawns), len(beliefs), len(wide), len(through)))
if problems:
    for p in problems:
        print("  FAIL items: %s" % p)
    sys.exit(1)
print("  ok   items: every belief was about somewhere the bot could actually see")
PY
[ $? -eq 0 ] || status=1

# Damage cues, and memory that ages.
#
# Corridor 7 shows a screen-wide red flash with no direction in it, so a hit
# tells a bot how much and what is left, and never where it came from. The
# attacker's identity is allowed only when the victim could already see them --
# the same rule as sound attribution, and checked the same way.
#
# The laser run above provides the damage: walking into a barrier costs ten
# points and has no attacker at all.
if [ -s "$work/bump.see" ]; then
	python3 - "$work/bump.see" <<'PY'
import sys
cues, sights = [], set()
for line in open(sys.argv[1]):
    f = line.split()
    if not f or f[0].startswith("#"):
        continue
    if f[0] == "damage":
        cues.append(dict(tic=int(f[1]), victim=f[2], points=int(f[4]),
                         left=int(f[6]), attacker=int(f[8])))
    elif f[0].isdigit():
        sights.add((int(f[0]), f[1], f[4]))

problems = []
if not cues:
    problems.append("nothing was hurt; damage cues were not tested")
named = [c for c in cues if c["attacker"] >= 0]
leaked = [c for c in named
          if (c["tic"], c["victim"], str(c["attacker"])) not in sights]
if leaked:
    problems.append("%d cues named an attacker the victim could not see, e.g. %s"
                    % (len(leaked), leaked[0]))
odd = [c for c in cues if c["points"] <= 0]
if odd:
    problems.append("a cue reported %d points" % odd[0]["points"])

print("  ..   damage: %d cues, %d named an attacker" % (len(cues), len(named)))
if problems:
    for p in problems:
        print("  FAIL damage: %s" % p)
    sys.exit(1)
print("  ok   damage: told how much and what was left, and nothing it could not see")
PY
	[ $? -eq 0 ] || status=1
fi

# Searching and forgetting: the last two verbs in the milestone's exit line.
run MAP53 mem software
python3 - "$work/mem.bots" <<'PY'
import sys, re

events = []
for line in open(sys.argv[1]):
    f = line.split()
    if len(f) < 3 or f[0].startswith("#"):
        continue
    who = re.search(r"slot=(\d+)", line)
    events.append((int(f[0]), f[1], f[2], who.group(1) if who else None, line))

noticed = set()
searches, forgets = [], []
lost_at = {}
problems = []

for tic, bot, ev, who, line in events:
    key = (bot, who)
    if ev == "noticed":
        noticed.add(key)
    elif ev == "lost":
        lost_at[key] = tic
    elif ev == "searching":
        # A bot only goes looking for somebody it was actually told about.
        if key not in noticed:
            problems.append("bot %s searched for %s it never noticed" % key)
            break
        searches.append((tic, key))
    elif ev == "forgot":
        after = int(re.search(r"after=(\d+)", line).group(1))
        # 350 tics, from FORGET_TICS in g_bot.cpp.
        if after < 350:
            problems.append("forgot after %d tics, sooner than the 350 declared" % after)
            break
        forgets.append((tic, key, after))

if not searches:
    problems.append("nobody went looking; searching was not tested")
if not forgets:
    problems.append("nothing was forgotten; memory ageing was not tested")

print("  ..   memory: %d searches, %d forgotten, ages %s"
      % (len(searches), len(forgets),
         sorted(set(a for _, _, a in forgets)) if forgets else "none"))
if problems:
    for p in problems:
        print("  FAIL memory: %s" % p)
    sys.exit(1)
print("  ok   memory: looked where it last saw them, and gave up on time")
PY
[ $? -eq 0 ] || status=1

# The same match, drawn two different ways, and drawn not at all as far as the
# bots are concerned.
run MAP53 sw software
run MAP53 gl opengl
if [ -s "$work/gl.see" ]; then
	check "the renderer does not change what a bot perceives" \
		cmp -s "$work/sw.see" "$work/gl.see"
else
	printf '  ..   OpenGL run produced nothing; skipping the renderer check\n'
fi

if [ "$status" -eq 0 ]; then
	printf 'PASS: bots see only what is really in front of them.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
