#!/bin/sh

# Regression test: EC7Edit's E0 foundation holds.
#
# Milestone E0 of docs/corridor7-level-editor.md. There is no editor yet, so
# this gate does not test one. It guards the three things E0 actually promises,
# each of which is easy to break silently later:
#
#   * the synthetic fixtures are reproducible byte for byte, so a digest in the
#     evidence ledger stays a contract rather than a snapshot;
#   * they are provably synthetic, so CI on a machine with no right to the
#     commercial data can still exercise every binary boundary;
#   * every local Markdown link resolves to a tracked path inside the ECWolf
#     git root -- the plan's own reference codec lives outside it, and a
#     document that links out reads fine to its author and is simply missing
#     for everyone else.
#
# Data-free on purpose: it needs no Corridor 7 data, no engine build and no
# display, so it belongs in the hosted CI lane.
#
# Usage: test_ec7edit_e0.sh

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
editor="$repo/editor"

command -v python3 >/dev/null 2>&1 || { printf 'SKIP: no python3\n'; exit 0; }
[ -d "$editor" ] || { printf 'SKIP: no editor/ tree yet\n'; exit 0; }

status=0
check() {
	message=$1
	shift
	if "$@" >/dev/null 2>&1; then printf '  ok   %s\n' "$message"
	else printf '  FAIL %s\n' "$message"; status=1; fi
}

work=$(mktemp -d /tmp/ec7edit-e0.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

printf 'The synthetic corpus\n'
python3 "$editor/scripts/make_fixtures.py" write "$work/a" >/dev/null 2>&1 || {
	printf '  FAIL the generator did not run\n'
	python3 "$editor/scripts/make_fixtures.py" write "$work/a" 2>&1 | tail -5
	exit 1
}
python3 "$editor/scripts/make_fixtures.py" write "$work/b" >/dev/null 2>&1
printf '  ..   %s fixtures\n' "$(find "$work/a" -type f | wc -l)"

# Byte-for-byte between two independent runs: determinism, not luck.
check "two runs produce identical bytes" diff -r "$work/a" "$work/b"
check "they match the generator afterwards" \
	python3 "$editor/scripts/make_fixtures.py" verify "$work/a"

# A fixture nobody can tamper with quietly.
printf 'tampered' >> "$work/a/archive/one-map.c7map"
if python3 "$editor/scripts/make_fixtures.py" verify "$work/a" >/dev/null 2>&1; then
	printf '  FAIL a tampered fixture was accepted\n'
	status=1
else
	printf '  ok   a tampered fixture is caught\n'
fi

printf '\nNothing commercial in the tree\n'
# The band is the proof: retail planes hold small indices, so a word this high
# cannot have come from the game. Checked on the generator, which is what the
# fixtures are made from.
check "plane words stay in the synthetic band" \
	grep -q 'SYNTH_BASE = 0xE000' "$editor/scripts/make_fixtures.py"
check "no fixture is committed to the repository" \
	sh -c '! git -C "'"$repo"'" ls-files | grep -qE "^editor/.*\.(c7map|wad|planes|idx)$"'

printf '\nDocumentation stays inside the repository\n'
check "every local Markdown link resolves to a tracked path" \
	python3 "$editor/scripts/audit_links.py"

printf '\nThe E0 test skeleton\n'
check "the unit tests pass" python3 "$editor/tests/unit/test_fixtures.py"

if [ "$status" -eq 0 ]; then
	printf '\nPASS: E0 foundation intact.\n'
else
	printf '\nFAIL: see above.\n'
fi
exit "$status"
