#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E2: the graphics decoders, on synthetic pages built from the format.

Every input here is generated to the documented layout rather than captured
from the game, so a decoder that agrees with these tests agrees with the format
and not with one sample of it. The retail data is exercised separately, by the
owned-data gate, where the assertion is a count and a digest rather than bytes
in the repository.

The hostile-input cases are the point of the file. GFXTILES and the sprite
pages are full of offsets, and every one of them is an index into a buffer.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.assets import (
    PALETTE_OFFSET,
    PALETTE_SIZE,
    AssetError,
    ImageCache,
    average_color,
    encode_png,
    extract_vga,
    is_blank,
    load_palette,
    parse_gfx_header,
    sprite_rgba,
    wall_rgb,
)

_spec = importlib.util.spec_from_file_location(
    "make_fixtures", EDITOR / "scripts" / "make_fixtures.py")
make_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_fixtures)
FIXTURES = make_fixtures.fixture_set()

PALETTE = load_palette(FIXTURES["assets/palette.exe"])


class Palette(unittest.TestCase):
    def test_expands_six_bits_to_eight(self):
        self.assertEqual(len(PALETTE), PALETTE_SIZE)
        self.assertTrue(all(0 <= value <= 255 for value in PALETTE))

    def test_full_six_bit_value_becomes_full_eight(self):
        raw = bytearray(FIXTURES["assets/palette.exe"])
        raw[PALETTE_OFFSET] = 63
        self.assertEqual(load_palette(bytes(raw))[0], 255)

    def test_zero_stays_zero(self):
        self.assertEqual(load_palette(FIXTURES["assets/palette.exe"])[0], 0)

    def test_a_short_file_is_refused(self):
        with self.assertRaises(AssetError):
            load_palette(b"\x00" * 1024)

    def test_a_file_without_a_six_bit_palette_is_refused(self):
        # This is what tells a real executable from one of the right length.
        raw = bytearray(FIXTURES["assets/palette.exe"])
        raw[PALETTE_OFFSET + 5] = 200
        with self.assertRaises(AssetError):
            load_palette(bytes(raw))


class Png(unittest.TestCase):
    def test_signature_and_chunks(self):
        blob = encode_png(2, 2, bytes(2 * 2 * 3), alpha=False)
        self.assertEqual(blob[:8], b"\x89PNG\r\n\x1a\n")
        for chunk in (b"IHDR", b"IDAT", b"IEND"):
            self.assertIn(chunk, blob)

    def test_header_records_size_and_colour_type(self):
        blob = encode_png(3, 5, bytes(3 * 5 * 4), alpha=True)
        width, height, depth, colour = struct.unpack_from(">IIBB", blob, 16)
        self.assertEqual((width, height, depth, colour), (3, 5, 8, 6))

    def test_deterministic(self):
        pixels = bytes(range(48))
        self.assertEqual(
            encode_png(4, 4, pixels, alpha=False), encode_png(4, 4, pixels, alpha=False)
        )

    def test_wrong_pixel_count_is_refused(self):
        with self.assertRaises(AssetError):
            encode_png(4, 4, b"\x00" * 10, alpha=False)


class Walls(unittest.TestCase):
    def test_decodes_to_row_major_rgb(self):
        page = FIXTURES["assets/wall.page"]
        rgb = wall_rgb(page, PALETTE)
        self.assertEqual(len(rgb), 64 * 64 * 3)

    def test_the_transpose_is_applied(self):
        # Pages are column-major. Cell (x=1, y=0) lives at byte 1*64+0 in the
        # page and at pixel 0*64+1 in the output; getting this backwards gives
        # a picture that looks plausible and is mirrored about the diagonal.
        page = bytearray(64 * 64)
        page[1 * 64 + 0] = 7
        rgb = wall_rgb(bytes(page), PALETTE)
        expected = tuple(PALETTE[7 * 3 : 7 * 3 + 3])
        self.assertEqual(tuple(rgb[3:6]), expected)
        self.assertNotEqual(tuple(rgb[64 * 3 : 64 * 3 + 3]), expected)

    def test_a_short_page_is_refused(self):
        with self.assertRaises(AssetError):
            wall_rgb(b"\x00" * 100, PALETTE)

    def test_two_pages_differ(self):
        self.assertNotEqual(
            wall_rgb(FIXTURES["assets/wall.page"], PALETTE),
            wall_rgb(FIXTURES["assets/wall-alt.page"], PALETTE),
        )


