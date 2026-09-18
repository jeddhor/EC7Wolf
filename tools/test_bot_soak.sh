#!/bin/sh

# Soak: a full roster, every arena, one match, and nothing coming apart.
#
# Milestone B10 of docs/multiplayer-bots-and-server.md: "per-change and
# release-duration soak on all arenas", and the memory half of "CPU and memory
# budgets measured and met".
#
# The other bot gates each hold one behaviour still and look at it. This one
# asks a different question: does an hour of this break anything? So it is the
# longest match the suite runs -- eleven slots, which is MAXPLAYERS, walking
# all eight arenas in one go -- and it asserts the things that only show up
# over time:
#
#   * it survives, without an assertion, an abort, or a sanitizer report;
#   * it keeps playing, rather than ending up with every bot stuck in a corner
#     -- routes are still being completed in the last arena, not only the first;
#   * every arena is actually reached, which the map cycle makes possible in
#     one process instead of eight;
#   * memory does not climb. Per-round allocation growth is exactly what a
#     rotation soak is for (section 34), and eight rounds of spawning,
#     killing and respawning eleven pawns is where it would show.
#
# Resident memory is sampled from /proc rather than measured inside the engine:
# an allocator that never returns pages to the OS is still a leak the player
# pays for, and the process is the honest place to see it.
#
# The rounds are ended by the time limit rather than by frags, so the run takes
# a predictable time instead of depending on how quickly somebody wins.
#
# Usage: test_bot_soak.sh BUILD_DIR DATA_DIR
#
# SOAK_MINUTES sets the per-round limit (default 1). The overnight rotation
# section 34 asks for is this gate with a larger one.

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

work=$(mktemp -d /tmp/ec7wolf-soak.XXXXXX)
. "$here/xvfb_common.sh"
display=:247
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${game:-}"
	xvfb_stop
	if [ "$status" -ne 0 ] || [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

seed=7
minutes=${SOAK_MINUTES:-1}
# Nine rounds: eight arenas and back round to the first, so the wrap is soaked
# too. One minute is 4200 tics, and the tally between rounds costs a few more.
rounds=9
maxtics=$((minutes * 4200 * rounds + 4000))

printf 'A full roster, every arena, one match\n'
printf '  ..   11 slots, %s rounds of %s minute(s), seed %s\n' \
	"$rounds" "$minutes" "$seed"

mkdir -p "$work/saves"
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  exec "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
	--vid-renderer software \
	--config "$work/soak.cfg" --savedir "$work/saves" \
	--capture-rngseed "$seed" --tedlevel MAP51 --skill 2 --battle \
	--bots 10 --bot-skill Veteran --timelimit "$minutes" --mapcycle \
	--capture-bots "$work/soak.bots" \
	--capture-maxtics "$maxtics" ) >"$work/soak.log" 2>&1 &
game=$!

# Resident memory, sampled while it runs. The first sample is taken after the
# first round so that start-up allocation is not counted as growth.
: > "$work/rss"
settle=$((minutes * 60 + 20))
waited=0
while kill -0 "$game" 2>/dev/null; do
	if [ "$waited" -ge "$settle" ]; then
		awk '/^VmRSS:/ { print $2 }' "/proc/$game/status" 2>/dev/null >> "$work/rss" || true
	fi
	sleep 5
	waited=$((waited + 5))
done
wait "$game" 2>/dev/null || true
game=

first_rss=$(head -1 "$work/rss" 2>/dev/null || echo 0)
last_rss=$(tail -1 "$work/rss" 2>/dev/null || echo 0)
peak_rss=$(sort -n "$work/rss" 2>/dev/null | tail -1 || echo 0)
samples=$(wc -l < "$work/rss" 2>/dev/null || echo 0)
growth=$(( (last_rss - first_rss) / 1024 ))

maps=$(sed -n 's/^Round [0-9]* begins:.* map=\(MAP[0-9]*\)$/\1/p' "$work/soak.log" |
	sort -u | tr '\n' ' ' | sed 's/ $//')
distinct=$(printf '%s\n' "$maps" | wc -w)
begun=$(grep -c '^Round [0-9]* begins' "$work/soak.log" || true)
limits=$(grep -c 'The time limit was reached' "$work/soak.log" || true)

printf '  ..   %s round(s) begun, %s time limit(s), arenas seen: %s\n' \
	"$begun" "$limits" "${maps:-none}"
printf '  ..   resident memory: %s KB first sample, %s KB last, %s KB peak (%s samples)\n' \
	"$first_rss" "$last_rss" "$peak_rss" "$samples"
printf '  ..   %s\n' "$(sed -n 's/^Capture: bot cpu //p' "$work/soak.log" | tail -1)"

check "the match ran every round" test "${begun:-0}" -ge "$((rounds - 1))"
check "and each one ended on the clock" test "${limits:-0}" -ge "$((rounds - 1))"
check "all eight arenas were played" test "${distinct:-0}" -eq 8

check "it survived without an abort or a sanitizer report" \
	sh -c "! grep -qiE 'assertion|sanitizer|AddressSanitizer|runtime error|Segmentation|buffer overflow' '$work/soak.log'"

# Still playing at the end, not merely still running: routes completed in the
# last quarter of the trace prove the bots had not all ended up in corners.
late_arrivals=$(tail -n "$(( $(wc -l < "$work/soak.bots") / 4 + 1 ))" "$work/soak.bots" |
	grep -c ' arrived ' || true)
printf '  ..   routes completed in the last quarter of the match: %s\n' "$late_arrivals"
check "the bots were still getting places at the end" \
	test "${late_arrivals:-0}" -ge 5

# Sampled every five seconds over the whole run, so a climb would be visible as
# a difference between the first sample and the last. Sixty-four megabytes is
# far more than any real growth and far less than a leak per round would reach.
check "resident memory did not climb (${growth} MB)" \
	sh -c "test ${samples:-0} -ge 4 && test ${growth:-999} -lt 64"

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: a full roster played every arena without coming apart.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  SOAK_MINUTES=%s %s %s %s   (seed %s)\n' \
		"$minutes" "$0" "$build_dir" "$data_dir" "$seed"
fi
exit "$status"
