#!/bin/sh

# Regression test: the campaign ends the way CORR7CD.EXE ends it.
#
# The original's ending (a2cc) is the SEQFOUR cinematic, the last floor's
# status report, MISSION HIT/MISS RATIO -- the bonus floors' hit/miss page
# over the whole mission's shooting, a block per hundred shots -- and then the
# high scores, but only if the score ranks. There is no victory page: the
# "CONGRATULATIONS!" routine in the executable is never called. The port used
# to show an invented one instead of the mission page. The runs:
#
#   finale    MAP40 left with seeded totals: 1234 shots and 567 hits from
#             earlier floors, 113 and 66 on this one, a score of 54321 -- the
#             numbers a DOS run used. The page must count 1347 and 633, pay
#             6440 points, and draw 13 and 6 blocks; the high-score row must
#             be the original's navy bar in a yellow frame, typed into.
#   unranked  the same with nothing scored: the page still shows, and the
#             high scores are skipped because the score does not rank.
#   held      a direction held while the page draws: the original's per-block
#             TicDelay(50) lets the tally count up visibly, and letting go
#             finishes it at once.
#   carried   MAP39's shooting reaches MAP40's totals (added at the floor's
#             setup), survives a save and a load, and a bonus floor's counts
#             join the totals too.
#
# Screens are sampled at 320x200 from a 640x400 software-rendered window, so
# palette colours come back exact.
#
# Usage: test_corridor7_ending.sh BUILD_DIR DATA_DIR   (both absolute)

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
for command in xvfb-run xdotool import python3 stdbuf; do
	if ! command -v "$command" >/dev/null 2>&1; then
		printf 'required command is missing: %s\n' "$command" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-ending.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# Symlinks keep the data directory untouched; the pk3 is the build's own. No
