#!/bin/sh

# Regression test: the skill ladder is real, and the top of it is still beatable.
#
# Milestone B8 of docs/multiplayer-bots-and-server.md, sections 17.1 to 17.6.
#
# Two kinds of check here, and the difference matters.
#
# The hard ones are bounds, and they are measured from the recorded pawn rather
# than from anything the bot says about itself. A bot that wrote "I turned three
# degrees" while turning thirty would pass a counter and fail this: the angle
# column in the players file is what the world did. Section 17.5's ceiling is
# only worth having if it is checked against the world.
#
# The soft one is the ladder itself. Skill progression has to be *perceptible*
# (B8's exit) and that is a statistical claim about a distribution, so it is
# pooled across seeds and stated as a gap rather than as an ordering of
# adjacent levels -- two neighbouring levels can cross on three seeds without
# anything being wrong, and a gate that forbids it would be measuring the seed.
#
# Usage: test_bot_skill.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

printf 'A ladder of opponents, none of them perfect\n'

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-skill.XXXXXX)
. "$here/xvfb_common.sh"
display=:207
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

map=MAP60
tics=2100
seeds="1 5 9"

run() {  # run SKILL SEED TAG [EXTRA...]
	skill=$1; seed=$2; tag=$3; shift 3
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed "$seed" \
		--bot-skill "$skill" \
		--capture-bots "$work/$tag.bots" \
		--capture-players "$work/$tag.players" \
		--capture-maxtics "$tics" \
		--tedlevel "$map" --skill 2 --battle --bots 3 "$@" ) \
		>"$work/$tag.log" 2>&1 || true
}

field() {  # field TAG NAME
	sed -n "s/.*Capture: bots .*$2=\([0-9]*\).*/\1/p" "$work/$1.log" | tail -1
}

# --- the ladder --------------------------------------------------------------

levels="Recruit Marine Veteran Elite"
for skill in $levels; do
	hit=0; shots=0
	for seed in $seeds; do
		run "$skill" "$seed" "$skill-$seed"
		h=$(field "$skill-$seed" oncone); s=$(field "$skill-$seed" hitscan)
		hit=$((hit + ${h:-0})); shots=$((shots + ${s:-0}))
	done
	acc=0
	[ "$shots" -gt 0 ] && acc=$((hit * 100 / shots))
	printf '  ..   %-7s %s of %s hitscan shots on target (%s%%)\n' \
		"$skill" "$hit" "$shots" "$acc"
	eval "acc_$skill=$acc"
	eval "shots_$skill=$shots"
	check "$skill: fired enough shots to say anything" test "$shots" -ge 10
done

# Section 17.5: no 100% in a sufficiently large contested test. Stated per
# level, because it is the *top* of the ladder that the rule exists for and
# checking only the pooled figure would let Elite hide behind Recruit.
for skill in $levels; do
	eval "a=\$acc_$skill"
	check "$skill: is not perfect ($a%)" test "$a" -lt 100
done

# Assigned through eval, so they are declared here as well: shellcheck cannot
# see an eval assignment and the names gate treats its warnings as errors.
low=0
high=0
eval "low=\$acc_Recruit"
eval "high=\$acc_Elite"
printf '  ..   ladder: Recruit %s%% to Elite %s%%, a gap of %s points\n' \
	"$low" "$high" "$((high - low))"
check "the ladder is perceptible from one end to the other" \
	test "$((high - low))" -ge 8
check "and the top of it is still beatable" test "$high" -le 90

# --- the motor ceiling, measured from the pawn -------------------------------
#
# Not from a counter. The angle column is what the body did.

printf '  ..   turn rates, measured from the recorded pawn angle\n'
yaw_ok=1
for skill in $levels; do
	if python3 - "$work/$skill-1.bots" "$work/$skill-1.players" "$skill" <<'PY'
import sys, re

trace, players, skill = sys.argv[1], sys.argv[2], sys.argv[3]

# What each bot said it was allowed to do.
allowed = {}
for line in open(trace):
    if " configure " not in line:
        continue
    slot = line.split()[1]
    m = re.search(r"yaw=(\d+)", line)
    if m:
        # Command units are a twentieth of a degree a tic (ControlMovement).
        allowed[slot] = int(m.group(1)) / 20.0

rows = []
for line in open(players):
    f = line.split()
    if not f or f[0].startswith("#"):
        continue
    rows.append((int(f[0]), f[1], float(f[4]), int(f[5]), int(f[10]), int(f[11])))

worst, prev = {}, {}
for tic, slot, angle, health, x, y in rows:
    if slot in prev:
        pa, ph, px, py = prev[slot]
        # A respawn puts the body somewhere else facing somewhere else, and
        # that is not a turn. Skipped on the evidence rather than on the tic
        # count: health going up, or the body moving further in one tic than
        # it could possibly walk.
        teleported = health > ph or (x - px) ** 2 + (y - py) ** 2 > 1 << 30
        if not teleported and health > 0 and ph > 0:
            d = abs((angle - pa + 180.0) % 360.0 - 180.0)
            if d > worst.get(slot, 0.0):
                worst[slot] = d
    prev[slot] = (angle, health, x, y)

problems = []
for slot, d in sorted(worst.items()):
    cap = allowed.get(slot)
    if cap is None:
        continue
    # The players file records whole degrees, so a 3.35 degree turn is written
    # down as 3 or 4. One degree of rounding, and not a tolerance on the rule.
    if d > cap + 1.0:
        problems.append("slot %s turned %.1f deg/tic, allowed %.2f" % (slot, d, cap))

print("  ..   %-7s fastest turn %s (allowed %s)"
      % (skill,
         ", ".join("%.0f" % d for _, d in sorted(worst.items())) or "none",
         ", ".join("%.2f" % c for _, c in sorted(allowed.items())) or "none"))
if not worst:
    problems.append("no bot turned at all; the ceiling was not tested")
for p in problems:
    print("  FAIL %s: %s" % (skill, p))
sys.exit(1 if problems else 0)
PY
	then :; else yaw_ok=0; fi
done
check "no bot ever turned faster than its level allows" test "$yaw_ok" -eq 1

# --- the developer profile is refused ----------------------------------------

run Perfect 1 refused
grep -q "Unknown or unavailable bot skill" "$work/refused.log" && refused=1 || refused=0
ran_as=$(grep -o "skill=[A-Za-z]*" "$work/refused.bots" | head -1)
printf '  ..   asked for Perfect without the opt-in: refused=%s, ran as %s\n' \
	"$refused" "${ran_as:-none}"
check "Perfect is refused in an ordinary match" test "$refused" -eq 1
check "and the match runs at an ordinary level instead" \
	test "${ran_as:-}" = "skill=Marine"

# --- reproducibility ---------------------------------------------------------

run Veteran 1 repeat
a=$(sed -n 's/.*Capture: bots .*brain=\([0-9a-f]*\).*/\1/p' "$work/Veteran-1.log" | tail -1)
b=$(sed -n 's/.*Capture: bots .*brain=\([0-9a-f]*\).*/\1/p' "$work/repeat.log" | tail -1)
printf '  ..   brain digests %s and %s\n' "${a:-?}" "${b:-?}"
check "one seed and one skill think the same thoughts twice" \
	test -n "${a:-}" -a "${a:-x}" = "${b:-y}"

if [ "$status" -eq 0 ]; then
	printf 'PASS: skill is a ladder, and nobody is at the top of it.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
