#!/bin/sh

# Regression test: a lump whose dimensions do not fit in an int.
#
# The engine decides what a file is by reading its first few bytes and doing
# arithmetic on them. Two of those sniffers multiplied a pair of 16-bit values
# straight out of the lump:
#
#   WORD Width = LittleShort(header[0]);
#   WORD Height = LittleShort(header[1]);
#   if(file.GetLength() == Width*Height+4)   // 64768 * 47104 overflows int
#
# Both promote to int, and the product of two large 16-bit values does not fit
# in one. That is undefined behaviour reached from data the engine did not
# create -- every lump in every archive it opens, and since E13 an archive can
# be a resource pack a player downloaded from somebody else.
#
# So this builds a pk3 containing a lump crafted to hit exactly that path: a
# width and a height whose product leaves the range of an int, and a length
# that matches neither sniffer, so the answer is "not a texture" and the
# arithmetic to reach it is the whole point. Loaded under the sanitizers,
# which is the only way to see the fault at all -- without them the overflow
# is silent and the game starts normally either way.
#
# Needs a sanitizer build; skips without one. See docs/undefined-behaviour.md.
#
# Usage: test_untrusted_lumps.sh SANITIZER_BUILD_DIR DATA_DIR

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s SANITIZER_BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" 2>/dev/null && pwd) || {
	printf 'SKIP: no such build directory: %s\n' "$1"; exit 0; }
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)

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
if ! ldd "$build_dir/ec7wolf" 2>/dev/null | grep -q 'libubsan\|libasan'; then
	printf 'SKIP: %s/ec7wolf is not a sanitizer build\n' "$build_dir"
	exit 0
fi

work=$(mktemp -d /tmp/ec7wolf-lumps.XXXXXX)
. "$here/xvfb_common.sh"
display=:269
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "$status" -ne 0 ] || [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
	true
}
trap cleanup EXIT INT TERM

printf 'A lump that lies about its size\n'

python3 - "$work/hostile.pk3" <<'PY'
import struct, sys, zipfile

# 0xFD00 by 0xB800 -- 64768 by 47104, whose product is 3,051,171,872 and does
# not fit in a signed 32-bit int. The rest is filler: the length deliberately
# matches neither "width*height+4" nor "+8", so both sniffers say no and the
# only thing under test is the arithmetic they did to get there.
header = struct.pack('<HH', 0xFD00, 0xB800)
body = header + b'\x00' * 64

with zipfile.ZipFile(sys.argv[1], 'w') as pack:
    # In graphics/ so the texture manager looks at it, and named as a lump
    # rather than a map so nothing else tries to parse it.
    pack.writestr('graphics/HOSTILE.lmp', body)
    # A second one whose dimensions are individually plausible and whose
    # product still overflows, in case a fix clamped the wrong one.
    pack.writestr('graphics/HOSTIL2.lmp', struct.pack('<HH', 0xFFFF, 0xFFFF) + b'\x00' * 16)
PY

[ -s "$work/hostile.pk3" ] || { printf '  FAIL the pack was not built\n'; exit 1; }

( cd "$data_dir"
  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
  UBSAN_OPTIONS=print_stacktrace=1 ASAN_OPTIONS=detect_leaks=0 \
  timeout 600 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
	--vid-renderer software --file "$work/hostile.pk3" \
	--config "$work/cfg" --savedir "$work/sv" \
	--capture-rngseed 1 --tedlevel MAP01 --skill 2 \
	--capture-maxtics 120 ) >"$work/game.log" 2>&1 || true

overflows=$(grep -c 'signed integer overflow' "$work/game.log" || true)
printf '  ..   %s signed overflow report(s) while loading the pack\n' "$overflows"
if [ "${overflows:-0}" -gt 0 ]; then
	grep -m2 -A3 'signed integer overflow' "$work/game.log" | sed 's/^/         /'
fi

check "the engine started with the pack loaded" \
	grep -q 'Capture: summary' "$work/game.log"
check "no sniffer overflowed on it" test "${overflows:-0}" -eq 0
check "and nothing was read out of bounds" \
	sh -c "! grep -q 'ERROR: AddressSanitizer' '$work/game.log'"

# And nothing else undefined either. The pack is untrusted input, so this is
# the run most likely to reach a parser nobody has pointed a sanitizer at
# before; anything not already accounted for in tools/ubsan-accepted.txt is a
# finding about handling somebody else's data.
printf '  ..   '
check "no undefined behaviour beyond what is already accepted" \
	python3 "$here/ubsan_check.py" "$work/game.log" \
		--accepted "$here/ubsan-accepted.txt" --root "$repo" --no-stale

printf '\n'
if [ "$status" -eq 0 ]; then
	printf 'PASS: a lump with impossible dimensions is rejected arithmetically.\n'
else
	printf 'FAIL: see above. Reproduce with:\n'
	printf '  %s %s %s\n' "$0" "$build_dir" "$data_dir"
fi
exit "$status"
