#!/bin/sh

# Regression test: the three screens a multiplayer match puts in front of you.
#
# Milestone 6 of docs/multiplayer.md.
#
#   * The scoreboard, held up during a match.
#   * The tally when a match ends.
#   * The screen a player stares at while joining, which has to look unlike a
#     crash.
#
# All three are pictures, so all three are checked as pictures. The scoreboard
# is checked by running the same match twice from the same seed, once with the
# key held and once without, and requiring the two frames to differ -- which is
# a stronger statement than "something was drawn", because it says the
# difference is the scoreboard and not the weather.
#
# The tally photographs itself. It is on screen for a few seconds at a moment
# decided by whoever reaches the frag limit first: no frame number finds it,
# and waiting for its message in the log does not work either, because stdout
# to a file is block-buffered and the line lands long after the page has gone.
# --capture-tally lets the page say when it is ready.
#
# The join screen is sampled twice a few seconds apart and the samples must
# differ. A waiting screen that shows the same pixels for eleven seconds is
# indistinguishable from a hung one, which was the complaint this milestone
# exists to answer.
#
# Usage: test_multiplayer_presentation.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
command -v import >/dev/null 2>&1 || { printf 'SKIP: ImageMagick is missing\n'; exit 0; }
python3 -c "import PIL" >/dev/null 2>&1 || { printf 'SKIP: Pillow is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-present.XXXXXX)
. "$here/xvfb_common.sh"

display=:155
xvfb_start "$display" "$work/xvfb.log" 1280x800x24 || exit 1
cleanup() {
	kill_pids "${pid0:-}" "${pid1:-}"
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

# How different two images are, as a percentage of pixels that changed.
differs() {  # differs A B MIN_PERCENT
	python3 - "$1" "$2" "$3" <<'PY'
import sys
from PIL import Image, ImageChops
a = Image.open(sys.argv[1]).convert("RGB")
b = Image.open(sys.argv[2]).convert("RGB")
if a.size != b.size:
    print("size mismatch", file=sys.stderr); sys.exit(1)
diff = ImageChops.difference(a, b).convert("L")
changed = sum(1 for p in diff.getdata() if p > 8)
pct = 100.0 * changed / (a.size[0]*a.size[1])
print("%.1f%% of pixels differ" % pct, file=sys.stderr)
sys.exit(0 if pct >= float(sys.argv[3]) else 1)
PY
}

not_blank() {
	python3 - "$1" <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB")
lo, hi = im.getextrema()[0][0], max(c[1] for c in im.getextrema())
print("brightest channel value %d" % hi, file=sys.stderr)
sys.exit(0 if hi > 40 else 1)
PY
}

# A two-player match. The host takes the pictures; only the host stops at a
# frame, because two instances stopping at the same one leaves whichever quits
# first waiting on a player who has gone.
match() {  # match TAG HOST_EXTRA...
	tag=$1; shift
	common="--data CO7 --res 1280 800 --nowait --capture-rngseed 7
	        --tedlevel MAP60 --skill 2 --battle --net-delay 6
	        --capture-duel 0 1 --capture-fire 40 --capture-ammo"

	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" $common \
		--config "$work/$tag-h.cfg" --savedir "$work/$tag-hs" \
		--host 2 --port 5171 "$@" >"$work/$tag-h.log" 2>&1 ) &
	pid0=$!
	sleep 3
	# shellcheck disable=SC2086
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 150 "$build_dir/ec7wolf" $common --capture-maxtics 900 \
		--config "$work/$tag-c.cfg" --savedir "$work/$tag-cs" \
		--port 5172 --join "127.0.0.1:5171" >"$work/$tag-c.log" 2>&1 ) &
	pid1=$!
	wait "$pid0" 2>/dev/null || true
	kill_pids "${pid1:-}"
	wait "$pid1" 2>/dev/null || true
	pid0=; pid1=
}

printf 'The scoreboard, held up during a match\n'
match plain  --capture-maxtics 900 --capture-frame 200 \
	--capture-glpresent "$work/plain.png"
match board  --capture-maxtics 900 --capture-frame 200 --capture-scoreboard \
	--capture-glpresent "$work/board.png"

if [ -s "$work/plain.png" ] && [ -s "$work/board.png" ]; then
	# Same seed, same tic, same everything but the held key: whatever differs
	# is the scoreboard.
	check "holding the key changes the picture" differs "$work/plain.png" "$work/board.png" 5
	check "and there is something to see" not_blank "$work/board.png"
else
	printf '  FAIL one of the two frames was never written\n'
	status=1
fi

printf '\nThe tally when a match ends\n'
match tally --capture-maxtics 900 --fraglimit 1 --capture-tally "$work/tally.png"

if [ -s "$work/tally.png" ]; then
	check "the page appeared" not_blank "$work/tally.png"
	# It is a page, not the game: it must not look like the frame before it.
	check "and it is not just the match still showing" \
		differs "$work/tally.png" "$work/plain.png" 40
else
	printf '  FAIL the tally never photographed itself\n'
	status=1
fi

printf '\nThe join screen, waiting on a host that is not there\n'
# Nothing is listening on this port, so this is the screen a player gets when
# the address is wrong or the port is closed.
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 40 "$build_dir/ec7wolf" \
	--data CO7 --res 1280 800 --nowait --config "$work/join.cfg" \
	--savedir "$work/join-s" --tedlevel MAP60 --skill 2 \
	--port 5173 --join "127.0.0.1:5999" >"$work/join.log" 2>&1 ) &
pid0=$!
sleep 8
DISPLAY=$display import -window root "$work/join-a.png" 2>/dev/null || true
sleep 5
DISPLAY=$display import -window root "$work/join-b.png" 2>/dev/null || true
kill_pids "${pid0:-}"
wait "$pid0" 2>/dev/null || true
pid0=

if [ -s "$work/join-a.png" ] && [ -s "$work/join-b.png" ]; then
	check "it is showing something" not_blank "$work/join-a.png"
	# Five seconds apart. A screen that has not changed at all in that time is
	# one a player cannot tell from a hang, which is the complaint this
	# milestone exists to answer.
	check "and it is still moving five seconds later" \
		differs "$work/join-a.png" "$work/join-b.png" 0.05
else
	printf '  FAIL the join screen was never captured\n'
	status=1
fi

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: the scoreboard, the tally and a join screen that looks alive.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
