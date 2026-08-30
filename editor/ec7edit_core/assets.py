# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Bounded decoders for Corridor 7's graphics containers.

Every decoder here takes bytes and returns pixels. None of them opens a file,
none writes one, and none keeps a copy: the retail data is the user's, and the
editor's job is to look at it, not to own it. That is also why the cache at the
bottom is in memory and bounded -- an unbounded one would eventually be a copy
of the game on disk, with all the licensing that implies.

Three containers:

* the palette, which lives in `CORR7CD.EXE` rather than in any data file;
* `GFXTILES.CO7`, holding 64x64 wall pages and Wolfenstein column-post sprites;
* the `VGADICT`/`VGAHEAD`/`VGAGRAPH` set, holding Huffman-compressed planar
  pictures.

The decoders are deliberately defensive. This is third-party binary data of
unknown provenance -- a truncated file, a wrong file with the right name, a
sprite whose column posts point outside the page -- and the failure mode has
to be a clear exception, never a silent read past the end of a buffer.
"""

from __future__ import annotations

import struct
import zlib
from collections import OrderedDict
from dataclasses import dataclass

#: The 6-bit VGA DAC palette sits at this offset in the CD executable. There is
#: no copy of it in any .CO7 file, which is why the executable is one of the
#: required game files even though nothing ever runs it.
PALETTE_OFFSET = 0x2FFC0
PALETTE_SIZE = 768

WALL_SIZE = 64
SPRITE_SIZE = 64


class AssetError(ValueError):
    """A container did not decode. Always says which one and why."""


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


def load_palette(executable: bytes) -> list[int]:
    """Expand the embedded 6-bit DAC palette to 8-bit RGB triples.

    The six-bit check is the useful part: it is what tells a real Corridor 7
    executable from a file of the same name that happens to be long enough.
    """
    raw = executable[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE]
    if len(raw) != PALETTE_SIZE:
        raise AssetError(
            f"executable is {len(executable)} bytes; the palette needs "
            f"{PALETTE_OFFSET + PALETTE_SIZE}"
        )
    if any(component > 63 for component in raw):
        raise AssetError("no 6-bit VGA palette at the expected offset")
    # 6 bits to 8 by replicating the top two, which is what the DAC does.
    return [(component << 2) | (component >> 4) for component in raw]


def palette_rgb(palette: list[int], index: int) -> tuple[int, int, int]:
    return palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2]


# ---------------------------------------------------------------------------
# PNG, with nothing but zlib
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytes, *, alpha: bool) -> bytes:
    """Encode raw RGB or RGBA bytes as a PNG.

    Deterministic: fixed filter, fixed compression level, so the same pixels
    give the same file and a thumbnail digest means something.
    """
    channels = 4 if alpha else 3
    stride = width * channels
    if len(pixels) != stride * height:
        raise AssetError(f"{width}x{height} needs {stride * height} bytes, got {len(pixels)}")

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter 0, none
        raw += pixels[y * stride : (y + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# GFXTILES: walls and sprites
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GfxHeader:
    """The chunk directory at the head of GFXTILES.CO7."""

    chunk_count: int
    sprite_start: int
    sound_start: int
    offsets: tuple[int, ...]
    lengths: tuple[int, ...]

    def wall_pages(self) -> range:
        return range(0, self.sprite_start)

    def sprite_pages(self) -> range:
        return range(self.sprite_start, self.sound_start)

    def chunk(self, data: bytes, index: int) -> bytes:
        """One chunk's bytes, bounds-checked against the file."""
        if not 0 <= index < self.chunk_count:
            raise AssetError(f"chunk {index} is outside 0..{self.chunk_count - 1}")
        start, length = self.offsets[index], self.lengths[index]
        if start + length > len(data):
            raise AssetError(
                f"chunk {index} runs 0x{start:x}+{length} past the {len(data)}-byte file"
            )
        return data[start : start + length]


def parse_gfx_header(data: bytes) -> GfxHeader:
    if len(data) < 6:
        raise AssetError(f"GFXTILES is {len(data)} bytes, too short for a header")
    chunk_count, sprite_start, sound_start = struct.unpack_from("<HHH", data)
    directory = 6 + chunk_count * 6
    if chunk_count == 0 or directory > len(data):
        raise AssetError(
            f"GFXTILES declares {chunk_count} chunks, needing {directory} bytes of "
            f"directory in a {len(data)}-byte file"
        )
    if not sprite_start <= sound_start <= chunk_count:
        raise AssetError(
            f"GFXTILES boundaries are out of order: walls|{sprite_start}|"
            f"{sound_start}|{chunk_count}"
        )
    offsets = struct.unpack_from(f"<{chunk_count}I", data, 6)
    lengths = struct.unpack_from(f"<{chunk_count}H", data, 6 + chunk_count * 4)
    return GfxHeader(chunk_count, sprite_start, sound_start, offsets, lengths)


