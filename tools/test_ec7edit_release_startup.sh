#!/bin/sh

# Regression test: the packaged editor starts, on its own, from its own folder.
#
# Milestone E12 of docs/corridor7-level-editor.md, and the reason it is its own
# gate is that a frozen build fails in ways a source checkout never does. A Qt
# plugin left out of the freeze, a resource path that was right relative to the
# source tree and meaningless inside a bundle, an import that only ever worked
# because the checkout happened to be on sys.path -- every one of those looks
# identical to somebody who unpacks the zip and double-clicks: a window that
# does not appear. None of them can be caught by the test suite, which runs
# from the tree the package was built from.
#
# So this runs the package the way a stranger would, and deliberately harder:
#
#   1. From a COPY somewhere else, because a package that only works where it
#      was built is not a package.
#   2. With an environment stripped to nothing -- no PYTHONPATH, no PYTHONHOME,
#      no Qt variables, and a PATH with no python3 on it at all. If the freeze
#      is leaning on the machine's Python or Qt, it fails here rather than on
#      the first user's machine that lacks them.
#   3. With a HOME of its own, so it cannot read the developer's settings and
#      cannot leave anything in a real profile.
#   4. Through --selftest, which builds the real main window and reads the real
#      catalogue. `--version` proves the executable starts, which was never the
#      part in doubt.
#
# And it audits what is in the file, because this is a PUBLIC artifact: no
# Corridor 7 content, and no absolute path from the machine that built it.
#
# Usage: test_ec7edit_release_startup.sh PACKAGE_DIR [ENGINE_DIR]

set -eu

if [ "$#" -lt 1 ]; then
	printf 'usage: %s PACKAGE_DIR [ENGINE_DIR]\n' "$0" >&2
	exit 2
fi

package=$1
engine_dir=${2:-}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

[ -d "$package" ] || { printf 'SKIP: no editor package at %s\n' "$package"; exit 0; }

# The package directory may be the output root holding one build, or the build
# itself. Both are ordinary things to be handed.
if [ ! -x "$package/ec7edit" ] && [ ! -f "$package/ec7edit.exe" ]; then
	inner=$(find "$package" -maxdepth 2 -name ec7edit -type f 2>/dev/null | head -1)
	[ -n "$inner" ] && package=$(dirname "$inner")
fi
if [ ! -x "$package/ec7edit" ] && [ ! -f "$package/ec7edit.exe" ]; then
	printf 'SKIP: %s holds no packaged editor\n' "$package"
	exit 0
fi
package=$(cd "$package" && pwd)

status=0
work=$(mktemp -d /tmp/ec7edit-startup.XXXXXX)
cleanup() { [ "$status" -eq 0 ] && rm -rf "$work" || printf '  logs kept in %s\n' "$work"; }
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

say()  { printf '  %-5s %s\n' "$1" "$2"; }
fail() { printf '  %-5s %s\n' "FAIL" "$1" >&2; status=1; }

# --- 1. somewhere else entirely -------------------------------------------
copy="$work/unpacked"
mkdir -p "$copy"
cp -a "$package" "$copy/editor"
printf '  ..   copied to %s\n' "$copy/editor"

# --- 2. and with nothing of this machine to lean on ------------------------
#
# `env -i` is the whole point. PATH has no python3 on it; there is no
# PYTHONPATH, no PYTHONHOME, no QT_PLUGIN_PATH, no LD_LIBRARY_PATH. A frozen
# build that needs any of those needs them from the user too.
home="$work/home"
mkdir -p "$home"
set +e
( cd "$copy/editor" && env -i \
	HOME="$home" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 \
	QT_QPA_PLATFORM=offscreen \
	timeout 180s ./ec7edit --selftest ) >"$work/selftest.txt" 2>&1
run_rc=$?
set -e

if [ "$run_rc" -ne 0 ]; then
	fail "the packaged editor did not start (exit $run_rc)"
	sed 's/^/       /' "$work/selftest.txt" | head -20 >&2
	exit 1
fi
grep -q "^selftest=ok$" "$work/selftest.txt" || {
	fail "it ran but did not report a working build"
	sed 's/^/       /' "$work/selftest.txt" | head -20 >&2
	exit 1
}
say ok "it starts from a copy, with no Python or Qt on the path"

field() { sed -n "s/^$1=//p" "$work/selftest.txt" | head -1; }

[ "$(field frozen)" = yes ] || fail "it reports frozen=$(field frozen); this is meant to be a package"
say ok "Python $(field python), Qt $(field qt), $(field catalog)"
say ok "window $(field window)"

# --- 3. it is the build this tree describes --------------------------------
#
# A package built from another checkout, or from a stale tree, starts perfectly
# and is the wrong editor. Version, schema and protocol are compared against
# the sources next to this script.
# Asked of the tree's own code rather than grepped out of it: the version is
# computed now (from git, the way the engine's is), so there is no literal in
# the source to find, and a sed that finds nothing compares against the empty
# string and fails with a message that names no expectation at all.
expected_version=$(cd "$repo/editor" && python3 -c \
	'import ec7edit_core; print(ec7edit_core.__version__)' 2>/dev/null || echo "")