# video directory, so the cinematic is skipped and the pages follow at once.
mkdir -p "$work/data"
for f in "$data_dir"/*.CO7 "$data_dir/CORR7CD.EXE"; do
	[ -e "$f" ] && ln -s "$f" "$work/data/$(basename "$f")"
done
cp "$build_dir/ec7wolf.pk3" "$work/data/"
export EN_BUILD="$build_dir" EN_WORK="$work"

# The finale's pages wait for keys, so these runs are driven by what the log
# says rather than by a clock: each key goes in once the page it answers has
# been reached, and each screenshot is taken after the page's own log line.
drive() { # $1 = tag, $2 = mode (finale|unranked|held), $3... = capture flags
	EN_TAG=$1 EN_MODE=$2
	shift 2
	EN_ARGS="$*"
	export EN_TAG EN_MODE EN_ARGS
	mkdir -p "$work/saves-$EN_TAG"
	timeout 180s xvfb-run -a -s '-screen 0 640x400x24' sh -c '
		cd "$EN_WORK/data"
		export SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11
		log="$EN_WORK/$EN_TAG.log" shot="$EN_WORK/$EN_TAG"
		# Line-buffered, or the lines this waits for sit in stdio until exit.
		stdbuf -oL -eL "$EN_BUILD/ec7wolf" --data CO7 --nowait --no-upscale --vid-renderer software \
			--res 640 400 --config "$EN_WORK/$EN_TAG.cfg" --savedir "$EN_WORK/saves-$EN_TAG" \
			--tedlevel MAP40 --skill 2 --capture-rngseed 7 --capture-exitlevel 35 \
			$EN_ARGS >"$log" 2>&1 &
		pid=$!
		wait_for() { # $1 = pattern; up to 30 s
			n=0
			while [ "$n" -lt 150 ] && ! grep -q "$1" "$log" 2>/dev/null; do
				kill -0 "$pid" 2>/dev/null || return 1
				sleep 0.2; n=$((n + 1))
			done
			grep -q "$1" "$log"
		}
		if wait_for "completing level"; then
			sleep 3
			import -window root "$shot-status.png"
			if [ "$EN_MODE" = held ]; then
				xdotool keydown Right; sleep 0.3
				xdotool key space
				wait_for "hit/miss:" || true
				sleep 1.2; import -window root "$shot-held1.png"
				sleep 1.4; import -window root "$shot-held2.png"
				xdotool keyup Right; sleep 1
				import -window root "$shot-released.png"
			else
				xdotool key space
				wait_for "hit/miss:" || true
				sleep 1.5; import -window root "$shot-mission.png"
				xdotool key space
				if [ "$EN_MODE" = finale ]; then
					sleep 3; import -window root "$shot-scores.png"
					for k in a c e; do xdotool key $k; sleep 0.2; done
					xdotool key Return; sleep 1.5
					import -window root "$shot-named.png"
				else
					wait_for "does not reach the high scores" || true
				fi
			fi
		fi
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	' || true
}

# The carried runs need only their floor reports dismissed: one K every two
# seconds, which nothing in play is bound to.
play() { # $1 = tag, $2 = map, $3... = capture flags
	EN_TAG=$1 EN_MAP=$2
	shift 2
	EN_ARGS="$*"
	export EN_TAG EN_MAP EN_ARGS
	mkdir -p "$work/saves-$EN_TAG"
	timeout 180s xvfb-run -a -s '-screen 0 640x400x24' sh -c '
		cd "$EN_WORK/data"
		export SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11
		"$EN_BUILD/ec7wolf" --data CO7 --nowait --no-upscale --vid-renderer software \
			--res 320 200 --config "$EN_WORK/$EN_TAG.cfg" --savedir "$EN_WORK/saves-$EN_TAG" \
			--tedlevel "$EN_MAP" --skill 2 --capture-rngseed 7 --capture-inventory \
			$EN_ARGS >"$EN_WORK/$EN_TAG.log" 2>&1 &
		pid=$!
		n=0
		while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 30 ]; do
			sleep 2
			xdotool key --clearmodifiers k 2>/dev/null || true
			n=$((n + 1))
		done
		kill "$pid" 2>/dev/null || true
		wait "$pid" 2>/dev/null || true
	' || true
}

seeds="--capture-shots 113 66 --capture-mission-shots 1234 567 --capture-score 54321"
drive finale finale $seeds &
drive unranked unranked --capture-shots 0 0 --capture-mission-shots 0 0 --capture-score 0 &
drive held held $seeds &
play carried MAP39 --capture-shots 50 20 --capture-exitlevel 35 \
	--capture-save 60 carried.ec7 --capture-maxtics 80 &
play bonus MAP41 --capture-shots 113 66 --capture-exitlevel 35 --capture-maxtics 80 &
wait
mkdir -p "$work/saves-loaded"
cp "$work/saves-carried/carried.ec7" "$work/saves-loaded/" 2>/dev/null || true
play loaded MAP01 --capture-load 5 carried.ec7 --capture-maxtics 30

status=0
python3 - "$work" <<'PY' || status=$?
import re
import sys
from pathlib import Path

work = Path(sys.argv[1])
failed = False

def check(ok, message):
    global failed
    print(("  ok  " if ok else "FAIL ") + message)
    failed |= not ok

def log(tag):
    path = work / f"{tag}.log"
    return path.read_text(errors="replace") if path.exists() else ""

def screen(name):
    """A 640x400 capture reduced to the original's 320x200, or None."""
    path = work / name
    if not path.exists():
        return None
    from PIL import Image
    image = Image.open(path).convert("RGB")
    w, h = image.size
    pixels = image.load()
    return [[pixels[x, y] for x in range(0, w, 2)] for y in range(0, h, 2)]

def count(img, colour, x0, y0, x1, y1, exact=True):
    hits = 0
    for row in img[y0:y1]:
        for px in row[x0:x1]:
            hits += px == colour if exact else colour(px)
    return hits

SALMON = (255, 101, 105)      # palette 0x57: shot blocks, the earned row's text
NAVY = (16, 16, 81)           # palette 0x30: the earned row's bar
YELLOW = (255, 255, 0)        # palette 0x6f: its frame
magenta = lambda p: p[0] > 150 and p[1] < 60 and p[2] > 150   # 0xb7: hit blocks

def floors(tag):
    seen = {}
    for line in log(tag).splitlines():
        if line.startswith("inventory "):
            fields = dict(f.split("=", 1) for f in line.split()[1:])
            seen.setdefault(fields["map"], fields)
    return seen

# finale
text = log("finale")
check("Corridor 7 mission hit/miss: 1347 shots, 633 hits, 46% accuracy, 6440 point bonus" in text,
      "finale: the mission page adds this floor to the totals and pays 6440")
mission = screen("finale-mission.png")
check(mission is not None, "finale: the mission page was captured")
if mission:
    shots = count(mission, SALMON, 88, 40, 310, 200) // 9
    hits = count(mission, magenta, 88, 40, 310, 200, exact=False) // 9
    check((shots, hits) == (13, 6), f"finale: a block per hundred shots, 13 and 6 (got {shots} and {hits})")
scores = screen("finale-scores.png")
check(scores is not None and "does not reach" not in text, "finale: the score ranked and the table followed")
if scores:
    bar = count(scores, NAVY, 21, 61, 300, 76)
    frame = count(scores, YELLOW, 20, 60, 301, 61) + count(scores, YELLOW, 20, 76, 301, 77)
    check(bar > 3000, f"finale: the earned row is the original's navy bar ({bar} px)")
    check(frame >= 500, f"finale: in a yellow frame ({frame} px of its two long sides)")
named = screen("finale-named.png")
if named:
    typed = count(named, SALMON, 22, 62, 120, 75)
    check(typed > 20, f"finale: the name is typed in the row's colour ({typed} px)")
check("CONGRATULATIONS" not in text, "finale: no invented victory page")

# unranked
text = log("unranked")
check("Corridor 7 mission hit/miss: 0 shots, 0 hits, 0% accuracy, 0 point bonus" in text,
      "unranked: the mission page shows even with nothing fired")
check("a score of 0 does not reach the high scores" in text,
      "unranked: a score that does not rank skips the table, as a2cc does")

# held
held1, held2, released = (screen(f"held-{n}.png") for n in ("held1", "held2", "released"))
if held1 and held2 and released:
    a = count(held1, SALMON, 88, 40, 310, 200) // 9
    b = count(held2, SALMON, 88, 40, 310, 200) // 9
    c = count(released, SALMON, 88, 40, 310, 200) // 9
    d = count(released, magenta, 88, 40, 310, 200, exact=False) // 9
    check(0 < a < b < 13, f"held: the tally counts up while a direction is held ({a}, then {b} of 13)")
    check((c, d) == (13, 6), f"held: letting go finishes it at once ({c} and {d})")
else:
    check(False, "held: the pages were captured")

# carried
f = floors("carried")
entry = f.get("MAP40")
check(entry is not None and entry.get("mission") == "50/20",
      f"carried: MAP39's 50 shots and 20 hits join the totals on MAP40 "
      f"(got {entry.get('mission') if entry else 'no MAP40'})")
check("saved snapshot" in log("carried"), "carried: a save was made on MAP40")
saving = work / "saves-carried" / "carried.ec7"
version = 0
if saving.exists():
    m = re.search(rb"ECWolf Save Version\x00[^0-9]*(\d+)", saving.read_bytes())
    version = int(m.group(1)) if m else 0
loaded = floors("loaded").get("MAP40")
text = log("loaded")
if version >= 1794700000:
    check(loaded is not None and loaded.get("mission") == "50/20",
          f"carried: the totals survive a save and a load "
          f"(got {loaded.get('mission') if loaded else 'no MAP40'})")
    check("predates mission shot totals" not in text, "carried: the save was not treated as legacy")
else:
    # Save versions are commit dates: an uncommitted build writes the old format.
    print(f"  --  carried: save version {version} predates the totals (an uncommitted build); "
          "checking the legacy path instead")
    check("predates mission shot totals" in text and loaded is not None and loaded.get("mission") == "0/0",
          "carried: an older save counts from its own floor and says so")

after = floors("bonus").get("MAP02")
check("bonus floor hit/miss: 113 shots, 66 hits" in log("bonus") and after is not None
      and after.get("mission") == "113/66",
      f"carried: a bonus floor's shooting joins the totals "
      f"(MAP02 has {after.get('mission') if after else 'not reached'})")

sys.exit(1 if failed else 0)
PY
[ "$status" -eq 0 ] && printf 'PASS: the campaign ends on the mission hit/miss page\n'
exit "$status"
