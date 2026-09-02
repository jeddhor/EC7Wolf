#!/bin/sh

# Regression test: EC7Edit's validator says useful things, quickly, and never
# about a map that is fine.
#
# Milestone E7 of docs/corridor7-level-editor.md. Three properties, because the
# validator fails in three different ways and each looks like success from the
# outside:
#
#   1. it catches what it claims to. Every code has a positive and a negative
#      fixture in tests/unit/test_validation.py and test_reachability.py.
#   2. it does not cry wolf. The sixty shipped maps are the corpus nobody can
#      argue with -- they are the game -- and the validator reports NO errors
#      across all of them. A rule that fires on retail data is a rule that has
#      taught its user to ignore the panel.
#   3. it is fast enough to run while somebody is drawing. A full pass over a
#      64x64 map and the incremental pass that runs on every edit both have a
#      budget here; the first honest implementation was eighteen times over it
#      because the catalog lookup was a linear scan.
#
# The validation-code reference is generated from the validator, so it is
# checked rather than trusted.
#
# Data-free except for the false-positive review, which needs the archive and
# is skipped without it. Nothing here prints or writes a byte of map data.
#
# Usage: test_ec7edit_e7.sh [DATA_DIR]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"
data=${1:-}

[ -f "$editor/ec7edit_core/reachability.py" ] || {
	printf 'SKIP: no reachability model yet\n'; exit 0; }
command -v python3 >/dev/null 2>&1 || { printf 'SKIP: python3 is missing\n'; exit 0; }

status=0
say() { printf '  %-5s %s\n' "$1" "$2"; }

# --- 1. the fixtures ------------------------------------------------------
if (cd "$editor" && QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=x11 python3 -m pytest \
	tests/unit/test_validation.py tests/unit/test_reachability.py -q \
	>/tmp/ec7edit-e7-unit.log 2>&1); then
	say "ok" "the validator and reachability fixtures pass"
else
	say "FAIL" "validator fixtures failed; see /tmp/ec7edit-e7-unit.log"
	status=1
fi

if (cd "$editor" && QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=x11 python3 -m pytest \
	tests/gui/test_editing.py -q -k "ProblemsPanel or ExportPreflight" \
	>/tmp/ec7edit-e7-gui.log 2>&1); then
	say "ok" "the Problems panel filters, marks stale results and applies fixes"
else
	say "FAIL" "Problems panel tests failed; see /tmp/ec7edit-e7-gui.log"
	status=1
fi

# --- 2. every code is documented, and the document is generated -----------
if (cd "$editor" && python3 scripts/validation_reference.py check >/dev/null 2>&1); then
	say "ok" "the validation-code reference matches the validator"
else
	say "FAIL" "docs/ec7edit-validation.md is stale; regenerate it"
	status=1
fi

if (cd "$editor" && python3 - <<'PY'
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
from validation_reference import CODES
from ec7edit_core.validation import GLOBAL_CODES, LOCAL_CODES
missing = sorted((LOCAL_CODES | GLOBAL_CODES) - set(CODES))
if missing:
    print("undocumented codes:", missing)
    raise SystemExit(1)
PY
); then
	say "ok" "every code the validator can emit is in the reference"
else
	say "FAIL" "a code the validator emits is not documented"
	status=1
fi

# --- 3. the latency budget ------------------------------------------------
# Generous on purpose: this is a floor against an accidental quadratic, not a
# benchmark. The measured figures when it was written were 15 ms and 5 ms.
if (cd "$editor" && python3 - <<'PY'
import sys, time
sys.path.insert(0, ".")
from pathlib import Path
from ec7edit_core.catalog import load_catalog
from ec7edit_core.document import MapDocument
from ec7edit_core.validation import validate_local, validate_map

catalog = load_catalog(Path("resources/editor_catalog.json"))
document = MapDocument.new_room(width=64, height=64)


def timed(call, runs=10):
    start = time.perf_counter()
    for _ in range(runs):
        call()
    return (time.perf_counter() - start) / runs * 1000


full = timed(lambda: validate_map(document, catalog))
quick = timed(lambda: validate_local(document, catalog))
print(f"full {full:.1f} ms, incremental {quick:.1f} ms")
if full > 150:
    print("FAIL: a full 64x64 validation is over the 150 ms budget")
    raise SystemExit(1)
if quick > 50:
    print("FAIL: the incremental pass is over the 50 ms budget")
    raise SystemExit(1)
PY
) >/tmp/ec7edit-e7-perf.log 2>&1; then
	say "ok" "validation latency: $(cat /tmp/ec7edit-e7-perf.log)"
else
	say "FAIL" "$(cat /tmp/ec7edit-e7-perf.log)"
	status=1
fi

# --- 4. no false positives on the game itself -----------------------------
if [ -n "$data" ] && [ -f "$data/MAPTEMP.CO7" ]; then
	if (cd "$editor" && MAPTEMP="$data/MAPTEMP.CO7" python3 - <<'PY'
import os, sys
sys.path.insert(0, ".")
from collections import Counter
from pathlib import Path
from ec7edit_core.archive import read_archive
from ec7edit_core.catalog import load_catalog
from ec7edit_core.document import MapDocument, SourceReference
from ec7edit_core.errors import Severity
from ec7edit_core.validation import profile_for_slot, validate_map

catalog = load_catalog(Path("resources/editor_catalog.json"))
archive = read_archive(os.environ["MAPTEMP"])
errors = Counter()
for record in archive.records:
    document = MapDocument(f"u{record.number}", record.number, record.name,
                           record.planes,
                           source=SourceReference("MAPTEMP.CO7", "0" * 64, record.number))
    for problem in validate_map(document, catalog,
                                profile=profile_for_slot(record.number)):
        if problem.severity is Severity.ERROR:
            errors[problem.code] += 1
# Codes only -- never a cell, a word or a name from the retail maps.
print(f"{len(archive.records)} maps, {sum(errors.values())} errors "
      f"{dict(sorted(errors.items()))}")
raise SystemExit(1 if errors else 0)
PY
	) >/tmp/ec7edit-e7-corpus.log 2>&1; then
		say "ok" "no errors across the shipped maps: $(cat /tmp/ec7edit-e7-corpus.log)"
	else
		say "FAIL" "the validator reports errors on retail data: $(cat /tmp/ec7edit-e7-corpus.log)"
		status=1
	fi
else
	say "..." "false-positive review skipped: no MAPTEMP.CO7 given"
fi

[ "$status" -eq 0 ] && printf 'PASS: E7 validation and reachability\n'
exit "$status"
