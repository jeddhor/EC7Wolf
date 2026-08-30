# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Compound structures: the things that are more than one word.

Corridor 7 builds most of its interesting features out of *pairs* of words on
different planes. A moving wall is an ordinary wall on plane 0 with marker 101
on plane 1. A health chamber is a wall, a door, a use panel and a chamber cell
in a fixed arrangement. Placing one by hand means knowing which words go where
and getting the arithmetic right, which is exactly what an editor exists to
avoid.

Every prefab here declares the six things the design guide requires, and a test
refuses one that is missing any of them:

1. **writes** -- the exact `(plane, dx, dy, value)` set, relative to an anchor;
2. **precondition** -- what must already be true of the cells it covers;
3. **preview** -- what to draw before the click, which is the writes;
4. **undo** -- inherent, because a prefab becomes one command;
5. **validation** -- the diagnostic code when the precondition fails;
6. **rotation** -- how the footprint turns, and what happens to facings;

plus a **source reference**, so anyone can check where the word set came from.

The rule that shapes all of them: a prefab writes raw words and nothing else.
There is no second representation, so a map built with these tools is exactly a
map somebody could have built by hand, and the editor never becomes something
the file format has to know about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .document import MapDocument
from .errors import Diagnostic, Severity
from .planes import linear_index

#: Corridor 7's empty object-plane marker.
EMPTY_OBJECT = 18

#: Plane-0 words that a person can stand on.
def is_floor(value: int) -> bool:
    return value == 0 or 256 <= value <= 300


def is_wall(value: int) -> bool:
    """A solid wall page. Doors and specials are walls too, but not plain ones."""
    return 1 <= value <= 250


@dataclass(frozen=True)
class Write:
    """One word, at an offset from the prefab's anchor."""

    plane: int
    dx: int
    dy: int
    value: int

    def rotated(self, quarter_turns: int) -> "Write":
        """Turn the offset clockwise. The value is handled by the caller."""
        dx, dy = self.dx, self.dy
        for _ in range(quarter_turns % 4):
            dx, dy = -dy, dx
        return Write(self.plane, dx, dy, self.value)


@dataclass(frozen=True)
class Precondition:
    """What must be true of a cell before a prefab may cover it."""

    dx: int
    dy: int
    #: "floor", "wall", "any", or "empty" (nothing on plane 1).
    requires: str
    why: str

    def holds(self, document: MapDocument, x: int, y: int) -> bool:
        cx, cy = x + self.dx, y + self.dy
        if not (0 <= cx < document.width and 0 <= cy < document.height):
            return False
        index = linear_index(cx, cy, document.width)
        plane0 = document.planes.planes[0][index]
        plane1 = document.planes.planes[1][index]
        if self.requires == "floor":
            return is_floor(plane0)
        if self.requires == "wall":
            return is_wall(plane0)
        if self.requires == "empty":
            return plane1 in (0, EMPTY_OBJECT)
        return True

    def rotated(self, quarter_turns: int) -> "Precondition":
        dx, dy = self.dx, self.dy
        for _ in range(quarter_turns % 4):
            dx, dy = -dy, dx
        return Precondition(dx, dy, self.requires, self.why)


