# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The editor's document model: immutable, revisioned, raw-first.

Two rules shape everything here.

**The raw words are canonical.** There is no second, semantic representation of
a map that could drift from the numbers the game reads. A door is plane-0 word
251; the catalogue turns that into the word "Door" for display, and changing
the door submits a command that declares exactly which words it writes. Nothing
is derived and then stored, because anything stored twice eventually disagrees
with itself.

**Documents are immutable.** An edit returns a new document rather than
mutating one. That is what makes undo a matter of keeping the old value, makes
a background thread's snapshot safe to hold, and makes "has this changed?" a
comparison of two integers instead of a deep walk. Corridor 7's maps are 64x64,
so a full copy is twelve thousand words -- cheap enough that the simple thing
is also the fast thing.

Identity is a UUID, assigned once and kept. Archive position is not identity:
a map that moves from slot 3 to slot 7, or gets renamed, is still the same map,
and an editor that identified maps by position would lose every annotation the
moment somebody reordered them.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from .archive import MapRecord
from .errors import Ec7EditError, Severity
from .names import NativeName
from .planes import MapPlanes

#: Bumped only for changes the on-disk schema notices. See `project.py`.
SCHEMA_VERSION = 1


def new_uuid() -> str:
    """A fresh identity. Random, so two editors never collide."""
    return str(_uuid.uuid4())


