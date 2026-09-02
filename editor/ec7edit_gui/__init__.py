# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""EC7Edit's Qt layer.

This package depends on `ec7edit_core`. The core never depends on this one:
every format, rule and document operation stays testable headless, and the GUI
is a view over them rather than a place where behavior hides.

Nothing here mutates a document directly. Edits go through commands, so undo
works and so the same operation is available from the command line.
"""

from __future__ import annotations

__all__ = []
