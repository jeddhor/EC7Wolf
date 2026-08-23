#!/bin/sh

# Regression test: multiplayer over a link that behaves like the internet.
#
# Milestone 1 of docs/multiplayer.md. The loopback gate proves the two sides
# agree; this one proves the game is playable when they are not in the same
# room, which is a different question and the one the feature turns on.
#
# The engine exchanged tic commands synchronously: every tic waited for every
# player, so the game advanced no faster than one network round trip. Measured
# at an 80ms round trip that is 8.6 tics a second against a TICRATE of 70. With
# input delay the round trip has a whole window to complete in, and the same
# link runs at the speed it does on loopback.
#
# So this gate does not assert an absolute tic rate -- that depends on the
# machine, and on a busy CI runner it would be flaky. It runs the same match
# twice over the same simulated link, once with the delay and once without, and
# requires the delayed one to be substantially faster. That is the claim being
# made, stated as a comparison rather than a number.
#
# The link is simulated in userspace by tools/netdelay.py. `tc netem` does this
# properly and needs root, which a gate should not have.
#
# Usage: test_multiplayer_latency.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }

tics=${TICS:-140}
one_way=${ONE_WAY_MS:-40}      # 80ms round trip
loss=${LOSS:-2}                # percent

work=$(mktemp -d /tmp/ec7wolf-mplat.XXXXXX)
. "$here/xvfb_common.sh"
display=:161
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${host_pid:-}" "${client_pid:-}" "${relay_pid:-}"
	xvfb_stop
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

# One match over the relay. Prints the tic rate it achieved.
match() {   # match TAG NETDELAY
	tag=$1
	net_delay=$2
	host_port=$((5050 + $3))
	relay_port=$((5060 + $3))
	client_port=$((5070 + $3))

	python3 "$here/netdelay.py" --listen "$relay_port" \
		--forward "127.0.0.1:$host_port" --delay "$one_way" --loss "$loss" \
		>"$work/$tag-relay.log" 2>&1 &
	relay_pid=$!
	sleep 1

	start=$(date +%s%N)
	for side in host client; do
		if [ "$side" = host ]; then
			role="--host 2 --port $host_port"
		else
			role="--port $client_port --join 127.0.0.1:$relay_port"
			sleep 3
		fi
		# shellcheck disable=SC2086
		(
			cd "$data_dir"
			DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
			timeout 180 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
				--config "$work/$tag-$side.cfg" --savedir "$work/$tag-$side-s" \
				--capture-rngseed 1 --capture-checksum "$work/$tag-$side.txt" \
				--capture-maxtics "$tics" --net-delay "$net_delay" \
				--tedlevel MAP51 --skill 2 $role \
				>"$work/$tag-$side.log" 2>&1
		) &
		if [ "$side" = host ]; then host_pid=$!; else client_pid=$!; fi
	done
	wait "$host_pid" "$client_pid" 2>/dev/null || true
	end=$(date +%s%N)
	kill "$relay_pid" 2>/dev/null || true

	# The three seconds before the client starts are setup, not play.
	elapsed_ms=$(( (end - start) / 1000000 - 3000 ))
	[ "$elapsed_ms" -lt 1 ] && elapsed_ms=1
	host_tics=$(grep -c '^tic ' "$work/$tag-host.txt" 2>/dev/null || echo 0)
	client_tics=$(grep -c '^tic ' "$work/$tag-client.txt" 2>/dev/null || echo 0)
	rate=$(( host_tics * 1000 / elapsed_ms ))

	printf '  %-9s delay %-2s  host %3s / client %3s tics in %sms = %s tics/sec\n' \
		"$tag" "$net_delay" "$host_tics" "$client_tics" "$elapsed_ms" "$rate"
	echo "$rate" > "$work/$tag.rate"
	# Both sides, not just the host. A stall leaves one of them short, and
	# recording only the host's count hid that from the completeness check
	# below -- which then let a truncated run reach the comparison and be
	# reported as a desync.
	echo "$host_tics" > "$work/$tag.tics"
	echo "$client_tics" > "$work/$tag.client-tics"
}

