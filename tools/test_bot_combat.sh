#!/bin/sh

# Regression test: bots fight, and lose sometimes.
#
# Milestone B6 of docs/multiplayer-bots-and-server.md, section 16.
#
# The fact this whole milestone turns on is section 16.2, and it is verified in
# the engine rather than assumed: Corridor 7's hitscan weapons call
# player_t::FindTarget, which acquires anything within ten degrees --
# CheckVisibility(check, ANGLE_90/9) -- and then applies ordinary weapon
# randomness. So an aim error of two degrees is not an aim error at all. A bot
# with a slightly noisy reticle that fires only while pointed at its target
# hits every time, and no amount of tuning the noise changes that.
#
# Which makes accuracy a two-sided check. A bot that never misses is cheating;
# a bot that never hits is not an opponent. The interesting range is in
# between, and this gate demands it.
#
# Accuracy is measured against where the target actually is, not against
# whether the bot finished turning. The second is what the first version
# measured and it scored 36 of 37 -- because the aim point already has the
# error in it, so a bot that settles neatly onto a badly wrong bearing looks
# perfect. Measured properly the same run scores 25 of 37.
#
# Usage: test_bot_combat.sh BUILD_DIR DATA_DIR

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

printf 'Bots that fight, and miss\n'

# The source rule first, before anything runs. Section 16.5: request bt_attack
# and let the weapon state machine decide when a shot happens. A brain that
# reaches for attackheld, a psprite, a cooldown or an ammunition count is
# taking a shot the rules did not give it, and no behavioural test would
# notice -- the bot would simply fire faster than a person can.
# Comment lines are stripped first. The rule is about what the code does, and
# the first version of this check failed on a comment promising that the code
# does not do it.
# Section 16.5 for the trigger and 16.6 for the weapon: both are requested
# through the ordinary button and neither is assigned. A bot that sets
# PendingWeapon switches instantly, which no player can do, and nothing in a
# match would look wrong -- it would just always have the right gun out.
banned='(attackheld|psprite|SetPSprite|ReadyWeapon->[A-Za-z]+ *=|(Pending|Ready)Weapon *=[^=]|ammo[A-Za-z]* *=)'
code() { sed 's;//.*;;' "$@" | grep -vE '^\s*\*'; }
forced=$(code "$here/../src/g_bot.cpp" "$here/../src/g_combat.cpp" 2>/dev/null |
	grep -cE "$banned" || true)
if [ "${forced:-0}" -ne 0 ]; then
	code "$here/../src/g_bot.cpp" "$here/../src/g_combat.cpp" |
		grep -nE "$banned" | head -3 | sed 's/^/         /'
fi
check "the brain asks for the trigger and forces nothing else" \
	test "${forced:-0}" -eq 0

command -v Xvfb >/dev/null 2>&1 || { printf 'SKIP: Xvfb is missing\n'; exit 0; }
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }
[ -f "$data_dir/MAPTEMP.CO7" ] || { printf 'SKIP: no Corridor 7 data in %s\n' "$data_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-combat.XXXXXX)
. "$here/xvfb_common.sh"
display=:201
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

tics=2100
map=${MAPS:-MAP53}

run() {  # run SEED TAG
	mkdir -p "$work/$2-saves"
	( cd "$data_dir"
	  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
	  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
		--vid-renderer software \
		--config "$work/$2.cfg" --savedir "$work/$2-saves" \
		--capture-rngseed "$1" \
		--capture-bots "$work/$2.bots" \
		--capture-players "$work/$2.players" \
		--capture-perception "$work/$2.see" \
		--capture-maxtics "$tics" \
		--tedlevel "$map" --skill 2 --battle --bots 3 ) >"$work/$2.log" 2>&1 || true
}

field() { sed -n "s/.*Capture: bots .*$2=\([0-9a-f]*\).*/\1/p" "$work/$1.log" | tail -1; }

for seed in 1 5; do
	tag="s$seed"
	run "$seed" "$tag"
	if [ ! -s "$work/$tag.bots" ]; then
		printf '  FAIL seed %s: no bot trace\n' "$seed"
		status=1
		continue
	fi

	targets=$(field "$tag" targets)
	shots=$(field "$tag" shots)
	oncone=$(field "$tag" oncone)
	frags=$(awk 'NR>1{f[$2]=$7} END{t=0; for(k in f) t+=f[k]; print t+0}' "$work/$tag.players")
	deaths=$(awk 'NR>1 && $6<=0 {print $2":"$1}' "$work/$tag.players" | sort -u | wc -l)
	accuracy=0
	[ "${shots:-0}" -gt 0 ] && accuracy=$(( ${oncone:-0} * 100 / shots ))

	printf '  ..   seed %s: %s targets, %s shots, %s%% on target, %s frags, %s death-tics\n' \
		"$seed" "${targets:-?}" "${shots:-?}" "$accuracy" "$frags" "$deaths"

	guns=$(field "$tag" guns)
	check "seed $seed: bots found somebody to shoot at" test "${targets:-0}" -ge 1
	check "seed $seed: and picked a weapon for the range" test "${guns:-0}" -ge 1
	check "seed $seed: and shot at them" test "${shots:-0}" -ge 5
	check "seed $seed: kills happened" test "${frags:-0}" -ge 1
	check "seed $seed: and somebody died for them" test "${deaths:-0}" -ge 1

	# Both sides. Ten degrees of auto-aim means a careful bot cannot miss, so
	# an accuracy near a hundred is evidence the error model is not reaching
	# outside the cone -- not evidence of skill.
	check "seed $seed: it hits often enough to be an opponent (>= 30%)" \
		test "$accuracy" -ge 30
	check "seed $seed: and misses often enough to be beatable (<= 90%)" \
		test "$accuracy" -le 90

	# Fairness: a bot may only shoot at somebody it was told about. Every
	# target must have been noticed first -- acting on a sighting before the
	# reaction delay releases it is the same as having no reaction time.
	python3 - "$work/$tag.bots" <<'PY'
import sys, re
noticed, bad = set(), []
for line in open(sys.argv[1]):
    f = line.split()
    if len(f) < 3 or f[0].startswith("#"):
        continue
    who = re.search(r"slot=(\d+)", line)
    if not who:
        continue
    key = (f[1], who.group(1))
    if f[2] == "noticed":
        noticed.add(key)
    elif f[2] == "target" and key not in noticed:
        bad.append((f[0], key))
if bad:
    print("  FAIL seed: %d targets were never noticed first, e.g. %s"
          % (len(bad), bad[0]))
    sys.exit(1)
print("  ok   seed: every target was a contact the bot had been told about")
PY
	[ $? -eq 0 ] || status=1
done

d1=$(field s1 brain); d2=$(field s5 brain)
printf '  ..   brain digests %s and %s\n' "${d1:-?}" "${d2:-?}"
check "different seeds fight differently" test "${d1:-x}" != "${d2:-y}"

if [ "$status" -eq 0 ]; then
	printf 'PASS: bots fight, hit, miss, and die.\n'
else
	printf 'FAIL: see above.\n'
fi
exit "$status"
