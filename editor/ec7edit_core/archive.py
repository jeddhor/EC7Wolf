# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The self-contained TED5 archive Corridor 7 ships as `MAPTEMP.CO7`.

Unlike Wolfenstein's split `MAPHEAD`/`GAMEMAPS` pair, this one file carries
both the headers and the plane streams, and each header is followed
immediately by its own three streams rather than all headers preceding all
data. The first record is 46 bytes and begins with the signature; every later
record is 42 bytes and begins with `!ID!`; a bare `!ID!` ends the archive.

The first record's plane-0 offset is **implicit**. It is not stored anywhere:
the stream simply begins at byte 46, and the engine hardcodes that
(`headers[0].PlaneOffset[0] = sizeof(first)`). Only planes 1 and 2 have stored
offsets in that record, which is why it is 46 bytes rather than 50.

Record layouts, little-endian::

    first (46)                       later (42)
    00  char[12] "TED5v1.0.\\0\\0\\0"   00  char[4]  "!ID!"
    (plane 0 offset is implicit 46)  04  u32[3]   plane offsets
    12  u32[2]   plane 1, 2 offsets  16  u16[3]   plane lengths
    20  u16[3]   plane lengths       22  u16      width
    26  u16      width               24  u16      height
    28  u16      height              26  char[16] name
    30  char[16] name

Every byte of both layouts is accounted for; the only field this editor cannot
fully explain is the tail of the name, which `names.py` preserves verbatim.

Validation is deliberately the engine's, not a tidier superset of it. Where
`FGamemaps::Open` accepts something the canonical writer would never emit, so
does this parser -- with a diagnostic. Refusing to open a map the game itself
loads would be a worse failure than any amount of noncanonical input.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from .errors import DiagnosticLog, native_error
from .names import NAME_FIELD_BYTES, NativeName
from .planes import MapPlanes, PLANE_COUNT, validate_dimensions
from .rlew import decode_plane, encode_plane

TED5_SIGNATURE = b"TED5v1.0.\x00\x00\x00"
MAP_MARKER = b"!ID!"

FIRST_RECORD_BYTES = 46
LATER_RECORD_BYTES = 42

#: `Ted5MapHeader headers[MAX_TED5_MAPS]` in the engine is a fixed array, so
#: this is a hard bound and not a policy choice.
MAX_MAPS = 100

_U32_MAX = 0xFFFFFFFF


@dataclass(frozen=True)
class RecordSource:
    """Where a record's bytes were, exactly as the file stated them.

    Kept so that a re-export can be compared against its origin, and so a
    diagnostic can name a file offset instead of an abstract map number.
    """

    header_offset: int
    plane_offsets: tuple[int, int, int]
    plane_lengths: tuple[int, int, int]


@dataclass(frozen=True)
class MapRecord:
    """One map: its slot, its 16 raw name bytes, and its three planes."""

    number: int  # 1-based; the archive's order is the map number
    name: NativeName
    planes: MapPlanes
    source: RecordSource | None = None

    @property
    def lump_name(self) -> str:
        """What the engine will call this map: `MAP01`, `MAP02`, ...

        The engine formats with `%02d`, so slot 100 becomes `MAP100` -- five
        characters, which still fits a WAD's eight-byte name field.
        """
        return f"MAP{self.number:02d}"

    @property
    def width(self) -> int:
        return self.planes.width

    @property
    def height(self) -> int:
        return self.planes.height


