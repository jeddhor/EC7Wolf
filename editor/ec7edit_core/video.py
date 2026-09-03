# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""From a modern video, or a folder of frames, to a cinematic the game plays.

The pipeline, and why each step is where it is:

    a video file  --ffmpeg-->  PNG frames  --here-->  .CO7 (FLIC)

**ffmpeg is not a dependency.** It is used if it is there, because asking
somebody to install it to convert an MP4 is reasonable and writing an H.264
decoder is not. Without it, the editor takes a folder of PNGs and says so --
and one ffmpeg command produces that folder, which the message quotes.

Everything after the frames is the standard library: `imagery` reads the PNGs
and reduces them to 256 colors, `flic` writes the file. Nothing is installed,
nothing is downloaded, and the result is a format this engine has decoded
since the CD's own animations were found.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import flic, imagery
from .errors import export_error

#: What the game's own cinematics run at, and a sensible default for one made
#: to sit beside them.
DEFAULT_FPS = 14

#: Formats worth trying ffmpeg on. Not a gate -- ffmpeg is asked to open
#: whatever it is given -- but it decides whether a path is treated as a video
#: or as a folder that does not exist.
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mpg",
                  ".mpeg", ".wmv", ".gif", ".flv", ".ogv"}


@dataclass(frozen=True)
class Encoded:
    """A finished cinematic, and what went into it."""

    data: bytes
    frames: int
    speed_ms: int
    colors: int
    source: str

    def describe(self) -> str:
        seconds = self.frames * self.speed_ms / 1000.0
        return (f"{self.frames} frames, {seconds:.1f}s at "
                f"{1000.0 / self.speed_ms:.1f} fps, {len(self.data) / 1024:.0f} kB")


def have_ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


def extract_frames(video: Path, into: Path, fps: int) -> list[Path]:
    """Ask ffmpeg for PNG frames at the size and rate the format needs."""
    ffmpeg = have_ffmpeg()
    if not ffmpeg:
        raise export_error(
            "C7E-VIDEO-001",
            f"ffmpeg is not installed, so {video.name} cannot be read here. "
            "Either install it, or extract the frames yourself and point this "
            "at the folder:\n"
            f"    ffmpeg -i {video.name} -vf scale={flic.WIDTH}:{flic.HEIGHT} "
            f"-r {fps} frames/%04d.png",
            str(video))

    into.mkdir(parents=True, exist_ok=True)
    # Scaled and padded rather than stretched: a widescreen source squeezed
    # into 320x200 looks wrong in a way nobody can put their finger on, and
    # letterboxing is what the CD's own animations do at the edges anyway.
    command = [
        ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", (f"scale={flic.WIDTH}:{flic.HEIGHT}:force_original_aspect_ratio="
                f"decrease,pad={flic.WIDTH}:{flic.HEIGHT}:(ow-iw)/2:(oh-ih)/2"),
        "-r", str(fps), "-pix_fmt", "rgb24",
        str(into / "%05d.png"),
    ]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as error:
        raise export_error("C7E-VIDEO-001", f"ffmpeg did not run: {error}",
                           str(video)) from error
    if done.returncode != 0:
        raise export_error(
            "C7E-VIDEO-001",
            f"ffmpeg could not read {video.name}: "
            f"{done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'no reason given'}",
            str(video))
    return sorted(into.glob("*.png"))


def frame_files(source: Path) -> list[Path]:
    """The PNGs in a folder, in the order their names put them.

    Sorted by name, which is what every frame extractor is built around --
    ffmpeg's `%05d` included. A folder whose frames are named for something
    else is a folder whose order nobody can guess.
    """
    files = sorted(p for p in source.iterdir()
                   if p.is_file() and p.suffix.lower() == ".png")
    if not files:
        raise export_error("C7E-VIDEO-002",
                           f"{source} holds no .png frames", str(source))
    return files


