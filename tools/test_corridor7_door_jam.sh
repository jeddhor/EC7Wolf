#!/bin/sh

# Regression test: a door that has begun closing reopens for whoever walks into
# it, instead of shutting them inside itself.
#
# The decision to close is taken on the tic BEFORE the tile turns solid: Tick
# lowers slideAmount below 0xffff, and a door only lets anything through at
# 0xffff. That leaves the player exactly one move in between, and one move at
# running speed is enough to carry somebody standing in front of a doorway into
# it. From the next tic every direction is refused -- TryMove rejects any
# destination still overlapping the tile, and a single move is not enough to
# leave -- so the only way out is to open the door again. That is what it looks
# like from the inside: being caught in the door.
#
# EVDoor::Tick's Closing case did not look again once it started. Wolf3D's
# DoorClosing tests every tic and calls DoorOpening when it finds someone.
#
# Asserted on MAP01's door at (16,31), which has floor at (15,31) and (17,31).
# The player is placed west of it, opens it, and stands still until the door's
# 300-tic timer runs out; forward is then pressed on a range of tics that
# brackets the moment the door decides to close. Two things must hold for every
# one of them:
#
#   1. the player never comes to rest overlapping the door's tile. Pressed
#      against a closed door from the west, a body of radius 22/64 rests at
#      x <= 15.65625; through it, at x >= 17.34375. Anything between those is a
#      player standing inside a closed door.
#   2. at least one start tic gets the player through, and at least one finds
#      the door already shut -- which is what proves the range brackets the
#      closing moment rather than missing it entirely.
#
# With the bug, pressing forward on the tic the door decides to close leaves the
# player at x = 15.6602: four thousandths of a tile inside the door, and stuck.
#
# Usage: test_corridor7_door_jam.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
work=$(mktemp -d /tmp/ec7wolf-doorjam.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# MAP01 plane 0: (16,31) is a door, (15,31) and (17,31) the floor either side.
# The player is C7Player, radius 22 of a 64-unit tile.
west_limit=15.65625
east_limit=17.34375

# Placed at tic 10, use pressed at 20: the door starts opening at 21, is fully
# open at 85, and its 300-tic timer then expires at 386.
first=382
last=390

status=0
got_through=0
found_shut=0

for start in $(seq "$first" "$last"); do
	(
		cd "$data_dir"
		timeout 180s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 640x400x24' \
			"$build_dir/ec7wolf" --data CO7 --no-upscale --nowait \
			--res 320 200 --vid-renderer software \
			--config "$work/config$start" --savedir "$work/save$start" \
			--tedlevel MAP01 --skill 2 --capture-rngseed 12345 \
			--capture-place 10 15.5 31.5 0 --capture-use 20 6 \
			--capture-forward "$start" --capture-trace 550 --capture-maxtics 560
	) >"$work/run$start.log" 2>&1 || true

	x=$(grep 'Capture: trace' "$work/run$start.log" | tail -1 |
		sed -n 's/.* x=\([0-9.]*\) .*/\1/p')
	if [ -z "$x" ]; then
		printf 'forward from %s: the run produced no trace\n' "$start"
		status=1
		continue
	fi

	verdict=$(awk -v x="$x" -v w="$west_limit" -v e="$east_limit" 'BEGIN{
		if (x > w && x < e) print "inside"
		else if (x >= e)    print "through"
		else                print "shut"
	}')
	case $verdict in
		inside)
			printf 'FAIL forward from %s: came to rest at x=%s, inside the door\n' \
				"$start" "$x"
			status=1
			;;
		through)
			printf '  ok  forward from %s: walked through, x=%s\n' "$start" "$x"
			got_through=$((got_through + 1))
			;;
		shut)
			printf '  ok  forward from %s: door already shut, x=%s\n' "$start" "$x"
			found_shut=$((found_shut + 1))
			;;
	esac
done

if [ "$got_through" -eq 0 ] || [ "$found_shut" -eq 0 ]; then
	printf 'FAIL: tics %s..%s do not bracket the moment the door closes '\
'(%s through, %s shut) -- the door timing moved and this gate is no longer '\
'testing the race\n' "$first" "$last" "$got_through" "$found_shut"
	status=1
fi

[ "$status" -eq 0 ] && printf 'PASS: a closing door reopens rather than trapping the player\n'
exit "$status"
