#!/bin/sh

# Regression test: you can watch what a bot is doing, and watching changes
# nothing.
#
# Milestone B2 of docs/multiplayer-bots-and-server.md: "graph, path, and state
# overlays and trace". The trace is a file; this is the part you look at.
# Debug key J cycles it, or --capture-bot-overlay LEVEL:
#
#   0  off
#   1  each bot's remaining route, dim behind the waypoint it has reached and
#      bright ahead of it, labelled with what the bot thinks it is doing
#   2  and the graph those routes were planned on
#
# The first check is the one that matters. A debug view that perturbs the thing
# it is showing is worse than no debug view: it sends you looking for a bug
# that only exists while you are looking. The overlay reads bot state through
# copies and draws; it holds no pointers into a brain and cannot write one. So
# the simulation checksum and the brain digest must be identical whether the
# overlay is off, on, or drawing the whole graph -- same seed, same tic count,
# same world.
#
# The rest checks it actually draws, because an overlay that renders nothing
# would pass the first check perfectly. Frames are compared at a fixed tic
# rather than a fixed frame number: drawing costs time, so the same frame index
# lands on different tics at different levels and would differ for reasons that
# have nothing to do with the overlay.
#
# Usage: test_bot_overlay.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-overlay.XXXXXX)
. "$here/xvfb_common.sh"

display=:196
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

map=MAP53
tics=320
# Snapshotted before anybody starts shooting.
#
# Once bots fight (B6) the console player gets hit, and the red damage flash
# decays with `damagecount -= tics` on every *frame* -- so its intensity at a
# given tic depends on how the tics fell across frames, and two runs of an
# identical simulation produce different pictures. That is a real property of
# the effect rather than a fault, and it is not what this gate is about.
#
# First contact in these matches is around tic 110. Routes exist from about
# tic 25, so ninety is comfortably after there is something to draw and before
# there is anything to flash.
shot_at=90

# A frame is only comparable between runs with interpolation off. The view is
# otherwise drawn part way between two tics, at a fraction that depends on how
# fast the frame arrived, so two identical runs snapshotted at the same tic
# produce different pixels -- which they did, and which made the three "it
# draws" checks below pass on a build with the drawing disabled entirely.
mkdir -p "$work/seed-saves"
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 120 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
	--vid-renderer software --config "$work/seed.cfg" \
	--savedir "$work/seed-saves" --capture-maxtics 5 \
	--tedlevel "$map" --skill 2 --battle ) >"$work/seed.log" 2>&1 || true
if ! grep -q 'R_Interpolate = 1;' "$work/seed.cfg" 2>/dev/null; then
	printf 'SKIP: could not find R_Interpolate in a fresh config\n'
	exit 0
fi
sed 's/R_Interpolate = 1;/R_Interpolate = 0;/' "$work/seed.cfg" > "$work/noint.cfg"

run() {  # run LEVEL   -- LEVEL of "off" means the flag is absent entirely
	mkdir -p "$work/$1-saves"
	if [ "$1" = "off" ]; then overlay=""
	else overlay="--capture-bot-overlay $1"; fi
	cp "$work/noint.cfg" "$work/$1.cfg"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 200 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$1.cfg" --savedir "$work/$1-saves" \
		--capture-rngseed 1 \
		$overlay \
		--capture-snapshot "$work/$1.png" "$shot_at" \
		--capture-maxtics "$tics" \
		--tedlevel "$map" --skill 2 --battle --bots 3 ) >"$work/$1.log" 2>&1 || true
}

world() { sed -n 's/.*summary .*checksum=\([0-9a-f]*\).*/\1/p' "$work/$1.log" | tail -1; }
brain() { sed -n 's/.*Capture: bots .*brain=\([0-9a-f]*\).*/\1/p' "$work/$1.log" | tail -1; }

printf 'Watching a bot, without disturbing it\n'

for level in off 0 1 2; do
	run "$level"
done

w=$(world off); b=$(brain off)
printf '  ..   world %s, brain %s with no overlay\n' "${w:-?}" "${b:-?}"
check "the run without an overlay produced a world at all" test -n "${w:-}" -a -n "${b:-}"

for level in 0 1 2; do
	printf '  ..   level %s: world %s, brain %s\n' \
		"$level" "$(world "$level")" "$(brain "$level")"
	check "level $level simulates the same world as no overlay" \
		test "$(world "$level")" = "${w:-x}"
	check "level $level thinks the same thoughts as no overlay" \
		test "$(brain "$level")" = "${b:-x}"
done

# And it draws. Same tic and no interpolation, so the frame is a function of
# the simulation alone and any difference is the overlay.
for level in 0 1 2; do
	check "level $level rendered a frame" test -s "$work/$level.png"
done

# The control, and the reason the rest of this section means anything: the same
# level twice is the same picture. Without it "the overlay drew something" and
# "frames are not reproducible" look identical, and it was the second.
cp "$work/1.png" "$work/1-again.png"
run 1
check "the same level twice renders the same frame" \
	test "$(md5sum < "$work/1-again.png")" = "$(md5sum < "$work/1.png")"
check "routes are visible where nothing was drawn before" \
	test -s "$work/1.png" -a -s "$work/0.png" \
	-a "$(md5sum < "$work/1.png")" != "$(md5sum < "$work/0.png")"
check "and the graph adds to them rather than replacing them" \
	test -s "$work/2.png" \
	-a "$(md5sum < "$work/2.png")" != "$(md5sum < "$work/1.png")"

if [ "$status" -eq 0 ]; then
	printf 'PASS: the overlay draws what the bots are doing and changes none of it.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
