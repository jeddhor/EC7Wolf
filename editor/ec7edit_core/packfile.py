# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Building the one file an author hands somebody.

`campaign.build_pack` writes a WAD: markers, PLANES and metadata, which is all a
pack needed before there was custom content. A pack carrying sprites and
DECORATE cannot be a WAD -- a WAD has flat eight-character lump names and no
folders, and the engine decides what a resource IS from the folder it is in. So
a pack with resources is a `.pk3`.

The layout is the engine's, not an invention, and one part of it is easy to get
wrong: **maps go in `maps/MAPxx.wad`, not at the root.** Archive entries are
sorted alphabetically when a zip is read (`PostProcessArchive`), so a root
`MAP61` is followed by `MAPINFO` rather than `PLANES`, and the load fails with
"Invalid map format for MAP61". `gamemap.cpp` looks for `maps/<map>.wad` first
and opens it as an embedded resource file, which is the supported route and the
one this builds.

    maps/MAP61.wad        one two-lump WAD per floor
    MAPINFO               the campaign, generated
    xlat/ec7edit.txt      the placement translator, generated
    DECORATE              #includes, one per resource that has actors
    decorate/<slug>.txt   each resource's own DECORATE, kept apart so two
                          packs cannot collide over one root lump name
    sprites/ textures/    the resources' art, copied through untouched
    music/ graphics/
    PACKINFO              the manifest

Everything from a resource is copied byte for byte. The editor does not decode
somebody's PNG and write it back out: it has no reason to, and a re-encode is a
chance to change art the author approved.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import custom
from .campaign import (
    Campaign, MANIFEST_LUMP, PackAudit, generate_manifest, generate_mapinfo,
    validate as validate_campaign,
)
from .errors import Diagnostic, Severity, export_error
from .resources import NAMESPACES, Resource
from .wad import build_preview_wad

#: Folders whose contents are copied into the pack. Anything else in a resource
#: -- previews, notes, the author's working files -- is left out: it is not
#: something the engine reads, and a pack is a download.
CARRIED = tuple(NAMESPACES)

#: Where each resource's DECORATE goes, and the root lump that includes them.
DECORATE_DIR = "decorate"
DECORATE_LUMP = "DECORATE"


def _slug(name: str) -> str:
    """A file name from a pack's name, safe in a zip and stable across runs."""
    stem = Path(name).stem.lower()
    kept = "".join(c if c.isalnum() or c in "-_" else "-" for c in stem)
    return kept.strip("-") or "resource"


@dataclass(frozen=True)
class ResourcePack:
    """A built pk3, and what went into it."""

    pk3: bytes
    manifest: str
    mapinfo: str
    translator: str
    audit: PackAudit
    problems: tuple[Diagnostic, ...] = ()


def audit_pk3(data: bytes) -> PackAudit:
    """Account for every entry in a built pack, by reading it.

    The same contract as `campaign.audit_pack`, for the other format: what is
    interesting is not what the builder meant to write but what is in the file
    somebody is about to be handed.
    """
    import io

    markers: list[str] = []
    names: list[str] = []
    unexpected: list[str] = []
    metadata = 0
    map_bytes = 0

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            names.append(name)
            lowered = name.lower()
            if lowered.startswith("maps/") and lowered.endswith(".wad"):
                markers.append(Path(name).stem.upper())
                map_bytes += info.file_size
            elif name in (MANIFEST_LUMP, "MAPINFO", DECORATE_LUMP):
                metadata += info.file_size
            elif lowered.startswith((f"{DECORATE_DIR}/", "xlat/")):
                metadata += info.file_size
            elif any(lowered.startswith(folder) for folder in CARRIED):
                map_bytes += info.file_size
            else:
                unexpected.append(name)

    return PackAudit(markers=tuple(markers), lump_names=tuple(names),
                     metadata_bytes=metadata, map_bytes=map_bytes,
                     unexpected=tuple(unexpected))