@dataclass
class Archive:
    """A parsed archive plus everything noticed while parsing it."""

    records: tuple[MapRecord, ...]
    diagnostics: DiagnosticLog = field(default_factory=DiagnosticLog)
    #: False when the file ends immediately after its last plane. The engine
    #: accepts that; the canonical writer always adds the terminator.
    terminated: bool = True

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, index: int) -> MapRecord:
        return self.records[index]

    def by_number(self, number: int) -> MapRecord:
        for record in self.records:
            if record.number == number:
                return record
        raise native_error(
            "C7E-NATIVE-001", f"archive has no map {number} (it holds {len(self.records)})"
        )


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _parse_header(
    data: bytes, offset: int, index: int
) -> tuple[NativeName, int, int, tuple[int, int, int], tuple[int, int, int]]:
    """Read one record header. Returns name, width, height, offsets, lengths."""
    where = f"map {index + 1}"
    if index == 0:
        if len(data) < FIRST_RECORD_BYTES:
            raise native_error(
                "C7E-NATIVE-001",
                f"file is {len(data)} bytes, too short for a {FIRST_RECORD_BYTES}-byte "
                "first record",
                where,
            )
        if data[:12] != TED5_SIGNATURE:
            raise native_error(
                "C7E-NATIVE-001", f"signature is {data[:12]!r}, expected {TED5_SIGNATURE!r}", where
            )
        plane_offsets = (FIRST_RECORD_BYTES, _u32(data, 12), _u32(data, 16))
        plane_lengths = tuple(_u16(data, 20 + plane * 2) for plane in range(PLANE_COUNT))
        width = _u16(data, 26)
        height = _u16(data, 28)
        raw_name = data[30:46]
    else:
        if len(data) - offset < LATER_RECORD_BYTES:
            raise native_error(
                "C7E-NATIVE-001",
                f"{len(data) - offset} bytes left at 0x{offset:x}, too few for a "
                f"{LATER_RECORD_BYTES}-byte record",
                where,
            )
        if data[offset : offset + 4] != MAP_MARKER:
            raise native_error(
                "C7E-NATIVE-001",
                f"expected {MAP_MARKER!r} at 0x{offset:x}, found "
                f"{data[offset:offset + 4]!r}",
                where,
            )
        plane_offsets = tuple(_u32(data, offset + 4 + plane * 4) for plane in range(PLANE_COUNT))
        plane_lengths = tuple(_u16(data, offset + 16 + plane * 2) for plane in range(PLANE_COUNT))
        width = _u16(data, offset + 22)
        height = _u16(data, offset + 24)
        raw_name = data[offset + 26 : offset + 42]

    return (
        NativeName.from_raw(raw_name),
        width,
        height,
        plane_offsets,  # type: ignore[return-value]
        plane_lengths,  # type: ignore[return-value]
    )


def parse_archive(data: bytes, *, log: DiagnosticLog | None = None) -> Archive:
    """Parse a whole archive, applying the engine's acceptance rules."""
    diagnostics = log if log is not None else DiagnosticLog()
    if len(data) > _U32_MAX:
        raise native_error(
            "C7E-NATIVE-001", f"file is {len(data)} bytes; offsets are 32-bit"
        )

    records: list[MapRecord] = []
    offset = 0
    terminated = False

    while offset < len(data):
        # The engine only reads a terminator when exactly four bytes remain,
        # so `!ID!` anywhere else is a record marker or an error, never an end.
        if len(data) - offset == 4:
            if data[offset : offset + 4] == MAP_MARKER:
                offset += 4
                terminated = True
                break

        if len(records) >= MAX_MAPS:
            raise native_error(
                "C7E-NATIVE-001",
                f"archive holds more than {MAX_MAPS} maps, the engine's fixed limit",
                f"0x{offset:x}",
            )

        index = len(records)
        where = f"map {index + 1}"
        name, width, height, plane_offsets, plane_lengths = _parse_header(data, offset, index)
        validate_dimensions(width, height, where=where)

        header_bytes = FIRST_RECORD_BYTES if index == 0 else LATER_RECORD_BYTES
        minimum_plane_offset = offset + header_bytes
        previous_end = 0
        for plane in range(PLANE_COUNT):
            start = plane_offsets[plane]
            end = start + plane_lengths[plane]
            if end > len(data):
                raise native_error(
                    "C7E-NATIVE-001",
                    f"plane {plane} runs 0x{start:x}+{plane_lengths[plane]} past the "
                    f"end of the {len(data)}-byte file",
                    where,
                )
            if plane == 0 and start < minimum_plane_offset:
                raise native_error(
                    "C7E-NATIVE-001",
                    f"plane 0 starts at 0x{start:x}, inside its own "
                    f"{header_bytes}-byte header ending at 0x{minimum_plane_offset:x}",
                    where,
                )
            if plane and start < previous_end:
                raise native_error(
                    "C7E-NATIVE-001",
                    f"plane {plane} starts at 0x{start:x}, overlapping plane "
                    f"{plane - 1} which ends at 0x{previous_end:x}",
                    where,
                )
            previous_end = end

        expected_words = width * height
        planes = tuple(
            decode_plane(
                data[plane_offsets[plane] : plane_offsets[plane] + plane_lengths[plane]],
                expected_words,
                where=f"{where} ({name.text}) plane {plane}",
                log=diagnostics,
            )
            for plane in range(PLANE_COUNT)
        )

        name.report(diagnostics, where)
        records.append(
            MapRecord(
                number=index + 1,
                name=name,
                planes=MapPlanes(width, height, planes),  # type: ignore[arg-type]
                source=RecordSource(offset, plane_offsets, plane_lengths),
            )
        )
        offset = plane_offsets[PLANE_COUNT - 1] + plane_lengths[PLANE_COUNT - 1]

    if offset != len(data):
        raise native_error(
            "C7E-NATIVE-001",
            f"{len(data) - offset} unexplained bytes after the last record at 0x{offset:x}",
        )
    if not records:
        raise native_error(
            "C7E-NATIVE-001",
            "archive contains no maps; the engine rejects an empty or marker-only file",
        )
    if not terminated:
        diagnostics.warning(
            "C7E-NATIVE-005",
            f"file ends at 0x{offset:x} without the conventional final {MAP_MARKER!r}; "
            "the engine loads it and the canonical writer adds one",
        )
    return Archive(tuple(records), diagnostics, terminated)


