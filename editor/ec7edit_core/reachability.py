# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Can the player get there, and can they finish the floor?

This is the advisory half of the validator. Everything else it reports is a
fact about one cell; this is a claim about the map as a whole, and the plan is
explicit that it must stay advisory: it is not a proof that a floor is
completable, and it is not a design opinion. It answers one question -- what
can be reached from the player start, given the doors and the keys and the
transporters -- and reports only the things that cannot be anything but a
mistake, such as an exit nobody can walk to.

**The model, stated so its limits are visible.**

* Movement is four-connected over floor. Corridor 7's clipping lets a body slip
  diagonally between two corners, so a route this says is missing may exist in
  play. That direction is safe: it means this under-reports.
* A door is passable when its lock is held. An unlocked door is always
  passable, which is true -- every door in the game opens on use.
* Keys are picked up by walking onto them, and granted by using a wall
  terminal, which needs a floor cell beside the terminal. Both are modelled.
* A transporter pair is a two-way edge between its endpoints. Reaching either
  end reaches the other.
* Progress is a fixpoint: flood, collect whatever keys the flood reached, flood
  again with those keys, until nothing new is reached. That is what makes a key
  locked behind the door it opens detectable -- the fixpoint stops with the key
  still outside the reached set.

What it deliberately does not model: pushwalls (a secret is meant to be a
shortcut, and treating one as a required route would invent errors), monsters,
damage, ammunition, and the vertical dimension, of which Corridor 7 has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog
from .document import MapDocument
from .planes import coordinates, linear_index

#: Plane-1 words that are a player start, in the order the catalogue lists
#: them. Corridor 7 reflects a start's angle, so this band reads north, east,
#: south, west -- see MapDocument.PLAYER_START_EAST.
PLAYER_STARTS = (19, 20, 21, 22)


def _is_floor(value: int) -> bool:
    """Walkable plane-0 word: open floor, or floor carrying a sound area."""
    return value == 0 or 256 <= value <= 300


@dataclass
class Reach:
    """What one floor's start can get to."""

    #: Indices into the plane, four-connected from the start.
    reached: set[int] = field(default_factory=set)
    #: Colours held once every reachable key and terminal has been used.
    keys: set[str] = field(default_factory=set)
    #: Locked door cells the flood stopped at, by colour.
    blocked: dict[str, list[int]] = field(default_factory=dict)
    #: True when the map has a start to flood from at all.
    started: bool = False


def _door_colour(entry) -> str | None:
    """The lock colour of a plane-0 door word, or None if it is not locked."""
    if entry is None or entry.subcategory != "door" or "locked" not in entry.aliases:
        return None
    return "RED" if "red" in entry.aliases else "BLUE"


def _key_colour(entry) -> str | None:
    """The colour a plane-1 pickup or a plane-0 terminal grants."""
    if entry is None or "keycard" not in entry.aliases:
        return None
    if entry.plane == 1:
        return "RED" if "red key" in entry.aliases else "BLUE"
    if entry.subcategory != "terminal":
        return None
    return "RED" if "red" in entry.aliases else "BLUE"


def _transporter_links(document: MapDocument, catalog: Catalog | None) -> dict[int, list[int]]:
    """Endpoint index -> the other endpoints on its channel.

    A channel with anything other than two endpoints is left unlinked here.
    That case has its own diagnostic (`C7E-WARP-001`) and guessing which two of
    three the author meant would turn one clear error into a wrong route.
    """
    if catalog is None:
        return {}
    width = document.width
    channels: dict[int, list[int]] = {}
    for index, value in enumerate(document.planes.planes[0]):
        entry = catalog.for_value(0, value)
        if entry is not None and entry.category == "zones" and "transporter" in entry.aliases:
            channels.setdefault(value, []).append(index)
    links: dict[int, list[int]] = {}
    for endpoints in channels.values():
        if len(endpoints) != 2:
            continue
        first, second = endpoints
        links[first] = [second]
        links[second] = [first]
    return links


def analyse(document: MapDocument, catalog: Catalog | None = None) -> Reach:
    """Flood from the player start, opening doors as keys are found."""
    width, height = document.width, document.height
    plane0 = document.planes.planes[0]
    plane1 = document.planes.planes[1]
    reach = Reach()

    starts = [index for index, value in enumerate(plane1) if value in PLAYER_STARTS]
    if not starts:
        return reach
    reach.started = True

    links = _transporter_links(document, catalog)

    # Precompute each cell's role once: floods run repeatedly.
    door_colour: dict[int, str] = {}
    open_doors: set[int] = set()
    key_at: dict[int, str] = {}
    for index, value in enumerate(plane0):
        entry = catalog.for_value(0, value) if catalog else None
        colour = _door_colour(entry)
        if colour:
            door_colour[index] = colour
        elif entry is not None and entry.subcategory == "door":
            # An unlocked door is a wall word, but it is not an obstacle: every
            # door in Corridor 7 opens on use.
            open_doors.add(index)
        granted = _key_colour(entry)
        if granted:
            # A terminal is in a wall; using it needs floor beside it, so the
            # key is collected from any neighbour rather than from the cell.
            key_at[index] = granted
    for index, value in enumerate(plane1):
        entry = catalog.for_value(1, value) if catalog else None
        if entry is not None and entry.subcategory in ("moving wall", "mutable wall"):
            # A pushwall is a wall the player can move, so the room behind it
            # is reachable -- treating a secret as a dead end would report a
            # warning on most of the shipped floors, which is how this was
            # found. It is still not a *required* route: nothing here decides
            # whether a secret is optional.
            open_doors.add(index)
        granted = _key_colour(entry)
        if granted:
            key_at[index] = granted

    def passable(index: int) -> bool:
        if _is_floor(plane0[index]) or index in open_doors:
            return True
        colour = door_colour.get(index)
        return colour is not None and colour in reach.keys

    while True:
        reached = set()
        blocked: dict[str, list[int]] = {}
        stack = [index for index in starts if passable(index) or _is_floor(plane0[index])]
        reached.update(stack)
        while stack:
            index = stack.pop()
            x, y = index % width, index // width
            neighbours = [ny * width + nx
                          for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y))
                          if 0 <= nx < width and 0 <= ny < height]
            neighbours.extend(links.get(index, ()))
            for neighbour in neighbours:
                if neighbour in reached:
                    continue
                if passable(neighbour):
                    reached.add(neighbour)
                    stack.append(neighbour)
                elif neighbour in door_colour:
                    blocked.setdefault(door_colour[neighbour], []).append(neighbour)

        # Anything standing on a reached cell is picked up; a terminal is used
        # from the floor beside it.
        found = set()
        for index, colour in key_at.items():
            if index in reached:
                found.add(colour)
                continue
            x, y = index % width, index // width
            for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)):
                if 0 <= nx < width and 0 <= ny < height and (ny * width + nx) in reached:
                    found.add(colour)
                    break

        if found <= reach.keys:
            reach.reached = reached
            reach.blocked = blocked
            return reach
        reach.keys |= found


def unreachable_floor(document: MapDocument, reach: Reach) -> list[int]:
    """Floor cells the player can never stand on, as plane indices."""
    if not reach.started:
        return []
    return [index for index, value in enumerate(document.planes.planes[0])
            if _is_floor(value) and index not in reach.reached]
