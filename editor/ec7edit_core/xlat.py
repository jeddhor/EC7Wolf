# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Reader for the engine's XLAT translation, `wadsrc/static/xlat/corridor7.txt`.

XLAT is the file that says what a raw map word means: which texture a plane-0
value paints, which special it triggers, which actor a plane-1 value spawns and
whether four consecutive values encode a facing. It is therefore the editor's
authority on semantics, and reading it beats maintaining a second table that
would drift the first time somebody fixed a translator entry.

The subset parsed here is the whole file as Corridor 7 uses it:

    tiles {
        tile N    { texturenorth = "C7W0000"; ... }   -- ordinary wall paint
        trigger N { action = "Door_Open"; arg1 = 16; playeruse = true; }
        zone N {}                                     -- sound zone
        modzone N fillzone ambush;
    }
    things {
        trigger N { ... }
        ignore N;
        {value, ClassName, angles, flags, minskill}
    }

`angles` is the count of consecutive values that encode a facing: 4 for most
actors (east, north, west, south), 8 for a patrol point, 0 for something with
no direction. So one `{108, C7OrganicEye, 4, 0, 1}` entry defines values 108
through 111, and the editor must expand it rather than record a single word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")

_TILE = re.compile(r"\btile\s+(\d+)\s*\{(.*?)\}", re.DOTALL)
_TRIGGER = re.compile(r"\btrigger\s+(\d+)\s*\{(.*?)\}", re.DOTALL)
_ZONE = re.compile(r"\bzone\s+(\d+)\s*\{\s*\}")
_MODZONE = re.compile(r"\bmodzone\s+(\d+)\s+([^;]+);")
_IGNORE = re.compile(r"\bignore\s+(\d+)\s*;")
_THING = re.compile(r"\{\s*(\d+)\s*,\s*([$\w]+)\s*,\s*(\w+)\s*,\s*([\w|]+)\s*,\s*(\d+)\s*\}")
_ASSIGN = re.compile(r"(\w+)\s*=\s*([^;]+);")

#: The eight facings a patrol point can take, and the four an actor can spawn
#: with, in the order the value offsets run. Wolf3D's convention, which
#: Corridor 7 inherited unchanged.
DIRECTIONS_8 = ("east", "northeast", "north", "northwest",
                "west", "southwest", "south", "southeast")
DIRECTIONS_4 = ("east", "north", "west", "south")


@dataclass(frozen=True)
class XlatTile:
    """A plane-0 value that paints an ordinary wall."""

    value: int
    textures: tuple[tuple[str, str], ...]

    @property
    def texture(self) -> str:
        """The north face, which for Corridor 7 is every face."""
        for side, name in self.textures:
            if side == "texturenorth":
                return name
        return self.textures[0][1] if self.textures else ""

    @property
    def uniform(self) -> bool:
        return len({name for _, name in self.textures}) <= 1


@dataclass(frozen=True)
class XlatTrigger:
    """A value that makes a cell do something."""

    value: int
    section: str  # "tiles" or "things"
    action: str
    args: tuple[int, ...]
    flags: frozenset[str]


@dataclass(frozen=True)
class XlatZone:
    value: int
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class XlatThing:
    """A plane-1 value that spawns something.

    `value` is the *base* value. When `angles` is nonzero the entry covers
    `angles` consecutive values, each one a facing.
    """

    value: int
    classname: str
    angles: int
    flags: tuple[str, ...]
    minskill: int

    @property
    def values(self) -> range:
        return range(self.value, self.value + max(1, self.angles))

    @property
    def pathing(self) -> bool:
        return "PATHING" in self.flags

    def direction_for(self, value: int) -> str:
        """Which way a spawn at `value` faces, or '' when it has no facing."""
        if not self.angles:
            return ""
        names = DIRECTIONS_8 if self.angles == 8 else DIRECTIONS_4
        offset = value - self.value
        return names[offset] if 0 <= offset < len(names) else ""


@dataclass
class Xlat:
    """Everything the translation says, indexed by raw value."""

    tiles: dict[int, XlatTile] = field(default_factory=dict)
    tile_triggers: dict[int, XlatTrigger] = field(default_factory=dict)
    zones: dict[int, XlatZone] = field(default_factory=dict)
    things: list[XlatThing] = field(default_factory=list)
    thing_triggers: dict[int, XlatTrigger] = field(default_factory=dict)
    ignored: dict[str, frozenset[int]] = field(default_factory=dict)

    def thing_for(self, value: int) -> XlatThing | None:
        """The entry covering a plane-1 value, facing offsets included."""
        for thing in self.things:
            if value in thing.values:
                return thing
        return None

    def thing_values(self) -> dict[int, XlatThing]:
        """Every plane-1 value that spawns something, expanded from the bases."""
        expanded: dict[int, XlatThing] = {}
        for thing in self.things:
            for value in thing.values:
                expanded[value] = thing
        return expanded


def _strip_comments(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _section(text: str, name: str) -> str:
    """The body of a top-level `name { ... }` block, brace-counted.

    A regex cannot do this: the block contains nested braces, and the naive
    non-greedy match stops at the first inner `}`.
    """
    start = text.find(name)
    while start != -1:
        brace = text.find("{", start)
        if brace == -1:
            break
        depth = 0
        for index in range(brace, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return text[brace + 1 : index]
        break
    return ""


def _parse_trigger(value: int, body: str, section: str) -> XlatTrigger:
    action = ""
    args = {}
    flags = set()
    for key, raw in _ASSIGN.findall(body):
        raw = raw.strip()
        if key == "action":
            action = raw.strip('"')
        elif key.startswith("arg") and key[3:].isdigit():
            args[int(key[3:])] = int(raw, 0)
        elif raw.lower() == "true":
            flags.add(key)
    ordered = tuple(args.get(index, 0) for index in range(max(args, default=-1) + 1))
    return XlatTrigger(value, section, action, ordered, frozenset(flags))


def parse_xlat(text: str) -> Xlat:
    """Parse a translation. Tolerant of layout, strict about structure."""
    clean = _strip_comments(text)
    tiles_body = _section(clean, "tiles")
    things_body = _section(clean, "things")
    result = Xlat()

    for value, body in _TILE.findall(tiles_body):
        textures = tuple(
            (key, raw.strip().strip('"'))
            for key, raw in _ASSIGN.findall(body)
            if key.startswith("texture")
        )
        result.tiles[int(value)] = XlatTile(int(value), textures)

    for value, body in _TRIGGER.findall(tiles_body):
        result.tile_triggers[int(value)] = _parse_trigger(int(value), body, "tiles")
    for value, body in _TRIGGER.findall(things_body):
        result.thing_triggers[int(value)] = _parse_trigger(int(value), body, "things")

    for value in _ZONE.findall(tiles_body):
        result.zones[int(value)] = XlatZone(int(value))
    for value, modifiers in _MODZONE.findall(tiles_body):
        result.zones[int(value)] = XlatZone(int(value), tuple(modifiers.split()))

    for value, classname, angles, flags, minskill in _THING.findall(things_body):
        result.things.append(
            XlatThing(
                value=int(value),
                classname=classname.lstrip("$"),
                angles=int(angles) if angles.isdigit() else 0,
                flags=tuple(f for f in flags.split("|") if f and f != "0"),
                minskill=int(minskill),
            )
        )

    result.ignored = {
        "tiles": frozenset(int(v) for v in _IGNORE.findall(tiles_body)),
        "things": frozenset(int(v) for v in _IGNORE.findall(things_body)),
    }
    return result


def read_xlat(path: Path | str) -> Xlat:
    return parse_xlat(Path(path).read_text(encoding="latin-1"))