def encode_archive(records) -> bytes:
    """Write a canonical archive: implicit first offset, terminator, no runs of zero.

    Deterministic. Given the same records this returns the same bytes, which is
    what makes an export digest reproducible across machines.
    """
    records = tuple(records)
    if not 1 <= len(records) <= MAX_MAPS:
        raise native_error(
            "C7E-NATIVE-001",
            f"an archive holds 1..{MAX_MAPS} maps, not {len(records)}",
        )

    output = bytearray()
    for index, record in enumerate(records):
        where = f"map {index + 1}"
        planes = record.planes
        validate_dimensions(planes.width, planes.height, where=where)
        streams = tuple(
            encode_plane(planes.planes[plane], where=f"{where} plane {plane}")
            for plane in range(PLANE_COUNT)
        )

        header_offset = len(output)
        header_bytes = FIRST_RECORD_BYTES if index == 0 else LATER_RECORD_BYTES
        output.extend(b"\x00" * header_bytes)

        plane_offsets = []
        for stream in streams:
            plane_offsets.append(len(output))
            output.extend(stream)
        if plane_offsets[-1] + len(streams[-1]) > _U32_MAX:
            raise native_error("C7E-NATIVE-001", "archive exceeds the 32-bit offset space", where)

        raw_name = record.name.raw
        if len(raw_name) != NAME_FIELD_BYTES:
            raise native_error(
                "C7E-NATIVE-004",
                f"name field is {len(raw_name)} bytes, must be {NAME_FIELD_BYTES}",
                where,
            )
        lengths = tuple(len(stream) for stream in streams)

        if index == 0:
            # Plane 0's offset is not written: it is always immediately after
            # this header, which is exactly what the engine assumes.
            assert plane_offsets[0] == FIRST_RECORD_BYTES
            output[header_offset : header_offset + 12] = TED5_SIGNATURE
            struct.pack_into("<II", output, header_offset + 12, plane_offsets[1], plane_offsets[2])
            struct.pack_into("<HHH", output, header_offset + 20, *lengths)
            struct.pack_into("<HH", output, header_offset + 26, planes.width, planes.height)
            output[header_offset + 30 : header_offset + 46] = raw_name
        else:
            output[header_offset : header_offset + 4] = MAP_MARKER
            struct.pack_into("<III", output, header_offset + 4, *plane_offsets)
            struct.pack_into("<HHH", output, header_offset + 16, *lengths)
            struct.pack_into("<HH", output, header_offset + 22, planes.width, planes.height)
            output[header_offset + 26 : header_offset + 42] = raw_name

    output.extend(MAP_MARKER)
    return bytes(output)


def read_archive(path: Path | str, *, log: DiagnosticLog | None = None) -> Archive:
    """Parse an archive from disk. Read-only: the source is never opened for writing."""
    return parse_archive(Path(path).read_bytes(), log=log)
