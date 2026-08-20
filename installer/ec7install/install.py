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
import shutil
import subprocess
import time
from pathlib import Path

from . import proc
from .identity import (APP_NAME, UNINSTALL_KEY, WM_CLASS, host_platform,
                       is_windows)
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

# What belongs to the player rather than to the installer, and therefore
# survives a reinstall. The launcher puts both of these inside the install
# folder deliberately, which is what makes them vulnerable to replacing it.
PLAYER_FILES = ("saves", "ec7wolf.cfg")

# The executable carries the palette the game reads at runtime, so its identity
# matters: budget and cracked builds move the embedded offsets.
CD_EXECUTABLE_SIZE = 250776

MANIFEST_NAME = ".ec7wolf-install.json"


class InstallError(Exception):
    pass


def default_destination() -> Path:
    """Under the user's own home, so the installer never needs to elevate."""
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "EC7Wolf"
    if host_platform() == "macos":
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

    def carry_over(self, reporter: Reporter) -> list[str]:
        """Bring the player's own files forward from an install being replaced.

        Everything else in the folder belongs to the installer and is about to
        be written fresh; these belong to whoever has been playing. They are
        copied into the staging tree *before* anything is moved or deleted, so
        a failure here costs nothing -- the old install is still standing.

        Without this the reinstall path silently destroyed saved games while
        the wizard was telling the user, in as many words, that it would keep
        them.
        """
        if not self.destination.is_dir():
            return []

        carried = []
        for relative in PLAYER_FILES:
            source = self.destination / relative
            target = self.path / relative
            if not source.exists() or target.exists():
                continue
            try:
                if source.is_dir():
                    shutil.copytree(source, target)
                    count = sum(1 for f in source.rglob("*") if f.is_file())
                    reporter.detail(f"keeping {relative} ({count} file(s))"
                                    if count != 1 else f"keeping {relative} (1 file)")
                else:
                    shutil.copy2(source, target)
                    reporter.detail(f"keeping {relative}")
                carried.append(relative)
            except OSError as error:
                # Refuse to continue: the next step deletes the original, and
                # quietly losing someone's saved games is worse than stopping.
                raise InstallError(
                    f"could not preserve {relative} from the existing install: "
                    f"{error}. Nothing has been changed; copy that folder "
                    "somewhere safe and try again.")
        return carried

    def commit(self, reporter: Reporter) -> Path:
        """Move the staging tree into place, replacing any previous install."""
        self.carry_over(reporter)

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
                f"could not move the finished install into {self.destination}: "
                f"{error}. Anything that was already there has been put back. "
                "This is usually a permissions problem, or the destination "
                "being on a different filesystem that is now full.")
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
    if is_windows():
        path = destination / "EC7Wolf.cmd"
        # write_bytes, not write_text: text mode translates \n to os.linesep,
        # so on Windows -- the only place this file is ever used -- these \r\n
        # pairs would each become \r\r\n. cmd tolerates a lot, but there is no
        # reason to write a file wrong and hope.
        path.write_bytes(_crlf(
            "@echo off\r\n"
            "setlocal\r\n"
            "cd /d \"%~dp0\"\r\n"
            "if not exist \"%~dp0saves\" mkdir \"%~dp0saves\"\r\n"
            "\"%~dp0ec7wolf.exe\" --data CO7 --config \"%~dp0ec7wolf.cfg\" "
            "--savedir \"%~dp0saves\" %*\r\n"))
        return path

    path = destination / "run-ec7wolf.sh"
    path.write_text(
        "#!/bin/sh\n"
        "# Launch EC7Wolf with its configuration and saves kept beside it.\n"
        "here=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "mkdir -p \"$here/saves\"\n"
        "\n"
        "# Tell SDL what to call the window. Without this the class comes from\n"
        "# argv[0] and reads \"ec7wolf\", which matches neither the desktop\n"
        "# file's name nor the AppStream id -- and a task manager that cannot\n"
        "# match the window to the entry falls back to a generic icon and\n"
        "# refuses to group the two. Measured with xprop, not assumed.\n"
        f"SDL_VIDEO_X11_WMCLASS={WM_CLASS}\n"
        f"SDL_VIDEO_WAYLAND_WMCLASS={WM_CLASS}\n"
        "export SDL_VIDEO_X11_WMCLASS SDL_VIDEO_WAYLAND_WMCLASS\n"
        "\n"
        "cd \"$here\"\n"
        "exec \"$here/ec7wolf\" --data CO7 --config \"$here/ec7wolf.cfg\" "
        "--savedir \"$here/saves\" \"$@\"\n")
    path.chmod(0o755)
    return path


def _crlf(text: str) -> bytes:
    """A cmd script's exact bytes, CRLF endings and all."""
    return text.encode("utf-8")


def shell_quote(text: str) -> str:
    """POSIX single-quoting, for paths baked into the generated uninstaller."""
    return "'" + text.replace("'", "'\\''") + "'"