@dataclass(frozen=True)
class Prefab:
    """One compound structure, complete enough to place, check, and undo."""

    key: str
    name: str
    description: str
    category: str
    writes: tuple[Write, ...]
    preconditions: tuple[Precondition, ...] = ()
    #: The diagnostic raised when a precondition fails.
    diagnostic: str = "C7E-CELL-004"
    #: What erasing puts back, by offset. Empty means "plain floor and nothing".
    erase_to: tuple[Write, ...] = ()
    #: Whether the footprint has an orientation the user can turn.
    rotatable: bool = False
    #: True for structures only offered under Advanced.
    advanced: bool = False
    evidence: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.writes:
            raise ValueError(f"{self.key}: a prefab with no writes is not a prefab")
        if not self.evidence:
            raise ValueError(f"{self.key}: every prefab records where its words came from")

    @property
    def footprint(self) -> tuple[tuple[int, int], ...]:
        """Every cell the prefab touches, deduplicated, in reading order."""
        cells = {(write.dx, write.dy) for write in self.writes}
        cells |= {(check.dx, check.dy) for check in self.preconditions}
        return tuple(sorted(cells, key=lambda cell: (cell[1], cell[0])))

    def rotated(self, quarter_turns: int) -> "Prefab":
        """The same structure turned clockwise.

        Only the offsets move. A prefab whose *values* encode a facing -- none
        do today, because the facing ones are single words and go through the
        catalogue -- would override this.
        """
        if not self.rotatable or quarter_turns % 4 == 0:
            return self
        from dataclasses import replace

        return replace(
            self,
            writes=tuple(write.rotated(quarter_turns) for write in self.writes),
            preconditions=tuple(c.rotated(quarter_turns) for c in self.preconditions),
        )

    def check(self, document: MapDocument, x: int, y: int) -> list[Diagnostic]:
        """Every reason this prefab may not go here. Empty means it may."""
        problems = []
        for cell in self.footprint:
            cx, cy = x + cell[0], y + cell[1]
            if not (0 <= cx < document.width and 0 <= cy < document.height):
                problems.append(Diagnostic(
                    "C7E-BOUNDARY-001", Severity.ERROR,
                    f"{self.name} does not fit here; it would reach outside the map",
                    f"cell ({cx}, {cy})",
                ))
                return problems
        for check in self.preconditions:
            if not check.holds(document, x, y):
                problems.append(Diagnostic(
                    self.diagnostic, Severity.ERROR,
                    f"{self.name} needs {check.why}",
                    f"cell ({x + check.dx}, {y + check.dy})",
                ))
        return problems

    def placement(self, x: int, y: int) -> list[tuple[int, int, int, int]]:
        """The `(plane, x, y, value)` writes for an anchor at `(x, y)`."""
        return [(w.plane, x + w.dx, y + w.dy, w.value) for w in self.writes]

    def removal(self, x: int, y: int) -> list[tuple[int, int, int, int]]:
        """The writes that take it away again.

        Not the inverse of placement -- that is what undo is for. This is what
        the eraser does to a structure somebody placed earlier and now wants
        gone, which means a defined safe base state rather than whatever was
        there before.
        """
        if self.erase_to:
            return [(w.plane, x + w.dx, y + w.dy, w.value) for w in self.erase_to]
        writes = []
        for cell in self.footprint:
            writes.append((0, x + cell[0], y + cell[1], 0))
            writes.append((1, x + cell[0], y + cell[1], EMPTY_OBJECT))
        return writes


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

#: A wall page that reads as a plain surface, used where a prefab needs a wall
#: and the author has not chosen one. Page 0, the grey diagonal.
DEFAULT_WALL = 1


