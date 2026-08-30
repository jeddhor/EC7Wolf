# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Building the command line that launches a playtest -- as data, not a string.

A launch is an argument *vector*, never a shell string. There is no quoting to
get wrong, no path with a space to break it, and nothing a project file could
put in a filename that would become a command. A project is untrusted input;
the only things from it that reach this are a map slot number and a WAD the
editor wrote itself.

The plan is returned rather than run, so the GUI can show the user exactly what
it is about to do, and so a test can assert on the arguments without starting a
game.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import Diagnostic, Ec7EditError, Severity

#: The engine wants the *extension* of its data files here, not a path. This is
#: the distinction that confuses everyone once: `--data CO7` selects Corridor 7,
#: and the directory comes from the working directory.
DATA_EXTENSION = "CO7"

_MARKER = re.compile(r"^MAP[0-9]{2,3}$")


class LaunchError(Ec7EditError):
    pass


def _error(message: str) -> LaunchError:
    return LaunchError(Diagnostic("C7E-ENGINE-001", Severity.ERROR, message))


@dataclass(frozen=True)
class LaunchPlan:
    """Everything needed to start a playtest, and nothing else."""

    executable: Path
    arguments: list[str]
    cwd: Path
    environment: dict = field(default_factory=dict)

    @property
    def argv(self) -> list[str]:
        return [str(self.executable), *self.arguments]

    def described(self) -> str:
        """What to show the user before running it."""
        return f"{self.cwd}$ {' '.join(self.argv)}"


def build_launch_plan(
    *,
    executable: Path | str,
    data_dir: Path | str,
    preview_wad: Path | str,
    marker: str = "MAP01",
    skill: int = 2,
    extra: list[str] | None = None,
) -> LaunchPlan:
    """The playtest command for one map of one preview WAD.

    `--file` last, because a WAD loaded later overrides the base data by lump
    name -- which is the entire mechanism by which the edit reaches the game.
    """
    executable = Path(executable).expanduser()
    data_dir = Path(data_dir).expanduser()
    preview = Path(preview_wad).expanduser()

    if not executable.is_file():
        raise _error(f"no engine at {executable}")
    if not data_dir.is_dir():
        raise _error(f"no game data directory at {data_dir}")
    if not preview.is_file():
        raise _error(f"no preview WAD at {preview}")
    if not _MARKER.match(marker):
        raise _error(f"{marker!r} is not a map marker the engine generates")
    if not 1 <= skill <= 4:
        raise _error(f"skill {skill} is outside 1..4")

    arguments = [
        "--data", DATA_EXTENSION,
        "--tedlevel", marker,
        "--skill", str(skill),
        "--file", str(preview.resolve()),
    ]
    if extra:
        arguments.extend(str(item) for item in extra)

    return LaunchPlan(
        executable=executable.resolve(),
        arguments=arguments,
        # The engine finds its data in the working directory, which is why this
        # runs there rather than passing a path it has no argument for.
        cwd=data_dir.resolve(),
    )
