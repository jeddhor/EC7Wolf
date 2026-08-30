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

__version__ = "0.1.0"
__all__ = ["__version__"]
