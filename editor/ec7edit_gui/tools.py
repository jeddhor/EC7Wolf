# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The tool controller: pointer gestures to commands, and nothing in between.

Every tool ends the same way -- a list of `(plane, x, y, value)` writes handed
to one command. That is what makes undo uniform: a flood fill, a dragged line
and a single click are the same kind of thing to the history, and none of them
needed its own inverse.

A drag is one undo step. The controller opens a gesture on press, tags every
command with it, and closes it on release, so the history coalesces the stroke.
Ctrl+Z takes back the line you drew, not the last cell of it.

Which plane a tool writes is the *catalogue's* decision, not the tool's. A wall
brush and an enemy brush are the same code; the difference is that the entry
says plane 0 or plane 1, which is why placing a door and placing an alien did
not need two implementations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal

from ec7edit_core.catalog import CatalogEntry
from ec7edit_core.commands import Command, write_words
from ec7edit_core.document import MapDocument
from ec7edit_core.tools import (
    FILL_BUDGET,
    flood_cells,
    line_cells,
    pick,
    rectangle_bounds,
    rectangle_cells,
)

#: Corridor 7's empty object marker, which is what erasing plane 1 writes.
EMPTY_OBJECT = 18


class Tool(Enum):
    POINTER = "pointer"
    BRUSH = "brush"
    LINE = "line"
    RECTANGLE = "rectangle"
    FILL = "fill"
    ERASER = "eraser"
    EYEDROPPER = "eyedropper"

    @property
    def label(self) -> str:
        return {
            Tool.POINTER: "Select",
            Tool.BRUSH: "Paint",
            Tool.LINE: "Line",
            Tool.RECTANGLE: "Rectangle",
            Tool.FILL: "Fill",
            Tool.ERASER: "Erase",
            Tool.EYEDROPPER: "Pick",
        }[self]

    @property
    def shortcut(self) -> str:
        return {
            Tool.POINTER: "S", Tool.BRUSH: "B", Tool.LINE: "L",
            Tool.RECTANGLE: "R", Tool.FILL: "F", Tool.ERASER: "E",
            Tool.EYEDROPPER: "I",
        }[self]


@dataclass
class Selection:
    """A rectangle of cells, in map coordinates."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def cells(self):
        for y in range(self.y, self.y + self.height):
            for x in range(self.x, self.x + self.width):
                yield x, y


class ToolController(QObject):
    """Turns canvas events into commands, one gesture at a time."""

    #: Emitted with a command the window should run.
    command_ready = Signal(object)
    #: The eyedropper found this raw value on this plane.
    picked = Signal(int, int)
    #: The selection changed.
    selection_changed = Signal(object)
    #: Something worth saying in the status bar.
    message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tool = Tool.BRUSH
        self.entry: CatalogEntry | None = None
        self.document: MapDocument | None = None
        self.selection = Selection()
        self.filled_rectangle = False
        self._gesture = ""
        self._anchor: tuple[int, int] | None = None
        self._preview: list[tuple[int, int]] = []

    # -- configuration ----------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self._anchor = None
        self.message.emit(f"{tool.label} tool")

    def set_entry(self, entry: CatalogEntry | None) -> None:
        self.entry = entry

    def set_document(self, document: MapDocument | None) -> None:
        """Point at a map, or at a newer snapshot of the one already open.

        Only a *different* map abandons the gesture in progress. Documents are
        immutable, so every edit produces a new snapshot and the window hands
        it over mid-stroke; clearing the anchor on those refreshes ended every
        drag after its first cell.
        """
        changed = (
            document is None
            or self.document is None
            or document.uuid != self.document.uuid
        )
        self.document = document
        if changed:
            self._anchor = None
            self._gesture = ""

    # -- what a tool writes -----------------------------------------------

    @property
    def target_plane(self) -> int:
        """The plane the current entry lives on. Zero when nothing is chosen."""
        return self.entry.plane if self.entry else 0

    def _value(self) -> int | None:
        if self.tool is Tool.ERASER:
            return EMPTY_OBJECT if self.target_plane == 1 else 0
        if self.entry is None:
            return None
        return self.entry.value

    def _writes(self, cells) -> list[tuple[int, int, int, int]]:
        value = self._value()
        if value is None or self.document is None:
            return []
        plane = self.target_plane
        return [(plane, x, y, value) for x, y in cells]

    def _emit(self, cells, label: str) -> None:
        writes = self._writes(cells)
        if not writes:
            return
        command = write_words(self.document, writes, label=label, gesture=self._gesture)
        if command.changes_anything:
            self.command_ready.emit(command)

    # -- events -----------------------------------------------------------

    def press(self, x: int, y: int, button: int) -> None:
        if self.document is None:
            return
        # A gesture id per stroke: the history coalesces commands that share
        # one, so a drag is a single undo step.
        self._gesture = uuid.uuid4().hex
        self._anchor = (x, y)

        if self.tool is Tool.EYEDROPPER:
            # Pick what is actually there, most specific first: an object if
            # the cell holds one, otherwise the wall or floor under it. Picking
            # from whichever plane the *previous* selection happened to use
            # would make the tool depend on invisible state.
            for plane in (1, 0):
                value = pick(self.document, plane, x, y)
                if value is None or (plane == 1 and value in (0, EMPTY_OBJECT)):
                    continue
                self.picked.emit(plane, value)
                self.message.emit(f"Picked {value} from plane {plane}")
                return
            self.message.emit("Nothing to pick here")
            return

        if self.tool is Tool.POINTER:
            self.selection = Selection(x, y, 1, 1)
            self.selection_changed.emit(self.selection)
            return

        if self.tool is Tool.FILL:
            cells, truncated = flood_cells(self.document, self.target_plane, x, y)
            self._emit(cells, "Fill")
            self.message.emit(
                f"Filled {len(cells)} cells"
                + (f" (stopped at the {FILL_BUDGET}-cell limit)" if truncated else "")
            )
            return

        if self.tool in (Tool.BRUSH, Tool.ERASER):
            self._emit([(x, y)], self.tool.label)

    def drag(self, x: int, y: int, button: int) -> None:
        if self.document is None or self._anchor is None:
            return

        if self.tool is Tool.POINTER:
            bounds = rectangle_bounds(*self._anchor, x, y)
            self.selection = Selection(*bounds)
            self.selection_changed.emit(self.selection)
            return

        if self.tool in (Tool.BRUSH, Tool.ERASER):
            # Straight from the last cell, so a fast drag does not leave gaps
            # where the pointer skipped between events.
            cells = line_cells(*self._anchor, x, y)
            self._emit(cells, self.tool.label)
            self._anchor = (x, y)

    def release(self, x: int, y: int) -> None:
        if self.document is None or self._anchor is None:
            self._gesture = ""
            return

        if self.tool is Tool.LINE and x >= 0:
            self._emit(line_cells(*self._anchor, x, y), "Line")
        elif self.tool is Tool.RECTANGLE and x >= 0:
            self._emit(
                rectangle_cells(*self._anchor, x, y, filled=self.filled_rectangle),
                "Rectangle",
            )
        self._anchor = None
        self._gesture = ""
