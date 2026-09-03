# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Reading PNG frames and reducing them to 256 colors, without a dependency.

`ec7edit_core` depends on nothing but the standard library, deliberately, so
that everything it does can be tested anywhere Python runs. Pulling in Pillow
to turn a folder of frames into a cinematic would give that up for two
operations that are eighty lines each -- and PNG's own decompression is
`zlib`, which is already there.

So: a PNG reader that handles what a frame actually is, and a color reducer.
Neither is general. The reader takes 8-bit truecolor and grayscale, with or
without alpha, non-interlaced -- which is what every tool writes when asked for
frames, `ffmpeg` included. Anything else is refused with a message saying what
to do about it, rather than half-decoded.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .errors import export_error

#: Bits per channel kept when building the palette. Five is 32768 buckets,
#: which is enough to tell a gradient from a flat area and small enough that
#: the whole mapping fits in a list that can be indexed rather than searched.
_QUANT_BITS = 5
_QUANT_SIZE = 1 << (_QUANT_BITS * 3)


def read_png(path: Path | str) -> tuple[int, int, bytes]:
    """One PNG as `(width, height, rgb)`, three bytes a pixel, row-major."""
    path = Path(path)
    blob = path.read_bytes()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise export_error("C7E-IMG-001", f"{path.name} is not a PNG", str(path))

    header = None
    palette = b""
    data = bytearray()
    at = 8
    while at + 8 <= len(blob):
        length, kind = struct.unpack_from(">I4s", blob, at)
        body = blob[at + 8:at + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            data.extend(body)
        elif kind == b"IEND":
            break
        at += 12 + length

    if header is None:
        raise export_error("C7E-IMG-001", f"{path.name} has no header", str(path))
    width, height, depth, mode, compression, filt, interlace = header
    if depth != 8:
        raise export_error(
            "C7E-IMG-002",
            f"{path.name} is {depth} bits a channel; frames must be 8. "
            "ffmpeg writes 8-bit by default.", str(path))
    if interlace:
        raise export_error(
            "C7E-IMG-002",
            f"{path.name} is interlaced, which this does not read. Save it "
            "without interlacing.", str(path))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(mode)
    if channels is None:
        raise export_error("C7E-IMG-002",
                           f"{path.name} uses PNG color type {mode}", str(path))
    if mode == 3 and len(palette) < 3:
        raise export_error("C7E-IMG-002",
                           f"{path.name} is paletted but carries no palette",
                           str(path))

    raw = zlib.decompress(bytes(data))
    stride = width * channels
    if len(raw) < (stride + 1) * height:
        raise export_error("C7E-IMG-001",
                           f"{path.name} ends part way through the image",
                           str(path))

    rgb = bytearray(width * height * 3)
    previous = bytearray(stride)
    at = 0
    for y in range(height):
        method = raw[at]
        at += 1
        line = bytearray(raw[at:at + stride])
        at += stride
        _unfilter(method, line, previous, channels)
        base = y * width * 3
        if mode == 2:
            rgb[base:base + width * 3] = line
        elif mode == 6:
            for x in range(width):
                rgb[base + x * 3:base + x * 3 + 3] = line[x * 4:x * 4 + 3]
        elif mode in (0, 4):
            step = channels
            for x in range(width):
                value = line[x * step]
                rgb[base + x * 3:base + x * 3 + 3] = bytes((value, value, value))
        else:                                   # paletted
            for x in range(width):
                index = line[x] * 3
                rgb[base + x * 3:base + x * 3 + 3] = palette[index:index + 3]
        previous = line
    return width, height, bytes(rgb)


def _unfilter(method: int, line: bytearray, previous: bytearray, channels: int) -> None:
    """PNG's five per-row filters, in place."""
    if method == 0:
        return
    for i in range(len(line)):
        a = line[i - channels] if i >= channels else 0
        b = previous[i]
        c = previous[i - channels] if i >= channels else 0
        if method == 1:
            line[i] = (line[i] + a) & 0xFF
        elif method == 2:
            line[i] = (line[i] + b) & 0xFF
        elif method == 3:
            line[i] = (line[i] + (a + b) // 2) & 0xFF
        elif method == 4:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            line[i] = (line[i] + (a if pa <= pb and pa <= pc
                                  else b if pb <= pc else c)) & 0xFF
        else:
            raise export_error("C7E-IMG-001", f"unknown PNG row filter {method}")


def _bucket(red: int, green: int, blue: int) -> int:
    shift = 8 - _QUANT_BITS
    return (((red >> shift) << (_QUANT_BITS * 2))
            | ((green >> shift) << _QUANT_BITS) | (blue >> shift))


def build_palette(images, colors: int = 256) -> list[tuple[int, int, int]]:
    """A shared palette for a whole animation, by popularity then spread.

    Median cut would be the textbook answer and is not obviously better here:
    an animation's frames share most of their colors, and what matters is that
    ONE palette serves all of them -- FLIC sets the palette on the first frame
    and every later frame is indices into it. So the colors that appear most
    are kept, and the rest map to the nearest of those.

    Counting is done on five-bit buckets rather than exact colors: a gradient
    has tens of thousands of distinct values, almost all of them within one
    step of each other, and counting them individually measures noise.
    """
    counts: dict[int, int] = {}
    for rgb in images:
        # Every seventh pixel. The palette does not change meaningfully with a
        # full count, and a full count of two hundred frames is a minute.
        for at in range(0, len(rgb) - 2, 21):
            key = _bucket(rgb[at], rgb[at + 1], rgb[at + 2])
            counts[key] = counts.get(key, 0) + 1

    ranked = sorted(counts, key=lambda key: -counts[key])[:colors]
    shift = 8 - _QUANT_BITS
    palette = []
    for key in ranked:
        red = (key >> (_QUANT_BITS * 2)) & ((1 << _QUANT_BITS) - 1)
        green = (key >> _QUANT_BITS) & ((1 << _QUANT_BITS) - 1)
        blue = key & ((1 << _QUANT_BITS) - 1)
        # Back to eight bits with the high bits repeated into the low ones, so
        # full-scale stays full-scale: 31 becomes 255, not 248.
        palette.append((((red << shift) | (red >> (_QUANT_BITS - shift))),
                        ((green << shift) | (green >> (_QUANT_BITS - shift))),
                        ((blue << shift) | (blue >> (_QUANT_BITS - shift)))))
    while len(palette) < colors:
        palette.append((0, 0, 0))
    return palette


def build_mapping(palette) -> bytes:
    """Bucket to palette index, once, so quantizing a pixel is a lookup.

    Thirty-two thousand buckets against 256 colors is eight million distance
    comparisons -- done once for the animation rather than once per pixel,
    which would be eight million per frame.
    """
    table = bytearray(_QUANT_SIZE)
    shift = 8 - _QUANT_BITS
    entries = [(r, g, b) for r, g, b in palette]
    for key in range(_QUANT_SIZE):
        red = ((key >> (_QUANT_BITS * 2)) & 31) << shift
        green = ((key >> _QUANT_BITS) & 31) << shift
        blue = (key & 31) << shift
        best = 0
        best_distance = 1 << 30
        for index, (r, g, b) in enumerate(entries):
            # Weighted for the eye's own sensitivity, which is the difference
            # between a sky that bands and one that does not.
            distance = (2 * (r - red) ** 2 + 4 * (g - green) ** 2
                        + 3 * (b - blue) ** 2)
            if distance < best_distance:
                best_distance = distance
                best = index
        table[key] = best
    return bytes(table)


def quantize(rgb: bytes, mapping: bytes) -> bytes:
    """One image's pixels as palette indices."""
    out = bytearray(len(rgb) // 3)
    bucket = _bucket
    for index in range(len(out)):
        at = index * 3
        out[index] = mapping[bucket(rgb[at], rgb[at + 1], rgb[at + 2])]
    return bytes(out)


#: How different a color has to be from the one already on screen before the
#: pixel is changed at all. Weighted squared distance, the same measure the
#: palette search uses; 900 is about a step of ten in one channel.
#:
#: Real footage is noisy, and quantizing each frame independently turns that
#: noise into a different palette index every frame across large flat areas.
#: Measured on a 77-frame clip: a quarter of every frame changed, and three
#: quarters of those changes were to a color indistinguishable from the one
#: already there. That is paid for twice -- in the delta, and in a shimmer
#: across every wall in the picture.
STABILITY = 900


def quantize_stable(rgb: bytes, mapping: bytes, palette, previous: bytes | None,
                    threshold: int = STABILITY) -> bytes:
    """Like `quantize`, but keeps the previous frame's index where it still fits.

    Only where the color it stands for is within `threshold` of the new one --
    so motion, edges and anything that actually changed come through
    untouched, and a wall that is the same wall stays the same byte.
    """
    if previous is None:
        return quantize(rgb, mapping)

    out = bytearray(len(rgb) // 3)
    bucket = _bucket
    entries = list(palette)
    for index in range(len(out)):
        at = index * 3
        red, green, blue = rgb[at], rgb[at + 1], rgb[at + 2]
        was = previous[index]
        r, g, b = entries[was]
        if (2 * (r - red) ** 2 + 4 * (g - green) ** 2
                + 3 * (b - blue) ** 2) <= threshold:
            out[index] = was
            continue
        out[index] = mapping[bucket(red, green, blue)]
    return bytes(out)


__all__ = ["STABILITY", "build_mapping", "build_palette", "quantize",
           "quantize_stable", "read_png"]
