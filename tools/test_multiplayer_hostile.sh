#!/bin/sh

# Regression test: a socket open to the internet, and what arrives on it.
#
# Milestone 7 of docs/multiplayer.md.
#
# The game reads structures straight off the wire. CheckPacketType proves a
# datagram is at least sizeof(T) and carries the right type byte, which is
# enough for the fixed-size packets and not enough for the start packet: that
# one ends in a client array whose length is declared by a byte inside it, so
# "at least sizeof(struct)" was never the size that mattered. Before this
# milestone one forged datagram could tell a joining client there were 255
# players, and the loop that copies their addresses would walk Client[11] off
# the end of itself, writing as it went.
#
# Two things are checked, and the second is the one worth having:
#
#   * Nothing falls over. The host and a joining client are both shot at with
#     a fixed battery of empty, truncated, oversized, mistyped and lying
#     packets, and both have to still be running afterward.
#   * The game still works. A real client then joins the host that was just
#     shot at, and the two play a match and agree on every tic of it. Surviving
#     is easy if the survivor is a wreck; this says it is not.
#
# tools/netfuzz.py holds the battery, deliberately fixed rather than random: a
# gate that fails one run in fifty on an input nobody can reproduce is worse
# than no gate.
#
# Usage: test_multiplayer_hostile.sh BUILD_DIR DATA_DIR

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

work=$(mktemp -d /tmp/ec7wolf-hostile.XXXXXX)
. "$here/xvfb_common.sh"

display=:154
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${host_pid:-}" "${client_pid:-}" "${victim_pid:-}"
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

host_port=5141
client_port=5142
victim_port=5143
# Nobody listens here; it is the address the join screen is told to dial, and
# the address the forged answers are sent from.
decoy_port=5999
tics=120

status=0
check() {
	message=$1; shift
	if "$@"; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

play() {  # play NAME ROLE_ARGS...
	name=$1
	shift
	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" \
		--data CO7 --res 320 200 --nowait \
		--config "$work/$name.cfg" --savedir "$work/$name-saves" \
		--capture-rngseed 1 --capture-checksum "$work/$name.checksum" \
		--capture-maxtics "$tics" --tedlevel MAP53 --skill 2 --battle \
		--net-delay 6 "$@" >"$work/$name.log" 2>&1
	  echo $? > "$work/$name.rc" ) &
}

alive() { kill -0 "$1" 2>/dev/null; }

printf 'A match in progress, shot at from outside\n'
# Fired at a running match rather than at a host still waiting for players.
# A host that is waiting will accept a connection request from anyone -- that
# is what hosting means, and a bare 0x00 byte is a well-formed request -- so
# shooting at one only proves that somebody can join, which is not a defect and
# not what this gate is about.
play host --host 2 --port "$host_port"
host_pid=$!
sleep 3
play client --port "$client_port" --join "127.0.0.1:$host_port"
client_pid=$!
sleep 4

check "the host is up" alive "$host_pid"
check "the client is up" alive "$client_pid"

python3 "$here/netfuzz.py" 127.0.0.1 "$host_port" --rounds 3 --no-requests \
	>"$work/fuzz-host.log" 2>&1 || true
python3 "$here/netfuzz.py" 127.0.0.1 "$client_port" --rounds 3 --no-requests \
	>"$work/fuzz-client.log" 2>&1 || true
sed -n '$p' "$work/fuzz-host.log" | sed 's/^/  ..   at the host: /'
sed -n '$p' "$work/fuzz-client.log" | sed 's/^/  ..   at the client: /'

wait "$host_pid" "$client_pid" 2>/dev/null || true
host_pid=; client_pid=

for side in host client; do
	if [ ! -s "$work/$side.checksum" ]; then
		printf '  FAIL %s simulated nothing\n' "$side"
		sed 's/\x08//g' "$work/$side.log" | grep -vE '^\s*$' | tail -5 | sed 's/^/         /'
		status=1
	fi
done

if [ -s "$work/host.checksum" ] && [ -s "$work/client.checksum" ]; then
	host_tics=$(grep -c '^tic ' "$work/host.checksum" || true)
	client_tics=$(grep -c '^tic ' "$work/client.checksum" || true)
	printf '  ..   %s tics on the host, %s on the client\n' "$host_tics" "$client_tics"
	check "the match ran to the end anyway" \
		test "$host_tics" -ge "$tics" -a "$client_tics" -ge "$tics"
	if cmp -s "$work/host.checksum" "$work/client.checksum"; then
		printf '  ok   and the two agreed on every tic of it\n'
	else
		printf '  FAIL the two disagreed while being shot at\n'
		diff "$work/host.checksum" "$work/client.checksum" | head -4 | sed 's/^/         /'
		status=1
	fi
fi

printf '\nA client on a join screen, answered by the wrong party\n'
# The most exposed the game ever is: an open socket, waiting, willing to
# believe whatever answers. The forged start packets are sent *from the address
# it dialled*, so the source check cannot be what rejects them -- what is under
# test here is whether the contents are examined at all.
play victim --port "$victim_port" --join "127.0.0.1:$decoy_port"
victim_pid=$!
sleep 4
check "it is waiting" alive "$victim_pid"

python3 "$here/netfuzz.py" 127.0.0.1 "$victim_port" --rounds 3 \
	--from-port "$decoy_port" >"$work/fuzz-victim.log" 2>&1 || true
sed -n '$p' "$work/fuzz-victim.log" | sed 's/^/  ..   at the join screen: /'
sleep 2

check "it survived being answered with rubbish" alive "$victim_pid"

if grep -q "malformed start packet" "$work/victim.log" 2>/dev/null; then
	printf '  ok   and rejected the forged start packets by name\n'
else
	printf '  FAIL nothing was rejected, so nothing was examined\n'
	status=1
fi

# A client that believed one of those packets would have left the join screen
# and started simulating. Judged on its checksum log rather than on anything it
# printed: stdout to a file is block-buffered, so a line saying what it did may
# never be flushed by a process that is then killed.
# grep -c prints its zero and *also* exits non-zero, so "|| echo 0" appends a
# second one and the comparison gets "0\n0".
victim_tics=$(grep -c '^tic ' "$work/victim.checksum" 2>/dev/null || true)
[ -n "$victim_tics" ] || victim_tics=0
check "and simulated nothing, rather than starting a game of 255" \
	test "$victim_tics" -eq 0

kill_pids "${victim_pid:-}"
wait "$victim_pid" 2>/dev/null || true
victim_pid=

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: shot at from both ends, still standing, still playable.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
