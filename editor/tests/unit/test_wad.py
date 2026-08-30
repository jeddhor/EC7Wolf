#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E1: the preview WAD and its WDC3.1 PLANES lump.

A round trip through one implementation proves only that it is
self-consistent, so the header is also checked field by field against offsets
read off the engine, and one test parses the WAD with a reader written here
from the format description rather than from `ec7edit_core.wad`.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.archive import MapRecord
from ec7edit_core.errors import WadFormatError
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.wad import (
    PLANES_HEADER_BYTES,
    PLANES_MAGIC,
    WAD_HEADER_BYTES,
    WadLump,
    build_preview_wad,
    decode_planes_lump,
    decode_wad,
    encode_planes_lump,
    encode_wad,
    read_preview_wad,
    validate_marker,
)

_spec = importlib.util.spec_from_file_location(
    "make_fixtures", EDITOR / "scripts" / "make_fixtures.py")
make_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_fixtures)


def record(number=1, name="PREVIEW", width=3, height=2) -> MapRecord:
    planes = tuple(
        tuple(plane * 100 + cell for cell in range(width * height)) for plane in range(3)
    )
    return MapRecord(number, NativeName.from_text(name), MapPlanes(width, height, planes))


def independent_wad_reader(blob: bytes):
    """A second reader, written from the format and not from the writer.

    Twelve-byte header of magic, lump count and directory offset; sixteen-byte
    directory entries of position, size and an eight-byte NUL-padded name.
    """
    assert blob[0:4] == b"PWAD"
    count = int.from_bytes(blob[4:8], "little")
    table = int.from_bytes(blob[8:12], "little")
    entries = []
    for index in range(count):
        base = table + index * 16
        position = int.from_bytes(blob[base : base + 4], "little")
        size = int.from_bytes(blob[base + 4 : base + 8], "little")
        name = blob[base + 8 : base + 16].rstrip(b"\x00").decode("ascii")
        entries.append((name, blob[position : position + size]))
    return entries


class PlanesHeader(unittest.TestCase):
    """Offsets read from FMapLump::FillCache and GameMap::ReadPlanesData."""

    def setUp(self):
        self.record = record()
        self.lump = encode_planes_lump(self.record)

    def test_magic(self):
        self.assertEqual(self.lump[0:6], PLANES_MAGIC)

    def test_plane_count_and_name_length_at_ten_and_twelve(self):
        self.assertEqual(struct.unpack_from("<HH", self.lump, 10), (3, 16))

    def test_name_at_fourteen(self):
        self.assertEqual(self.lump[14:30], self.record.name.raw)

    def test_dimensions_at_thirty(self):
        self.assertEqual(struct.unpack_from("<HH", self.lump, 30), (3, 2))

    def test_plane_data_begins_at_thirty_four(self):
        self.assertEqual(len(self.lump), PLANES_HEADER_BYTES + 3 * 3 * 2 * 2)
        first = struct.unpack_from("<6H", self.lump, PLANES_HEADER_BYTES)
        self.assertEqual(first, self.record.planes.planes[0])

    def test_words_are_little_endian(self):
        wide = MapRecord(1, NativeName.from_text("LE"), MapPlanes(1, 1, ((0x1234,),) * 3))
        lump = encode_planes_lump(wide)
        self.assertEqual(lump[PLANES_HEADER_BYTES : PLANES_HEADER_BYTES + 2], b"\x34\x12")

    def test_planes_appear_in_file_order(self):
        lump = encode_planes_lump(self.record)
        cells = self.record.planes.cell_count
        for plane in range(3):
            begin = PLANES_HEADER_BYTES + plane * cells * 2
            self.assertEqual(
                struct.unpack_from(f"<{cells}H", lump, begin), self.record.planes.planes[plane]
            )

    def test_matches_the_independent_fixture_lump(self):
        # The E0 generator builds a PLANES payload from the same description
        # without importing any of this code.
        fixture = make_fixtures.fixture_set()["planes/8x8.planes"]
        self.assertEqual(fixture[0:6], PLANES_MAGIC)
        self.assertEqual(struct.unpack_from("<HH", fixture, 10), (3, 16))
        self.assertEqual(struct.unpack_from("<HH", fixture, 30), (8, 8))
        self.assertEqual(len(fixture), PLANES_HEADER_BYTES + 3 * 8 * 8 * 2)
        parsed = decode_planes_lump(fixture)
        self.assertEqual((parsed.width, parsed.height), (8, 8))


