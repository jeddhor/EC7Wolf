# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Preview export: a `PWAD` holding `MAPxx` markers and `WDC3.1` PLANES lumps.

This is how a map reaches the running game without touching retail bytes. The
engine already turns each archive record into a zero-length `MAPxx` marker
followed by a generated `PLANES` lump (`FGamemaps::Open`), and a WAD supplied
later on the command line overrides the earlier one by name. So a preview WAD
is not a special editor format -- it is the same pair of lumps the engine makes
for itself, written to a file it loads last.

PLANES layout, little-endian, from `FMapLump::FillCache` and the reader in
`GameMap::ReadPlanesData`::

    00  char[6]  "WDC3.1"
    06  u32      map count (always 1 here)
    10  u16      plane count (3)
    12  u16      name length (16)
    14  char[16] name
    30  u16      width
    32  u16      height
    34  ...      three uncompressed planes, width*height u16 each

The reader seeks straight to offset 10 and never looks at bytes 6..9; the
engine's own writer leaves them uninitialized. This writer puts the documented
map count there, so a byte-for-byte comparison against an engine-produced lump
is meaningful from offset 10 onward and nowhere earlier.

WAD layout is the ordinary id one: a 12-byte header, lump data in order with
no padding, then the directory. Fixing "no padding, directory last, lumps in
declaration order" is what makes an exported digest reproducible.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .archive import MAX_MAPS, MapRecord
from .errors import wad_error
from .names import NAME_FIELD_BYTES, NativeName
from .planes import MapPlanes, PLANE_COUNT

PLANES_MAGIC = b"WDC3.1"
PLANES_HEADER_BYTES = 34
PLANES_LUMP_NAME = "PLANES"

WAD_MAGIC = b"PWAD"
WAD_HEADER_BYTES = 12
WAD_DIRECTORY_ENTRY_BYTES = 16
WAD_NAME_BYTES = 8

_U32_MAX = 0xFFFFFFFF
_MARKER = re.compile(r"^MAP([0-9]{2,3})$")


def validate_marker(name: str) -> str:
    """Accept the markers the engine actually generates, and nothing else.

    `mysnprintf(lumpname, 14, "MAP%02d", i+1)` gives `MAP01`..`MAP99` and then
    `MAP100` for the hundredth slot -- five characters, still inside a WAD name
    field, so the bounded three-digit case is representable rather than special.
    """
    match = _MARKER.match(name)
    if not match or not 1 <= int(match.group(1)) <= MAX_MAPS:
        raise wad_error(
            "C7E-WAD-001",
            f"{name!r} is not a map marker the engine generates; expected MAP01..MAP{MAX_MAPS}",
        )
    return name


def encode_planes_lump(record: MapRecord) -> bytes:
    """Build the uncompressed PLANES lump for one map."""
    planes = record.planes
    if len(record.name.raw) != NAME_FIELD_BYTES:
        raise wad_error(
            "C7E-WAD-002",
            f"name field is {len(record.name.raw)} bytes, PLANES declares {NAME_FIELD_BYTES}",
            record.lump_name,
        )

    lump = bytearray(PLANES_HEADER_BYTES)
    lump[0:6] = PLANES_MAGIC
    struct.pack_into("<I", lump, 6, 1)
    struct.pack_into("<HH", lump, 10, PLANE_COUNT, NAME_FIELD_BYTES)
    lump[14 : 14 + NAME_FIELD_BYTES] = record.name.raw
    struct.pack_into("<HH", lump, 30, planes.width, planes.height)

    for plane in range(PLANE_COUNT):
        lump.extend(struct.pack(f"<{planes.cell_count}H", *planes.planes[plane]))
    return bytes(lump)


