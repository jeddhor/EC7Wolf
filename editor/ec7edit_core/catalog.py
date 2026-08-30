# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The semantic catalogue: raw map words to things a person can recognise.

A map cell is a number. `23` is a filing cabinet, `108` is an alien facing
east, `251` is a door, and `1` is a wall painted with page 0. The catalogue is
what lets a palette show those as pictures with names instead of as a list of
integers, and what lets the editor write the right number back.

It is *generated*, not written by hand, from three inputs that already exist:

* [`xlat.py`](xlat.py) reads the engine's translation -- which value spawns
  which class, which values are a facing, which are ignored;
* [`decorate.py`](decorate.py) reads the actor definitions -- what each class
  inherits from and which sprite page it shows;
* a small curated file supplies the things neither can know: that `C7Rodex` is
  called a Rodex, that it travels in packs, and what to search for to find it.

Generating it matters because all three inputs are living files. A translator
entry fixed during a bug hunt should change the editor's palette, not leave it
quietly describing a game that no longer exists.

Two rules hold the honesty line:

* **an unresolved join is reported, never guessed.** If XLAT spawns a class
  DECORATE does not define, that is a defect somewhere and the catalogue says
  so rather than inventing a plausible entry;
* **only entries with a complete raw write mapping are offered in the normal
  palette.** Everything else is reachable through Raw, where the user can see
  exactly what they are placing.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .decorate import ActorInfo
from .xlat import Xlat, XlatThing

#: Bump when the entry shape changes in a way a stored project could notice.
CATALOG_SCHEMA = 1

#: Palette tabs, in the order section 8.6 lists them.
CATEGORIES = ("walls", "specials", "objects", "enemies", "starts", "zones", "raw")

#: Plane-0 wall values map to GFXTILES pages one lower: wall 1 is page 0.
WALL_PAGE_OFFSET = 1

#: Plane-1 statics index the executable's 83-row table starting at word 23.
STATIC_WORD_BASE = 23


@dataclass(frozen=True)
class CatalogEntry:
    """One selectable thing, with everything needed to draw and place it."""

    key: str
    category: str
    subcategory: str
    rank: int
    name: str
    plane: int
    value: int
    values: tuple[int, ...]

    description: str = ""
    aliases: tuple[str, ...] = ()

    actor: str = ""
    sprite: int | None = None
    texture: str = ""

    #: Facing name to the exact raw value that produces it.
    directions: tuple[tuple[str, int], ...] = ()
    #: "stand" / "patrol", and the difficulty band, where the value encodes one.
    variant: str = ""
    minskill: int = 0

    placement: str = "floor"  # floor | wall | any
    blocking: bool | None = None
    #: False for values only ever seen in imported maps, or needing Advanced.
    safe_for_new_maps: bool = True

    evidence: str = ""
    grade: str = "A"
    test_vector: str = ""

    @property
    def resolved(self) -> bool:
        """Whether this entry knows exactly what to write."""
        return bool(self.values)

    def matches(self, query: str) -> bool:
        """Search by friendly name, raw value, class, texture or alias."""
        needle = query.strip().lower()
        if not needle:
            return True
        if needle.isdigit() and int(needle) in self.values:
            return True
        haystack = [self.name, self.actor, self.texture, self.key, self.subcategory]
        haystack.extend(self.aliases)
        return any(needle in item.lower() for item in haystack if item)


@dataclass
class Catalog:
    """Every entry, plus what could not be resolved while building it."""

    entries: tuple[CatalogEntry, ...] = ()
    unresolved: tuple[str, ...] = ()
    schema: int = CATALOG_SCHEMA

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def by_key(self, key: str) -> CatalogEntry | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def for_value(self, plane: int, value: int) -> CatalogEntry | None:
        """The entry that owns a raw value on a plane, if any does."""
        for entry in self.entries:
            if entry.plane == plane and value in entry.values:
                return entry
        return None

    def in_category(self, category: str) -> list[CatalogEntry]:
        return sorted(
            (e for e in self.entries if e.category == category),
            key=lambda e: (e.rank, e.name),
        )

    def search(self, query: str, *, category: str = "") -> list[CatalogEntry]:
        pool = self.in_category(category) if category else list(self.entries)
        return [entry for entry in pool if entry.matches(query)]


# ---------------------------------------------------------------------------
# Curated identity
# ---------------------------------------------------------------------------


