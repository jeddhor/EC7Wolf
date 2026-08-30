# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""First-run setup: point the editor at your engine, your game data, a workspace.

The page shows a checklist rather than a verdict. "Could not find your game" is
the least useful thing a program can say to somebody holding a CD, so every
line names what was looked for, what was found, and what to do about it.

The engine identity probe runs the binary, which is a real action on a file the
user chose, so it is a button they press and not something that happens while
they are still typing the path.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ec7edit_core.discovery import (
    FAIL,
    OK,
    WARN,
    Profile,
    candidate_data_dirs,
    candidate_engines,
    check_profile,
    data_fingerprint,
    default_workspace,
    engine_version,
)
from ec7edit_core.document import new_uuid

_STATUS_TEXT = {OK: "OK", WARN: "note", FAIL: "problem"}


class PathRow(QWidget):
    """A labelled path field with a Browse button. Accessible, tab-ordered."""

    changed = Signal()

    def __init__(self, placeholder: str, *, directory: bool, parent=None) -> None:
        super().__init__(parent)
        self.directory = directory
        self.field = QLineEdit(self)
        self.field.setPlaceholderText(placeholder)
        self.field.setAccessibleName(placeholder)
        self.field.setClearButtonEnabled(True)
        self.field.textChanged.connect(lambda _: self.changed.emit())

        self.button = QPushButton("Browse…", self)
        self.button.setAccessibleName(f"Browse for {placeholder}")
        self.button.clicked.connect(self._browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.button)
        self.setTabOrder(self.field, self.button)

    @property
    def path(self) -> str:
        return self.field.text().strip()

    @path.setter
    def path(self, value: str) -> None:
        self.field.setText(str(value))

    def _browse(self) -> None:
        start = self.path or str(Path.home())
        if self.directory:
            chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Choose a file", start)
        if chosen:
            self.path = chosen


class FirstRunDialog(QDialog):
    """The setup page. Also reachable later from Settings, unchanged."""

    def __init__(self, profile: Profile | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EC7Edit setup")
        self.setObjectName("first-run")
        self._probe_engine = False

        self.engine = PathRow("EC7Wolf executable", directory=False)
        self.data = PathRow("Corridor 7 game data folder", directory=True)
        self.workspace = PathRow("Where to keep your projects", directory=True)

        form = QFormLayout()
        form.addRow("Engine", self.engine)
        form.addRow("Game data", self.data)
        form.addRow("Workspace", self.workspace)

        self.checklist = QTreeWidget(self)
        self.checklist.setHeaderLabels(["", "Check", "Detail"])
        self.checklist.setRootIsDecorated(False)
        self.checklist.setAccessibleName("Setup checklist")
        self.checklist.setColumnWidth(0, 70)
        self.checklist.setColumnWidth(1, 200)

        self.summary = QLabel("", self)
        self.summary.setWordWrap(True)
        self.summary.setAccessibleName("Setup summary")

        self.probe_button = QPushButton("Check the engine…", self)
        self.probe_button.setToolTip(
            "Runs the executable once with --help to read its version. "
            "Nothing is run until you ask."
        )
        self.probe_button.clicked.connect(self._run_probe)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        explain = QLabel(
            "EC7Edit needs your own copy of Corridor 7. Nothing from the game is "
            "copied into the editor or into your projects — the editor reads it "
            "where it is and leaves it alone.",
            self,
        )
        explain.setWordWrap(True)
        layout.addWidget(explain)
        layout.addLayout(form)
        layout.addWidget(self.probe_button)
        layout.addWidget(self.checklist, 1)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)

        for row in (self.engine, self.data, self.workspace):
            row.changed.connect(self._revalidate)

        self._apply(profile or self._suggest())
        self._revalidate()

    # -- profile ----------------------------------------------------------

    def _suggest(self) -> Profile:
        engines = candidate_engines()
        data = candidate_data_dirs()
        return Profile(
            profile_id=new_uuid(),
            engine_path=str(engines[0]) if engines else "",
            data_dir=str(data[0]) if data else "",
            workspace_dir=str(default_workspace()),
        )

    def _apply(self, profile: Profile) -> None:
        self._profile_id = profile.profile_id or new_uuid()
        self.engine.path = profile.engine_path
        self.data.path = profile.data_dir
        self.workspace.path = profile.workspace_dir

    def profile(self) -> Profile:
        """The profile as configured. Fingerprint computed only if data is set."""
        data = self.data.path
        fingerprint = ""
        if data and Path(data).is_dir():
            try:
                fingerprint = data_fingerprint(data)
            except OSError:
                fingerprint = ""
        return Profile(
            profile_id=self._profile_id,
            engine_path=self.engine.path,
            data_dir=data,
            workspace_dir=self.workspace.path,
            data_fingerprint=fingerprint,
            engine_version=self._engine_version,
        )

    # -- validation -------------------------------------------------------

    _engine_version = ""

    def _run_probe(self) -> None:
        self._probe_engine = True
        self._revalidate()

    def _revalidate(self) -> None:
        profile = Profile(
            profile_id=self._profile_id,
            engine_path=self.engine.path,
            data_dir=self.data.path,
            workspace_dir=self.workspace.path,
        )
        report = check_profile(profile, probe=self._probe_engine)
        if self._probe_engine:
            self._engine_version = engine_version(report) or self._engine_version
        self._probe_engine = False

        self.checklist.clear()
        for check in report:
            item = QTreeWidgetItem(
                [_STATUS_TEXT.get(check.status, check.status), check.name, check.detail]
            )
            item.setToolTip(2, check.remedy or check.detail)
            if check.status == FAIL:
                item.setToolTip(0, check.remedy)
            self.checklist.addTopLevelItem(item)

        problems = report.failures
        if not report.checks:
            self.summary.setText("Choose an engine, your game data, and a workspace.")
        elif problems:
            self.summary.setText(
                f"{len(problems)} thing{'s' if len(problems) > 1 else ''} to fix: "
                + problems[0].remedy
            )
        else:
            notes = len(report.warnings)
            self.summary.setText(
                "Ready." + (f" {notes} note{'s' if notes > 1 else ''}." if notes else "")
            )
        self.buttons.button(QDialogButtonBox.Save).setEnabled(not problems)

    @property
    def usable(self) -> bool:
        return self.buttons.button(QDialogButtonBox.Save).isEnabled()
