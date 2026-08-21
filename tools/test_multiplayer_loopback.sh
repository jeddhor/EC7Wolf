#!/bin/sh

# Regression test: two players, one machine, and identical simulations.
#
# Milestone 0 of docs/multiplayer.md. Lockstep multiplayer is correct only
# while every machine simulates the same world from the same inputs, and when
# that stops being true the symptom is not a crash -- the two games simply
# drift apart, and whoever is playing discovers it by shooting at someone who
# is no longer there. So the thing this gate compares is not "did it run" but
# the per-tic determinism checksum from both sides.
#
# The engine already writes that checksum: --capture-checksum logs one line per
# tic. Two instances that agree on every line simulated the same game.
#
# Both sides pass --tedlevel, and both must: it routes through NewGame, which
# calls Net::NewGame, which exchanges the map and difficulty and takes the
# arbiter's. A client without it falls into the menu instead and the host then
# blocks for ever in ExchangePacket waiting for tic commands from a player who
# is reading a menu.
#
# The two instances need different local ports. Host and client both bind
# InitVars.port, so on one machine they collide, and the client's join address
# carries the host's port explicitly -- "--join host:port" -- because --port is
# the local bind, not the destination.
#
# Usage: test_multiplayer_loopback.sh BUILD_DIR DATA_DIR [TICS]

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [TICS]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
tics=${3:-120}
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdpyinfo; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-mp.XXXXXX)
. "$here/xvfb_common.sh"

display=:157
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill "${host_pid:-0}" "${client_pid:-0}" 2>/dev/null || true
	xvfb_stop
	rm -rf "$work"
}
trap cleanup EXIT INT TERM

host_port=5029
client_port=5030
map=${MAP:-MAP51}

play() {   # play NAME ROLE_ARGS...
	name=$1
	shift
	(
		cd "$data_dir"
		DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		timeout 120 "$build_dir/ec7wolf" \
			--data CO7 --res 320 200 --nowait \
			--config "$work/$name.cfg" --savedir "$work/$name-saves" \
			--capture-rngseed 1 \
			--capture-checksum "$work/$name.checksum" \
			--capture-maxtics "$tics" \
			--tedlevel "$map" --skill 2 \
			"$@" >"$work/$name.log" 2>&1
		echo $? > "$work/$name.rc"
	) &
}

mkdir -p "$work/host-saves" "$work/client-saves"

play host --host 2 --port "$host_port"
host_pid=$!
sleep 3
play client --port "$client_port" --join "127.0.0.1:$host_port"
client_pid=$!

wait "$host_pid" "$client_pid" 2>/dev/null || true

status=0
report() { printf '  %-6s %s\n' "$1" "$2"; }

for side in host client; do
	rc=$(cat "$work/$side.rc" 2>/dev/null || echo "?")
	case "$rc" in
		0) report "$side" "finished cleanly" ;;
		124) report "$side" "TIMED OUT -- it never reached $tics tics"; status=1 ;;
		*) report "$side" "exited $rc"; status=1 ;;
	esac
done

for side in host client; do
	if [ ! -s "$work/$side.checksum" ]; then
		printf '\nFAIL: %s wrote no checksum, so it simulated nothing.\n' "$side"
		printf 'Last lines of its log:\n'
		sed 's/\x08//g; s/\.\{3,\}/../g' "$work/$side.log" | grep -vE '^\s*$' | tail -6 | sed 's/^/    /'
		exit 1
	fi
done

host_tics=$(grep -c '^tic ' "$work/host.checksum" || true)
client_tics=$(grep -c '^tic ' "$work/client.checksum" || true)
report host "$host_tics tics"
report client "$client_tics tics"

if [ "$host_tics" -lt "$tics" ] || [ "$client_tics" -lt "$tics" ]; then
	printf '\nFAIL: expected %s tics from each side.\n' "$tics"
	exit 1
fi

# The comparison the whole gate exists for.
if diff -q "$work/host.checksum" "$work/client.checksum" >/dev/null 2>&1; then
	printf '\nPASS: %s tics, both sides identical every tic (%s)\n' \
		"$host_tics" "$(grep '^summary' "$work/host.checksum" || true)"
	exit "$status"
fi

printf '\nFAIL: the two simulations diverged.\n'
first=$(diff "$work/host.checksum" "$work/client.checksum" | grep -m1 '^<' || true)
printf '  first tic where they differ: %s\n' "${first:-unknown}"
printf '  host   | client\n'
diff -y --suppress-common-lines "$work/host.checksum" "$work/client.checksum" | head -5 | sed 's/^/  /'
exit 1
