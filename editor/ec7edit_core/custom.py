# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Giving custom content a map word, and telling the engine what it means.

A Corridor 7 map is three grids of numbers, and the translator says what each
number means. Everything the game ships already has a number; a monster from a
resource pack does not, so the editor has to allocate one and then generate the
translator entry that gives it meaning.

Two properties decide the whole design.

**Allocation must be stable.** A word is written into map data the moment
somebody paints with it. If the next session allocated the words in a different
order, a map full of 900s would quietly start spawning something else -- the
worst kind of bug, because the map file is unchanged and looks right. So
allocations are recorded in the project, keyed by what they are for, and a word
once given is never reused for anything else.

**The base game must not change.** Corridor 7's translator is `include`d rather
than replaced, and the generated one is named by the map's own `translator`
key, so it applies to that floor and nothing else. A player loading the pack
finds their game exactly as it was.

The two kinds of custom content need different bands, because plane 0 and plane
1 mean different things:

* **objects** (plane 1) are allocated from 900 upward. Corridor 7's own object
  dispatch stops in the 370s, the words are 16-bit, and nothing reads the gap
  between -- so a high band cannot collide with anything now or later.
* **walls** (plane 0) cannot use a high band at all: 256 and above is a floor
  cell carrying a sound area, and 1..250 are wall IDs that index the game's own
  artwork. A custom texture therefore does not get a new word -- it *re-points*
  a wall ID the map does not otherwise use, which the per-map translator
  confines to that floor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import Diagnostic, Severity, export_error

#: The first object word given to a resource's actor. Corridor 7's own dispatch
#: table ends in the 370s; this leaves a wide gap on purpose, so a future
#: engine change that claims more of the low range cannot reach these.
OBJECT_BASE = 900
#: The last. Plane words are 16-bit, so the ceiling is generous; the limit is
#: here to make "ran out" a diagnostic rather than an overflow.
OBJECT_LAST = 4000

#: Wall IDs a custom texture may claim. 1..250 index the game's own artwork,
#: and the highest are the least likely to be in an author's map already --
#: the shipped floors use the low end heavily. 251..255 are doors and specials
#: and are never offered.
WALL_FIRST = 200
WALL_LAST = 250

_LUMP_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,7}$")


@dataclass(frozen=True)
class Allocation:
    """One map word, and what it was given to."""

    plane: int
    word: int
    kind: str            # "actor" | "texture"
    name: str            # the DECORATE class, or the texture lump
    resource: str        # the pack's digest, so a detached pack is detectable

    @property
    def key(self) -> str:
        return f"{self.plane}:{self.word}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "name": self.name, "resource": self.resource}

    @classmethod
    def from_json(cls, key: str, raw: dict) -> "Allocation":
        plane, _, word = key.partition(":")
        if not plane.isdigit() or not word.isdigit():
            raise export_error("C7E-CUSTOM-001",
                               f"{key!r} is not a plane:word allocation key", key)
        if not isinstance(raw, dict):
            raise export_error("C7E-CUSTOM-001", "an allocation is an object", key)
        return cls(int(plane), int(word), str(raw.get("kind", "")),
                   str(raw.get("name", "")), str(raw.get("resource", "")))


def load(allocations: dict) -> list[Allocation]:
    """Read the project's allocation table, oldest first."""
    return [Allocation.from_json(key, raw) for key, raw in sorted(allocations.items())]


def store(allocations) -> dict:
    return {a.key: a.to_json() for a in allocations}