class PlanesRoundTrip(unittest.TestCase):
    def test_planes_survive(self):
        original = record()
        parsed = decode_planes_lump(encode_planes_lump(original))
        self.assertEqual(parsed.planes.planes, original.planes.planes)

    def test_raw_name_survives(self):
        raw = b"SLOT\x00\x001\x00" + b"\x00" * 8
        original = MapRecord(1, NativeName.from_raw(raw), MapPlanes.empty(2, 2))
        self.assertEqual(decode_planes_lump(encode_planes_lump(original)).name.raw, raw)

    def test_plane_two_is_carried_not_synthesised(self):
        planes = MapPlanes(2, 2, ((0,) * 4, (0,) * 4, (7, 8, 9, 10)))
        original = MapRecord(1, NativeName.from_text("P2"), planes)
        self.assertEqual(decode_planes_lump(encode_planes_lump(original)).planes.planes[2],
                         (7, 8, 9, 10))


class PlanesRejects(unittest.TestCase):
    def assertRefused(self, blob):
        with self.assertRaises(WadFormatError) as caught:
            decode_planes_lump(blob)
        self.assertEqual(caught.exception.diagnostic.code, "C7E-WAD-002")

    def test_truncated_header(self):
        self.assertRefused(encode_planes_lump(record())[:20])

    def test_bad_magic(self):
        blob = bytearray(encode_planes_lump(record()))
        blob[0:6] = b"WDC9.9"
        self.assertRefused(bytes(blob))

    def test_wrong_plane_count(self):
        blob = bytearray(encode_planes_lump(record()))
        struct.pack_into("<H", blob, 10, 4)
        self.assertRefused(bytes(blob))

    def test_wrong_name_length(self):
        blob = bytearray(encode_planes_lump(record()))
        struct.pack_into("<H", blob, 12, 8)
        self.assertRefused(bytes(blob))

    def test_dimensions_do_not_match_the_data(self):
        blob = bytearray(encode_planes_lump(record()))
        struct.pack_into("<HH", blob, 30, 9, 9)
        self.assertRefused(bytes(blob))

    def test_excess_data(self):
        self.assertRefused(encode_planes_lump(record()) + b"\x00" * 4)

    def test_zero_dimensions(self):
        blob = bytearray(encode_planes_lump(record()))
        struct.pack_into("<HH", blob, 30, 0, 0)
        self.assertRefused(bytes(blob))


class WadContainer(unittest.TestCase):
    def test_header_fields(self):
        blob = encode_wad([WadLump("MAP01", b""), WadLump("PLANES", b"abcd")])
        magic, count, table = struct.unpack_from("<4sII", blob, 0)
        self.assertEqual((magic, count), (b"PWAD", 2))
        self.assertEqual(table, WAD_HEADER_BYTES + 4)

    def test_lumps_are_contiguous_from_twelve_with_no_padding(self):
        blob = encode_wad([WadLump("A", b"1234"), WadLump("B", b"56789")])
        entries = independent_wad_reader(blob)
        self.assertEqual([data for _, data in entries], [b"1234", b"56789"])
        first = struct.unpack_from("<II", blob, 12 + 9)
        self.assertEqual(first[0], WAD_HEADER_BYTES)

    def test_names_are_upper_case_and_nul_padded(self):
        blob = encode_wad([WadLump("map01", b"")])
        table = struct.unpack_from("<I", blob, 8)[0]
        self.assertEqual(blob[table + 8 : table + 16], b"MAP01\x00\x00\x00")

    def test_digest_is_reproducible(self):
        lumps = [WadLump("MAP01", b""), WadLump("PLANES", encode_planes_lump(record()))]
        self.assertEqual(encode_wad(lumps), encode_wad(lumps))

    def test_an_eight_byte_name_is_the_limit(self):
        encode_wad([WadLump("ABCDEFGH", b"")])
        with self.assertRaises(WadFormatError):
            encode_wad([WadLump("ABCDEFGHI", b"")])

    def test_empty_wad_refused(self):
        with self.assertRaises(WadFormatError):
            encode_wad([])


