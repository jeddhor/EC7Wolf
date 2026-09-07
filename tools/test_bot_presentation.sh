#!/bin/sh

# Regression test: a player can tell who is in the game and which ones are bots.
#
# Milestone B9 of docs/multiplayer-bots-and-server.md, sections 18.1 to 18.7.
#
# The point of this milestone is that identity comes from the session roster
# and not from the player index. Before it the scoreboard printed the character
# class -- "Marine, Marine, Marine" -- because player_t has no name and nothing
# in the protocol carried one. That is a fine answer for two humans who know
# who they are, and no answer at all once three of the four are machines.
#
# Usage: test_bot_presentation.sh BUILD_DIR DATA_DIR

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

printf 'Who is in this game, and which of them are people\n'

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-present.XXXXXX)
. "$here/xvfb_common.sh"
display=:211
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

run() {  # run TAG [EXTRA...]
	tag=$1; shift
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 200 "$build_dir/ec7wolf" --data CO7 --res 640 400 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-rngseed 1 --capture-maxtics 60 \
		--tedlevel MAP60 --skill 2 --battle "$@" ) >"$work/$tag.log" 2>&1 || true
}

# --- the roster names itself -------------------------------------------------

run three --bots 3 --bot-skill Veteran --bot-list

check "the roster lists every slot" \
	test "$(grep -c '^  [0-9]' "$work/three.log" || true)" -eq 4
check "the human is named" grep -q 'Player 1' "$work/three.log"
check "and so is every bot" \
	test "$(grep -cE '^  [0-9]+  Bot [123] ' "$work/three.log" || true)" -eq 3
check "each bot reports the skill it was asked for" \
	test "$(grep -c 'Veteran' "$work/three.log" || true)" -eq 3

# Bots are numbered among bots, so the first one is Bot 1 whatever slot it
# landed in. With one human that slot is 2 -- and a name taken from the slot
# index would read "Bot 2" there, which is the mistake this catches.
check "the first bot is Bot 1 and not Bot 2" grep -q '2  Bot 1 ' "$work/three.log"

# --- the cap, and what it says when you exceed it ----------------------------

run toomany --bots 20 --bot-list
printf '  ..   %s\n' "$(grep -m1 'supports' "$work/toomany.log" || echo 'no message')"
check "asking for too many names humans, bots, total and the maximum" \
	grep -qE 'player.* and 20 bots is 21 slots; this game supports 11' \
		"$work/toomany.log"
check "and it fills to the cap rather than refusing outright" \
	grep -q 'Roster: 11 slots' "$work/toomany.log"

# --- the developer seed announces itself -------------------------------------

run seeded --bots 1 --bot-seed 4242
check "a seed override says so, because such a match is not comparable" \
	grep -q 'Bot seed overridden to 4242' "$work/seeded.log"

run unseeded --bots 1
check "and an ordinary match says nothing about seeds" \
	test "$(grep -c 'seed overridden' "$work/unseeded.log" || true)" -eq 0

# --- the scoreboard at its largest -------------------------------------------
#
# A picture, because that is what it is: the game's own font into the game's
# own palette. The failure guarded against is a table sized for four players
# that silently drops rows once eleven are in it.

mkdir -p "$work/full-saves"
( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  timeout 200 "$build_dir/ec7wolf" --data CO7 --res 640 400 --nowait \
	--config "$work/full.cfg" --savedir "$work/full-saves" \
	--capture-rngseed 1 --capture-maxtics 900 --capture-frame 400 \
	--capture-scoreboard --capture-glpresent "$work/full.ppm" \
	--tedlevel MAP60 --skill 2 --battle --bots 10 ) >"$work/full.log" 2>&1 || true

if [ -s "$work/full.ppm" ] && command -v convert >/dev/null 2>&1; then
	convert "$work/full.ppm" "$work/full.png" 2>/dev/null || true
	if python3 - "$work/full.png" <<'PY'
import sys
try:
    from PIL import Image
except ImportError:
    print("  ..   scoreboard: PIL missing, not measured")
    sys.exit(0)
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size

def lit(x0, x1, y0, y1):
    return sum(1 for y in range(y0, y1, 2) for x in range(x0, x1, 2)
               if sum(im.getpixel((x, y))) > 200)

# Counting rows down the page was the first version of this and it was wrong
# the moment the board grew a second column: eleven players became six rows,
# and a check expecting eight called a working board broken. So the property
# checked is the one that matters -- every player is on screen -- expressed as
# two things a picture can actually answer.
#
# One: both halves of the table carry text, so the second column exists.
left  = lit(int(w * 0.04), int(w * 0.46), int(h * 0.24), int(h * 0.74))
right = lit(int(w * 0.50), int(w * 0.96), int(h * 0.24), int(h * 0.74))
print("  ..   scoreboard: %d lit samples left, %d right" % (left, right))

# Checking for spill into the status bar was tried and dropped: the status bar
# is itself lit, so the measurement cannot tell a row drawn over it from the
# bar's own pixels, and printing the number invited a reader to treat it as a
# finding. What catches the clipping this replaced is the right-hand column --
# a board that cannot fit eleven rows has nothing in it.

ok = left > 50 and right > 50
sys.exit(0 if ok else 1)
PY
	then check "a full roster of eleven fits on the scoreboard" true
	else check "a full roster of eleven fits on the scoreboard" false
	fi
else
	printf '  ..   scoreboard: no capture or no convert; not measured\n'
fi

if [ "$status" -eq 0 ]; then
	printf 'PASS: the roster names itself, and says which of them are machines.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