def allocate(existing, resources, documents=()) -> tuple[list[Allocation], list[Diagnostic]]:
    """The word for every placeable thing in every attached resource.

    Existing allocations are kept exactly as they are -- that is the whole
    point -- and only things without one are given a word. A resource that has
    been detached keeps its allocations too, because a map may still contain
    those words; the problem list says so rather than the table forgetting.
    """
    problems: list[Diagnostic] = []
    allocations = list(existing)
    by_thing = {(a.kind, a.name): a for a in allocations}
    used_objects = {a.word for a in allocations if a.plane == 1}
    used_walls = {a.word for a in allocations if a.plane == 0}

    # Wall IDs any map already uses are off limits: re-pointing one would
    # change walls the author drew on purpose.
    for document in documents:
        used_walls |= {word for word in document.planes.planes[0]
                       if WALL_FIRST <= word <= WALL_LAST}

    seen_actors: dict[str, str] = {}
    for resource in resources:
        digest = resource.sha256
        for actor in resource.actors:
            if not actor.placeable:
                continue
            if actor.name in seen_actors and seen_actors[actor.name] != digest:
                problems.append(Diagnostic(
                    "C7E-CUSTOM-002", Severity.ERROR,
                    f"two resource packs both define {actor.name}; the engine "
                    "would keep whichever loaded last", actor.name))
                continue
            seen_actors[actor.name] = digest

            found = by_thing.get(("actor", actor.name))
            if found is not None:
                continue
            word = next((w for w in range(OBJECT_BASE, OBJECT_LAST + 1)
                         if w not in used_objects), None)
            if word is None:
                problems.append(Diagnostic(
                    "C7E-CUSTOM-003", Severity.ERROR,
                    f"no object word left for {actor.name}; the band "
                    f"{OBJECT_BASE}..{OBJECT_LAST} is full", actor.name))
                continue
            used_objects.add(word)
            allocation = Allocation(1, word, "actor", actor.name, digest)
            allocations.append(allocation)
            by_thing[("actor", actor.name)] = allocation

        for texture in resource.textures:
            if not _LUMP_NAME.match(texture):
                problems.append(Diagnostic(
                    "C7E-CUSTOM-004", Severity.WARNING,
                    f"{texture!r} is not a name the engine can look up; a "
                    "texture is up to eight characters, letters and digits",
                    texture))
                continue
            if by_thing.get(("texture", texture)) is not None:
                continue
            word = next((w for w in range(WALL_LAST, WALL_FIRST - 1, -1)
                         if w not in used_walls), None)
            if word is None:
                problems.append(Diagnostic(
                    "C7E-CUSTOM-003", Severity.WARNING,
                    f"no spare wall ID for {texture}. Wall IDs {WALL_FIRST}.."
                    f"{WALL_LAST} are all in use by this project's maps",
                    texture))
                continue
            used_walls.add(word)
            allocation = Allocation(0, word, "texture", texture, digest)
            allocations.append(allocation)
            by_thing[("texture", texture)] = allocation

    attached = {r.sha256 for r in resources}
    for allocation in allocations:
        if allocation.resource not in attached:
            problems.append(Diagnostic(
                "C7E-CUSTOM-005", Severity.WARNING,
                f"{allocation.name} is still allocated word {allocation.word}, "
                "but the pack it came from is no longer attached. Any map using "
                "that word will spawn nothing.", allocation.name))

    return allocations, problems


def used_by(document, allocations) -> list[Allocation]:
    """Which allocations a map actually contains."""
    planes = document.planes.planes
    return [a for a in allocations if a.word in planes[a.plane]]


# ---------------------------------------------------------------------------
# The translator
# ---------------------------------------------------------------------------

#: The lump the generated translator is written to inside a pack.
TRANSLATOR_LUMP = "xlat/ec7edit.txt"
#: What it builds on. Named rather than copied: the game's own translator is
#: the authority on everything except the words allocated here.
BASE_TRANSLATOR = "xlat/corridor7.txt"


def generate_translator(allocations) -> str:
    """A translator that adds the allocated words to Corridor 7's.

    `include` rather than a copy, and `LoadXlat` keeps the included tables --
    so this is additive. Everything the game already understands still works on
    a floor using it, which is what makes a custom monster something you add to
    a Corridor 7 level rather than something you rebuild one around.
    """
    actors = [a for a in allocations if a.kind == "actor"]
    textures = [a for a in allocations if a.kind == "texture"]

    lines = [
        "// Generated by EC7Edit. Placement only: this adds words for custom",
        "// content and changes nothing the base game defines.",
        f'include "{BASE_TRANSLATOR}"',
        "",
    ]
    if textures:
        lines.append("tiles")
        lines.append("{")
        for allocation in sorted(textures, key=lambda a: a.word):
            lines.append(f"\t// {allocation.name}, from a resource pack")
            lines.append(f"\ttile {allocation.word}")
            lines.append("\t{")
            for side in ("north", "south", "east", "west"):
                lines.append(f'\t\ttexture{side} = "{allocation.name}";')
            lines.append("\t}")
        lines.append("}")
        lines.append("")
    if actors:
        lines.append("things")
        lines.append("{")
        for allocation in sorted(actors, key=lambda a: a.word):
            # {value, class, angles, flags, minskill}. Zero angles because a
            # custom actor has one rotation unless its author says otherwise,
            # and the editor has no way to know that it does.
            lines.append(f"\t{{{allocation.word}, {allocation.name}, 0, 0, 0}}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "Allocation", "BASE_TRANSLATOR", "OBJECT_BASE", "OBJECT_LAST",
    "TRANSLATOR_LUMP", "WALL_FIRST", "WALL_LAST", "allocate",
    "generate_translator", "load", "store", "used_by",
]
