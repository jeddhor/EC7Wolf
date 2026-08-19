"""Checking that what was installed will actually run.

The extraction is the step most likely to fail quietly -- a scratched disc, a
truncated image, a rip that ran out of space -- and the failure shows up much
later as a game that will not start, or one that plays half a cinematic and
stops. So the install ends by reading back what it wrote.
"""

from __future__ import annotations

import struct
from pathlib import Path

from .install import (CD_EXECUTABLE_SIZE, CINEMATICS, OPTIONAL_DATA,
                      REQUIRED_DATA)


class Problem:
    def __init__(self, path: str, message: str, fatal: bool = True):
        self.path = path
        self.message = message
        self.fatal = fatal

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _check_flic(path: Path) -> str | None:
    """None if this is a playable cinematic, else why not."""
    try:
        with path.open("rb") as handle:
            header = handle.read(20)
        actual = path.stat().st_size
    except OSError as error:
        return str(error)
    if len(header) < 20:
        return "too short to be an animation"
    size, magic, frames, width, height, depth, _flags = struct.unpack_from(
        "<IHHHHHH", header, 0)
    if magic not in (0xAF11, 0xAF12):
        return f"not a FLIC (magic 0x{magic:04X})"
    # The header's own length against the real one is the cheapest integrity
    # check there is, and the one that catches a short read.
    if size != actual:
        return f"header says {size} bytes, file is {actual}"
    if (width, height, depth) != (320, 200, 8):
        return f"expected 320x200x8, got {width}x{height}x{depth}"
    if frames == 0:
        return "no frames"
    return None


def verify(destination: Path, expect_music: bool = False,
           expect_video: bool = False) -> list[Problem]:
    destination = Path(destination)
    problems: list[Problem] = []

    # The game files sit beside the engine, not in a subfolder: "--data CO7"
    # names the file EXTENSION the engine looks for, not a directory, and it
    # searches the working directory. This is the layout
    # tools/package_corridor7_release.sh already produces.
    data = destination
    executable = destination / ("ec7wolf.exe" if (destination / "ec7wolf.exe").exists()
                                else "ec7wolf")
    if not executable.is_file():
        problems.append(Problem(executable.name, "the engine is missing"))
    if not (destination / "ec7wolf.pk3").is_file():
        problems.append(Problem("ec7wolf.pk3",
                                "the engine's own data file is missing"))

    for name in REQUIRED_DATA:
        target = data / name
        if not target.is_file():
            problems.append(Problem(name,
                                    "required game file is missing"))
        elif target.stat().st_size == 0:
            problems.append(Problem(name, "is empty"))

    executable_data = data / "CORR7CD.EXE"
    if executable_data.is_file():
        size = executable_data.stat().st_size
        if size != CD_EXECUTABLE_SIZE:
            problems.append(Problem(
                "CORR7CD.EXE",
                f"is {size} bytes, not the {CD_EXECUTABLE_SIZE} of the CD "
                "release. The game reads its palette out of this file, so a "
                "different build will not work.",
                fatal=False))

    for name in OPTIONAL_DATA:
        if not (data / name).is_file():
            problems.append(Problem(
                name,
                "is missing: the game will run but will use the AdLib sound "
                "effects instead of the digitized ones", fatal=False))

    if expect_video:
        video = data / "video"
        for name in CINEMATICS:
            target = video / name
            if not target.is_file():
                problems.append(Problem(f"video/{name}",
                                        "cinematic is missing", fatal=False))
                continue
            why = _check_flic(target)
            if why:
                problems.append(Problem(f"video/{name}", why))

    if expect_music:
        music = data / "cdaudio"
        # The game plays tracks 3, 5, 7 and 9 -- the four pieces of music.
        for track in (3, 5, 7, 9):
            target = music / f"track{track:02d}.ogg"
            if not target.is_file():
                problems.append(Problem(f"cdaudio/{target.name}",
                                        "soundtrack file is missing",
                                        fatal=False))
            elif target.stat().st_size < 4096:
                problems.append(Problem(f"cdaudio/{target.name}",
                                        "is too small to be a music track"))

    return problems
