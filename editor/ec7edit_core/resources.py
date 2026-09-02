# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Resource packs: somebody else's art and actors, read and vouched for.

A map pack (`campaign.py`) carries maps and metadata and deliberately nothing
else. This is the other half: a **resource pack**, a `.pk3` holding sprites,
textures, music and the DECORATE that makes them into actors, so a campaign can
use things Corridor 7 never had.

The format is not invented here. A `.pk3` is a zip, the engine already loads one
with `--file`, and which folder a file is in decides what the engine does with
it -- `sprites/`, `textures/`, `graphics/`, `music/`, `patches/`, and anything
at the root as an ordinary lump (`resourcefile.cpp`). So a pack produced by
`docs/corridor7-monster-sprite-workflow.md`, whose layout is a root `DECORATE`
beside a `sprites/` folder, is already exactly right and needs no conversion.

What this module adds is *knowing what is in one*. The editor cannot offer a
custom monster in its palette without being told the class exists, and it
cannot refuse a pack that would break a map without looking inside first.

**A pack is untrusted input**, like a shared project: it arrives from someone
else, it is a zip, and zips lie. Every name is checked before anything is read
-- no absolute paths, no `..`, no unreasonable sizes -- and the contents are
never executed, only described.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import Diagnostic, Severity, export_error

#: What the engine does with each top-level folder, from `resourcefile.cpp`.
#: Anything else is carried but ignored -- `previews/` and `docs/` in a pack
#: from the sprite workflow, for instance, which are there for the author.
NAMESPACES = {
    "sprites/": "sprites",
    "textures/": "textures",
    "graphics/": "graphics",
    "patches/": "patches",
    "music/": "music",
    "sounds/": "sounds",
    "flats/": "flats",
}

#: Lumps at the root the engine reads by name. Case-insensitive, as the engine
#: is: a pack with `Decorate` works.
ROOT_LUMPS = {"decorate", "mapinfo", "zmapinfo", "textures", "sndinfo",
              "animdefs", "language.enu", "lockdefs"}

#: Refused outright. These are Corridor 7's own files, and a pack containing
#: one is either a mistake or a redistribution of the game.
RETAIL_NAMES = {"maptemp.co7", "maphead.co7", "gfxtiles.co7", "audiot.co7",
                "audiohed.co7", "audiomus.co7", "vgagraph.co7", "vgahead.co7",
                "vgadict.co7", "corr7cd.exe"}
RETAIL_SUFFIX = {".co7"}

#: Bounds. A pack is art, and art is not gigabytes; a zip that claims to be is
#: either broken or hostile, and either way is not opened.
MAX_TOTAL_BYTES = 512 << 20
MAX_ENTRIES = 20000
MAX_SINGLE_BYTES = 64 << 20

_ACTOR = re.compile(
    r"^\s*actor\s+(?P<name>[A-Za-z_][\w]*)\s*"
    r"(?::\s*(?P<parent>[A-Za-z_][\w]*)\s*)?"
    r"(?:replaces\s+(?P<replaces>[A-Za-z_][\w]*)\s*)?",
    re.IGNORECASE | re.MULTILINE,
)
_STATE_LABEL = re.compile(r"^\s*(?P<label>[A-Za-z_]\w*)\s*:\s*$", re.MULTILINE)
#: A frame line: four-character sprite name, then the frame letters.
_FRAME = re.compile(r"^\s*(?P<sprite>[A-Z0-9_]{4})\s+(?P<frames>[A-Z0-9\[\]\\#]+)\s",
                    re.MULTILINE)


@dataclass(frozen=True)
class ResourceActor:
    """One custom actor, as much as an editor needs to offer it."""

    name: str
    parent: str = ""
    #: The stock class this one takes the place of, if the author said so.
    #: `replaces` is a global switch: it changes every map in the game while
    #: the pack is loaded, which is a different thing from placing the actor
    #: on a map and worth saying out loud.
    replaces: str = ""
    #: The four-character sprite name its Spawn state draws, e.g. "CFLR".
    sprite: str = ""
    lump: str = ""

    @property
    def placeable(self) -> bool:
        """Whether the editor can give it a map word.

        Anything with a Spawn state can be placed. A class with none is a base
        class or an effect, and putting one on a floor produces nothing.
        """
        return bool(self.sprite)


