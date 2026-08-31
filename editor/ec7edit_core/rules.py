# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Corridor 7's placement rules, mirrored from the engine rather than invented.

Two things in this format are decided by *topology* rather than stored, and an
editor that guesses differently from the engine shows the author one thing and
ships another.

**A door has no axis.** The map records its colour and nothing else; the engine
works out which way it slides by counting how many of its four neighbours are
open. `door_axis` is that count, copied from `gamemap_planes.cpp` including the
tie-break, so the preview matches what will load.

**A transporter is a pair.** Eight channels, each needing exactly two
endpoints. One is an error and three is an error, and both are the kind of
mistake that is invisible in the raw words and obvious in a list.
"""

from __future__ import annotations

from dataclasses import dataclass

from .document import MapDocument
from .errors import Diagnostic, Severity
from .planes import linear_index
from .prefabs import TRANSPORTER_CHANNELS, is_floor

#: The engine calls a neighbouring cell "open" when it is not a tile -- floor
#: or a sound zone. A wall, a door and a special are all tiles, and all closed.
def is_open(value: int) -> bool:
    return is_floor(value)


@dataclass(frozen=True)
class DoorAxis:
    """Which way a door slides, and how sure the map is about it."""

    horizontal: bool
    open_north: bool
    open_south: bool
    open_west: bool
    open_east: bool

    @property
    def vertical(self) -> bool:
        return not self.horizontal

    @property
    def label(self) -> str:
        """What the door does, in terms a person can check against the map.

        The engine's own name for this is `horizontal`, meaning the tile's
        horizontal offset -- which is the opposite of the corridor it blocks
        and reads backwards to everyone. So the label describes the corridor.
        """
        return "a north-south corridor" if self.horizontal else "an east-west corridor"

    @property
    def approaches(self) -> int:
        return sum((self.open_north, self.open_south, self.open_west, self.open_east))

    @property
    def tie(self) -> bool:
        """Equal openness both ways: the engine picks vertical, but only just."""
        return (self.open_north + self.open_south) == (self.open_west + self.open_east)

    @property
    def two_sided(self) -> bool:
        """A door somebody can walk through from both sides, which is the point."""
        if self.horizontal:
            return self.open_north and self.open_south
        return self.open_west and self.open_east


def door_axis(document: MapDocument, x: int, y: int) -> DoorAxis:
    """Reproduce `gamemap_planes.cpp`'s inference exactly.

        const bool horizontal = (openNorth + openSouth) > (openWest + openEast);

    Note the `>`: a tie is *not* horizontal, so a door with the same number of
    open cells each way takes the default vertical plane. Off the edge of the
    map counts as closed, because the engine's bounds checks make it so.
    """
    plane0 = document.planes.planes[0]
    width, height = document.width, document.height

    def open_at(cx: int, cy: int) -> bool:
        if not (0 <= cx < width and 0 <= cy < height):
            return False
        return is_open(plane0[linear_index(cx, cy, width)])

    north, south = open_at(x, y - 1), open_at(x, y + 1)
    west, east = open_at(x - 1, y), open_at(x + 1, y)
    return DoorAxis((north + south) > (west + east), north, south, west, east)


def check_door(document: MapDocument, x: int, y: int) -> list[Diagnostic]:
    """What is wrong with a door here, if anything."""
    axis = door_axis(document, x, y)
    where = f"cell ({x}, {y})"
    problems = []

    if not axis.two_sided:
        problems.append(Diagnostic(
            "C7E-DOOR-001", Severity.WARNING,
            f"this door blocks {axis.label}, but the floor it needs on both sides "
            "of that corridor is not there, so it opens onto a wall",
            where,
        ))
    if axis.tie and axis.approaches:
        problems.append(Diagnostic(
            "C7E-DOOR-002", Severity.WARNING,
            "the walls around this door are equally open both ways; the engine "
            f"will treat it as blocking {axis.label}, which may not be what it "
            "looks like on the canvas",
            where,
        ))
    return problems


# ---------------------------------------------------------------------------
# Transporters
# ---------------------------------------------------------------------------


def transporter_endpoints(document: MapDocument) -> dict[int, list[tuple[int, int]]]:
    """Every transporter cell on the map, grouped by channel."""
    found: dict[int, list[tuple[int, int]]] = {c: [] for c in TRANSPORTER_CHANNELS}
    plane0 = document.planes.planes[0]
    for index, value in enumerate(plane0):
        if value in found:
            found[value].append((index % document.width, index // document.width))
    return {channel: cells for channel, cells in found.items() if cells}


def check_transporters(document: MapDocument) -> list[Diagnostic]:
    """A channel needs exactly two ends."""
    problems = []
    for channel, cells in sorted(transporter_endpoints(document).items()):
        if len(cells) == 2:
            continue
        first = cells[0]
        problems.append(Diagnostic(
            "C7E-WARP-001", Severity.ERROR,
            f"transporter channel {channel} has {len(cells)} endpoint"
            f"{'s' if len(cells) != 1 else ''}; a channel needs exactly two",
            f"cell ({first[0]}, {first[1]})",
        ))
    return problems


def free_channel(document: MapDocument) -> int | None:
    """The lowest channel with room for another endpoint, or None."""
    used = transporter_endpoints(document)
    for channel in TRANSPORTER_CHANNELS:
        if len(used.get(channel, ())) < 2:
            return channel
    return None


def door_cells(document: MapDocument, catalog=None) -> list[tuple[int, int]]:
    """Every cell holding a door, so the checks know where to look."""
    doors = {251, 252, 253, 254}
    plane0 = document.planes.planes[0]
    return [(index % document.width, index // document.width)
            for index, value in enumerate(plane0) if value in doors]


#: The plane-0 words that are sound areas. Corridor 7 defines 256..286 in the
#: translation; anything outside that is not an area the engine knows.
AREA_FIRST = 256
AREA_LAST = 286


def assign_sound_areas(document) -> list[tuple[int, int, int, int]]:
    """Give every floor cell that has no sound area one, as `write_words` input.

    Corridor 7's floor words are Wolf3D areas, and the engine carries sound
    between two actors only if `CheckLink` finds a path from one's area to the
    other's. Word 0 is walkable but carries no area at all, so a floor built
    from it is a floor nothing can hear through -- see
    `MapDocument.DEFAULT_FLOOR`.

    Regions are the connected runs of floor, four-connected. A door is a
    plane-0 word rather than floor, so it already separates the rooms it joins,
    which is what makes the areas mean anything: sound crosses a doorway when
    the door opens and links the two areas, exactly as it does in the shipped
    maps.

    A region touching cells that already have an area joins that one rather
    than being given a new number -- repairing part of a map must not cut it
    off from the part that was already right. Fresh regions take the next
    unused number, and if a map has more regions than Corridor 7 has area
    words they share the last one: too few areas is a map that hears too much,
    which is recoverable, and an out-of-range word is not a map at all.
    """
    from .prefabs import is_floor

    width, height = document.width, document.height
    plane0 = document.planes.planes[0]

    def at(x, y):
        return plane0[y * width + x]

    used = {value for value in plane0 if AREA_FIRST <= value <= AREA_LAST}
    spare = (n for n in range(AREA_FIRST, AREA_LAST + 1) if n not in used)

    writes: list[tuple[int, int, int, int]] = []
    seen = [False] * (width * height)
    for start in range(width * height):
        if seen[start] or at(start % width, start // width) != 0:
            continue
        # One region: every zoneless floor cell reachable from here.
        region, neighbours, stack = [], set(), [start]
        seen[start] = True
        while stack:
            index = stack.pop()
            x, y = index % width, index // width
            region.append((x, y))
            for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)):
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                value = at(nx, ny)
                if value == 0:
                    if not seen[ny * width + nx]:
                        seen[ny * width + nx] = True
                        stack.append(ny * width + nx)
                elif AREA_FIRST <= value <= AREA_LAST:
                    neighbours.add(value)
                elif is_floor(value):
                    pass
        area = min(neighbours) if neighbours else next(spare, AREA_LAST)
        writes.extend((0, x, y, area) for x, y in region)
    return writes