def build_resource_pack(campaign: Campaign, documents, resources,
                        allocations=(), *, project_name: str = "",
                        author: str = "", allow_warnings: bool = True,
                        resource_files=None) -> ResourcePack:
    """Build the pk3: the campaign, the maps, and the resources behind them.

    `resource_files` maps a resource's digest to the file it was read from --
    the project stores an inert path and this is where a caller says which
    file it actually resolved to, so a shared project can never make the editor
    open something on its own.
    """
    problems = list(validate_campaign(campaign, documents))
    blocking = [p for p in problems if p.severity >= Severity.ERROR]
    if blocking:
        raise export_error(blocking[0].code,
                           f"{blocking[0].message} ({len(blocking)} problem(s) "
                           "block this pack)", blocking[0].where)
    if not allow_warnings:
        warnings = [p for p in problems if p.severity == Severity.WARNING]
        if warnings:
            raise export_error(warnings[0].code,
                               f"{warnings[0].message} ({len(warnings)} warning(s), "
                               "and warnings were asked to block)", warnings[0].where)

    by_slot = {document.slot: document for document in documents}
    allocations = list(allocations)
    translator = custom.generate_translator(allocations) if allocations else ""
    mapinfo = generate_mapinfo(
        campaign, translator=custom.TRANSLATOR_LUMP if translator else "")
    manifest = generate_manifest(campaign, documents, project_name=project_name,
                                 author=author)

    resource_files = dict(resource_files or {})
    buffer = _Zip()
    for entry in campaign.entries:
        buffer.write(f"maps/{entry.lump_name}.wad",
                     build_preview_wad([(entry.lump_name,
                                         by_slot[entry.slot].to_record())]))
    buffer.write("MAPINFO", mapinfo.encode("ascii"))
    if translator:
        buffer.write(custom.TRANSLATOR_LUMP, translator.encode("ascii"))

    includes: list[str] = []
    for resource in resources:
        source = resource_files.get(resource.sha256)
        if source is None:
            problems.append(Diagnostic(
                "C7E-RES-008", Severity.ERROR,
                f"{resource.name} is attached but its file was not found, so "
                "its art cannot go in the pack", resource.display_path))
            continue
        slug = _slug(resource.name)
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                name = info.filename
                if name.endswith("/"):
                    continue
                lowered = name.lower()
                if any(lowered.startswith(folder) for folder in CARRIED):
                    buffer.write(name, archive.read(name))
                elif "/" not in lowered and Path(lowered).name == "decorate":
                    target = f"{DECORATE_DIR}/{slug}.txt"
                    buffer.write(target, archive.read(name))
                    includes.append(target)

    if includes:
        # One root DECORATE that includes the rest. Two packs cannot both own
        # the root lump name, and the engine's own decorate.txt does exactly
        # this, so it is the shape the parser is built for.
        text = ("// Generated by EC7Edit: one line per resource pack.\n"
                + "".join(f'#include "{path}"\n' for path in sorted(includes)))
        buffer.write(DECORATE_LUMP, text.encode("ascii"))

    buffer.write(MANIFEST_LUMP, manifest.encode("ascii"))
    data = buffer.finish()
    return ResourcePack(pk3=data, manifest=manifest, mapinfo=mapinfo,
                        translator=translator, audit=audit_pk3(data),
                        problems=tuple(problems))


class _Zip:
    """A deterministic zip: fixed timestamps, sorted, so a pack has one digest."""

    #: The zip epoch. A build's mtime in the archive would make two identical
    #: packs differ, which breaks the one thing a digest is for.
    STAMP = (1980, 1, 1, 0, 0, 0)

    def __init__(self) -> None:
        self._entries: dict[str, bytes] = {}

    def write(self, name: str, data: bytes) -> None:
        if name in self._entries:
            raise export_error("C7E-RES-009",
                               f"two things want to be {name} in the pack", name)
        self._entries[name] = data

    def finish(self) -> bytes:
        import io

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(self._entries):
                info = zipfile.ZipInfo(name, date_time=self.STAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, self._entries[name])
        return buffer.getvalue()


__all__ = ["CARRIED", "DECORATE_DIR", "DECORATE_LUMP", "ResourcePack",
           "audit_pk3", "build_resource_pack"]