class WadRejectsHostileInput(unittest.TestCase):
    def assertRefused(self, blob):
        with self.assertRaises(WadFormatError):
            decode_wad(blob)

    def test_too_short(self):
        self.assertRefused(b"PWAD")

    def test_bad_magic(self):
        self.assertRefused(b"XWAD" + b"\x00" * 8)

    def test_absurd_lump_count(self):
        blob = bytearray(encode_wad([WadLump("A", b"1")]))
        struct.pack_into("<I", blob, 4, 0xFFFFFFF)
        self.assertRefused(bytes(blob))

    def test_directory_offset_past_the_file(self):
        blob = bytearray(encode_wad([WadLump("A", b"1")]))
        struct.pack_into("<I", blob, 8, 0xFFFFFF00)
        self.assertRefused(bytes(blob))

    def test_directory_offset_inside_the_header(self):
        blob = bytearray(encode_wad([WadLump("A", b"1")]))
        struct.pack_into("<I", blob, 8, 4)
        self.assertRefused(bytes(blob))

    def test_lump_extending_past_the_file(self):
        blob = bytearray(encode_wad([WadLump("A", b"1")]))
        table = struct.unpack_from("<I", blob, 8)[0]
        struct.pack_into("<I", blob, table + 4, 0xFFFF)
        self.assertRefused(bytes(blob))

    def test_thirty_two_bit_overflow_in_a_lump_range(self):
        blob = bytearray(encode_wad([WadLump("A", b"1")]))
        table = struct.unpack_from("<I", blob, 8)[0]
        struct.pack_into("<II", blob, table, 0xFFFFFFF0, 0x20)
        self.assertRefused(bytes(blob))


class PreviewWad(unittest.TestCase):
    def test_marker_then_planes(self):
        blob = build_preview_wad([("MAP01", record())])
        entries = independent_wad_reader(blob)
        self.assertEqual([name for name, _ in entries], ["MAP01", "PLANES"])
        self.assertEqual(entries[0][1], b"")

    def test_several_maps_make_several_pairs(self):
        pairs = [("MAP01", record(1)), ("MAP07", record(7, "SEVEN")), ("MAP60", record(60, "SIXTY"))]
        entries = independent_wad_reader(build_preview_wad(pairs))
        self.assertEqual(
            [name for name, _ in entries],
            ["MAP01", "PLANES", "MAP07", "PLANES", "MAP60", "PLANES"],
        )

    def test_readback_returns_the_same_maps(self):
        pairs = [("MAP01", record(1)), ("MAP02", record(2, "TWO", 4, 4))]
        for (marker, original), (seen_marker, seen) in zip(pairs, read_preview_wad(
                build_preview_wad(pairs))):
            self.assertEqual(marker, seen_marker)
            self.assertEqual(seen.planes.planes, original.planes.planes)
            self.assertEqual(seen.name.raw, original.name.raw)

    def test_independent_reader_agrees_with_the_libraries(self):
        blob = build_preview_wad([("MAP01", record())])
        mine = [(lump.name, lump.data) for lump in decode_wad(blob)]
        self.assertEqual(mine, independent_wad_reader(blob))

    def test_nothing_but_the_map_pairs_is_written(self):
        blob = build_preview_wad([("MAP01", record())])
        self.assertEqual({name for name, _ in independent_wad_reader(blob)}, {"MAP01", "PLANES"})

    def test_duplicate_markers_refused(self):
        with self.assertRaises(WadFormatError):
            build_preview_wad([("MAP01", record()), ("MAP01", record(1, "AGAIN"))])

    def test_empty_selection_refused(self):
        with self.assertRaises(WadFormatError):
            build_preview_wad([])


class Markers(unittest.TestCase):
    def test_accepts_the_engines_range(self):
        for name in ("MAP01", "MAP09", "MAP40", "MAP60", "MAP99", "MAP100"):
            self.assertEqual(validate_marker(name), name)

    def test_rejects_everything_else(self):
        for name in ("MAP0", "MAP00", "MAP101", "MAP1", "map01", "E1M1", "PLANES", "MAPXX", ""):
            with self.subTest(name=name):
                with self.assertRaises(WadFormatError) as caught:
                    validate_marker(name)
                self.assertEqual(caught.exception.diagnostic.code, "C7E-WAD-001")


class MalformedPreviews(unittest.TestCase):
    def test_odd_lump_count(self):
        with self.assertRaises(WadFormatError):
            read_preview_wad(encode_wad([WadLump("MAP01", b"")]))

    def test_non_empty_marker(self):
        blob = encode_wad([WadLump("MAP01", b"junk"), WadLump("PLANES", encode_planes_lump(record()))])
        with self.assertRaises(WadFormatError):
            read_preview_wad(blob)

    def test_marker_not_followed_by_planes(self):
        blob = encode_wad([WadLump("MAP01", b""), WadLump("THINGS", b"")])
        with self.assertRaises(WadFormatError):
            read_preview_wad(blob)

    def test_reads_the_fixture_wad(self):
        fixture = make_fixtures.fixture_set()["wad/one-map.wad"]
        self.assertEqual([name for name, _ in independent_wad_reader(fixture)],
                         [name for name, _ in [(l.name, l.data) for l in decode_wad(fixture)]])


if __name__ == "__main__":
    unittest.main(verbosity=1)