def utc_now() -> str:
    """An ISO-8601 timestamp in UTC, to the second. Stable across machines."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DocumentError(Ec7EditError):
    """A `C7E-SCHEMA-*` failure: the document does not hold together."""


def _schema_error(message: str, where: str = "") -> DocumentError:
    from .errors import Diagnostic

    return DocumentError(Diagnostic("C7E-SCHEMA-002", Severity.ERROR, message, where))


@dataclass(frozen=True)
class SourceReference:
    """Where a map came from, without depending on it.

    The path is *inert text*. Opening a project someone shared must not stat,
    hash, open, or otherwise touch a path that project names -- a shared file
    is untrusted input, and a path in it is a string, not an instruction. The
    digest is what actually identifies the content, and resolving it to a real
    file happens only through the user's own local profile or an explicit
    relink they asked for.
    """

    display_path: str = ""
    sha256: str = ""
    map_number: int = 0
    imported_at: str = ""

    @property
    def identified(self) -> bool:
        return bool(self.sha256)


@dataclass(frozen=True)
class MapDocument:
    """One map, with a stable identity and its exact raw words."""

    uuid: str
    slot: int
    native_name: NativeName
    planes: MapPlanes
    #: Editor-only. Never affects what the game reads.
    annotations: dict = field(default_factory=dict)
    source: SourceReference | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.slot <= 100:
            raise _schema_error(f"slot {self.slot} is outside MAP01..MAP100", self.uuid)

    @property
    def name(self) -> str:
        """The display name: a view over the raw field, never a second copy."""
        return self.native_name.text

    @property
    def lump_name(self) -> str:
        return f"MAP{self.slot:02d}"

    @property
    def width(self) -> int:
        return self.planes.width

    @property
    def height(self) -> int:
        return self.planes.height

    def cell(self, plane: int, x: int, y: int) -> int:
        return self.planes.at(plane, x, y)

    def with_planes(self, planes: MapPlanes) -> "MapDocument":
        return replace(self, planes=planes)

    def renamed(self, text: str) -> "MapDocument":
        """A deliberate rename replaces the whole 16-byte field.

        Not a patch of the visible part: keeping stale tail bytes under a new
        name would be the worst of both worlds, neither the imported field nor
        a clean one.
        """
        return replace(self, native_name=NativeName.from_text(text))

    def to_record(self) -> MapRecord:
        """The codec's view of this map, for export."""
        return MapRecord(
            number=self.slot,
            name=self.native_name,
            planes=self.planes,
        )

    @classmethod
    def from_record(
        cls, record: MapRecord, *, source: SourceReference | None = None
    ) -> "MapDocument":
        """Import: a fresh identity, the exact bytes, nothing invented."""
        return cls(
            uuid=new_uuid(),
            slot=record.number,
            native_name=record.name,
            planes=record.planes,
            source=source,
        )

    #: Plane-0 word for a plain solid wall, and plane-1's empty marker. The
    #: second is 18, not 0: a new map whose object plane were all zeros would
    #: place whatever word 0 means on every cell of it.
    SOLID_WALL = 1
    EMPTY_OBJECT = 18
    #: The plane-0 word for open floor. NOT zero.
    #:
    #: Corridor 7's floor words are sound areas -- Wolf3D "areas" -- and the
    #: engine propagates noise by asking map->CheckLink() whether the shooter's
    #: area connects to the listener's. CheckLink answers false the moment
    #: either side is NULL, and word 0 carries no area at all, so on a map
    #: floored with zeros nothing can ever hear anything: aliens ignore gunfire
    #: entirely and wake only on sight or contact. None of the sixty shipped
    #: maps contains a single plane-0 zero; 256 is the area they use most.
    DEFAULT_FLOOR = 256
    #: The player start facing east. Corridor 7 reflects a start's angle, so
    #: this band reads north, east, south, west -- 20 is east, not 19.
    PLAYER_START_EAST = 20

    @classmethod
    def blank(cls, *, slot: int = 1, name: str = "NEW MAP", width: int = 64,
              height: int = 64) -> "MapDocument":
        """Three planes of zeros. The primitive, with no opinions."""
        return cls(
            uuid=new_uuid(),
            slot=slot,
            native_name=NativeName.from_text(name),
            planes=MapPlanes.empty(width, height),
        )

    @classmethod
    def new_room(cls, *, slot: int = 1, name: str = "NEW MAP", width: int = 64,
                 height: int = 64, with_start: bool = True) -> "MapDocument":
        """A map somebody would actually want to start drawing on.

        Four differences from `blank`, all of which every author would make
        immediately: the boundary is solid, because an open edge lets the
        player walk out of the world; the floor is a sound area rather than
        zero, because an area of zero is no area and nothing on such a map can
        hear anything (see DEFAULT_FLOOR); the object plane holds Corridor 7's
        empty marker rather than zeros, since a plane of zeros would place
        whatever word 0 means on every cell; and there is a player start in the
        middle, because the engine refuses a map without one -- it prints "No
        player 1 start!" and exits, which looks exactly like a crash.
        """
        cells = width * height
        floor = [cls.DEFAULT_FLOOR] * cells
        for x in range(width):
            floor[x] = floor[(height - 1) * width + x] = cls.SOLID_WALL
        for y in range(height):
            floor[y * width] = floor[y * width + width - 1] = cls.SOLID_WALL

        objects = [cls.EMPTY_OBJECT] * cells
        if with_start:
            objects[(height // 2) * width + (width // 2)] = cls.PLAYER_START_EAST

        return cls(
            uuid=new_uuid(),
            slot=slot,
            native_name=NativeName.from_text(name),
            planes=MapPlanes(
                width, height,
                (tuple(floor), tuple(objects), (0,) * cells),
            ),
        )


@dataclass(frozen=True)
class ProjectDocument:
    """Everything the editor is holding, at one revision.

    `revision` counts edits and `saved_revision` records the one on disk, so
    dirty is a comparison of two integers. Both are monotonic: an edit made
    while a save is in flight leaves the document dirty afterwards, because the
    revision it saved is no longer the current one.
    """

    uuid: str
    maps: tuple[MapDocument, ...] = ()
    name: str = "Untitled"
    author: str = ""
    notes: str = ""
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION
    revision: int = 0
    saved_revision: int = 0
    #: Catalogue version the UI interpreted this project's words with. Recorded
    #: rather than acted on: a catalogue change must never rewrite raw words.
    catalog_version: int = 0
    export_defaults: dict = field(default_factory=dict)

    @property
    def dirty(self) -> bool:
        return self.revision != self.saved_revision

    def __len__(self) -> int:
        return len(self.maps)

    def map_by_uuid(self, uuid: str) -> MapDocument:
        for document in self.maps:
            if document.uuid == uuid:
                return document
        raise _schema_error(f"no map with id {uuid}", uuid)

    def index_of(self, uuid: str) -> int:
        for index, document in enumerate(self.maps):
            if document.uuid == uuid:
                return index
        raise _schema_error(f"no map with id {uuid}", uuid)

    def touched(self) -> "ProjectDocument":
        """The same document, one revision later."""
        return replace(self, revision=self.revision + 1)

    def with_map(self, document: MapDocument) -> "ProjectDocument":
        """Replace one map by identity, bumping the revision."""
        index = self.index_of(document.uuid)
        maps = list(self.maps)
        maps[index] = document
        return replace(self, maps=tuple(maps), revision=self.revision + 1)

    def with_maps(self, maps) -> "ProjectDocument":
        return replace(self, maps=tuple(maps), revision=self.revision + 1)

    def added(self, document: MapDocument) -> "ProjectDocument":
        if any(existing.uuid == document.uuid for existing in self.maps):
            raise _schema_error(f"map {document.uuid} is already in the project")
        return replace(self, maps=self.maps + (document,), revision=self.revision + 1)

    def removed(self, uuid: str) -> "ProjectDocument":
        index = self.index_of(uuid)
        maps = list(self.maps)
        del maps[index]
        return replace(self, maps=tuple(maps), revision=self.revision + 1)

    def marked_saved(self, revision: int) -> "ProjectDocument":
        """Record that `revision` reached disk.

        Only moves the marker forward, and only to a revision that actually
        happened -- a save that finishes after a further edit leaves the
        document dirty, which is the honest answer.
        """
        if revision > self.revision:
            raise _schema_error(
                f"cannot mark revision {revision} saved; the document is at {self.revision}"
            )
        return replace(self, saved_revision=max(self.saved_revision, revision))

    @classmethod
    def create(cls, name: str = "Untitled", *, author: str = "") -> "ProjectDocument":
        return cls(uuid=new_uuid(), name=name, author=author, created_at=utc_now())
