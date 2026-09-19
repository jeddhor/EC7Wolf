#!/bin/sh

# Regression test: bots and humans together, over a link that misbehaves.
#
# Milestone B10 of docs/multiplayer-bots-and-server.md: "loopback latency, loss
# and reorder mixed matches".
#
# Bots only exist on the authority. Every other machine receives their commands
# the same way it receives a person's, and section 19.1 is the rule the whole
# design rests on: a bot bug may make a bad decision, but it must never make
# two machines disagree. That claim is easy to satisfy on a clean loopback
# socket, where nothing is ever late, lost or out of order. This gate takes it
# away.
#
# tools/netdelay.py sits between the two peers and delays, jitters, drops and
# duplicates datagrams. Jitter is what produces reorder: a packet held longer
# than the one behind it arrives second. Loss and duplication exercise the
# retransmit and the de-duplicate paths, which a clean link never touches.
#
# The link is clean for the first seconds, and lossy only once the match is
# running. That is not a softening of the test, it is aim: Net::NewGame's
# level-start exchange has no recovery from a lost packet and hangs about half
# the time at 5% loss. That is a known defect, measured and recorded under M7
# in docs/multiplayer.md, and it belongs to the multiplayer handshake rather
# than to the bots. Writing this gate without the clean window made it
# rediscover that instead of testing anything about bots: the first run wedged
# before tic 10 with both processes waiting for each other until they timed
# out. Delay and jitter apply from the first packet either way.
#
# So the claim here is exactly: once a mixed match is under way, a link that
# loses, reorders and duplicates does not make the two machines disagree.
#
# What is asserted is not "it felt all right" but that the two recorded matches
# are byte-identical: same pawns, same positions, same health, same frags, on
# every tic. A command that arrived twice, or late, or not at all, and changed
# the world on one machine and not the other would show up here as a difference
# in the trace, and everything else -- the bots' aim, their routes, their
# decisions -- is downstream of that.
#
# Usage: test_bot_netplay.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-botnet.XXXXXX)
. "$here/xvfb_common.sh"
display=:249
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

seed=11
host_port=5181
client_port=5182
relay_port=5183
delay=40
jitter=15
loss=2
duplicate=1
arena=MAP53
bots=4
# Long enough for the join and the level-start exchange: the client is started
# three seconds in and the exchange is done well inside the next few.
clean_for=12

printf 'Bots and people, over a link that loses and reorders\n'
printf '  ..   %sms delay, %sms jitter, %s%% loss, %s%% duplicate, %s bots, seed %s\n' \
	"$delay" "$jitter" "$loss" "$duplicate" "$bots" "$seed"
printf '  ..   the link is clean for the first %ss, so this tests the match and not the handshake\n' \
	"$clean_for"

python3 "$here/netdelay.py" --listen "$relay_port" \
	--forward "127.0.0.1:$host_port" --delay "$delay" --jitter "$jitter" \
	--loss "$loss" --duplicate "$duplicate" --seed "$seed" \
	--impair-after "$clean_for" \
	>"$work/relay.log" 2>&1 &
relay=$!
sleep 1

play() {  # play TAG ROLE...
	tag=$1; shift
	mkdir -p "$work/$tag-saves"
	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  exec timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed "$seed" --tedlevel "$arena" --skill 2 --battle \
		--net-delay 6 --capture-players "$work/$tag.tr" \
		--capture-maxtics 1200 "$@" ) >"$work/$tag.log" 2>&1 &
}

# The host owns the roster, so only it is told about the bots; the client
# learns of them from the roster exchange.
play host --host 2 --port "$host_port" --bots "$bots" --bot-skill Veteran
host=$!
sleep 3
play client --port "$client_port" --join "127.0.0.1:$relay_port"
client=$!
wait "$host" 2>/dev/null || true
wait "$client" 2>/dev/null || true
host=; client=

host_lines=$(wc -l < "$work/host.tr" 2>/dev/null || echo 0)
client_lines=$(wc -l < "$work/client.tr" 2>/dev/null || echo 0)
printf '  ..   host recorded %s lines, client %s\n' "$host_lines" "$client_lines"
printf '  ..   relay: %s\n' "$(tail -1 "$work/relay.log" 2>/dev/null || echo 'said nothing')"

check "both machines played a full match" \
	sh -c "test ${host_lines:-0} -gt 3000 && test ${client_lines:-0} -gt 3000"

# Six slots: two people and four bots, on both machines.
host_slots=$(awk '$1 !~ /^#/ { print $2 }' "$work/host.tr" 2>/dev/null | sort -u | wc -l)
printf '  ..   slots recorded by the host: %s\n' "$host_slots"
check "the match really was two people and four bots" test "${host_slots:-0}" -eq 6

# Compared over the tics both machines actually simulated, not over whole
# files. Each process is given a fixed number of tics; whichever reaches them
# first exits, and the other notices it has gone and ends the match a few tics
# later -- so the two recordings routinely differ in length by a handful of
# lines with nothing wrong. Measured on a failing run: 7183 lines against
# 7201, identical over all 7183. Comparing the files whole turned that into
# "the two machines disagreed", which is the one thing this gate exists to
# detect and would then have cried wolf about.
common=$host_lines
[ "$client_lines" -lt "$common" ] && common=$client_lines
head -n "$common" "$work/host.tr" > "$work/host-common.tr"
head -n "$common" "$work/client.tr" > "$work/client-common.tr"
printf '  ..   comparing the %s lines both machines recorded\n' "$common"
check "and the two machines recorded the same match, tic for tic" \
	sh -c "test ${common:-0} -gt 3000 && \
		cmp -s '$work/host-common.tr' '$work/client-common.tr'"

# Matched on the engine's own words. This looked for "abandon" at first and
# matched "abandoned=0" in the bots' own counter line -- a gate reporting its
# own grep rather than anything about the game.
# "left the game" is not checked for, because it is the expected end of this
# match: one side runs out of tics and exits, and the other says so. A real
# disagreement says Desync, and the trace comparison above is the stronger
# check anyway.
check "neither side reported a desync" \
	sh -c "! grep -qE 'Desync:' '$work/host.log' '$work/client.log'"

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: a mixed match survives a bad link and stays in step.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  %s %s %s   (seed %s, %sms/%sms/%s%%/%s%%)\n' \
		"$0" "$build_dir" "$data_dir" "$seed" "$delay" "$jitter" "$loss" "$duplicate"
fi
exit "$status"
