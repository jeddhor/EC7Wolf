# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Attaching resource packs, and seeing what attaching one did.

Deliberately a list and a description rather than a browser. A pack is not
something to explore in the editor -- its author already knows what is in it,
and everything placeable ends up in the palette a moment later. What this has
to answer is narrower and more urgent: what did I attach, what map words did it
take, and what will break if I take it away.

The last one is why detaching says what it will cost before it does it. A word
is written into map data, so removing a pack does not remove the things placed
from it: they become words the engine cannot translate, and the map quietly
stops spawning them.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from ec7edit_core.custom import allocate, load as load_allocations, store, used_by
from ec7edit_core.errors import Ec7EditError, Severity
from ec7edit_core.resources import Resource, inspect


class ResourceDialog(QDialog):
    """Edit the set of packs attached to a project."""

    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resource packs")
        self.setObjectName("resource-dialog")
        self._project = project
        self._resources = [Resource.from_json(raw) for raw in project.resources]
        self._allocations = load_allocations(project.allocations)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Sprites, textures, music and the actors that use them. A pack is a "
            ".pk3; everything placeable in one appears in the palette's Custom "
            "tab once it is attached."))

        self.list = QListWidget(self)
        self.list.setObjectName("resource-list")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.currentRowChanged.connect(lambda _row: self._describe())
        layout.addWidget(self.list, 1)

        self.detail = QLabel()
        self.detail.setObjectName("resource-detail")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setMinimumHeight(90)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.add = QPushButton("Attach a pack…")
        self.add.setObjectName("resource-add")
        self.remove = QPushButton("Detach")
        self.remove.setObjectName("resource-remove")
        buttons.addWidget(self.add)
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self.add.clicked.connect(lambda _checked=False: self.attach())
        self.remove.clicked.connect(lambda _checked=False: self.detach())

        self._refresh()
        self.resize(640, 460)

    # -- state --------------------------------------------------------------

    def resources(self) -> list[dict]:
        return [resource.to_json() for resource in self._resources]

    def allocations(self) -> dict:
        return store(self._allocations)

    def _reallocate(self) -> list:
        self._allocations, problems = allocate(
            self._allocations, self._resources, self._project.maps)
        return problems

    def _refresh(self) -> None:
        row = self.list.currentRow()
        self.list.clear()
        for resource in self._resources:
            item = QListWidgetItem(f"{resource.name} — {resource.describe()}")
            item.setData(Qt.ItemDataRole.UserRole, resource.sha256)
            self.list.addItem(item)
        if self._resources:
            self.list.setCurrentRow(min(max(row, 0), len(self._resources) - 1))
        self.remove.setEnabled(bool(self._resources))
        self._describe()

    def _current(self) -> Resource | None:
        row = self.list.currentRow()
        return self._resources[row] if 0 <= row < len(self._resources) else None

    def _describe(self) -> None:
        resource = self._current()
        if resource is None:
            self.detail.setText("No pack attached. Attach one to use art the "
                                "game never had.")
            return
        lines = [f"{resource.display_path}", f"sha256 {resource.sha256[:16]}"]
        mine = [a for a in self._allocations if a.resource == resource.sha256]
        for allocation in mine:
            kind = "object word" if allocation.plane == 1 else "wall"
            lines.append(f"  {allocation.name}: {kind} {allocation.word}")
        for problem in resource.problems:
            lines.append(f"  {problem.severity.name.lower()}: {problem.message}")
        self.detail.setText("\n".join(lines))

    # -- actions ------------------------------------------------------------

    def attach(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach a resource pack", "",
            "Resource packs (*.pk3 *.zip);;All files (*)")
        if not path:
            return False
        try:
            resource = inspect(Path(path))
        except Ec7EditError as error:
            QMessageBox.warning(self, "That pack cannot be used",
                                str(error.diagnostic.message))
            return False
        if any(r.sha256 == resource.sha256 for r in self._resources):
            QMessageBox.information(self, "Already attached",
                                    f"{resource.name} is attached already.")
            return False

        self._resources.append(resource)
        problems = [p for p in self._reallocate() if p.severity >= Severity.ERROR]
        if problems:
            # Refused after the fact rather than before, because whether it
            # can be used depends on what is already attached -- two packs
            # defining one class is a conflict neither one causes alone.
            self._resources.pop()
            self._reallocate()
            QMessageBox.warning(self, "That pack conflicts with one attached",
                                "\n".join(p.message for p in problems[:4]))
            return False
        self._refresh()
        return True

    def detach(self) -> bool:
        resource = self._current()
        if resource is None:
            return False

        # What it will cost, before it costs it. Detaching does not remove
        # anything already placed: those words stay in the map and stop
        # meaning anything.
        mine = {a.word for a in self._allocations if a.resource == resource.sha256}
        placed = 0
        for document in self._project.maps:
            for allocation in used_by(document, self._allocations):
                if allocation.word in mine:
                    placed += 1
        warning = (f"{placed} thing(s) from this pack are on your maps. "
                   "Detaching leaves those words in place, and the engine will "
                   "no longer know what they mean.\n\n" if placed else "")
        if QMessageBox.warning(
            self, f"Detach {resource.name}?",
            warning + "The pack file itself is not touched.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return False

        self._resources.remove(resource)
        self._reallocate()
        self._refresh()
        return True
