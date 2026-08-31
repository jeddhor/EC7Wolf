#!/bin/sh

# Regression test: aliens hear gunfire.
#
# Corridor 7's floor words are Wolf3D areas, and hearing is built on them:
# CheckSightTo takes madenoise and then asks map->CheckLink() whether the
# shooter's area reaches the listener's, dropping the noise if it does not.
# CheckLink answers false the moment either side is NULL. Plane-0 word 0 is
# walkable but carries no area, so on a floor built from zeros nothing can hear
# anything -- every alien ignores gunfire completely and wakes only on sight or
# on contact. None of the sixty shipped maps holds a single plane-0 zero; the
# map editor floored new maps with them, which is how this was found, and it
# reads in play as "the monsters are broken" rather than as a property of the
# floor.
#
# Nothing tested hearing at all before this, in either direction.
#
# The alien is placed two tiles BEHIND the player and facing away, which is the
# only arrangement where hearing is the sole explanation:
#
#   * facing away, the field-of-view test in CheckSightTo refuses sight, and at
#     two tiles it is outside MINSIGHT's automatic close-range radius of 1.5;
#   * behind the player it is off screen, so the player's own gun cannot hit
#     it. That matters more than it sounds: Wolf3D's GunAttack picks its target
#     with a screen-space window rather than a ray, so an alien well off the
#     line of fire is still shot if it is drawn. An earlier version of this
#     test put it 16 tiles ahead and 2 to the side and killed it every run,
#     which looks exactly like "it woke up and then stopped existing".
#
# Both directions are asserted, because either alone passes for the wrong
# reason: a quiet run where the alien wakes anyway would mean it can see the
# player after all, and the firing run would then prove nothing.
#
# Usage: test_corridor7_hearing.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d /tmp/ec7wolf-hearing.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

lab="$work/lab"
mkdir -p "$lab"
# The build's OWN pk3: ECWolf resolves ec7wolf.pk3 from the working directory
# first, so running from the data directory silently tests whatever was
# installed there last. That has produced false passes before.
cp "$build_dir/ec7wolf" "$build_dir/ec7wolf.pk3" "$lab/"
for f in "$data_dir"/*.CO7 "$data_dir"/CORR7CD.EXE; do
	[ -e "$f" ] && cp "$f" "$lab/" || true
done

# 118 is a probe standing and facing west; the player starts at x=4 facing east.
python3 "$here/make_corridor7_ai_lab.py" \
	"$data_dir/MAPTEMP.CO7" "$lab/MAPTEMP.CO7" 118:2 >/dev/null

listen() { # $1 = tag, $2... = extra flags
	tag=$1
	shift
	(
		cd "$lab"
		timeout 300s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
			xvfb-run -a -s '-screen 0 640x400x24' ./ec7wolf \
			--data CO7 --no-upscale --nowait --vid-renderer software --res 320 200 \
			--config "$work/$tag.cfg" --savedir "$work/$tag.sv" \
			--tedlevel MAP01 --skill 2 --capture-rngseed 12345 \
			--capture-actors "$work/$tag.txt" --capture-maxtics 300 "$@"
	) >"$work/$tag.log" 2>&1 || true
	if [ ! -s "$work/$tag.txt" ]; then
		printf 'FAIL: the %s run produced no actor trace; see %s/%s.log\n' \
			"$tag" "$work" "$tag" >&2
		exit 1
	fi
}

listen quiet
listen firing --capture-fire 60

status=0

report() { # $1 = tag
	awk -v tag="$1" '
		!/^#/ {
			seen = 1
			if ($7 == 1 && !woke) woke = $1
			health = $8
			last = $1
		}
		END {
			if (!seen) { print "none 0 0"; exit }
			printf "%s %s %s\n", (woke ? woke : "never"), health, last
		}' "$work/$1.txt"
}

set -- $(report quiet)
quiet_woke=$1; quiet_health=$2; quiet_last=$3
set -- $(report firing)
fire_woke=$1; fire_health=$2; fire_last=$3

if [ "$quiet_woke" != "never" ]; then
	printf 'FAIL quiet: the alien woke at tic %s with nothing to hear -- it can see\n'\
' the player, so the firing half of this test proves nothing\n' "$quiet_woke"
	status=1
else
	printf '  ok  quiet:  slept through %s tics\n' "$quiet_last"
fi

if [ "$fire_woke" = "never" ]; then
	printf 'FAIL firing: the alien never reacted to %s tics of gunfire. Sound does '\
'not reach it -- check that the floor it stands on is a sound area and not word 0\n' \
		"$fire_last"
	status=1
else
	printf '  ok  firing: woke at tic %s, %s tics after the first shot\n' \
		"$fire_woke" "$((fire_woke - 60))"
fi

# It has to have woken rather than died: an alien shot dead leaves the trace,
# and "no rows after tic N" must never be mistaken for "it reacted".
if [ "$fire_health" -le 0 ] 2>/dev/null || [ "$quiet_health" -le 0 ] 2>/dev/null; then
	printf 'FAIL: the alien ended up dead (quiet %s, firing %s); it is being shot '\
'rather than listening\n' "$quiet_health" "$fire_health"
	status=1
else
	printf '  ok  it survived both runs (health %s), so it heard rather than died\n' \
		"$fire_health"
fi

[ "$status" -eq 0 ] && printf 'PASS: aliens hear gunfire they cannot see\n'
exit "$status"
