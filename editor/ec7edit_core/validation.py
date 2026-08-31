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
* a locked door has a matching key somewhere on the floor;
* the floor is made of sound areas, because a cell with no area is a cell
  nothing can hear the player through;
* the floor can be finished: an exit the player can walk to, given the doors,
  the keys and the transporters between them.

Reachability is advisory and its model is written down in `reachability.py`,
limits included. It under-reports rather than inventing errors.

Each diagnostic carries a stable `C7E-*` code and a cell, so the GUI can put
the cursor on the problem instead of describing it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog
from .document import MapDocument
from .errors import Diagnostic, Severity
from .planes import coordinates, linear_index
from .reachability import analyse, unreachable_floor

#: Corridor 7's empty object-plane marker. Not zero.
EMPTY_OBJECT = 18

#: Plane-0 words that are floor rather than wall. Zero is open floor; the sound
#: zones are floor with an area number on them.
def _is_floor(value: int) -> bool:
    return value == 0 or 256 <= value <= 300


def _where(x: int, y: int) -> str:
    return f"cell ({x}, {y})"


@dataclass(frozen=True)
class Profile:
    """What kind of map is being checked.

    Corridor 7's rules are not the same for every slot: a floor exported to a
    stock single-player slot must have exactly one start and a way out, and a
    map being built as a deathmatch arena has neither. Rather than a pile of
    booleans at every call site, the profile is one object the rules ask.
    """

    key: str
    name: str
    #: How many player starts are right. None means "do not check".
    starts: int | None = 1
    #: Whether the floor has to be completable.
    needs_exit: bool = True
    #: Whether unreachable floor is worth reporting.
    reports_unreachable: bool = True


#: The default, and the only one the exporters currently target.
SINGLE_PLAYER = Profile("single_player_stock_slot", "Single player, stock slot")
#: The stock slots that hold a network arena rather than a campaign floor.
#:
#: From wadsrc/static/mapinfo/corridor7.txt, where each of these names itself as
#: its own `next` and sets `nointermission` -- a finished match starts another
#: on the same arena. They are not the contiguous block the compendium
#: describes: the maps at 58 and 59 are bare boxes and the eighth arena is at
#: 60. An arena has no exit and several starts, and judging one by the
#: campaign's rules reports both as faults.
ARENA_SLOTS = frozenset({51, 52, 53, 54, 55, 56, 57, 60})
#: A map for the multiplayer arenas: several starts, no exit, and unreachable
#: pockets are usually deliberate scenery.
DEATHMATCH = Profile("deathmatch", "Deathmatch arena",
                     starts=None, needs_exit=False, reports_unreachable=False)
PROFILES = {profile.key: profile for profile in (SINGLE_PLAYER, DEATHMATCH)}


def profile_for_slot(slot: int) -> Profile:
    """The rules that apply to the stock slot a map is exported to.

    This is the plan's "target-slot context": the same map is right or wrong
    depending on where it is going, and the editor knows where it is going
    because the document says which slot it occupies.
    """
    return DEATHMATCH if slot in ARENA_SLOTS else SINGLE_PLAYER


#: Codes whose answer depends only on the cells around the one that changed.
#: An incremental pass runs these and keeps the rest of the previous result,
#: which is what makes validating on every stroke affordable; a full pass runs
#: everything and is what the Problems panel and the export preflight use.
LOCAL_CODES = frozenset({
    "C7E-BOUNDARY-001", "C7E-CELL-002", "C7E-THING-001", "C7E-WALL-001",
    "C7E-ZONE-001",
})

#: Codes that are a claim about the whole map: starts, keys, routes, exits.
GLOBAL_CODES = frozenset({
    "C7E-START-001", "C7E-START-002", "C7E-START-003", "C7E-DOOR-003",
    "C7E-DOOR-004", "C7E-EXIT-001", "C7E-ZONE-002",
})


