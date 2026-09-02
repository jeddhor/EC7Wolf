# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Project files: schema, deterministic serialisation, and a save that survives.

The format is JSON because a project is something a person may want to read, a
reviewer may want to diff, and a support conversation may want to paste. Plane
words are JSON integers, not base64: forty thousand small numbers costs a few
hundred kilobytes and buys the ability to see what changed.

Two ideas run through the whole file.

**A shared project is untrusted input.** Someone else's `.ec7project` is data,
not instructions. It may name a path; that path is inert text and opening the
project must not stat, hash, open or contact it. External content resolves only
through the user's own local profile or a relink they deliberately asked for.
Unknown properties are rejected rather than kept and later interpreted.

**A save either happens or does not.** The protocol in `save_project` is longer
than "write the file" because every step of the short version has a failure
mode that loses work: a half-written file, a file that parsed but lost a plane,
a save that overwrote someone else's newer one, a rename that landed before the
bytes did. Each numbered step below answers one of those, and each has a fault
injection point so the answer can be tested rather than asserted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .document import (
    SCHEMA_VERSION,
    DocumentError,
    MapDocument,
    ProjectDocument,
    SourceReference,
    new_uuid,
    utc_now,
)
from .errors import Diagnostic, Severity, export_error
from .names import NAME_FIELD_BYTES, NativeName
from .planes import MapPlanes

PROJECT_SUFFIX = ".ec7project"
RECOVERY_SUFFIX = ".ec7recovery"

#: The oldest schema this build can still open. Raise it only by dropping a
#: migration, which is a decision, not a cleanup.
OLDEST_SUPPORTED_SCHEMA = 1

_PROJECT_KEYS = {"schema_version", "project", "maps", "export_defaults",
                 "campaign", "resources", "allocations"}
_META_KEYS = {"uuid", "name", "author", "notes", "created_at", "catalog_version"}
_MAP_KEYS = {
    "uuid", "slot", "native_name", "native_name_raw_hex", "width", "height",
    "planes", "annotations", "source",
}
_SOURCE_KEYS = {"display_path", "sha256", "map_number", "imported_at"}


def _schema_error(message: str, where: str = "") -> DocumentError:
    return DocumentError(Diagnostic("C7E-SCHEMA-002", Severity.ERROR, message, where))


def _unsupported(message: str) -> DocumentError:
    return DocumentError(Diagnostic("C7E-SCHEMA-001", Severity.ERROR, message))


