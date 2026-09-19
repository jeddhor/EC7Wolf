#!/bin/sh

# How often does a match actually start, on a line that loses packets?
#
# Milestone 7 of docs/multiplayer.md left this open, and it is the last thing
# between a working netgame and a releasable one: Net::NewGame's exchange is
# synchronous and its exit is assumed rather than negotiated. A peer leaves as
# soon as everyone has acked its packet and it holds everyone else's -- which
# says nothing about whether its own acks arrived. If one did not, the peer it
# was owed to resends its packet for ever, to nobody: the only machine that
# would have answered has gone to load the level.
#
# docs/multiplayer.md recorded "about half of connections at 5% loss" from M7.
# That did not survive being measured again: 23 of 24 complete. The earlier
# figure counted the artifact described below -- a peer still waiting at the
# end of a fixed-length match -- as a failed handshake, which is the same
# mistake the first version of this harness made, reporting 62% until its
# "failures" were read rather than counted.
#
# The defect was real and its deadlock permanent; only its rate was wrong.
# Fixed now, in three parts described in docs/multiplayer.md, and measured
# over 24 connections each way:
#
#   loss   before   after
#   5%     23/24    24/24
#   15%    19/24    24/24
#   30%     7/16    16/16
#
# This is a statistical claim, so the gate is a sample rather than a single
# run, and its threshold is set well below the measured rate so that it
# reports a regression rather than the weather. HANDSHAKE_RUNS raises the
# sample when the number itself is the point -- when changing the exchange,
# take a before and an after at 24 or more, because 12 runs cannot tell 60%
# from 75%.
#
# Each run is its own pair of processes, its own ports and its own relay seed,
# and counts as a success only if both ends reached the level and simulated
# it. A host that starts alone is not a success; neither is a client that
# reaches the level while the host is still waiting.
#
# Usage: test_multiplayer_handshake.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-handshake.XXXXXX)
. "$here/xvfb_common.sh"
display=:259
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${relay:-}" "${host:-}" "${client:-}"
	xvfb_stop
	if [ "$status" -ne 0 ] || [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

# Sixteen runs at 15% loss, because that is where the two behaviours are
# distinguishable. At 5% the fault shows in about one connection in twenty, and
# a dozen runs cannot tell that from none; at 15% the old code scores about 79%
# and the fixed code 100%, which a sample this size separates comfortably.
runs=${HANDSHAKE_RUNS:-16}
loss=${HANDSHAKE_LOSS:-15}
delay=40
base_port=5201
arena=MAP53
# Long enough for a good connection to finish and start simulating, short
# enough that a wedged one does not hold the gate up: a completed handshake
# reaches the level in a couple of seconds, and a wedged one never does.
patience=30

printf 'Starting a match on a line that loses packets\n'
printf '  ..   %s connections, %s%% loss each way, %sms delay\n' \
	"$runs" "$loss" "$delay"

started=0
n=0
while [ "$n" -lt "$runs" ]; do
	n=$((n + 1))
	host_port=$((base_port + n*4))
	client_port=$((host_port + 1))
	relay_port=$((host_port + 2))
	tag="run$n"
	mkdir -p "$work/$tag-h-saves" "$work/$tag-c-saves"

	python3 "$here/netdelay.py" --listen "$relay_port" \
		--forward "127.0.0.1:$host_port" --delay "$delay" --loss "$loss" \
		--seed "$n" >"$work/$tag-relay.log" 2>&1 &
	relay=$!
	sleep 0.5

	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  exec timeout "$patience" "$build_dir/ec7wolf" --data CO7 --res 320 200 \
		--nowait --vid-renderer software \
		--config "$work/$tag-h.cfg" --savedir "$work/$tag-h-saves" \
		--capture-rngseed 1 --tedlevel "$arena" --skill 2 --battle \
		--net-delay 6 --capture-maxtics 60 \
		--host 2 --port "$host_port" ) >"$work/$tag-h.log" 2>&1 &
	host=$!
	sleep 2
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  exec timeout "$patience" "$build_dir/ec7wolf" --data CO7 --res 320 200 \
		--nowait --vid-renderer software \
		--config "$work/$tag-c.cfg" --savedir "$work/$tag-c-saves" \
		--capture-rngseed 1 --tedlevel "$arena" --skill 2 --battle \
		--net-delay 6 --capture-maxtics 60 \
		--port "$client_port" --join "127.0.0.1:$relay_port" ) \
		>"$work/$tag-c.log" 2>&1 &
	client=$!

	wait "$host" 2>/dev/null || true
	wait "$client" 2>/dev/null || true
	kill_pids "$relay"
	host=; client=; relay=

	# Success is that both ends got past the exchange and loaded the level.
	#
	# Not "both ran to the end": each process is given a fixed sixty tics, and
	# whichever reaches them first exits, leaving the other waiting for
	# commands that will never come. That is this harness ending the match,
	# not the handshake failing, and counting it as a failure put the measured
	# rate at 62% when the handshake itself was managing 92%. The map header
	# is printed the moment the level starts, which is the first thing that
	# happens after the exchange returns.
	if grep -q "^$arena - " "$work/$tag-h.log" &&
		grep -q "^$arena - " "$work/$tag-c.log"; then
		started=$((started + 1))
		outcome=started
	else
		# Which end never got there, and what it said it was waiting for.
		stuck=host
		grep -q "^$arena - " "$work/$tag-h.log" && stuck=client
		outcome="wedged ($stuck): $(grep -m1 -oE 'Still exchanging tic [0-9]+|waiting on:.*' \
			"$work/$tag-$(printf %s "$stuck" | cut -c1).log" 2>/dev/null |
			head -1 || echo 'said nothing')"
	fi
	printf '  ..   %-6s %s\n' "$tag" "$outcome"
done

rate=$((started * 100 / runs))
printf '  ..   %s of %s connections completed (%s%%)\n' "$started" "$runs" "$rate"

# Measured 24/24 after the fix at both 5% and 15%. The bound is below that
# rather than at it, because one machine's scheduler is not another's -- but
# it is well above the 79% the unfixed exchange manages, which is the
# regression this is here to catch.
check "a lost packet no longer wedges the start of a match" test "$rate" -ge 87

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: a lossy line does not stop a match from starting.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  HANDSHAKE_RUNS=%s HANDSHAKE_LOSS=%s %s %s %s\n' \
		"$runs" "$loss" "$0" "$build_dir" "$data_dir"
fi
exit "$status"
