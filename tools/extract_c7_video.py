#!/usr/bin/env python3
"""Extract the Corridor 7 CD cinematics into the video directory the port reads.

The CD release ships three animations the floppy release does not, and the DOS
installer leaves them on the disc because they were meant to be streamed from
it. So they are in nobody's installed game directory, and the port has to be
pointed at the disc once to get them:

  extract_c7_video.py Corridor7.cue /path/to/game/video
  extract_c7_video.py disc.iso      /path/to/game/video
  extract_c7_video.py /mnt/cdrom    /path/to/game/video

What comes out:

  SEQONE.CO7    90 frames,   6.4 s   Capstone logo
  SEQTHREE.CO7  605 frames, 43.0 s   opening cinematic
  SEQFOUR.CO7   1100 frames, 78.1 s  ending cinematic

They are Autodesk FLIC animations (FLC, 320x200, 8-bit, 71 ms/frame), which is
what the game plays them as -- nothing is transcoded here, the files are copied
out byte for byte and verified.

Only the standard library is used. A .cue/.bin pair is MODE1/2352, so each
2352-byte sector carries a 16-byte sync and header, 2048 bytes of data, and 288
bytes of error correction; this strips that itself rather than needing bchunk,
and walks ISO9660 itself rather than needing isoinfo (which can list this
particular disc but declines to extract from it).
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

# The three sequence files, in the order the executable's own name table lists
# them at offset 247109.
WANTED = ("SEQONE.CO7", "SEQTHREE.CO7", "SEQFOUR.CO7")

FLC_MAGIC = 0xAF12
FLI_MAGIC = 0xAF11

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c7disc import GameSource, DiscError   # noqa: E402  (after the path fix)


# ---------------------------------------------------------------------------
# Checking what came out
# ---------------------------------------------------------------------------

def describe_flic(blob: bytes, name: str) -> str:
    """Raise unless this really is one of the game's animations."""
    if len(blob) < 128:
        raise DiscError(f"{name}: too short to be a FLIC ({len(blob)} bytes)")

    size, magic, frames, width, height, depth, flags = struct.unpack_from("<IHHHHHH", blob, 0)
    speed = struct.unpack_from("<I", blob, 16)[0]

    if magic not in (FLC_MAGIC, FLI_MAGIC):
        raise DiscError(f"{name}: not a FLIC (magic 0x{magic:04X})")
    # The header's own size field against the real length is the cheapest
    # integrity check there is, and the one that catches a short read off a
    # scratched disc -- which would otherwise play half way and stop.
    if size != len(blob):
        raise DiscError(f"{name}: header says {size} bytes, file is {len(blob)}")
    if (width, height, depth) != (320, 200, 8):
        raise DiscError(f"{name}: expected 320x200x8, got {width}x{height}x{depth}")
    if frames == 0 or speed == 0:
        raise DiscError(f"{name}: {frames} frames at {speed} ms")

    seconds = frames * speed / 1000.0
    return f"{frames} frames, {width}x{height}, {speed} ms/frame -> {seconds:.1f} s"


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract the Corridor 7 CD cinematics.")
    parser.add_argument("source", type=Path,
                        help="a .cue, a .iso, or a mounted CD directory")
    parser.add_argument("dest", type=Path,
                        help="the video/ directory beside your game data")
    args = parser.parse_args()

    args.dest.mkdir(parents=True, exist_ok=True)

    blobs: dict[str, bytes] = {}
    try:
        with GameSource.open(args.source) as source:
            available = source.list()
            for name in WANTED:
                if name in available:
                    blobs[name] = source.read(name)
    except DiscError as error:
        print(f"{args.source}: {error}", file=sys.stderr)
        return 1

    if not blobs:
        print(f"No cinematics found in {args.source}.", file=sys.stderr)
        print("Expected SEQONE.CO7, SEQTHREE.CO7 and SEQFOUR.CO7 in /CORR7CD.",
              file=sys.stderr)
        return 1

    failures = 0
    for name in WANTED:
        if name not in blobs:
            print(f"  {name:<13} MISSING")
            failures += 1
            continue
        try:
            summary = describe_flic(blobs[name], name)
        except DiscError as error:
            print(f"  {name:<13} REJECTED -- {error}", file=sys.stderr)
            failures += 1
            continue
        out = args.dest / name
        out.write_bytes(blobs[name])
        print(f"  {name:<13} {summary}")

    if failures:
        print(f"\n{failures} of {len(WANTED)} cinematics could not be written.",
              file=sys.stderr)
        return 1

    print(f"\nWrote {len(WANTED)} cinematics to {args.dest}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
