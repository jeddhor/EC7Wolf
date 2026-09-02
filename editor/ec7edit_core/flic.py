# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Writing Autodesk FLIC, so a campaign can have a cinematic of its own.

The engine already decodes FLIC and has done since the CD's three animations
were found still sitting on the disc. Teaching it a modern container instead
would mean bundling a video decoder -- its dependencies, its licences, its
attack surface -- to play fifteen seconds of animation. FLIC is 8-bit
paletted, which is what this game is; the sensible half to build is the one
that writes it, and that belongs in the editor.

So: frames in, `.CO7` out, in the standard library alone. A modern video
becomes frames with one ffmpeg command, or the editor takes a folder of PNGs.

**The format, as this game's decoder reads it** (`src/c7_flic.cpp`, which is
the authority here rather than any specification -- a file this writes has to
play in EC7Wolf, not in the abstract):

    header      128 bytes: size, magic 0xAF12, frame count, 320x200x8,
                milliseconds per frame, and the offset of the first frame
    frame       16 bytes: size, magic 0xF1FA, how many chunks follow
    chunk       6 bytes: size, type, then the payload

Three chunk types are written and no others:

* **COLOR256** (4) -- the palette, whole, on the first frame. 0..255 per
  channel, unlike COLOR64's DAC range.
* **BRUN** (15) -- a whole frame, run-length encoded per row. `count >= 0`
  means that many copies of the byte that follows; `count < 0` means -count
  literal bytes. Note which way round that is: it is the opposite of the same
  encoding in several other formats, and getting it backwards produces a file
  that decodes to noise rather than failing.
* **LC** (12) -- a run of changed lines, for every frame after the first.
  Between two frames of an animation most rows are identical, and sending
  only the band that moved is the difference between a cinematic somebody can
  download and one they cannot.

The vestigial per-row packet count in BRUN is written as zero. It cannot
express more than 255 packets and a 320-pixel row can need more, so this
game's decoder ignores it, as every real player does.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .errors import export_error

WIDTH = 320
HEIGHT = 200
PIXELS = WIDTH * HEIGHT

FLC_MAGIC = 0xAF12
FRAME_MAGIC = 0xF1FA
HEADER_BYTES = 128
FRAME_HEADER_BYTES = 16
CHUNK_HEADER_BYTES = 6

COLOR256 = 4
LC = 12
BRUN = 15

#: The CD's own animations run at this, and it is what the engine falls back
#: to when a file says zero.
DEFAULT_SPEED_MS = 71

#: A cinematic is an animation, not a feature film. The ceiling is here so a
#: mistake -- a folder of ten thousand frames -- is a diagnostic rather than a
#: machine that stops responding.
MAX_FRAMES = 3000


@dataclass(frozen=True)
class Frame:
    """One frame: 320x200 palette indices, row-major."""

    pixels: bytes

    def __post_init__(self) -> None:
        if len(self.pixels) != PIXELS:
            raise export_error(
                "C7E-FLIC-001",
                f"a frame is {WIDTH}x{HEIGHT} = {PIXELS} bytes, not "
                f"{len(self.pixels)}")


def encode_brun(pixels: bytes) -> bytes:
    """A whole frame, run-length encoded per row."""
    out = bytearray()
    for y in range(HEIGHT):
        row = pixels[y * WIDTH:(y + 1) * WIDTH]
        out.append(0)                      # the vestigial packet count
        out.extend(_pack_row(row))
    return bytes(out)


def _pack_row(row: bytes) -> bytes:
    """One row as BRUN packets: positive is a run, negative is literals."""
    out = bytearray()
    x = 0
    while x < len(row):
        value = row[x]
        run = 1
        while x + run < len(row) and row[x + run] == value and run < 127:
            run += 1
        if run >= 2:
            out.append(run)
            out.append(value)
            x += run
            continue
        # Literals, up to 127, stopping early where a run worth encoding
        # begins -- three of the same byte pays for its own packet.
        start = x
        while x < len(row) and x - start < 127:
            if (x + 2 < len(row) and row[x] == row[x + 1] == row[x + 2]):
                break
            x += 1
        count = x - start
        out.append((256 - count) & 0xFF)   # negative, as a signed byte
        out.extend(row[start:x])
    return bytes(out)


def encode_lc(previous: bytes, pixels: bytes) -> bytes | None:
    """Only the band of rows that changed, or None if nothing did.

    LC addresses one contiguous run of lines, so the first and last changed
    rows bound it. A frame where the top and the bottom both move but the
    middle does not still sends the middle -- which is correct, just not
    minimal, and far simpler than the alternative.
    """
    first = None
    last = None
    for y in range(HEIGHT):
        begin = y * WIDTH
        if previous[begin:begin + WIDTH] != pixels[begin:begin + WIDTH]:
            first = y if first is None else first
            last = y
    if first is None:
        return None

    out = bytearray(struct.pack("<HH", first, last - first + 1))
    for y in range(first, last + 1):
        begin = y * WIDTH
        packets = _pack_lc_row(previous[begin:begin + WIDTH],
                               pixels[begin:begin + WIDTH])
        if len(packets) > 255:
            # More packets than the count byte can hold. The row goes whole
            # instead, as literals, which always fits in a handful.
            row = pixels[begin:begin + WIDTH]
            packets = [(0, "lit", row[i:i + 127])
                       for i in range(0, WIDTH, 127)]
            for index in range(1, len(packets)):
                packets[index] = (0, "lit", packets[index][2])
        out.append(len(packets))
        for skip, kind, payload in packets:
            out.append(skip)
            if kind == "lit":
                out.append(len(payload))            # positive: literals follow
                out.extend(payload)
            else:
                count, value = payload
                out.append((256 - count) & 0xFF)    # negative: a run
                out.append(value)
    return bytes(out)


