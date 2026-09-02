# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Where the editor's own files are, whether it was frozen or not.

Two ways EC7Edit runs, and they disagree about every path that is not absolute.

From a checkout, `ec7edit_core/x.py` sits two levels below the editor tree, so
`resources/` is `parents[1]`. Frozen by PyInstaller, that same module lives
inside a bundle, `parents[1]` is somewhere under `_internal`, and the answer is
whatever `sys._MEIPASS` says. Guessing wrong is not a crash -- it is an editor
that starts with an empty palette and no explanation, because the catalogue it
could not find is read through a path that simply does not exist.

So both questions are asked here, once, and every caller asks this instead of
computing a relative path of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    """Whether this is a packaged build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """The directory holding `resources/`.

    PyInstaller unpacks declared data under `sys._MEIPASS`; onedir puts that in
    `_internal` beside the executable, onefile in a temporary directory. Either
    way the attribute is the answer, and neither is guessable from `__file__`.
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def catalog_path() -> Path:
    """The editor catalogue, wherever this build keeps it."""
    return resource_root() / "resources" / "editor_catalog.json"


def workspace_root() -> Path:
    """Where to look for a sibling EC7Wolf build and game data.

    From a checkout this is the containing workspace -- three levels above this
    file -- which is how the first-run page can offer `builds/release` without
    searching anyone's home directory. A packaged editor has no checkout above
    it, so it looks beside itself instead: someone who unpacked the editor next
    to their game has done the same thing, and the suggestions are as useful.
    """
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]
