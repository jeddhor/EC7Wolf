#!/bin/sh

# Regression test: what the brains cost, against the tic they have to fit in.
#
# Milestone B10 of docs/multiplayer-bots-and-server.md: "CPU and memory budgets
# measured and met". Section 34 gives the budget -- at 70 Hz a tic is 14.286 ms
# for everything the game does, and the bots are one part of that. Section 34
# also says to take thresholds from real hardware rather than asserting a
# percentage, so these come from measurement:
#
#   roster   mean/tic   p95/tic   worst tic   worst once under way
#   1 bot       4-6us      50us     2.1-4.4ms        423us
#   2 bots      7-10us     50us     2.7-11.5ms       420us
#   8 bots     15-16us     50us     2.3-6.9ms        443us
#  10 bots     18-20us     50us     2.3-6.3ms        542us
#
# The last column barely moves with the roster while the mean triples, because
# it is one bot replanning a route rather than all of them thinking at once.
#
# That worst column looks alarming beside a mean of twenty microseconds, and it
# is entirely start-up: every bot plans its first route from a cold graph on
# the tic it starts thinking. Measured at 60, 400 and 2100 tics the worst is
# the same, so it happens inside the first sixty tics and never comes back.
#
# Which is why the engine reports two of them. `worst` includes that first
# planning tic and is bounded loosely, at three tics, because it is a one-off
# whose size depends on how busy the machine is -- across runs here, with
# nothing changed but load, two bots measured 2.7 ms and then 11.5 ms. `warmworst` ignores the
# first two seconds and is the one held to a tight bound: a brain that costs
# milliseconds in the middle of a match is dropping frames, and no amount of
# machine load explains that away.
#
# The mean and p95 thresholds are roughly two orders of magnitude above the
# measurement, so this gate reports a regression rather than the weather.
#
# Timing is measured by the engine around the brains themselves (Bot::Cost) and
# never reaches the simulation: a bot that behaved differently on a slow
# machine would be a desync, not a diagnostic.
#
# Usage: test_bot_budget.sh BUILD_DIR DATA_DIR

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

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-budget.XXXXXX)
. "$here/xvfb_common.sh"
display=:245
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	# Kept when the gate fails, not only when asked: B10 wants the seed and the
	# trace of a failure, and a run that has been deleted cannot be read.
	if [ "$status" -ne 0 ] || [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

TIC_MICROS=14286		# 70 Hz
MEAN_LIMIT=2000
P95_LIMIT=3000
# Start-up planning may cost more than one tic; nothing after it may.
START_LIMIT=$((TIC_MICROS * 3))
WARM_LIMIT=2000

seed=3
run() {  # run BOTS MAP
	tag="$1-$2"
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed "$seed" --tedlevel "$2" --skill 2 --battle \
		--bots "$1" --bot-skill Elite --capture-maxtics 2100 ) \
		>"$work/$tag.log" 2>&1 || true
	printf '  ..   %2s bots on %s: %s\n' "$1" "$2" \
		"$(sed -n 's/^Capture: bot cpu //p' "$work/$tag.log" | tail -1)"
}

field() {  # field TAG NAME -- microseconds, or -1 when the line is missing
	sed -n 's/^Capture: bot cpu .*/&/p' "$work/$1.log" | tail -1 |
		tr ' ' '\n' | sed -n "s/^$2=//p" | sed 's/us$//' | tail -1 |
		sed 's/^$/-1/'
}

printf 'What the brains cost, per tic\n'

# 10 bots plus the local player is 11 slots, which is MAXPLAYERS: the maximum
# roster the game can be asked to run.
for n in 1 2 8 10; do
	run "$n" MAP51
done
run 10 MAP60

for tag in 1-MAP51 2-MAP51 8-MAP51 10-MAP51 10-MAP60; do
	mean=$(field "$tag" mean)
	p95=$(field "$tag" p95)
	worst=$(field "$tag" worst)
	check "$tag: the brains were timed at all" test "${mean:--1}" -ge 0
	check "$tag: mean ${mean}us is inside the budget" \
		sh -c "test ${mean:--1} -ge 0 && test ${mean:--1} -lt $MEAN_LIMIT"
	check "$tag: 95th percentile ${p95}us is inside the budget" \
		sh -c "test ${p95:--1} -ge 0 && test ${p95:--1} -lt $P95_LIMIT"
	warm=$(field "$tag" warmworst)
	check "$tag: the worst tic ${worst}us is start-up, not a stall" \
		sh -c "test ${worst:--1} -ge 0 && test ${worst:--1} -lt $START_LIMIT"
	check "$tag: once under way the worst tic is ${warm}us" \
		sh -c "test ${warm:--1} -ge 0 && test ${warm:--1} -lt $WARM_LIMIT"
done

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: the brains fit the tic, at every roster size.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  %s %s %s   (seed %s)\n' "$0" "$build_dir" "$data_dir" "$seed"
fi
exit "$status"
