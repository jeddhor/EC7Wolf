# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""EC7Edit core: the Qt-free half of the Corridor 7 level editor.

Nothing in this package may import Qt. The GUI depends on the core; the core
never depends on the GUI, so every format contract stays testable headless and
every editor operation stays scriptable.

The byte formats implemented here are documented in
`editor/docs/native-formats.md` and reconciled against the engine loader in
`src/resourcefiles/file_gamemaps.cpp`.
"""

from __future__ import annotations

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    """`__version__`, computed the first time anybody reads it.

    PEP 562. The version is the engine's -- `1.0-betaN`, counted from the same
    commit -- and in a checkout that means asking git. Doing it at import time
    would put a subprocess in front of every `import ec7edit_core`, including
    the several hundred a test run does.
    """
    if name in ("__version__", "__pep440__"):
        from .version import pep440, version
        return pep440() if name == "__pep440__" else version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
