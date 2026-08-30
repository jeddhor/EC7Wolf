# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The inspector: what is in this cell, and how to change it.

Corridor 7 encodes an alien's facing, its patrol state and its difficulty band
in the raw word itself -- 108 is an Alioprobe standing still facing east on
skill 1, and 184 is the same alien patrolling on skill 3. So "turn this one to
face north" is not a property assignment; it is a different word.

The inspector makes that visible rather than hiding it. Each control changes
one axis and writes the word the catalogue says corresponds to the result, and
the raw value is shown throughout, because an editor for a game like this
should never make its user guess what it is about to write.

Where a combination does not exist -- there is no patrolling Eniram, because
the translation has no entry for one -- the control is disabled rather than
writing something approximate.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ec7edit_core.assets import AssetError
from ec7edit_core.catalog import Catalog, CatalogEntry
from ec7edit_core.document import MapDocument

#: The preview is deliberately larger than the palette's tiles. A 64x64 wall
#: page at 64 pixels is a swatch you pick from; at 128 it is something you can
#: actually read, which is the difference between "that is the grey one" and
#: "that is the one with the vent".
PREVIEW_SIZE = 128
#: The other plane's artwork, shown beside it. A cell often holds both a wall
#: and something standing on it, and the heading can only name one of them.
SECONDARY_SIZE = 64