@dataclass(frozen=True)
class Resource:
    """What a pack is and what is in it. Never the bytes themselves."""

    display_path: str
    sha256: str
    entries: int
    total_bytes: int
    actors: tuple[ResourceActor, ...] = ()
    sprites: tuple[str, ...] = ()
    textures: tuple[str, ...] = ()
    music: tuple[str, ...] = ()
    graphics: tuple[str, ...] = ()
    #: Carried into the pack but not read by the engine -- previews, notes.
    ignored: tuple[str, ...] = ()
    problems: tuple[Diagnostic, ...] = ()

    @property
    def name(self) -> str:
        return Path(self.display_path).name

    def describe(self) -> str:
        parts = []
        if self.actors:
            parts.append(f"{len(self.actors)} actor(s)")
        for count, what in ((len(self.sprites), "sprite"), (len(self.textures), "texture"),
                            (len(self.music), "music track"), (len(self.graphics), "graphic")):
            if count:
                parts.append(f"{count} {what}{'s' if count != 1 else ''}")
        return ", ".join(parts) or "nothing the engine reads"

    def to_json(self) -> dict:
        return {
            "display_path": self.display_path,
            "sha256": self.sha256,
            "entries": self.entries,
            "total_bytes": self.total_bytes,
            "actors": [
                {"name": a.name, "parent": a.parent, "replaces": a.replaces,
                 "sprite": a.sprite, "lump": a.lump}
                for a in self.actors
            ],
            "sprites": list(self.sprites),
            "textures": list(self.textures),
            "music": list(self.music),
            "graphics": list(self.graphics),
        }

    @classmethod
    def from_json(cls, raw: dict, where: str = "resource") -> "Resource":
        if not isinstance(raw, dict):
            raise export_error("C7E-RES-001", "a resource record is an object", where)
        unknown = sorted(set(raw) - {
            "display_path", "sha256", "entries", "total_bytes", "actors",
            "sprites", "textures", "music", "graphics"})
        if unknown:
            raise export_error("C7E-RES-001", f"unknown resource keys {unknown}", where)
        actors = tuple(
            ResourceActor(name=str(a.get("name", "")), parent=str(a.get("parent", "")),
                          replaces=str(a.get("replaces", "")),
                          sprite=str(a.get("sprite", "")), lump=str(a.get("lump", "")))
            for a in raw.get("actors", []) if isinstance(a, dict))
        return cls(
            display_path=str(raw.get("display_path", "")),
            sha256=str(raw.get("sha256", "")),
            entries=int(raw.get("entries", 0) or 0),
            total_bytes=int(raw.get("total_bytes", 0) or 0),
            actors=actors,
            sprites=tuple(str(s) for s in raw.get("sprites", [])),
            textures=tuple(str(s) for s in raw.get("textures", [])),
            music=tuple(str(s) for s in raw.get("music", [])),
            graphics=tuple(str(s) for s in raw.get("graphics", [])),
        )


# ---------------------------------------------------------------------------
# Reading one
# ---------------------------------------------------------------------------
#
#   C7E-RES-001  the stored record is malformed (raised)
#   C7E-RES-002  not a readable pk3
#   C7E-RES-003  a name a zip should not contain
#   C7E-RES-004  Corridor 7's own files are in it
#   C7E-RES-005  bigger than this will open
#   C7E-RES-006  nothing the engine would read
#   C7E-RES-007  something the editor cannot offer, and why


def _safe_name(name: str) -> bool:
    """Whether a zip entry names a file that can be extracted safely.

    Zip archives carry paths as text, and nothing stops one saying
    `../../.bashrc` or `/etc/passwd`. Python's `extractall` guards against this
    now, but the editor never extracts a pack at all -- it copies entries into
    a WAD -- so the check has to be here, where the names are believed.
    """
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    if ".." in Path(name).parts:
        return False
    if ":" in name:                        # a Windows drive letter
        return False
    return True


def _sprite_of(body: str) -> str:
    """The four-character sprite the Spawn state draws first.

    That is what an editor should show for an actor, for the same reason the
    engine's own catalog uses it: the map looks like this before anything
    moves. Falls back to the first frame anywhere, because a pack may name its
    states unusually and a picture from the wrong state beats no picture.
    """
    spawn = re.search(r"^\s*Spawn\s*:\s*$", body, re.IGNORECASE | re.MULTILINE)
    if spawn:
        frame = _FRAME.search(body, spawn.end())
        if frame:
            return frame.group("sprite").upper()
    frame = _FRAME.search(body)
    return frame.group("sprite").upper() if frame else ""