def validate_local(document: MapDocument, catalog: Catalog | None = None, *,
                   profile: Profile = SINGLE_PLAYER,
                   previous: list[Diagnostic] | None = None) -> list[Diagnostic]:
    """A cheap pass for "the user just painted a cell".

    Runs the rules whose answer is local and reuses the previous result for the
    ones that are not, so the panel stays useful between full passes without
    flooding a stroke with reachability work. The contract the tests hold it
    to: for every code in `LOCAL_CODES`, this agrees exactly with a full
    validation of the same document.
    """
    fresh = validate_map(document, catalog, profile=profile, only=LOCAL_CODES)
    local = [problem for problem in fresh if problem.code in LOCAL_CODES]
    stale = [problem for problem in (previous or []) if problem.code not in LOCAL_CODES]
    return sorted(local + stale,
                  key=lambda problem: (-problem.severity.value, problem.code,
                                       problem.cell or (0, 0)))


def validate_map(document: MapDocument, catalog: Catalog | None = None, *,
                 profile: Profile = SINGLE_PLAYER,
                 only: frozenset[str] | None = None) -> list[Diagnostic]:
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
            "C7E-BOUNDARY-001", preserved if imported else Severity.ERROR,
            f"{len(open_edges)} cell(s) on the outer boundary are walkable; "
            "the player can leave the map",
            _where(*first), first, fix="seal_boundary",
        ))

    # -- player starts ----------------------------------------------------
    starts = []
    if catalog is not None:
        for index, value in enumerate(plane1):
            entry = catalog.for_value(1, value)
            if entry is not None and entry.category == "starts" and entry.subcategory == "player":
                starts.append(coordinates(index, width))
    if catalog is not None and profile.starts is not None:
        if not starts:
            problems.append(Diagnostic(
                "C7E-START-001", Severity.ERROR,
                "there is no player start on this map", "",
            ))
        elif len(starts) > profile.starts:
            problems.append(Diagnostic(
                "C7E-START-002", Severity.ERROR,
                f"{len(starts)} player starts; {profile.name} needs exactly "
                f"{profile.starts}",
                _where(*starts[1]), starts[1],
            ))
    if catalog is not None:
        for start in starts:
            if not _is_floor(plane0[linear_index(start[0], start[1], width)]):
                problems.append(Diagnostic(
                    "C7E-START-003", Severity.ERROR,
                    "the player start is inside a wall", _where(*start), start,
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

    # -- floor with no sound area ------------------------------------------
    #
    # Corridor 7's floor words are Wolf3D areas. The engine decides whether a
    # monster hears gunfire by asking map->CheckLink() whether the shooter's
    # area reaches the listener's, and CheckLink answers false the moment
    # either side is NULL. Word 0 is walkable but carries no area, so on a
    # floor built from it nothing can hear anything: aliens ignore gunfire
    # entirely and wake only on sight or on contact, which reads as "the
    # monsters are broken" rather than as a property of the floor. None of the
    # sixty shipped maps contains a single plane-0 zero.
    # Severity follows the same rule as the other authored-content checks: an
    # error in a map somebody is drawing, a warning in one that came out of the
    # retail archive, where an unexpected word is evidence about the original
    # rather than a mistake to correct.
    zoneless = [index for index, value in enumerate(plane0) if value == 0]
    if zoneless:
        problems.append(Diagnostic(
            "C7E-ZONE-001", preserved if imported else Severity.ERROR,
            f"{len(zoneless)} floor cell(s) have no sound area, so nothing on this "
            "map can hear the player; Tools -> Give the floor sound areas fixes it",
            _where(*coordinates(zoneless[0], width)),
            coordinates(zoneless[0], width), fix="sound_areas",
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

    # -- reachability -----------------------------------------------------
    #
    # Advisory by design: the model in reachability.py under-reports rather
    # than inventing routes, and the plan is explicit that this is not a proof
    # that a floor can be finished.
    if catalog is not None and starts and (only is None or (GLOBAL_CODES & only)):
        reach = analyse(document, catalog)

        # A key behind the only door it opens. The flood is a fixpoint, so a
        # colour still blocking when it stops is a colour whose key the player
        # can never hold -- which is the one shape of key puzzle that is always
        # a mistake rather than a design.
        for colour, cells in sorted(reach.blocked.items()):
            if colour in reach.keys:
                continue
            cell = coordinates(cells[0], width)
            problems.append(Diagnostic(
                "C7E-DOOR-004", Severity.WARNING,
                f"the {colour} access card cannot be reached without the "
                f"{colour} card; the route through this door is closed to the player",
                _where(*cell), cell,
            ))

        if profile.needs_exit:
            exits = []
            for plane, words in ((0, plane0), (1, plane1)):
                for index, value in enumerate(words):
                    entry = catalog.for_value(plane, value)
                    if entry is not None and entry.subcategory in ("exit",) \
                            or (entry is not None and "exit" in entry.aliases):
                        exits.append(index)
            if not exits:
                # A warning, not an error, and deliberately: a map somebody
                # started ten minutes ago has no exit yet, and a validator that
                # opens with an error on every new map is one they learn to
                # ignore. It still has to be said -- a floor with no way out is
                # not finishable -- so it is said once, quietly.
                problems.append(Diagnostic(
                    "C7E-EXIT-001", Severity.WARNING,
                    "there is no way to finish this floor; place an elevator "
                    "switch, a floor exit or an exit vortex", "",
                ))
            elif not any(_touches(index, reach.reached, width, height)
                         for index in exits):
                cell = coordinates(exits[0], width)
                problems.append(Diagnostic(
                    "C7E-EXIT-001", Severity.WARNING,
                    "the player cannot reach any exit on this floor",
                    _where(*cell), cell,
                ))

        if profile.reports_unreachable:
            stranded = unreachable_floor(document, reach)
            if stranded:
                cell = coordinates(stranded[0], width)
                problems.append(Diagnostic(
                    "C7E-ZONE-002", Severity.WARNING,
                    f"{len(stranded)} floor cell(s) cannot be reached from the "
                    "player start",
                    _where(*cell), cell,
                ))

    problems.sort(key=lambda problem: (-problem.severity.value, problem.code,
                                       problem.cell or (0, 0)))
    return problems


def _touches(index: int, reached: set[int], width: int, height: int) -> bool:
    """Whether a cell is reached, or has a reached cell beside it.

    An exit is often a switch in a wall, which the player never stands on --
    they stand next to it and use it. Asking only whether the exit cell itself
    was flooded would report every elevator in the game as unreachable.
    """
    if index in reached:
        return True
    x, y = index % width, index // width
    for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)):
        if 0 <= nx < width and 0 <= ny < height and (ny * width + nx) in reached:
            return True
    return False


# -- safe repairs ---------------------------------------------------------
#
# A fix is offered only where there is exactly one thing the author can have
# meant. Sealing a boundary and giving the floor sound areas both qualify:
# neither has a second reasonable answer, and both are tedious by hand. Most
# diagnostics have no fix on purpose -- "there is no exit" has a hundred
# answers and picking one for somebody is not a repair, it is a guess.


def _fix_seal_boundary(document: MapDocument) -> list[tuple[int, int, int, int]]:
    """Paint the outer ring solid."""
    width, height = document.width, document.height
    plane0 = document.planes.planes[0]
    writes = []
    for x in range(width):
        for y in (0, height - 1):
            if _is_floor(plane0[linear_index(x, y, width)]):
                writes.append((0, x, y, document.SOLID_WALL))
    for y in range(height):
        for x in (0, width - 1):
            if _is_floor(plane0[linear_index(x, y, width)]):
                writes.append((0, x, y, document.SOLID_WALL))
    return writes


def _fix_sound_areas(document: MapDocument) -> list[tuple[int, int, int, int]]:
    from .rules import assign_sound_areas

    return assign_sound_areas(document)


#: id -> (label, builder). The builder returns `write_words` input, so a fix is
#: an ordinary command: one undo, and no path that edits a document directly.
FIXES = {
    "seal_boundary": ("Seal the map boundary", _fix_seal_boundary),
    "sound_areas": ("Give the floor sound areas", _fix_sound_areas),
}


def fix_writes(fix: str, document: MapDocument) -> list[tuple[int, int, int, int]]:
    """The writes a fix would make, or an empty list if there is nothing to do."""
    entry = FIXES.get(fix)
    return entry[1](document) if entry else []


def fix_label(fix: str) -> str:
    entry = FIXES.get(fix)
    return entry[0] if entry else ""


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
