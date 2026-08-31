# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Choosing which maps to bring in from a Corridor 7 archive.

Import used to take map 1 and nothing else, which is fine only if the map you
want is map 1. An archive holds sixty; this lists them and lets the user take
one, several, or all of them in one command.

Nothing here reads or shows map *content*. The list is what the archive's own
records say about themselves -- number, name, size -- which is the same
information the maps list shows about a project and carries no artwork, no
words, and nothing that could not be re-derived from a file the user already
owns. See section 5 of the design guide.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class ImportDialog(QDialog):
    """Pick maps out of an archive. `chosen()` is the map numbers."""

    def __init__(self, archive, display_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import maps")
        self.setObjectName("import-dialog")
        self.archive = archive

        heading = QLabel(
            f"<b>{len(archive)} maps</b> in {display_path}<br>"
            "Choose one or more. They are copied into the project; the archive "
            "is only ever read.", self)
        heading.setWordWrap(True)

        self.list = QListWidget(self)
        self.list.setAccessibleName("Maps in this archive")
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for record in archive.records:
            item = QListWidgetItem(
                f"{record.lump_name}   {record.name.text or '(unnamed)'}"
                f"   {record.width}x{record.height}")
            item.setData(Qt.UserRole, record.number)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self)
        self.all_button = buttons.addButton("Import &all",
                                            QDialogButtonBox.ButtonRole.ActionRole)
        self.all_button.clicked.connect(lambda _checked=False: self._select_all())
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.list)
        layout.addWidget(buttons)

    def _select_all(self) -> None:
        self.list.selectAll()
        self.accept()

    def chosen(self) -> list[int]:
        """The selected map numbers, in archive order."""
        return sorted(item.data(Qt.UserRole) for item in self.list.selectedItems())
