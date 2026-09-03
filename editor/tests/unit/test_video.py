# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Frames in, cinematic out: the PNG reader, the color reduction, the pipeline.

None of this needs a third-party library, which is the point -- `ec7edit_core`
depends on the standard library alone, and PNG's own decompression is zlib.
ffmpeg is used when it is there and its absence is a message rather than a
failure, so the tests that need it say so.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core import flic, video
from ec7edit_core.errors import ExportError
from ec7edit_core.imagery import (
    build_mapping, build_palette, quantize, quantize_stable, read_png,
)


def write_png(path: Path, width: int, height: int, rgb: bytes, *,
              mode: int = 2, filt: int = 0) -> Path:
    """A PNG with a chosen row filter, so the reader's filters get exercised."""
    channels = {0: 1, 2: 3, 6: 4}[mode]
    rows = []
    previous = bytearray(width * channels)
    for y in range(height):
        if mode == 2:
            line = bytearray(rgb[y * width * 3:(y + 1) * width * 3])
        elif mode == 6:
            line = bytearray()
            for x in range(width):
                line.extend(rgb[(y * width + x) * 3:(y * width + x) * 3 + 3])
                line.append(255)
        else:
            line = bytearray(rgb[(y * width + x) * 3] for x in range(width))
        raw = bytearray(line)
        if filt == 1:                     # Sub
            for i in range(len(raw) - 1, channels - 1, -1):
                raw[i] = (raw[i] - raw[i - channels]) & 0xFF
        elif filt == 2:                   # Up
            for i in range(len(raw)):
                raw[i] = (raw[i] - previous[i]) & 0xFF
        rows.append(bytes([filt]) + bytes(raw))
        previous = line

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, mode, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
        + chunk(b"IEND", b""))
    return path


def a_frame(step: int) -> bytes:
    rgb = bytearray(flic.WIDTH * flic.HEIGHT * 3)
    for y in range(flic.HEIGHT):
        for x in range(flic.WIDTH):
            at = (y * flic.WIDTH + x) * 3
            rgb[at] = (x * 255) // flic.WIDTH
            rgb[at + 1] = (y * 255) // flic.HEIGHT
            rgb[at + 2] = (step * 30) % 256
    return bytes(rgb)


