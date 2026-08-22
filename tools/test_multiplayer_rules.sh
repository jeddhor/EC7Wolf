#!/bin/sh

# Regression test: who may shoot whom, what that scores, and when it stops.
#
# Milestone 4 of docs/multiplayer.md. Three rules, and the middle one is the
# reason this gate needs three players rather than two.
#
#   * Free-for-all. Everybody can hurt everybody, and a kill is a frag.
#   * Team play, per the compendium's 9.5: players controlling the same
#     character cannot damage one another and their kills count together.
#     Teams are dealt by player number until the characters exist (M5), so
#     players 0 and 2 are team-mates and player 1 is the opposition -- which
#     is why a two-player match cannot test the rule at all.
#   * A frag limit ends the match.
#
# Scripting a fight headlessly needs two capture-time tools, both added for
# this. --capture-duel stands two named players face to face on floor it finds
# in the map, and parks everyone else far away; --capture-fire holds the
# trigger down. Neither may be --capture-warp, which pins players[ConsolePlayer]
# -- a different pawn on each machine -- and would part the two simulations
# before a shot was fired. The duel positions are computed from map data, so
# every machine reaches the same ones without a packet about it, and the
# trigger is injected into the local command before it is sent, so a shot
# travels the way a real one does.
#
# Every case also requires the machines to agree, because a rule that is
# applied on one side and not the other is a desync wearing a rule's clothes.
#
# Usage: test_multiplayer_rules.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-rules.XXXXXX)
. "$here/xvfb_common.sh"

display=:158
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${pid0:-}" "${pid1:-}" "${pid2:-}"
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
base_port=5151
status=0

check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

# match TAG MODEFLAG NPLAYERS DUEL_A DUEL_B FRAGLIMIT [DUEL_C] [MAXTICS]
match() {
	tag=$1; mode=$2; nplayers=$3; duel_a=$4; duel_b=$5; fraglimit=$6
	duel_c=${7:-}; maxtics=${8:-300}

	pid0=; pid1=; pid2=
	n=0
	while [ "$n" -lt "$nplayers" ]; do
		if [ "$n" -eq 0 ]; then
			role="--host $nplayers --port $base_port"
		else
			role="--port $((base_port + n)) --join 127.0.0.1:$base_port"
		fi

		# shellcheck disable=SC2086
		( cd "$data_dir"
		  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		  timeout 150 "$build_dir/ec7wolf" \
			--data CO7 --res 320 200 --nowait \
			--config "$work/$tag-$n.cfg" --savedir "$work/$tag-$n-s" \
			--capture-rngseed 1 --tedlevel "$arena" --skill 2 \
			"$mode" --fraglimit "$fraglimit" --net-delay 6 \
			--capture-duel "$duel_a" "$duel_b" $duel_c --capture-fire 40 --capture-ammo \
			--capture-players "$work/$tag-$n.tr" --capture-maxtics "$maxtics" \
			$role >"$work/$tag-$n.log" 2>&1 ) &
		eval "pid$n=\$!"
		n=$((n + 1))
		[ "$n" -lt "$nplayers" ] && sleep 3
	done
	wait "$pid0" ${pid1:+"$pid1"} ${pid2:+"$pid2"} 2>/dev/null || true
	pid0=; pid1=; pid2=
}

# Final recorded value of a column for one player. 6 = health, 7 = frags.
final() {  # final FILE PLAYER COLUMN
	awk -v p="$2" -v c="$3" '$1 !~ /^#/ && $2 == p { v=$c } END { print (v == "" ? "?" : v) }' "$1"
}

lowest_health() {  # lowest_health FILE PLAYER
	awk -v p="$2" '$1 !~ /^#/ && $2 == p { if(m == "" || $6 < m) m = $6 } END { print (m == "" ? "?" : m) }' "$1"
}

agree() {  # agree TAG N -- every machine's trace identical to the host's
	_tag=$1; _n=$2; _i=1
	while [ "$_i" -lt "$_n" ]; do
		cmp -s "$work/$_tag-0.tr" "$work/$_tag-$_i.tr" || return 1
		_i=$((_i + 1))
	done
	return 0
}

