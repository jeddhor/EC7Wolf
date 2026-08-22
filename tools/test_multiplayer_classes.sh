#!/bin/sh

# Regression test: the Marine and the alien are actually different characters.
#
# Milestone 5 of docs/multiplayer.md. The compendium's 9.5 says players "may
# select the Marine or alien classes with different health, speed, and damage
# characteristics", and gives no numbers for any of the three -- so what this
# gate defends is that the two classes differ in each of the named ways, that
# both machines agree which player is which, and that the difference is the one
# the definitions ask for rather than whatever the engine happened to do.
#
# Speed is measured rather than read back. A player walks forward for fifty
# tics and the distance is compared: reading player.forwardmove out of the
# definition would prove only that the file says what the file says.
#
# The alien is Eitak. Which alien the original used is recorded nowhere, so it
# is an argument: Eitak is the game's primary alien-world guard, it is upright
# and armed, and it is one of only seven actors in the archive drawn in eight
# rotations -- and a player, being seen from every angle, needs those.
#
# Usage: test_multiplayer_classes.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-classes.XXXXXX)
. "$here/xvfb_common.sh"

display=:156
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${pid0:-}" "${pid1:-}"
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

arena=MAP53
status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# Column numbers in the player trace.
C_HEALTH=6
C_TEAM=8
C_CLASS=10
C_X=11
C_Y=12

at_tic() {  # at_tic FILE TIC PLAYER COLUMN
	awk -v t="$2" -v p="$3" -v c="$4" \
		'$1 !~ /^#/ && $1 == t && $2 == p { print $c; exit }' "$1"
}

printf 'One of each, in the same match\n'

common="--data CO7 --res 320 200 --nowait --capture-rngseed 1 --tedlevel $arena
        --skill 2 --battle --net-delay 6 --capture-maxtics 60"

# shellcheck disable=SC2086
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 120 "$build_dir/ec7wolf" $common \
	--playerclass C7Player --config "$work/h.cfg" --savedir "$work/hs" \
	--capture-players "$work/host.tr" --host 2 --port 5161 \
	>"$work/host.log" 2>&1 ) &
pid0=$!
sleep 3
# shellcheck disable=SC2086
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 120 "$build_dir/ec7wolf" $common \
	--playerclass C7AlienPlayer --config "$work/c.cfg" --savedir "$work/cs" \
	--capture-players "$work/client.tr" --port 5162 --join "127.0.0.1:5161" \
	>"$work/client.log" 2>&1 ) &
pid1=$!
wait "$pid0" "$pid1" 2>/dev/null || true
pid0=; pid1=

if [ ! -s "$work/host.tr" ] || [ ! -s "$work/client.tr" ]; then
	printf '  FAIL the match produced no player trace\n'
	sed 's/\x08//g' "$work/host.log" | grep -vE '^\s*$' | tail -5 | sed 's/^/         /'
	exit 1
fi

cls0=$(at_tic "$work/host.tr" 1 0 $C_CLASS)
cls1=$(at_tic "$work/host.tr" 1 1 $C_CLASS)
hp0=$(at_tic "$work/host.tr" 1 0 $C_HEALTH)
hp1=$(at_tic "$work/host.tr" 1 1 $C_HEALTH)
tm0=$(at_tic "$work/host.tr" 1 0 $C_TEAM)
tm1=$(at_tic "$work/host.tr" 1 1 $C_TEAM)

printf '  ..   player 1 is %s with %s health on team %s\n' "$cls0" "$hp0" "$tm0"
printf '  ..   player 2 is %s with %s health on team %s\n' "$cls1" "$hp1" "$tm1"

check "the marine got the marine pawn" test "$cls0" = "C7Player"
check "the alien got the alien pawn" test "$cls1" = "C7AlienPlayer"
check "they do not have the same health" test "$hp0" -ne "$hp1"
check "the alien is the tougher of the two" test "$hp1" -gt "$hp0"
# Since M5 a team is the character, which is what 9.5 says a team is.
check "and they are on opposite sides, because they are different characters" \
	test "$tm0" != "$tm1"

if cmp -s "$work/host.tr" "$work/client.tr"; then
	printf '  ok   both machines agreed about both players throughout\n'
else
	printf '  FAIL the two machines disagreed\n'
	diff "$work/host.tr" "$work/client.tr" | head -6 | sed 's/^/         /'
	status=1
fi

printf '\nSpeed, measured rather than read back\n'

walk() {  # walk CLASS -> prints distance covered between tic 5 and tic 55
	_cls=$1
	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 90 "$build_dir/ec7wolf" \
		--data CO7 --res 320 200 --nowait --capture-rngseed 1 \
		--tedlevel "$arena" --skill 2 --playerclass "$_cls" \
		--capture-forward 5 --capture-players "$work/walk-$_cls.tr" \
		--capture-maxtics 60 --config "$work/walk-$_cls.cfg" \
		--savedir "$work/walk-$_cls-s" >"$work/walk-$_cls.log" 2>&1 ) || true

	awk -v cx=$C_X -v cy=$C_Y '
		$1 !~ /^#/ && $2 == 0 && $1 == 5  { x0=$cx; y0=$cy }
		$1 !~ /^#/ && $2 == 0 && $1 == 55 { x1=$cx; y1=$cy }
		END {
			dx = x1 - x0; if(dx < 0) dx = -dx
			dy = y1 - y0; if(dy < 0) dy = -dy
			print dx + dy
		}' "$work/walk-$_cls.tr"
}

marine_dist=$(walk C7Player)
alien_dist=$(walk C7AlienPlayer)
printf '  ..   in fifty tics the marine covered %s and the alien %s\n' \
	"$marine_dist" "$alien_dist"

check "both of them actually moved" test "$marine_dist" -gt 0 -a "$alien_dist" -gt 0
check "the alien is the slower of the two" test "$alien_dist" -lt "$marine_dist"
# The definitions give the alien four fifths of the marine's stride. Allowing a
# tenth either way catches a class that stopped differing without failing on a
# tile boundary.
if [ "$marine_dist" -gt 0 ]; then
	ratio=$((alien_dist * 100 / marine_dist))
	printf '  ..   which is %s%% of the marine\n' "$ratio"
	check "by about the fifth the definitions ask for" test "$ratio" -ge 70 -a "$ratio" -le 90
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: two characters, differing in pawn, health, side and speed.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