def encode_frames(files, *, fps: int = DEFAULT_FPS, colors: int = 256,
                  stability: int = imagery.STABILITY, progress=None) -> Encoded:
    """Frames to a cinematic, with one palette shared by all of them."""
    files = list(files)
    if not files:
        raise export_error("C7E-VIDEO-002", "there are no frames to encode")
    if len(files) > flic.MAX_FRAMES:
        raise export_error(
            "C7E-VIDEO-002",
            f"{len(files)} frames is more than the {flic.MAX_FRAMES} this "
            "writes. Shorten the video, or lower the frame rate.")
    if not 1 <= fps <= 70:
        raise export_error("C7E-VIDEO-002", f"{fps} fps is outside 1..70")
    if not 2 <= colors <= 256:
        raise export_error("C7E-VIDEO-002", f"{colors} colors is outside 2..256")

    def note(message: str) -> None:
        if progress is not None:
            progress(message)

    note(f"reading {len(files)} frame(s)")
    images = []
    for path in files:
        width, height, rgb = imagery.read_png(path)
        if (width, height) != (flic.WIDTH, flic.HEIGHT):
            raise export_error(
                "C7E-VIDEO-003",
                f"{path.name} is {width}x{height}; every frame must be "
                f"{flic.WIDTH}x{flic.HEIGHT}. ffmpeg's scale filter does this.",
                str(path))
        images.append(rgb)

    # One palette for the whole animation, because FLIC sets it on the first
    # frame and every later frame is indices into it. A per-frame palette is
    # possible in the format and is a different, worse thing to look at: the
    # whole screen shifts hue whenever the palette changes.
    note("choosing 256 colors for the whole animation")
    palette = imagery.build_palette(images, colors)
    mapping = imagery.build_mapping(palette)

    note("reducing frames to those colors")
    frames = []
    previous = None
    for rgb in images:
        indices = imagery.quantize_stable(rgb, mapping, palette, previous,
                                          stability)
        frames.append(flic.Frame(indices))
        previous = indices

    note("writing")
    speed_ms = max(1, round(1000 / fps))
    data = flic.encode(frames, palette, speed_ms=speed_ms)
    return Encoded(data=data, frames=len(frames), speed_ms=speed_ms,
                   colors=colors, source=str(files[0].parent))


def encode(source: Path | str, *, fps: int = DEFAULT_FPS, colors: int = 256,
           stability: int = imagery.STABILITY, progress=None) -> Encoded:
    """A cinematic from a video file or a folder of PNG frames."""
    source = Path(source)
    if source.is_dir():
        return encode_frames(frame_files(source), fps=fps, colors=colors,
                             stability=stability, progress=progress)
    if not source.is_file():
        raise export_error("C7E-VIDEO-002", f"{source} is not there", str(source))
    if source.suffix.lower() not in VIDEO_SUFFIXES:
        raise export_error(
            "C7E-VIDEO-002",
            f"{source.name} is neither a folder of frames nor a video this "
            f"recognizes ({', '.join(sorted(VIDEO_SUFFIXES))})", str(source))

    with tempfile.TemporaryDirectory(prefix="ec7edit-frames-") as scratch:
        if progress is not None:
            progress(f"extracting frames from {source.name} with ffmpeg")
            # Said every time rather than only when there is audio to drop.
            # Detecting that would mean another tool, and somebody whose clip
            # is silent anyway loses nothing by being told.
            progress("FLIC carries no sound, so the audio is not included")
        files = extract_frames(source, Path(scratch), fps)
        result = encode_frames(files, fps=fps, colors=colors,
                               stability=stability, progress=progress)
    return Encoded(data=result.data, frames=result.frames,
                   speed_ms=result.speed_ms, colors=result.colors,
                   source=str(source))


__all__ = ["DEFAULT_FPS", "Encoded", "VIDEO_SUFFIXES", "encode", "encode_frames",
           "extract_frames", "frame_files", "have_ffmpeg"]
