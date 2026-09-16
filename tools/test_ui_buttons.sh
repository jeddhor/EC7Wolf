#!/bin/sh

# Regression test: a held UI button is one press, and the menu button reaches
# the menu.
#
# Both reported from a pad. Command::Apply writes the *finalized* command back
# into control[], and finalization strips the buttons that are not gameplay --
# the menu, the automap, the floor map, the scoreboard, pause. PollControls
# then derived "held last frame" from control[], so those buttons were never
# held: holding the floor map button re-toggled the map every tic, which looks
# like the map flashing, and a pad's Start button (which sets bt_esc) had the
# bit removed before CheckKeys could see it, so it did nothing at all.
#
# A keyboard hid half of it: Escape is also checked as a raw scancode, so the
# key worked while the button did not.
#
# Measured against the broken behaviour before this was trusted: holding the
# floor map button for sixty tics toggled it sixty times.
#
# Usage: test_ui_buttons.sh BUILD_DIR DATA_DIR

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

printf 'A held button is one press\n'

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-ui.XXXXXX)
. "$here/xvfb_common.sh"
display=:221
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

hold() {  # hold TAG BUTTON TICS
	tag=$1; button=$2; tics=$3
	mkdir -p "$work/$tag-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 120 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$tag.cfg" --savedir "$work/$tag-saves" \
		--capture-hold-button "$button" 60 "$tics" \
		--capture-maxtics 200 \
		--tedlevel MAP60 --skill 2 ) >"$work/$tag.log" 2>&1 || true
	grep -c "ui action" "$work/$tag.log" || true
}

# Sixty tics is most of a second -- a real press on a pad, and long enough that
# a per-tic re-toggle is unmistakable rather than a near miss.
floormap=$(hold map c7map 60)
automap=$(hold am automap 60)
printf '  ..   held for 60 tics: floor map acted %s time(s), automap %s\n' \
	"$floormap" "$automap"
check "holding the floor map button toggles it once" test "${floormap:-0}" -eq 1
check "and so does the automap button" test "${automap:-0}" -eq 1

printf '\nThe menu button opens the menu\n'

# bt_esc is what a pad's Start sets (id_in.cpp). The keyboard's Escape is also
# a raw scancode, so this is the only check that covers the pad.
menu=$(hold esc esc 30)
printf '  ..   menu opened %s time(s)\n' "$menu"
check "the menu button reaches the control panel" test "${menu:-0}" -ge 1
check "and opens it once, not once a tic" test "${menu:-0}" -eq 1

if [ "$status" -eq 0 ]; then
	printf 'PASS: held UI buttons act once, and the menu button works.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