def _reject_unknown(present, allowed, where: str) -> None:
    """Unknown keys are refused, not ignored.

    Ignoring them is how a field added by a later version, or by somebody
    else's tool, ends up silently dropped on the next save -- and how a
    hostile file gets somewhere to hide.
    """
    unknown = sorted(set(present) - allowed)
    if unknown:
        raise _schema_error(f"unknown propert{'y' if len(unknown) == 1 else 'ies'}: "
                            f"{', '.join(unknown)}", where)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialize(project: ProjectDocument) -> str:
    """Deterministic JSON: sorted keys, fixed indent, trailing newline.

    Two saves of the same document give the same bytes, which is what lets the
    save protocol compare a digest and what makes a project diffable.
    """
    payload = {
        "schema_version": project.schema_version,
        "project": {
            "uuid": project.uuid,
            "name": project.name,
            "author": project.author,
            "notes": project.notes,
            "created_at": project.created_at,
            "catalog_version": project.catalog_version,
        },
        "export_defaults": project.export_defaults,
        "campaign": project.campaign,
        "resources": [dict(r) for r in project.resources],
        "allocations": project.allocations,
        "maps": [
            {
                "uuid": document.uuid,
                "slot": document.slot,
                "native_name": document.name,
                "native_name_raw_hex": document.native_name.raw.hex(),
                "width": document.width,
                "height": document.height,
                "planes": [
                    [list(row) for row in document.planes.rows(plane)] for plane in range(3)
                ],
                "annotations": document.annotations,
                "source": {
                    "display_path": document.source.display_path,
                    "sha256": document.source.sha256,
                    "map_number": document.source.map_number,
                    "imported_at": document.source.imported_at,
                }
                if document.source
                else None,
            }
            for document in project.maps
        ],
    }
    return json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _load_map(raw: dict, where: str) -> MapDocument:
    _reject_unknown(raw, _MAP_KEYS, where)
    for required in ("uuid", "slot", "native_name_raw_hex", "width", "height", "planes"):
        if required not in raw:
            raise _schema_error(f"map is missing '{required}'", where)

    try:
        raw_name = bytes.fromhex(raw["native_name_raw_hex"])
    except ValueError as error:
        raise _schema_error(f"native_name_raw_hex is not hexadecimal: {error}", where) from error
    if len(raw_name) != NAME_FIELD_BYTES:
        raise _schema_error(
            f"native_name_raw_hex decodes to {len(raw_name)} bytes, needs {NAME_FIELD_BYTES}",
            where,
        )
    name = NativeName(raw_name, imported=True)
    # The text is a *view* over the raw field. A file where they disagree was
    # either hand-edited or written by something with a different idea of the
    # decode, and guessing which one to believe is how the tail bytes get lost.
    if raw.get("native_name", name.text) != name.text:
        raise _schema_error(
            f"native_name {raw.get('native_name')!r} does not match the raw field, "
            f"which decodes to {name.text!r}",
            where,
        )

    width, height = raw["width"], raw["height"]
    planes = raw["planes"]
    if not isinstance(planes, list) or len(planes) != 3:
        raise _schema_error(f"expected 3 planes, got {len(planes) if isinstance(planes, list) else type(planes).__name__}", where)

    flattened = []
    for number, plane in enumerate(planes):
        if not isinstance(plane, list) or len(plane) != height:
            raise _schema_error(
                f"plane {number} has {len(plane) if isinstance(plane, list) else '?'} rows, "
                f"height is {height}",
                where,
            )
        words: list[int] = []
        for y, row in enumerate(plane):
            if not isinstance(row, list) or len(row) != width:
                raise _schema_error(
                    f"plane {number} row {y} has {len(row) if isinstance(row, list) else '?'} "
                    f"cells, width is {width}",
                    where,
                )
            for value in row:
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFF:
                    raise DocumentError(
                        Diagnostic("C7E-CELL-001", Severity.ERROR,
                                   f"plane {number} row {y} holds {value!r}, "
                                   "which is not a word in 0..65535", where)
                    )
            words.extend(row)
        flattened.append(tuple(words))

    source = raw.get("source")
    if source is not None:
        _reject_unknown(source, _SOURCE_KEYS, where)
        source = SourceReference(
            display_path=source.get("display_path", ""),
            sha256=source.get("sha256", ""),
            map_number=source.get("map_number", 0),
            imported_at=source.get("imported_at", ""),
        )

    annotations = raw.get("annotations") or {}
    if not isinstance(annotations, dict):
        raise _schema_error("annotations must be an object", where)

    return MapDocument(
        uuid=raw["uuid"],
        slot=raw["slot"],
        native_name=name,
        planes=MapPlanes(width, height, tuple(flattened)),
        annotations=annotations,
        source=source,
    )


