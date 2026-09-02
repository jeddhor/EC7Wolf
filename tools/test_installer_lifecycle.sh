#!/bin/sh

# Regression test: what happens to an install after the first one.
#
# The gates so far all cover installing onto a clean machine. This covers the
# rest of the life: installing again over the top, removing it, driving both
# without a window, and picking up where a failed run left off.
#
# The reason it exists is the bug it was written around. Staging.commit renamed
# the old install aside and then deleted it outright -- saved games and settings
# with it -- while the wizard's destination page told the user, in as many
# words, that saved games would be kept. Nothing caught that, because nothing
# had ever installed twice.
#
# Usage: test_installer_lifecycle.sh [DISC] [BUILD_DIR]
#
# BUILD_DIR names the engine to install. Without it this asked find_existing to
# guess, which refuses a build made at a different revision than the tree -- so
# the gate skipped itself, silently, from the moment anyone committed until the
# next rebuild. A gate that stops testing exactly when the code changed is
# worse than no gate.

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)

disc=${1:-${CORRIDOR7_DISC:-}}
build_dir=${2:-}
if [ -z "$disc" ]; then
	for candidate in "$repo/../corr7/Corridor7.cue" "$repo/../corr7/corridor7.cue"; do
		[ -f "$candidate" ] && { disc=$candidate; break; }
	done
fi
if [ -z "$disc" ] || [ ! -f "$disc" ]; then
	printf 'SKIP: no Corridor 7 disc\n'
	exit 0
fi

work=$(mktemp -d /tmp/ec7wolf-life.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
mkdir -p "$work/home"

HOME="$work/home" XDG_DATA_HOME="$work/home/.local/share" \
QT_QPA_PLATFORM=offscreen QT_LOGGING_RULES='*.debug=false;qt.qpa.*=false' \
python3 - "$repo" "$work" "$disc" "$build_dir" <<'PY'
import shutil, sys, time
from pathlib import Path

repo, work, disc = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
named = [Path(sys.argv[4])] if len(sys.argv) > 4 and sys.argv[4] else []
sys.path.insert(0, str(repo / "installer"))
sys.path.insert(0, str(repo / "tools"))

from c7disc import GameSource
from ec7install import audio, build, install
from ec7install.plan import InstallPlan, RemovalPlan
from ec7install.progress import Cancelled, Reporter

failures = []

def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)

# The build this suite was pointed at, used as given. Guessing is for a user
# running the installer by hand; a test knows which engine it means.
engine = build.find_existing(repo, extra=named)
if engine is None:
    print("SKIP: no built engine, so there is nothing to install")
    sys.exit(0)

target = work / "game"
source = GameSource.open(disc)

def do_install(quiet=Reporter()):
    return InstallPlan(repo_root=repo, source=source, destination=target,
                       with_music=False, with_video=False,
                       menu_shortcut=False, desktop_shortcut=False,
                       engine=engine).run(quiet)

# --- first install ---------------------------------------------------------
print("\nthe first install")
do_install()
check(target.is_dir() and (target / "MAPTEMP.CO7").exists(), "it is installed")
check(install.read_manifest(target) is not None, "and it left a manifest")

# What a player would then have, in the places the launcher puts them.
saves = target / "saves"
saves.mkdir(exist_ok=True)
(saves / "SAVE0.ec7").write_bytes(b"hard-won progress")
(saves / "SAVE1.ec7").write_bytes(b"more of it")
(target / "ec7wolf.cfg").write_text("my key bindings\n")

# --- installing again over the top ----------------------------------------
print("\ninstalling again over the top")
before = (target / "ec7wolf").stat().st_size
do_install()

check((saves / "SAVE0.ec7").read_bytes() == b"hard-won progress",
      "the saved games are still there, byte for byte")
check((saves / "SAVE1.ec7").exists(), "all of them, not just the first")
check((target / "ec7wolf.cfg").read_text() == "my key bindings\n",
      "and the settings survived too")
check((target / "ec7wolf").stat().st_size == before,
      "while the engine itself was written again")
check(install.read_manifest(target) is not None, "the manifest is still good")
leftovers = list(target.parent.glob(".*previous*")) + \
            list(target.parent.glob(".*staging*"))
check(not leftovers, f"and nothing was left lying beside it ({leftovers})")

# A reinstall must not be able to eat the saves when it fails part way either.
print("\na reinstall that fails does not take them with it")
class Boom(Reporter):
    def step(self, name, detail=""):
        if "Assembling" in name:
            raise RuntimeError("stopped on purpose")

