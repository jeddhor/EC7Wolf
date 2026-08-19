"""Assembling the install: what goes where, and how to undo it.

Nothing is written into the destination until every piece has been gathered in
a staging directory beside it and the final move is a rename. That is how
tools/package_corridor7_release.sh already works, and for the same reason: a
cancelled or failed install must not leave a half-populated folder that looks
like a working one.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from .progress import Reporter

# The eight files the engine will not start without, established from
# LookForGameData's table in wl_iwad.cpp and verified by running the game from a
# directory holding these and nothing else. See docs/corridor7.md.
REQUIRED_DATA = (
    "CORR7CD.EXE",
    "MAPTEMP.CO7",
    "GFXTILES.CO7",
    "VGADICT.CO7",
    "VGAHEAD.CO7",
    "VGAGRAPH.CO7",
    "AUDIOHED.CO7",
    "AUDIOT.CO7",
)

# Optional, and the only optional one: the game starts without it and falls back
# to the AdLib effects in AUDIOT, but it holds the 100 digitized sounds that are
# most of what Corridor 7 sounds like.
OPTIONAL_DATA = ("AUDIOMUS.CO7",)

CINEMATICS = ("SEQONE.CO7", "SEQTHREE.CO7", "SEQFOUR.CO7")

# The executable carries the palette the game reads at runtime, so its identity
# matters: budget and cracked builds move the embedded offsets.
CD_EXECUTABLE_SIZE = 250776

MANIFEST_NAME = ".ec7wolf-install.json"


class InstallError(Exception):
    pass


def default_destination() -> Path:
    """Under the user's own home, so the installer never needs to elevate."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "EC7Wolf"
    if platform.system() == "Darwin":
        return Path.home() / "Applications" / "EC7Wolf"
    # Deliberately NOT XDG_DATA_HOME. That variable is right for user data, but
    # this is an application install, and a sandboxed launcher sets it to its
    # own private tree: run from inside a snapped editor it resolves to
    # ~/snap/<app>/<rev>/.local/share, which the user cannot launch from a
    # normal shell. Observed, not hypothetical. The desktop entry written later
    # carries an absolute path, so nothing needs XDG to find this.
    return Path.home() / ".local" / "share" / "ec7wolf"


def free_space(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def estimate_size(with_music: bool, with_video: bool) -> int:
    """Roughly what the finished install will occupy, for the space check."""
    total = 6 * 1024 * 1024        # engine + pk3
    total += 6 * 1024 * 1024       # the required data files
    total += 2 * 1024 * 1024       # AUDIOMUS
    if with_video:
        total += 27 * 1024 * 1024
    if with_music:
        total += 40 * 1024 * 1024  # four ogg tracks at the disc's lengths
    return total


class Staging:
    """A directory being built up, then moved into place in one step."""

    def __init__(self, destination: Path):
        self.destination = Path(destination)
        parent = self.destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        self.path = parent / f".{self.destination.name}.staging.{os.getpid()}"
        if self.path.exists():
            shutil.rmtree(self.path)
        self.path.mkdir(parents=True)
        self._files: list[str] = []

    def write(self, relative: str, data: bytes) -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self._files.append(relative)
        return target

    def copy(self, source: Path, relative: str) -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self._files.append(relative)
        return target

    def note(self, relative: str) -> None:
        """Record a file written into the staging tree by someone else."""
        self._files.append(relative)

    @property
    def files(self) -> list[str]:
        return sorted(set(self._files))

    def commit(self, reporter: Reporter) -> Path:
        """Move the staging tree into place, replacing any previous install."""
        previous = None
        if self.destination.exists():
            previous = self.destination.with_name(
                f".{self.destination.name}.previous.{os.getpid()}")
            reporter.detail(f"replacing the existing install at {self.destination}")
            self.destination.rename(previous)
        try:
            self.path.rename(self.destination)
        except OSError as error:
            if previous is not None:
                previous.rename(self.destination)
            raise InstallError(
                f"could not move the staged install into {self.destination}: {error}")
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
        return self.destination

    def abandon(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def write_manifest(destination: Path, entries: dict) -> Path:
    """What was installed, so the uninstaller can undo exactly that."""
    manifest = {
        "product": "EC7Wolf",
        "installed": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "destination": str(destination),
        **entries,
    }
    path = destination / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2))
    return path


def read_manifest(destination: Path) -> dict | None:
    path = Path(destination) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_launcher(destination: Path) -> Path:
    """A launcher that keeps config and saves inside the install folder.

    Without it the engine writes to the user's global config, which is fine
    until they also have a system ECWolf -- and then the two fight over the same
    file. Self-contained is the behaviour tools/package_corridor7_release.sh
    already gives its releases.
    """
    if platform.system() == "Windows":
        path = destination / "EC7Wolf.cmd"
        path.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            "cd /d \"%~dp0\"\r\n"
            "if not exist \"%~dp0saves\" mkdir \"%~dp0saves\"\r\n"
            "\"%~dp0ec7wolf.exe\" --data CO7 --config \"%~dp0ec7wolf.cfg\" "
            "--savedir \"%~dp0saves\" %*\r\n")
        return path

    path = destination / "run-ec7wolf.sh"
    path.write_text(
        "#!/bin/sh\n"
        "# Launch EC7Wolf with its configuration and saves kept beside it.\n"
        "here=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "mkdir -p \"$here/saves\"\n"
        "cd \"$here\"\n"
        "exec \"$here/ec7wolf\" --data CO7 --config \"$here/ec7wolf.cfg\" "
        "--savedir \"$here/saves\" \"$@\"\n")
    path.chmod(0o755)
    return path


def uninstall(destination: Path, reporter: Reporter) -> None:
    """Remove an install and anything it registered outside its own folder."""
    destination = Path(destination)
    manifest = read_manifest(destination)
    if manifest is None:
        raise InstallError(f"{destination} does not look like an EC7Wolf install")

    for shortcut in manifest.get("shortcuts", []):
        target = Path(shortcut)
        if target.exists():
            reporter.detail(f"removing {target}")
            try:
                target.unlink()
            except OSError as error:
                reporter.warn(f"could not remove {target}: {error}")

    reporter.detail(f"removing {destination}")
    shutil.rmtree(destination, ignore_errors=True)

    if platform.system() == "Linux" and shutil.which("update-desktop-database"):
        applications = Path.home() / ".local" / "share" / "applications"
        subprocess.run(["update-desktop-database", str(applications)],
                       capture_output=True)