def read_decorate(text: str, lump: str) -> list[ResourceActor]:
    """Every actor a DECORATE lump declares.

    Deliberately a scan rather than a parser. The editor needs four things --
    the class name, what it inherits, what it replaces, and which sprite it
    shows -- and a full DECORATE parser would be a second implementation of the
    engine's, wrong in different places, maintained by nobody.
    """
    actors: list[ResourceActor] = []
    matches = list(_ACTOR.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        actors.append(ResourceActor(
            name=match.group("name"),
            parent=match.group("parent") or "",
            replaces=match.group("replaces") or "",
            sprite=_sprite_of(body),
            lump=lump,
        ))
    return actors


def _stem(name: str) -> str:
    """The lump name the engine will know an entry by: no folder, no suffix."""
    return Path(name).stem.upper()


def inspect(path: Path | str) -> Resource:
    """Open a pack, describe it, and refuse it if it should not be used."""
    path = Path(path)
    try:
        blob = path.read_bytes()
    except OSError as error:
        raise export_error("C7E-RES-002", f"could not read {path.name}: {error}",
                           str(path)) from error
    if len(blob) > MAX_TOTAL_BYTES:
        raise export_error(
            "C7E-RES-005",
            f"{path.name} is {len(blob) / 1e6:.0f} MB; the limit is "
            f"{MAX_TOTAL_BYTES / 1e6:.0f} MB", str(path))

    try:
        archive = zipfile.ZipFile(path)
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as error:
        raise export_error(
            "C7E-RES-002",
            f"{path.name} is not a pk3. A resource pack is a zip holding "
            "sprites, textures, music and DECORATE.", str(path)) from error

    if len(infos) > MAX_ENTRIES:
        raise export_error("C7E-RES-005",
                           f"{path.name} holds {len(infos)} entries; the limit is "
                           f"{MAX_ENTRIES}", str(path))

    problems: list[Diagnostic] = []
    sprites: list[str] = []
    textures: list[str] = []
    music: list[str] = []
    graphics: list[str] = []
    ignored: list[str] = []
    actors: list[ResourceActor] = []
    total = 0

    with archive:
        for info in infos:
            name = info.filename
            if name.endswith("/"):
                continue
            if not _safe_name(name):
                raise export_error(
                    "C7E-RES-003",
                    f"{path.name} contains {name!r}, which is not a name a "
                    "resource pack may use", str(path))
            lowered = name.lower()
            base = Path(lowered).name
            if base in RETAIL_NAMES or Path(base).suffix in RETAIL_SUFFIX:
                raise export_error(
                    "C7E-RES-004",
                    f"{path.name} contains {name}, which is Corridor 7's own "
                    "data. A resource pack holds only original work.", str(path))
            if info.file_size > MAX_SINGLE_BYTES:
                raise export_error(
                    "C7E-RES-005",
                    f"{name} is {info.file_size / 1e6:.0f} MB, which is more "
                    "than one entry may be", str(path))
            total += info.file_size

            folder = next((f for f in NAMESPACES if lowered.startswith(f)), "")
            if folder:
                bucket = {"sprites": sprites, "textures": textures,
                          "music": music, "graphics": graphics}.get(
                              NAMESPACES[folder])
                (bucket if bucket is not None else graphics).append(_stem(name))
                continue
            if "/" not in lowered and base in ROOT_LUMPS:
                if base in ("decorate",):
                    try:
                        text = archive.read(name).decode("latin-1")
                    except (OSError, zipfile.BadZipFile) as error:
                        problems.append(Diagnostic(
                            "C7E-RES-002", Severity.WARNING,
                            f"{name} could not be read: {error}", name))
                        continue
                    actors.extend(read_decorate(text, _stem(name)))
                continue
            ignored.append(name)

    if not (actors or sprites or textures or music or graphics):
        raise export_error(
            "C7E-RES-006",
            f"{path.name} holds nothing the engine reads. A resource pack puts "
            "art in sprites/, textures/, graphics/ or music/, and actors in a "
            "DECORATE file beside them.", str(path))

    for actor in actors:
        if not actor.placeable:
            problems.append(Diagnostic(
                "C7E-RES-007", Severity.INFORMATION,
                f"{actor.name} has no Spawn frames, so it cannot be placed on a "
                "map. That is normal for a base class.", actor.name))
        elif actor.sprite not in {s[:4] for s in sprites}:
            problems.append(Diagnostic(
                "C7E-RES-007", Severity.WARNING,
                f"{actor.name} draws sprite {actor.sprite}, and this pack has no "
                f"{actor.sprite} sprites. It will show as a missing texture.",
                actor.name))
        if actor.replaces:
            problems.append(Diagnostic(
                "C7E-RES-007", Severity.INFORMATION,
                f"{actor.name} replaces {actor.replaces} everywhere while this "
                "pack is loaded, not only on your maps.", actor.name))

    return Resource(
        display_path=str(path),
        sha256=hashlib.sha256(blob).hexdigest(),
        entries=len(infos),
        total_bytes=total,
        actors=tuple(actors),
        sprites=tuple(sorted(set(sprites))),
        textures=tuple(sorted(set(textures))),
        music=tuple(sorted(set(music))),
        graphics=tuple(sorted(set(graphics))),
        ignored=tuple(sorted(ignored)),
        problems=tuple(problems),
    )


__all__ = [
    "MAX_ENTRIES", "MAX_SINGLE_BYTES", "MAX_TOTAL_BYTES", "NAMESPACES",
    "Resource", "ResourceActor", "ROOT_LUMPS", "inspect", "read_decorate",
]
