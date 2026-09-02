# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The campaign editor: what a map pack is, said as a list of levels and routes.

A campaign is a graph, and the obvious thing to build is a node editor. This is
a table instead, deliberately. The graph a pack can describe is tiny -- each
level has one exit and at most one secret exit -- so a canvas would spend most
of its code on arranging boxes and none of it on the questions an author
actually has: which level starts, where each exit goes, and whether the whole
thing can be finished. A table answers all three by reading down a column.

Everything shown is checked by `campaign.validate` as it is typed, and the
result is the same list of diagnostics the CLI prints and the gate asserts on.
There is no second opinion in here: the panel at the bottom is that function's
output, and OK stays available while warnings stand because a warning is a
thing an author may knowingly accept.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QVBoxLayout, QWidget,
)

from ec7edit_core.campaign import (
    Campaign, CampaignEntry, MAX_LEVEL_NAME, MAX_TITLE, Route, validate,
)
from ec7edit_core.errors import Severity

#: The "this level finishes the campaign" choice, as a combo box value. Not a
#: slot number, and never confusable with one.
END = -1


class CampaignDialog(QDialog):
    """Edit a project's campaign. Returns the new one through `campaign()`."""

    COLUMNS = ("Level", "Name in game", "Exit goes to", "Secret exit",
               "Music", "Par", "Tally")

    def __init__(self, campaign: Campaign, documents, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Campaign")
        self.setObjectName("campaign-dialog")
        self._documents = sorted(documents, key=lambda d: d.slot)
        self._slots = [document.slot for document in self._documents]

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.title = QLineEdit(campaign.title)
        self.title.setMaxLength(MAX_TITLE)
        self.title.setObjectName("campaign-title")
        self.key = QLineEdit(campaign.key)
        self.key.setMaxLength(1)
        self.key.setObjectName("campaign-key")
        self.key.setFixedWidth(40)
        form.addRow("Campaign name", self.title)
        form.addRow("Menu key", self.key)
        layout.addLayout(form)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setObjectName("campaign-levels")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.add = QPushButton("Add level")
        self.add.setObjectName("campaign-add")
        self.remove = QPushButton("Remove")
        self.remove.setObjectName("campaign-remove")
        self.up = QPushButton("Move up")
        self.up.setObjectName("campaign-up")
        self.down = QPushButton("Move down")
        self.down.setObjectName("campaign-down")
        for widget in (self.add, self.remove, self.up, self.down):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        # The first row is where a new game starts, which is not something a
        # table says on its own -- so it is said here, next to the buttons that
        # change it.
        self.start = QLabel()
        self.start.setObjectName("campaign-start")
        buttons.addWidget(self.start)
        layout.addLayout(buttons)

        self.problems = QLabel()
        self.problems.setObjectName("campaign-problems")
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.problems)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.ok = box.button(QDialogButtonBox.StandardButton.Ok)
        layout.addWidget(box)

        self.add.clicked.connect(self._add_level)
        self.remove.clicked.connect(self._remove_level)
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        self.title.textChanged.connect(self._revalidate)
        self.key.textChanged.connect(self._revalidate)

        for entry in campaign.entries:
            self._append_row(entry)
        if not campaign.entries:
            for document in self._documents:
                self._append_row(self._default_entry(document.slot))
        self._revalidate()
        self.resize(760, 460)

    # -- rows ---------------------------------------------------------------

    def _default_entry(self, slot: int) -> CampaignEntry:
        """A new level, routed to the next map the project has, or to the end."""
        later = [s for s in self._slots if s > slot]
        return CampaignEntry(slot, f"Level {slot}",
                             next=Route(later[0] if later else None))

    def _route_box(self, route: Route | None) -> QComboBox:
        box = QComboBox()
        box.addItem("End of campaign", END)
        for slot in self._slots:
            box.addItem(f"MAP{slot:02d}", slot)
        if route is not None:
            index = box.findData(END if route.ends else route.slot)
            box.setCurrentIndex(max(0, index))
        box.currentIndexChanged.connect(self._revalidate)
        return box

    def _append_row(self, entry: CampaignEntry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        slots = QComboBox()
        for document in self._documents:
            slots.addItem(f"MAP{document.slot:02d}  {document.name}", document.slot)
        index = slots.findData(entry.slot)
        if index < 0:
            # A campaign can name a slot the project no longer has. Keeping the
            # row and letting the validator say so beats silently dropping a
            # level the author wrote.
            slots.addItem(f"MAP{entry.slot:02d}  (no map)", entry.slot)
            index = slots.count() - 1
        slots.setCurrentIndex(index)
        slots.currentIndexChanged.connect(self._revalidate)
        self.table.setCellWidget(row, 0, slots)

        name = QLineEdit(entry.name)
        name.setMaxLength(MAX_LEVEL_NAME)
        name.textChanged.connect(self._revalidate)
        self.table.setCellWidget(row, 1, name)

        self.table.setCellWidget(row, 2, self._route_box(entry.next))

        secret = QWidget()
        secret_layout = QHBoxLayout(secret)
        secret_layout.setContentsMargins(0, 0, 0, 0)
        enabled = QCheckBox()
        enabled.setChecked(entry.secret is not None)
        destination = self._route_box(entry.secret)
        destination.setEnabled(entry.secret is not None)
        # Both wrapped, for opposite reasons. setEnabled genuinely wants the
        # checked bool, so the lambda says so rather than leaving a reader to
        # work out whether the argument was intended. _revalidate does not want
        # it at all, and would silently receive it as its first parameter.
        enabled.toggled.connect(lambda on, box=destination: box.setEnabled(on))
        enabled.toggled.connect(lambda _checked=False: self._revalidate())
        secret_layout.addWidget(enabled)
        secret_layout.addWidget(destination, 1)
        secret.setProperty("enabled_box", enabled)
        secret.setProperty("route_box", destination)
        self.table.setCellWidget(row, 3, secret)

        music = QLineEdit(entry.music)
        music.setPlaceholderText("stock")
        music.setMaxLength(8)
        music.textChanged.connect(self._revalidate)
        self.table.setCellWidget(row, 4, music)

        par = QSpinBox()
        par.setRange(0, 24 * 60 * 60)
        par.setValue(entry.par)
        par.setSpecialValueText("none")
        par.valueChanged.connect(self._revalidate)
        self.table.setCellWidget(row, 5, par)

        tally = QCheckBox()
        tally.setChecked(entry.intermission)
        tally.toggled.connect(lambda _checked=False: self._revalidate())
        self.table.setCellWidget(row, 6, tally)

    def _add_level(self) -> None:
        used = {self._row_slot(row) for row in range(self.table.rowCount())}
        spare = [document.slot for document in self._documents if document.slot not in used]
        if not spare and not self._documents:
            return
        self._append_row(self._default_entry(spare[0] if spare else self._slots[0]))
        self._revalidate()

    def _remove_level(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._revalidate()

    def _move(self, delta: int) -> None:
        """Reorder by rebuilding both rows: the first row is the campaign start.

        Qt has no "move row" for a table of widgets, and swapping cell widgets
        one at a time loses their signal connections. Reading the entries out
        and writing them back is the only version that cannot half-work.
        """
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        entries = list(self._entries())
        entries[row], entries[target] = entries[target], entries[row]
        self.table.setRowCount(0)
        for entry in entries:
            self._append_row(entry)
        self.table.setCurrentCell(target, 0)
        self._revalidate()

    # -- reading the table back --------------------------------------------

    def _row_slot(self, row: int) -> int:
        return self.table.cellWidget(row, 0).currentData()

    def _entries(self):
        for row in range(self.table.rowCount()):
            secret_cell = self.table.cellWidget(row, 3)
            enabled = secret_cell.property("enabled_box")
            destination = secret_cell.property("route_box")
            secret = None
            if enabled.isChecked():
                value = destination.currentData()
                secret = Route(None if value == END else value)
            value = self.table.cellWidget(row, 2).currentData()
            yield CampaignEntry(
                slot=self._row_slot(row),
                name=self.table.cellWidget(row, 1).text(),
                next=Route(None if value == END else value),
                secret=secret,
                music=self.table.cellWidget(row, 4).text().strip(),
                par=self.table.cellWidget(row, 5).value(),
                intermission=self.table.cellWidget(row, 6).isChecked(),
            )

    def campaign(self) -> Campaign:
        return Campaign(title=self.title.text(), key=self.key.text(),
                        entries=tuple(self._entries()))

    # -- the panel ----------------------------------------------------------

    def _revalidate(self) -> None:
        campaign = self.campaign()
        self.start.setText(
            f"Starts at MAP{campaign.start:02d}" if campaign.start is not None
            else "No levels")

        problems = validate(campaign, self._documents)
        errors = [p for p in problems if p.severity >= Severity.ERROR]
        warnings = [p for p in problems if p.severity == Severity.WARNING]

        lines = [f"{p.severity.name.lower()}: {p.message}" for p in errors + warnings]
        self.problems.setText("\n".join(lines[:6]) if lines
                              else "This campaign is ready to build.")
        # Errors block the build, so they block OK. Warnings do not: "this slot
        # replaces a stock level" is a thing someone may mean to do.
        self.ok.setEnabled(not errors)