class Sprites(unittest.TestCase):
    def test_decodes_the_expected_opaque_area(self):
        rgba = sprite_rgba(FIXTURES["assets/sprite.page"], PALETTE)
        self.assertEqual(len(rgba), 64 * 64 * 4)
        opaque = sum(1 for index in range(3, len(rgba), 4) if rgba[index])
        self.assertEqual(opaque, (43 - 20 + 1) * (48 - 16))

    def test_everything_outside_the_posts_is_transparent(self):
        rgba = sprite_rgba(FIXTURES["assets/sprite.page"], PALETTE)
        for x in (0, 19, 44, 63):
            for y in (0, 32, 63):
                self.assertEqual(rgba[(y * 64 + x) * 4 + 3], 0, f"({x},{y})")

    def assertRefused(self, page):
        with self.assertRaises(AssetError):
            sprite_rgba(page, PALETTE)

    def test_truncated_bounds(self):
        self.assertRefused(b"\x00\x00")

    def test_reversed_column_range(self):
        self.assertRefused(struct.pack("<HH", 40, 10) + b"\x00" * 64)

    def test_column_past_the_page_width(self):
        self.assertRefused(struct.pack("<HH", 0, 200) + b"\x00" * 64)

    def test_column_table_longer_than_the_page(self):
        self.assertRefused(struct.pack("<HH", 0, 63))

    def test_post_pointing_outside_the_page(self):
        page = bytearray(FIXTURES["assets/sprite.page"])
        first = struct.unpack_from("<H", page, 4)[0]
        struct.pack_into("<h", page, first + 2, 30000)
        self.assertRefused(bytes(page))

    def test_post_taller_than_the_sprite(self):
        page = bytearray(FIXTURES["assets/sprite.page"])
        first = struct.unpack_from("<H", page, 4)[0]
        struct.pack_into("<H", page, first, 200 * 2)
        self.assertRefused(bytes(page))

    def test_command_offset_past_the_page(self):
        page = bytearray(FIXTURES["assets/sprite.page"])
        struct.pack_into("<H", page, 4, 0xFFF0)
        self.assertRefused(bytes(page))


class GfxHeaderTests(unittest.TestCase):
    def build(self, chunk_count=4, sprite_start=2, sound_start=4, payload=b"\x00" * 64):
        offsets = [len(payload)] * chunk_count
        header = struct.pack("<HHH", chunk_count, sprite_start, sound_start)
        header += struct.pack(f"<{chunk_count}I", *offsets)
        header += struct.pack(f"<{chunk_count}H", *([0] * chunk_count))
        return header + payload

    def test_reads_the_directory(self):
        header = parse_gfx_header(self.build())
        self.assertEqual(header.chunk_count, 4)
        self.assertEqual(list(header.wall_pages()), [0, 1])
        self.assertEqual(list(header.sprite_pages()), [2, 3])

    def test_too_short_for_a_header(self):
        with self.assertRaises(AssetError):
            parse_gfx_header(b"\x00\x00")

    def test_directory_longer_than_the_file(self):
        with self.assertRaises(AssetError):
            parse_gfx_header(struct.pack("<HHH", 9999, 0, 0))

    def test_boundaries_out_of_order(self):
        with self.assertRaises(AssetError):
            parse_gfx_header(self.build(sprite_start=4, sound_start=2))

    def test_chunk_index_is_bounds_checked(self):
        data = self.build()
        header = parse_gfx_header(data)
        with self.assertRaises(AssetError):
            header.chunk(data, 99)

    def test_chunk_running_past_the_file_is_refused(self):
        data = bytearray(self.build())
        struct.pack_into("<H", data, 6 + 4 * 4, 0xFFFF)
        header = parse_gfx_header(bytes(data))
        with self.assertRaises(AssetError):
            header.chunk(bytes(data), 0)


class Vga(unittest.TestCase):
    def test_a_short_dictionary_is_refused(self):
        with self.assertRaises(AssetError):
            extract_vga(b"\x00" * 16, b"\x00" * 6, b"\x00" * 16, PALETTE)


class Helpers(unittest.TestCase):
    def test_average_colour(self):
        self.assertEqual(average_color(bytes([0, 0, 0, 10, 20, 30])), (5, 10, 15))

    def test_average_of_nothing(self):
        self.assertEqual(average_color(b""), (0, 0, 0))

    def test_blank_detection(self):
        self.assertTrue(is_blank(bytes(4 * 4 * 4), channels=4))
        self.assertTrue(is_blank(b"\x11\x22\x33" * 16, channels=3))
        self.assertFalse(is_blank(b"\x11\x22\x33" * 15 + b"\x00\x00\x00", channels=3))


class Cache(unittest.TestCase):
    def test_evicts_least_recently_used(self):
        cache = ImageCache(budget_bytes=100)
        cache.put("a", b"x" * 40)
        cache.put("b", b"y" * 40)
        cache.get("a")  # touch a, so b becomes the oldest
        cache.put("c", b"z" * 40)
        self.assertIsNotNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))
        self.assertIsNotNone(cache.get("c"))

    def test_bounded_by_bytes_not_entries(self):
        cache = ImageCache(budget_bytes=1000)
        for index in range(100):
            cache.put(str(index), b"x" * 100)
        self.assertLessEqual(cache.size_bytes, 1000)

    def test_an_item_larger_than_the_budget_is_not_cached(self):
        cache = ImageCache(budget_bytes=50)
        cache.put("big", b"x" * 500)
        self.assertIsNone(cache.get("big"))
        self.assertEqual(cache.size_bytes, 0)

    def test_replacing_a_key_accounts_for_the_old_size(self):
        cache = ImageCache(budget_bytes=1000)
        cache.put("a", b"x" * 400)
        cache.put("a", b"y" * 10)
        self.assertEqual(cache.size_bytes, 10)
        self.assertEqual(len(cache), 1)

    def test_fetch_produces_once(self):
        cache = ImageCache()
        calls = []

        def produce():
            calls.append(1)
            return b"value"

        self.assertEqual(cache.fetch("k", produce), b"value")
        self.assertEqual(cache.fetch("k", produce), b"value")
        self.assertEqual(len(calls), 1)
        self.assertEqual((cache.hits, cache.misses), (1, 1))


if __name__ == "__main__":
    unittest.main(verbosity=1)
