# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The map canvas: draws a Corridor 7 floor and says which cell you are on.

Corridor 7 maps are 64x64, so the whole thing fits on screen at a readable zoom
and there is no need for tiling, level-of-detail, or a scene graph. The canvas
paints cells directly, which keeps the code small enough to be obviously
correct about the one thing that matters: that the cell under the pointer is
the cell that gets edited.

Two layers, both optional:

* **texture** -- each cell drawn as the average colour of its wall page, which
  reads like the map;
* **schematic** -- walls, floor, doors and objects as flat shapes, which reads
  like a plan and works with no game data at all.

The schematic layer is what makes the editor usable before discovery has found
anything, and what makes these tests runnable on a machine with no right to the
artwork.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ec7edit_core.catalog import Catalog
from ec7edit_core.document import MapDocument

#: Zoom is in pixels per cell. Below four a 64x64 map is unreadable; above
#: forty it stops being a map and starts being a spreadsheet.
MIN_ZOOM = 4
MAX_ZOOM = 40
DEFAULT_ZOOM = 12

#: Plane-1 word for "nothing here". Corridor 7 uses 18, not zero.
EMPTY_OBJECT = 18

_SCHEMATIC = {
    "wall": QColor(96, 100, 110),
    "floor": QColor(28, 30, 36),
    "door": QColor(196, 152, 64),
    "special": QColor(120, 140, 200),
    "zone": QColor(40, 52, 44),
    "object": QColor(210, 210, 190),
    "enemy": QColor(206, 88, 76),
    "start": QColor(96, 200, 120),
    "unknown": QColor(150, 60, 150),
}


