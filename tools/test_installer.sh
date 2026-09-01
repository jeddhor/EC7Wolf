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

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/xvfb_common.sh"

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

# Which engine a plain install would reuse. This gate spent weeks reporting on
# a six-week-old binary because find_existing rejected every current build (its
# pk3 is packaged seconds BEFORE the executable is linked, and the rule allowed
# one second of that) and fell through to a leftover ECWolf/release from an
# upstream 1.5pre. Both halves are checked here: the right directory is picked,
# and a build from another revision is refused.
from ec7install import build as build_mod
from pathlib import Path as _Path

repo_root = _Path(sys.argv[1])
wanted = build_mod.tree_version(repo_root)
if wanted:
    engine = build_mod.find_existing(repo_root)
    if engine is None:
        # Two different situations, and telling them apart matters: nothing
        # built at all is nothing to check, while builds that exist and were
        # all refused is the check doing its job.
        built = [d for d in (repo_root.parent / "builds" / "release-build",
                             repo_root.parent / "builds" / "release",
                             repo_root / "build", repo_root / "release")
                 if (d / "ec7wolf").is_file()]
        if built:
            print(f"  reuse: none accepted; {len(built)} build(s) present are "
                  f"from another revision, so it would compile")
        else:
            print("  reuse: nothing built yet, not checked")
    else:
        got = engine.version()
        if not got:
            sys.exit(f"FAIL: {engine.executable} reports no version at all -- "
                     "the version regex cannot read this project's own tags")
        if got.removesuffix("-m") != wanted:
            sys.exit(f"FAIL: a plain install would reuse {engine.executable}, "
                     f"built from {got}, while this tree is {wanted}")
        print(f"  reuse: {engine.source}")

    class _Quiet:
        def detail(self, message): pass

    stale = repo_root / "release"
    if (stale / "ec7wolf").is_file():
        picked = build_mod.find_existing(repo_root, reporter=_Quiet())
        if picked is not None and picked.executable.parent == stale:
            sys.exit(f"FAIL: {stale} is from another revision and was reused anyway")

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

# --engine "$build_dir": install the engine this suite just built, not one the
# installer went looking for. Without it this gate searched four directories
# and packaged whatever turned up first, which for weeks was a stale untracked
# ECWolf/release from six weeks earlier -- so the gate was testing an engine
# nobody had built, and reported on features that binary did not have.
HOME="$fake_home" "$installer" --source "$disc" --dest "$destination" \
	--engine "$build_dir" \
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
# Its own display, started and waited for, rather than `xvfb-run -a`.
#
# `-a` picks a free display number and races every other gate doing the same.
# Under a full suite this gate hung for the whole 300s having printed NOTHING
# -- the engine never started, because the display never arrived. A fixed
# number of our own, and xvfb_start's poll for the server actually accepting
# connections, removes the race and the guess together.
display=:181
xvfb_start "$display" "$work/xvfb.log" 900x600x24 || {
	printf 'SKIP: no Xvfb available\n'; exit 0; }

# No --capture-* options here, deliberately.
#
# The installer downloads a RELEASED source archive and builds it, so this
# binary is whatever that release was -- not this working tree. Handing it this
# build's test-harness options is unsound, and it showed: the version it
# installs does not consume them, so they fell through to the wad loader
# ("Could not stat --capture-maxtics"), --capture-maxtics never armed, and the
# game ran until the timeout killed it. EVERY run. The old code hid that behind
# `|| true` and then grepped the log, which found MAP01 and passed -- so this
# gate was green for a run that never once ended the way it claimed to.
#
# What it actually wants to know is whether the thing the installer produced
# runs and reaches the first floor. So: start it, give it long enough to get
# there, and stop it. Being killed is the expected ending, and the log is the
# evidence.
#
# stdbuf -oL because the kill is a SIGTERM and the engine's stdout is a file,
# so libc block-buffers it: whatever is in the unflushed tail dies with the
# process. That is not hypothetical -- without it this run reached MAP01 and
# then "lost" the CD audio and cinematics lines that init had already printed,
# and the gate reported the installed game could not find its soundtrack.
set +e
( cd "$destination"
  timeout 90s env DISPLAY="$display" SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
	stdbuf -oL -eL ./ec7wolf --data CO7 --nowait --tedlevel MAP01 --skill 2 \
	--config "$work/cfg" --savedir "$work/sv"
) >"$run_log" 2>&1
run_rc=$?
set -e
xvfb_stop 2>/dev/null || kill "${xvfb:-0}" 2>/dev/null || true

grep -q "MAP01 - Corridor 7 Level 1" "$run_log" || {
	printf 'FAIL: the installed game did not reach MAP01 (exit %s)\n' "$run_rc" >&2
	tail -20 "$run_log" >&2
	exit 1
}
grep -q "CD audio: 4 of 4" "$run_log" || {
	printf 'FAIL: the installed game did not find the ripped soundtrack\n' >&2
	printf '       what it said about CD audio (exit %s):\n' "$run_rc" >&2
	grep -i "cd audio" "$run_log" | sed 's/^/       /' >&2 || printf '       nothing\n' >&2
	exit 1
}
grep -q "Cinematics: 3 of 3" "$run_log" || {
	printf 'FAIL: the installed game did not find the cinematics\n' >&2
	printf '       what it said about cinematics (exit %s):\n' "$run_rc" >&2
	grep -i "cinematics" "$run_log" | sed 's/^/       /' >&2 || printf '       nothing\n' >&2
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
# --engine again, for the same reason as the first install and one more: this
# check is timed, and without it the second install goes looking for an engine,
# finds none it will accept, and spends the budget on the build instead of on
# the media step being measured.
HOME="$fake_home" "$installer" --source "$disc" --dest "$destination" \
	--engine "$build_dir" \
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
