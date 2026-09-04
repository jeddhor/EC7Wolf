#!/bin/sh

# Regression test: bots use the transporters, and do not live in them.
#
# Milestone B3 of docs/multiplayer-bots-and-server.md, section 12.6.
#
# Transporters are what makes three of the eight arenas one arena. Without
# edges for them MAP56 is in 5 pieces, MAP57 in 2 and MAP60 in 5, and a bot
# dropped into the wrong piece can reach a quarter of the map. They are also
# the easiest thing in the game to get stuck in: a relative teleport lands a
# body a tile short of the nominal destination, which is usually beside the pad
# that sends it straight back.
#
# What is checked:
#
#   * every transporter the map declares has an edge in the graph, and every
#     transporter edge in the graph is one the map declares;
#   * the arena is one connected piece once they are in;
#   * bots actually cross them;
#   * the freeze is accounted for exactly -- 35 tics per crossing, no more and
#     no fewer, which is the cheapest possible check that the follower waits
#     rather than fighting the engine;
#   * no bot crosses a transporter twice inside the cooldown. This is the
#     oscillation check, and it is the one worth having: before the cooldown
#     was wired up, bots bounced between two pads every 38 tics -- freeze,
#     three steps, back again -- for as long as the match lasted; and
#   * two runs of one match produce the same brain.
#
# Usage: test_bot_transporters.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-ports.XXXXXX)
. "$here/xvfb_common.sh"

display=:197
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

# The cooldown the bot applies after arriving, from g_bot.cpp. Two crossings by
# one bot closer together than this is the bounce this gate exists to catch.
cooldown=210
tics=1200
maps=${MAPS:-"MAP60 MAP56 MAP57"}

run() {  # run MAP TAG [EXTRA...]
	map=$1; tag=$2; shift 2
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 250 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed 1 \
		--capture-nav "$work/$tag.nav" \
		--capture-bots "$work/$tag.bots" \
		--capture-players "$work/$tag.players" \
		--capture-maxtics "$tics" \
		--tedlevel "$map" --skill 2 --battle --bots 2 "$@" ) >"$work/$tag.log" 2>&1 || true
}

field() {  # field TAG KEY
	sed -n "s/.*Capture: bots .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" | tail -1
}

printf 'Transporters, used and not lived in\n'

for map in $maps; do
	run "$map" a
	if [ ! -s "$work/a.nav" ] || [ ! -s "$work/a.bots" ]; then
		printf '  FAIL %s: no navigation dump or no bot trace\n' "$map"
		sed 's/\x08//g' "$work/a.log" | grep -vE '^\s*$' | tail -4 | sed 's/^/         /'
		status=1
		continue
	fi

	pads=$(grep -c '^transporter ' "$work/a.nav" || true)
	edges=$(awk '$1=="edge" && $7==4' "$work/a.nav" | wc -l)
	regions=$(sed -n 's/^# nav .*regions \([0-9]*\) .*/\1/p' "$work/a.nav")
	ports=$(field a ports)
	frozen=$(field a frozen)
	printf '  ..   %s: %s pads, %s transporter edges, %s region(s), %s crossing(s)\n' \
		"$map" "$pads" "$edges" "${regions:-?}" "${ports:-?}"

	check "$map: the map has transporters to test" test "${pads:-0}" -ge 2

	# Every declared transporter became an edge, and nothing else did. The
	# counts can differ legitimately -- a pad whose destination is not a
	# standable cell builds no edge -- so this compares the endpoints, not just
	# the totals.
	awk '$1=="transporter"{split($8,d,","); print $2, $3, d[1], d[2]}' \
		"$work/a.nav" | sort > "$work/$map.declared"
	awk '$1=="edge" && $7==4 {print $2, $3, $4, $5}' \
		"$work/a.nav" | sort > "$work/$map.built"
	if diff -q "$work/$map.declared" "$work/$map.built" >/dev/null 2>&1; then
		printf '  ok   %s: every transporter the map declares is in the graph\n' "$map"
	else
		printf '  FAIL %s: the graph and the map disagree about transporters\n' "$map"
		diff "$work/$map.declared" "$work/$map.built" | head -4 | sed 's/^/         /'
		status=1
	fi

	check "$map: the arena is one connected piece" test "${regions:-0}" -eq 1
	check "$map: bots crossed at least one" test "${ports:-0}" -ge 1

	# 35 tics of freeze per crossing, exactly. Fewer means the follower moved
	# during a freeze the engine was ignoring; more means it sat still for
	# something else and called it a transporter.
	expect=$((${ports:-0} * 35))
	check "$map: the freeze cost exactly 35 tics a crossing ($frozen)" \
		test "${frozen:-0}" -eq "$expect"

	# The oscillation check.
	#
	# Not "two crossings close together": crossing a second, different
	# transporter soon after the first is a bot getting somewhere, and an
	# earlier version of this check failed a perfectly good run for it. What is
	# wrong is going back -- arriving within a tile or two of where the
	# previous crossing started, inside the cooldown. That is the bounce.
	osc=$(awk -v cd="$cooldown" '$3=="teleported" {
			slot = $2
			split($4, f, "="); split(f[2], fc, ",")
			split($5, t, "="); split(t[2], tc, ",")
			if (slot in prevfx) {
				dx = tc[1] - prevfx[slot]; if (dx < 0) dx = -dx
				dy = tc[2] - prevfy[slot]; if (dy < 0) dy = -dy
				if ($1 - prevt[slot] < cd && dx <= 2 && dy <= 2)
					print $1 " slot " slot " returned to " tc[1] "," tc[2]
			}
			prevfx[slot] = fc[1]; prevfy[slot] = fc[2]; prevt[slot] = $1
		}' "$work/a.bots")
	if [ -n "$osc" ]; then
		printf '  FAIL %s: a bot went straight back where it came from\n' "$map"
		printf '%s\n' "$osc" | head -3 | sed 's/^/         /'
		status=1
	else
		printf '  ok   %s: no bot went straight back through a pair\n' "$map"
	fi
