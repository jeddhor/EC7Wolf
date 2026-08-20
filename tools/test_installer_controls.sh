#!/bin/sh

# Regression test: the control schemes the installer sets up.
#
# The installer offers the original's controls by writing a configuration file
# with those bindings. That only works while three things stay true, and none
# of them is guaranteed by anything else here:
#
#   - the engine's defaults really are the modern ones the installer claims
#   - a partial config is honoured rather than ignored or rejected
#   - the values mean what the installer thinks they mean
#
# The last is the one worth testing hardest. The numbers are SDL 1.2 keysyms
# because that is what the engine's config format happens to store; nothing
# stops that changing, and if it did, the installer would write a file full of
# plausible numbers that quietly bind the wrong keys.
#
# Usage: test_installer_controls.sh BUILD_DIR DATA_DIR

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)

work=$(mktemp -d /tmp/ec7wolf-controls.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

run_engine() {   # run_engine CONFIG
	( cd "$data_dir" && timeout 120 env SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11 \
		xvfb-run -a "$build_dir/ec7wolf" --data CO7 --config "$1" \
		--savedir "$work/sv" --nowait --tedlevel MAP01 --skill 2 \
		--capture-frame 2 --capture-maxframes 3 ) >>"$work/engine.log" 2>&1
}

# --- what the engine does when nobody has said anything -------------------
run_engine "$work/default.cfg" || { echo "FAIL: the engine would not run"; tail -5 "$work/engine.log"; exit 1; }

# --- what the installer writes when asked for the original's --------------
python3 -c "
import sys; sys.path.insert(0, '$repo/installer')
from pathlib import Path
from ec7install import controls
controls.write_config(Path('$work'), controls.CLASSIC)"
mv "$work/ec7wolf.cfg" "$work/classic.cfg"
cp "$work/classic.cfg" "$work/classic-before.cfg"
run_engine "$work/classic.cfg" || { echo "FAIL: the engine rejected the classic config"; exit 1; }

python3 - "$work" "$repo" <<'PY'
import re
import sys
from pathlib import Path

work, repo = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo / "installer"))
from ec7install import controls

failures = []

def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)

def bindings(path: Path) -> dict:
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"^(Keyboard_\w+) = (-?\d+);", path.read_text(), re.M)}

print("\nthe engine's own defaults are what the installer says they are")
default = bindings(work / "default.cfg")
for key, (value, name) in sorted(controls.MODERN.items()):
    check(default.get(key) == value,
          f"{key} is {name} ({value}), and the engine agrees "
          f"({default.get(key)})")

print("\nthe original's scheme survives being read by the engine")
classic = bindings(work / "classic.cfg")
for key, (value, name) in sorted(controls.CLASSIC.items()):
    check(classic.get(key) == value,
          f"{key} stayed {name} ({value})")

print("\nand it is actually a different scheme")
moved = [k for k in controls.CLASSIC
         if controls.CLASSIC[k][0] != controls.MODERN.get(k, (None,))[0]]
check("Keyboard_Forward" in moved and "Keyboard_Use" in moved,
      f"movement and use are rebound, not merely restated ({sorted(moved)})")

print("\na partial config is completed rather than rejected")
written = set(bindings(work / "classic-before.cfg"))
after = set(classic)
check(len(after) > len(written),
      f"the engine filled in the rest ({len(written)} written, {len(after)} after)")
check(written <= after, "without dropping anything that was written")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
PY
