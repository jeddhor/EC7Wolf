#!/usr/bin/env python3
"""Reading Corridor 7's files off a disc, an image, or a folder.

One implementation, used by tools/extract_c7_video.py and by the installer.
Previously the ISO9660 walk lived only in the video extractor; the installer
needs the same walk to pull the data files and the audio tracks, and two copies
of a filesystem parser is two chances to be subtly wrong about one.

Sources it understands, all through the same interface:

    GameSource.open("/dev/sr0")          a CD in a drive
    GameSource.open("Corridor7.cue")     a BIN/CUE pair (Steam/GOG)
    GameSource.open("disc.iso")          a plain image
    GameSource.open("/path/to/CORR7CD")  an already-installed folder

Only the standard library. A .cue/.bin is MODE1/2352, so each 2352-byte sector
carries a 16-byte sync and header, 2048 bytes of data and 288 bytes of error
correction; this strips that itself rather than needing bchunk, and walks
ISO9660 itself rather than needing isoinfo -- which can list the Corridor 7 disc
but declines to extract from it.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

RAW_SECTOR = 2352
DATA_SECTOR = 2048
MODE1_HEADER = 16
FRAMES_PER_SECOND = 75


class DiscError(Exception):
    """Anything that means "this is not a readable Corridor 7 disc"."""


class AudioTrack:
    """One redbook track, located in a BIN image."""

    def __init__(self, number: int, first_sector: int, sectors: int):
        self.number = number
        self.first_sector = first_sector
        self.sectors = sectors

    @property
    def seconds(self) -> float:
        return self.sectors / FRAMES_PER_SECOND

    def __repr__(self) -> str:
        return f"<AudioTrack {self.number} {self.seconds:.1f}s>"


def parse_msf(text: str) -> int:
    minutes, seconds, frames = (int(part) for part in text.split(":"))
    return (minutes * 60 + seconds) * FRAMES_PER_SECOND + frames


# ---------------------------------------------------------------------------
# Sector access
# ---------------------------------------------------------------------------

class _Sectors:
    """2048-byte logical sectors, whatever the container underneath is."""

    def __init__(self, path: Path, first: int = 0, count: int | None = None,
                 raw: bool = False):
        self._path = path
        self._file = path.open("rb")
        self._first = first
        self._raw = raw
        step = RAW_SECTOR if raw else DATA_SECTOR
        if count is not None:
            self.count = count
        else:
            try:
                self.count = path.stat().st_size // step
            except OSError:
                self.count = 0
            if self.count == 0:
                # A block device reports no useful size through stat; seek to
                # the end instead. A CD is small enough that this is instant.
                self._file.seek(0, 2)
                self.count = self._file.tell() // step
                self._file.seek(0)

    def read(self, lba: int, sectors: int = 1) -> bytes:
        if lba < 0:
            raise DiscError(f"sector {lba} is before the start of the track")
        if not self._raw:
            self._file.seek((self._first + lba) * DATA_SECTOR)
            return self._file.read(DATA_SECTOR * sectors)
        out = bytearray()
        for i in range(sectors):
            self._file.seek((self._first + lba + i) * RAW_SECTOR + MODE1_HEADER)
            out += self._file.read(DATA_SECTOR)
        return bytes(out)

    def close(self) -> None:
        self._file.close()


# ---------------------------------------------------------------------------
# ISO9660
# ---------------------------------------------------------------------------

def _walk_iso(sectors: _Sectors) -> dict[str, tuple[int, int]]:
    """-> {UPPERCASE NAME: (lba, length)} for every file on the disc.

    Deliberately small: the primary volume descriptor, then directories
    breadth-first, understanding only what a 1994 ISO9660 level-1 disc uses. No
    Joliet, no Rock Ridge. Names are returned bare -- no ";1" version suffix and
    no directory path, because Corridor 7 has one data directory and the callers
    all want to ask for "MAPTEMP.CO7".
    """
    pvd = None
    for sector in range(16, 32):
        try:
            block = sectors.read(sector)
        except (OSError, DiscError):
            break
        if len(block) < 6 or block[1:6] != b"CD001":
            continue
        if block[0] == 1:
            pvd = block
            break
        if block[0] == 255:
            break
    if pvd is None:
        raise DiscError("no ISO9660 primary volume descriptor")

    root = pvd[156:156 + 34]
    queue = [(struct.unpack("<I", root[2:6])[0],
              struct.unpack("<I", root[10:14])[0])]
    seen: set[tuple[int, int]] = set()
    found: dict[str, tuple[int, int]] = {}

    while queue:
        lba, length = queue.pop(0)
        if (lba, length) in seen or length == 0:
            continue
        seen.add((lba, length))

        data = sectors.read(lba, (length + DATA_SECTOR - 1) // DATA_SECTOR)
        offset = 0
        while offset < len(data):
            record_len = data[offset]
            if record_len == 0:
                # Records never straddle a sector boundary.
                offset = (offset // DATA_SECTOR + 1) * DATA_SECTOR
                if offset >= len(data):
                    break
                continue
            record = data[offset:offset + record_len]
            if len(record) < 33:
                break
            child_lba = struct.unpack("<I", record[2:6])[0]
            child_len = struct.unpack("<I", record[10:14])[0]
            flags = record[25]
            name_len = record[32]
            name = record[33:33 + name_len].decode("ascii", "replace")

            if flags & 0x02:
                if name not in ("\x00", "\x01"):
                    queue.append((child_lba, child_len))
            else:
                found[name.split(";")[0].upper()] = (child_lba, child_len)
            offset += record_len

    return found


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class GameSource:
    """Somewhere Corridor 7's files can be read from."""

    kind = "unknown"

    def describe(self) -> str:
        raise NotImplementedError

    def list(self) -> dict[str, int]:
        """-> {UPPERCASE NAME: size in bytes}"""
        raise NotImplementedError

    def read(self, name: str) -> bytes:
        raise NotImplementedError

    def audio_tracks(self) -> list[AudioTrack]:
        """Redbook tracks, where the source can offer them. A folder cannot."""
        return []

    @property
    def audio_image(self) -> Path | None:
        """The BIN holding the audio tracks, if there is one."""
        return None

    def close(self) -> None:
        pass

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()

    # -- detection ---------------------------------------------------------

    @staticmethod
    def open(path) -> "GameSource":
        path = Path(path)
        if path.is_dir():
            return FolderSource(path)
        if not path.exists():
            raise DiscError(f"{path} does not exist")
        if path.suffix.lower() == ".cue":
            return CueSource(path)

        # A .bin is the obvious file to reach for -- it is the big one -- but on
        # its own it is just sectors: nothing in it says where the data track
        # ends and the audio begins, or even how large a sector is. The .cue
        # beside it says all of that, so use it.
        if path.suffix.lower() in (".bin", ".img"):
            for candidate in (path.with_suffix(".cue"), path.with_suffix(".CUE")):
                if candidate.is_file():
                    return CueSource(candidate)
            for candidate in sorted(path.parent.glob("*.[cC][uU][eE]")):
                if candidate.stem.lower() == path.stem.lower():
                    return CueSource(candidate)
            raise DiscError(
                f"{path.name} is a raw disc image, and on its own it does not "
                "say how its tracks are laid out -- that is what the .cue file "
                "beside it is for. No .cue was found next to it; choose the "
                ".cue rather than the .bin.")

        return ImageSource(path)


