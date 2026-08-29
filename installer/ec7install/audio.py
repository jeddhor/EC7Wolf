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

from . import proc
from .progress import Cancelled, Reporter

RAW_SECTOR = 2352
MUSIC_TRACKS = (3, 5, 7, 9)


class AudioError(Exception):
    pass


def can_rip(source) -> bool:
    return bool(source.audio_tracks()) and source.audio_image is not None


def rip(source, destination: Path, reporter: Reporter,
        only_music: bool = False, cache: Path | None = None) -> list[Path]:
    """Write trackNN.ogg into destination for every audio track on the disc.

    With a cache directory, encoding survives a failed run: each track is
    written there under a .part name and renamed only once FFmpeg has finished,
    so a file that exists is a file that is complete, and a second attempt
    copies it instead of spending another minute encoding it. Ripping is the
    longest step after the compile, and the compile already resumes because
    CMake's build tree outlives a failure.
    """
    tracks = source.audio_tracks()
    image = source.audio_image
    if not tracks or image is None:
        raise AudioError(
            "this source has no audio tracks. A folder holds only the game's "
            "files; the music needs the disc itself or a BIN/CUE image.")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        from .deps import remedy
        raise AudioError(
            "FFmpeg is needed to encode the CD soundtrack, and is not "
            f"installed. {remedy('ffmpeg')}. The game plays without it; it "
            "just falls back to the AdLib music.")

    destination.mkdir(parents=True, exist_ok=True)
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    wanted = [t for t in tracks if not only_music or t.number in MUSIC_TRACKS]

    with image.open("rb") as handle:
        for index, track in enumerate(wanted):
            reporter.check_cancelled()
            name = f"track{track.number:02d}.ogg"
            out = destination / name

            # Already here -- adopted from the install being replaced, most
            # likely. Encoding it again would produce the same bytes and cost
            # the better part of a minute.
            if out.is_file() and out.stat().st_size >= 4096:
                reporter.detail(f"track {track.number:02d}: already installed")
                written.append(out)
                reporter.progress((index + 1) / len(wanted))
                continue

            kept = cache / name if cache is not None else None
            if kept is not None and kept.is_file() and kept.stat().st_size > 0:
                reporter.detail(f"track {track.number:02d}: already encoded")
                shutil.copy2(kept, out)
                written.append(out)
                reporter.progress((index + 1) / len(wanted))
                continue

            reporter.detail(f"track {track.number:02d}: {track.seconds:.1f}s")
            # Encode to a name nothing will mistake for a finished file, and
            # rename only on success -- otherwise a run killed part way through
            # leaves a truncated track that the next run happily believes.
            encoding = (cache / (name + ".part")) if cache is not None else out

            handle.seek(track.first_sector * RAW_SECTOR)
            remaining = track.sectors * RAW_SECTOR

            process = subprocess.Popen(
                [ffmpeg, "-hide_banner", "-loglevel", "error",
                 "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", "pipe:0",
                 # -f ogg because the container is named, not guessed: the
                 # file being written is trackNN.ogg.part while it encodes, and
                 # FFmpeg picks the muxer from the extension unless told.
                 "-c:a", "libvorbis", "-q:a", "5", "-f", "ogg",
                 "-y", str(encoding)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, **proc.quiet())
            try:
                assert process.stdin is not None
                # Streamed in chunks rather than read whole: the longest track is
                # ten minutes, which is about 108 MB of raw audio, and there is
                # no reason for any of it to be resident at once.
                while remaining > 0:
                    # Polled here, not just between tracks: the longest track
                    # is ten minutes, and a Cancel button that does nothing
                    # until the current track finishes is not a Cancel button.
                    reporter.check_cancelled()
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
                if encoding is not out and encoding.exists():
                    encoding.unlink()
                raise

            _, errors = process.communicate()
            if process.returncode != 0:
                if encoding is not out and encoding.exists():
                    encoding.unlink()
                raise AudioError(
                    f"FFmpeg could not encode track {track.number}: "
                    f"{(errors or b'').decode('utf-8', 'replace').strip()}")
            if encoding is not out:
                encoding.replace(kept)
                shutil.copy2(kept, out)
            written.append(out)
            reporter.progress((index + 1) / len(wanted))

    return written
