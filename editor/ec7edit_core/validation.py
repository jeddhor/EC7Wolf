# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""A deliberately small validator: the things that stop a map loading or playing.

E5's scope is explicit about this being basic, and that is the right shape. A
validator that reported forty advisory notes on a map somebody just started
would train them to ignore it, and the note that mattered would be lost in the
list. E7 extends *this* service rather than a second one, so a rule added later
appears everywhere the editor already shows problems.

What is checked now:

* the outer boundary is solid, because an open edge lets the player walk out of
  the world;
* exactly one player start, because zero will not spawn and more than one is
  ambiguous;
* every word is a word the translation knows, so nothing silently spawns
  nothing;
* things stand on floor rather than inside walls;
* a locked door has a matching key somewhere on the floor.

Each diagnostic carries a stable `C7E-*` code and a cell, so the GUI can put
the cursor on the problem instead of describing it.
"""

from __future__ import annotations

from .catalog import Catalog
from .document import MapDocument
from .errors import Diagnostic, Severity
from .planes import coordinates, linear_index

#: Corridor 7's empty object-plane marker. Not zero.
EMPTY_OBJECT = 18

#: Plane-0 words that are floor rather than wall. Zero is open floor; the sound
#: zones are floor with an area number on them.
def _is_floor(value: int) -> bool:
    return value == 0 or 256 <= value <= 300


def _where(x: int, y: int) -> str:
    return f"cell ({x}, {y})"


def validate_map(document: MapDocument, catalog: Catalog | None = None) -> list[Diagnostic]:
    """Check one map. Returns diagnostics worst first.

    Imported maps are judged more gently than authored ones, which is the
    plan's rule and also just true: the shipped maps have twelve cells with a
    thing inside a wall, and an editor that opens somebody's legally purchased
    game and reports it as broken has taught them to ignore the panel. The same
    placement made by hand *is* an error, because it is a mistake being made
    now rather than one preserved from 1994.
    """
    problems: list[Diagnostic] = []
    imported = document.source is not None and bool(document.source.sha256)
    preserved = Severity.WARNING if imported else Severity.ERROR
    width, height = document.width, document.height
    plane0 = document.planes.planes[0]
    plane1 = document.planes.planes[1]

    # -- the outer boundary ----------------------------------------------
    open_edges = []
    for x in range(width):
        for y in (0, height - 1):
            if _is_floor(plane0[linear_index(x, y, width)]):
                open_edges.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if _is_floor(plane0[linear_index(x, y, width)]):
                open_edges.append((x, y))
    if open_edges:
        first = open_edges[0]
        problems.append(Diagnostic(
            "C7E-BOUNDARY-001", Severity.ERROR,
            f"{len(open_edges)} cell(s) on the outer boundary are walkable; "
            "the player can leave the map",
            _where(*first),
        ))

    # -- player starts ----------------------------------------------------
    starts = []
    if catalog is not None:
        for index, value in enumerate(plane1):
            entry = catalog.for_value(1, value)
            if entry is not None and entry.category == "starts" and entry.subcategory == "player":
                starts.append(coordinates(index, width))
    if catalog is not None:
        if not starts:
            problems.append(Diagnostic(
                "C7E-START-001", Severity.ERROR,
                "there is no player start on this map", "",
            ))
        elif len(starts) > 1:
            problems.append(Diagnostic(
                "C7E-START-002", Severity.ERROR,
                f"{len(starts)} player starts; a single-player map needs exactly one",
                _where(*starts[1]),
            ))
        else:
            index = linear_index(starts[0][0], starts[0][1], width)
            if not _is_floor(plane0[index]):
                problems.append(Diagnostic(
                    "C7E-START-003", Severity.ERROR,
                    "the player start is inside a wall", _where(*starts[0]),
                ))

    # -- words the translation does not know ------------------------------
    if catalog is not None:
        unknown0, unknown1 = set(), set()
        for index, value in enumerate(plane0):
            if value and catalog.for_value(0, value) is None:
                unknown0.add((value, coordinates(index, width)))
        for index, value in enumerate(plane1):
            if value and value != EMPTY_OBJECT and catalog.for_value(1, value) is None:
                unknown1.add((value, coordinates(index, width)))
        for plane, unknown in ((0, unknown0), (1, unknown1)):
            for value, cell in sorted(unknown)[:5]:
                problems.append(Diagnostic(
                    "C7E-CELL-002", Severity.WARNING,
                    f"plane {plane} word {value} is not in the catalogue; it is "
                    "preserved exactly and spawns nothing the editor knows about",
                    _where(*cell),
                ))

    # -- things standing in walls -----------------------------------------
    if catalog is not None:
        buried = []
        for index, value in enumerate(plane1):
            if not value or value == EMPTY_OBJECT:
                continue
            entry = catalog.for_value(1, value)
            if entry is None or entry.placement != "floor":
                continue
            if not _is_floor(plane0[index]):
                buried.append((coordinates(index, width), entry.name))
        for cell, name in buried[:5]:
            problems.append(Diagnostic(
                "C7E-THING-001", preserved,
                f"{name} is inside a wall"
                + (" (preserved from the imported map)" if imported else ""),
                _where(*cell),
            ))

    # -- wall markers with no wall under them ------------------------------
    # The mirror of the check above, and the one that catches a pushwall placed
    # as a bare marker: 98, 101, 102 and 106 modify the wall cell they sit in,
    # so on open floor they are a moving wall with nothing to move.
    if catalog is not None:
        floating = []
        for index, value in enumerate(plane1):
            if not value or value == EMPTY_OBJECT:
                continue
            entry = catalog.for_value(1, value)
            if entry is None or entry.placement != "wall":
                continue
            if not (1 <= plane0[index] <= 250):
                floating.append((coordinates(index, width), entry.name))
        for cell, name in floating[:5]:
            problems.append(Diagnostic(
                "C7E-WALL-001", preserved if imported else Severity.ERROR,
                f"{name} has no wall to act on; it needs a solid wall in the same cell",
                _where(*cell),
            ))

    # -- locked doors without their key ------------------------------------
    if catalog is not None:
        locks = {}
        for index, value in enumerate(plane0):
            entry = catalog.for_value(0, value)
            if entry is not None and entry.subcategory == "door" and "locked" in entry.aliases:
                colour = "RED" if "red" in entry.aliases else "BLUE"
                locks.setdefault(colour, coordinates(index, width))
        if locks:
            # A card reaches the player two ways: lying on the floor, or handed
            # over by the wall terminal of that colour. Corridor 7 mostly uses
            # the terminal, so counting only floor cards would warn about the
            # ordinary case.
            keys = set()
            for value in plane1:
                entry = catalog.for_value(1, value)
                if entry is not None and "keycard" in entry.aliases:
                    keys.add("RED" if "red key" in entry.aliases else "BLUE")
            for value in plane0:
                entry = catalog.for_value(0, value)
                if entry is not None and entry.subcategory == "terminal" \
                        and "keycard" in entry.aliases:
                    keys.add("RED" if "red" in entry.aliases else "BLUE")
            for colour, cell in locks.items():
                if colour not in keys:
                    problems.append(Diagnostic(
                        "C7E-DOOR-003", Severity.WARNING,
                        f"a {colour}-locked door has no {colour} access card on this "
                        f"floor and no {colour} terminal to grant one",
                        _where(*cell),
                    ))

    problems.sort(key=lambda problem: -problem.severity.value)
    return problems


def summarise(problems) -> str:
    """One line for a status bar."""
    errors = sum(1 for problem in problems if problem.severity is Severity.ERROR)
    warnings = sum(1 for problem in problems if problem.severity is Severity.WARNING)
    if not problems:
        return "No problems found"
    parts = []
    if errors:
        parts.append(f"{errors} error{'s' if errors > 1 else ''}")
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings > 1 else ''}")
    return ", ".join(parts)
