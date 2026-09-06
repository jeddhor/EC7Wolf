#!/bin/sh

# A benchmark, not a gate. Prints distributions; asserts nothing.
#
# Section 17.6: "keep deterministic regressions separate from probabilistic
# benchmarks". test_bot_skill.sh is the regression -- it has bounds and it
# fails. This has neither. It exists to answer "what changed?" after a trait is
# adjusted, which is the loop section 17.6 describes: adjust one trait family
# at a time, with recorded before-and-after metrics.
#
# Section 17.4 is the reason it reports distributions rather than one accuracy
# number: "a bot that misses half the time by alternately snapping perfectly
# and firing 90 degrees away is not human-like", and both of those bots score
# fifty percent. The time series and the circumstances are the measurement.
#
# Usage: bot_report.sh BUILD_DIR DATA_DIR [SEEDS...]

set -eu

if [ "$#" -lt 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [SEEDS...]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
shift 2
seeds=${*:-"1 5 9"}

command -v Xvfb >/dev/null 2>&1 || { printf 'Xvfb is missing\n' >&2; exit 2; }

work=$(mktemp -d /tmp/ec7wolf-report.XXXXXX)
. "$here/xvfb_common.sh"
display=:209
xvfb_start "$display" "$work/xvfb.log" 640x400x24 || exit 1
cleanup() {
	xvfb_stop
	if [ "${KEEP_WORK:-0}" = "1" ]; then printf 'kept: %s\n' "$work"; else rm -rf "$work"; fi
	true
}
trap cleanup EXIT INT TERM

printf 'EC7Wolf bot report\n'
printf '  build %s\n  seeds %s\n\n' "$build_dir" "$seeds"

for skill in Recruit Marine Veteran Elite; do
	for seed in $seeds; do
		mkdir -p "$work/$skill-$seed-saves"
		( cd "$data_dir"
		  DISPLAY=$display SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
		  timeout 300 "$build_dir/ec7wolf" --data CO7 --res 320 200 --nowait \
			--vid-renderer software \
			--config "$work/$skill-$seed.cfg" \
			--savedir "$work/$skill-$seed-saves" \
			--capture-rngseed "$seed" --bot-skill "$skill" \
			--capture-bots "$work/$skill-$seed.bots" \
			--capture-players "$work/$skill-$seed.players" \
			--capture-maxtics 2100 \
			--tedlevel MAP60 --skill 2 --battle --bots 3 ) \
			>"$work/$skill-$seed.log" 2>&1 || true
	done
done

python3 - "$work" "$seeds" <<'PY'
import sys, os, re

work, seeds = sys.argv[1], sys.argv[2].split()
levels = ["Recruit", "Marine", "Veteran", "Elite"]

def pct(n, d):
    return (100.0 * n / d) if d else 0.0

print("%-8s %7s %7s %8s %9s %8s %8s %9s" %
      ("level", "shots", "onTgt", "acc%", "react", "turn/tic", "retreat", "deaths"))
print("-" * 72)

for level in levels:
    shots = hits = retreats = deaths = 0
    reactions, turns = [], []
    for seed in seeds:
        log = os.path.join(work, "%s-%s.log" % (level, seed))
        trace = os.path.join(work, "%s-%s.bots" % (level, seed))
        players = os.path.join(work, "%s-%s.players" % (level, seed))
        if os.path.exists(log):
            text = open(log, errors="replace").read()
            for name, add in (("hitscan", "shots"), ("oncone", "hits"),
                              ("retreats", "retreats")):
                m = re.findall(r"Capture: bots .*?%s=(\d+)" % name, text)
                if m:
                    v = int(m[-1])
                    if add == "shots": shots += v
                    elif add == "hits": hits += v
                    else: retreats += v
        if os.path.exists(trace):
            for line in open(trace, errors="replace"):
                m = re.search(r" noticed .*after=(\d+)", line)
                if m:
                    reactions.append(int(m.group(1)))
                if " behavior dead" in line:
                    deaths += 1
        # Turn rate, from the body rather than from anything the bot claims.
        if os.path.exists(players):
            prev = {}
            for line in open(players, errors="replace"):
                f = line.split()
                if not f or f[0].startswith("#"):
                    continue
                slot, ang, hp = f[1], float(f[4]), int(f[5])
                x, y = int(f[10]), int(f[11])
                if slot in prev:
                    pa, ph, px, py = prev[slot]
                    moved = (x - px) ** 2 + (y - py) ** 2
                    if hp > 0 and ph > 0 and hp <= ph and moved <= (1 << 30):
                        d = abs((ang - pa + 180.0) % 360.0 - 180.0)
                        if d > 0:
                            turns.append(d)
                prev[slot] = (ang, hp, x, y)

    def band(v):
        if not v:
            return "n/a"
        v = sorted(v)
        return "%d-%d" % (v[0], v[-1])

    def p95(v):
        if not v:
            return 0.0
        v = sorted(v)
        return v[min(len(v) - 1, int(len(v) * 0.95))]

    print("%-8s %7d %7d %7.1f%% %9s %8.1f %8d %9d" %
          (level, shots, hits, pct(hits, shots), band(reactions), p95(turns),
           retreats, deaths))

print()
print("react is the observed span of reaction delays in tics; turn/tic is the")
print("95th percentile of per-tic heading change in degrees, measured from the")
print("recorded pawn and not from the command the bot asked for.")
PY
