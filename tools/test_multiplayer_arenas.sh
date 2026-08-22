#!/bin/sh

# Regression test: the eight Corridor 7 arenas, and players placed apart in them.
#
# Milestone 3 of docs/multiplayer.md.
#
# Two claims are being defended here, and the second is the awkward one.
#
# The first is that all eight arenas load and can be played. They are not the
# contiguous block the compendium describes -- it places them at internal
# levels 51-58 with 59-60 empty, but the archived maps at 58 and 59 are bare
# 64x64 boxes holding a single marker, the same shape as the unused level at
# 50, while a full arena sits at 60 under the name "Network Lvl 8". So the list
# below skips two and ends at MAP60.
#
# The second is that players do not all spawn on the same tile. The arenas
# carry one placed player start each and contain no monsters, which defeats
# both of the fallbacks ECWolf uses to find deathmatch starts -- the co-op
# branch would hand every player that single start. GameMap::GenerateDeathmatch
# Starts deals starts from the arena's floor instead, and this gate is the
# check that it is dealing them apart, on every arena, rather than on the one
# that happened to be tested by hand.
#
# Being dealt apart is not enough on its own. The starts are chosen from a
# shuffle, and a shuffle that ran differently on the two machines would place
# each player somewhere its opponent did not agree with -- so the two player
# traces must also come out identical, which is what a lockstep game requires
# of anything derived from the seed. The last case runs one arena under a
# second seed and requires a different answer, because a "random" start that is
# the same every session is not one.
#
# Usage: test_multiplayer_arenas.sh BUILD_DIR DATA_DIR

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

display=:159
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${host_pid:-}" "${client_pid:-}"
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	# An EXIT trap's last command becomes the script's exit status, so it ends
	# on something that cannot fail. See kill_pids in xvfb_common.sh.
	true
}
trap cleanup EXIT INT TERM

arenas="MAP51 MAP52 MAP53 MAP54 MAP55 MAP56 MAP57 MAP60"
host_port=5131
client_port=5132

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# A match on one arena. Both sides pass --tedlevel and --battle: the map is
# exchanged and the arbiter's kept, but the game mode is not part of that
# handshake at the point the level loads, and a side that thinks it is playing
# co-op looks for different starts.
match() {
	_map=$1
	_seed=$2
	_tag=$3

	for _side in host client; do
		rm -f "$work/$_tag.$_side"
	done

	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 120 "$build_dir/ec7wolf" \
		--data CO7 --res 320 200 --nowait \
		--config "$work/host.cfg" --savedir "$work/host-saves" \
		--capture-rngseed "$_seed" --capture-players "$work/$_tag.host" \
		--capture-maxtics 15 --tedlevel "$_map" --skill 2 --battle \
		--host 2 --port "$host_port" --net-delay 6 \
		>"$work/$_tag.host.log" 2>&1 ) &
	host_pid=$!

	sleep 3

	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 120 "$build_dir/ec7wolf" \
		--data CO7 --res 320 200 --nowait \
		--config "$work/client.cfg" --savedir "$work/client-saves" \
		--capture-rngseed "$_seed" --capture-players "$work/$_tag.client" \
		--capture-maxtics 15 --tedlevel "$_map" --skill 2 --battle \
		--port "$client_port" --join "127.0.0.1:$host_port" --net-delay 6 \
		>"$work/$_tag.client.log" 2>&1 ) &
	client_pid=$!

	wait "$host_pid" "$client_pid" 2>/dev/null || true
	host_pid=; client_pid=
}

# The first tic each player was traced on, as "tilex tiley".
spawn_of() {  # spawn_of FILE PLAYER
	awk -v p="$2" '$1 !~ /^#/ && $2 == p { print $3, $4; exit }' "$1"
}

separation() {  # separation FILE -> chebyshev distance between the two players
	awk '
		$1 ~ /^#/ { next }
		$2 == 0 && !have0 { x0=$3; y0=$4; have0=1 }
		$2 == 1 && !have1 { x1=$3; y1=$4; have1=1 }
		have0 && have1 {
			dx = x0 > x1 ? x0-x1 : x1-x0
			dy = y0 > y1 ? y0-y1 : y1-y0
			print (dx > dy ? dx : dy); exit
		}
	' "$1"
}

printf 'The eight arenas:\n'
for map in $arenas; do
	match "$map" 1 "$map"

	if [ ! -s "$work/$map.host" ] || [ ! -s "$work/$map.client" ]; then
		printf '  FAIL %s produced no player trace\n' "$map"
		sed 's/\x08//g' "$work/$map.host.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
		status=1
		continue
	fi

	gap=$(separation "$work/$map.host")
	[ -n "$gap" ] || gap=0

	# Two tiles apart would technically be "not the same tile" while still
	# being close enough to shoot each other before either had moved. The
	# generator keeps starts five tiles apart where the arena allows it.
	if [ "$gap" -ge 5 ]; then
		printf '  ok   %s placed them %s tiles apart\n' "$map" "$gap"
	else
		printf '  FAIL %s placed them %s tiles apart\n' "$map" "$gap"
		status=1
	fi

	if cmp -s "$work/$map.host" "$work/$map.client"; then
		printf '  ok   %s: both machines agreed where everyone was\n' "$map"
	else
		printf '  FAIL %s: the two machines disagreed about player positions\n' "$map"
		diff "$work/$map.host" "$work/$map.client" | head -6 | sed 's/^/         /'
		status=1
	fi
done

printf '\nA second session on the same arena:\n'
match MAP51 7 reseed
if [ -s "$work/reseed.host" ]; then
	first=$(spawn_of "$work/MAP51.host" 0)
	again=$(spawn_of "$work/reseed.host" 0)
	printf '  ..   seed 1 started player 1 at %s, seed 7 at %s\n' "$first" "$again"
	check "a different seed deals a different start" test "$first" != "$again"
else
	printf '  FAIL the reseeded match produced no player trace\n'
	status=1
fi

printf '\n'
[ "$status" -eq 0 ] && printf 'PASS: eight arenas, players placed apart, both machines agreeing.\n' \
                    || printf 'FAIL: see above.\n'
exit "$status"