def _terminal(key, name, value, description, evidence) -> Prefab:
    """A one-shot wall terminal: a single plane-0 word with floor to reach it."""
    return Prefab(
        key=key, name=name, description=description, category="specials",
        writes=(Write(0, 0, 0, value),),
        preconditions=(Precondition(0, 1, "floor", "floor in front of it to reach it from"),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        rotatable=True, evidence=evidence,
    )


def _wall_marker(key, name, marker, description, evidence, *, wall=DEFAULT_WALL,
                 advanced=False, notes="") -> Prefab:
    """A plane-1 marker over a plane-0 wall: the shape most of these take."""
    return Prefab(
        key=key, name=name, description=description, category="walls",
        writes=(Write(0, 0, 0, wall), Write(1, 0, 0, marker)),
        preconditions=(),
        erase_to=(Write(0, 0, 0, wall), Write(1, 0, 0, EMPTY_OBJECT)),
        evidence=evidence, advanced=advanced, notes=notes,
    )


PREFABS: tuple[Prefab, ...] = (
    _wall_marker(
        "prefab.pushwall.secret", "Secret pushwall", 98,
        "Slides two tiles when used, and counts toward the floor's restricted-area "
        "total. This is the one that makes a secret a secret.",
        "xlat/corridor7.txt things trigger 98, secret = true",
    ),
    _wall_marker(
        "prefab.pushwall.plain", "Moving wall", 101,
        "Slides two tiles when used. Unlike the secret pushwall it is not counted, "
        "so it is the one to use for a shortcut rather than a discovery.",
        "xlat/corridor7.txt things trigger 101; the released maps use 101 and 102",
    ),
    _wall_marker(
        "prefab.wall.disintegrating", "Disintegrating wall", 106,
        "Advances four texture frames when used and leaves the masked aperture "
        "open. The wall it starts from must have four consecutive pages.",
        "xlat/corridor7.txt things trigger 106, Wall_AnimateRemove",
        notes="The base wall needs frames at wall, wall+1, wall+2 and wall+3.",
    ),
    _wall_marker(
        "prefab.wall.open-aperture", "Open aperture", 107,
        "The disintegrating wall's already-open state, as the shipped maps store "
        "it. Preserved on import; placing one by hand is an Advanced choice.",
        "xlat/corridor7.txt things ignore 107; the engine reads it as the open state",
        advanced=True,
    ),
    Prefab(
        key="prefab.door.plain",
        name="Door",
        description="Opens on use. The engine works out which way it slides from the "
                    "walls beside it, so it needs solid walls on one axis and floor "
                    "on the other.",
        category="specials",
        writes=(Write(0, 0, 0, 251),),
        preconditions=(
            Precondition(0, 0, "any", "a cell to sit in"),
        ),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        evidence="xlat/corridor7.txt tiles trigger 251, Door_Open",
        notes="Axis is inferred, never stored. See rules.door_axis.",
    ),
    Prefab(
        key="prefab.door.red",
        name="Door (RED lock)",
        description="Needs the RED access card, which a terminal grants rather than "
                    "the floor holding one.",
        category="specials",
        writes=(Write(0, 0, 0, 252),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        evidence="xlat/corridor7.txt tiles trigger 252, arg3 = 1",
    ),
    Prefab(
        key="prefab.door.blue",
        name="Door (BLUE lock)",
        description="Needs the BLUE access card.",
        category="specials",
        writes=(Write(0, 0, 0, 253),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        evidence="xlat/corridor7.txt tiles trigger 253, arg3 = 2",
    ),
    Prefab(
        key="prefab.elevator",
        name="Elevator",
        description="The ordinary floor exit. Its arrow lights when it accepts you, "
                    "which only happens once enough of the floor is cleared.",
        category="specials",
        writes=(Write(0, 0, 0, 63),),
        preconditions=(
            Precondition(0, 1, "floor", "floor in front of it to stand on"),
        ),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        rotatable=True,
        evidence="xlat/corridor7.txt tiles trigger 63, Exit_Normal arg0 = 1",
        notes="arg1 = 64 is the lit panel the engine swaps in on use.",
    ),
    _terminal(
        "prefab.terminal.red", "RED access terminal", 9,
        "Grants the RED access card and switches to its used panel. There is no "
        "red card lying on any floor -- a terminal is the only way to get one.",
        "xlat/corridor7.txt tiles trigger 9, C7_WallSwitch arg0 = 10, arg1 = 1; "
        "lnspec.cpp maps arg1 = 1 to C7Static001",
    ),
    _terminal(
        "prefab.terminal.blue", "BLUE access terminal", 11,
        "Grants the BLUE access card and switches to its used panel.",
        "xlat/corridor7.txt tiles trigger 11, C7_WallSwitch arg0 = 12, arg1 = 2; "
        "lnspec.cpp maps arg1 = 2 to C7Static002",
    ),
    _terminal(
        "prefab.terminal.alarm", "Intruder alarm", 30,
        "Wakes every alien on the floor that can hear it. One shot, and there is "
        "no undoing it in play.",
        "xlat/corridor7.txt tiles trigger 30, C7_WallSwitch arg1 = 3, which calls "
        "P_AlertCorridor7Monsters",
    ),
    Prefab(
        key="prefab.dispenser.health",
        name="Health chamber",
        description="The wall unit that restores health. It opens a four-frame "
                    "aperture, turns the player to face out, and closes again.",
        category="specials",
        writes=(Write(0, 0, 0, 85),),
        preconditions=(
            Precondition(0, 1, "floor", "floor in front of it to stand in"),
        ),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        rotatable=True,
        evidence="xlat/corridor7.txt tiles trigger 85, C7_Dispenser arg0 = 1",
        notes="The engine drives the aperture from the player's own tic; the map "
              "only needs the one wall.",
    ),
    Prefab(
        key="prefab.dispenser.ammo",
        name="Ammo dispenser",
        description="The wall unit that refills standard rounds.",
        category="specials",
        writes=(Write(0, 0, 0, 111),),
        preconditions=(Precondition(0, 1, "floor", "floor in front of it"),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        rotatable=True,
        evidence="xlat/corridor7.txt tiles trigger 111, C7_Dispenser arg0 = 2",
    ),
    Prefab(
        key="prefab.dispenser.visor",
        name="Visor recharger",
        description="The wall unit that refills the visor. Corridor 7 has no visor "
                    "battery to pick up; this is how the visor is recharged.",
        category="specials",
        writes=(Write(0, 0, 0, 110),),
        preconditions=(Precondition(0, 1, "floor", "floor in front of it"),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        rotatable=True,
        evidence="xlat/corridor7.txt tiles trigger 110, C7_Dispenser arg0 = 3",
    ),
    _wall_marker(
        "prefab.pushwall.plain-alt", "Moving wall (alternate)", 102,
        "The same moving wall as 101. The released maps use both words, so both "
        "exist here rather than one being silently rewritten to the other.",
        "xlat/corridor7.txt things trigger 102, identical arguments to 101",
    ),
    Prefab(
        key="prefab.door.plain-alt",
        name="Door (alternate)",
        description="The same door as 251, with the other of the two words the "
                    "released maps use for it.",
        category="specials",
        writes=(Write(0, 0, 0, 254),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        evidence="xlat/corridor7.txt tiles trigger 254, identical arguments to 251",
    ),
    Prefab(
        key="prefab.dispenser.health-alt",
        name="Health chamber (alternate)",
        description="The same health unit as 85, on the wall page two released maps "
                    "use for it directly.",
        category="specials",
        writes=(Write(0, 0, 0, 88),),
        preconditions=(Precondition(0, 1, "floor", "floor in front of it to stand in"),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        rotatable=True,
        evidence="xlat/corridor7.txt tiles trigger 88, C7_Dispenser arg0 = 1",
    ),
    Prefab(
        key="prefab.exit.floor",
        name="Floor exit",
        description="Completes the floor when the player walks over it, rather than "
                    "when they use it. This is the crossed marker, not the elevator.",
        category="specials",
        writes=(Write(0, 0, 0, 287),),
        preconditions=(Precondition(0, 0, "any", "a cell to sit in"),),
        erase_to=(Write(0, 0, 0, 0), Write(1, 0, 0, EMPTY_OBJECT)),
        evidence="xlat/corridor7.txt tiles trigger 287, Exit_Normal with playercross",
    ),
    Prefab(
        key="prefab.exit.vortex",
        name="Exit vortex",
        description="Completes the floor when the player walks into it. The two boss "
                    "floors finish this way instead of by elevator.",
        category="specials",
        writes=(Write(1, 0, 0, 268),),
        preconditions=(
            Precondition(0, 0, "floor", "floor to stand on"),
            Precondition(0, 0, "empty", "nothing else on the cell"),
        ),
        erase_to=(Write(1, 0, 0, EMPTY_OBJECT),),
        evidence="xlat/corridor7.txt things 268, C7ExitVortex",
    ),
)

#: Transporters are a pair, so they are their own tool rather than a prefab:
#: one channel, two endpoints, and the second click is what completes it.
TRANSPORTER_CHANNELS = tuple(range(279, 287))


def by_key(key: str) -> Prefab | None:
    for prefab in PREFABS:
        if prefab.key == key:
            return prefab
    return None


def in_category(category: str) -> list[Prefab]:
    return [prefab for prefab in PREFABS if prefab.category == category]


def placeable(*, include_advanced: bool = False) -> list[Prefab]:
    return [p for p in PREFABS if include_advanced or not p.advanced]
