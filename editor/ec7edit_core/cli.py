# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""`ec7edit` -- the headless half of the editor, usable before the GUI exists.

Three verbs in E1:

* `inspect`  -- what is in this archive;
* `validate` -- would the engine load it, and what is noncanonical about it;
* `convert-to-preview-wad` -- write a WAD that overrides one map at run time.

Every verb is read-only with respect to its input. The one that writes takes
the source's directory as a protected root automatically, so the common
accident -- exporting next to the retail data and clobbering it -- is refused
rather than trusted not to happen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .archive import Archive, MAX_MAPS, read_archive
from .document import MapDocument, ProjectDocument, SourceReference, utc_now
from .errors import DiagnosticLog, Ec7EditError, Severity
from .paths import OutputGuard, SourceIdentity, atomic_write, digest_bytes, digest_file
from .planes import PLANE_COUNT
from .project import PROJECT_SUFFIX, load_project, new_project, save_project, serialize
from .campaign import Campaign, audit_pack, build_pack
from .errors import Severity
from .resources import Resource
from .campaign import validate as campaign_validate
from .wad import build_preview_wad, read_preview_wad

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _describe(archive: Archive) -> dict:
    return {
        "format": "Corridor 7 self-contained TED5",
        "map_count": len(archive),
        "terminated": archive.terminated,
        "maps": [
            {
                "number": record.number,
                "lump": record.lump_name,
                "name": record.name.text,
                "name_raw": record.name.raw.hex(),
                "name_canonical": record.name.is_canonical,
                "width": record.width,
                "height": record.height,
                "header_offset": record.source.header_offset if record.source else None,
                "plane_offsets": list(record.source.plane_offsets) if record.source else None,
                "plane_lengths": list(record.source.plane_lengths) if record.source else None,
                "plane_distinct_values": [
                    len(set(plane)) for plane in record.planes.planes
                ],
            }
            for record in archive
        ],
        "diagnostics": [
            {
                "code": entry.code,
                "severity": entry.severity.name.lower(),
                "message": entry.message,
                "where": entry.where,
            }
            for entry in archive.diagnostics
        ],
    }


def _report(archive: Archive, stream) -> None:
    for entry in archive.diagnostics:
        print(f"  {entry}", file=stream)


def _resolve_selection(archive: Archive, numbers, want_all: bool) -> list:
    """Selected records, or None if the selection names a map that isn't there.

    Asking for map 99 of 60 is a usage mistake, not a malformed archive, so it
    does not get a `C7E-NATIVE` code -- those mean the file is wrong.
    """
    if want_all:
        return list(archive.records)
    available = {r.number for r in archive.records}
    missing = sorted(set(numbers) - available)
    if missing:
        print(
            f"no map {', '.join(str(n) for n in missing)} in this archive; "
            f"it holds 1..{len(archive)}",
            file=sys.stderr,
        )
        return None
    return [archive.by_number(number) for number in numbers]


def command_inspect(args) -> int:
    archive = read_archive(args.archive)
    if args.json:
        json.dump(_describe(archive), sys.stdout, indent=2)
        print()
        return EXIT_OK

    print(f"{args.archive}: {len(archive)} maps, TED5 self-contained")
    for record in archive:
        flag = "" if record.name.is_canonical else "  (noncanonical name)"
        print(
            f"  {record.lump_name}  {record.width:3d}x{record.height:<3d}  "
            f"{record.name.text:<16}{flag}"
        )
    if not archive.terminated:
        print("  no final !ID! terminator")
    _report(archive, sys.stdout)
    return EXIT_OK


def command_validate(args) -> int:
    log = DiagnosticLog()
    archive = read_archive(args.archive, log=log)
    worst = log.worst()
    print(f"{args.archive}: {len(archive)} maps parsed, {len(log)} diagnostic(s)")
    _report(archive, sys.stdout)

    if worst is not None and worst >= Severity.ERROR:
        return EXIT_ERROR
    if args.strict and len(log):
        print("strict: noncanonical input rejected")
        return EXIT_ERROR
    return EXIT_OK