def _pack_lc_row(before: bytes, after: bytes):
    """Skip/replace packets for one row, against what was there before.

    **LC's sign convention is the opposite of BRUN's.** Here a positive count
    means that many literal bytes follow and a negative one means a run --
    exactly inverted from the whole-frame encoding in the same file. Writing
    BRUN's convention here produces a file that decodes to noise rather than
    failing, and every frame after the first is wrong while the first looks
    perfect. Which is precisely what happened.
    """
    packets = []
    x = 0
    pending = 0                            # unchanged bytes waiting to be skipped
    while x < WIDTH:
        if before[x] == after[x]:
            pending += 1
            x += 1
            if pending == 255:
                # A skip byte cannot exceed 255, so the run is broken with an
                # empty literal packet rather than losing the position.
                packets.append((255, "lit", b""))
                pending = 0
            continue

        start = x
        while x < WIDTH and before[x] != after[x]:
            x += 1
        span = after[start:x]

        # Inside a changed span, a run of four or more of one byte is cheaper
        # as a run packet -- two bytes against however many it repeats.
        at = 0
        skip = pending
        pending = 0
        while at < len(span):
            value = span[at]
            run = 1
            while at + run < len(span) and span[at + run] == value and run < 127:
                run += 1
            if run >= 4:
                packets.append((skip, "run", (run, value)))
                skip = 0
                at += run
                continue
            begin = at
            while at < len(span) and at - begin < 127:
                if (at + 3 < len(span)
                        and span[at] == span[at + 1] == span[at + 2] == span[at + 3]):
                    break
                at += 1
            packets.append((skip, "lit", span[begin:at]))
            skip = 0
    return packets


def encode_palette(palette) -> bytes:
    """The whole palette as one COLOR256 packet."""
    if len(palette) != 256:
        raise export_error("C7E-FLIC-002",
                           f"a palette is 256 colors, not {len(palette)}")
    out = bytearray(struct.pack("<H", 1))  # one packet
    out.append(0)                          # skipping nothing
    out.append(0)                          # 0 means 256
    for red, green, blue in palette:
        out.extend((red & 0xFF, green & 0xFF, blue & 0xFF))
    return bytes(out)


def _chunk(kind: int, payload: bytes) -> bytes:
    return struct.pack("<IH", len(payload) + CHUNK_HEADER_BYTES, kind) + payload


def encode(frames, palette, *, speed_ms: int = DEFAULT_SPEED_MS) -> bytes:
    """A complete FLC file: header, frames, and the palette on the first."""
    frames = list(frames)
    if not frames:
        raise export_error("C7E-FLIC-003", "an animation needs at least one frame")
    if len(frames) > MAX_FRAMES:
        raise export_error("C7E-FLIC-003",
                           f"{len(frames)} frames; the limit is {MAX_FRAMES}")
    if not 1 <= speed_ms <= 60000:
        raise export_error("C7E-FLIC-003",
                           f"{speed_ms} ms a frame is outside 1..60000")

    body = bytearray()
    offsets = []
    previous = None
    for index, frame in enumerate(frames):
        chunks = []
        if index == 0:
            chunks.append(_chunk(COLOR256, encode_palette(palette)))
            chunks.append(_chunk(BRUN, encode_brun(frame.pixels)))
        else:
            delta = encode_lc(previous, frame.pixels)
            if delta is None:
                pass                       # identical frame: no chunks at all
            elif len(delta) < PIXELS // 2:
                chunks.append(_chunk(LC, delta))
            else:
                chunks.append(_chunk(BRUN, encode_brun(frame.pixels)))
        payload = b"".join(chunks)
        offsets.append(HEADER_BYTES + len(body))
        body.extend(struct.pack("<IHH", len(payload) + FRAME_HEADER_BYTES,
                                FRAME_MAGIC, len(chunks)))
        body.extend(b"\0" * 8)
        body.extend(payload)
        previous = frame.pixels

    header = bytearray(HEADER_BYTES)
    struct.pack_into("<IHHHHHH", header, 0,
                     HEADER_BYTES + len(body), FLC_MAGIC, len(frames),
                     WIDTH, HEIGHT, 8, 3)
    struct.pack_into("<I", header, 16, speed_ms)
    struct.pack_into("<I", header, 80, offsets[0])
    struct.pack_into("<I", header, 84, offsets[1] if len(offsets) > 1 else offsets[0])
    return bytes(header) + bytes(body)


__all__ = ["BRUN", "COLOR256", "DEFAULT_SPEED_MS", "Frame", "HEIGHT", "LC",
           "MAX_FRAMES", "PIXELS", "WIDTH", "encode", "encode_brun",
           "encode_lc", "encode_palette"]