def write_uninstaller(destination: Path, shortcuts: list[Path]) -> Path:
    """A remover that lives inside the install and needs nothing else.

    The CLI can already uninstall, but only from a checkout of the source tree,
    and someone who installed a game a year ago has no reason to still have one.
    The list of shortcuts is baked in at install time rather than parsed back
    out of the manifest, because the plan knows exactly what it created and a
    shell script that has to parse JSON to decide what to delete is a shell
    script waiting to delete the wrong thing.
    """
    if is_windows():
        path = destination / "Uninstall.cmd"
        removals = "".join(
            f'if exist "{p}" del /q "{p}"\r\n' for p in shortcuts)
        path.write_bytes(_crlf(
            "@echo off\r\n"
            "setlocal\r\n"
            f"rem Remove this {APP_NAME} install, the shortcuts it created and\r\n"
            "rem its Add/Remove Programs entry. Pass --yes to skip the question,\r\n"
            "rem which is what QuietUninstallString in the registry does.\r\n"
            "\r\n"
            "echo This removes:\r\n"
            "echo   %~dp0\r\n"
            + "".join(f"echo   {p}\r\n" for p in shortcuts) +
            "\r\n"
            "if exist \"%~dp0saves\" (\r\n"
            "  echo.\r\n"
            "  echo Saved games are inside this folder, in %~dp0saves.\r\n"
            "  echo Copy them somewhere else first if you want to keep them.\r\n"
            ")\r\n"
            "\r\n"
            "if /i \"%~1\"==\"--yes\" goto remove\r\n"
            "if /i \"%~1\"==\"/S\" goto remove\r\n"
            "echo.\r\n"
            "set /p answer=Remove it? [y/N] \r\n"
            "if /i not \"%answer%\"==\"y\" (\r\n"
            "  echo Nothing was removed.\r\n"
            "  exit /b 1\r\n"
            ")\r\n"
            "\r\n"
            ":remove\r\n"
            + removals +
            f"reg delete \"HKCU\\{UNINSTALL_KEY}\" /f >nul 2>&1\r\n"
            "\r\n"
            "rem Delete the folder from outside it: cmd holds its own script\r\n"
            "rem file open, so a plain rmdir of %~dp0 leaves the script behind.\r\n"
            "set target=%~dp0\r\n"
            "cd /d \"%~dp0..\"\r\n"
            "start \"\" /min cmd /c \"timeout /t 1 >nul & rmdir /s /q \"%target%\"\"\r\n"
            f"echo {APP_NAME} was removed.\r\n"))
        return path

    removals = "".join(f'rm -f {shell_quote(str(p))}\n' for p in shortcuts)
    path = destination / "uninstall.sh"
    path.write_text(
        "#!/bin/sh\n"
        f"# Remove this {APP_NAME} install, and the shortcuts it created.\n"
        "#\n"
        "# Written by the installer, with the shortcut list already filled in.\n"
        "# Pass --yes to skip the question.\n"
        "set -eu\n"
        "\n"
        "here=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "\n"
        "printf 'This removes:\\n'\n"
        "printf '  %s\\n' \"$here\"\n"
        + "".join(f"printf '  %s\\n' {shell_quote(str(p))}\n"
                  for p in shortcuts) +
        "\n"
        "# Saved games live inside the install, so say so before taking it away.\n"
        "if [ -d \"$here/saves\" ]; then\n"
        "\tsaves=$(find \"$here/saves\" -type f 2>/dev/null | wc -l)\n"
        "\tif [ \"$saves\" -gt 0 ]; then\n"
        "\t\tif [ \"$saves\" -eq 1 ]; then word=file; else word=files; fi\n"
        "\t\tprintf '\\nThis includes %s saved game %s in %s.\\n' "
        "\"$saves\" \"$word\" \"$here/saves\"\n"
        "\t\tprintf 'Copy them somewhere else first if you want to keep them.\\n'\n"
        "\tfi\n"
        "fi\n"
        "\n"
        "if [ \"${1:-}\" != \"--yes\" ]; then\n"
        "\tprintf '\\nRemove it? [y/N] '\n"
        "\tread -r answer\n"
        "\tcase $answer in\n"
        "\t\ty|Y|yes|YES) ;;\n"
        "\t\t*) printf 'Nothing was removed.\\n'; exit 1 ;;\n"
        "\tesac\n"
        "fi\n"
        "\n"
        + removals +
        "\n"
        "if command -v update-desktop-database >/dev/null 2>&1; then\n"
        "\tupdate-desktop-database \"$HOME/.local/share/applications\" "
        "2>/dev/null || true\n"
        "fi\n"
        "\n"
        "# Leave the directory before removing it, or the shell is standing in a\n"
        "# folder that no longer exists.\n"
        "cd \"$here/..\"\n"
        "rm -rf \"$here\"\n"
        f"printf '{APP_NAME} was removed.\\n'\n")
    path.chmod(0o755)
    return path


def uninstall(destination: Path, reporter: Reporter) -> None:
    """Remove an install and anything it registered outside its own folder."""
    destination = Path(destination)
    manifest = read_manifest(destination)
    if manifest is None:
        raise InstallError(
            f"{destination} does not look like an EC7Wolf install: it has no "
            f"{MANIFEST_NAME}. Point this at the folder the installer created, "
            "so that nothing else gets deleted by mistake.")

    for shortcut in manifest.get("shortcuts", []):
        target = Path(shortcut)
        if target.exists():
            reporter.detail(f"removing {target}")
            try:
                target.unlink()
            except OSError as error:
                reporter.warn(f"could not remove {target}: {error}. "
                              "Everything else was removed; delete that one "
                              "by hand.")

    if is_windows():
        from . import windows
        windows.unregister_uninstall()
        reporter.detail("removed the Add/Remove Programs entry")

    reporter.detail(f"removing {destination}")
    shutil.rmtree(destination, ignore_errors=True)

    if host_platform() == "linux" and shutil.which("update-desktop-database"):
        applications = Path.home() / ".local" / "share" / "applications"
        subprocess.run(["update-desktop-database", str(applications)],
                       capture_output=True, **proc.quiet())