def command_preview(args) -> int:
    source = Path(args.archive)
    identity = SourceIdentity.probe(source)
    archive = read_archive(source)
    _report(archive, sys.stdout)

    records = _resolve_selection(archive, args.map, args.all)
    if records is None:
        return EXIT_USAGE
    if not records:
        print("nothing selected: pass --map N (repeatable) or --all", file=sys.stderr)
        return EXIT_USAGE
    if args.slot and len(records) != 1:
        print("--slot retargets a single map; pass exactly one --map", file=sys.stderr)
        return EXIT_USAGE

    pairs = [(args.slot or record.lump_name, record) for record in records]
    blob = build_preview_wad(pairs)

    # Read it back through the independent reader before it is written, so a
    # writer bug is caught here rather than by the engine at playtest time.
    reread = read_preview_wad(blob)
    if len(reread) != len(pairs):
        print(f"internal error: wrote {len(pairs)} maps, read back {len(reread)}", file=sys.stderr)
        return EXIT_ERROR
    for (marker, original), (read_marker, read_record) in zip(pairs, reread):
        if marker != read_marker or read_record.planes.planes != original.planes.planes:
            print(f"internal error: {marker} did not survive readback", file=sys.stderr)
            return EXIT_ERROR

    guard = OutputGuard.for_source(source, extra_roots=args.protect)
    written = atomic_write(args.output, blob, guard=guard)
    identity.verify_unchanged()

    print(
        f"{written}: {len(pairs)} map(s), {len(blob)} bytes, "
        f"sha256 {digest_bytes(blob)[:16]}"
    )
    for marker, record in pairs:
        print(f"  {marker}  <- map {record.number} {record.name.text!r} "
              f"{record.width}x{record.height} x{PLANE_COUNT} planes")
    print(f"  source {identity.resolved} unchanged ({identity.digest[:16]})")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def command_project_new(args) -> int:
    project = new_project(args.name, author=args.author)
    save_project(project, args.output)
    print(f"{args.output}: new project {project.name!r} ({project.uuid})")
    return EXIT_OK


def command_project_inspect(args) -> int:
    project = load_project(args.project)
    if args.json:
        json.dump(
            {
                "uuid": project.uuid,
                "name": project.name,
                "author": project.author,
                "schema_version": project.schema_version,
                "maps": [
                    {
                        "uuid": document.uuid,
                        "slot": document.slot,
                        "lump": document.lump_name,
                        "name": document.name,
                        "width": document.width,
                        "height": document.height,
                        "source_sha256": document.source.sha256 if document.source else "",
                    }
                    for document in project.maps
                ],
            },
            sys.stdout,
            indent=2,
        )
        print()
        return EXIT_OK

    print(f"{args.project}: {project.name!r} by {project.author or 'nobody'}, "
          f"{len(project)} map(s), schema {project.schema_version}")
    for document in project.maps:
        origin = ""
        if document.source and document.source.sha256:
            origin = f"  from map {document.source.map_number} of " \
                     f"{document.source.sha256[:12]}"
        print(f"  {document.lump_name}  {document.width:3d}x{document.height:<3d}  "
              f"{document.name:<16}{origin}")
    return EXIT_OK


def command_project_import(args) -> int:
    """Copy a map out of a native archive into a project. The archive is read only."""
    source = Path(args.archive)
    identity = SourceIdentity.probe(source)
    archive = read_archive(source)

    project = load_project(args.project) if args.project.exists() else new_project(args.name)
    reference = SourceReference(
        display_path=str(source),
        sha256=identity.digest,
        map_number=args.map,
        imported_at=utc_now(),
    )
    record = archive.by_number(args.map)
    document = MapDocument.from_record(record, source=reference)
    if args.slot:
        from dataclasses import replace

        document = replace(document, slot=args.slot)

    project = project.added(document)
    guard = OutputGuard.for_source(source, extra_roots=args.protect)
    guard.check(args.project)
    save_project(project, args.project)
    identity.verify_unchanged()

    print(f"{args.project}: imported map {args.map} {record.name.text!r} "
          f"as {document.lump_name} ({len(project)} map(s))")
    print(f"  source {identity.resolved} unchanged ({identity.digest[:16]})")
    return EXIT_OK


def command_project_export(args) -> int:
    """Export a project's maps as a preview WAD the engine can load."""
    project = load_project(args.project)
    if not project.maps:
        print("the project has no maps to export", file=sys.stderr)
        return EXIT_USAGE

    chosen = project.maps
    if args.map_uuid:
        chosen = tuple(d for d in project.maps if d.uuid in args.map_uuid)
        missing = set(args.map_uuid) - {d.uuid for d in chosen}
        if missing:
            print(f"no map with id {', '.join(sorted(missing))}", file=sys.stderr)
            return EXIT_USAGE

    pairs = [(document.lump_name, document.to_record()) for document in chosen]
    blob = build_preview_wad(pairs)
    reread = read_preview_wad(blob)
    if len(reread) != len(pairs):
        print("internal error: the export did not survive readback", file=sys.stderr)
        return EXIT_ERROR

    guard = OutputGuard(protected_roots=tuple(args.protect))
    written = atomic_write(args.output, blob, guard=guard)
    print(f"{written}: {len(pairs)} map(s), {len(blob)} bytes, "
          f"sha256 {digest_bytes(blob)[:16]}")
    for marker, record in pairs:
        print(f"  {marker}  {record.name.text!r} {record.planes.width}x{record.planes.height}")
    return EXIT_OK


