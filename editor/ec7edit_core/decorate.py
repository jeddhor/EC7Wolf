# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Reader for the Corridor 7 DECORATE actors the engine defines.

XLAT says which class a map word spawns; DECORATE says what that class *is* --
what it inherits from, which sprite page it shows when it is standing still,
and what the person who wrote it said about it in the comment above. All three
matter to a catalog entry, and all three are already in the repository, so
the alternative to reading them is maintaining a copy that goes stale the first
time somebody fixes an actor.

Sprite pages are the join to the artwork: a DECORATE frame `C001 A -1` names
page 1 of `GFXTILES.CO7`'s sprite range, which is what the palette browser has
to draw. The `Spawn` state's first page is the one an editor should show,
because that is what the map looks like before anything moves.

This reads either the source tree (`wadsrc/static/actors/corridor7/`) or a
built `ec7wolf.pk3`. Same parser, same result -- the pk3's copies are the same
text.
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

#: A DECORATE sprite frame: a four-character bank name, then frame letters.
#: Corridor 7 uses two kinds. One-off frames are `C` plus three digits, which
#: *is* the GFXTILES page. The aliens use named banks -- `RODX`, `AILO` -- with
#: eight rotations each, and those resolve through `co7map.txt`, which lists
#: every sprite in page order.
_SPRITE = re.compile(r"\b([A-Z][A-Z0-9]{3})\s+[A-Z#\[\]\\]")
_NUMERIC_SPRITE = re.compile(r"^C(\d{3})$")

#: The null sprite. Every actor that does nothing for a tic uses it.
_NULL_SPRITE = "TNT1"
_ACTOR = re.compile(r"^\s*actor\s+(\w+)\s*(?::\s*(\w+))?", re.IGNORECASE)
#: Every state label that appears in Corridor 7's actors. The weapon ones
#: matter more than they look: a weapon's `Spawn` state is its pickup on the
#: floor and `Ready` is the thing in your hands, and they are different art.
#: Leaving Ready/Fire/Hold off this list made the parser take the first frame
#: it saw -- the viewmodel -- as the pickup sprite, so the catalog showed the
#: Taser as a gun barrel and reported it as an item nothing places.
_STATE_LABEL = re.compile(
    r"^\s*(Spawn|See|Path|Missile|Melee|Pain|Death|Raise|Idle"
    r"|Ready|Fire|Hold|Select|Deselect|Flash|Bob|Pickup|Use|AltFire|AltHold)\s*:",
    re.IGNORECASE,
)

SOURCES = ("monsters", "statics", "player")

#: The engine's own list of GFXTILES sprites, in page order. Entry *n* is
#: page *n*, so a bank's first rotation gives the page an editor should draw.
SPRITE_MAP = "co7map.txt"

#: How the player pawn is handed a class rather than finding it on the floor.
_GRANTED = re.compile(
    r'player\.(?:startitem|weaponslot)\s+(?:\d+\s*,\s*)?"(\w+)"', re.IGNORECASE
)


def granted_classes(text: str) -> set[str]:
    """Classes the player pawn is given: starting items and weapon slots.

    These are not placeable and never were. The Taser is weapon slot 1 and a
    starting item, so nothing puts it on a map -- and reporting it as an item
    with no map word, which an earlier version of the catalog did, is just
    wrong about how a player gets a weapon.
    """
    return set(_GRANTED.findall(text))


def load_sprite_map(path: Path | str) -> dict[str, int]:
    """Read `co7map.txt`'s sprites block into `name -> page`."""
    return load_sprite_map_text(Path(path).read_text(encoding="latin-1"))


def load_sprite_map_text(text: str) -> dict[str, int]:
    """The same, from text already in hand."""
    if "sprites" not in text:
        return {}
    block = text.split("sprites", 1)[1]
    block = block[block.index("{") + 1 : block.index("}")]
    return {name: page for page, name in enumerate(re.findall(r'"([^"]+)"', block))}


def resolve_sprite(token: str, sprite_map: dict[str, int] | None) -> int | None:
    """A DECORATE bank name to a GFXTILES page, or None if it is not art."""
    if token == _NULL_SPRITE:
        return None
    numeric = _NUMERIC_SPRITE.match(token)
    if numeric:
        return int(numeric.group(1))
    if not sprite_map:
        return None
    for suffix in ("A1", "A0"):
        page = sprite_map.get(token + suffix)
        if page is not None:
            return page
    return None

#: Engine base classes, by what an actor inheriting from one of them *is*.
#: Matched against the root of the inheritance chain, not the immediate parent,
#: so `C7Disintegrator : C7Weapon : Weapon` reaches "item" in one step of
#: resolution rather than needing its own rule.
_ROOT_ROLES = {
    "weapon": "item",
    "ammo": "item",
    "health": "item",
    "key": "item",
    "inventory": "item",
    "custominventory": "item",
    "scoreitem": "item",
    "maprevealer": "item",
    "armor": "item",
    "basicarmorpickup": "item",
    "powerup": "item",
    "powerupgiver": "item",
    "wolfensteinmonster": "enemy",
    "playerpawn": "player",
}