@dataclass
class Curation:
    """The names, aliases and notes that no generated input can supply."""

    actors: dict[str, dict] = field(default_factory=dict)
    values: dict[str, dict] = field(default_factory=dict)  # "plane:value" -> fields
    walls: dict[str, dict] = field(default_factory=dict)  # str(value) -> fields

    @classmethod
    def load(cls, path: Path | str) -> "Curation":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            actors=data.get("actors", {}),
            values=data.get("values", {}),
            walls=data.get("walls", {}),
        )

    def for_actor(self, name: str) -> dict:
        return self.actors.get(name, {})

    def for_value(self, plane: int, value: int) -> dict:
        return self.values.get(f"{plane}:{value}", {})

    def for_wall(self, value: int) -> dict:
        return self.walls.get(str(value), {})


def _pretty(classname: str) -> str:
    """`C7OrganicEye` to `Organic Eye`, for an actor with no curated name."""
    stem = classname[2:] if classname.startswith("C7") else classname
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    return spaced.replace("_", " ").strip() or classname


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def _wall_entries(xlat: Xlat, curation: Curation) -> list[CatalogEntry]:
    """Ordinary paint only.

    A plane-0 value can be two things at once: value 9 both paints wall page 8
    and is the access terminal, and every door is a tile with a texture as well
    as a trigger. Those belong in Doors & Specials, not in the wall palette --
    painting a corridor with "wall 9" would scatter working terminals down it.
    """
    entries = []
    for value, tile in sorted(xlat.tiles.items()):
        if value in xlat.tile_triggers:
            continue
        custom = curation.for_wall(value)
        page = value - WALL_PAGE_OFFSET
        entries.append(
            CatalogEntry(
                key=f"wall.{value:03d}",
                category="walls",
                subcategory=custom.get("subcategory", "material"),
                rank=value,
                name=custom.get("name", f"Wall {value:03d}"),
                description=custom.get("description", ""),
                aliases=tuple(custom.get("aliases", [])) + (tile.texture,),
                plane=0,
                value=value,
                values=(value,),
                texture=tile.texture,
                sprite=None,
                placement="wall",
                blocking=True,
                evidence=f"xlat/corridor7.txt tile {value}",
                test_vector=f"wall-{value:03d}",
            )
        )
    return entries


_SPECIAL_SUBCATEGORY = {
    "Door_Open": "door",
    "Exit_Normal": "exit",
    "Teleport_Relative": "transporter",
    "C7_WallSwitch": "switch",
    "C7_Dispenser": "dispenser",
    "Elevator_SwitchFloor": "elevator",
    "Pushwall_Move": "moving wall",
    "Wall_AnimateRemove": "mutable wall",
}


def _trigger_entries(xlat: Xlat, curation: Curation) -> list[CatalogEntry]:
    entries = []
    sources = [(0, xlat.tile_triggers), (1, xlat.thing_triggers)]
    for plane, triggers in sources:
        for value, trigger in sorted(triggers.items()):
            custom = curation.for_value(plane, value)
            subcategory = custom.get(
                "subcategory", _SPECIAL_SUBCATEGORY.get(trigger.action, "special")
            )
            # Section 8.6 puts transporters with the zones, not with the doors.
            category = "zones" if trigger.action == "Teleport_Relative" else "specials"
            entries.append(
                CatalogEntry(
                    key=f"special.{plane}.{value:03d}",
                    category=category,
                    subcategory=subcategory,
                    rank=value,
                    name=custom.get("name", f"{_pretty(trigger.action)} {value}"),
                    description=custom.get("description", ""),
                    aliases=tuple(custom.get("aliases", []))
                    + (trigger.action,)
                    + ((xlat.tiles[value].texture,) if value in xlat.tiles else ()),
                    plane=plane,
                    value=value,
                    values=(value,),
                    texture=xlat.tiles[value].texture if value in xlat.tiles else "",
                    # Corridor 7's plane-1 triggers all configure the wall cell
                    # they sit in -- a pushwall slides a wall, a disintegrating
                    # wall opens one. Calling them floor placements made the
                    # validator report five errors on every shipped map, which
                    # is how this was found.
                    placement="wall",
                    blocking=None,
                    evidence=f"xlat/corridor7.txt {trigger.section} trigger {value}",
                    test_vector=f"special-{plane}-{value:03d}",
                )
            )
    return entries