class Inspector(QWidget):
    """Properties of the selected cell."""

    #: (plane, x, y, value) -- one raw write the window should turn into a command.
    change_requested = Signal(int, int, int, int)

    def __init__(self, catalog: Catalog | None = None, thumbnails=None, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.thumbnails = thumbnails
        self.document: MapDocument | None = None
        self.cell: tuple[int, int] | None = None
        self._loading = False

        self.preview = QLabel(self)
        self.preview.setAccessibleName("Selected artwork")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(PREVIEW_SIZE)
        self.secondary = QLabel(self)
        self.secondary.setAccessibleName("Artwork under it")
        self.secondary.setAlignment(Qt.AlignCenter)
        self.secondary.setVisible(False)

        self.heading = QLabel("Nothing selected", self)
        self.heading.setWordWrap(True)
        self.heading.setAccessibleName("Selected cell")

        self.raw = QLabel("", self)
        self.raw.setAccessibleName("Raw words")
        self.raw.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.direction = QComboBox(self)
        self.direction.setAccessibleName("Facing")
        self.direction.currentIndexChanged.connect(self._on_direction)

        self.movement = QComboBox(self)
        self.movement.setAccessibleName("Movement")
        self.movement.addItems(["Standing", "Patrolling"])
        self.movement.currentIndexChanged.connect(self._on_variant)

        self.rank = QComboBox(self)
        self.rank.setAccessibleName("Appears from skill")
        self.rank.currentIndexChanged.connect(self._on_variant)

        form = QFormLayout()
        form.addRow("Facing", self.direction)
        form.addRow("Movement", self.movement)
        form.addRow("Difficulty", self.rank)

        art = QHBoxLayout()
        art.addStretch(1)
        art.addWidget(self.preview)
        art.addWidget(self.secondary)
        art.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(art)
        layout.addWidget(self.heading)
        layout.addWidget(self.raw)
        layout.addLayout(form)
        layout.addStretch(1)
        self._set_enabled(False)

    def set_catalog(self, catalog: Catalog | None) -> None:
        self.catalog = catalog

    # -- artwork ----------------------------------------------------------

    def _pixmap_for(self, entry: CatalogEntry | None, size: int):
        """The entry's artwork at `size`, or a labelled placeholder, or None.

        Nearest-neighbour, always: these are 64x64 pages of hand-placed pixels,
        and smoothing them turns the thing being identified into a smear.
        """
        if entry is None or self.thumbnails is None:
            return None
        cached = self.thumbnails.cached(entry, size)
        if cached is not None:
            return cached
        if not self.thumbnails.available:
            return None
        from PySide6.QtGui import QPixmap

        try:
            pixels, edge, alpha = self.thumbnails.pixels_for(entry)
        except AssetError:
            return self.thumbnails.store(entry, size, self.thumbnails.placeholder(entry, size))
        image = self.thumbnails.image_from(pixels, edge, alpha)
        pixmap = QPixmap.fromImage(image).scaled(
            size, size, Qt.KeepAspectRatio, Qt.FastTransformation
        )
        return self.thumbnails.store(entry, size, pixmap)

    def _show_artwork(self, primary: CatalogEntry | None,
                      secondary: CatalogEntry | None) -> None:
        pixmap = self._pixmap_for(primary, PREVIEW_SIZE)
        if pixmap is None:
            self.preview.clear()
            self.preview.setText("no artwork" if primary is not None else "")
        else:
            self.preview.setPixmap(pixmap)
        self.preview.setToolTip(primary.name if primary is not None else "")

        under = self._pixmap_for(secondary, SECONDARY_SIZE) if secondary is not None else None
        self.secondary.setVisible(under is not None)
        if under is not None:
            self.secondary.setPixmap(under)
            self.secondary.setToolTip(f"under it: {secondary.name}")

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.direction, self.movement, self.rank):
            widget.setEnabled(enabled)

    # -- display ----------------------------------------------------------

    def show_cell(self, document: MapDocument | None, x: int, y: int) -> None:
        self.document = document
        self.cell = (x, y) if document is not None and x >= 0 else None
        self._loading = True
        try:
            self._refresh()
        finally:
            self._loading = False

    def _refresh(self) -> None:
        if self.document is None or self.cell is None:
            self.heading.setText("Nothing selected")
            self.raw.setText("")
            self._show_artwork(None, None)
            self._set_enabled(False)
            return

        x, y = self.cell
        words = [self.document.cell(plane, x, y) for plane in range(3)]
        self.raw.setText(
            f"({x}, {y})  plane 0: <b>{words[0]}</b>  "
            f"plane 1: <b>{words[1]}</b>  plane 2: <b>{words[2]}</b>"
        )

        entry = self._entry_for(words)
        # A cell holds up to two things worth looking at: what is standing here
        # and what it is standing on. The heading can only name the one the
        # controls act on, so the other gets the small tile beside it.
        under = self.catalog.for_value(0, words[0]) if (self.catalog and words[0]) else None
        if under is entry:
            under = None

        if entry is None:
            self.heading.setText("Empty floor" if not words[0] else f"Unknown word {words[0]}")
            self._show_artwork(None, None)
            self._set_enabled(False)
            return

        self.heading.setText(f"<b>{entry.name}</b><br>{entry.description or entry.actor}")
        self._show_artwork(entry, under)
        self._populate(entry, words[1])

    def _entry_for(self, words) -> CatalogEntry | None:
        if self.catalog is None:
            return None
        from .tools import EMPTY_OBJECT

        if words[1] and words[1] != EMPTY_OBJECT:
            found = self.catalog.for_value(1, words[1])
            if found is not None:
                return found
        return self.catalog.for_value(0, words[0]) if words[0] else None

    # -- the three axes ---------------------------------------------------

    def _populate(self, entry: CatalogEntry, value: int) -> None:
        self.direction.clear()
        self.movement.setCurrentIndex(1 if entry.variant == "patrol" else 0)
        self.rank.clear()

        if entry.plane != 1 or not entry.values:
            self._set_enabled(False)
            return

        self.direction.setEnabled(bool(entry.directions))
        for name, raw in entry.directions:
            self.direction.addItem(name.title(), raw)
            if raw == value:
                self.direction.setCurrentIndex(self.direction.count() - 1)

        # Which other variants of this actor exist is a catalogue question:
        # there is no patrolling Eniram because the translation has no entry
        # for one, and offering the control would promise something the format
        # cannot express.
        siblings = self._siblings(entry)
        self.movement.setEnabled(any(s.variant == "patrol" for s in siblings)
                                 and any(s.variant == "stand" for s in siblings))
        ranks = sorted({s.minskill for s in siblings if s.minskill})
        self.rank.setEnabled(len(ranks) > 1)
        for rank in ranks:
            self.rank.addItem(f"Skill {rank}+", rank)
            if rank == entry.minskill:
                self.rank.setCurrentIndex(self.rank.count() - 1)

    def _siblings(self, entry: CatalogEntry) -> list[CatalogEntry]:
        if self.catalog is None or not entry.actor:
            return [entry]
        return [other for other in self.catalog if other.actor == entry.actor]

    def _current_entry(self) -> CatalogEntry | None:
        if self.document is None or self.cell is None or self.catalog is None:
            return None
        x, y = self.cell
        return self.catalog.for_value(1, self.document.cell(1, x, y))

    def _on_direction(self, index: int) -> None:
        if self._loading or index < 0 or self.cell is None:
            return
        raw = self.direction.itemData(index)
        if raw is not None:
            self.change_requested.emit(1, self.cell[0], self.cell[1], int(raw))

    def _on_variant(self, _index: int) -> None:
        """Switch to the sibling entry matching the chosen movement and rank."""
        if self._loading or self.cell is None:
            return
        entry = self._current_entry()
        if entry is None:
            return

        wanted_variant = "patrol" if self.movement.currentIndex() == 1 else "stand"
        wanted_rank = self.rank.currentData() or entry.minskill
        facing = self.direction.currentText().lower()

        for sibling in self._siblings(entry):
            if sibling.variant != wanted_variant or sibling.minskill != wanted_rank:
                continue
            directions = dict(sibling.directions)
            raw = directions.get(facing, sibling.value)
            self.change_requested.emit(1, self.cell[0], self.cell[1], int(raw))
            return
