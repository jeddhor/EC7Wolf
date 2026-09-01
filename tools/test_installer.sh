#!/bin/sh

# Regression test: the installer core.
#
# The installer's whole design is a headless library with a thin GUI on top, and
# this is why: a graphical installer cannot be tested, but everything it does
# can. This drives the same code the GUI will, end to end.
#
# What it checks, in order of how much it needs:
#
#   always      the dependency scan runs and reports remedies, and --check works
#   with a disc a complete install: engine, data files, cinematics, soundtrack,
#               launcher and manifest -- then that the GAME ACTUALLY RUNS from
#               the result, then that the uninstaller removes everything it made
#               and nothing it did not
#
# The disc is commercial and lives outside the repository, so the second half is
# skipped when it is absent, the same way every other data gate behaves. Point
# CORRIDOR7_DISC at a .cue/.iso to run it elsewhere.
#
# Shortcuts are created into a throwaway HOME. A test that scatters desktop icons
# across the developer's actual desktop would be its own bug report.
#
# Usage: test_installer.sh BUILD_DIR [DATA_DIR]

set -eu

if [ "$#" -lt 1 ]; then
	printf 'usage: %s BUILD_DIR [DATA_DIR]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
installer="$repo/installer/ec7wolf-install"

if [ ! -x "$installer" ]; then
	printf 'FAIL: %s is missing\n' "$installer" >&2
	exit 1
fi

