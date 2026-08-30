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
from .errors import DiagnosticLog, Ec7EditError, Severity
from .paths import OutputGuard, SourceIdentity, atomic_write, digest_bytes
from .planes import PLANE_COUNT
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