def wall_rgb(page: bytes, palette: list[int]) -> bytes:
    """Decode a 64x64 wall page to row-major RGB.

    Wall pages are stored column-major, which is the transpose everyone forgets
    once and then never again.
    """
    expected = WALL_SIZE * WALL_SIZE
    if len(page) < expected:
        raise AssetError(f"wall page is {len(page)} bytes, needs {expected}")

    out = bytearray(expected * 3)
    for y in range(WALL_SIZE):
        for x in range(WALL_SIZE):
            index = page[x * WALL_SIZE + y] * 3
            destination = (y * WALL_SIZE + x) * 3
            out[destination] = palette[index]
            out[destination + 1] = palette[index + 1]
            out[destination + 2] = palette[index + 2]
    return bytes(out)


def sprite_rgba(page: bytes, palette: list[int]) -> bytes:
    """Decode a Wolfenstein column-post sprite to 64x64 RGBA.

    Sprites are sparse: a left and right column bound, one command offset per
    column in between, and each command a chain of `(end, source, start)`
    triples terminated by a zero end. Everything an untrusted file could lie
    about here is checked, because every one of those values is an index.
    """
    if len(page) < 4:
        raise AssetError(f"sprite page is {len(page)} bytes, too short for its bounds")
    left, right = struct.unpack_from("<HH", page)
    if left > right or right >= SPRITE_SIZE:
        raise AssetError(f"sprite column range {left}..{right} is outside 0..{SPRITE_SIZE - 1}")
    if 4 + (right - left + 1) * 2 > len(page):
        raise AssetError("sprite page is too short for its column table")

    rgba = bytearray(SPRITE_SIZE * SPRITE_SIZE * 4)
    for x in range(left, right + 1):
        command = struct.unpack_from("<H", page, 4 + (x - left) * 2)[0]
        posts = 0
        while True:
            if command + 2 > len(page):
                raise AssetError(f"sprite column {x} post table runs past the page")
            end_word = struct.unpack_from("<H", page, command)[0]
            if end_word == 0:
                break
            if command + 6 > len(page):
                raise AssetError(f"sprite column {x} has a truncated post")
            source = struct.unpack_from("<h", page, command + 2)[0]
            start_word = struct.unpack_from("<H", page, command + 4)[0]
            start, end = start_word >> 1, end_word >> 1
            if start > end or end > SPRITE_SIZE or source + start < 0 or source + end > len(page):
                raise AssetError(f"sprite column {x} post {start}..{end} is out of range")
            for y in range(start, end):
                index = page[source + y] * 3
                destination = (y * SPRITE_SIZE + x) * 4
                rgba[destination] = palette[index]
                rgba[destination + 1] = palette[index + 1]
                rgba[destination + 2] = palette[index + 2]
                rgba[destination + 3] = 255
            command += 6
            posts += 1
            if posts > SPRITE_SIZE:
                raise AssetError(f"sprite column {x} has more posts than it has pixels")
    return bytes(rgba)


def average_color(rgb: bytes) -> tuple[int, int, int]:
    """The mean colour of an RGB buffer, for a palette swatch."""
    count = len(rgb) // 3
    if not count:
        return 0, 0, 0
    return sum(rgb[0::3]) // count, sum(rgb[1::3]) // count, sum(rgb[2::3]) // count


def is_blank(pixels: bytes, *, channels: int) -> bool:
    """True when nothing would be visible: all one colour, or fully transparent."""
    if not pixels:
        return True
    if channels == 4:
        return not any(pixels[3::4])
    return len(set(zip(pixels[0::3], pixels[1::3], pixels[2::3]))) <= 1


# ---------------------------------------------------------------------------
# VGAGRAPH: Huffman-compressed planar pictures
# ---------------------------------------------------------------------------


def _huff_expand(source: bytes, nodes: list[tuple[int, int]], expected: int) -> bytes:
    out = bytearray()
    node = 254
    for value in source:
        for bit in range(8):
            child = nodes[node][(value >> bit) & 1]
            if child < 256:
                out.append(child)
                if len(out) == expected:
                    return bytes(out)
                node = 254
            else:
                node = child - 256
    raise AssetError(f"Huffman chunk ended at {len(out)} of {expected} bytes")


