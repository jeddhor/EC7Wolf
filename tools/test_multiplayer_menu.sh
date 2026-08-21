#!/bin/sh

# Regression test: joining a game from the menu.
#
# Milestone 2 of docs/multiplayer.md. The netcode worked before any of this and
# could only be reached with --join on a command line, which is not a feature
# anybody can use. This drives the menu the way a player would -- New Mission,
# down past the ranks to Multiplayer, type an address, Start -- and then checks
# the only thing that settles whether it worked: that a host on the other end
# gets a second player and the two simulate the same game.
#
# Asserting that the typed text reached Net::InitVars would be easier and would
# prove less. The address is not the point; connecting is.
#
# The window is found by name rather than by process id, because the game is
# started from a subshell and $! is the subshell. That cost an hour once.
#
# Usage: test_multiplayer_menu.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in Xvfb xdotool import; do
	command -v "$tool" >/dev/null 2>&1 || { printf 'SKIP: %s is missing\n' "$tool"; exit 0; }
done
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-mpmenu.XXXXXX)
. "$here/xvfb_common.sh"
display=:173
port=5029    # what the setup screen offers by default, so nothing is typed here
xvfb_start "$display" "$work/xvfb.log" 1280x800x24 || exit 1
cleanup() {
	kill ${host_pid:-0} ${client_pid:-0} 2>/dev/null || true
	xvfb_stop
	if [ -n "${KEEP_WORK:-}" ]; then
		printf '\nkept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
}
trap cleanup EXIT INT TERM

status=0
# Takes the test as arguments rather than $? -- under `set -e` a bare failing
# test kills the script before the report runs, which is how this gate first
# managed to fail with no output whatsoever.
check() {
	message=$1
	shift
	if "$@"; then
		printf '  ok   %s\n' "$message"
	else
		printf '  FAIL %s\n' "$message"
		status=1
	fi
}

# The far end: an ordinary host, waiting.
(
	cd "$data_dir"
	DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	timeout 150 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--config "$work/host.cfg" --savedir "$work/host-s" \
		--capture-rngseed 1 --capture-checksum "$work/host.checksum" \
		--capture-maxtics 90 --net-delay 10 \
		--tedlevel MAP51 --skill 2 --host 2 --port "$port" \
		>"$work/host.log" 2>&1
) &
host_pid=$!

# The near end: no network arguments at all. Everything comes from the menu.
(
	cd "$data_dir"
	DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	timeout 150 "$build_dir/ec7wolf" --data CO7 --res 1280 800 --nowait \
		--config "$work/client.cfg" --savedir "$work/client-s" \
		--capture-rngseed 1 --capture-checksum "$work/client.checksum" \
		--capture-maxtics 90 \
		>"$work/client.log" 2>&1
) &
client_pid=$!

sleep 10

# Both games are called EC7Wolf, so the window has to be picked by size: the
# client is the wide one, the host runs at 320x200. Sending the menu keys to
# the host's window instead is silent -- it is not in a menu, so nothing
# happens and the client simply never joins.
window=""
for candidate in $(DISPLAY=$display xdotool search --onlyvisible --name "EC7Wolf" 2>/dev/null); do
	geometry=$(DISPLAY=$display xdotool getwindowgeometry "$candidate" 2>/dev/null | grep Geometry || true)
	case "$geometry" in
		*1280x800*) window=$candidate ;;
	esac
done
if [ -z "$window" ]; then
	printf 'FAIL: the client window (1280x800) never appeared\n'
	DISPLAY=$display xdotool search --onlyvisible --name "EC7Wolf" 2>/dev/null | while read -r w; do
		DISPLAY=$display xdotool getwindowgeometry "$w" 2>/dev/null | sed 's/^/    /'
	done
	exit 1
fi
printf '  ..   driving the client window %s\n' "$window"
DISPLAY=$display xdotool windowfocus --sync "$window" 2>/dev/null || true
DISPLAY=$display xdotool mousemove --window "$window" 20 20 2>/dev/null || true

# Focus is taken again before every key. Two games are running on a display
# with no window manager, and the second one's window maps part way through
# this sequence and takes the focus with it -- after which every keystroke goes
# to a game that is not in a menu, silently.
press() {
	DISPLAY=$display xdotool windowfocus --sync "$window" 2>/dev/null || true
	DISPLAY=$display xdotool key --clearmodifiers "$1"
	sleep "${2:-1}"
}

press Escape 1.5
press Escape 2
press Return 2.5          # New Mission -> the rank ladder

DISPLAY=$display import -window root "$work/ranks.png" 2>/dev/null || true

# Captain is preselected, and the section label is skipped, so three steps down
# reach Multiplayer: Major, President, Multiplayer.
press Down 0.8
press Down 0.8
press Down 1
press Return 2.5

DISPLAY=$display import -window root "$work/setup.png" 2>/dev/null || true

# The screen opens on the address, ready to type.
press Return 1.5
DISPLAY=$display xdotool type --delay 60 "127.0.0.1"
sleep 1.5
press Return 1.5

DISPLAY=$display import -window root "$work/address.png" 2>/dev/null || true

# Down to Start, past the port, and go.
# Three steps to Start: Port, Connection, Start. Players and Game are skipped
# because joining leaves them disabled, and the list wraps -- five steps come
# back round to the address, which is a silent way to press the wrong thing.
press Down 0.7
press Down 0.7
press Down 0.9
DISPLAY=$display import -window root "$work/before-start.png" 2>/dev/null || true
press Return 3
DISPLAY=$display import -window root "$work/after-start.png" 2>/dev/null || true

wait "$host_pid" "$client_pid" 2>/dev/null || true

# Did the menu actually put the client into the host's game?
check "the client entered a game from the menu" test -s "$work/client.checksum"
check "the host got its second player" test -s "$work/host.checksum"

if [ ! -s "$work/client.checksum" ] || [ ! -s "$work/host.checksum" ]; then
	for side in host client; do
		printf '\n--- %s, last lines ---\n' "$side"
		sed 's/\x08//g; s/\.\{3,\}/../g' "$work/$side.log" | grep -vE '^\s*$' | tail -6 | sed 's/^/    /'
	done
fi

if [ -s "$work/client.checksum" ] && [ -s "$work/host.checksum" ]; then
	client_tics=$(grep -c '^tic ' "$work/client.checksum" || true)
	host_tics=$(grep -c '^tic ' "$work/host.checksum" || true)
	printf '  ..   %s tics on the host, %s on the client\n' "$host_tics" "$client_tics"

	# They joined at different moments, so compare where they overlap: every
	# tic both of them simulated has to agree.
	# Process substitution is a bashism and this is /bin/sh, so the two
	# sorted lists go through files.
	awk '/^tic /{print $2" "$3}' "$work/host.checksum" | sort -k1,1 > "$work/h.pairs"
	awk '/^tic /{print $2" "$3}' "$work/client.checksum" | sort -k1,1 > "$work/c.pairs"
	join -j 1 -o 1.2,2.2 "$work/h.pairs" "$work/c.pairs" > "$work/paired" 2>/dev/null || true
	shared=$(wc -l < "$work/paired")
	differing=$(awk '$1 != $2' "$work/paired" | wc -l)
	printf '  ..   %s tics simulated by both\n' "$shared"

	check "they played together for a useful stretch" test "$shared" -ge 30
	check "and agreed on every tic they shared" test "$differing" -eq 0
	if [ "$differing" -ne 0 ]; then
		awk '$1 != $2' "$work/paired" | head -3 | sed 's/^/       /'
	fi
fi

exit "$status"
