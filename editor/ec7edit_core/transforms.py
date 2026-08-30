# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Copy, paste, rotate and reflect a region of a map.

Moving cells around is the easy half. The half worth writing carefully is what
happens to things that *face* a direction.

Corridor 7 encodes an actor's facing in the raw word itself: values 108 to 111
are the same alien looking east, north, west and south. Rotating a selection
therefore has to rewrite those words, and the tempting way to do it -- add one
to the value, since the directions are consecutive -- is wrong in a way that
looks right on the first thing you try. The bands are not all four long, they
do not all start on the same rotation, patrol markers have eight, and nothing
in the numbering says which value means which way. Adjacency is a coincidence
of the table, not a rule of the format.

So rotation goes through the catalogue: read the value's direction *by name*,
turn the name, and look up the value that means the new name. A value the
catalogue does not describe as directional is carried through untouched, which
is the right answer for a wall and for an imported word nobody has identified.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog
from .document import MapDocument
from .planes import PLANE_COUNT, linear_index
from .xlat import DIRECTIONS_4, DIRECTIONS_8

#: Compass directions in counter-clockwise order, which is the order both of
#: Corridor 7's bands run in. One step here is 45 degrees; the four-direction
#: bands take two steps at a time.
_COMPASS = DIRECTIONS_8


def rotate_direction(name: str, quarter_turns: int) -> str:
    """Turn a compass name by quarter turns clockwise on screen.

    Screen clockwise is compass counter-clockwise in this table's order, hence
    the sign: rotating the map right takes something facing east to facing
    south, and south is two steps *back* along a counter-clockwise list.
    """
    if name not in _COMPASS:
        return name
    step = (_COMPASS.index(name) - 2 * quarter_turns) % len(_COMPASS)
    return _COMPASS[step]


def mirror_direction(name: str, axis: str) -> str:
    """Reflect a compass name across the vertical or horizontal axis."""
    if name not in _COMPASS:
        return name
    if axis == "horizontal":  # mirror left-right: east <-> west
        pairs = {"east": "west", "west": "east",
                 "northeast": "northwest", "northwest": "northeast",
                 "southeast": "southwest", "southwest": "southeast"}
    elif axis == "vertical":  # mirror top-bottom: north <-> south
        pairs = {"north": "south", "south": "north",
                 "northeast": "southeast", "southeast": "northeast",
                 "northwest": "southwest", "southwest": "northwest"}
    else:
        raise ValueError(f"axis must be 'horizontal' or 'vertical', not {axis!r}")
    return pairs.get(name, name)


@dataclass(frozen=True)
class Clip:
    """A rectangular region of all three planes, detached from any map."""

    width: int
    height: int
    planes: tuple[tuple[int, ...], ...]
    source_map: str = ""

    def __post_init__(self) -> None:
        expected = self.width * self.height
        if len(self.planes) != PLANE_COUNT or any(len(p) != expected for p in self.planes):
            raise ValueError(f"a clip of {self.width}x{self.height} needs {expected} cells")

    def at(self, plane: int, x: int, y: int) -> int:
        return self.planes[plane][linear_index(x, y, self.width)]

    @property
    def cell_count(self) -> int:
        return self.width * self.height


def copy_region(document: MapDocument, x: int, y: int, width: int, height: int) -> Clip:
    """Take a rectangle out of a map. All three planes, always.

    Copying only the plane you can see would silently drop the zone under the
    floor and whatever plane 2 holds, and the paste would look right until
    somebody played it.
    """
    x0, y0 = max(0, x), max(0, y)
    x1 = min(document.width, x + width)
    y1 = min(document.height, y + height)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the selection is empty")

    planes = []
    for plane in range(PLANE_COUNT):
        words = []
        for row in range(y0, y1):
            begin = row * document.width
            words.extend(document.planes.planes[plane][begin + x0 : begin + x1])
        planes.append(tuple(words))
    return Clip(x1 - x0, y1 - y0, tuple(planes), document.uuid)


def _remap(clip: Clip, catalog: Catalog | None, convert) -> tuple[tuple[int, ...], ...]:
    """Rewrite directional plane-1 words through `convert(name) -> name`."""
    if catalog is None:
        return clip.planes

    planes = list(clip.planes)
    rewritten = []
    for value in planes[1]:
        entry = catalog.for_value(1, value)
        if entry is None or not entry.directions:
            rewritten.append(value)
            continue
        directions = dict(entry.directions)
        current = next((name for name, raw in entry.directions if raw == value), "")
        target = convert(current)
        rewritten.append(directions.get(target, value))
    planes[1] = tuple(rewritten)
    return tuple(planes)


def rotate_clip(clip: Clip, quarter_turns: int, catalog: Catalog | None = None) -> Clip:
    """Rotate clockwise on screen by 90 degrees a time, facings included."""
    quarter_turns %= 4
    if quarter_turns == 0:
        return clip

    turned = _remap(clip, catalog, lambda name: rotate_direction(name, quarter_turns))
    width, height = clip.width, clip.height
    for _ in range(quarter_turns):
        rotated = []
        for plane in turned:
            words = []
            # Clockwise: the new row y is the old column y read bottom-to-top.
            for y in range(width):
                for x in range(height):
                    words.append(plane[(height - 1 - x) * width + y])
            rotated.append(tuple(words))
        turned = tuple(rotated)
        width, height = height, width
    return Clip(width, height, turned, clip.source_map)


def flip_clip(clip: Clip, axis: str, catalog: Catalog | None = None) -> Clip:
    """Mirror horizontally or vertically, facings included."""
    mirrored = _remap(clip, catalog, lambda name: mirror_direction(name, axis))
    planes = []
    for plane in mirrored:
        words = []
        for y in range(clip.height):
            row = plane[y * clip.width : (y + 1) * clip.width]
            words.append(tuple(reversed(row)) if axis == "horizontal" else row)
        if axis == "vertical":
            words = list(reversed(words))
        planes.append(tuple(value for row in words for value in row))
    return Clip(clip.width, clip.height, tuple(planes), clip.source_map)


def paste_writes(document: MapDocument, clip: Clip, x: int, y: int, *, planes=None):
    """The `(plane, x, y, value)` writes a paste would make.

    Returned rather than applied, so the caller turns them into one command and
    the paste is one undo step. Cells that would land outside the map are
    dropped: a paste near an edge should put down what fits, not refuse.
    """
    chosen = range(PLANE_COUNT) if planes is None else tuple(planes)
    writes = []
    for plane in chosen:
        for row in range(clip.height):
            target_y = y + row
            if not 0 <= target_y < document.height:
                continue
            for column in range(clip.width):
                target_x = x + column
                if not 0 <= target_x < document.width:
                    continue
                writes.append((plane, target_x, target_y, clip.at(plane, column, row)))
    return writes
