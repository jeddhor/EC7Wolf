# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Reader for the Corridor 7 DECORATE actors the engine defines.

XLAT says which class a map word spawns; DECORATE says what that class *is* --
what it inherits from, which sprite page it shows when it is standing still,
and what the person who wrote it said about it in the comment above. All three
matter to a catalogue entry, and all three are already in the repository, so
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

#: A DECORATE sprite frame: four-character page name, then frame letters.
#: Corridor 7's are all `C` plus three digits.
_SPRITE = re.compile(r"\bC(\d{3})\s+[A-Z]")
_ACTOR = re.compile(r"^\s*actor\s+(\w+)\s*(?::\s*(\w+))?", re.IGNORECASE)
_STATE_LABEL = re.compile(
    r"^\s*(Spawn|See|Path|Missile|Melee|Pain|Death|Raise|Idle)\s*:", re.IGNORECASE
)

SOURCES = ("monsters", "statics", "player")

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
    root nothing recognises becomes a decoration, which is the safest thing for
    an editor to draw and the least likely to imply behaviour it lacks.
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


def parse_decorate(text: str, source: str) -> dict[str, ActorInfo]:
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
        for line in body:
            found = _STATE_LABEL.match(line)
            if found:
                label = found.group(1).capitalize()
            for sprite in _SPRITE.finditer(line):
                page = int(sprite.group(1))
                info.sprites.add(page)
                if label:
                    info.states[page].add(label)
                if info.spawn_sprite is None and label in (None, "Spawn"):
                    info.spawn_sprite = page
        if info.spawn_sprite is None and info.sprites:
            info.spawn_sprite = min(info.sprites)
        actors[name] = info

    return actors


def resolve_roles(actors: dict[str, ActorInfo]) -> dict[str, ActorInfo]:
    """Fill in every actor's role once the whole graph is known."""
    for name, info in actors.items():
        info.role = classify(actors, name)
    return actors


def read_actors_from_source(root: Path | str) -> dict[str, ActorInfo]:
    """Read `wadsrc/static/actors/corridor7/` out of a checkout."""
    root = Path(root)
    actors: dict[str, ActorInfo] = {}
    for source in SOURCES:
        path = root / f"{source}.txt"
        if path.exists():
            actors.update(parse_decorate(path.read_text(encoding="latin-1"), source))
    return resolve_roles(actors)


def read_actors_from_pk3(path: Path | str) -> dict[str, ActorInfo]:
    """Read the same files out of a built `ec7wolf.pk3`."""
    actors: dict[str, ActorInfo] = {}
    with zipfile.ZipFile(path) as archive:
        for source in SOURCES:
            try:
                raw = archive.read(f"actors/corridor7/{source}.txt")
            except KeyError:
                continue
            actors.update(parse_decorate(raw.decode("latin-1"), source))
    return resolve_roles(actors)