class FolderSource(GameSource):
    """An already-installed game directory, or a mounted CD."""

    kind = "folder"

    def __init__(self, root: Path):
        self.root = root
        # The disc has its files under CORR7CD; an install has them loose.
        self._dirs = [root]
        sub = root / "CORR7CD"
        if sub.is_dir():
            self._dirs.insert(0, sub)

    def describe(self) -> str:
        return f"folder {self.root}"

    def _resolve(self, name: str) -> Path | None:
        for directory in self._dirs:
            for spelling in (name, name.lower(), name.upper()):
                candidate = directory / spelling
                if candidate.is_file():
                    return candidate
        return None

    def list(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for directory in reversed(self._dirs):
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if entry.is_file():
                    out[entry.name.upper()] = entry.stat().st_size
        return out

    def read(self, name: str) -> bytes:
        resolved = self._resolve(name)
        if resolved is None:
            raise DiscError(f"{name} is not in {self.root}")
        return resolved.read_bytes()


class ImageSource(GameSource):
    """A plain .iso, or a CD device whose data track is sector-addressable."""

    kind = "image"

    def __init__(self, path: Path, first: int = 0, count: int | None = None,
                 raw: bool = False, audio: list[AudioTrack] | None = None,
                 audio_image: Path | None = None):
        self.path = path
        self._sectors = _Sectors(path, first, count, raw)
        self._audio = audio or []
        self._audio_image = audio_image
        try:
            self._files = _walk_iso(self._sectors)
        except Exception:
            self._sectors.close()
            raise

    def describe(self) -> str:
        return f"image {self.path}"

    def list(self) -> dict[str, int]:
        return {name: length for name, (_, length) in self._files.items()}

    def read(self, name: str) -> bytes:
        key = name.upper()
        if key not in self._files:
            raise DiscError(f"{name} is not on {self.path}")
        lba, length = self._files[key]
        blob = self._sectors.read(lba, (length + DATA_SECTOR - 1) // DATA_SECTOR)
        if len(blob) < length:
            raise DiscError(f"{name} is truncated: wanted {length}, read {len(blob)}")
        return blob[:length]

    def audio_tracks(self) -> list[AudioTrack]:
        return list(self._audio)

    @property
    def audio_image(self) -> Path | None:
        return self._audio_image

    def close(self) -> None:
        self._sectors.close()


def CueSource(cue_path: Path) -> ImageSource:
    """A BIN/CUE pair: the data track for files, the rest as audio tracks."""
    text = cue_path.read_text(errors="replace")

    file_match = re.search(r'FILE\s+"([^"]+)"', text)
    if not file_match:
        raise DiscError(f"{cue_path}: no FILE line")
    binary = cue_path.parent / file_match.group(1)
    if not binary.exists():
        raise DiscError(f"{cue_path} names {file_match.group(1)}, "
                        "which is not beside it")

    # A PREGAP is silence the disc has but the file does not, so every track
    # after one sits that much earlier in the image than its INDEX says -- and
    # the shift ACCUMULATES down the sheet. Applying only each track's own
    # pregap stretched Corridor 7's track 2 from 8 seconds to 10, because its
    # start moved earlier while track 3's did not.
    tracks = []
    shift = 0
    for match in re.finditer(
            r"TRACK\s+(\d+)\s+(\S+)(.*?)(?=TRACK\s+\d+|\Z)", text, re.S):
        index = re.search(r"INDEX\s+01\s+(\d+:\d+:\d+)", match.group(3))
        pregap = re.search(r"PREGAP\s+(\d+:\d+:\d+)", match.group(3))
        if pregap:
            shift += parse_msf(pregap.group(1))
        if not index:
            continue
        tracks.append({
            "n": int(match.group(1)),
            "mode": match.group(2),
            "start": parse_msf(index.group(1)),
            "shift": shift,
        })

    data = [t for t in tracks if t["mode"].startswith("MODE")]
    if not data:
        raise DiscError(f"{cue_path}: no data track")
    track = data[0]

    total = binary.stat().st_size // RAW_SECTOR
    starts = sorted(t["start"] - t["shift"] for t in tracks)

    def extent(start: int) -> int:
        later = [s for s in starts if s > start]
        return (min(later) if later else total) - start

    audio = [AudioTrack(t["n"], t["start"] - t["shift"],
                        extent(t["start"] - t["shift"]))
             for t in tracks if not t["mode"].startswith("MODE")]

    first = track["start"] - track["shift"]
    return ImageSource(binary, first, extent(first),
                       raw=track["mode"].endswith("/2352"),
                       audio=audio, audio_image=binary)


# ---------------------------------------------------------------------------
# Finding a disc without being told where it is
# ---------------------------------------------------------------------------

class Drive:
    """An optical drive, and whatever is in it."""

    def __init__(self, path: str, label: str, has_disc: bool):
        self.path = path
        self.label = label
        self.has_disc = has_disc

    def __repr__(self) -> str:
        return f"<Drive {self.path} {'loaded' if self.has_disc else 'empty'}>"


def optical_drives() -> list[Drive]:
    """Optical drives on this machine, so the user can be offered a list.

    Readability is the test, not the presence of a device node: an empty drive
    exists but cannot be read, and offering it as a choice only produces a
    confusing error two pages later.
    """
    import platform

    drives: list[Drive] = []

    if platform.system() == "Windows":
        try:
            import ctypes
            DRIVE_CDROM = 5
            bits = ctypes.windll.kernel32.GetLogicalDrives()
            for index in range(26):
                if not bits & (1 << index):
                    continue
                root = f"{chr(ord('A') + index)}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(root) != DRIVE_CDROM:
                    continue
                name_buffer = ctypes.create_unicode_buffer(261)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    root, name_buffer, 261, None, None, None, None, 0)
                label = name_buffer.value or "CD drive"
                drives.append(Drive(root, f"{root}  {label}",
                                    bool(name_buffer.value)))
        except Exception:
            pass
        return drives

    # A mounted disc is the easy case, and the one that needs no permissions.
    seen: set[str] = set()
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] in ("iso9660", "udf"):
                mount = parts[1].replace("\\040", " ")
                if mount not in seen:
                    seen.add(mount)
                    drives.append(Drive(mount, f"{mount}  (mounted disc)", True))
    except OSError:
        pass

    # Then the raw devices, which can be read directly when permissions allow.
    for pattern in ("/dev/sr*", "/dev/cdrom*", "/dev/dvd*"):
        for device in sorted(Path("/dev").glob(pattern.split("/")[-1])):
            path = str(device)
            if path in seen:
                continue
            seen.add(path)
            readable = False
            try:
                with device.open("rb") as handle:
                    handle.seek(16 * DATA_SECTOR)
                    readable = handle.read(6)[1:6] == b"CD001"
            except OSError:
                readable = False
            drives.append(Drive(path, f"{path}  " +
                                ("(disc inserted)" if readable else "(empty or unreadable)"),
                                readable))
    return drives
