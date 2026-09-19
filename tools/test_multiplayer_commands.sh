#!/bin/sh

# Regression test: a slot with neither a keyboard nor a socket still gets a
# command, and no producer can say anything the game does not allow.
#
# Milestone S4 of docs/multiplayer-bots-and-server.md.
#
# The engine had exactly one command producer -- PollControls, sampling this
# machine's keyboard into control[ConsolePlayer] -- and everything else in a
# netgame arrived from a socket. That describes the world completely until a
# slot needs a command and has neither, which is every bot and every slot on a
# server with no player of its own.
#
# So sampling and finalizing became two steps, and this checks the seam:
#
#   * a slot driven by nothing but a fixed tape spawns, walks, shoots, scores
#     and dies like an ordinary player, offline, with no socket anywhere;
#   * a producer that asks for axes outside the human range is clamped, and a
#     producer that asks for escape, pause, the automap or the scoreboard has
#     them removed -- both counted, so the test can insist it happened rather
#     than infer it from behavior;
#   * every active slot gets exactly one command every tic; and
#   * two machines in a netgame finalize identical commands, which is a
#     different question from whether they simulate identical worlds and is
#     worth asking separately.
#
# The tape is not an AI and is not a step toward one. It reads no world state
# and makes no decisions. Its whole job is to prove the boundary carries a
# command for a slot that cannot produce one for itself; the AI arrives in
# Phase B and arrives behind this same interface.
#
# Usage: test_multiplayer_commands.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdpyinfo; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-commands.XXXXXX)
. "$here/xvfb_common.sh"

display=:178
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	kill_pids "${host_pid:-}" "${client_pid:-}"
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

# Traced where ptrace is allowed, so "offline" can be proven rather than
# assumed. Containers commonly forbid it; the run still happens and the socket
# check says it was skipped rather than passing quietly.
tracer=""
if command -v strace >/dev/null 2>&1 &&
	strace -f -e trace=socket -o /dev/null true >/dev/null 2>&1; then
	tracer=yes
fi

solo() {   # solo NAME TICS EXTRA...
	name=$1; ticcount=$2; shift 2
	trace=""
	[ -n "$tracer" ] && trace="strace -f -e trace=socket -o $work/$name.strace"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 $trace "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--config "$work/$name.cfg" --savedir "$work/$name-saves" \
		--capture-rngseed 1 \
		--capture-players "$work/$name.players" \
		--capture-commands "$work/$name.commands" \
		--capture-maxtics "$ticcount" --tedlevel MAP53 --skill 2 --battle \
		"$@" ) >"$work/$name.log" 2>&1 || true
}

field() {  # field NAME KEY -- pull one number out of the summary line
	sed -n "s/.*Capture: commands .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" |
		tail -1
}

# ---------------------------------------------------------------------------
printf 'A slot with no keyboard and no socket\n'

cat > "$work/duel.tape" <<'EOF'
# Stand for a moment, then hold fire. No world queries, no decisions.
0 0 0
repeat 30
0 0 0 attack
repeat 400
loop
EOF

solo duel 400 --capture-tape "$work/duel.tape" \
	--capture-duel 0 1 --capture-fire 40 --capture-ammo

slots=$(awk '$1 ~ /^[0-9]+$/ {print $2}' "$work/duel.players" 2>/dev/null |
	sort -u | tr -d '\n')
printf '  ..   slots that had a pawn: %s\n' "${slots:-none}"
check "the tape's slot got a pawn of its own" test "$slots" = "01"

# Frags on both sides: each killed the other at least once.
frags0=$(awk '$2==0 {f=$7} END {print f+0}' "$work/duel.players" 2>/dev/null)
frags1=$(awk '$2==1 {f=$7} END {print f+0}' "$work/duel.players" 2>/dev/null)
low0=$(awk '$2==0 {if(min==""||$6<min) min=$6} END {print min+0}' "$work/duel.players")
low1=$(awk '$2==1 {if(min==""||$6<min) min=$6} END {print min+0}' "$work/duel.players")
printf '  ..   frags %s and %s; lowest health %s and %s\n' \
	"$frags0" "$frags1" "$low0" "$low1"
check "the player killed the tape" test "$frags0" -ge 1
check "and the tape killed the player" test "$frags1" -ge 1
check "both of them died to do it" test "$low0" -eq 0 -a "$low1" -eq 0

# Dying in an offline deathmatch puts you back in the arena rather than
# restarting the level: the tic stream is continuous across the death.
ticspan=$(awk '$2==0 {n++} END {print n+0}' "$work/duel.players")
printf '  ..   %s continuous tics of slot 0, across its death and return\n' "$ticspan"
check "the level did not restart when the player died" test "$ticspan" -ge 390
check "and the player came back" \
	test "$(awk '$2==0 {h=$6} END {print h+0}' "$work/duel.players")" -gt 0

# The whole duel -- two pawns, two frags, two deaths -- with no network
# underneath it. This is the Phase S exit criterion in one run.
if [ -n "$tracer" ]; then
	opened=$(grep -c 'AF_INET' "$work/duel.strace" 2>/dev/null || true)
	[ -n "$opened" ] || opened=0
	printf '  ..   %s internet sockets opened during the duel\n' "$opened"
	check "two players fought without a socket between them" \
		test "$opened" -eq 0
else
	printf '  ..   strace cannot trace here; socket check skipped\n'
fi

# ---------------------------------------------------------------------------
printf '\nA slot that walks, rather than one that is placed\n'

