#!/bin/sh

# Regression test: bots play every shipped arena, on more than one seed, and
# none of them ends the match.
#
# Milestone B3 of docs/multiplayer-bots-and-server.md. This is the milestone's
# exit criterion: all eight arena traversal tests pass over multiple seeds and
# spawns, no permanent stuck state, and battle exit switches are never
# activated.
#
# Three things are worth explaining.
#
# The exit check. Every arena has an Exit_Normal switch -- MAP51 at (47,60),
# MAP53 has two -- and each is playerUse on a wall tile, so pressing use while
# facing one ends the match for everybody. Bots press use in exactly two
# places: at a door they are opening, and while dead asking to respawn. Neither
# can reach a switch today (a dead player never runs Cmd_Use, and the door
# protocol only presses while square-on to a door), but "cannot today" is not a
# property, it is an accident of what the bot currently does. A run that ends
# early ended because something activated the exit, so a match that reaches its
# full tic count is the check.
#
# Connectivity is measured as the share of cells in the largest region, not as
# "one region". MAP55 is in five pieces and always will be: four of them are
# sealed decorative alcoves behind masked walls, 35 cells out of 1005, that no
# player can reach either. Demanding one region would fail a correct map.
#
# Permanent stuck is checked as refusals and coverage together. A bot that
# stops moving keeps its route and reports refusals; a bot that shuffles on the
# spot reports none and covers no ground. Neither alone is conclusive.
#
# Usage: test_bot_arenas.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-arenas.XXXXXX)
. "$here/xvfb_common.sh"

display=:198
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

tics=900
maps=${MAPS:-"MAP51 MAP52 MAP53 MAP54 MAP55 MAP56 MAP57 MAP60"}
seeds=${SEEDS:-"1 7"}

run() {  # run MAP SEED TAG
	mkdir -p "$work/$3-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$3.cfg" --savedir "$work/$3-saves" \
		--capture-rngseed "$2" \
		--capture-nav "$work/$3.nav" \
		--capture-bots "$work/$3.bots" \
		--capture-players "$work/$3.players" \
		--capture-maxtics "$tics" \
		--tedlevel "$1" --skill 2 --battle --bots 3 ) >"$work/$3.log" 2>&1 || true
}

field() {  # field TAG KEY
	sed -n "s/.*Capture: bots .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" | tail -1
}

printf 'Every arena, more than one seed\n'

for map in $maps; do
	for seed in $seeds; do
		tag="$map-$seed"
		run "$map" "$seed" "$tag"
		if [ ! -s "$work/$tag.bots" ]; then
			printf '  FAIL %s seed %s: no bot trace\n' "$map" "$seed"
			sed 's/\x08//g' "$work/$tag.log" | grep -vE '^\s*$' | tail -3 |
				sed 's/^/         /'
			status=1
			continue
		fi

		ran=$(sed -n 's/.*summary tics=\([0-9]*\) .*/\1/p' "$work/$tag.log" | tail -1)
		planned=$(field "$tag" planned)
		arrived=$(field "$tag" arrived)
		refused=$(field "$tag" refused)
		nogoal=$(field "$tag" nogoal)
		tiles=$(awk 'NR>1 && $2!=0 {print $2":"$3":"$4}' "$work/$tag.players" |
			sort -u | wc -l)
		nodes=$(sed -n 's/^# nav nodes \([0-9]*\).*/\1/p' "$work/$tag.nav")
		largest=$(sed -n 's/^# nav .*largest \([0-9]*\).*/\1/p' "$work/$tag.nav")
		share=0
		[ "${nodes:-0}" -gt 0 ] && share=$(( ${largest:-0} * 100 / nodes ))

		printf '  ..   %s/%s: %s tics, planned %s, arrived %s, refused %s, nogoal %s, %s tiles, %s%% connected\n' \
			"$map" "$seed" "${ran:-?}" "${planned:-?}" "${arrived:-?}" \
			"${refused:-?}" "${nogoal:-?}" "$tiles" "$share"

		# The exit switch. A short match is a match somebody ended.
		check "$map/$seed: the match ran its full length, so no exit was used" \
			test "${ran:-0}" -ge "$tics"
		check "$map/$seed: the arena hangs together" test "$share" -ge 90
		check "$map/$seed: bots planned routes" test "${planned:-0}" -ge 2
		check "$map/$seed: and reached somewhere" test "${arrived:-0}" -ge 1
		check "$map/$seed: the world refused no step the graph offered" \
			test "${refused:-0}" -eq 0
		# Three bots over 900 tics on a 500-plus cell arena. A number this low
		# means they are shuffling on the spot rather than going anywhere.
		check "$map/$seed: and covered ground rather than milling about" \
			test "$tiles" -ge 40

		# B5's last exit clause: item navigation must not replan without bound.
		#
		# Every route a bot commits to is one line in the trace, so the count
		# is the number of times it changed its mind about where to go. Three
		# bots deciding afresh every tic for 900 tics would be 2700; a bot that
		# finishes what it starts is nearer thirty. The bound is deliberately
		# loose -- this is a check against runaway, not a performance target --
		# and it is per match rather than per bot because a single bot stuck in
		# a replan loop is exactly what it should catch.
		routes=$(grep -c ' route ' "$work/$tag.bots" || true)
		printf '  ..   %s/%s: %s routes committed to\n' "$map" "$seed" "$routes"
		check "$map/$seed: it replanned a bounded number of times" \
			test "${routes:-0}" -le 150
	done
done

if [ "$status" -eq 0 ]; then
	printf 'PASS: every arena is played, and no bot ends the match.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
