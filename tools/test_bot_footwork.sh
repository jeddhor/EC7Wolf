#!/bin/sh

# Regression test: a bot that is being shot at moves, and the better it is the
# more it moves.
#
# Sections 17.5 and 17.6. Three separate faults live behind this gate, and all
# three were found by a playtest rather than by the suite, which is why the
# suite now has it.
#
# 1. Damage never reached a brain at all. Perception::NoteDamage files a cue in
#    the middle of a tic; BeginFrame rebuilds every observation from scratch at
#    the top of the next one. The cue was therefore written on every hit and
#    read on none -- the list had a producer, a consumer, and a wipe in between
#    them. Sounds are double-buffered for exactly this reason and damage was
#    not. The dodge counter is the read end of that path, so a zero here means
#    the buffering has regressed and a bot has gone deaf to being shot.
#
# 2. A strafe that walks into a wall was still a strafe. The side is chosen at
#    random and held for a commitment interval, so a bot that picked the side
#    with a wall on it leaned on that wall for up to two seconds, asking to
#    move the whole time and going nowhere. That is most of what a playtest
#    described as bots standing around. The reversal counter is the footwork
#    noticing it.
#
# 3. The skill ladder did not reach the fight. Every level strafed the same
#    way, so "Elite" meant a better aim attached to identical feet.
#
# The condition is forced rather than waited for. Corridor 7's guns average a
# hundred and twenty-eight points at close range against a hundred of health,
# so a bot that is hit is usually killed rather than wounded: eight
# bot-versus-bot matches produced one non-fatal hit on a bot that was holding a
# target, which is a gate measuring the weather. --capture-graze-slot takes six
# points at a time from a bot that is fighting and never takes it low enough to
# retreat, which is what a human with a machine gun does to it constantly.
#
# The ladder is pooled across seeds and stated as a gap between the ends rather
# than as an ordering of adjacent levels, for the reason test_bot_skill.sh
# gives: neighbours can cross on three seeds without anything being wrong.
#
# Usage: test_bot_footwork.sh BUILD_DIR DATA_DIR

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

printf 'Being shot at is a reason to move\n'

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-footwork.XXXXXX)
. "$here/xvfb_common.sh"
display=:219
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

seeds="1 5 9"

for skill in Recruit Elite; do
	for seed in $seeds; do
		mkdir -p "$work/$skill-$seed-sv"
		( cd "$data_dir"
		  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
			--vid-renderer software \
			--config "$work/$skill-$seed.cfg" \
			--savedir "$work/$skill-$seed-sv" \
			--capture-rngseed "$seed" --bot-skill "$skill" \
			--capture-graze-slot 1 200 14 \
			--capture-maxtics 2100 \
			--tedlevel MAP60 --skill 2 --battle --bots 3 ) \
			>"$work/$skill-$seed.log" 2>&1 || true
	done
done

# Summed from the engine's own end-of-run tally rather than inferred from
# anything: these two counters exist so that footwork is a number.
total() {	# total SKILL COUNTER
	sum=0
	for seed in $seeds; do
		log="$work/$1-$seed.log"
		[ -f "$log" ] || continue
		line=$(grep "Capture: bots " "$log" 2>/dev/null | tail -1) || true
		[ -n "$line" ] || continue
		v=$(printf '%s\n' "$line" | tr ' ' '\n' | sed -n "s/^$2=//p" | tail -1)
		[ -n "$v" ] || v=0
		sum=$((sum + v))
	done
	printf '%s\n' "$sum"
}

recruitDodges=$(total Recruit dodges)
eliteDodges=$(total Elite dodges)
recruitRev=$(total Recruit reversals)
eliteRev=$(total Elite reversals)

printf '  Recruit  dodges=%s reversals=%s\n' "$recruitDodges" "$recruitRev"
printf '  Elite    dodges=%s reversals=%s\n' "$eliteDodges" "$eliteRev"

# The regression guard for the wiped damage cue. Before it was fixed this was
# exactly zero at every level and in every seed, because it could not be
# anything else.
check "a bot that is shot at answers with its feet" \
	test "$eliteDodges" -gt 0

# Not "more than Recruit" by a hair: the bands are 10-30 against 85-100 and the
# rest between reactions scales with the same trait, so the gap is large or
# something has stopped reading the trait.
check "and a better fighter answers far more often than a worse one" \
	test "$eliteDodges" -ge "$((recruitDodges * 2 + 2))"

# Reversals prove the other half: a strafe that is not moving the body gets
# turned round rather than held. Checked at both ends because it is not a skill
# behaviour -- every bot should stop leaning on walls.
check "a blocked strafe turns round (Recruit)" test "$recruitRev" -gt 0
check "a blocked strafe turns round (Elite)" test "$eliteRev" -gt 0

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: footwork is real and it is on the skill ladder.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
