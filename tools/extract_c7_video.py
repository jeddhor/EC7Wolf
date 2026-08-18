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

RAW_SECTOR = 2352
DATA_SECTOR = 2048
MODE1_HEADER = 16
FRAMES_PER_SECOND = 75

# The three sequence files, in the order the executable's own name table lists
# them at offset 247109.
WANTED = ("SEQONE.CO7", "SEQTHREE.CO7", "SEQFOUR.CO7")

FLC_MAGIC = 0xAF12
FLI_MAGIC = 0xAF11


class DiscError(Exception):
    pass


# ---------------------------------------------------------------------------
# Getting at the filesystem
# ---------------------------------------------------------------------------

def parse_msf(text: str) -> int:
    minutes, seconds, frames = (int(part) for part in text.split(":"))
    return (minutes * 60 + seconds) * FRAMES_PER_SECOND + frames


def data_track_from_cue(cue_path: Path) -> tuple[Path, int, int, bool]:
    """-> (bin path, first sector, sector count, raw 2352-byte sectors)

    The data track is track 1 on every Corridor 7 pressing seen, but this reads
    it out of the sheet rather than assuming, and takes the next track's start
    as the end so the audio tracks are never fed to the ISO parser.
    """
    text = cue_path.read_text(errors="replace")

    file_match = re.search(r'FILE\s+"([^"]+)"', text)
    if not file_match:
        raise DiscError(f"{cue_path}: no FILE line")
    binary = cue_path.parent / file_match.group(1)
    if not binary.exists():
        raise DiscError(f"{cue_path} names {file_match.group(1)}, which is not beside it")

    tracks = []
    for match in re.finditer(
        r"TRACK\s+(\d+)\s+(\S+)(.*?)(?=TRACK\s+\d+|\Z)", text, re.S):
        number, mode, body = int(match.group(1)), match.group(2), match.group(3)
        index = re.search(r"INDEX\s+01\s+(\d+:\d+:\d+)", body)
        pregap = re.search(r"PREGAP\s+(\d+:\d+:\d+)", body)
        if not index:
            continue
        start = parse_msf(index.group(1))
        # A PREGAP is not present in the file, so everything after it sits that
        # much earlier in the image than its INDEX says.
        tracks.append({"n": number, "mode": mode, "start": start,
                       "pregap": parse_msf(pregap.group(1)) if pregap else 0})

    data = [t for t in tracks if t["mode"].startswith("MODE")]
    if not data:
        raise DiscError(f"{cue_path}: no data track")
    track = data[0]

    later = [t for t in tracks if t["start"] > track["start"]]
    end = min(t["start"] - t["pregap"] for t in later) if later else None
    if end is None:
        end = binary.stat().st_size // RAW_SECTOR

    raw = track["mode"].endswith("/2352")
    return binary, track["start"], end - track["start"], raw


class SectorSource:
    """Reads 2048-byte logical sectors, whatever the container is."""

    def __init__(self, path: Path, first: int = 0, count: int | None = None,
                 raw: bool = False):
        self.file = path.open("rb")
        self.first = first
        self.raw = raw
        size = path.stat().st_size
        step = RAW_SECTOR if raw else DATA_SECTOR
        self.count = count if count is not None else size // step

    def read(self, lba: int, sectors: int = 1) -> bytes:
        if lba < 0 or lba + sectors > self.count:
            raise DiscError(f"sector {lba}+{sectors} is outside the track")
        if not self.raw:
            self.file.seek((self.first + lba) * DATA_SECTOR)
            return self.file.read(DATA_SECTOR * sectors)
        out = bytearray()
        for i in range(sectors):
            self.file.seek((self.first + lba + i) * RAW_SECTOR + MODE1_HEADER)
            out += self.file.read(DATA_SECTOR)
        return bytes(out)

    def close(self):
        self.file.close()


def iso_find_files(src: SectorSource, wanted: set[str]) -> dict[str, tuple[int, int]]:
    """-> {NAME: (lba, length)} by walking ISO9660 from the root directory.

    Deliberately small: this reads the Primary Volume Descriptor, then walks
    directories breadth-first, and understands only what a 1994 ISO9660 level-1
    disc uses. No Joliet, no Rock Ridge, no extents past 4 GB.
    """
    pvd = None
    for sector in range(16, 32):
        block = src.read(sector)
        if block[1:6] != b"CD001":
            continue
        if block[0] == 1:
            pvd = block
            break
        if block[0] == 255:
            break
    if pvd is None:
        raise DiscError("no ISO9660 primary volume descriptor")

    # The root directory record sits at offset 156 of the PVD.
    root = pvd[156:156 + 34]
    root_lba = struct.unpack("<I", root[2:6])[0]
    root_len = struct.unpack("<I", root[10:14])[0]

    found: dict[str, tuple[int, int]] = {}
    queue = [(root_lba, root_len)]
    seen = set()

    while queue:
        lba, length = queue.pop(0)
        if (lba, length) in seen:
            continue
        seen.add((lba, length))

        sectors = (length + DATA_SECTOR - 1) // DATA_SECTOR
        data = src.read(lba, sectors)

        offset = 0
        while offset < len(data):
            record_len = data[offset]
            if record_len == 0:
                # Records never straddle a sector; skip to the next one.
                offset = (offset // DATA_SECTOR + 1) * DATA_SECTOR
                if offset >= len(data):
                    break
                continue
            record = data[offset:offset + record_len]
            child_lba = struct.unpack("<I", record[2:6])[0]
            child_len = struct.unpack("<I", record[10:14])[0]
            flags = record[25]
            name_len = record[32]
            name = record[33:33 + name_len].decode("ascii", "replace")

            if flags & 0x02:                      # directory
                if name not in ("\x00", "\x01"):  # . and ..
                    queue.append((child_lba, child_len))
            else:
                bare = name.split(";")[0].upper()
                if bare in wanted:
                    found[bare] = (child_lba, child_len)

            offset += record_len

    return found


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

    if args.source.is_dir():
        for name in WANTED:
            for candidate in (args.source, args.source / "CORR7CD"):
                for spelling in (name, name.lower()):
                    path = candidate / spelling
                    if path.is_file():
                        blobs[name] = path.read_bytes()
                        break
                if name in blobs:
                    break
    else:
        suffix = args.source.suffix.lower()
        if suffix == ".cue":
            binary, first, count, raw = data_track_from_cue(args.source)
            src = SectorSource(binary, first, count, raw)
        else:
            src = SectorSource(args.source)
        try:
            located = iso_find_files(src, set(WANTED))
            for name, (lba, length) in located.items():
                sectors = (length + DATA_SECTOR - 1) // DATA_SECTOR
                blobs[name] = src.read(lba, sectors)[:length]
        finally:
            src.close()

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