printf 'Free-for-all: two players, face to face\n'
match ffa --battle 2 0 1 0
if [ -s "$work/ffa-0.tr" ]; then
	h0=$(lowest_health "$work/ffa-0.tr" 0)
	h1=$(lowest_health "$work/ffa-0.tr" 1)
	f0=$(final "$work/ffa-0.tr" 0 7)
	f1=$(final "$work/ffa-0.tr" 1 7)
	printf '  ..   lowest health %s and %s; frags %s and %s\n' "$h0" "$h1" "$f0" "$f1"
	check "they hurt each other" test "$h0" -lt 100 -a "$h1" -lt 100
	check "and the kills were scored" test $((f0 + f1)) -ge 1
	check "both machines agreed throughout" agree ffa 2
else
	printf '  FAIL no player trace\n'; status=1
fi

printf '\nTeam play: two team-mates face to face\n'
match mates --teams 3 0 2 0
if [ -s "$work/mates-0.tr" ]; then
	t0=$(final "$work/mates-0.tr" 0 8)
	t2=$(final "$work/mates-0.tr" 2 8)
	h0=$(lowest_health "$work/mates-0.tr" 0)
	h2=$(lowest_health "$work/mates-0.tr" 2)
	f0=$(final "$work/mates-0.tr" 0 7)
	f2=$(final "$work/mates-0.tr" 2 7)
	printf '  ..   players 0 and 2 on teams %s and %s; lowest health %s and %s; frags %s and %s\n' \
		"$t0" "$t2" "$h0" "$h2" "$f0" "$f2"
	check "they really are team-mates" test "$t0" = "$t2"
	check "neither could hurt the other" test "$h0" -eq 100 -a "$h2" -eq 100
	check "and nothing was scored" test $((f0 + f2)) -eq 0
	check "both machines agreed throughout" agree mates 3
else
	printf '  FAIL no player trace\n'; status=1
fi

printf '\nTeam play: opponents face to face\n'
match foes --teams 3 0 1 0
if [ -s "$work/foes-0.tr" ]; then
	t0=$(final "$work/foes-0.tr" 0 8)
	t1=$(final "$work/foes-0.tr" 1 8)
	h0=$(lowest_health "$work/foes-0.tr" 0)
	h1=$(lowest_health "$work/foes-0.tr" 1)
	printf '  ..   players 0 and 1 on teams %s and %s; lowest health %s and %s\n' \
		"$t0" "$t1" "$h0" "$h1"
	check "they are on opposite sides" test "$t0" != "$t1"
	check "so the shots landed" test "$h0" -lt 100 -o "$h1" -lt 100
	check "both machines agreed throughout" agree foes 3
else
	printf '  FAIL no player trace\n'; status=1
fi

printf '\nTeam kills add up\n'
match agg --teams 3 0 1 3 2 1200
if [ -s "$work/agg-0.tr" ]; then
	f0=$(final "$work/agg-0.tr" 0 7)
	f2=$(final "$work/agg-0.tr" 2 7)
	printf '  ..   team-mates 0 and 2 scored %s and %s against player 1\n' "$f0" "$f2"
	check "both of them got kills" test "$f0" -ge 1 -a "$f2" -ge 1
	check "and together they reached the team limit of 3" test $((f0 + f2)) -ge 3
	check "which neither had reached alone" test "$f0" -lt 3 -a "$f2" -lt 3
	if grep -q "Team 1 reached the frag limit" "$work/agg-0.log" 2>/dev/null; then
		printf '  ok   and the match was called on the team total\n'
	else
		printf '  FAIL the team total never ended the match\n'; status=1
	fi
	check "both machines agreed throughout" agree agg 3
else
	printf '  FAIL no player trace\n'; status=1
fi

printf '\nA frag limit ends the match\n'
match limit --battle 2 0 1 1
if grep -q "reached the frag limit" "$work/limit-0.log" 2>/dev/null; then
	printf '  ok   the host called the match\n'
else
	printf '  FAIL the host never reached the frag limit\n'
	status=1
fi
if grep -q "reached the frag limit" "$work/limit-1.log" 2>/dev/null; then
	printf '  ok   and so did the other machine, on its own\n'
else
	printf '  FAIL the other machine did not end the match\n'
	status=1
fi
# A match that ends starts another on the same arena, so the level line appears
# more than once rather than the campaign's first floor appearing at all.
restarts=$(grep -c "^$arena - " "$work/limit-0.log" 2>/dev/null || echo 0)
printf '  ..   the arena loaded %s times\n' "$restarts"
check "it began again rather than leaving for the campaign" test "$restarts" -ge 2
check "and did not fall through to MAP01" sh -c "! grep -q '^MAP01 - ' '$work/limit-0.log'"

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: the rules hold, and both machines applied them alike.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
