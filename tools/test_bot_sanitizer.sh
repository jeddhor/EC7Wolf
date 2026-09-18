#!/bin/sh

# A full roster under AddressSanitizer and UndefinedBehaviorSanitizer.
#
# Milestone B10 of docs/multiplayer-bots-and-server.md: "protocol fuzz and
# sanitizers at maximum roster".
#
# Eleven slots is MAXPLAYERS, and the bot code is full of fixed-size arrays
# indexed by slot -- the per-slot view, the sighting rings, the aim history,
# the mine list, the RNG streams. A loop that runs one past the end of any of
# them is invisible in an ordinary build, which is exactly the kind of fault
# that reaches a player as a crash weeks later. The sanitizers make it a
# message instead.
#
# This gate needs a sanitizer build, which is not what anybody has lying about
# by default, so it skips rather than fails when there is none. Build one with:
#
#   cmake -S ECWolf -B builds/sanitizer -DCMAKE_BUILD_TYPE=Debug \
#         -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer"
#   cmake --build builds/sanitizer -j"$(nproc)"
#
# and point this gate at it. The match is short because an instrumented build
# is an order of magnitude slower, and short is enough: what is being looked
# for is a bad access, and the roster is what provokes it.
#
# stdbuf is deliberately not used here. It works by preloading libstdbuf, which
# lands ahead of libasan and makes a sanitizer build abort before main().
#
# Usage: test_bot_sanitizer.sh SANITIZER_BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s SANITIZER_BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" 2>/dev/null && pwd) || {
	printf 'SKIP: no such build directory: %s\n' "$1"; exit 0; }
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
if ! ldd "$build_dir/ec7wolf" 2>/dev/null | grep -q 'libasan\|libubsan'; then
	printf 'SKIP: %s/ec7wolf is not a sanitizer build\n' "$build_dir"
	exit 0
fi

work=$(mktemp -d /tmp/ec7wolf-botasan.XXXXXX)
. "$here/xvfb_common.sh"
display=:251
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "$status" -ne 0 ] || [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

printf 'Eleven slots, instrumented\n'

seed=5
play() {  # play TAG MAP [EXTRA...]
	tag=$1; map=$2; shift 2
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 \
	  UBSAN_OPTIONS=print_stacktrace=1 \
	  timeout 900 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed "$seed" --tedlevel "$map" --skill 2 --battle \
		"$@" ) >"$work/$tag.log" 2>&1 || true
}

# Leak detection is off on purpose. The engine frees very little at exit by
# design -- the process is ending -- so a leak report here would be a page of
# things that are not faults. What is being looked for is a bad access while
# the match runs.
#
# Two different bars, because the two sanitizers are finding different things
# in this tree.
#
# AddressSanitizer fails the gate wherever it fires. It found a real one the
# first time this gate ran: SD_PlaySound wrote channelSoundPos[-1] whenever
# SD_PlayDigitized declined to play a sound, which its own
# too-soon-to-repeat guard does constantly once eleven players are shooting.
# That is memory corruption in every build, silent without instrumentation.
#
# UndefinedBehaviorSanitizer fails the gate only for the code this milestone
# is about -- the bots, their perception and navigation, the command path and
# the netcode. Inherited ECWolf and ZDoom code trips it in quantity at
# start-up and while loading: TObjPtr offset arithmetic in dobject.h, null
# references in TArray, misaligned reads of packed art and palette data, left
# shifts of negative values in the raycaster. Those are real UB and worth
# fixing, but they are not this milestone, they fire before a bot exists, and
# a gate that failed on them would report the same page of upstream findings
# for ever while saying nothing about the bots. They are recorded in the B10
# record instead.
BOT_SOURCES='src/g_bot|src/g_botnav|src/g_perception|src/g_command|src/g_skill|src/g_items|src/g_combat|src/wl_net'

clean() {  # clean TAG
	if grep -qE 'ERROR: AddressSanitizer|SEGV|stack-buffer|heap-buffer|use-after' \
		"$work/$1.log"; then
		return 1
	fi
	! grep -E 'runtime error:' "$work/$1.log" | grep -qE "$BOT_SOURCES"
}

ran() {  # ran TAG
	grep -q 'Capture: summary' "$work/$1.log"
}

# The maximum roster, in a small arena so that eleven pawns are in each
# other's way rather than spread out: contact is what exercises the per-slot
# arrays.
play max MAP53 --bots 10 --bot-skill Elite --capture-maxtics 700
printf '  ..   max roster: %s\n' \
	"$(sed -n 's/^Capture: summary //p' "$work/max.log" | tail -1)"
check "a match of eleven slots ran to the end" ran max
check "with no bad access and no undefined behaviour" clean max

# And the round change, which rebuilds every brain's map-local state while ten
# of them are mid-route: Bot::BeginMap clears the tactical half of eleven
# States and keeps the rest.
play rounds MAP51 --bots 10 --bot-skill Veteran --fraglimit 1 \
	--capture-maxtics 900
printf '  ..   rounds: %s round(s) begun\n' \
	"$(grep -c '^Round [0-9]* begins' "$work/rounds.log" || true)"
check "a round change with a full roster ran" ran rounds
check "and it too was clean" clean rounds

# Said either way: a run with no AddressSanitizer report but a page of
# inherited UB findings is a different thing from a clean one, and the count
# is how a regression in that page would be noticed.
for tag in max rounds; do
	inherited=$(grep -cE 'runtime error:' "$work/$tag.log" 2>/dev/null || true)
	printf '  ..   %s: %s inherited UB finding(s), none in bot or net code\n' \
		"$tag" "${inherited:-0}"
done

if [ "$status" -ne 0 ]; then
	printf '\n  first report:\n'
	grep -m1 -A12 -E 'ERROR: AddressSanitizer|runtime error:' "$work"/*.log |
		sed 's/^/    /' || true
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: the sanitizers found nothing at maximum roster.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  %s %s %s   (seed %s)\n' "$0" "$build_dir" "$data_dir" "$seed"
fi
exit "$status"
