# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Writing FLIC, checked by a decoder written separately.

The encoder is verified against an independent implementation in this file
rather than against itself. A round trip through one shared misunderstanding
proves nothing, and this format has a specific way of inviting one: **BRUN and
LC use opposite sign conventions.** In BRUN a positive count is a run and a
negative one is literals; in LC it is the other way round. Getting LC's
backwards produces a file whose first frame is perfect and whose every later
frame is noise -- which is exactly what happened, and is why the decoder below
exists.

`tools/test_ec7edit_e14.sh` checks the same files against the engine's own
decoder, which is the authority that actually matters.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core.errors import ExportError
from ec7edit_core.flic import (
    BRUN, COLOR256, FLC_MAGIC, FRAME_MAGIC, HEIGHT, LC, PIXELS, WIDTH, Frame,
    encode, encode_brun, encode_lc,
)


def decode(blob: bytes):
    """An independent FLIC reader: frames and the palette, nothing else."""
    size, magic, count, width, height, depth = struct.unpack_from("<IHHHHH", blob, 0)
    assert magic == FLC_MAGIC, f"magic {magic:#x}"
    assert size == len(blob), f"header says {size}, file is {len(blob)}"
    assert (width, height, depth) == (WIDTH, HEIGHT, 8)
    speed = struct.unpack_from("<I", blob, 16)[0]

    pixels = bytearray(PIXELS)
    palette = [(0, 0, 0)] * 256
    frames = []
    at = 128
    while at + 16 <= len(blob) and len(frames) < count:
        chunk_size, chunk_magic, chunks = struct.unpack_from("<IHH", blob, at)
        assert chunk_magic == FRAME_MAGIC
        sub = at + 16
        for _ in range(chunks):
            sub_size, kind = struct.unpack_from("<IH", blob, sub)
            body = blob[sub + 6:sub + sub_size]
            if kind == COLOR256:
                _color(body, palette)
            elif kind == BRUN:
                _brun(body, pixels)
            elif kind == LC:
                _lc(body, pixels)
            else:
                raise AssertionError(f"unexpected chunk {kind}")
            sub += sub_size
        frames.append(bytes(pixels))
        at += chunk_size
    return frames, palette, speed


def _color(body, palette):
    packets = struct.unpack_from("<H", body, 0)[0]
    at, index = 2, 0
    for _ in range(packets):
        index += body[at]
        count = body[at + 1] or 256
        at += 2
        for _ in range(count):
            palette[index] = (body[at], body[at + 1], body[at + 2])
            at += 3
            index += 1


def _brun(body, pixels):
    at = 0
    for y in range(HEIGHT):
        at += 1                                   # the vestigial packet count
        x = 0
        while x < WIDTH:
            count = struct.unpack_from("<b", body, at)[0]
            at += 1
            if count >= 0:                        # BRUN: positive is a RUN
                pixels[y * WIDTH + x:y * WIDTH + x + count] = bytes([body[at]]) * count
                at += 1
                x += count
            else:
                run = -count
                pixels[y * WIDTH + x:y * WIDTH + x + run] = body[at:at + run]
                at += run
                x += run


def _lc(body, pixels):
    y, lines = struct.unpack_from("<HH", body, 0)
    at = 4
    for _ in range(lines):
        packets = body[at]
        at += 1
        x = 0
        for _ in range(packets):
            x += body[at]
            count = struct.unpack_from("<b", body, at + 1)[0]
            at += 2
            if count >= 0:                        # LC: positive is LITERALS
                pixels[y * WIDTH + x:y * WIDTH + x + count] = body[at:at + count]
                at += count
                x += count
            else:
                run = -count
                pixels[y * WIDTH + x:y * WIDTH + x + run] = bytes([body[at]]) * run
                at += 1
                x += run
        y += 1


def flat(value: int) -> Frame:
    return Frame(bytes([value]) * PIXELS)


def patterned(seed: int) -> Frame:
    return Frame(bytes((x * 7 + y * 13 + seed) % 256
                       for y in range(HEIGHT) for x in range(WIDTH)))