def deserialize(text: str) -> ProjectDocument:
    """Parse a project file, validating everything before believing any of it."""
    if text.startswith("﻿"):
        raise _schema_error("the file begins with a byte-order mark; UTF-8 without one")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise _schema_error(f"not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise _schema_error("a project file is a JSON object")

    version = payload.get("schema_version")
    if not isinstance(version, int):
        raise _schema_error("schema_version is missing or not an integer")
    if version > SCHEMA_VERSION:
        raise _unsupported(
            f"this project is schema {version}; this build understands up to "
            f"{SCHEMA_VERSION}. Open it with a newer EC7Edit, or export through "
            "a compatible version."
        )
    if version < OLDEST_SUPPORTED_SCHEMA:
        raise _unsupported(
            f"schema {version} is older than the oldest supported ({OLDEST_SUPPORTED_SCHEMA})"
        )
    payload = migrate(payload)

    _reject_unknown(payload, _PROJECT_KEYS, "project")
    meta = payload.get("project")
    if not isinstance(meta, dict):
        raise _schema_error("the 'project' object is missing")
    _reject_unknown(meta, _META_KEYS, "project")
    if not meta.get("uuid"):
        raise _schema_error("the project has no uuid")

    raw_maps = payload.get("maps", [])
    if not isinstance(raw_maps, list):
        raise _schema_error("'maps' must be a list")

    maps = []
    seen = set()
    for index, raw in enumerate(raw_maps):
        if not isinstance(raw, dict):
            raise _schema_error(f"map {index} is not an object")
        document = _load_map(raw, f"map {index}")
        if document.uuid in seen:
            raise _schema_error(f"two maps share the id {document.uuid}")
        seen.add(document.uuid)
        maps.append(document)

    export_defaults = payload.get("export_defaults") or {}
    if not isinstance(export_defaults, dict):
        raise _schema_error("export_defaults must be an object")

    # Structure only, here. Whether the campaign makes sense is
    # `campaign.validate`'s question and is asked when a pack is built, not
    # when a file is opened -- a project is allowed to be saved mid-thought.
    raw_campaign = payload.get("campaign") or {}
    if not isinstance(raw_campaign, dict):
        raise _schema_error("campaign must be an object")

    raw_resources = payload.get("resources") or []
    if not isinstance(raw_resources, list) or not all(
            isinstance(r, dict) for r in raw_resources):
        raise _schema_error("resources must be a list of objects")
    raw_allocations = payload.get("allocations") or {}
    if not isinstance(raw_allocations, dict):
        raise _schema_error("allocations must be an object")

    revision = len(maps)
    return ProjectDocument(
        uuid=meta["uuid"],
        maps=tuple(maps),
        name=meta.get("name", "Untitled"),
        author=meta.get("author", ""),
        notes=meta.get("notes", ""),
        created_at=meta.get("created_at", ""),
        schema_version=SCHEMA_VERSION,
        revision=revision,
        saved_revision=revision,
        catalog_version=meta.get("catalog_version", 0),
        export_defaults=export_defaults,
        campaign=raw_campaign,
        resources=tuple(raw_resources),
        allocations=raw_allocations,
    )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _add_campaign(payload: dict) -> dict:
    """1 -> 2: projects gained a map-pack campaign.

    An absent campaign and an empty one mean the same thing -- this project
    does not build a pack -- so the migration is an insertion with no decision
    in it. Every schema-1 project keeps exporting exactly the preview WAD it
    did before, because that path never consults this block.
    """
    return {**payload, "campaign": {}}


def _add_resources(payload: dict) -> dict:
    """2 -> 3: projects gained attached resource packs and their allocations.

    Both empty, and both meaning the same as absent -- this project uses only
    Corridor 7's own content. Every schema-2 project exports exactly what it
    did before, because neither path consults these.
    """
    return {**payload, "resources": [], "allocations": {}}


#: `version -> pure function from payload to the next version's payload`.
MIGRATIONS: dict[int, callable] = {1: _add_campaign, 2: _add_resources}


def migrate(payload: dict) -> dict:
    """Bring a payload up to the current schema, one pure step at a time."""
    version = payload["schema_version"]
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise _unsupported(f"no migration from schema {version} to {version + 1}")
        payload = step(payload)
        payload["schema_version"] = version + 1
        version += 1
    return payload


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


class SaveConflict(Exception):
    """The destination changed, or a newer save already committed."""


@dataclass
class FaultInjector:
    """Raise at a named stage, so every stage's failure can be tested.

    Testing durability by unplugging a machine does not scale; testing it by
    asserting the code looks careful proves nothing. This is the middle: each
    stage has a name, a test asks for a failure at that name, and the assertion
    is that the destination afterward is a valid old, new, or recovery state.
    """

    stage: str = ""
    error: type[BaseException] = OSError

    def check(self, stage: str) -> None:
        if stage and stage == self.stage:
            raise self.error(f"injected failure at stage {stage!r}")


#: Every point `save_project` can fail, in order.
SAVE_STAGES = (
    "serialize", "validate", "tempfile", "write", "flush", "reopen",
    "verify", "identity", "generation", "replace", "dirsync",
)


class WriterQueue:
    """One writer per destination, with monotonic generations.

    Autosave and an explicit save can be in flight at once, and the failure to
    avoid is the slow older one landing after the newer. Every request takes a
    generation; a request whose generation is behind what already committed is
    abandoned rather than allowed to win by finishing late.
    """

    def __init__(self) -> None:
        self._next: dict[Path, int] = {}
        self._committed: dict[Path, int] = {}

    def begin(self, destination: Path) -> int:
        destination = destination.resolve()
        generation = self._next.get(destination, 0) + 1
        self._next[destination] = generation
        return generation

    def superseded(self, destination: Path, generation: int) -> bool:
        return generation < self._committed.get(destination.resolve(), 0)

    def commit(self, destination: Path, generation: int) -> None:
        destination = destination.resolve()
        self._committed[destination] = max(self._committed.get(destination, 0), generation)

    def committed_generation(self, destination: Path) -> int:
        return self._committed.get(destination.resolve(), 0)


_DEFAULT_QUEUE = WriterQueue()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identity(path: Path) -> tuple:
    """What the destination looked like, for the just-before-replace check."""
    try:
        status = path.stat()
        return (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns)
    except FileNotFoundError:
        return ()


def save_project(
    project: ProjectDocument,
    path: Path | str,
    *,
    queue: WriterQueue | None = None,
    generation: int | None = None,
    faults: FaultInjector | None = None,
    expect_identity: tuple | None = None,
) -> int:
    """Write a project atomically. Returns the revision that reached disk.

    The steps, and what each one is for:

    1. take a generation, so a slower older save cannot land after a newer one;
    2. serialise an immutable snapshot -- later edits cannot change what is
       being written half way through;
    3. validate by parsing what we are about to write, in memory;
    4. write to a sibling temporary file with restrictive permissions;
    5. flush and fsync, so the bytes are on the disk before the rename;
    6. reopen and parse the temporary file from disk;
    7. confirm it round-trips to the same digest -- this is what catches a
       serialiser that lost a plane, which a length check would not;
    8. compare the destination's identity with what we expected, so a save does
       not silently overwrite an edit made by something else;
    9. confirm no newer generation committed while we were working;
    10. replace atomically;
    11. fsync the directory, so the rename itself survives a power cut.
    """
    queue = queue or _DEFAULT_QUEUE
    faults = faults or FaultInjector()
    destination = Path(path).expanduser().resolve()
    # A caller that took its generation earlier -- a background autosave that
    # has been serialising while the user carried on working -- passes it in,
    # so it can be refused if a newer save committed meanwhile. Taking one here
    # would make it the newest by definition and the check meaningless.
    if generation is None:
        generation = queue.begin(destination)
    revision = project.revision

    faults.check("serialize")
    text = serialize(project)

    faults.check("validate")
    reloaded = deserialize(text)
    if len(reloaded.maps) != len(project.maps):
        raise export_error(
            "C7E-EXPORT-002",
            f"serialising lost maps: {len(project.maps)} in, {len(reloaded.maps)} out",
            str(destination),
        )
    expected = _digest(text)

    destination.parent.mkdir(parents=True, exist_ok=True)
    faults.check("tempfile")
    handle, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".part"
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        faults.check("write")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            faults.check("flush")
            os.fsync(stream.fileno())

        faults.check("reopen")
        written = temporary.read_text(encoding="utf-8")
        faults.check("verify")
        if _digest(written) != expected:
            raise export_error(
                "C7E-EXPORT-002", "the file on disk differs from what was written",
                str(temporary),
            )
        # Parsing it back is the check that matters: equal bytes only proves
        # the write worked, not that the document survived serialisation.
        if len(deserialize(written).maps) != len(project.maps):
            raise export_error(
                "C7E-EXPORT-002", "the reloaded project does not match the document",
                str(temporary),
            )

        faults.check("identity")
        if expect_identity is not None and _identity(destination) != expect_identity:
            raise SaveConflict(
                f"{destination} changed since it was opened; save elsewhere or reload"
            )

        faults.check("generation")
        if queue.superseded(destination, generation):
            raise SaveConflict(
                f"a newer save of {destination} already committed; this one is abandoned"
            )

        faults.check("replace")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    queue.commit(destination, generation)
    faults.check("dirsync")
    _sync_directory(destination.parent)
    return revision


def _sync_directory(directory: Path) -> None:
    """Make the rename itself durable. Not every platform can."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # Windows and some filesystems cannot fsync a directory.
    finally:
        os.close(fd)


def load_project(path: Path | str) -> ProjectDocument:
    return deserialize(Path(path).read_text(encoding="utf-8"))


def project_identity(path: Path | str) -> tuple:
    """The identity to pass back as `expect_identity` on the next save."""
    return _identity(Path(path).expanduser().resolve())


# ---------------------------------------------------------------------------
# Autosave and recovery
# ---------------------------------------------------------------------------


@dataclass
class RecoveryRecord:
    """What a recovery file knows about the work it is holding."""

    project_uuid: str
    original_path: str
    saved_revision: int
    autosaved_revision: int
    timestamp: str
    digest: str

    def to_json(self) -> dict:
        return {
            "project_uuid": self.project_uuid,
            "original_path": self.original_path,
            "saved_revision": self.saved_revision,
            "autosaved_revision": self.autosaved_revision,
            "timestamp": self.timestamp,
            "digest": self.digest,
        }


@dataclass
class RecoveryStore:
    """Autosaves, in the application's own directory and nowhere else.

    Never beside the retail data, and never beside the project unless the user
    picked a workspace: an editor that scatters files into a game directory is
    one bug away from writing over something it must not touch.
    """

    root: Path
    queue: WriterQueue = field(default_factory=WriterQueue)
    max_projects: int = 20
    max_bytes: int = 64 << 20

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()

    def path_for(self, project: ProjectDocument) -> Path:
        return self.root / f"{project.uuid}{RECOVERY_SUFFIX}"

    def autosave(self, project: ProjectDocument, original_path: str = "") -> Path:
        """Write a recovery copy. Does not clear the document's dirty flag.

        Autosave is a safety net, not a save: telling the user their work is
        saved because a background timer wrote a copy into an application
        directory they have never seen would be a lie.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        text = serialize(project)
        record = RecoveryRecord(
            project_uuid=project.uuid,
            original_path=original_path,
            saved_revision=project.saved_revision,
            autosaved_revision=project.revision,
            timestamp=utc_now(),
            digest=_digest(text),
        )
        payload = json.dumps(
            {"recovery": record.to_json(), "project": json.loads(text)},
            indent=1, sort_keys=True, ensure_ascii=False,
        ) + "\n"

        target = self.path_for(project)
        generation = self.queue.begin(target)
        if self.queue.superseded(target, generation):
            raise SaveConflict("a newer autosave already committed")
        handle, temporary_name = tempfile.mkstemp(dir=self.root, prefix=".autosave.", suffix=".part")
        temporary = Path(temporary_name)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self.queue.commit(target, generation)
        self.prune()
        return target

    def list_recoveries(self) -> list[RecoveryRecord]:
        records = []
        for path in sorted(self.root.glob(f"*{RECOVERY_SUFFIX}")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records.append(RecoveryRecord(**payload["recovery"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # a damaged recovery file is not a reason to fail startup
        return records

    def load(self, project_uuid: str) -> ProjectDocument:
        path = self.root / f"{project_uuid}{RECOVERY_SUFFIX}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return deserialize(json.dumps(payload["project"]))

    def discard(self, project_uuid: str) -> None:
        """Delete one recovery. Only ever an exact path this store owns."""
        target = self.root / f"{project_uuid}{RECOVERY_SUFFIX}"
        if target.parent == self.root and target.suffix == RECOVERY_SUFFIX:
            target.unlink(missing_ok=True)

    def prune(self) -> None:
        """Keep the store inside its count and byte budgets, oldest first."""
        files = sorted(
            self.root.glob(f"*{RECOVERY_SUFFIX}"), key=lambda p: p.stat().st_mtime
        )
        total = sum(path.stat().st_size for path in files)
        while files and (len(files) > self.max_projects or total > self.max_bytes):
            victim = files.pop(0)
            total -= victim.stat().st_size
            victim.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Cooperative locking
# ---------------------------------------------------------------------------


class ProjectLock:
    """A cooperative lock so a second instance opens read-only.

    Advisory, and honest about it: it coordinates EC7Edit instances, and does
    not pretend to stop a different program, or a malicious one, from writing
    the same file. A stale lock from a crashed process is detected by its
    pid no longer existing.
    """

    def __init__(self, path: Path | str) -> None:
        self.target = Path(path).expanduser().resolve()
        self.lock_path = self.target.with_suffix(self.target.suffix + ".lock")
        self.held = False

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self._stale():
                self.lock_path.unlink(missing_ok=True)
                return self.acquire()
            return False
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "acquired_at": utc_now()}, stream)
        self.held = True
        return True

    def _stale(self) -> bool:
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
            pid = int(payload["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return True  # unreadable lock helps nobody
        # Not "is this pid ours": within one process a second lock on the same
        # project is exactly the case this exists to refuse, and treating our
        # own pid as stale would let an editor take a lock it already holds.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False  # it exists and belongs to someone else
        return False

    def release(self) -> None:
        if self.held:
            self.lock_path.unlink(missing_ok=True)
            self.held = False

    def __enter__(self) -> "ProjectLock":
        if not self.acquire():
            raise SaveConflict(
                f"{self.target} is open in another EC7Edit; open it read-only or Save As"
            )
        return self

    def __exit__(self, kind, value, traceback) -> bool:
        self.release()
        return False


def new_project(name: str = "Untitled", *, author: str = "") -> ProjectDocument:
    project = ProjectDocument.create(name, author=author)
    return project


__all__ = [
    "FaultInjector", "MIGRATIONS", "OLDEST_SUPPORTED_SCHEMA", "PROJECT_SUFFIX",
    "ProjectLock", "RECOVERY_SUFFIX", "RecoveryRecord", "RecoveryStore",
    "SAVE_STAGES", "SaveConflict", "WriterQueue", "deserialize", "load_project",
    "migrate", "new_project", "new_uuid", "project_identity", "save_project",
    "serialize",
]