def _zone_entries(xlat: Xlat, curation: Curation) -> list[CatalogEntry]:
    entries = []
    for value, zone in sorted(xlat.zones.items()):
        if value in xlat.tile_triggers:
            # 279..286 are declared as zones *and* as teleport triggers -- that
            # is how the engine models a transporter pad. The trigger is the
            # useful thing to place, so it owns the value; see `_trigger_entries`.
            continue
        custom = curation.for_value(0, value)
        modifiers = " ".join(zone.modifiers)
        entries.append(
            CatalogEntry(
                key=f"zone.{value:03d}",
                category="zones",
                subcategory="ambush" if "ambush" in zone.modifiers else "area",
                rank=value,
                name=custom.get("name", f"Area {value}" + (f" ({modifiers})" if modifiers else "")),
                description=custom.get("description", ""),
                aliases=tuple(custom.get("aliases", [])) + (("zone", "sound area")),
                plane=0,
                value=value,
                values=(value,),
                placement="floor",
                blocking=False,
                evidence=f"xlat/corridor7.txt zone {value}",
                test_vector=f"zone-{value:03d}",
            )
        )
    return entries


def _ignored_entries(xlat: Xlat, curation: Curation) -> list[CatalogEntry]:
    """Values the translation deliberately ignores, as Raw entries.

    The shipped maps are full of these -- plane-1 words 86 to 88 configure a
    masked wall in the DOS engine rather than spawning anything, and 99 and
    103 to 105 hit nothing in the executable's object switch at all. They spawn
    nothing, so they are not palette items, but they are *in the data*, and an
    editor that had no entry for them would show an imported map as having
    cells it could not name and could not put back.

    So they exist, in Raw, marked as imported-only: visible, preserved,
    explained, and not offered for new work.
    """
    entries = []
    for plane, section in ((0, "tiles"), (1, "things")):
        for value in sorted(xlat.ignored.get(section, ())):
            custom = curation.for_value(plane, value)
            entries.append(
                CatalogEntry(
                    key=f"raw.{plane}.{value:03d}",
                    category="raw",
                    subcategory=custom.get("subcategory", "ignored"),
                    rank=value,
                    name=custom.get("name", f"Raw value {value}"),
                    description=custom.get(
                        "description",
                        "The translation ignores this value: it spawns nothing. It is "
                        "preserved exactly where an imported map uses it.",
                    ),
                    aliases=tuple(custom.get("aliases", [])) + ("raw", "ignored"),
                    plane=plane,
                    value=value,
                    values=(value,),
                    placement="any",
                    safe_for_new_maps=False,
                    evidence=f"xlat/corridor7.txt {section} ignore {value}",
                    grade="B",
                    test_vector=f"raw-{plane}-{value:03d}",
                )
            )
    return entries


def _category_for_role(role: str) -> str:
    return {
        "enemy": "enemies",
        "player": "starts",
        "item": "objects",
        "decoration": "objects",
        "effect": "objects",
    }.get(role, "objects")


def _thing_entry(
    thing: XlatThing,
    actor: ActorInfo | None,
    curation: Curation,
    *,
    extra_values: tuple[int, ...] = (),
    has_patrol_variant: bool = False,
) -> CatalogEntry:
    custom = curation.for_actor(thing.classname)
    role = actor.role if actor else ""
    values = tuple(thing.values) + extra_values

    if thing.classname == "PatrolPoint":
        category, subcategory = "starts", "patrol"
    elif thing.classname.endswith("Start") or role == "player":
        category, subcategory = "starts", "player"
    else:
        category = _category_for_role(role)
        subcategory = custom.get("subcategory", role or "unknown")

    # "Standing" only means something where the same class also has a
    # patrolling band. A player start and a patrol marker have a facing but no
    # opposite, and calling them "stand" would put a distinction in the key
    # that does not exist in the game.
    variant = "patrol" if thing.pathing else ("stand" if has_patrol_variant else "")
    suffix = []
    if variant:
        suffix.append(variant)
    if thing.minskill:
        suffix.append(f"skill{thing.minskill}")
    key = ".".join(["thing", thing.classname.lower(), *suffix]) if suffix else \
        f"thing.{thing.classname.lower()}"

    name = custom.get("name") or _pretty(thing.classname)
    if thing.pathing:
        name = f"{name} (patrolling)"
    if thing.minskill > 1:
        name = f"{name} — skill {thing.minskill}+"

    directions = tuple(
        (thing.direction_for(value), value)
        for value in thing.values
        if thing.direction_for(value)
    )

    static_index = thing.value - STATIC_WORD_BASE
    description = custom.get("description", "")
    if not description and actor and actor.note:
        description = actor.note

    return CatalogEntry(
        key=key,
        category=category,
        subcategory=subcategory,
        rank=thing.value,
        name=name,
        description=description,
        aliases=tuple(custom.get("aliases", []))
        + ((f"static {static_index:03d}",) if 0 <= static_index < 83 else ()),
        plane=1,
        value=thing.value,
        values=values,
        actor=thing.classname,
        sprite=actor.spawn_sprite if actor else None,
        directions=directions,
        variant=variant,
        minskill=thing.minskill,
        placement="floor",
        blocking=actor.blocking if actor else None,
        evidence=f"xlat/corridor7.txt things {thing.value}"
        + (f"; actor {thing.classname}" if actor else ""),
        grade="A" if actor else "C",
        test_vector=f"thing-{thing.value:03d}",
    )