work=$(mktemp -d /tmp/ec7wolf-installer.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# --- the parts that need nothing -------------------------------------------

python3 - "$repo" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/installer")
from ec7install import deps, install

report = deps.scan_build()
if not list(report):
    sys.exit("FAIL: the build dependency scan reported nothing at all")

# Every requirement that is missing has to say what to do about it. A scan that
# reports "SDL2: missing" and stops is the thing this installer exists to avoid.
for requirement in report:
    if not requirement.found and not requirement.remedy:
        sys.exit(f"FAIL: {requirement.key} is missing but offers no remedy")

for requirement in deps.scan_rip():
    if not requirement.found and not requirement.remedy:
        sys.exit(f"FAIL: {requirement.key} is missing but offers no remedy")

# The default destination must be somewhere the user can actually run from, and
# must not need root. A sandboxed launcher sets XDG_DATA_HOME to its own private
# tree, which is how this went wrong once already.
destination = install.default_destination()
home = str(__import__("pathlib").Path.home())
if not str(destination).startswith(home):
    sys.exit(f"FAIL: the default destination {destination} is outside {home}")
if "/snap/" in str(destination) or "/flatpak/" in str(destination):
    sys.exit(f"FAIL: the default destination {destination} is inside a sandbox")

print(f"  dependency scan: {len(list(report))} build requirements, remedies present")
print(f"  default destination: {destination}")
PY

"$installer" --check >"$work/check.txt" 2>&1 || {
	printf 'FAIL: --check exited non-zero\n' >&2
	cat "$work/check.txt" >&2
	exit 1
}
grep -q "EC7Wolf installer" "$work/check.txt" || {
	printf 'FAIL: --check produced no report\n' >&2
	cat "$work/check.txt" >&2
	exit 1
}
printf '  --check runs and reports\n'

# --- the parts that need a disc --------------------------------------------

disc=${CORRIDOR7_DISC:-}
if [ -z "$disc" ]; then
	for candidate in \
		"$repo/../corr7/Corridor7.cue" \
		"$repo/../corr7/corridor7.cue"; do
		[ -f "$candidate" ] && disc=$candidate && break
	done
fi

if [ -z "$disc" ] || [ ! -f "$disc" ]; then
	printf 'SKIP: no Corridor 7 disc image; set CORRIDOR7_DISC to run the '
	printf 'full install test\n'
	printf 'PASS: the installer core scans and reports correctly.\n'
	exit 0
fi

# The audio track layout is worth pinning on its own: PREGAP shifts ACCUMULATE
# down a cue sheet, and applying only each track's own stretched track 2 from
# 8 seconds to 10 -- which would have misplaced every track in the rip.
python3 - "$repo" "$disc" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/tools")
from c7disc import GameSource

with GameSource.open(sys.argv[2]) as source:
    files = source.list()
    for name in ("MAPTEMP.CO7", "GFXTILES.CO7", "CORR7CD.EXE"):
        if name not in files:
            sys.exit(f"FAIL: {name} is not on {sys.argv[2]}")
    if files["CORR7CD.EXE"] != 250776:
        sys.exit(f"FAIL: CORR7CD.EXE is {files['CORR7CD.EXE']} bytes, not 250776")

    tracks = {t.number: round(t.seconds, 1) for t in source.audio_tracks()}
    expected = {2: 8.0, 3: 636.1, 4: 6.0, 5: 347.6, 6: 6.0, 7: 183.4, 8: 6.0}
    for number, seconds in expected.items():
        if abs(tracks.get(number, -1) - seconds) > 0.2:
            sys.exit(f"FAIL: track {number} is {tracks.get(number)}s, "
                     f"expected {seconds}s -- cue PREGAP handling is wrong")
    print(f"  disc: {len(files)} files, {len(tracks)} audio tracks, "
          "durations as measured")
PY

fake_home="$work/home"
mkdir -p "$fake_home/Desktop"
destination="$work/install"

HOME="$fake_home" "$installer" --source "$disc" --dest "$destination" \
	--log "$work/install.log" >"$work/install.txt" 2>&1 || {
	printf 'FAIL: the install failed\n' >&2
	tail -30 "$work/install.txt" >&2
	exit 1
}

for required in ec7wolf ec7wolf.pk3 MAPTEMP.CO7 CORR7CD.EXE run-ec7wolf.sh; do
	[ -f "$destination/$required" ] || {
		printf 'FAIL: the install has no %s\n' "$required" >&2
		exit 1
	}
done
[ -f "$destination/video/SEQFOUR.CO7" ] || { printf 'FAIL: no cinematics\n' >&2; exit 1; }
[ -f "$destination/cdaudio/track03.ogg" ] || { printf 'FAIL: no soundtrack\n' >&2; exit 1; }
printf '  installed %s\n' "$(du -sh "$destination" | cut -f1)"

# The only check that really matters: does the thing it produced run?
run_log="$work/run.txt"
set +e
( cd "$destination"
  # Generous, and its expiry is told apart from a game that ran and failed.
  # At 120s this timed out on a machine already busy building the installer
  # this test just made, and the gate then said "the installed game did not
  # reach MAP01" -- blaming the game for the clock.
  timeout 300s env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 xvfb-run -a \
	./ec7wolf --data CO7 --nowait --tedlevel MAP01 --skill 2 \
	--capture-rngseed 1 --capture-maxtics 60 \
	--config "$work/cfg" --savedir "$work/sv"
) >"$run_log" 2>&1
run_rc=$?
set -e
[ "$run_rc" -eq 124 ] && {
	printf 'FAIL: the installed game was still going after 300s\n' >&2
	exit 1
}

grep -q "MAP01 - Corridor 7 Level 1" "$run_log" || {
	printf 'FAIL: the installed game did not reach MAP01 (exit %s)\n' "$run_rc" >&2
	tail -20 "$run_log" >&2
	exit 1
}
grep -q "CD audio: 4 of 4" "$run_log" || {
	printf 'FAIL: the installed game did not find the ripped soundtrack\n' >&2
	exit 1
}
grep -q "Cinematics: 3 of 3" "$run_log" || {
	printf 'FAIL: the installed game did not find the cinematics\n' >&2
	exit 1
}
printf '  the installed game starts, and finds its music and cinematics\n'

# --- installing again over the top does not redo the CD media ---------------
#
# Ripping the soundtrack is the longest step after the compile, and it and the
# cinematics come off the disc identically every time -- so upgrading from one
# beta to the next used to spend minutes reproducing files already in the
# folder. Timed rather than read off a log line: the point is the work not
# happening, and a message can be printed by a step that goes on to do the work
# regardless.
#
# The cache is removed first, because the cache already made a *second* attempt
# quick. What is being tested is the install itself being the source, which is
# the case a player upgrading actually has.
rm -rf "$work"/.ec7wolf-cache "$destination/../.ec7wolf-cache"
tracks_before=$(cd "$destination/cdaudio" && ls -l track*.ogg | awk '{print $5,$9}' | sort)
began=$(date +%s)
HOME="$fake_home" "$installer" --source "$disc" --dest "$destination" \
	--log "$work/again.log" >"$work/again.txt" 2>&1 || {
	printf 'FAIL: installing again over the top failed\n' >&2
	tail -30 "$work/again.txt" >&2
	exit 1
}
elapsed=$(( $(date +%s) - began ))
[ "$elapsed" -lt 20 ] || {
	printf 'FAIL: the second install took %ss; the media was made again\n' "$elapsed" >&2
	exit 1
}
tracks_after=$(cd "$destination/cdaudio" && ls -l track*.ogg | awk '{print $5,$9}' | sort)
[ "$tracks_before" = "$tracks_after" ] || {
	printf 'FAIL: the soundtrack changed across a reinstall\n' >&2
	exit 1
}
[ -f "$destination/video/SEQFOUR.CO7" ] || {
	printf 'FAIL: the cinematics did not survive the reinstall\n' >&2
	exit 1
}
printf '  installing again took %ss and kept the CD media\n' "$elapsed"

# Damaged media must be made again rather than adopted: it would pass through
# the install and fail in front of the player at New Mission.
printf 'rubbish' > "$destination/video/SEQONE.CO7"
printf 'x' > "$destination/cdaudio/track03.ogg"
HOME="$fake_home" "$installer" --source "$disc" --dest "$destination" \
	--log "$work/repair.log" >"$work/repair.txt" 2>&1 || {
	printf 'FAIL: the repairing install failed\n' >&2
	tail -30 "$work/repair.txt" >&2
	exit 1
}
seq_size=$(stat -c %s "$destination/video/SEQONE.CO7")
trk_size=$(stat -c %s "$destination/cdaudio/track03.ogg")
[ "$seq_size" -gt 4096 ] && [ "$trk_size" -gt 4096 ] || {
	printf 'FAIL: damaged media was adopted (SEQONE %s, track03 %s)\n' \
		"$seq_size" "$trk_size" >&2
	exit 1
}
printf '  damaged media was made again, not adopted\n'

# Shortcuts went into the throwaway home, and the uninstaller takes back
# everything it made.
shortcuts=$(find "$fake_home" -name "*.desktop" | wc -l | tr -d ' ')
[ "$shortcuts" -ge 2 ] || {
	printf 'FAIL: expected a menu entry and a desktop icon, found %s\n' "$shortcuts" >&2
	exit 1
}
if command -v desktop-file-validate >/dev/null 2>&1; then
	desktop-file-validate "$fake_home/.local/share/applications/org.ec7wolf.EC7Wolf.desktop" || {
		printf 'FAIL: the menu entry is not a valid desktop file\n' >&2
		exit 1
	}
fi
printf '  %s shortcuts created, menu entry valid\n' "$shortcuts"

HOME="$fake_home" "$installer" --uninstall "$destination" >>"$work/install.txt" 2>&1 || {
	printf 'FAIL: the uninstall failed\n' >&2
	tail -20 "$work/install.txt" >&2
	exit 1
}
[ -d "$destination" ] && { printf 'FAIL: %s survived the uninstall\n' "$destination" >&2; exit 1; }
left=$(find "$fake_home" -name "*.desktop" -o -name "org.ec7wolf.*" | wc -l | tr -d ' ')
[ "$left" -eq 0 ] || {
	printf 'FAIL: %s files were left behind by the uninstall\n' "$left" >&2
	find "$fake_home" -name "*.desktop" -o -name "org.ec7wolf.*" >&2
	exit 1
}
printf '  uninstall removed the install and every shortcut\n'

printf 'PASS: the installer builds, installs, runs and uninstalls cleanly.\n'
