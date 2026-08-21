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
	kill ${host_pid:-0} ${client_pid:-0} ${relay_pid:-0} 2>/dev/null || true
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
	echo "$host_tics" > "$work/$tag.tics"
}

printf 'a %sms round trip with %s%% loss, %s tics each way\n' \
	"$((one_way * 2))" "$loss" "$tics"

match delayed 8 0
match immediate 0 1

status=0

# 1. The delayed run has to actually finish, and agree tic for tic.
if [ "$(cat "$work/delayed.tics")" -lt "$tics" ]; then
	printf '\nFAIL: with input delay the match did not reach %s tics.\n' "$tics"
	status=1
elif ! diff -q "$work/delayed-host.txt" "$work/delayed-client.txt" >/dev/null 2>&1; then
	printf '\nFAIL: the two sides diverged with input delay on.\n'
	diff "$work/delayed-host.txt" "$work/delayed-client.txt" | head -4 | sed 's/^/    /'
	status=1
else
	printf '  ok   in sync, every tic, over a lossy link\n'
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
