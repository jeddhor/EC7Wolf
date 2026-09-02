# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Finding and validating the user's engine, game data and workspace.

The output of first-run setup is not "valid" or "invalid" — it is a checklist,
because "could not find your game" is the least useful thing a program can say
to somebody holding a CD. Every check here names what it looked for, what it
found, and what to do about it.

Two rules the plan is firm about, and both are about not being clever:

**Do not go looking.** Nothing here scans a home directory. Candidates come
from the package's own layout, from paths the user picked, and from nowhere
else. An editor that trawls the filesystem for a game is an editor that finds
somebody's backup and edits that.

**Do not run it to identify it.** The engine's version comes from asking it,
which means executing a binary the user selected — so that happens only after
they confirm the probe. Until then, identification is a bounded read of the
file's own bytes.

Everything in this module is Qt-free; the wizard is a view over it.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .archive import parse_archive
from .assets import PALETTE_OFFSET, PALETTE_SIZE, AssetError, load_palette, parse_gfx_header
from .bundle import workspace_root
from .paths import canonical, digest_file, looks_like_game_data

#: The minimum a Corridor 7 installation must have for the editor to work.
#: The executable is on the list because the palette lives in it and nowhere
#: else -- the game's own data files do not contain one.
REQUIRED_DATA = ("MAPTEMP.CO7", "GFXTILES.CO7", "CORR7CD.EXE")

#: Nice to have. Their absence is reported and is never a blocker: an editor
#: that refuses to open because the music is missing is an editor with its
#: priorities wrong.
OPTIONAL_DATA = ("VGAGRAPH.CO7", "VGADICT.CO7", "VGAHEAD.CO7", "AUDIOT.CO7", "AUDIOHED.CO7")

OK = "ok"
WARN = "warning"
FAIL = "error"


@dataclass(frozen=True)
class Check:
    """One line of the first-run checklist."""

    name: str
    status: str
    detail: str = ""
    remedy: str = ""

    @property
    def passed(self) -> bool:
        return self.status != FAIL