try:
    do_install(Boom())
    check(False, "the failing install should have raised")
except RuntimeError:
    check(True, "the install failed where it was told to")
check((saves / "SAVE0.ec7").read_bytes() == b"hard-won progress",
      "the saved games are untouched")
check((target / "MAPTEMP.CO7").exists(), "and the old install still works")

# --- resuming a rip --------------------------------------------------------
print("\npicking up an interrupted soundtrack")
cache = work / "cache"

class StopAfter(Reporter):
    def __init__(self, limit): self.limit, self.seen = limit, 0
    def detail(self, line):
        if line.startswith("track") and "already" not in line:
            self.seen += 1
    def cancelled(self): return self.seen > self.limit

try:
    audio.rip(source, work / "music-1", StopAfter(1), cache=cache)
    check(False, "the rip should have been cancelled")
except Cancelled:
    check(True, "the rip stopped part way")

encoded = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else []
check(encoded, f"what it finished was kept ({encoded})")
check(not any(name.endswith(".part") for name in encoded),
      "and nothing half-written was kept, which a later run would trust")

class Watch(Reporter):
    def __init__(self): self.reused = self.fresh = 0
    def detail(self, line):
        if "already encoded" in line: self.reused += 1
        elif line.startswith("track"): self.fresh += 1

watch = Watch()
audio.rip(source, work / "music-2", watch, cache=cache)
check(watch.reused == len(encoded),
      f"the second run reused all {len(encoded)} of them")
check(watch.fresh > 0, "and encoded the rest")
tracks = sorted((work / "music-2").iterdir())
check(len(tracks) == 8, f"all eight tracks are there ({len(tracks)})")
check(all(t.stat().st_size > 1000 for t in tracks), "and none of them empty")

# --- removing --------------------------------------------------------------
print("\nremoving it")
RemovalPlan(target).run(Reporter())
check(not target.exists(), "the install is gone")

print("\nremoving something that is not an install")
stranger = work / "not-an-install"
stranger.mkdir()
(stranger / "important.txt").write_text("someone else's file")
try:
    RemovalPlan(stranger).run(Reporter())
    check(False, "it should refuse a directory it did not install")
except install.InstallError:
    check(True, "it refuses a directory it did not install")
check((stranger / "important.txt").exists(),
      "and leaves what is in there alone")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
PY

# --- the unattended front end ----------------------------------------------
#
# Driven as a deployment tool would: no window, answers on the command line,
# and the exit code for a result.

echo
echo "unattended"

if ! python3 -c "import PySide6.QtWidgets" >/dev/null 2>&1; then
	printf '  SKIP  PySide6 is not installed\n'
	exit 0
fi

setup="$repo/installer/ec7wolf-setup"
run_setup() {
	HOME="$work/home" XDG_DATA_HOME="$work/home/.local/share" \
	QT_QPA_PLATFORM=offscreen QT_LOGGING_RULES='*.debug=false;qt.qpa.*=false' \
	"$setup" "$@" >"$work/unattended.log" 2>&1
}

status=0

if run_setup --unattended --dest "$work/u"; then
	printf '  FAIL  it installed with no --source\n'; status=1
else
	code=$?
	if [ "$code" -eq 1 ]; then
		printf '  ok   no --source is refused, with the exit code that says why\n'
	else
		printf '  FAIL  no --source exited %s, expected 1\n' "$code"; status=1
	fi
fi
if grep -q -- "--source" "$work/unattended.log"; then
	printf '  ok   and the log says what is missing\n'
else
	printf '  FAIL  the log does not say what is missing\n'; status=1
fi

if run_setup --unattended --source "$disc" --dest "$work/u" \
             --no-music --no-video --no-shortcuts; then
	printf '  ok   an unattended install succeeds\n'
else
	printf '  FAIL  the unattended install failed (%s)\n' "$?"
	tail -5 "$work/unattended.log" | sed 's/^/        /'
	status=1
fi
if [ -x "$work/u/ec7wolf" ] && [ -f "$work/u/MAPTEMP.CO7" ]; then
	printf '  ok   and produced a real install\n'
else
	printf '  FAIL  the unattended install produced nothing usable\n'; status=1
fi

if run_setup --remove "$work/u"; then
	if [ -d "$work/u" ]; then
		printf '  FAIL  --remove reported success but left the folder\n'; status=1
	else
		printf '  ok   --remove takes it away again\n'
	fi
else
	printf '  FAIL  --remove failed (%s)\n' "$?"; status=1
fi

exit "$status"
