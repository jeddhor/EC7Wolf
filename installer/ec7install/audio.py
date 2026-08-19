"""Ripping the CD soundtrack.

The disc's music is redbook audio: it is in none of the game files, and the
CD release plays it straight off the disc. Audio tracks in a BIN image are
already raw CD audio (44100 Hz, 16-bit stereo, little endian), so this slices
the image at sector boundaries and hands the bytes to an encoder -- no decoding
step, and nothing to get wrong beyond the offsets.

The game plays tracks 3, 5, 7 and 9. The short even-numbered tracks between them
are a few seconds of lead-in; they are written too, because they cost almost
nothing and a rip that matches the disc is easier to reason about than one that
has been pruned.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .progress import Cancelled, Reporter

RAW_SECTOR = 2352
MUSIC_TRACKS = (3, 5, 7, 9)


class AudioError(Exception):
    pass


def can_rip(source) -> bool:
    return bool(source.audio_tracks()) and source.audio_image is not None


def rip(source, destination: Path, reporter: Reporter,
        only_music: bool = False) -> list[Path]:
    """Write trackNN.ogg into destination for every audio track on the disc."""
    tracks = source.audio_tracks()
    image = source.audio_image
    if not tracks or image is None:
        raise AudioError(
            "this source has no audio tracks. A folder holds only the game's "
            "files; the music needs the disc itself or a BIN/CUE image.")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError("FFmpeg is needed to encode the soundtrack")

    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    wanted = [t for t in tracks if not only_music or t.number in MUSIC_TRACKS]

    with image.open("rb") as handle:
        for index, track in enumerate(wanted):
            reporter.check_cancelled()
            out = destination / f"track{track.number:02d}.ogg"
            reporter.detail(f"track {track.number:02d}: {track.seconds:.1f}s")

            handle.seek(track.first_sector * RAW_SECTOR)
            remaining = track.sectors * RAW_SECTOR

            process = subprocess.Popen(
                [ffmpeg, "-hide_banner", "-loglevel", "error",
                 "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "pipe:0",
                 "-c:a", "libvorbis", "-q:a", "5", "-y", str(out)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE)
            try:
                assert process.stdin is not None
                # Streamed in chunks rather than read whole: the longest track is
                # ten minutes, which is about 108 MB of raw audio, and there is
                # no reason for any of it to be resident at once.
                while remaining > 0:
                    chunk = handle.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    process.stdin.write(chunk)
                    remaining -= len(chunk)
                process.stdin.close()
            except BrokenPipeError:
                pass
            except Cancelled:
                process.kill()
                raise

            _, errors = process.communicate()
            if process.returncode != 0:
                raise AudioError(
                    f"FFmpeg could not encode track {track.number}: "
                    f"{(errors or b'').decode('utf-8', 'replace').strip()}")
            written.append(out)
            reporter.progress((index + 1) / len(wanted))

    return written
