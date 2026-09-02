# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""List models over the catalog, with thumbnails that arrive when they can.

The model shows every entry immediately, with a placeholder, and replaces each
tile as its artwork decodes. That ordering is deliberate: a palette that waits
for 243 wall pages before showing anything feels broken, and one that shows
only what has decoded so far makes the list jump under the pointer.

An entry whose artwork fails keeps its placeholder and its name. A palette that
hid broken items would hide the fact that something is wrong with the data,
which is the opposite of helpful when the data is the thing being diagnosed.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap

from ec7edit_core.catalog import Catalog, CatalogEntry

from .thumbnails import ThumbnailFactory
from .workers import WorkerPool

#: Roles beyond the display ones, so a view can get at the entry itself.
EntryRole = Qt.UserRole + 1
KeyRole = Qt.UserRole + 2
ValueRole = Qt.UserRole + 3


class CatalogModel(QAbstractListModel):
    """One palette tab's worth of entries."""

    def __init__(self, entries=(), factory: ThumbnailFactory | None = None,
                 pool: WorkerPool | None = None, *, icon_size: int = 48, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[CatalogEntry] = list(entries)
        self._factory = factory
        self._pool = pool
        self._icon_size = icon_size
        self._icons: dict[str, QIcon] = {}
        self._requested: set[str] = set()
        if pool is not None:
            pool.completed.connect(self._on_decoded)

    # -- Qt model interface ----------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]

        if role == Qt.DisplayRole:
            return entry.name
        if role == Qt.ToolTipRole:
            return self._tooltip(entry)
        if role == Qt.DecorationRole:
            return self._icon_for(entry)
        if role == Qt.SizeHintRole:
            return QSize(self._icon_size + 8, self._icon_size + 28)
        if role == Qt.AccessibleTextRole:
            return f"{entry.name}, raw value {entry.value}"
        if role == EntryRole:
            return entry
        if role == KeyRole:
            return entry.key
        if role == ValueRole:
            return entry.value
        return None

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if not index.isValid():
            return base
        entry = self._entries[index.row()]
        if not entry.safe_for_new_maps:
            # Imported-only values stay visible and selectable, but the view
            # can style them differently; hiding them would lose imported work.
            return base | Qt.ItemIsSelectable
        return base

    # -- content ----------------------------------------------------------

    def set_entries(self, entries) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self._requested.clear()
        self.endResetModel()

    def entry_at(self, row: int) -> CatalogEntry | None:
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def row_of(self, key: str) -> int:
        for row, entry in enumerate(self._entries):
            if entry.key == key:
                return row
        return -1

    # -- thumbnails -------------------------------------------------------

    def _tooltip(self, entry: CatalogEntry) -> str:
        lines = [f"<b>{entry.name}</b>", f"raw {entry.value} on plane {entry.plane}"]
        if entry.actor:
            lines.append(entry.actor)
        if entry.description:
            lines.append(entry.description)
        if not entry.safe_for_new_maps:
            lines.append("<i>imported content: preserved, not offered for new maps</i>")
        return "<br>".join(lines)

    def _icon_for(self, entry: CatalogEntry) -> QIcon:
        icon = self._icons.get(entry.key)
        if icon is not None:
            return icon

        if self._factory is None:
            icon = QIcon()
            self._icons[entry.key] = icon
            return icon

        cached = self._factory.cached(entry, self._icon_size)
        if cached is not None:
            icon = QIcon(cached)
            self._icons[entry.key] = icon
            return icon

        placeholder = QIcon(self._factory.placeholder(entry, self._icon_size))
        self._icons[entry.key] = placeholder
        self._request(entry)
        return placeholder

    def _request(self, entry: CatalogEntry) -> None:
        if self._pool is None or not self._factory.available or entry.key in self._requested:
            return
        self._requested.add(entry.key)
        factory = self._factory

        def work(job):
            if job.canceled:
                return None
            return factory.pixels_for(entry)

        # Not revision-tracked: a thumbnail is the user's artwork, which does
        # not go stale because the document changed.
        self._pool.submit(f"thumb:{entry.key}", work, metadata={"entry": entry},
                          tracks_revision=False)

    def _on_decoded(self, key: str, result) -> None:
        if not key.startswith("thumb:") or result is None or self._factory is None:
            return
        entry_key = key[len("thumb:"):]
        row = self.row_of(entry_key)
        if row < 0:
            return
        entry = self._entries[row]
        pixels, edge, alpha = result
        image = self._factory.image_from(pixels, edge, alpha)
        pixmap = QPixmap.fromImage(image).scaled(
            self._icon_size, self._icon_size, Qt.KeepAspectRatio, Qt.FastTransformation
        )
        self._factory.store(entry, self._icon_size, pixmap)
        self._icons[entry.key] = QIcon(pixmap)
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [Qt.DecorationRole])


class CatalogFilter:
    """Search and category filtering, kept out of the model on purpose.

    A model that filtered itself would need resetting on every keystroke and
    would lose the view's selection each time. Filtering here means the model
    is handed a list and does not care where it came from.
    """

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def entries(self, *, category: str = "", query: str = "",
                include_imported_only: bool = True) -> list[CatalogEntry]:
        found = self.catalog.search(query, category=category) if query \
            else self.catalog.in_category(category) if category else list(self.catalog)
        if not include_imported_only:
            found = [entry for entry in found if entry.safe_for_new_maps]
        return found