class MapCanvas(QWidget):
    """Renders one map. Editing arrives in E5; this is the view it edits."""

    #: (x, y) under the pointer, or (-1, -1) when it leaves.
    hovered = Signal(int, int)
    #: (x, y, button) on press, for the tools E5 adds.
    pressed = Signal(int, int, int)
    dragged = Signal(int, int, int)
    released = Signal(int, int)
    zoom_changed = Signal(int)

    def __init__(self, document: MapDocument | None = None, catalog: Catalog | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._document = document
        self._catalog = catalog
        self._zoom = DEFAULT_ZOOM
        self._show_grid = True
        self._show_objects = True
        self._hover = (-1, -1)
        #: The snapshot camera, when it belongs to the map this canvas shows.
        #: `(x, y, angle)` in map coordinates -- a view of the map rather than
        #: anything in it, so it is drawn and never written.
        self._camera: tuple[float, float, float] | None = None
        self._swatches: dict[int, QColor] = {}
        self._button = Qt.NoButton

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Map canvas")
        self.setAutoFillBackground(True)
        self._resize_to_document()

    # -- content ----------------------------------------------------------

    @property
    def document(self) -> MapDocument | None:
        return self._document

    def set_document(self, document: MapDocument | None) -> None:
        self._document = document
        self._resize_to_document()
        self.update()

    def set_camera(self, camera) -> None:
        """Show the snapshot camera here, or nowhere if `camera` is None.

        Placing the camera used to be completely invisible: nothing was drawn,
        so a click did its job and looked like it had done nothing, taking a
        snapshot looked like it had lost the camera, and placing a second one
        looked like it had failed as well. All three were working.
        """
        value = None if camera is None else (camera.x, camera.y, camera.angle)
        if value == self._camera:
            return
        self._camera = value
        self.update()

    def set_catalog(self, catalog: Catalog | None) -> None:
        self._catalog = catalog
        self.update()

    def set_wall_colours(self, colours: dict[int, QColor]) -> None:
        """Average colours per plane-0 value, for the texture layer."""
        self._swatches = dict(colours)
        self.update()

    # -- view -------------------------------------------------------------

    @property
    def zoom(self) -> int:
        return self._zoom

    def set_zoom(self, zoom: int) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, int(zoom)))
        if zoom != self._zoom:
            self._zoom = zoom
            self._resize_to_document()
            self.update()
            self.zoom_changed.emit(zoom)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom + 2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom - 2)

    def fit_to(self, size: QSize) -> None:
        if not self._document:
            return
        longest = max(self._document.width, self._document.height)
        if longest:
            self.set_zoom(max(1, min(size.width(), size.height()) // longest))

    @property
    def show_grid(self) -> bool:
        return self._show_grid

    def set_show_grid(self, show: bool) -> None:
        self._show_grid = bool(show)
        self.update()

    def set_show_objects(self, show: bool) -> None:
        self._show_objects = bool(show)
        self.update()

    def _resize_to_document(self) -> None:
        if self._document is None:
            self.setFixedSize(QSize(200, 200))
            return
        self.setFixedSize(
            QSize(self._document.width * self._zoom, self._document.height * self._zoom)
        )

    # -- coordinates ------------------------------------------------------

    def cell_at(self, point: QPoint) -> tuple[int, int]:
        """Which cell a widget point is over, or (-1, -1) for none.

        The one piece of arithmetic in this file that must be right: everything
        the user paints depends on it agreeing with what they see.
        """
        if self._document is None or self._zoom <= 0:
            return (-1, -1)
        x, y = point.x() // self._zoom, point.y() // self._zoom
        if 0 <= x < self._document.width and 0 <= y < self._document.height:
            return (int(x), int(y))
        return (-1, -1)

    def cell_rect(self, x: int, y: int) -> QRect:
        return QRect(x * self._zoom, y * self._zoom, self._zoom, self._zoom)

    @property
    def hovered_cell(self) -> tuple[int, int]:
        return self._hover

    # -- painting ---------------------------------------------------------

    def _colour_for(self, plane0: int, plane1: int) -> QColor:
        if plane0 == 0:
            return _SCHEMATIC["zone"] if plane1 and plane1 != EMPTY_OBJECT else _SCHEMATIC["floor"]
        swatch = self._swatches.get(plane0)
        if swatch is not None:
            return swatch
        if self._catalog is not None:
            entry = self._catalog.for_value(0, plane0)
            if entry is None:
                return _SCHEMATIC["unknown"]
            if entry.category == "specials":
                return _SCHEMATIC["door"] if entry.subcategory == "door" \
                    else _SCHEMATIC["special"]
            if entry.category == "zones":
                return _SCHEMATIC["zone"]
        return _SCHEMATIC["wall"]

    def _object_colour(self, value: int) -> QColor | None:
        if not value or value == EMPTY_OBJECT:
            return None
        if self._catalog is None:
            return _SCHEMATIC["object"]
        entry = self._catalog.for_value(1, value)
        if entry is None:
            return _SCHEMATIC["unknown"]
        return {
            "enemies": _SCHEMATIC["enemy"],
            "starts": _SCHEMATIC["start"],
            "objects": _SCHEMATIC["object"],
            "specials": _SCHEMATIC["special"],
            "zones": _SCHEMATIC["special"],
        }.get(entry.category, _SCHEMATIC["object"])

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), _SCHEMATIC["floor"].darker(140))
        if self._document is None:
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(self.rect(), Qt.AlignCenter, "No map open")
            return

        document = self._document
        zoom = self._zoom
        plane0 = document.planes.planes[0]
        plane1 = document.planes.planes[1]

        # Only the cells the repaint actually covers: scrolling a 64x64 map at
        # forty pixels a cell is otherwise four thousand fills per event.
        area = event.rect()
        first_x = max(0, area.left() // zoom)
        last_x = min(document.width - 1, area.right() // zoom)
        first_y = max(0, area.top() // zoom)
        last_y = min(document.height - 1, area.bottom() // zoom)

        for y in range(first_y, last_y + 1):
            row = y * document.width
            for x in range(first_x, last_x + 1):
                index = row + x
                painter.fillRect(
                    self.cell_rect(x, y), self._colour_for(plane0[index], plane1[index])
                )

        if self._show_objects:
            inset = max(1, zoom // 4)
            for y in range(first_y, last_y + 1):
                row = y * document.width
                for x in range(first_x, last_x + 1):
                    colour = self._object_colour(plane1[row + x])
                    if colour is not None:
                        painter.fillRect(self.cell_rect(x, y).adjusted(
                            inset, inset, -inset, -inset), colour)

        if self._show_grid and zoom >= 8:
            painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
            for x in range(first_x, last_x + 2):
                painter.drawLine(x * zoom, area.top(), x * zoom, area.bottom())
            for y in range(first_y, last_y + 2):
                painter.drawLine(area.left(), y * zoom, area.right(), y * zoom)

        if self._hover != (-1, -1):
            painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
            painter.drawRect(self.cell_rect(*self._hover).adjusted(0, 0, -1, -1))

        if self._camera is not None:
            self._paint_camera(painter)

    def _paint_camera(self, painter) -> None:
        """A ring where the camera stands, and a cone showing where it looks.

        Drawn over everything and in a colour nothing else uses, because it has
        to be findable on a busy map -- and drawn as a direction rather than a
        dot, because the angle is half of what a snapshot is of and turning the
        camera has to visibly do something.
        """
        x, y, angle = self._camera
        zoom = self._zoom
        centre = QPointF(x * zoom, y * zoom)
        radius = max(4.0, zoom * 0.32)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        # The cone first, so the ring sits on top of its point.
        #
        # Qt takes sixteenths of a degree counter-clockwise from east, and it
        # already accounts for the downward y axis -- so a positive angle goes
        # visually up, which is the engine's convention too: 0 is east and 90
        # is north. Negating it, which the flipped axis makes tempting, drew
        # every camera facing the opposite way, and the only angle that looked
        # right was zero.
        reach = max(radius * 2.2, zoom * 0.95)
        painter.setBrush(QColor(255, 214, 0, 70))
        painter.setPen(Qt.NoPen)
        painter.drawPie(QRectF(centre.x() - reach, centre.y() - reach,
                               reach * 2, reach * 2),
                        int((angle - 26) * 16), int(52 * 16))

        painter.setBrush(QColor(255, 214, 0, 190))
        painter.setPen(QPen(QColor(40, 30, 0), max(1.0, zoom / 16.0)))
        painter.drawEllipse(centre, radius, radius)
        painter.restore()

    # -- input ------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        cell = self.cell_at(event.position().toPoint())
        if cell != self._hover:
            previous, self._hover = self._hover, cell
            for stale in (previous, cell):
                if stale != (-1, -1):
                    self.update(self.cell_rect(*stale).adjusted(-2, -2, 2, 2))
            self.hovered.emit(*cell)
        if self._button != Qt.NoButton and cell != (-1, -1):
            self.dragged.emit(cell[0], cell[1], self._button.value)

    def mousePressEvent(self, event) -> None:
        cell = self.cell_at(event.position().toPoint())
        self._button = event.button()
        if cell != (-1, -1):
            self.pressed.emit(cell[0], cell[1], event.button().value)

    def mouseReleaseEvent(self, event) -> None:
        self._button = Qt.NoButton
        cell = self.cell_at(event.position().toPoint())
        self.released.emit(*cell)

    def leaveEvent(self, event) -> None:
        if self._hover != (-1, -1):
            self._hover = (-1, -1)
            self.update()
            self.hovered.emit(-1, -1)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            self.set_zoom(self._zoom + (2 if event.angleDelta().y() > 0 else -2))
            event.accept()
        else:
            event.ignore()
