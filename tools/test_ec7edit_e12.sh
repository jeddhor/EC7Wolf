#!/bin/sh

# Regression test: the things that have to be true before the editor ships.
#
# Milestone E12 of docs/corridor7-level-editor.md. Everything the earlier
# milestones built is tested by its own gate; what is left over is the release
# itself, and those checks have a particular character -- they are all about
# consistency between things that are kept in different places and drift apart
# silently.
#
# What is asserted:
#
#   1. One version, everywhere. The editor now carries the engine's number,
#      counted from the same commit by the same rule, so "the same" is a claim
#      that can be checked rather than a convention somebody remembers.
#   2. The manual's screenshots are current. A picture generated in March is a
#      lie by June, and nothing about it looks wrong.
#   3. The manual is honest about what exists: every panel, tool and keyboard
#      shortcut it documents is one the editor really has.
#   4. The validation reference still matches the validator.
#   5. Nothing commercial is anywhere near the public artifacts. Asked of the
#      committed tree, by looking, not by intending.
#   6. The packager and the startup gate exist and are runnable.
#
# Data-free on purpose: every one of these is about the editor's own files, and
# a release check that cannot run on a machine without the game is a release
# check that runs rarely.
#
# Usage: test_ec7edit_e12.sh [BUILD_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }

status=0
work=$(mktemp -d /tmp/ec7edit-e12.XXXXXX)
cleanup() { [ "$status" -eq 0 ] && rm -rf "$work" || printf '  logs kept in %s\n' "$work"; }
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

say()  { printf '  %-5s %s\n' "$1" "$2"; }
fail() { printf '  %-5s %s\n' "FAIL" "$1" >&2; status=1; }

# --- 1. one version ---------------------------------------------------------
printf '\nOne version for both halves\n'
engine_beta=$(git -C "$repo" rev-list --count \
	"$(sed -n 's/^set(EC7WOLF_BETA_ANCHOR "\(.*\)")$/\1/p' "$repo/src/versiondefs.cmake")..HEAD" \
	2>/dev/null || echo "")
editor_version=$(cd "$editor" && python3 -c \
	'import ec7edit_core; print(ec7edit_core.__version__)' 2>/dev/null || echo "")

if [ -z "$engine_beta" ]; then
	say ".." "no git history to count from; version agreement not checked"
elif [ "$editor_version" = "1.0-beta$engine_beta" ]; then
	say ok "the editor calls itself $editor_version, and so would the engine"
else
	fail "the editor says $editor_version; the engine would say 1.0-beta$engine_beta"
fi

# The fallback is what a source zip reports, and it is the number that goes
# stale without anyone noticing -- the engine's sat eighty-eight releases
# behind for months. It may lag HEAD; it may not lag the last release.
editor_fallback=$(sed -n 's/^BETA_FALLBACK = //p' "$editor/ec7edit_core/version.py")
engine_fallback=$(sed -n 's/^set(EC7WOLF_BETA_FALLBACK \([0-9]*\))$/\1/p' \
	"$repo/src/versiondefs.cmake")
if [ "$editor_fallback" = "$engine_fallback" ]; then
	say ok "both fallbacks say $editor_fallback, for a build with no git to ask"
else
	fail "the fallbacks disagree: editor $editor_fallback, engine $engine_fallback"
fi

# --- 2. the manual's pictures are of this editor ----------------------------
printf '\nThe manual\n'
shots="$repo/docs/images/manual"
if [ ! -d "$shots" ]; then
	fail "the manual has no screenshots at $shots"
else
	missing=""
	for image in window dock-maps dock-palette dock-inspector dock-problems \
		dock-testlog dock-snapshot camera campaign first-run; do
		[ -f "$shots/$image.png" ] || missing="$missing $image.png"
	done
	if [ -n "$missing" ]; then
		fail "the manual is missing:$missing"
	else
		say ok "ten screenshots, all present"
	fi
fi

# Regenerated into a scratch directory and compared by SIZE and dimensions
# rather than byte-for-byte: Qt does not promise identical PNG bytes across
# versions, and a gate that demands them fails on somebody else's machine for
# no reason. What it is really asking is whether the generator still runs and
# still produces every picture the manual references.
if python3 -c 'import PySide6' 2>/dev/null; then
	if QT_QPA_PLATFORM=offscreen LC_ALL=C.UTF-8 timeout 300s \
		python3 "$editor/scripts/manual_shots.py" "$work/shots" \
		>"$work/shots.log" 2>"$work/shots.err"; then
		regenerated=$(find "$work/shots" -name '*.png' | wc -l)
		committed=$(find "$shots" -name '*.png' | wc -l)
		if [ "$regenerated" -eq "$committed" ]; then
			say ok "the generator still produces all $regenerated of them"
		else
			fail "regenerating gives $regenerated pictures, the manual has $committed"
		fi
		python3 - "$work/shots" "$shots" <<'PY' || status=1
import sys
from pathlib import Path

fresh, committed = Path(sys.argv[1]), Path(sys.argv[2])
stale = []
for made in sorted(fresh.glob("*.png")):
    kept = committed / made.name
    if not kept.is_file():
        stale.append(f"{made.name} is new")
        continue
    # Dimensions must match exactly; a panel that grew or a window that was
    # resized is a picture the manual is now wrong about.
    import struct
    def size(path):
        blob = path.read_bytes()[16:24]
        return struct.unpack(">II", blob)
    if size(made) != size(kept):
        stale.append(f"{made.name} is now {size(made)}, the manual has {size(kept)}")
