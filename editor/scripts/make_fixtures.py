#!/usr/bin/env python3
"""Generate the synthetic binaries EC7Edit's tests are allowed to use.

Milestone E0 of docs/corridor7-level-editor.md.

Every byte these produce is computed here, from constants written here. None of
it is derived from Corridor 7 -- not a wall index, not a palette entry, not a
map name. That is the whole point: the editor has to exercise its binary
boundaries in CI, on machines that have no right to the commercial data, and a
fixture cut from a retail archive could not be committed.

Being synthetic is not a claim to be taken on trust, so it is made checkable:

  * plane words are drawn from a band (0xE000+) that the game's own data never
    uses, so a retail word cannot be mistaken for one of ours;
  * every archive carries the marker name "SYNTH" and a generator tag;
  * `verify` re-runs the generators and compares digests, so a fixture edited
    by hand -- or replaced with real data -- stops the gate.

Determinism matters as much as provenance: the same call produces the same
bytes on every platform, so a digest is a stable contract rather than a
snapshot of one machine's luck. There is no randomness here at all, seeded or
otherwise.

Usage:
  make_fixtures.py write DIR     write the fixture set
  make_fixtures.py digests       print name and sha256 of each, without writing
  make_fixtures.py verify DIR    re-generate and compare against what is there
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

# --- the native contracts, restated here on purpose ------------------------
#
# E1 implements the production codec. These constants are duplicated rather
# than imported so that a fixture cannot drift silently with the code under
# test: if E1 changes a constant, this file has to change too, visibly, in the
# same review.
TED5_SIGNATURE = b"TED5v1.0.\x00\x00\x00"
MAP_MARKER = b"!ID!"
RLEW_TAG = 0xABCD
NAME_FIELD = 16

# Plane words are taken from here upward. Corridor 7's planes hold small
# numbers -- tile and object indices in the hundreds -- so nothing in this band
# can be confused for game data, by a reader or by an auditor.
SYNTH_BASE = 0xE000


def rlew_compress(words: list[int]) -> bytes:
    """A legal RLEW encoding: runs of three or more, never a bare literal tag.

    Deliberately not the production writer's encoding. E1 measured the retail
    archive and found its encoder never emits a run shorter than four, so
    `ec7edit_core.rlew` matches that instead. Keeping this generator at three
    means the fixtures exercise a legal encoding the production writer would
    not itself produce, which is what makes reading them a real test of the
    decoder rather than a round trip through one shared assumption.
    """
    out = bytearray()
    i = 0
    while i < len(words):
        value = words[i]
        run = 1
        while i + run < len(words) and words[i + run] == value:
            run += 1
        # A literal equal to the tag must use the triple form whatever its run
        # length, or a reader cannot tell it from the start of one.
        if run >= 3 or value == RLEW_TAG:
            out += struct.pack("<HHH", RLEW_TAG, run, value)
            i += run
        else:
            out += struct.pack("<H", value)
            i += 1
    return bytes(out)


def plane_stream(words: list[int]) -> bytes:
    """A stored plane: expanded byte count, then the compressed word stream."""
    return struct.pack("<H", len(words) * 2) + rlew_compress(words)


def synth_plane(width: int, height: int, salt: int) -> list[int]:
    """A reproducible, obviously-synthetic plane with runs and singletons.

    The pattern deliberately contains both -- long runs down the border and
    varying interior values -- so a codec that mishandles either is caught.
    """
    words = []
    for y in range(height):
        for x in range(width):
            if x == 0 or y == 0 or x == width - 1 or y == height - 1:
                words.append(SYNTH_BASE)                  # a long border run
            else:
                words.append(SYNTH_BASE + 1 + ((x * 7 + y * 13 + salt) % 32))
    return words


def build_archive(maps: list[tuple[str, int, int]], *,
                  final_marker: bool = True) -> bytes:
    """A complete native archive.

    maps: (name, width, height).

    The layout, read off the working implementation and restated rather than
    imported (see the note on constants above):

      first record, 46 bytes
        0   12  TED5v1.0.\0\0\0
        12   8  absolute offsets of planes 1 and 2 -- plane 0's is implicit,
                the stream beginning immediately after this header
        20   6  three compressed plane lengths
        26   4  width, height
        30  16  name

      later record, 42 bytes
        0    4  !ID!
        4   12  absolute offsets of all three planes
        16   6  three compressed plane lengths
        22   4  width, height
        26  16  name

    Each header is followed immediately by its own three plane streams, and the
    archive ends with a bare !ID!.
    """
    out = bytearray()
    for index, (name, width, height) in enumerate(maps):
        streams = [plane_stream(synth_plane(width, height, p + index * 3))
                   for p in range(3)]
        header_offset = len(out)
        header_size = 46 if index == 0 else 42
        out += b"\x00" * header_size

        offsets = []
        for s in streams:
            offsets.append(len(out))
            out += s

        raw = name.encode("ascii")[:NAME_FIELD - 1].ljust(NAME_FIELD, b"\x00")
        if index == 0:
            out[header_offset:header_offset + 12] = TED5_SIGNATURE
            struct.pack_into("<II", out, header_offset + 12,
                             offsets[1], offsets[2])
            struct.pack_into("<HHH", out, header_offset + 20,
                             *(len(s) for s in streams))
            struct.pack_into("<HH", out, header_offset + 26, width, height)
            out[header_offset + 30:header_offset + 46] = raw
        else:
            out[header_offset:header_offset + 4] = MAP_MARKER
            struct.pack_into("<III", out, header_offset + 4, *offsets)
            struct.pack_into("<HHH", out, header_offset + 16,
                             *(len(s) for s in streams))
            struct.pack_into("<HH", out, header_offset + 22, width, height)
            out[header_offset + 26:header_offset + 42] = raw
    if final_marker:
        out += MAP_MARKER
    return bytes(out)


def build_planes_lump(width: int, height: int, salt: int,
                     name: str = "SYNTHPLANES") -> bytes:
    """A complete WDC3.1 PLANES lump: 34-byte header, then three word planes.

    Restated from the engine's own writer and reader rather than imported, so
    that checking the production codec against this is a comparison of two
    implementations instead of a round trip through one:

      00  char[6]  WDC3.1
      06  u32      map count
      10  u16      plane count
      12  u16      name length
      14  char[16] name
      30  u16      width
      32  u16      height
      34  ...      three uncompressed planes of width*height u16

    E1 corrected this: it used to emit the payload alone, so the WAD fixture
    built from it held a PLANES lump the engine could not have loaded.
    """
    out = bytearray(34)
    out[0:6] = b"WDC3.1"
    struct.pack_into("<I", out, 6, 1)
    struct.pack_into("<HH", out, 10, 3, NAME_FIELD)
    out[14:14 + NAME_FIELD] = name.encode("ascii")[:NAME_FIELD - 1].ljust(NAME_FIELD, b"\x00")
    struct.pack_into("<HH", out, 30, width, height)
    for p in range(3):
        for word in synth_plane(width, height, salt + p):
            out += struct.pack("<H", word)
    return bytes(out)


def build_wad(lumps: list[tuple[str, bytes]]) -> bytes:
    """A minimal PWAD. Deterministic directory order, no padding."""
    out = bytearray(b"PWAD" + struct.pack("<II", len(lumps), 0))
    entries = []
    for name, data in lumps:
        entries.append((len(out), len(data), name))
        out += data
    directory = len(out)
    for offset, size, name in entries:
        out += struct.pack("<II", offset, size)
        out += name.encode("ascii")[:8].ljust(8, b"\x00")
    struct.pack_into("<II", out, 4, len(lumps), directory)
    return bytes(out)


def build_indexed_image(width: int, height: int) -> bytes:
    """An indexed bitmap and its 256-entry palette, drawn by arithmetic.

    Not a game graphic and not a photograph of one: a gradient and a diagonal,
    which is enough to prove a decoder's stride, bounds and palette lookup.
    """
    palette = bytearray()
    for i in range(256):
        palette += bytes(((i * 7) % 64, (i * 11) % 64, (i * 13) % 64))
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.append((x + y) % 256 if x != y else 255)
    return bytes(struct.pack("<HH", width, height) + palette + pixels)


def build_palette_executable() -> bytes:
    """A stand-in for CORR7CD.EXE carrying a synthetic 6-bit palette.

    Only the palette window matters, so the rest is a recognizable filler
    rather than anything resembling an executable. The values stay inside
    0..63 because that six-bit range is exactly what the loader checks to tell
    a real Corridor 7 executable from a file of the right length.
    """
    PALETTE_OFFSET, PALETTE_SIZE = 0x2FFC0, 768
    out = bytearray(b"SYNTHETIC-NOT-AN-EXECUTABLE\x00" * 1000)
    out = out[:PALETTE_OFFSET].ljust(PALETTE_OFFSET, b"\x00")
    # A deterministic ramp: entry i is (i/4, i/8, i/16) clipped into 0..63.
    for index in range(256):
        out += bytes(((index // 4) & 63, (index // 8) & 63, (index // 16) & 63))
    return bytes(out)


def build_wall_page(salt: int = 0) -> bytes:
    """A 64x64 wall page, column-major, as GFXTILES stores them."""
    return bytes(((x * 3 + y * 5 + salt) & 0xFF) for x in range(64) for y in range(64))


def build_sprite_page(left: int = 20, right: int = 43) -> bytes:
    """A Wolfenstein column-post sprite: one post per column, all opaque.

    Built to the format rather than copied from one, so a decoder that agrees
    with it agrees with the documented layout and not with a captured sample.
    """
    columns = right - left + 1
    top, bottom = 16, 48
    height = bottom - top
    # Layout: bounds, column offsets, then per column a (end, source, start)
    # triple, a terminating zero, and the column's pixels.
    header = 4 + columns * 2
    per_column = 6 + 2 + height
    body = bytearray()
    offsets = []
    for index in range(columns):
        base = header + index * per_column
        offsets.append(base)
        pixels_at = base + 8
        # `source` is the offset the decoder adds `y` to, so it is biased by
        # the post's own starting row.
        body += struct.pack("<HhH", bottom * 2, pixels_at - top, top * 2)
        body += struct.pack("<H", 0)
        body += bytes(((index * 7 + y) & 0xFF) or 1 for y in range(height))
    out = bytearray(struct.pack("<HH", left, right))
    for offset in offsets:
        out += struct.pack("<H", offset)
    return bytes(out + body)


def build_project(name: str) -> bytes:
    """A versioned project file over synthetic planes."""
    document = {
        "schema": 1,
        "generator": "ec7edit-fixtures",
        "synthetic": True,
        "name": name,
        "maps": [{
            "slot": 1,
            "name": "SYNTH01",
            "width": 8,
            "height": 8,
            "planes": [synth_plane(8, 8, p) for p in range(3)],
        }],
    }
    return json.dumps(document, indent=2, sort_keys=True).encode("ascii") + b"\n"


def malformed() -> dict[str, bytes]:
    """Inputs a strict reader must refuse, each wrong in exactly one way."""
    good = build_archive([("SYNTH01", 8, 8)])
    cases: dict[str, bytes] = {}
    cases["empty.bin"] = b""
    cases["marker-only.bin"] = MAP_MARKER
    cases["truncated-signature.bin"] = TED5_SIGNATURE[:6]
    cases["bad-signature.bin"] = b"TED4v1.0.\x00\x00\x00" + good[12:]
    # Dimensions past the loader's 181 limit. Offset 26 in the first record:
    # 12 signature + 8 offsets + 6 lengths. Written at 30 first time round,
    # which is the name field -- the fixture was malformed in a way it did not
    # claim, and the parser was right to accept it.
    over = bytearray(good)
    struct.pack_into("<HH", over, 26, 200, 200)
    cases["oversize-dimensions.bin"] = bytes(over)
    # A plane offset pointing inside its own header.
    inside = bytearray(good)
    struct.pack_into("<I", inside, 12, 4)
    cases["plane-offset-in-header.bin"] = bytes(inside)
    # Truncated mid-plane: the header still declares plane 2's full length,
    # but the file stops inside it. Everything after the cut goes with it,
    # terminator included, because that is what truncation means.
    plane2_offset, plane2_length = struct.unpack_from("<IH", good, 16)[0], struct.unpack_from("<H", good, 24)[0]
    cases["truncated-plane.bin"] = good[:plane2_offset + plane2_length // 2]
    # A run count that overruns the declared expansion, edited inside plane 0's
    # stream so the archive's structure stays intact and the decoder is what
    # refuses it. 4x4 expands to 32 bytes; 0xFFFF words is far past that.
    small = build_archive([("SYNTH01", 4, 4)])
    overrun = bytearray(small)
    stream_at = 46 + 2  # first record header, then the stream's size prefix
    struct.pack_into("<HHH", overrun, stream_at, RLEW_TAG, 0xFFFF, SYNTH_BASE)
    cases["rlew-overrun.bin"] = bytes(overrun)
    # A later record whose plane 0 begins inside its own 42-byte header. Only
    # a later record can express this fault: the first record's plane 0 offset
    # is implicit, so there is no field to corrupt.
    two = bytearray(build_archive([("SYNTH01", 4, 4), ("SYNTH02", 4, 4)]))
    second = two.index(MAP_MARKER, 46)
    struct.pack_into("<I", two, second + 4, second + 8)
    cases["plane0-inside-header.bin"] = bytes(two)
    # A stream whose declared expanded size disagrees with the header's
    # dimensions. Neither is corrupt on its own; together they cannot both be
    # right, and a reader that trusts either one silently loads the wrong map.
    mismatch = bytearray(good)
    struct.pack_into("<H", mismatch, 46, 8 * 8 * 2 - 2)
    cases["plane-size-mismatch.bin"] = bytes(mismatch)
    # Bytes after the terminator. The engine only reads a terminator when
    # exactly four bytes remain, so this is trailing data, not an end.
    cases["trailing-garbage.bin"] = good + b"\x00\x00"
    return cases


def fixture_set() -> dict[str, bytes]:
    """Every fixture, by relative path. The single source of truth."""
    out: dict[str, bytes] = {}
    out["archive/one-map.c7map"] = build_archive([("SYNTH01", 8, 8)])
    out["archive/three-maps.c7map"] = build_archive(
        [("SYNTH01", 8, 8), ("SYNTH02", 16, 16), ("SYNTH03", 64, 64)])
    out["archive/no-final-marker.c7map"] = build_archive(
        [("SYNTH01", 8, 8)], final_marker=False)
    out["wad/one-map.wad"] = build_wad([
        ("MAP01", b""),
        ("PLANES", build_planes_lump(8, 8, 0)),
    ])
    out["planes/8x8.planes"] = build_planes_lump(8, 8, 0)
    out["image/gradient.idx"] = build_indexed_image(32, 32)
    out["assets/palette.exe"] = build_palette_executable()
    out["assets/wall.page"] = build_wall_page()
    out["assets/wall-alt.page"] = build_wall_page(salt=91)
    out["assets/sprite.page"] = build_sprite_page()
    out["project/minimal.ec7proj"] = build_project("Synthetic Project")
    for name, blob in malformed().items():
        out[f"malformed/{name}"] = blob
    return out


def digests() -> dict[str, str]:
    return {name: hashlib.sha256(blob).hexdigest()
            for name, blob in sorted(fixture_set().items())}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-4], file=sys.stderr)
        return 2
    action = sys.argv[1]

    if action == "digests":
        for name, digest in digests().items():
            print(f"{digest}  {name}")
        return 0

    if action not in ("write", "verify") or len(sys.argv) != 3:
        print(f"usage: {Path(sys.argv[0]).name} write|verify DIR", file=sys.stderr)
        print(f"       {Path(sys.argv[0]).name} digests", file=sys.stderr)
        return 2
    root = Path(sys.argv[2])

    if action == "write":
        for name, blob in sorted(fixture_set().items()):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        print(f"wrote {len(fixture_set())} fixtures to {root}")
        return 0

    bad = 0
    for name, blob in sorted(fixture_set().items()):
        target = root / name
        if not target.is_file():
            print(f"MISSING  {name}")
            bad += 1
        elif target.read_bytes() != blob:
            print(f"CHANGED  {name}")
            bad += 1
    if bad:
        print(f"\n{bad} fixture(s) do not match the generator. Regenerate with "
              f"'write', and if that was not expected, find out why.")
        return 1
    print(f"all {len(fixture_set())} fixtures match the generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