def command_project_pack(args) -> int:
    """Build a distributable map pack: maps, generated MAPINFO, and a manifest."""
    project = load_project(args.project)
    campaign = Campaign.from_json(project.campaign or None)

    if not campaign.entries:
        print("this project has no campaign; add one before building a pack",
              file=sys.stderr)
        return EXIT_USAGE

    problems = campaign_validate(campaign, project.maps)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)

    if project.resources:
        return _pack_with_resources(args, project, campaign)

    pack = build_pack(campaign, project.maps, project_name=project.name,
                      author=project.author, allow_warnings=not args.strict)

    if not pack.audit.clean:
        # Never write a file whose contents could not be accounted for. The
        # audit exists to be believed, which means acting on it.
        print("internal error: the built pack holds lumps this tool did not "
              f"expect: {', '.join(pack.audit.unexpected)}", file=sys.stderr)
        return EXIT_ERROR

    guard = OutputGuard(protected_roots=tuple(args.protect))
    written = atomic_write(args.output, pack.wad, guard=guard)
    print(f"{written}: {pack.audit.describe()}, sha256 {digest_bytes(pack.wad)[:16]}")

    manifest_path = args.manifest or Path(str(args.output) + ".txt")
    written_manifest = atomic_write(manifest_path, pack.manifest.encode("ascii"), guard=guard)
    print(f"{written_manifest}: manifest, {len(pack.manifest)} characters")

    for entry in campaign.entries:
        route = "end of campaign" if entry.next.ends else f"MAP{entry.next.slot:02d}"
        secret = ""
        if entry.secret is not None:
            secret = ("  secret -> end of campaign" if entry.secret.ends
                      else f"  secret -> MAP{entry.secret.slot:02d}")
        print(f"  {entry.lump_name}  {entry.name!r} -> {route}{secret}")
    return EXIT_OK


def command_resource_add(args) -> int:
    """Attach a resource pack to a project, and allocate its map words."""
    from .custom import allocate, load as load_allocations, store
    from .resources import inspect as inspect_resource

    project = load_project(args.project)
    resource = inspect_resource(args.resource)

    attached = [Resource.from_json(r) for r in project.resources]
    if any(r.sha256 == resource.sha256 for r in attached):
        print(f"{resource.name} is already attached ({resource.sha256[:16]})")
        return EXIT_OK
    attached.append(resource)

    allocations, problems = allocate(load_allocations(project.allocations),
                                    attached, project.maps)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if any(p.severity >= Severity.ERROR for p in problems):
        return EXIT_ERROR

    project = project.with_resources([r.to_json() for r in attached],
                                     store(allocations))
    save_project(project, args.project)

    print(f"{args.project}: attached {resource.name} -- {resource.describe()}")
    for allocation in allocations:
        if allocation.resource == resource.sha256:
            plane = "object" if allocation.plane == 1 else "wall"
            print(f"  {plane} word {allocation.word}  {allocation.name}")
    for problem in resource.problems:
        print(f"  {problem}")
    return EXIT_OK


def command_resource_inspect(args) -> int:
    """Say what is in a resource pack, without attaching it to anything."""
    from .resources import inspect as inspect_resource

    resource = inspect_resource(args.resource)
    print(f"{resource.name}: {resource.describe()}")
    print(f"  sha256 {resource.sha256[:16]}, {resource.total_bytes / 1e3:.0f} kB "
          f"in {resource.entries} entries")
    for actor in resource.actors:
        line = f"  actor {actor.name}"
        if actor.parent:
            line += f" : {actor.parent}"
        if actor.replaces:
            line += f" (replaces {actor.replaces})"
        line += f"  sprite {actor.sprite or '-'}"
        if not actor.placeable:
            line += "  [not placeable]"
        print(line)
    for label, names in (("sprites", resource.sprites), ("textures", resource.textures),
                         ("music", resource.music), ("graphics", resource.graphics)):
        if names:
            shown = ", ".join(names[:6]) + ("..." if len(names) > 6 else "")
            print(f"  {label}: {shown}")
    if resource.ignored:
        print(f"  carried by the author, not read by the engine: "
              f"{len(resource.ignored)} file(s)")
    for problem in resource.problems:
        print(f"  {problem}")
    return EXIT_OK


