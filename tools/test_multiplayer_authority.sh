#!/bin/sh

# Regression test: an authority speaking for slots that own no socket.
#
# Milestone B1 of docs/multiplayer-bots-and-server.md.
#
# S4 proved a slot with no keyboard gets a command, in one process. This is the
# same thing across a wire, where three new things can go wrong:
#
#   * the other machine does not know the slot exists, because a roster with a
#     peerless slot in it has to be told rather than inferred from an address
#     list;
#   * the two machines author different commands for it, because both ran the
#     producer instead of one authoring and the other receiving; and
#   * anyone at all can claim to speak for it, because a command used to say
#     nothing about whose it was -- the slot was the sender's address, and a
#     slot with no address had no way to be named or checked.
#
# So: a host with a scripted tape, a client that has never heard of it, and a
# link that delays, drops, duplicates and reorders. Both machines must finalize
# byte-identical commands for every slot and simulate identical worlds, and a
# peer that claims a slot it does not own must be refused and say so.
#
# The tape is not an AI. See test_multiplayer_commands.sh.
#
# Usage: test_multiplayer_authority.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdpyinfo python3; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-authority.XXXXXX)
. "$here/xvfb_common.sh"

display=:179
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${host_pid:-}" "${client_pid:-}" "${relay_pid:-}"
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

tics=150
map=MAP53

cat > "$work/t.tape" <<'EOF'
# Stand, then walk. Reads nothing, decides nothing.
0 0 0
repeat 20
0 35 0
repeat 400
loop
EOF

play() {   # play NAME ROLE_ARGS...
	name=$1
	shift
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--config "$work/$name.cfg" --savedir "$work/$name-saves" \
		--capture-rngseed 1 \
		--capture-checksum "$work/$name.checksum" \
		--capture-commands "$work/$name.commands" \
		--capture-players "$work/$name.players" \
		--capture-maxtics "$tics" --tedlevel "$map" --skill 2 --battle \
		--net-delay 6 "$@" >"$work/$name.log" 2>&1
	  echo $? > "$work/$name.rc" ) &
}

compare() {  # compare LABEL HOSTNAME CLIENTNAME
	label=$1; h=$2; c=$3
	hslots=$(awk 'NR>1{print $2}' "$work/$h.players" 2>/dev/null | sort -u | tr -d '\n')
	cslots=$(awk 'NR>1{print $2}' "$work/$c.players" 2>/dev/null | sort -u | tr -d '\n')
	printf '  ..   slots with a pawn: host %s, client %s\n' \
		"${hslots:-none}" "${cslots:-none}"
	check "$label: the client knows about the slot it was told about" \
		test "$hslots" = "$cslots" -a "$hslots" = "012"

	if [ -s "$work/$h.commands" ] && [ -s "$work/$c.commands" ]; then
		if diff -q "$work/$h.commands" "$work/$c.commands" >/dev/null; then
			printf '  ok   %s: both machines finalized byte-identical commands\n' "$label"
		else
			printf '  FAIL %s: the two disagreed about what was pressed\n' "$label"
			diff "$work/$h.commands" "$work/$c.commands" | head -4 |
				sed 's/^/         /'
			status=1
		fi
	else
		printf '  FAIL %s: no command trace\n' "$label"
		status=1
	fi

	if cmp -s "$work/$h.checksum" "$work/$c.checksum"; then
		printf '  ok   %s: and simulated identical worlds\n' "$label"
	else
		printf '  FAIL %s: identical commands but different worlds\n' "$label"
		status=1
	fi

	ticsrun=$(grep -c '^tic ' "$work/$h.checksum" 2>/dev/null || true)
	check "$label: the match ran to the end" test "${ticsrun:-0}" -ge "$tics"
}

# ---------------------------------------------------------------------------
printf 'A host speaking for a slot the client has never heard of\n'
mkdir -p "$work/h-saves" "$work/c-saves"
play h --host 2 --port 5195 --capture-tape "$work/t.tape"
host_pid=$!
sleep 3
play c --port 5196 --join "127.0.0.1:5195"
client_pid=$!
wait "$host_pid" "$client_pid" 2>/dev/null || true
host_pid=; client_pid=
compare clean h c

# The authority's slot has to be doing something, or identical commands would
# be identical nothing.
moved=$(awk '$2==2 {print $3":"$4}' "$work/h.players" 2>/dev/null | sort -u | wc -l)
printf '  ..   the authority-owned slot occupied %s tiles\n' "$moved"
check "the slot it spoke for actually moved" test "$moved" -ge 2

# ---------------------------------------------------------------------------
printf '\nThe same, over a link that mistreats it\n'
# Delay, jitter to reorder, loss to force resends, and duplication so a resend
# that arrives twice has to be harmless.
python3 "$here/netdelay.py" --listen 5197 --forward 127.0.0.1:5195 \
	--delay 25 --jitter 12 --loss 3 --duplicate 8 --seed 7 \
	>"$work/relay.log" 2>&1 &
relay_pid=$!
sleep 1

mkdir -p "$work/ih-saves" "$work/ic-saves"
play ih --host 2 --port 5195 --capture-tape "$work/t.tape"
host_pid=$!
sleep 3
play ic --port 5198 --join "127.0.0.1:5197"
client_pid=$!
wait "$host_pid" "$client_pid" 2>/dev/null || true
host_pid=; client_pid=
kill_pids "${relay_pid:-}"; relay_pid=
sed -n 's/.*\(dropped [0-9]*\).*/  ..   the link \1/p' "$work/relay.log" | tail -1
compare impaired ih ic

# ---------------------------------------------------------------------------
printf '\nA peer claiming a slot that is not its own\n'
# A genuine, connected client that puts a command for the authority's own
# slot into its bundle. Nothing outside the game can reach this check -- an
# unknown sender is refused long before ownership is consulted -- so the peer
# has to misbehave on purpose.
mkdir -p "$work/vh-saves" "$work/vc-saves"
play vh --host 2 --port 5199 --capture-tape "$work/t.tape"
host_pid=$!
sleep 3
play vc --port 5200 --join "127.0.0.1:5199" --capture-forge-slot 2
client_pid=$!
wait "$host_pid" "$client_pid" 2>/dev/null || true
host_pid=; client_pid=

if grep -q "does not own" "$work/vh.log" 2>/dev/null; then
	printf '  ok   the host refused the commands and said so\n'
	sed -n 's/.*\(Refused [0-9]* command.*\)/  ..   \1/p' "$work/vh.log" | tail -1
else
	printf '  FAIL a forged command for another slot was not refused\n'
	sed 's/\x08//g' "$work/vh.log" | grep -vE '^\s*$' | tail -5 | sed 's/^/         /'
	status=1
fi

# And the refusal has to be a refusal, not a stall or a divergence: the match
# still finished and the two still agree.
compare forged vh vc

# The forged command asked for full-speed forward. If it had ever been applied
# the authority's slot would have run somewhere the client's copy did not.
if cmp -s "$work/vh.checksum" "$work/vc.checksum"; then
	printf '  ok   and the slot it tried to drive was unaffected\n'
else
	printf '  FAIL the forged command changed something\n'
	status=1
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: one machine speaks for the slots it owns, and only those.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