def decode_planes_lump(data: bytes) -> MapRecord:
    """Read a PLANES lump back, without reference to how it was written.

    Deliberately a separate implementation from `encode_planes_lump`: a round
    trip through one shared misunderstanding proves nothing about the format.
    """
    if len(data) < PLANES_HEADER_BYTES:
        raise wad_error(
            "C7E-WAD-002",
            f"lump is {len(data)} bytes, shorter than the {PLANES_HEADER_BYTES}-byte header",
        )
    if data[0:6] != PLANES_MAGIC:
        raise wad_error("C7E-WAD-002", f"magic is {data[0:6]!r}, expected {PLANES_MAGIC!r}")

    plane_count, name_length = struct.unpack_from("<HH", data, 10)
    if plane_count != PLANE_COUNT:
        raise wad_error("C7E-WAD-002", f"lump declares {plane_count} planes, expected {PLANE_COUNT}")
    if name_length != NAME_FIELD_BYTES:
        raise wad_error(
            "C7E-WAD-002",
            f"lump declares a {name_length}-byte name; this layout fixes it at "
            f"{NAME_FIELD_BYTES}",
        )

    raw_name = data[14 : 14 + name_length]
    width, height = struct.unpack_from("<HH", data, 14 + name_length)
    cells = width * height
    if not cells:
        raise wad_error("C7E-WAD-002", f"lump declares {width}x{height}")

    expected = PLANES_HEADER_BYTES + PLANE_COUNT * cells * 2
    if len(data) != expected:
        raise wad_error(
            "C7E-WAD-002",
            f"lump is {len(data)} bytes; {width}x{height} with {PLANE_COUNT} planes needs {expected}",
        )

    planes = []
    for plane in range(PLANE_COUNT):
        begin = PLANES_HEADER_BYTES + plane * cells * 2
        planes.append(struct.unpack_from(f"<{cells}H", data, begin))
    return MapRecord(
        number=1,
        name=NativeName.from_raw(raw_name),
        planes=MapPlanes(width, height, tuple(planes)),  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class WadLump:
    """One directory entry and its bytes."""

    name: str
    data: bytes


def encode_wad(lumps) -> bytes:
    """Serialise lumps in order: header, data with no padding, then directory."""
    lumps = tuple(lumps)
    if not lumps:
        raise wad_error("C7E-WAD-001", "a WAD needs at least one lump")

    body = bytearray()
    directory = bytearray()
    offset = WAD_HEADER_BYTES
    for lump in lumps:
        encoded = lump.name.encode("ascii", errors="strict").upper()
        if len(encoded) > WAD_NAME_BYTES:
            raise wad_error(
                "C7E-WAD-001",
                f"lump name {lump.name!r} is {len(encoded)} bytes; the field is {WAD_NAME_BYTES}",
            )
        if offset + len(lump.data) > _U32_MAX:
            raise wad_error("C7E-WAD-001", "WAD exceeds the 32-bit offset space")
        directory.extend(struct.pack("<II", offset, len(lump.data)))
        directory.extend(encoded.ljust(WAD_NAME_BYTES, b"\x00"))
        body.extend(lump.data)
        offset += len(lump.data)

    header = struct.pack("<4sII", WAD_MAGIC, len(lumps), WAD_HEADER_BYTES + len(body))
    return bytes(header) + bytes(body) + bytes(directory)


def decode_wad(data: bytes) -> list[WadLump]:
    """Read a WAD's directory defensively; a hostile file must not be trusted."""
    if len(data) < WAD_HEADER_BYTES:
        raise wad_error("C7E-WAD-001", f"file is {len(data)} bytes, shorter than a WAD header")
    magic, count, table = struct.unpack_from("<4sII", data, 0)
    if magic not in (WAD_MAGIC, b"IWAD"):
        raise wad_error("C7E-WAD-001", f"magic is {magic!r}, expected {WAD_MAGIC!r}")

    # Check the whole table fits before believing `count`, so a claimed four
    # billion lumps costs a comparison rather than an allocation.
    end = table + count * WAD_DIRECTORY_ENTRY_BYTES
    if table < WAD_HEADER_BYTES or end > len(data):
        raise wad_error(
            "C7E-WAD-001",
            f"directory of {count} entries at 0x{table:x} does not fit the {len(data)}-byte file",
        )

    lumps = []
    for index in range(count):
        position, size, raw_name = struct.unpack_from(
            "<II8s", data, table + index * WAD_DIRECTORY_ENTRY_BYTES
        )
        if position + size > len(data):
            raise wad_error(
                "C7E-WAD-001",
                f"lump {index} runs 0x{position:x}+{size} past the {len(data)}-byte file",
            )
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        lumps.append(WadLump(name, data[position : position + size]))
    return lumps


def build_preview_wad(pairs) -> bytes:
    """Build a preview WAD from `(marker, record)` pairs.

    Each map contributes exactly two lumps: a zero-length marker and the PLANES
    that must immediately follow it. Nothing else goes in -- an override WAD
    that also carried textures or MAPINFO would stop being a preview and start
    being a mod.
    """
    pairs = tuple(pairs)
    if not pairs:
        raise wad_error("C7E-WAD-001", "a preview WAD needs at least one map")

    seen: set[str] = set()
    lumps: list[WadLump] = []
    for marker, record in pairs:
        validate_marker(marker)
        if marker in seen:
            raise wad_error("C7E-WAD-001", f"marker {marker} appears twice; each must be unique")
        seen.add(marker)
        lumps.append(WadLump(marker, b""))
        lumps.append(WadLump(PLANES_LUMP_NAME, encode_planes_lump(record)))
    return encode_wad(lumps)


def read_preview_wad(data: bytes) -> list[tuple[str, MapRecord]]:
    """Independent readback: marker/PLANES pairing is verified, not assumed."""
    lumps = decode_wad(data)
    if len(lumps) % 2:
        raise wad_error("C7E-WAD-001", f"{len(lumps)} lumps; a preview holds marker/PLANES pairs")

    pairs = []
    for index in range(0, len(lumps), 2):
        marker, planes = lumps[index], lumps[index + 1]
        validate_marker(marker.name)
        if marker.data:
            raise wad_error(
                "C7E-WAD-001", f"marker {marker.name} is {len(marker.data)} bytes, must be empty"
            )
        if planes.name != PLANES_LUMP_NAME:
            raise wad_error(
                "C7E-WAD-001",
                f"{marker.name} is followed by {planes.name!r}, not {PLANES_LUMP_NAME!r}",
            )
        pairs.append((marker.name, decode_planes_lump(planes.data)))
    return pairs
