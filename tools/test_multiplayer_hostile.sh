#!/bin/sh

# Regression test: a socket open to the internet, and what arrives on it.
#
# Milestone 7 of docs/multiplayer.md.
#
# The game reads structures straight off the wire. A datagram being at least
# sizeof(T) with the right type byte is enough for the fixed-size packets and
# not enough for the start packet: that one ends in a client array whose length
# is declared by a byte inside it, so "at least sizeof(struct)" was never the
# size that mattered. One forged datagram could tell a joining client there
# were 255 players, and the swap that walks their addresses would follow that
# count forty bytes past the end of the receive buffer, writing as it went.
#
# Three things are checked, and the last two are the ones worth having:
#
#   * The fuzzer and the engine still agree on the wire format, which the
#     engine states itself through --netvectors. The battery below used to
#     carry a hand-written copy of the packet layout, and that copy had drifted
#     twice: its NET_ enum had NewGame and TicCmd the wrong way round, and its
#     start packet assumed natural alignment when the real struct is packed. It
#     was firing well-formed nonsense at the wrong message types, and passing.
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
vectors="$work/netvectors.txt"
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
# Each launch gets a port of its own. Reusing one is a race: the previous
# process is killed but its socket is not necessarily released by the time the
# next one tries to bind, and the loser dies during startup with a message
# nobody reads, several checks before the one that then fails.
version_port=5144
lonehost_port=5145
# Nobody listens here; it is the address the join screen is told to dial, and
# the address the forged answers are sent from.
decoy_port=5999
version_decoy_port=5998
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

printf 'The shape of the packets\n'
if "$build_dir/ec7wolf" --netvectors "$vectors" >"$work/netvectors.log" 2>&1 &&
	[ -s "$vectors" ]; then
	printf '  ok   the engine described its wire format\n'
else
	printf '  FAIL the engine would not describe its wire format\n'
	tail -3 "$work/netvectors.log" 2>/dev/null | sed 's/^/         /'
	exit 1
fi
# --rounds 0 fires nothing: this is the fuzzer rebuilding the engine's own
# golden start packet and refusing to run if the bytes differ.
check "the fuzzer builds the same bytes the engine emits" \
	python3 "$here/netfuzz.py" 127.0.0.1 "$decoy_port" --vectors "$vectors" \
		--rounds 0
[ "$status" -eq 0 ] || exit 1

printf '\nA match in progress, shot at from outside\n'
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

python3 "$here/netfuzz.py" 127.0.0.1 "$host_port" --vectors "$vectors" \
	--rounds 3 --no-requests \
	>"$work/fuzz-host.log" 2>&1 || true
python3 "$here/netfuzz.py" 127.0.0.1 "$client_port" --vectors "$vectors" \
	--rounds 3 --no-requests \
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

python3 "$here/netfuzz.py" 127.0.0.1 "$victim_port" --vectors "$vectors" \
	--rounds 3 \
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

# A well-formed packet from a build that speaks a different protocol. Not
# rubbish, and not a survival question: what is under test is whether the
# refusal says so, because the alternative to naming it is joining and
# desynchronizing, which looks like a game bug for the rest of the evening.
printf '\nA host and a client that do not speak the same protocol\n'
play version --port "$version_port" --join "127.0.0.1:$version_decoy_port"
victim_pid=$!
sleep 4
check "the client is waiting" alive "$victim_pid"

python3 "$here/netfuzz.py" 127.0.0.1 "$version_port" --vectors "$vectors" \
	--only start-wrong-version --rounds 2 --from-port "$version_decoy_port" \
	>"$work/fuzz-version.log" 2>&1 || true

# Waited for rather than slept on: the client holds the message on screen for
# several seconds and a fixed sleep would either race it or pad every run.
waited=0
while [ "$waited" -lt 100 ]; do
	grep -q "network protocol" "$work/version.log" 2>/dev/null && break
	sleep 0.1
	waited=$((waited + 1))
done
if grep -q "Host speaks network protocol 1" "$work/version.log" 2>/dev/null &&
	grep -q "this game speaks 2" "$work/version.log" 2>/dev/null; then
	printf '  ok   it named both protocol versions\n'
else
	printf '  FAIL it did not say the versions differed\n'
	sed 's/\x08//g' "$work/version.log" | grep -vE '^\s*$' | tail -5 |
		sed 's/^/         /'
	status=1
fi

version_tics=$(grep -c '^tic ' "$work/version.checksum" 2>/dev/null || true)
[ -n "$version_tics" ] || version_tics=0
check "and refused rather than joining a game it cannot simulate" \
	test "$version_tics" -eq 0

kill_pids "${victim_pid:-}"
wait "$victim_pid" 2>/dev/null || true
victim_pid=

# And the same disagreement seen from the other side.
printf '\nA host answering a client that speaks another protocol\n'
play lonehost --host 2 --port "$lonehost_port"
host_pid=$!
sleep 3
check "the host is listening" alive "$host_pid"
python3 "$here/netfuzz.py" 127.0.0.1 "$lonehost_port" --vectors "$vectors" \
	--only request-wrong-version --rounds 2 >"$work/fuzz-hostver.log" 2>&1 || true
waited=0
while [ "$waited" -lt 100 ]; do
	grep -q "network protocol" "$work/lonehost.log" 2>/dev/null && break
	sleep 0.1
	waited=$((waited + 1))
done
if grep -q "network protocol 1, expected 2" "$work/lonehost.log" 2>/dev/null; then
	printf '  ok   the host refused it and said why\n'
else
	printf '  FAIL the host did not refuse a request from another protocol\n'
	sed 's/\x08//g' "$work/lonehost.log" | grep -vE '^\s*$' | tail -5 |
		sed 's/^/         /'
	status=1
fi
check "and is still listening for a client that can play" alive "$host_pid"
kill_pids "${host_pid:-}"
wait "$host_pid" 2>/dev/null || true
host_pid=

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: shot at from both ends, still standing, still playable.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
