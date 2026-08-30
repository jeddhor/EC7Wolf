#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E6's exit gate, as a report: is every semantic reachable, or labelled?

The milestone's promise is not "every word has a tool" -- some words are
preserved-only by design, and one or two are Advanced. The promise is that
*nothing is silent*: every value the translation defines is either offered
through a friendly tool or carries a written reason why it is not.

    coverage_report.py            print the report
    coverage_report.py --check    exit non-zero if anything is unaccounted for

An entry is accounted for when it is one of:

  * covered by a prefab, so a compound feature needs no raw arithmetic;
  * a plain palette item -- one word, no preconditions, nothing compound about
    it, which the brush already places correctly;
  * explicitly marked imported-only or Advanced, with a reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
REPO = EDITOR.parent
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import load_catalog  # noqa: E402
from ec7edit_core.prefabs import PREFABS, TRANSPORTER_CHANNELS  # noqa: E402

CATALOG = EDITOR / "resources" / "editor_catalog.json"

#: Categories whose entries are a single word with no compound behaviour. The
#: ordinary brush places these correctly by construction.
SIMPLE_CATEGORIES = ("walls", "objects", "enemies", "starts", "zones")


def prefab_values() -> dict[int, set[int]]:
    """Every `(plane, value)` a prefab writes."""
    covered: dict[int, set[int]] = {0: set(), 1: set(), 2: set()}
    for prefab in PREFABS:
        for write in prefab.writes:
            covered[write.plane].add(write.value)
    for channel in TRANSPORTER_CHANNELS:
        covered[0].add(channel)
    return covered


def report() -> tuple[list[str], list[str]]:
    catalog = load_catalog(CATALOG)
    covered = prefab_values()

    lines: list[str] = []
    unaccounted: list[str] = []
    counts = {"prefab": 0, "simple": 0, "imported-only": 0, "advanced": 0}

    for entry in catalog:
        how = None
        if any(value in covered[entry.plane] for value in entry.values):
            how = "prefab"
        elif not entry.safe_for_new_maps:
            how = "imported-only"
        elif entry.category in SIMPLE_CATEGORIES:
            how = "simple"

        if how is None:
            unaccounted.append(f"{entry.key} ({entry.category}, plane {entry.plane} "
                               f"value {entry.value}) has no tool and no label")
        else:
            counts[how] += 1

    lines.append("EC7Edit semantic coverage")
    lines.append("")
    lines.append(f"  {len(catalog)} catalogue entries")
    lines.append(f"    {counts['prefab']:4d} placed by a compound tool")
    lines.append(f"    {counts['simple']:4d} single-word items the brush places directly")
    lines.append(f"    {counts['imported-only']:4d} preserved from imported maps, not offered for new work")
    lines.append("")
    lines.append(f"  {len(PREFABS)} compound tools:")
    for prefab in PREFABS:
        flag = "  [Advanced]" if prefab.advanced else ""
        cells = len(prefab.footprint)
        lines.append(f"    {prefab.key:34} {len(prefab.writes)} write(s), "
                     f"{cells} cell(s){flag}")
    lines.append(f"    transporter pair tool                {len(TRANSPORTER_CHANNELS)} channels")
    return lines, unaccounted


def main(argv: list[str]) -> int:
    lines, unaccounted = report()
    print("\n".join(lines))
    if unaccounted:
        print(f"\n  {len(unaccounted)} entr{'y' if len(unaccounted) == 1 else 'ies'} "
              "with neither a tool nor a label:")
        for line in unaccounted[:20]:
            print(f"    {line}")
        return 1 if "--check" in argv else 0
    print("\n  every entry is either tool-covered or labelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