@dataclass
class ActorInfo:
    """One DECORATE actor, as much as an editor needs to describe it."""

    name: str
    parent: str
    source: str  # which file it came from
    role: str  # enemy | item | decoration | effect | player
    note: str  # the comment above the declaration, if any
    spawn_sprite: int | None = None
    sprites: set[int] = field(default_factory=set)
    states: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    #: True when the player is given this at spawn or holds it in a weapon
    #: slot. Such a class is never placed by a map word and is not missing.
    granted: bool = False

    @property
    def blocking(self) -> bool:
        """Whether walking into it is refused. Decorations mostly block."""
        return self.role in ("enemy", "decoration")


def classify(actors: dict[str, "ActorInfo"], name: str) -> str:
    """Decide what an actor is by following its inheritance to the root.

    The file an actor is declared in is not the answer: `player.txt` holds the
    weapons and the inventory as well as the pawn, and the projectiles live
    beside the monsters that fire them. Only the chain says what something is.

    Deliberately conservative at the end of the chain: an actor that reaches a
    root nothing recognizes becomes a decoration, which is the safest thing for
    an editor to draw and the least likely to imply behavior it lacks.
    """
    seen: set[str] = set()
    current = name
    while current and current not in seen:
        seen.add(current)
        info = actors.get(current)
        parent = info.parent if info else ""
        role = _ROOT_ROLES.get(parent.lower())
        if role:
            return role
        if not parent:
            break
        if parent not in actors:
            # An unresolved parent is a fact, not a guess to paper over.
            return _ROOT_ROLES.get(parent.lower(), "decoration")
        current = parent

    # Nothing in the chain named a known base. Fall back on where it lives:
    # an actor declared among the monsters that has no monster root is one of
    # their projectiles or effects.
    info = actors.get(name)
    if info and info.source == "monsters":
        return "effect"
    return "decoration"


def parse_decorate(text: str, source: str,
                   sprite_map: dict[str, int] | None = None) -> dict[str, ActorInfo]:
    """Parse one DECORATE file into actors keyed by class name."""
    actors: dict[str, ActorInfo] = {}
    lines = text.splitlines()
    pending: list[str] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("//"):
            pending.append(stripped.lstrip("/ ").strip())
            index += 1
            continue

        match = _ACTOR.match(lines[index])
        if not match:
            # Any other content ends a comment's association with what follows.
            if stripped and not stripped.startswith(("/*", "*")):
                pending = []
            index += 1
            continue

        name, parent = match.group(1), (match.group(2) or "")
        note = " ".join(part for part in pending if part).strip()
        pending = []

        body: list[str] = []
        depth = 0
        started = False
        while index < len(lines):
            line = lines[index]
            depth += line.count("{") - line.count("}")
            body.append(line)
            if "{" in line:
                started = True
            index += 1
            if started and depth <= 0:
                break

        info = ActorInfo(name, parent, source, "", note)
        label = None
        first_seen = None
        for line in body:
            found = _STATE_LABEL.match(line)
            if found:
                label = found.group(1).capitalize()
            for sprite in _SPRITE.finditer(line):
                page = resolve_sprite(sprite.group(1), sprite_map)
                if page is None:
                    continue
                info.sprites.add(page)
                if first_seen is None:
                    first_seen = page
                if label:
                    info.states[page].add(label)
                # The Spawn state is what the thing looks like lying on the
                # floor, which is the only frame an editor should draw. It is
                # not always first: a weapon declares Ready and Fire above it.
                if info.spawn_sprite is None and label == "Spawn":
                    info.spawn_sprite = page
        if info.spawn_sprite is None:
            info.spawn_sprite = first_seen
        actors[name] = info

    return actors


def resolve_roles(actors: dict[str, ActorInfo]) -> dict[str, ActorInfo]:
    """Fill in every actor's role once the whole graph is known."""
    for name, info in actors.items():
        info.role = classify(actors, name)
    return actors


def read_actors_from_source(root: Path | str,
                            sprite_map_path: Path | str | None = None) -> dict[str, ActorInfo]:
    """Read `wadsrc/static/actors/corridor7/` out of a checkout.

    `co7map.txt` sits two directories up in the tree this is normally called
    on, so it is found by default and may be pointed at explicitly.
    """
    root = Path(root)
    if sprite_map_path is None:
        candidate = root.parent.parent / SPRITE_MAP
        sprite_map_path = candidate if candidate.exists() else None
    sprite_map = load_sprite_map(sprite_map_path) if sprite_map_path else {}

    actors: dict[str, ActorInfo] = {}
    granted: set[str] = set()
    for source in SOURCES:
        path = root / f"{source}.txt"
        if path.exists():
            text = path.read_text(encoding="latin-1")
            actors.update(parse_decorate(text, source, sprite_map))
            granted |= granted_classes(text)
    for name in granted & set(actors):
        actors[name].granted = True
    return resolve_roles(actors)


def read_actors_from_pk3(path: Path | str) -> dict[str, ActorInfo]:
    """Read the same files out of a built `ec7wolf.pk3`."""
    actors: dict[str, ActorInfo] = {}
    granted: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        try:
            sprite_map = load_sprite_map_text(archive.read(SPRITE_MAP).decode("latin-1"))
        except KeyError:
            sprite_map = {}
        for source in SOURCES:
            try:
                raw = archive.read(f"actors/corridor7/{source}.txt")
            except KeyError:
                continue
            text = raw.decode("latin-1")
            actors.update(parse_decorate(text, source, sprite_map))
            granted |= granted_classes(text)
    for name in granted & set(actors):
        actors[name].granted = True
    return resolve_roles(actors)