def _pack_with_resources(args, project, campaign) -> int:
    """The pk3 route: a pack that carries somebody's art cannot be a WAD.

    A WAD has flat eight-character lump names and no folders, and the engine
    decides what a resource IS from the folder it is in.
    """
    from .custom import load as load_allocations
    from .packfile import build_resource_pack

    attached = [Resource.from_json(r) for r in project.resources]
    files = {}
    for resource in attached:
        candidate = Path(resource.display_path)
        # The stored path is inert text until a digest says it is the right
        # file. A shared project naming /home/someone/pack.pk3 must not make
        # this open whatever happens to be there.
        if candidate.is_file() and digest_bytes(candidate.read_bytes()) == resource.sha256:
            files[resource.sha256] = candidate
        else:
            print(f"  {resource.name}: not found at {resource.display_path}, "
                  "or the file there is a different one", file=sys.stderr)

    pack = build_resource_pack(
        campaign, project.maps, attached, load_allocations(project.allocations),
        project_name=project.name, author=project.author,
        allow_warnings=not args.strict, resource_files=files)

    for problem in pack.problems:
        if problem.severity >= Severity.ERROR:
            print(f"  {problem}", file=sys.stderr)
    if any(p.severity >= Severity.ERROR for p in pack.problems):
        return EXIT_ERROR
    if not pack.audit.clean:
        print("internal error: the built pack holds entries this tool did not "
              f"expect: {', '.join(pack.audit.unexpected)}", file=sys.stderr)
        return EXIT_ERROR

    output = args.output
    if output.suffix.lower() != ".pk3":
        output = output.with_suffix(".pk3")
    guard = OutputGuard(protected_roots=tuple(args.protect))
    written = atomic_write(output, pack.pk3, guard=guard)
    print(f"{written}: {pack.audit.describe()}, sha256 "
          f"{digest_bytes(pack.pk3)[:16]}")

    manifest_path = args.manifest or Path(str(output) + ".txt")
    atomic_write(manifest_path, pack.manifest.encode("ascii"), guard=guard)
    print(f"{manifest_path}: manifest, {len(pack.manifest)} characters")
    for entry in campaign.entries:
        route = "end of campaign" if entry.next.ends else f"MAP{entry.next.slot:02d}"
        print(f"  {entry.lump_name}  {entry.name!r} -> {route}")
    return EXIT_OK


def command_video_encode(args) -> int:
    """Turn a video, or a folder of frames, into a cinematic the game plays."""
    from . import video

    def note(message: str) -> None:
        print(f"  {message}")

    result = video.encode(args.source, fps=args.fps, colors=args.colors,
                          progress=note)
    guard = OutputGuard(protected_roots=tuple(args.protect))
    output = args.output
    if output.suffix.upper() != ".CO7":
        output = output.with_suffix(".CO7")
    written = atomic_write(output, result.data, guard=guard)
    print(f"{written}: {result.describe()}, sha256 "
          f"{digest_bytes(result.data)[:16]}")
    print(f"  put it in a resource pack as video/{output.stem.upper()}.CO7, and "
          "name it in your campaign's ending")
    return EXIT_OK