@dataclass
class Report:
    """A checklist, and whether it is good enough to work with."""

    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", remedy: str = "") -> None:
        self.checks.append(Check(name, status, detail, remedy))

    @property
    def usable(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if check.status == FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [check for check in self.checks if check.status == WARN]

    def __iter__(self):
        return iter(self.checks)

    def __len__(self) -> int:
        return len(self.checks)


@dataclass
class Profile:
    """A trusted local association of engine, data and workspace.

    Lives in the user's own settings, never in a project file. A project refers
    to a profile *id* and an expected data fingerprint; it cannot carry the
    paths themselves, because then opening somebody else's project would point
    this editor at their filesystem.
    """

    profile_id: str = ""
    engine_path: str = ""
    data_dir: str = ""
    workspace_dir: str = ""
    data_fingerprint: str = ""
    engine_version: str = ""

    def to_json(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "engine_path": self.engine_path,
            "data_dir": self.data_dir,
            "workspace_dir": self.workspace_dir,
            "data_fingerprint": self.data_fingerprint,
            "engine_version": self.engine_version,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Profile":
        return cls(**{key: payload.get(key, "") for key in cls().to_json()})


def data_fingerprint(directory: Path | str) -> str:
    """A digest over the required files, identifying a data set by content.

    Content, not path: the same CD copied to two machines gives one
    fingerprint, and a project made against it opens on both.
    """
    import hashlib

    directory = Path(directory)
    digest = hashlib.sha256()
    for name in REQUIRED_DATA:
        path = directory / name
        digest.update(name.encode("ascii"))
        digest.update(digest_file(path).encode("ascii") if path.is_file() else b"-")
    return digest.hexdigest()


def check_data_directory(directory: Path | str) -> Report:
    """Bounded, read-only probes of a candidate game-data directory."""
    report = Report()
    directory = Path(directory).expanduser()

    if not directory.is_dir():
        report.add("Data directory", FAIL, f"{directory} is not a directory",
                   "Choose the folder holding MAPTEMP.CO7 and CORR7CD.EXE.")
        return report
    report.add("Data directory", OK, str(canonical(directory)))

    missing = [name for name in REQUIRED_DATA if not (directory / name).is_file()]
    if missing:
        report.add(
            "Required game files", FAIL, f"missing: {', '.join(missing)}",
            "Copy these from your own legally owned Corridor 7. The editor never "
            "ships them.",
        )
    else:
        report.add("Required game files", OK, f"all {len(REQUIRED_DATA)} present")

    absent_optional = [name for name in OPTIONAL_DATA if not (directory / name).is_file()]
    if absent_optional:
        report.add("Optional content", WARN, f"not present: {', '.join(absent_optional)}",
                   "Pictures and audio will be unavailable; editing maps is unaffected.")
    else:
        report.add("Optional content", OK, "all present")

    executable = directory / "CORR7CD.EXE"
    if executable.is_file():
        size = executable.stat().st_size
        if size < PALETTE_OFFSET + PALETTE_SIZE:
            report.add(
                "Palette", FAIL,
                f"CORR7CD.EXE is {size} bytes; the palette lives at 0x{PALETTE_OFFSET:X}",
                "This is not the CD executable the palette comes from.",
            )
        else:
            # A bounded read, not the whole file: enough to identify, no more.
            with open(executable, "rb") as handle:
                handle.seek(PALETTE_OFFSET)
                window = handle.read(PALETTE_SIZE)
            try:
                load_palette(b"\x00" * PALETTE_OFFSET + window)
                report.add("Palette", OK, "a 6-bit VGA palette is at the expected offset")
            except AssetError as error:
                report.add("Palette", FAIL, str(error),
                           "The executable is the wrong build or the wrong game.")

    archive = directory / "MAPTEMP.CO7"
    if archive.is_file():
        try:
            parsed = parse_archive(archive.read_bytes())
            report.add("Map archive", OK,
                       f"{len(parsed)} maps, {parsed[0].width}x{parsed[0].height}")
        except Exception as error:  # any codec failure, reported not raised
            report.add("Map archive", FAIL, str(error),
                       "MAPTEMP.CO7 did not parse; the copy may be damaged.")

    graphics = directory / "GFXTILES.CO7"
    if graphics.is_file():
        try:
            with open(graphics, "rb") as handle:
                head = handle.read(6)
                chunk_count = int.from_bytes(head[0:2], "little")
                handle.seek(0)
                header = parse_gfx_header(handle.read(6 + chunk_count * 6))
            report.add("Wall and sprite artwork", OK,
                       f"{header.sprite_start} walls, "
                       f"{header.sound_start - header.sprite_start} sprites")
        except Exception as error:
            report.add("Wall and sprite artwork", FAIL, str(error),
                       "GFXTILES.CO7 did not parse.")

    return report


#: The engine prints its identity as part of the usage page. `--version` is
#: not a flag it has: passing it falls through to a normal start, which on a
#: headless machine means a probe that never returns.
IDENTITY_FLAG = "--help"
_IDENTITY = re.compile(r"^(EC7Wolf|ECWolf)\s+(\S+)", re.MULTILINE)


def check_engine(
    path: Path | str,
    *,
    probe: bool = False,
    timeout: float = 20.0,
    cwd: Path | str | None = None,
) -> Report:
    """Check an engine binary. Only runs it when `probe` is explicitly asked for."""
    report = Report()
    path = Path(path).expanduser()

    if not path.exists():
        report.add("Engine", FAIL, f"{path} does not exist",
                   "Choose the ec7wolf executable from your build or release.")
        return report
    if not path.is_file():
        report.add("Engine", FAIL, f"{path} is not a regular file",
                   "Choose the executable itself, not a directory or a device.")
        return report
    report.add("Engine", OK, str(canonical(path)))

    if not os.access(path, os.X_OK):
        report.add("Executable bit", FAIL, "the file is not executable",
                   "chmod +x it, or choose a different build.")
        return report
    report.add("Executable bit", OK, "set")

    if not probe:
        # Running a binary somebody selected is a real action, so it waits for
        # a real decision. Until then the checklist says what it does not know.
        report.add("Engine identity", WARN, "not checked",
                   "Run the identity probe to confirm this is EC7Wolf.")
        return report

    try:
        # Absolute: the probe runs in the data directory, so a relative path
        # would be resolved against the wrong place.
        result = subprocess.run(
            [str(canonical(path)), IDENTITY_FLAG],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
        )
        text = (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        report.add("Engine identity", FAIL, f"the probe did not return within {timeout:g}s",
                   "The binary may be waiting for input or for a display.")
        return report
    except (OSError, subprocess.SubprocessError) as error:
        report.add("Engine identity", FAIL, f"the probe failed: {error}",
                   "The file may not be an executable for this machine.")
        return report

    found = _IDENTITY.search(text)
    if found and found.group(1) == "EC7Wolf":
        report.add("Engine identity", OK, found.group(0).strip())
    elif found:
        report.add(
            "Engine identity", FAIL, found.group(0).strip(),
            "This is upstream ECWolf, not EC7Wolf. Corridor 7 support is in the fork.",
        )
    else:
        first = text.strip().splitlines()[0] if text.strip() else "no output"
        report.add("Engine identity", FAIL, first,
                   "This does not identify itself as EC7Wolf.")
    return report


def engine_version(report: Report) -> str:
    """Pull the version string out of a probed engine report, if there is one."""
    for check in report:
        if check.name == "Engine identity" and check.status == OK:
            return check.detail
    return ""


def check_workspace(directory: Path | str, *, data_dir: Path | str = "") -> Report:
    """Check the workspace: writable, and not inside the game data."""
    report = Report()
    directory = Path(directory).expanduser()

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        report.add("Workspace", FAIL, f"cannot create {directory}: {error}",
                   "Choose a folder you can write to.")
        return report

    if not os.access(directory, os.W_OK):
        report.add("Workspace", FAIL, f"{directory} is not writable",
                   "Choose a folder you can write to.")
        return report
    report.add("Workspace", OK, str(canonical(directory)))

    resolved = canonical(directory)
    if looks_like_game_data(resolved):
        report.add(
            "Separation", FAIL, f"{resolved} holds game data",
            "Keep projects out of the game directory so an export can never "
            "land on the originals.",
        )
    elif data_dir:
        data_resolved = canonical(data_dir)
        if resolved == data_resolved or resolved.is_relative_to(data_resolved):
            report.add("Separation", FAIL, f"{resolved} is inside {data_resolved}",
                       "Choose a workspace outside the game data directory.")
        else:
            report.add("Separation", OK, "workspace and game data are separate")
    else:
        report.add("Separation", OK, "no game data here")
    return report


def check_profile(profile: Profile, *, probe: bool = False) -> Report:
    """The whole first-run checklist, in the order the page shows it."""
    report = Report()
    if profile.engine_path:
        # The engine reads its data from the working directory, so a probe runs
        # there when we know it -- otherwise it reports a missing IWAD rather
        # than its version.
        report.checks.extend(
            check_engine(profile.engine_path, probe=probe, cwd=profile.data_dir or None)
        )
    if profile.data_dir:
        report.checks.extend(check_data_directory(profile.data_dir))
    if profile.workspace_dir:
        report.checks.extend(
            check_workspace(profile.workspace_dir, data_dir=profile.data_dir)
        )
    if not report.checks:
        report.add("Profile", FAIL, "nothing has been chosen yet",
                   "Pick an engine, a game-data directory and a workspace.")
    return report


def candidate_engines(start: Path | str | None = None) -> list[Path]:
    """Places an EC7Wolf build plausibly is, relative to this checkout.

    Deliberately a short list of specific places rather than a search. The
    editor suggesting three paths that might be right is helpful; the editor
    walking somebody's home directory is not.
    """
    root = Path(start) if start else workspace_root()
    names = ("ec7wolf", "ec7wolf.exe")
    places = [
        root / "builds" / "release",
        root / "builds" / "release-build",
        root / "build",
        Path.cwd(),
    ]
    found = []
    for place in places:
        for name in names:
            candidate = place / name
            if candidate.is_file() and candidate not in found:
                found.append(candidate)
    return found


def candidate_data_dirs(start: Path | str | None = None) -> list[Path]:
    """Likewise for the game data: named places, never a scan."""
    root = Path(start) if start else workspace_root()
    places = [
        root / "corr7" / "CORR7CD",
        root / "builds" / "release",
        Path.cwd(),
    ]
    return [place for place in places if place.is_dir() and looks_like_game_data(place)]


def default_workspace() -> Path:
    """Where projects go unless the user says otherwise."""
    return Path.home() / "EC7Edit Projects"