@dataclass(frozen=True)
class VgaPicture:
    """One decoded VGAGRAPH picture, row-major RGB."""

    number: int  # the C7G#### id the engine uses
    width: int
    height: int
    rgb: bytes


def extract_vga(
    vgadict: bytes, vgahead: bytes, vgagraph: bytes, palette: list[int]
) -> list[VgaPicture]:
    """Decode every picture chunk.

    Chunk 0 is PICTABLE (the dimensions), 1 and 2 are fonts, 3 is TILE8, and
    the pictures start at 4 -- so picture *i* is chunk *i+4* and carries the
    engine's id *i+3*. A chunk whose size does not match its declared
    dimensions is skipped rather than guessed at.
    """
    if len(vgadict) < 255 * 4:
        raise AssetError(f"VGADICT is {len(vgadict)} bytes, needs {255 * 4}")
    nodes = list(struct.iter_unpack("<HH", vgadict[: 255 * 4]))
    offsets = [
        int.from_bytes(vgahead[i : i + 3], "little") for i in range(0, len(vgahead) - 2, 3)
    ]

    decoded: list[bytes] = []
    for index, start in enumerate(offsets):
        if start >= len(vgagraph):
            break
        end = offsets[index + 1] if index + 1 < len(offsets) else len(vgagraph)
        if not start + 4 <= end <= len(vgagraph):
            raise AssetError(f"VGAGRAPH chunk {index} spans 0x{start:x}..0x{end:x}")
        expected = struct.unpack_from("<I", vgagraph, start)[0]
        decoded.append(_huff_expand(vgagraph[start + 4 : end], nodes, expected))

    if not decoded:
        raise AssetError("VGAGRAPH decoded to no chunks")

    table = decoded[0]
    dimensions = []
    for width, height in struct.iter_unpack("<HH", table[: len(table) & ~3]):
        if not (0 < width <= 640 and 0 < height <= 480):
            break
        dimensions.append((width, height))

    pictures: list[VgaPicture] = []
    for index in range(min(len(dimensions), max(0, len(decoded) - 4))):
        width, height = dimensions[index]
        data = decoded[index + 4]
        if len(data) != width * height or width % 4:
            continue
        pictures.append(
            VgaPicture(index + 3, width, height, _unplane(data, width, height, palette))
        )
    return pictures


def _unplane(data: bytes, width: int, height: int, palette: list[int]) -> bytes:
    """Undo VGA's four-plane interleave into row-major RGB."""
    plane = width * height // 4
    rgb = bytearray(width * height * 3)
    for y in range(height):
        row = y * (width // 4)
        for x in range(width):
            index = data[(x & 3) * plane + row + (x >> 2)] * 3
            destination = (y * width + x) * 3
            rgb[destination] = palette[index]
            rgb[destination + 1] = palette[index + 1]
            rgb[destination + 2] = palette[index + 2]
    return bytes(rgb)


# ---------------------------------------------------------------------------
# A bounded cache
# ---------------------------------------------------------------------------


class ImageCache:
    """Least-recently-used, bounded by total bytes rather than entry count.

    Entry count is the wrong unit here: a 320x200 picture is fifty times a
    wall page, so a hundred-entry cache is somewhere between 1 and 60 MB
    depending on what the user happened to click. Bytes are what the machine
    actually has.
    """

    def __init__(self, budget_bytes: int = 32 << 20) -> None:
        self.budget = budget_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._size = 0
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def size_bytes(self) -> int:
        return self._size

    def get(self, key: str):
        if key in self._entries:
            self._entries.move_to_end(key)
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        return None

    def put(self, key: str, value: bytes) -> None:
        if key in self._entries:
            self._size -= len(self._entries.pop(key))
        # An item larger than the whole budget is not cached; caching it would
        # evict everything and then itself.
        if len(value) > self.budget:
            return
        self._entries[key] = value
        self._size += len(value)
        while self._size > self.budget:
            _, evicted = self._entries.popitem(last=False)
            self._size -= len(evicted)

    def fetch(self, key: str, produce):
        """Get, or produce and store. The only method callers normally need."""
        found = self.get(key)
        if found is None:
            found = produce()
            self.put(key, found)
        return found

    def clear(self) -> None:
        self._entries.clear()
        self._size = 0