class Png(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_truecolor(self):
        rgb = a_frame(0)
        path = write_png(self.root / "a.png", flic.WIDTH, flic.HEIGHT, rgb)
        self.assertEqual(read_png(path), (flic.WIDTH, flic.HEIGHT, rgb))

    def test_every_row_filter_this_reads(self):
        rgb = a_frame(1)
        for filt in (0, 1, 2):
            with self.subTest(filter=filt):
                path = write_png(self.root / f"f{filt}.png", flic.WIDTH,
                                 flic.HEIGHT, rgb, filt=filt)
                self.assertEqual(read_png(path)[2], rgb)

    def test_alpha_is_dropped_rather_than_refused(self):
        # A cinematic has no transparency, and every screen recorder writes
        # RGBA. Refusing those would be refusing the common case.
        rgb = a_frame(2)
        path = write_png(self.root / "rgba.png", flic.WIDTH, flic.HEIGHT, rgb, mode=6)
        self.assertEqual(read_png(path)[2], rgb)

    def test_something_that_is_not_a_png(self):
        path = self.root / "no.png"
        path.write_bytes(b"not a png at all")
        with self.assertRaises(ExportError):
            read_png(path)


class Colors(unittest.TestCase):
    def test_the_palette_keeps_the_colors_that_are_actually_there(self):
        images = [a_frame(step) for step in range(4)]
        palette = build_palette(images)
        self.assertEqual(len(palette), 256)

    def test_quantizing_maps_a_color_to_something_close(self):
        images = [a_frame(0)]
        palette = build_palette(images)
        mapping = build_mapping(palette)
        indexed = quantize(images[0], mapping)
        self.assertEqual(len(indexed), flic.PIXELS)
        worst = 0
        for at in range(0, flic.PIXELS, 997):
            r, g, b = images[0][at * 3:at * 3 + 3]
            pr, pg, pb = palette[indexed[at]]
            worst = max(worst, abs(r - pr) + abs(g - pg) + abs(b - pb))
        # Five-bit buckets, so eight per channel is the floor; anything much
        # above that means the nearest-color search is picking badly.
        self.assertLess(worst, 60, "quantization is losing too much")

    def test_a_smaller_palette_is_honored(self):
        palette = build_palette([a_frame(0)], colors=16)
        self.assertEqual(len(palette), 16)


class Stability(unittest.TestCase):
    """Keeping the previous frame's index where the color has not really moved.

    Real footage is noisy, and quantizing each frame on its own turns that
    noise into a different palette index every frame across large flat areas.
    Measured on a 77-frame clip of real video: a quarter of every frame
    changed, and three quarters of those changes were to a color
    indistinguishable from the one already there -- paid for twice, in the
    delta and in a shimmer across every wall in the picture.
    """

    def setUp(self):
        self.palette = [(0, 0, 0), (10, 10, 10), (200, 30, 30), (255, 255, 255)]
        self.palette += [(0, 0, 0)] * (256 - len(self.palette))
        self.mapping = build_mapping(self.palette)

    def test_the_first_frame_is_quantized_normally(self):
        from ec7edit_core.imagery import quantize, quantize_stable
        rgb = bytes([200, 30, 30] * 16)
        self.assertEqual(quantize_stable(rgb, self.mapping, self.palette, None),
                         quantize(rgb, self.mapping))

    def test_a_color_that_barely_moved_keeps_its_index(self):
        from ec7edit_core.imagery import quantize_stable
        previous = bytes([1] * 16)                      # (10, 10, 10)
        rgb = bytes([12, 12, 12] * 16)                  # near enough
        self.assertEqual(quantize_stable(rgb, self.mapping, self.palette, previous),
                         previous)

    def test_a_color_that_really_moved_does_not(self):
        from ec7edit_core.imagery import quantize_stable
        previous = bytes([1] * 16)                      # (10, 10, 10)
        rgb = bytes([255, 255, 255] * 16)               # nothing like it
        self.assertNotEqual(quantize_stable(rgb, self.mapping, self.palette, previous),
                            previous)

    def test_zero_stability_is_plain_quantization(self):
        from ec7edit_core.imagery import quantize, quantize_stable
        previous = bytes([1] * 16)
        rgb = bytes([11, 11, 11] * 16)
        self.assertEqual(
            quantize_stable(rgb, self.mapping, self.palette, previous, 0),
            quantize(rgb, self.mapping))

    def test_it_makes_a_noisy_animation_smaller(self):
        import random

        from ec7edit_core import video as video_module

        random.seed(7)
        base = bytearray()
        for _ in range(flic.WIDTH * flic.HEIGHT):
            base.extend((120, 120, 120))
        frames = []
        for _ in range(6):
            noisy = bytearray(base)
            for at in range(0, len(noisy), 3):
                jitter = random.randint(-4, 4)
                noisy[at] = max(0, min(255, noisy[at] + jitter))
                noisy[at + 1] = max(0, min(255, noisy[at + 1] + jitter))
                noisy[at + 2] = max(0, min(255, noisy[at + 2] + jitter))
            frames.append(bytes(noisy))

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for index, rgb in enumerate(frames):
                write_png(folder / f"{index:03d}.png", flic.WIDTH, flic.HEIGHT, rgb)
            steady = video_module.encode(folder, stability=900)
            jumpy = video_module.encode(folder, stability=0)
        self.assertLess(len(steady.data), len(jumpy.data),
                        "stability should shrink a noisy animation")


class Pipeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.frames = self.root / "frames"
        self.frames.mkdir()
        for step in range(4):
            write_png(self.frames / f"{step:04d}.png", flic.WIDTH, flic.HEIGHT,
                      a_frame(step))

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_folder_of_frames_becomes_a_cinematic(self):
        result = video.encode(self.frames, fps=14)
        self.assertEqual(result.frames, 4)
        self.assertEqual(result.speed_ms, 71)
        self.assertEqual(result.data[4:6], b"\x12\xaf")   # the FLC magic

    def test_frames_are_taken_in_name_order(self):
        files = video.frame_files(self.frames)
        self.assertEqual([p.name for p in files],
                         ["0000.png", "0001.png", "0002.png", "0003.png"])

    def test_a_frame_of_the_wrong_size_says_which_one_and_what_to_do(self):
        write_png(self.frames / "9999.png", 100, 80, bytes(100 * 80 * 3))
        with self.assertRaises(ExportError) as caught:
            video.encode(self.frames)
        self.assertIn("9999.png", caught.exception.diagnostic.message)
        self.assertIn("scale", caught.exception.diagnostic.message)

    def test_an_empty_folder(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(ExportError):
            video.encode(empty)

    def test_something_that_is_neither(self):
        odd = self.root / "notes.txt"
        odd.write_text("hello")
        with self.assertRaises(ExportError):
            video.encode(odd)

    def test_an_impossible_frame_rate(self):
        with self.assertRaises(ExportError):
            video.encode(self.frames, fps=0)

    @unittest.skipUnless(video.have_ffmpeg(), "ffmpeg is not installed")
    def test_a_real_video_file(self):
        import subprocess

        source = self.root / "clip.mp4"
        subprocess.run(
            [video.have_ffmpeg(), "-nostdin", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=640x480:rate=10:duration=1",
             str(source)], check=True, capture_output=True)
        result = video.encode(source, fps=10)
        self.assertGreaterEqual(result.frames, 8)
        self.assertEqual(result.data[4:6], b"\x12\xaf")


if __name__ == "__main__":
    unittest.main()