if stale:
    print("  FAIL  the manual's pictures are out of date: " + "; ".join(stale[:4]))
    print("        run editor/scripts/manual_shots.py and commit the result")
    sys.exit(1)
print("  ok    and every one is still the size the manual shows")
PY
	else
		fail "the screenshot generator does not run"
		tail -5 "$work/shots.err" >&2 || true
	fi
else
	say ".." "no PySide6 here, so the screenshots were not regenerated"
fi

# --- 3. the manual describes the editor that exists -------------------------
python3 - "$repo" <<'PY' || status=1
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
manual = (repo / "docs" / "ec7edit-manual.md").read_text()
gui = (repo / "editor" / "ec7edit_gui" / "main_window.py").read_text()
tools = (repo / "editor" / "ec7edit_gui" / "tools.py").read_text()
cli = (repo / "editor" / "ec7edit_core" / "cli.py").read_text()

problems = []

# Every single-key tool shortcut the manual lists must be one the editor binds.
bound = set(re.findall(r'Tool\.[A-Z_]+:\s*"([A-Z])"', tools))
claimed = set(re.findall(r"\|\s*`([A-Z])`\s*\|\s*\*\*[A-Za-z]+\*\*", manual))
if claimed - bound:
    problems.append(f"the manual documents tool keys the editor does not bind: "
                    f"{sorted(claimed - bound)}")
if bound - claimed:
    problems.append(f"the editor binds tool keys the manual never mentions: "
                    f"{sorted(bound - claimed)}")

# Every CLI verb the manual shows has to exist.
verbs = set(re.findall(r'verbs\.add_parser\(\s*"([a-z-]+)"', cli))
shown = set(re.findall(r"ec7edit_core ([a-z-]+)", manual))
if shown - verbs:
    problems.append(f"the manual shows commands that do not exist: {sorted(shown - verbs)}")

# Every dock the manual illustrates has to be a dock.
docks = set(re.findall(r'setObjectName\("([a-z-]+-dock)"\)', gui))
pictured = set(re.findall(r"images/manual/dock-([a-z]+)\.png", manual))
known = {name.replace("-dock", "").replace("test-log", "testlog") for name in docks}
if pictured - known:
    problems.append(f"the manual pictures panels that are not docks: "
                    f"{sorted(pictured - known)}")

if problems:
    for problem in problems:
        print(f"  FAIL  {problem}")
    sys.exit(1)
print(f"  ok    it documents {len(claimed)} tools, {len(shown)} commands and "
      f"{len(pictured)} panels, and the editor has all of them")
PY

# --- 4. the validation reference still matches the validator ----------------
printf '\nGenerated documents\n'
if (cd "$editor" && python3 scripts/validation_reference.py check \
	>"$work/validation.log" 2>&1); then
	say ok "the validation reference matches the validator"
else
	fail "docs/ec7edit-validation.md is out of date"
	tail -5 "$work/validation.log" >&2 || true
fi

# --- 5. nothing commercial is committed -------------------------------------
printf '\nWhat is in the public tree\n'
python3 - "$repo" <<'PY' || status=1
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1])
tracked = subprocess.run(["git", "-C", str(repo), "ls-files"],
                         capture_output=True, text=True, check=True).stdout.split()

BANNED_SUFFIX = {".co7", ".ec7project", ".ec7recovery", ".vswap", ".wl6", ".sod"}
BANNED_NAME = {"corr7cd.exe", "maptemp.co7", "maphead.co7", "gfxtiles.co7"}

bad = [name for name in tracked
       if Path(name).suffix.lower() in BANNED_SUFFIX
       or Path(name).name.lower() in BANNED_NAME]
if bad:
    sys.exit("  FAIL  commercial game data is committed: " + ", ".join(bad[:8]))

# The manual's images are the newest public artifacts and the easiest to get
# wrong: one screenshot taken with the game configured would put Corridor 7's
# artwork in a public repository.
#
# Checked at the CAUSE rather than by looking at the pixels. Counting colors
# was the obvious thing and it was useless -- a Qt window full of antialiased
# text has ten thousand of them, so the measure could not tell artwork from a
# font. What actually guarantees it is that the generator refuses to run with a
# data directory configured, so that guard is what is asserted here.
generator = (repo / "editor" / "scripts" / "manual_shots.py").read_text()
if "refusing to generate" not in generator or "settings.profile.data_dir" not in generator:
    sys.exit("  FAIL  manual_shots.py has lost its guard against generating "
             "screenshots with game data configured")

shots = sorted((repo / "docs" / "images" / "manual").glob("*.png"))
if not shots:
    sys.exit("  FAIL  no manual screenshots to audit")

print(f"  ok    {len(tracked)} tracked files hold no game data")
print(f"  ok    {len(shots)} screenshots, and the generator refuses to make "
      "them with data configured")
PY

# --- 6. the release tooling is there ----------------------------------------
printf '\nRelease tooling\n'
for script in package_ec7edit.sh test_ec7edit_release_startup.sh; do
	if [ -x "$here/$script" ]; then
		sh -n "$here/$script" && say ok "$script is present and parses"
	else
		fail "$script is missing or not executable"
	fi
done

[ "$status" -eq 0 ] && printf '\nPASS: the editor is consistent with its own release.\n' \
	|| printf '\nFAIL: see above.\n' >&2
exit "$status"
