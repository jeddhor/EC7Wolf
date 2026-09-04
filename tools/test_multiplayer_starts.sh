#!/bin/sh

# Regression test: every arena start is somewhere a player can leave.
#
# GameMap::GenerateDeathmatchStarts deals starting positions from the arena's
# floor, because the shipped arenas have one placed start apiece and the manual
# says positions are assigned randomly. A cell qualified as floor if it had a
# sector and no wall tile -- which says nothing at all about whether a player
# standing on it can walk anywhere.
#
# The arenas contain sealed floor: map-edge padding, closets, cells left
# floored and walled in. A start dealt from one strands whoever draws it for
# the whole match, standing still with the movement key held.
#
# Two players never saw it, because two players take the first two starts, and
# the arenas gate tests two players. The third one along is the one that ends
# up in the cupboard. So this runs three.
#
# Every player walks forward for the whole match. Every player has to end up
# somewhere other than where it started -- on all eight arenas, with the seed
# the starts are dealt from held fixed so a failure can be repeated.
#
# Usage: test_multiplayer_starts.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdpyinfo; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-starts.XXXXXX)
. "$here/xvfb_common.sh"

display=:182
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${p0:-}" "${p1:-}" "${p2:-}"
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
tics=220
# The arenas the menu offers. MAP58 and MAP59 are unused boxes; Network Level 8
# is MAP60.
arenas=${ARENAS:-"MAP51 MAP52 MAP53 MAP54 MAP55 MAP56 MAP57 MAP60"}

# Several seeds, because the starts are dealt from the seed and one seed only
# proves one deal. Two by default keeps the sweep to about nine minutes; set
# SEEDS to widen it when a map is under suspicion, and ARENAS to narrow it.
seeds=${SEEDS:-"1 4"}

# One player. Software rendering on purpose: this asks where a pawn stands,
# not what it looks like, and three GL contexts per combination across
# twenty-four combinations is a great deal of memory to allocate for a
# question about tile coordinates.
one() {   # one INDEX MAP SEED ROLE...
	idx=$1; map=$2; seed=$3
	shift 3
	mkdir -p "$work/p$idx-saves"
	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 90 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/p$idx.cfg" --savedir "$work/p$idx-saves" \
		--capture-rngseed "$seed" \
		--capture-players "$work/p$idx.players" \
		--capture-maxtics "$tics" --capture-forward 20 --capture-turn 20 \
		--tedlevel "$map" --skill 2 --battle --net-delay 6 \
		"$@" >"$work/p$idx.log" 2>&1 ) &
}

run() {   # run MAP SEED
	map=$1; seed=$2
	rm -f "$work"/p*.players "$work"/p*.log

	one 0 "$map" "$seed" --host 3 --port 5200
	p0=$!
	sleep 3
	one 1 "$map" "$seed" --port 5201 --join 127.0.0.1:5200
	p1=$!
	one 2 "$map" "$seed" --port 5202 --join 127.0.0.1:5200
	p2=$!

	wait "$p0" "$p1" "$p2" 2>/dev/null || true
	# Belt and braces. A host still waiting on a peer that died holds its
	# socket and its memory for the whole timeout, and twenty-four of those
	# overlapping is how a test run takes a desktop down with it.
	kill_pids "${p0:-}" "${p1:-}" "${p2:-}"
	p0=; p1=; p2=
}

# Every slot's start and finish, from the host's own trace so that one file
# answers for all three.
report() {  # report MAP SEED
	map=$1; seed=$2
	if [ ! -s "$work/p0.players" ]; then
		printf '  FAIL %s seed %s: the match produced no trace\n' "$map" "$seed"
		sed 's/\x08//g' "$work/p0.log" | grep -vE '^\s*$' | tail -4 |
			sed 's/^/         /'
		status=1
		return
	fi

	# Distinct tiles visited, not where it finished. The players walk with a
	# steady turn so that a start facing a wall still gets a fair try, which
	# means they trace a circle -- and a circle comes back to where it began.
	# Comparing first tile to last called a player stuck for going round in one.
	#
	# Three tiles is comfortably more than a pawn can reach by jittering inside
	# one cell, and comfortably less than a circle in open floor.
	stuck=$(awk '
		$1 ~ /^[0-9]+$/ {
			slot = $2
			if (!(slot in firstx)) { firstx[slot] = $3; firsty[slot] = $4 }
			tiles[slot "," $3 "," $4] = 1
			seen[slot] = 1
		}
		END {
			for (key in tiles) {
				split(key, part, ",")
				count[part[1]]++
			}
			for (s in seen)
				if (count[s] < 3)
					printf "%s@%s,%s(%d tile%s) ", s, firstx[s], firsty[s],
						count[s], count[s] == 1 ? "" : "s"
		}' "$work/p0.players")

	slots=$(awk '$1 ~ /^[0-9]+$/ {seen[$2]=1} END {print length(seen)}' \
		"$work/p0.players")

	if [ "$slots" -ne 3 ]; then
		printf '  FAIL %s seed %s: %s players in the world, wanted 3\n' \
			"$map" "$seed" "$slots"
		status=1
	elif [ -n "$stuck" ]; then
		printf '  FAIL %s seed %s: could not get out of its start: %s\n' \
			"$map" "$seed" "$stuck"
		status=1
	else
		printf '  ok   %s seed %s: all three walked away from their starts\n' \
			"$map" "$seed"
	fi
}

printf 'Three players, every arena, every start walked away from\n'
for map in $arenas; do
	for seed in $seeds; do
		run "$map" "$seed"
		report "$map" "$seed"
	done
done

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: no arena deals a start a player cannot leave.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