def build_catalog(
    xlat: Xlat, actors: dict[str, ActorInfo], curation: Curation | None = None
) -> Catalog:
    """Join the three inputs into one catalogue, reporting what will not join."""
    curation = curation or Curation()
    unresolved: list[str] = []

    entries: list[CatalogEntry] = []
    entries.extend(_wall_entries(xlat, curation))
    entries.extend(_trigger_entries(xlat, curation))
    entries.extend(_zone_entries(xlat, curation))
    entries.extend(_ignored_entries(xlat, curation))

    # Two raw values can spawn exactly the same thing -- 142 and 143 are both
    # a skill-1 Eniram, 232 and 233 both a Mechanoid. That is one item in a
    # palette, not two identical ones, so entries are merged and the lowest
    # value is what gets written. An imported map using either still resolves,
    # because lookup is by membership.
    patrolling = {thing.classname for thing in xlat.things if thing.pathing}
    merged: dict[tuple, list[XlatThing]] = {}
    for thing in xlat.things:
        merged.setdefault(
            (thing.classname, thing.angles, thing.flags, thing.minskill), []
        ).append(thing)

    for group in merged.values():
        group.sort(key=lambda t: t.value)
        primary = group[0]
        actor = actors.get(primary.classname)
        if actor is None and primary.classname not in ("PatrolPoint", "Player1Start"):
            unresolved.append(
                f"xlat things {primary.value} spawns {primary.classname}, "
                "which no Corridor 7 DECORATE file defines"
            )
        extra = tuple(v for other in group[1:] for v in other.values)
        entries.append(
            _thing_entry(
                primary,
                actor,
                curation,
                extra_values=extra,
                has_patrol_variant=primary.classname in patrolling,
            )
        )

    # An actor that exists but nothing can place is worth knowing about: it is
    # either dead weight in the pk3 or a translator entry somebody forgot.
    placeable = {thing.classname for thing in xlat.things}
    bases = {actor.parent for actor in actors.values() if actor.parent}
    for name, actor in sorted(actors.items()):
        if name in bases:
            continue  # something inherits from it; it is a base, not an item
        # A class with no spawn sprite is bookkeeping -- an ammo type, a
        # capacity, an inheritance base -- and was never meant to be placed.
        if actor.spawn_sprite is None or name in placeable:
            continue
        # Nor is a starting weapon missing: the player is handed it, and no
        # map word puts one down. Reporting the Taser as an unplaced item was
        # a statement about this check, not about the game.
        if actor.granted:
            continue
        if actor.role in ("enemy", "item"):
            unresolved.append(f"actor {name} ({actor.role}) has no xlat entry that places it")

    entries.sort(key=lambda e: (CATEGORIES.index(e.category), e.rank, e.key))
    return Catalog(tuple(entries), tuple(unresolved))


# ---------------------------------------------------------------------------
# Serialisation: metadata only, never pixels
# ---------------------------------------------------------------------------


def catalog_to_json(catalog: Catalog) -> str:
    """Deterministic JSON. Sorted keys, fixed separators, trailing newline.

    No image data of any kind: the catalogue says *which* sprite page to draw,
    and the pixels are decoded from the user's own copy at runtime. That is the
    difference between a distributable file and one that is not.
    """
    payload = {
        "schema": catalog.schema,
        "entries": [
            {key: value for key, value in asdict(entry).items() if value not in ((), "", None)}
            for entry in catalog.entries
        ],
        "unresolved": list(catalog.unresolved),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def catalog_from_json(text: str) -> Catalog:
    data = json.loads(text)
    entries = []
    for raw in data["entries"]:
        raw = dict(raw)
        raw["aliases"] = tuple(raw.get("aliases", ()))
        raw["values"] = tuple(raw.get("values", ()))
        raw["directions"] = tuple(tuple(pair) for pair in raw.get("directions", ()))
        entries.append(CatalogEntry(**raw))
    return Catalog(tuple(entries), tuple(data.get("unresolved", ())), data.get("schema", 0))


def load_catalog(path: Path | str) -> Catalog:
    return catalog_from_json(Path(path).read_text(encoding="utf-8"))
