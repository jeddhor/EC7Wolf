#!/bin/sh

# Regression test: a bot that goes somewhere, on purpose, by walking.
#
# Milestone B2, step 4, of docs/multiplayer-bots-and-server.md.
#
# The first three steps built a brain, a query and a graph. This is the first
# one where any of it moves a pawn: pick a reachable goal with the bot's own
# random, plan a route through the graph, and walk it by turning toward the
# next node and pressing forward -- through the ordinary command boundary, with
# no actor state written anywhere.
#
# What is checked:
#
#   * bots reach goals rather than merely moving. Distance covered is not the
#     measure; a pawn orbiting a waypoint covers a great deal of it;
#   * they cover ground, so a bot that reached one goal beside its spawn and
#     stopped does not pass;
#   * two runs of one match produce identical brains, since a bot whose
#     decisions cannot be reproduced cannot be debugged; and
#   * no step the graph offered was refused by the world.
#
# That last number is the point of this gate existing rather than being folded
# into the navigation one. test_bot_traversal.sh compares what a pawn did
# against what the query allows, which catches a query that is too strict and
# structurally cannot catch one that is too permissive -- and too permissive is
# the failure that strands a navigator. A bot walking its own plans is the only
# thing that finds those, and every one it finds is counted here.
#
# Usage: test_bot_roam.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-roam.XXXXXX)
. "$here/xvfb_common.sh"

display=:193
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

tics=1200
maps=${MAPS:-"MAP53 MAP51 MAP60"}

roam() {  # roam MAP SEED TAG
	mkdir -p "$work/$3-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$3.cfg" --savedir "$work/$3-saves" \
		--capture-rngseed "$2" \
		--capture-bots "$work/$3.bots" \
		--capture-players "$work/$3.players" \
		--capture-maxtics "$tics" \
		--tedlevel "$1" --skill 2 --battle --bots 2 ) >"$work/$3.log" 2>&1 || true
}

field() {  # field TAG KEY
	sed -n "s/.*Capture: bots .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" | tail -1
}

printf 'Bots that go somewhere\n'
for map in $maps; do
	roam "$map" 1 a
	if [ ! -s "$work/a.bots" ]; then
		printf '  FAIL %s: the bots left no account of themselves\n' "$map"
		sed 's/\x08//g' "$work/a.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
		status=1
		continue
	fi

	planned=$(field a planned)
	arrived=$(field a arrived)
	refused=$(field a refused)
	abandoned=$(field a abandoned)
	tiles=$(awk 'NR>1 && $2!=0 {print $2":"$3":"$4}' "$work/a.players" | sort -u | wc -l)
	printf '  ..   %s: planned %s, arrived %s, abandoned %s, refused %s, %s tiles\n' \
		"$map" "${planned:-?}" "${arrived:-?}" "${abandoned:-?}" \
		"${refused:-?}" "$tiles"

	check "$map: they planned routes" test "${planned:-0}" -ge 2
	check "$map: and reached goals rather than just moving" test "${arrived:-0}" -ge 2
	check "$map: covering ground while they did it" test "$tiles" -ge 60
	# The number this gate exists for.
	check "$map: no step the graph offered was one the world refused" \
		test "${refused:-1}" -eq 0
done

printf '\nThe same match twice\n'
roam MAP53 1 b
roam MAP53 1 c
brain_b=$(field b brain)
brain_c=$(field c brain)
printf '  ..   brain digests %s and %s\n' "${brain_b:-?}" "${brain_c:-?}"
check "two runs of one match think the same thoughts" \
	test -n "$brain_b" -a "$brain_b" = "$brain_c"
if cmp -s "$work/b.bots" "$work/c.bots"; then
	printf '  ok   and made the same decisions in the same order\n'
else
	printf '  FAIL the two runs decided differently\n'
	diff "$work/b.bots" "$work/c.bots" | head -4 | sed 's/^/         /'
	status=1
fi

printf '\nA different match\n'
roam MAP53 9 d
brain_d=$(field d brain)
check "a different seed produces different bots" \
	test -n "$brain_d" -a "$brain_d" != "$brain_b"

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: bots pick somewhere to go and walk there.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