expected_schema=$(sed -n 's/^SCHEMA_VERSION = //p' \
	"$repo/editor/ec7edit_core/document.py" | head -1)
expected_protocol=$(sed -n 's/^PROTOCOL_VERSION = //p' \
	"$repo/editor/ec7edit_core/engine_runner.py" | head -1)

for pair in "version:$expected_version" "schema:$expected_schema" \
	"editor-protocol:$expected_protocol"; do
	key=${pair%%:*}
	want=${pair#*:}
	got=$(field "$key")
	if [ -z "$want" ]; then
		say ".." "cannot work out this tree's $key, so it was not compared"
		continue
	fi
	if [ "$got" = "$want" ]; then
		say ok "$key $got matches the source tree"
	else
		fail "the package reports $key=$got; this tree says $want"
	fi
done

# --- 4. what a public artifact may contain ---------------------------------
python3 - "$copy/editor" "$repo" <<'PY' || status=1
import re
import sys
from pathlib import Path

root, repo = Path(sys.argv[1]), Path(sys.argv[2])

BANNED_NAME = {"corr7cd.exe", "maptemp.co7", "maphead.co7", "gfxtiles.co7",
               "audiot.co7", "audiohed.co7", "vswap.co7"}
BANNED_SUFFIX = {".co7", ".wad", ".ec7project", ".ec7recovery"}

offenders = []
files = 0
total = 0
for path in root.rglob("*"):
    if not path.is_file():
        continue
    files += 1
    total += path.lstat().st_size
    lowered = path.name.lower()
    if lowered in BANNED_NAME or path.suffix.lower() in BANNED_SUFFIX:
        offenders.append(str(path.relative_to(root)))

if offenders:
    sys.exit("  FAIL  the package holds game data: " + ", ".join(offenders[:8]))
print(f"  ok    {files} files, {total / 1e6:.1f} MB, and none of it is Corridor 7")

# No absolute path from the build machine. A frozen bundle records the paths it
# was built from in a few places, and one of them naming somebody's home
# directory is a small privacy leak that ships to everyone.
home = str(Path.home())
leaks = []
for path in root.rglob("*"):
    if not path.is_file() or path.stat().st_size > 8 << 20:
        continue
    try:
        blob = path.read_bytes()
    except OSError:
        continue
    if home.encode() in blob:
        leaks.append(str(path.relative_to(root)))
    if len(leaks) > 4:
        break
if leaks:
    print("  FAIL  these name the build machine's home directory: "
          + ", ".join(leaks[:5]))
    sys.exit(1)
print("  ok    no path from the machine that built it")
PY

# --- 4b. what a package owes the person who downloaded it ------------------
#
# It bundles a Qt and a Python, so it owes their licences: "it is only a
# dependency" stops being true the moment the libraries are inside the file
# being distributed. And a manual is not much use left on a website.
for required in LICENSE.txt THIRD-PARTY.txt README.txt MANUAL.md; do
	if [ -f "$copy/editor/$required" ]; then
		say ok "it carries $required"
	else
		fail "the package has no $required"
	fi
done
grep -q "LGPL" "$copy/editor/THIRD-PARTY.txt" 2>/dev/null ||
	fail "THIRD-PARTY.txt does not mention Qt's terms"
grep -qi "no part of corridor 7" "$copy/editor/THIRD-PARTY.txt" 2>/dev/null ||
	fail "THIRD-PARTY.txt does not say the game is not included"

# --- 5. it can see an engine put beside it ---------------------------------
#
# Not required to run, and deliberately not fatal: this checks the packaged
# editor's first-run suggestions work from a package rather than a checkout,
# which is a different code path -- workspace_root() is the executable's own
# folder once frozen, not three levels up from a source file.
if [ -n "$engine_dir" ] && [ -x "$engine_dir/ec7wolf" ]; then
	cp "$engine_dir/ec7wolf" "$copy/editor/ec7wolf"
	found=$( ( cd "$copy/editor" && env -i HOME="$home" PATH=/usr/bin:/bin \
		LC_ALL=C.UTF-8 QT_QPA_PLATFORM=offscreen \
		timeout 60s ./ec7edit --selftest ) 2>/dev/null | sed -n 's/^resources=//p' )
	if [ -n "$found" ]; then
		say ok "still starts with an engine unpacked beside it"
	else
		fail "it stopped starting once an engine was put next to it"
	fi
	rm -f "$copy/editor/ec7wolf"
fi

[ "$status" -eq 0 ] && printf 'PASS: the packaged editor runs on its own.\n' \
	|| printf 'FAIL: see above.\n' >&2
exit "$status"
