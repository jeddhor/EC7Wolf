#!/usr/bin/env python3
"""Compare a sanitizer run's UBSan findings against the accepted list.

The engine inherits a hundred-odd UndefinedBehaviorSanitizer findings from
ECWolf and ZDoom, in two idioms that cannot be fixed without replacing
machinery this fork did not write. Failing on them would mean a gate nobody
can ever make green; ignoring them would mean a new finding -- in new code,
where it might matter -- disappearing into the crowd.

So they are written down, in tools/ubsan-accepted.txt, and this fails on
anything that is not on the list. Entries on the list that no longer fire are
reported too, because a stale acceptance is a claim about the program that has
stopped being true.

Usage: ubsan_check.py LOG [LOG...] --accepted FILE [--quiet]
Exit 0 if every finding is accounted for, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FINDING = re.compile(r"^(?P<path>[^\s:]+):(?P<line>\d+):(?P<col>\d+): "
                     r"runtime error: (?P<message>.*)$")


def classify(message: str) -> str:
    """The sanitizer's own check name, as best it can be recovered.

    UBSan prints prose rather than the check that produced it, so this maps
    the prose back. Anything unrecognised is reported under its own text,
    which fails the gate rather than being quietly filed as something else.
    """
    if "does not point to an object" in message or message.startswith("downcast"):
        return "vptr"
    if "misaligned" in message:
        return "alignment"
    if "null pointer" in message or "reference binding to null" in message:
        return "null"
    if "left shift" in message or "shift exponent" in message:
        return "shift"
    if "overflow" in message:
        return "overflow"
    if "not a valid value for type 'bool'" in message:
        return "bool"
    return "other"


def read_accepted(path: Path) -> dict[tuple[str, str], str]:
    accepted = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            sys.exit(f"{path}:{number}: expected 'kind path', got {raw!r}")
        kind, source = parts
        accepted[(kind, source)] = raw
    return accepted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--accepted", required=True)
    parser.add_argument("--root", default="",
                        help="prefix stripped from reported paths")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-stale", action="store_true",
                        help="do not report accepted entries that did not "
                             "fire. Use when the logs given are only part of "
                             "the picture: one scenario does not reach every "
                             "file, and an entry is only stale if nothing "
                             "reaches it.")
    args = parser.parse_args()

    accepted = read_accepted(Path(args.accepted))
    seen: dict[tuple[str, str], int] = {}
    unexpected: dict[tuple[str, str], tuple[int, str]] = {}

    for log in args.logs:
        text = Path(log).read_text(errors="replace")
        for raw in text.splitlines():
            match = FINDING.match(raw.strip())
            if not match:
                continue
            source = match.group("path")
            if args.root and source.startswith(args.root):
                source = source[len(args.root):].lstrip("/")
            key = (classify(match.group("message")), source)
            seen[key] = seen.get(key, 0) + 1
            if key not in accepted:
                count, _ = unexpected.get(key, (0, ""))
                unexpected[key] = (count + 1, raw.strip())

    total = sum(seen.values())
    if not args.quiet:
        print(f"  ..   {total} UBSan finding(s), "
              f"{len(seen)} distinct kind/file pair(s)")

    stale = [] if args.no_stale else sorted(
        key for key in accepted if key not in seen)
    for kind, source in stale:
        print(f"  ..   accepted but no longer seen: {kind} {source} "
              f"-- delete it from the accepted list")

    if not unexpected:
        return 0

    print("")
    for (kind, source), (count, example) in sorted(unexpected.items()):
        print(f"  FAIL {count} unaccepted {kind} finding(s) in {source}")
        print(f"         {example}")
    print("")
    print("  If these are new code, fix them. If they are inherited and")
    print("  genuinely not fixable, add them to the accepted list with a")
    print("  reason -- and say why in docs/undefined-behaviour.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