def command_pack_audit(args) -> int:
    """Account for every lump in a pack, including one this tool did not write."""
    blob = args.pack.read_bytes()
    report = audit_pack(blob)
    print(f"{args.pack}: {report.describe()}")
    for name in report.lump_names:
        print(f"  {name}")
    if not report.clean:
        for name in report.unexpected:
            print(f"  unexpected: {name}", file=sys.stderr)
        return EXIT_ERROR
    print("  only markers, PLANES and metadata: no game content")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ec7edit",
        description="Corridor 7 native map tools (EC7Edit core).",
    )
    parser.add_argument("--version", action="version", version=f"EC7Edit {__version__}")
    verbs = parser.add_subparsers(dest="verb", required=True)

    inspect = verbs.add_parser("inspect", help="list the maps in a native archive")
    inspect.add_argument("archive", type=Path)
    inspect.add_argument("--json", action="store_true", help="machine-readable output")
    inspect.set_defaults(handler=command_inspect)

    validate = verbs.add_parser("validate", help="check an archive against the engine's rules")
    validate.add_argument("archive", type=Path)
    validate.add_argument(
        "--strict", action="store_true", help="fail on warnings and noncanonical input too"
    )
    validate.set_defaults(handler=command_validate)

    preview = verbs.add_parser(
        "convert-to-preview-wad", help="export maps as a WAD the engine can load with --file"
    )
    preview.add_argument("archive", type=Path)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument(
        "--map", type=int, action="append", default=[], metavar="N",
        help=f"1..{MAX_MAPS}; repeat for several maps",
    )
    preview.add_argument("--all", action="store_true", help="export every map in the archive")
    preview.add_argument(
        "--slot", metavar="MAPxx", help="write a single selected map into a different slot"
    )
    preview.add_argument(
        "--protect", type=Path, action="append", default=[], metavar="DIR",
        help="additional directory the output must not land in; repeatable",
    )
    preview.set_defaults(handler=command_preview)

    project_new = verbs.add_parser("project-new", help="create an empty project")
    project_new.add_argument("--output", type=Path, required=True)
    project_new.add_argument("--name", default="Untitled")
    project_new.add_argument("--author", default="")
    project_new.set_defaults(handler=command_project_new)

    project_inspect = verbs.add_parser("project-inspect", help="list a project's maps")
    project_inspect.add_argument("project", type=Path)
    project_inspect.add_argument("--json", action="store_true")
    project_inspect.set_defaults(handler=command_project_inspect)

    project_import = verbs.add_parser(
        "project-import", help="copy a map from a native archive into a project"
    )
    project_import.add_argument("archive", type=Path)
    project_import.add_argument("--project", type=Path, required=True)
    project_import.add_argument("--map", type=int, required=True, metavar="N")
    project_import.add_argument("--slot", type=int, metavar="N",
                                help="target MAPxx slot; defaults to the source's")
    project_import.add_argument("--name", default="Imported",
                                help="project name, when creating a new one")
    project_import.add_argument("--protect", type=Path, action="append", default=[])
    project_import.set_defaults(handler=command_project_import)

    project_export = verbs.add_parser(
        "project-export", help="export a project's maps as a preview WAD"
    )
    project_export.add_argument("project", type=Path)
    project_export.add_argument("--output", type=Path, required=True)
    project_export.add_argument("--map-uuid", action="append", default=[], metavar="ID")
    project_export.add_argument("--protect", type=Path, action="append", default=[])
    project_export.set_defaults(handler=command_project_export)

    project_pack = verbs.add_parser(
        "project-pack", help="build a distributable map pack with generated MAPINFO"
    )
    project_pack.add_argument("project", type=Path)
    project_pack.add_argument("--output", type=Path, required=True)
    project_pack.add_argument("--manifest", type=Path, default=None,
                              help="where to write the manifest (default: OUTPUT.txt)")
    project_pack.add_argument("--strict", action="store_true",
                              help="treat campaign warnings as reasons not to build")
    project_pack.add_argument("--protect", type=Path, action="append", default=[])
    project_pack.set_defaults(handler=command_project_pack)

    resource_add = verbs.add_parser(
        "resource-add", help="attach a resource pack and allocate its map words"
    )
    resource_add.add_argument("project", type=Path)
    resource_add.add_argument("resource", type=Path)
    resource_add.set_defaults(handler=command_resource_add)

    resource_inspect = verbs.add_parser(
        "resource-inspect", help="say what is inside a resource pack"
    )
    resource_inspect.add_argument("resource", type=Path)
    resource_inspect.set_defaults(handler=command_resource_inspect)

    video_encode = verbs.add_parser(
        "video-encode",
        help="convert a video or a folder of PNG frames into a cinematic"
    )
    video_encode.add_argument("source", type=Path,
                              help="a video file, or a folder of PNG frames")
    video_encode.add_argument("--output", type=Path, required=True)
    video_encode.add_argument("--fps", type=int, default=14,
                              help="frames a second (default 14, as the game's own)")
    video_encode.add_argument("--colors", type=int, default=256,
                              help="palette size, 2..256")
    video_encode.add_argument("--protect", type=Path, action="append", default=[])
    video_encode.set_defaults(handler=command_video_encode)

    pack_audit = verbs.add_parser(
        "pack-audit", help="list what a map pack contains and flag anything else"
    )
    pack_audit.add_argument("pack", type=Path)
    pack_audit.set_defaults(handler=command_pack_audit)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except Ec7EditError as error:
        print(f"error: {error.diagnostic}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