cat > "$work/walk.tape" <<'EOF'
0 0 0
repeat 20
0 35 0
repeat 120
loop
EOF

solo walk 160 --capture-tape "$work/walk.tape"
tiles=$(awk '$2==1 {print $3":"$4}' "$work/walk.players" 2>/dev/null | sort -u | wc -l)
printf '  ..   the tape visited %s distinct tiles\n' "$tiles"
check "a command tape moves a pawn through the ordinary movement code" \
	test "$tiles" -ge 3

# ---------------------------------------------------------------------------
printf '\nA producer that asks for things it may not have\n'

cat > "$work/bad.tape" <<'EOF'
# Axes far outside the human range, and buttons belonging to this machine's
# own screen rather than to the game.
500 -900 400 attack esc pause automap c7map statusbar scoreboard
repeat 100
loop
EOF

solo bad 100 --capture-tape "$work/bad.tape"
clamped=$(field bad clamped)
stripped=$(field bad stripped)
missing=$(field bad missing)
printf '  ..   clamped %s axes, stripped %s buttons, %s missing commands\n' \
	"${clamped:-?}" "${stripped:-?}" "${missing:-?}"
check "the out-of-range axes were clamped" test "${clamped:-0}" -gt 0
check "the local UI buttons were stripped" test "${stripped:-0}" -gt 0
check "and nothing went missing" test "${missing:-1}" -eq 0

# And the command that actually reached the slot says so.
line=$(awk '$2==1' "$work/bad.commands" | sed -n '2p')
turn=$(printf '%s' "$line" | awk '{print $3}')
fwd=$(printf '%s' "$line" | awk '{print $4}')
strafe=$(printf '%s' "$line" | awk '{print $5}')
pressed=$(printf '%s' "$line" | awk '{print $6}')
printf '  ..   the slot received turn %s forward %s strafe %s buttons %s\n' \
	"$turn" "$fwd" "$strafe" "$pressed"
check "every axis is inside the range the game was balanced for" \
	test "$turn" -le 100 -a "$turn" -ge -100 \
		-a "$fwd" -le 100 -a "$fwd" -ge -100 \
		-a "$strafe" -le 100 -a "$strafe" -ge -100
# bt_attack is bit 0 and is the only one that should have survived.
check "the attack it asked for survived" \
	test "$(printf '%s' "$pressed" | cut -c1)" = "1"
check "and nothing else did" \
	test "$(printf '%s' "$pressed" | cut -c2- | tr -d '0')" = ""

# ---------------------------------------------------------------------------
printf '\nOne command per slot per tic, and no more\n'
dupes=$(awk '$1 ~ /^[0-9]+$/ {k=$1":"$2; n[k]++} END {c=0; for(k in n) if(n[k]!=1) c++; print c+0}' \
	"$work/duel.commands")
check "no slot was given two commands for one tic" test "$dupes" -eq 0
lines=$(awk '$1 ~ /^[0-9]+$/' "$work/duel.commands" | wc -l)
seqs=$(awk '$1 ~ /^[0-9]+$/ {print $1}' "$work/duel.commands" | sort -u | wc -l)
printf '  ..   %s commands over %s sequences for 2 slots\n' "$lines" "$seqs"
check "every sequence carried a command for both slots" \
	test "$lines" -eq "$((seqs * 2))"

# ---------------------------------------------------------------------------
printf '\nTwo machines finalizing the same commands\n'

host_port=5181
client_port=5182
nettics=120

netplay() {  # netplay NAME ROLE_ARGS...
	name=$1; shift
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--config "$work/$name.cfg" --savedir "$work/$name-saves" \
		--capture-rngseed 1 \
		--capture-checksum "$work/$name.checksum" \
		--capture-commands "$work/$name.commands" \
		--capture-maxtics "$nettics" --tedlevel MAP51 --skill 2 --battle \
		--net-delay 6 "$@" >"$work/$name.log" 2>&1
	  echo $? > "$work/$name.rc" ) &
}

mkdir -p "$work/nhost-saves" "$work/nclient-saves"
netplay nhost --host 2 --port "$host_port"
host_pid=$!
sleep 3
netplay nclient --port "$client_port" --join "127.0.0.1:$host_port"
client_pid=$!
wait "$host_pid" "$client_pid" 2>/dev/null || true
host_pid=; client_pid=

if [ -s "$work/nhost.commands" ] && [ -s "$work/nclient.commands" ]; then
	# Compare the commands rather than the digests: a digest that differs says
	# only that something did, and the first differing line says which slot on
	# which tic, which is the whole difference between a bug report and a
	# shrug.
	if diff -q "$work/nhost.commands" "$work/nclient.commands" >/dev/null; then
		printf '  ok   both machines finalized byte-identical commands\n'
	else
		printf '  FAIL the two machines disagreed about what was pressed\n'
		diff "$work/nhost.commands" "$work/nclient.commands" | head -4 |
			sed 's/^/         /'
		status=1
	fi
	if cmp -s "$work/nhost.checksum" "$work/nclient.checksum"; then
		printf '  ok   and simulated identical worlds from them\n'
	else
		printf '  FAIL identical commands but different worlds\n'
		status=1
	fi
	nmissing=$(field nhost missing)
	check "no slot went without a command on the wire" test "${nmissing:-1}" -eq 0
else
	printf '  FAIL the netgame produced no command trace\n'
	sed 's/\x08//g' "$work/nhost.log" | grep -vE '^\s*$' | tail -5 |
		sed 's/^/         /'
	status=1
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: a slot with no keyboard and no socket plays by the same rules.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