printf 'a %sms round trip with %s%% loss, %s tics each way\n' \
	"$((one_way * 2))" "$loss" "$tics"

# The delayed run gets a second chance, and only the delayed one.
#
# Not to paper over a flaky test: what it retries is a documented product
# limitation, written up under M7 in docs/multiplayer.md. On a lossy link the
# tic exchange can stall and never recover -- a peer stops sending, everyone
# else waits for ever -- and at 2% loss this run hits that perhaps one time in
# three. What this gate is for is that input delay keeps a match in sync and
# makes it several times faster, and neither of those questions is answered by
# a link that stalled.
#
# A real regression fails both attempts. The retry is reported either way, so a
# run that needed one is never mistaken for a run that did not.
match delayed 8 0
delayed_host=$(cat "$work/delayed.tics")
delayed_client=$(cat "$work/delayed.client-tics")
if [ "$delayed_host" -lt "$tics" ] || [ "$delayed_client" -lt "$tics" ]; then
	printf '  ..   the delayed run stalled (host %s, client %s of %s); trying once more\n' \
		"$delayed_host" "$delayed_client" "$tics"
	match delayed 8 0
fi

match immediate 0 1

status=0

# 1. The delayed run has to actually finish, and agree tic for tic.
#
# Two separate questions, and the answers must not be run together. A stall
# cuts one side short; comparing the two logs whole then reports the missing
# tail as a divergence, which sends whoever reads it hunting a desync that
# never happened. So agreement is judged on the tics both sides actually
# simulated, and falling short is its own failure with its own message.
delayed_host=$(cat "$work/delayed.tics")
delayed_client=$(cat "$work/delayed.client-tics")
shared=$delayed_host
[ "$delayed_client" -lt "$shared" ] && shared=$delayed_client

if [ "$shared" -lt 1 ]; then
	printf '\nFAIL: with input delay the match simulated nothing.\n'
	status=1
else
	head -n "$shared" "$work/delayed-host.txt"   > "$work/dh.cmp"
	head -n "$shared" "$work/delayed-client.txt" > "$work/dc.cmp"

	if ! cmp -s "$work/dh.cmp" "$work/dc.cmp"; then
		printf '\nFAIL: the two sides diverged with input delay on.\n'
		diff "$work/dh.cmp" "$work/dc.cmp" | head -4 | sed 's/^/    /'
		status=1
	elif [ "$delayed_host" -lt "$tics" ] || [ "$delayed_client" -lt "$tics" ]; then
		printf '\nFAIL: with input delay the match did not reach %s tics (host %s, client %s).\n' \
			"$tics" "$delayed_host" "$delayed_client"
		printf '      They agreed on all %s tics they did simulate, so this is\n' "$shared"
		printf '      the link stalling rather than the two games drifting apart.\n'
		status=1
	else
		printf '  ok   in sync, every tic, over a lossy link\n'
	fi
fi

# 2. And it has to be worth having. The effect measured while writing this was
#    8.6 -> 21.4 tics/sec; requiring only 1.5x leaves room for a busy machine
#    without letting a regression through.
delayed=$(cat "$work/delayed.rate")
immediate=$(cat "$work/immediate.rate")
if [ "$immediate" -gt 0 ] && [ $((delayed * 10)) -lt $((immediate * 15)) ]; then
	printf '\nFAIL: input delay bought almost nothing (%s vs %s tics/sec).\n' \
		"$delayed" "$immediate"
	printf '      It should be several times faster; the round trip is\n'
	printf '      supposed to stop costing a tic each.\n'
	status=1
else
	printf '  ok   %s tics/sec with the delay against %s without\n' \
		"$delayed" "$immediate"
fi

exit "$status"
