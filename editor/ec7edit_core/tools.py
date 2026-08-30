# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""What the drawing tools compute, with no Qt anywhere near it.

Each function here takes a map and some coordinates and returns the cells a
tool would affect. Turning those into a command, and the command into an undo
step, is the caller's job; putting the geometry here means a line can be tested
by asserting on a list of coordinates instead of by driving a mouse.

The flood fill is bounded, and that is not a detail. An unbounded fill on a
malformed map -- one whose outer wall has a gap, which is exactly the map
somebody is editing when they need the fill -- walks every cell, allocates a
frontier the size of the map, and does it inside the GUI thread. A budget turns
that from a hang into a message.
"""

from __future__ import annotations

from .document import MapDocument
from .planes import linear_index

#: The most cells one fill will change. A 181x181 map is 32 761 cells, so this
#: allows filling the largest legal map completely and stops anything larger.
FILL_BUDGET = 33_000


def line_cells(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham, so a dragged line has no gaps and no repeats.

    A tool that interpolated with floats would drop cells on shallow diagonals
    -- which is where a wall you drew turns out to have a hole in it.
    """
    cells = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = dx + dy
    x, y = x0, y0
    while True:
        cells.append((x, y))
        if x == x1 and y == y1:
            return cells
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x += step_x
        if doubled <= dx:
            error += dx
            y += step_y


def rectangle_cells(x0: int, y0: int, x1: int, y1: int, *, filled: bool = False):
    """The outline of a rectangle, or all of it."""
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    if filled:
        return [(x, y) for y in range(top, bottom + 1) for x in range(left, right + 1)]

    cells = []
    for x in range(left, right + 1):
        cells.append((x, top))
        if bottom != top:
            cells.append((x, bottom))
    for y in range(top + 1, bottom):
        cells.append((left, y))
        if right != left:
            cells.append((right, y))
    return cells


def flood_cells(document: MapDocument, plane: int, x: int, y: int, *,
                budget: int = FILL_BUDGET) -> tuple[list[tuple[int, int]], bool]:
    """Every cell reachable from `(x, y)` holding the same word.

    Returns the cells and whether the budget stopped it. Four-connected, not
    eight: a diagonal gap in a wall is a gap you can see but not walk through,
    and a fill that leaked through one would surprise the person who drew it.
    """
    if not (0 <= x < document.width and 0 <= y < document.height):
        return [], False

    words = document.planes.planes[plane]
    target = words[linear_index(x, y, document.width)]
    width, height = document.width, document.height

    seen = {(x, y)}
    frontier = [(x, y)]
    found = []
    truncated = False

    while frontier:
        if len(found) >= budget:
            truncated = True
            break
        cx, cy = frontier.pop()
        found.append((cx, cy))
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                continue
            if words[linear_index(nx, ny, width)] == target:
                seen.add((nx, ny))
                frontier.append((nx, ny))
    return found, truncated


def pick(document: MapDocument, plane: int, x: int, y: int) -> int | None:
    """The eyedropper: the raw word at a cell, or None outside the map."""
    if not (0 <= x < document.width and 0 <= y < document.height):
        return None
    return document.planes.planes[plane][linear_index(x, y, document.width)]


def rectangle_bounds(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    """`(x, y, width, height)` for a selection dragged in any direction."""
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    return left, top, right - left + 1, bottom - top + 1
