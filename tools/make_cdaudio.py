#!/usr/bin/env python3
"""Rip the Corridor 7 CD soundtrack into the cdaudio directory the port reads.

The CD release plays its music off the disc rather than out of AUDIOMUS.CO7, so
none of it is in the game files. Point this at a BIN/CUE image of your own disc
and it writes trackNN.ogg files named for their physical track number, which is
what EC7Wolf looks for.

Usage:
  make_cdaudio.py Corridor7.cue /path/to/game/cdaudio

The game itself only ever plays tracks 3, 5, 7 and 9 -- the four pieces of
music. The short even-numbered tracks between them are lead-ins a few seconds
long; they are written out too, because they cost almost nothing and a rip that
matches the disc is easier to reason about than one that has been pruned.

Requires ffmpeg on PATH. Audio tracks in a BIN image are already raw CD audio
(44100 Hz, 16-bit stereo, little endian), so this only slices the image at
sector boundaries and hands the bytes to the encoder.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SECTOR_BYTES = 2352
FRAMES_PER_SECOND = 75


def parse_msf(text: str) -> int:
    """MM:SS:FF -> frames (sectors)."""
    minutes, seconds, frames = (int(part) for part in text.split(":"))
    return (minutes * 60 + seconds) * FRAMES_PER_SECOND + frames


def parse_cue(cue_path: Path) -> tuple[Path, list[tuple[int, str, int]]]:
    """Return (bin path, [(track number, mode, start sector), ...])."""
    binary: Path | None = None
    tracks: list[tuple[int, str, int]] = []
    number: int | None = None
    mode = ""

    for line in cue_path.read_text(errors="replace").splitlines():
        line = line.strip()

        match = re.match(r'FILE\s+"(.+)"', line, re.IGNORECASE)
        if match:
            binary = cue_path.parent / match.group(1)
            continue

        match = re.match(r"TRACK\s+(\d+)\s+(\S+)", line, re.IGNORECASE)
        if match:
            number, mode = int(match.group(1)), match.group(2).upper()
            continue

        # INDEX 01 is where the track's content begins. INDEX 00 and PREGAP are
        # the gap before it and are not part of the track.
        match = re.match(r"INDEX\s+0*1\s+(\d+:\d+:\d+)", line, re.IGNORECASE)
        if match and number is not None:
            tracks.append((number, mode, parse_msf(match.group(1))))
            number = None

    if binary is None:
        sys.exit(f"{cue_path} names no FILE")
    if not binary.exists():
        sys.exit(f"the image {binary} named by {cue_path} is missing")

    return binary, tracks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cue", type=Path, help="the disc's .cue sheet")
    parser.add_argument("outdir", type=Path, help="the game's cdaudio directory")
    parser.add_argument("--quality", type=int, default=6,
                        help="libvorbis quality, 0-10 (default 6)")
    args = parser.parse_args()

    binary, tracks = parse_cue(args.cue)
    image_sectors = binary.stat().st_size // SECTOR_BYTES

    args.outdir.mkdir(parents=True, exist_ok=True)

    written = 0
    for index, (number, mode, start) in enumerate(tracks):
        if mode != "AUDIO":
            continue

        end = tracks[index + 1][2] if index + 1 < len(tracks) else image_sectors
        out = args.outdir / f"track{number:02d}.ogg"

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "pipe:0",
            "-c:a", "libvorbis", "-q:a", str(args.quality), str(out),
        ]

        with binary.open("rb") as image, subprocess.Popen(
                command, stdin=subprocess.PIPE) as encoder:
            image.seek(start * SECTOR_BYTES)
            remaining = (end - start) * SECTOR_BYTES
            while remaining > 0:
                chunk = image.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                encoder.stdin.write(chunk)
                remaining -= len(chunk)
            encoder.stdin.close()
            if encoder.wait() != 0:
                sys.exit(f"ffmpeg failed writing {out}")

        seconds = (end - start) / FRAMES_PER_SECOND
        print(f"track{number:02d}.ogg  {seconds:7.2f}s")
        written += 1

    if written == 0:
        sys.exit(f"{args.cue} lists no audio tracks; this is not the CD release")

    missing = [n for n in (3, 5, 7, 9)
               if not (args.outdir / f"track{n:02d}.ogg").exists()]
    if missing:
        print("warning: the game's four music tracks are "
              + ", ".join(f"track{n:02d}" for n in (3, 5, 7, 9))
              + "; missing " + ", ".join(f"track{n:02d}" for n in missing),
              file=sys.stderr)

    print(f"wrote {written} track(s) to {args.outdir}")


if __name__ == "__main__":
    main()