done

# Every pair, one at a time.
#
# B3 asks for every transporter pair to be exercised, and roaming will not do
# it: bots go where their goals take them, and over a match that is a handful
# of the thirty pads in the three arenas. So each pad is named as a goal in
# turn. Walking onto it is the crossing, which is why the bot never "arrives"
# -- it is somewhere else before the arrival check runs -- and the crossing is
# the thing being tested.
#
# Budget: 700 tics a pad. MAP56's western pair sits at the far edge of a
# 1498-cell arena and a bot spawning across the map needs most of that just to
# walk there -- at 450 it was reported as never crossed, and at 1200 the same
# bot crosses it seventeen times. The cost of this sweep is thirty process
# launches rather than the simulation, so a tighter budget saves little.
#
# Set PADS=sample for a faster run that checks three per map.
printf '  ..   naming every pad in turn\n'
for map in $maps; do
	run "$map" pads
	pads_list=$(awk '$1=="transporter"{print $2","$3}' "$work/pads.nav")
	[ "${PADS:-all}" = "sample" ] &&
		pads_list=$(printf '%s\n' "$pads_list" | head -3)

	missed=""
	tried=0
	for pad in $pads_list; do
		px=${pad%,*}; py=${pad#*,}
		tried=$((tried + 1))
		mkdir -p "$work/pad-saves"
		( cd "$data_dir"
		  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		  timeout 120 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
			--vid-renderer software \
			--config "$work/pad.cfg" --savedir "$work/pad-saves" \
			--capture-rngseed 1 \
			--capture-bot-goal "$px" "$py" \
			--capture-maxtics 700 \
			--tedlevel "$map" --skill 2 --battle --bots 1 ) >"$work/pad.log" 2>&1 || true
		crossed=$(sed -n 's/.*Capture: bots .*ports=\([0-9]*\).*/\1/p' "$work/pad.log" | tail -1)
		[ "${crossed:-0}" -ge 1 ] || missed="$missed ($px,$py)"
	done

	if [ -z "$missed" ]; then
		printf '  ok   %s: all %s pads were reached and crossed\n' "$map" "$tried"
	else
		printf '  FAIL %s: pads never crossed:%s\n' "$map" "$missed"
		status=1
	fi
done

# Reproducibility, on the map with the most of them.
run MAP60 r1
run MAP60 r2
d1=$(field r1 brain); d2=$(field r2 brain)
printf '  ..   brain digests %s and %s\n' "${d1:-?}" "${d2:-?}"
check "two runs of one match think the same thoughts" \
	test -n "${d1:-}" -a "${d1:-x}" = "${d2:-y}"

if [ "$status" -eq 0 ]; then
	printf 'PASS: transporters connect the arenas and bots pass through them.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