def moving(step: int) -> Frame:
    pixels = bytearray(PIXELS)
    for y in range(HEIGHT):
        pixels[y * WIDTH:(y + 1) * WIDTH] = bytes([16 if (y // 20) % 2 else 32]) * WIDTH
    left = 20 + step * 9
    for y in range(80, 130):
        for x in range(left, min(WIDTH, left + 45)):
            pixels[y * WIDTH + x] = 200 + ((x + y) % 40)
    return Frame(bytes(pixels))


PALETTE = [(i, (i * 7) % 256, (i * 13) % 256) for i in range(256)]


class RoundTrip(unittest.TestCase):
    def assertSurvives(self, frames):
        blob = encode(frames, PALETTE)
        decoded, palette, _ = decode(blob)
        self.assertEqual(len(decoded), len(frames))
        for index, (want, got) in enumerate(zip(frames, decoded)):
            self.assertEqual(got, want.pixels, f"frame {index + 1} differs")
        self.assertEqual(palette, PALETTE)
        return blob

    def test_one_flat_frame(self):
        self.assertSurvives([flat(7)])

    def test_a_frame_with_no_runs_at_all(self):
        # Every byte different from its neighbour: all literals, no runs, and
        # the packet counts have to be right or the row walks off its end.
        self.assertSurvives([patterned(0)])

    def test_frames_that_move(self):
        # The case the format is for, and the one that exercises LC.
        self.assertSurvives([moving(step) for step in range(8)])

    def test_a_frame_identical_to_the_one_before_it(self):
        self.assertSurvives([flat(3), flat(3), flat(3)])

    def test_a_frame_that_changes_completely(self):
        # LC would be larger than the frame, so BRUN is used instead. Both
        # paths have to decode to the same thing.
        self.assertSurvives([patterned(0), patterned(101), patterned(202)])

    def test_a_long_run_of_one_color_across_a_whole_row(self):
        # 320 pixels is longer than one packet can express, so a row of one
        # color must be split into several.
        self.assertSurvives([flat(0), flat(255)])


class Compression(unittest.TestCase):
    def test_a_still_animation_costs_almost_nothing_after_the_first_frame(self):
        blob = encode([flat(9)] * 30, PALETTE)
        self.assertLess(len(blob), PIXELS + 4000,
                        "identical frames should carry no image data")

    def test_movement_costs_far_less_than_a_whole_frame(self):
        blob = encode([moving(step) for step in range(20)], PALETTE)
        per_frame = len(blob) / 20
        self.assertLess(per_frame, PIXELS / 8,
                        f"{per_frame:.0f} bytes a frame is not a delta")


class Refusing(unittest.TestCase):
    def test_a_frame_of_the_wrong_size(self):
        with self.assertRaises(ExportError):
            Frame(b"\0" * 100)

    def test_no_frames(self):
        with self.assertRaises(ExportError):
            encode([], PALETTE)

    def test_a_palette_that_is_not_256_colors(self):
        with self.assertRaises(ExportError):
            encode([flat(0)], PALETTE[:200])

    def test_an_impossible_speed(self):
        with self.assertRaises(ExportError):
            encode([flat(0)], PALETTE, speed_ms=0)


class Header(unittest.TestCase):
    def test_the_speed_is_what_was_asked_for(self):
        _, _, speed = decode(encode([flat(1), flat(2)], PALETTE, speed_ms=100))
        self.assertEqual(speed, 100)

    def test_the_size_field_matches_the_file(self):
        blob = encode([moving(0), moving(1)], PALETTE)
        self.assertEqual(struct.unpack_from("<I", blob, 0)[0], len(blob))

    def test_the_first_frame_offset_points_at_a_frame(self):
        blob = encode([flat(1)], PALETTE)
        offset = struct.unpack_from("<I", blob, 80)[0]
        self.assertEqual(struct.unpack_from("<H", blob, offset + 4)[0], FRAME_MAGIC)


class Encodings(unittest.TestCase):
    def test_lc_reports_no_change(self):
        self.assertIsNone(encode_lc(flat(4).pixels, flat(4).pixels))

    def test_brun_covers_every_row(self):
        pixels = bytearray(PIXELS)
        out = bytearray(PIXELS)
        _brun(encode_brun(bytes(pixels)), out)
        self.assertEqual(bytes(out), bytes(pixels))


if __name__ == "__main__":
    unittest.main()
