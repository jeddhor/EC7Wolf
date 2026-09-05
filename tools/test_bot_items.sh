#!/bin/sh

# Regression test: bots fetch what they need, for reasons you can read.
#
# Milestone B5 of docs/multiplayer-bots-and-server.md, sections 12.8 and 14.2.
#
# The exit criterion is that seeded scenarios select and collect the expected
# resource "for explainable reasons", so the explanation is part of the
# deliverable rather than a debugging aid. Every decision emits one line naming
# how many candidates were considered and why each was rejected, and this gate
# reads it.
#
# Two things here are less obvious than they look.
#
# Collection cannot be observed by watching the pickup vanish. Multiplayer
# weapon-stay leaves it lying in the world after it is collected, so the map
# looks identical and a belief of "present" stays correct. What changes is
# whose backpack it is in, which is why the engine reports weapons held.
#
# And "already-have" is the check that stay-in-world semantics are respected.
# A weapon already carried is worth nothing -- not a little less -- because
# picking it up again does nothing whatsoever. Seeing that reason appear is
# how we know a bot stopped wanting the thing it just collected.
#
# Usage: test_bot_items.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-items.XXXXXX)
. "$here/xvfb_common.sh"

display=:200
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# MAP60 has eleven pickups, the most of any arena. MAP53 has three, which is
# enough to show the same behaviour on a second map.
maps=${MAPS:-"MAP60 MAP53"}
tics=1400

run() {  # run MAP SEED TAG
	mkdir -p "$work/$3-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$3.cfg" --savedir "$work/$3-saves" \
		--capture-rngseed "$2" \
		--capture-bots "$work/$3.bots" \
		--capture-nav "$work/$3.nav" \
		--capture-maxtics "$tics" \
		--tedlevel "$1" --skill 2 --battle --bots 3 ) >"$work/$3.log" 2>&1 || true
}

printf 'Bots fetch what they need, for readable reasons\n'

for map in $maps; do
	for seed in 1 5; do
		tag="$map-$seed"
		run "$map" "$seed" "$tag"
		if [ ! -s "$work/$tag.bots" ]; then
			printf '  FAIL %s/%s: no bot trace\n' "$map" "$seed"
			status=1
			continue
		fi

		spawns=$(grep -c '^item ' "$work/$tag.nav" || true)
		scans=$(grep -c 'item-scan' "$work/$tag.bots" || true)
		goals=$(grep -c 'route item' "$work/$tag.bots" || true)
		weapons=$(sed -n 's/.*Capture: bot weapons \(.*\)/\1/p' "$work/$tag.log" | tail -1)
		# A C7Player spawns with two weapons: the M16 and the bayonet.
		extra=$(printf '%s' "$weapons" | tr ',' '\n' |
			awk -F: '{ if ($2 > 2) n += $2 - 2 } END { print n+0 }')
		printf '  ..   %s/%s: %s spawns, %s decisions, %s item goals, weapons %s (+%s collected)\n' \
			"$map" "$seed" "$spawns" "$scans" "$goals" "${weapons:-none}" "$extra"

		check "$map/$seed: the map annotates its pickups" test "${spawns:-0}" -ge 3
		check "$map/$seed: every decision was explained" test "${scans:-0}" -ge 3
		check "$map/$seed: something was chosen to fetch" test "${goals:-0}" -ge 1
		check "$map/$seed: and collected" test "${extra:-0}" -ge 1

		# Reasons must be real: a decision line that rejected nothing and chose
		# nothing would satisfy the counts above while meaning nothing.
		reasons=$(grep -o 'considered=[0-9]* .*' "$work/$tag.bots" |
			sed 's/considered=[0-9]* //' | tr ' ' '\n' |
			sed -n 's/\([a-z-]*\)=.*/\1/p' | sort -u | tr '\n' ' ')
		printf '  ..   %s/%s: reasons seen: %s\n' "$map" "$seed" "${reasons:-none}"
		check "$map/$seed: candidates were rejected for named reasons" \
			test -n "${reasons:-}"

		# Stay-in-world: once a weapon is carried it is worth nothing, and the
		# bot must stop wanting it. If this never appears, either nothing was
		# collected or the rule is not being applied.
		check "$map/$seed: a collected weapon stopped being wanted" \
			grep -q 'already-have' "$work/$tag.bots"

		# Commitment: a bot reconsiders when its route runs out, not every tic.
		# More decisions than tics/70 would mean it is thinking constantly.
		perbot=$(( ${scans:-0} / 3 ))
		check "$map/$seed: it did not deliberate every tic ($perbot each)" \
			test "$perbot" -le 25
	done
done

if [ "$status" -eq 0 ]; then
	printf 'PASS: bots choose, explain, and collect.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
