"""The wizard's pages.

Each page owns its widgets and reads and writes one shared State object, rather
than QWizard's field registry: the state is what the install actually needs, and
keeping it in one plain object means the summary and the plan are built from the
same thing the pages set.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QRadioButton, QSizePolicy, QTextBrowser,
                               QVBoxLayout, QWizard, QWizardPage)

from c7disc import GameSource
from ec7install import build, deps, install
from ec7install.progress import LogFile
from ec7install.plan import InstallPlan, RemovalPlan

from .worker import Bridge, GuiReporter, InstallThread, Task


# ---------------------------------------------------------------------------
# Shared state and small helpers
# ---------------------------------------------------------------------------

class State:
    """Everything the pages collect, and the plan consumes."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.source: GameSource | None = None
        self.source_path: Path | None = None
        self.probe: dict | None = None
        self.engine: build.Engine | None = None
        # Places to look for a built engine besides the usual build trees --
        # the folder holding a frozen setup.exe, most of all.
        self.extra_engine_paths: list[Path] = []
        self.force_build = False
        # Set when the installer has no source tree beside it and the user has
        # agreed it should download one.
        self.fetch_source = False
        self.build_report: deps.Report | None = None
        self.rip_report: deps.Report | None = None
        self.destination = install.default_destination()
        self.with_music = True
        self.with_video = True
        self.menu_shortcut = True
        self.desktop_shortcut = True
        self.jobs = os.cpu_count() or 2
        self.log_path: Path | None = None
        # "install" or "remove". There is deliberately no separate upgrade or
        # repair: this installer always writes everything, so those would be
        # the same action under three names.
        self.mode = "install"
        self.existing: dict | None = None
        self.outcome = ""
        self.message = ""
        self.installed: Path | None = None
        self.warnings: list[str] = []


def megabytes(count: int) -> str:
    if count >= 1024 ** 3:
        return f"{count / 1024 ** 3:.1f} GB"
    return f"{count / 1024 ** 2:.0f} MB"


def plural(count: int, noun: str, many: str | None = None) -> str:
    """"1 audio track" / "8 audio tracks". Cheap, and "track(s)" looks unfinished."""
    return f"{count} {noun if count == 1 else (many or noun + 's')}"


def mono_font() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPointSize(max(8, font.pointSize() - 1))
    return font


def body(text: str) -> QLabel:
    """A wrapped paragraph. Qt labels do not wrap unless told to, every time."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(True)
    return label


class Html(QTextBrowser):
    """A read-only panel used wherever a table or a list needs to wrap.

    Colours come from the widget palette rather than being written into the
    markup, so the panel follows the desktop theme instead of assuming a light
    one -- which on a KDE dark theme would be black text on black.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.StyledPanel)

    def colours(self) -> dict:
        palette = self.palette()
        return {
            "text": palette.text().color().name(),
            "dim": palette.placeholderText().color().name(),
            "ok": "#2e9e4f" if palette.base().color().lightness() > 128 else "#59d67f",
            "bad": "#c0392b" if palette.base().color().lightness() > 128 else "#ff6b5b",
            "warn": "#b8860b" if palette.base().color().lightness() > 128 else "#e0b040",
        }

    def show_html(self, markup: str) -> None:
        colour = self.colours()
        self.setHtml(
            f"<body style='color:{colour['text']}; font-family:sans-serif;'>"
            + markup + "</body>")


def requirement_rows(report: deps.Report, colours: dict) -> str:
    """One line per dependency, with the remedy underneath the missing ones."""
    rows = []
    for requirement in report:
        if requirement.found:
            mark, colour = "&#10003;", colours["ok"]
        elif requirement.optional:
            mark, colour = "&#8211;", colours["warn"]
        else:
            mark, colour = "&#10007;", colours["bad"]
        note = requirement.detail if requirement.found else requirement.remedy
        rows.append(
            f"<tr><td style='color:{colour}; padding-right:8px; "
            f"font-size:large;' valign='top'>{mark}</td>"
            f"<td style='padding-right:12px;' valign='top'><b>{requirement.label}</b></td>"
            f"<td style='color:{colours['dim']};' valign='top'>{note}</td></tr>")
    return "<table cellspacing='4'>" + "".join(rows) + "</table>"


# ---------------------------------------------------------------------------
# Welcome
# ---------------------------------------------------------------------------

class WelcomePage(QWizardPage):
    NAME = "welcome"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("Install EC7Wolf")
        self.setSubTitle("Corridor 7: Alien Invasion, on a modern machine.")

        layout = QVBoxLayout(self)
        layout.addWidget(body(
            "This installer builds the EC7Wolf engine, takes the game's data, "
            "soundtrack and cinematics from your Corridor 7 CD, and puts them "
            "together in a folder you choose."))
        layout.addSpacing(8)
        layout.addWidget(body(
            "<b>You need your own copy of Corridor 7: Alien Invasion.</b> "
            "The engine is free software, but the game's data is not "
            "distributed with it and is not included here. The CD-ROM release "
            "&#8211; the disc, or the BIN/CUE image sold by GOG or Steam "
            "&#8211; is the one to use, because it is the only one carrying "
            "the soundtrack and the cinematics."))
        layout.addSpacing(8)
        layout.addWidget(body(
            "Nothing is written outside the folder you pick, and the installer "
            "never needs administrator rights."))
        layout.addStretch(1)

    def initializePage(self) -> None:
        # Looked up once, here, so the page after this one knows whether it has
        # anything to say.
        self.state.existing = install.read_manifest(self.state.destination)

    def nextId(self) -> int:
        wizard = self.wizard()
        if self.state.existing:
            return wizard.ids["mode"]
        return wizard.ids["license"]


# ---------------------------------------------------------------------------
# Already installed?
# ---------------------------------------------------------------------------

class ModePage(QWizardPage):
    """Shown only when there is already an EC7Wolf where one would go.

    Skipped entirely otherwise -- a page that says "you have not installed this
    yet" is a page nobody needs to read.
    """

    NAME = "mode"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("EC7Wolf is already installed")
        self.setSubTitle("Choose what to do with the copy that is already here.")

        layout = QVBoxLayout(self)
        self.details = Html()
        self.details.setMaximumHeight(120)
        layout.addWidget(self.details)
        layout.addSpacing(8)

        self.reinstall = QRadioButton("Reinstall it")
        self.remove = QRadioButton("Remove it")
        reinstall_note = body(
            "Writes everything again from your disc. Your saved games and "
            "settings are kept.")
        remove_note = body(
            "Deletes the installed game, its shortcuts and its entry in the "
            "list of installed programs. <b>Saved games in the install folder "
            "go with it.</b>")
        for note in (reinstall_note, remove_note):
            note.setContentsMargins(22, 0, 0, 8)

        layout.addWidget(self.reinstall)
        layout.addWidget(reinstall_note)
        layout.addWidget(self.remove)
        layout.addWidget(remove_note)
        layout.addStretch(1)

        self.reinstall.setChecked(True)
        for radio in (self.reinstall, self.remove):
            radio.toggled.connect(self._changed)

    def initializePage(self) -> None:
        manifest = self.state.existing or {}
        colour = self.details.colours()
        rows = [f"<p><b>{self.state.destination}</b></p>"]
        installed = manifest.get("installed")
        source = manifest.get("source")
        extra = []
        if installed:
            extra.append(f"installed {installed.replace('T', ' at ')}")
        if source:
            extra.append(f"from {source}")
        saves = self.state.destination / "saves"
        if saves.is_dir():
            count = sum(1 for f in saves.rglob("*") if f.is_file())
            if count:
                extra.append(f"<b>{plural(count, 'saved game file')}</b>")
        if extra:
            rows.append(f"<p style='color:{colour['dim']};'>"
                        + "<br>".join(extra) + "</p>")
        self.details.show_html("".join(rows))
        self._changed()

    def _changed(self, *_) -> None:
        self.state.mode = "remove" if self.remove.isChecked() else "install"

    def nextId(self) -> int:
        wizard = self.wizard()
        if self.remove.isChecked():
            # Nothing to ask: no disc, no engine, no options.
            return wizard.ids["summary"]
        return wizard.ids["license"]


# ---------------------------------------------------------------------------
# Licence
# ---------------------------------------------------------------------------

class LicensePage(QWizardPage):
    NAME = "license"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("Licence")
        self.setSubTitle("EC7Wolf is free software under the GNU General "
                         "Public License, version 3.")

        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(mono_font())
        self.text.setPlainText(self._licence_text())
        layout.addWidget(self.text, 1)

        self.accepted = QCheckBox("I accept the terms of the licence")
        self.accepted.toggled.connect(self.completeChanged)
        layout.addWidget(self.accepted)

    def _licence_text(self) -> str:
        path = self.state.repo_root / "docs" / "license-gpl.txt"
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ("The GNU General Public License, version 3.\n\n"
                    "The full text should have been shipped alongside this "
                    "installer, at docs/license-gpl.txt, and could not be "
                    "read. It is also at https://www.gnu.org/licenses/gpl-3.0.txt")

    def isComplete(self) -> bool:
        return self.accepted.isChecked()


# ---------------------------------------------------------------------------
# Where the game's data comes from
# ---------------------------------------------------------------------------

def probe_source(path: Path) -> dict:
    """Open a source and work out whether it can actually furnish an install.

    Runs on a worker thread: reading the directory of a real CD spins the drive
    up and can take several seconds.
    """
    path = Path(path).resolve()
    source = GameSource.open(path)
    names = source.list()
    try:
        tracks = source.audio_tracks()
    except Exception:                                 # noqa: BLE001
        tracks = []
    return {
        "source": source,
        "describe": source.describe(),
        "missing": [n for n in install.REQUIRED_DATA if n not in names],
        "optional": [n for n in install.OPTIONAL_DATA if n in names],
        "cinematics": [n for n in install.CINEMATICS if n in names],
        "tracks": len(tracks),
    }


class SourcePage(QWizardPage):
    NAME = "source"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.task: Task | None = None
        self.setTitle("Your copy of Corridor 7")
        self.setSubTitle("Point the installer at the CD, or at an image of it.")

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        self.driveRadio = QRadioButton("A Corridor 7 CD in a drive")
        self.driveCombo = QComboBox()
        self.driveCombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refreshButton = QPushButton("Rescan")
        grid.addWidget(self.driveRadio, 0, 0, 1, 3)
        grid.addWidget(self.driveCombo, 1, 1)
        grid.addWidget(self.refreshButton, 1, 2)

        self.imageRadio = QRadioButton("A disc image (BIN/CUE, or ISO)")
        self.imageEdit = QLineEdit()
        self.imageEdit.setPlaceholderText("Corridor7.cue")
        self.imageBrowse = QPushButton("Browse…")
        grid.addWidget(self.imageRadio, 2, 0, 1, 3)
        grid.addWidget(self.imageEdit, 3, 1)
        grid.addWidget(self.imageBrowse, 3, 2)

        self.folderRadio = QRadioButton("A folder that already holds the game's files")
        self.folderEdit = QLineEdit()
        self.folderBrowse = QPushButton("Browse…")
        grid.addWidget(self.folderRadio, 4, 0, 1, 3)
        grid.addWidget(self.folderEdit, 5, 1)
        grid.addWidget(self.folderBrowse, 5, 2)
        layout.addLayout(grid)

        layout.addSpacing(10)
        self.result = Html()
        self.result.setMinimumHeight(120)
        layout.addWidget(self.result, 1)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(400)
        self.debounce.timeout.connect(self.rescan)

        for radio in (self.driveRadio, self.imageRadio, self.folderRadio):
            radio.toggled.connect(self._changed)
        self.driveCombo.currentIndexChanged.connect(self._changed)
        self.imageEdit.textChanged.connect(self._changed)
        self.folderEdit.textChanged.connect(self._changed)
        self.refreshButton.clicked.connect(self.find_drives)
        self.imageBrowse.clicked.connect(self._browse_image)
        self.folderBrowse.clicked.connect(self._browse_folder)

        self.imageRadio.setChecked(True)

    # -- filling in --------------------------------------------------------

    def initializePage(self) -> None:
        self.find_drives()
        if self.state.source_path and not self.imageEdit.text():
            self.imageEdit.setText(str(self.state.source_path))

    def find_drives(self) -> None:
        from c7disc import optical_drives
        self.driveCombo.clear()
        drives = [d for d in optical_drives() if d.has_disc] or optical_drives()
        for drive in drives:
            self.driveCombo.addItem(drive.label, drive.path)
        loaded = bool(drives)
        self.driveRadio.setEnabled(loaded)
        self.driveCombo.setEnabled(loaded)
        if not loaded:
            self.driveCombo.addItem("no CD drive found")
            if self.driveRadio.isChecked():
                self.imageRadio.setChecked(True)

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a disc image", str(Path.home()),
            "Disc images (*.cue *.CUE *.iso *.ISO *.bin *.BIN);;All files (*)")
        if path:
            self.imageEdit.setText(path)
            self.imageRadio.setChecked(True)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose the folder holding the game's files", str(Path.home()))
        if path:
            self.folderEdit.setText(path)
            self.folderRadio.setChecked(True)

    # -- validating --------------------------------------------------------

    def selected_path(self) -> Path | None:
        if self.driveRadio.isChecked():
            data = self.driveCombo.currentData()
            return Path(data) if data else None
        if self.imageRadio.isChecked():
            text = self.imageEdit.text().strip()
            return Path(text).expanduser() if text else None
        text = self.folderEdit.text().strip()
        return Path(text).expanduser() if text else None

    def _changed(self, *_) -> None:
        self.state.probe = None
        self.state.source = None
        self.completeChanged.emit()
        self.debounce.start()

    def rescan(self) -> None:
        path = self.selected_path()
        if path is None:
            self.result.show_html("")
            return
        if not path.exists():
            self.result.show_html(
                f"<p style='color:{self.result.colours()['bad']};'>"
                f"There is nothing at {path}.</p>")
            return
        self.result.show_html("<p>Reading&#8230;</p>")
        self.task = Task(lambda p=path: probe_source(p), self)
        self.task.ended.connect(self._probed)
        self.task.start()

    def _probed(self, result, error: str) -> None:
        colour = self.result.colours()
        if error:
            self.result.show_html(
                f"<p style='color:{colour['bad']};'>This source could not be "
                f"read: {error}</p>")
            self.completeChanged.emit()
            return

        lines = [f"<p><b>{result['describe']}</b></p>"]
        if result["missing"]:
            lines.append(
                f"<p style='color:{colour['bad']};'>Not the Corridor 7 game "
                "data. Missing: " + ", ".join(result["missing"]) + "</p>")
        else:
            lines.append(f"<p style='color:{colour['ok']};'>&#10003; All "
                         f"{len(install.REQUIRED_DATA)} game files are here.</p>")
            extras = []
            extras.append(
                plural(result["tracks"], "audio track") + " for the soundtrack"
                if result["tracks"] else
                "<span style='color:%s'>no audio tracks &#8211; the CD "
                "soundtrack cannot be ripped from this source</span>" % colour["warn"])
            extras.append(
                f"{len(result['cinematics'])} of {len(install.CINEMATICS)} cinematics"
                if result["cinematics"] else
                "<span style='color:%s'>no cinematics &#8211; they exist only "
                "on the CD</span>" % colour["warn"])
            if result["optional"]:
                extras.append(", ".join(result["optional"]) + " (digitised speech)")
            lines.append("<ul><li>" + "</li><li>".join(extras) + "</li></ul>")
        self.result.show_html("".join(lines))

        if not result["missing"]:
            self.state.probe = result
            self.state.source = result["source"]
            self.state.source_path = self.selected_path()
            self.state.with_music = result["tracks"] > 0
            self.state.with_video = bool(result["cinematics"])
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self.state.source is not None


# ---------------------------------------------------------------------------
# The engine: already built, or built here
# ---------------------------------------------------------------------------

def can_build_here(repo_root: Path) -> bool:
    """Whether there is a source tree to compile at all.

    A frozen installer carries the wizard, not the engine's source, so on
    Windows this is normally False -- and saying "install CMake" to someone
    with nothing to compile would send them off to do useless work.
    """
    return (repo_root / "CMakeLists.txt").is_file()


def survey_engine(repo_root: Path, force: bool, need_music: bool,
                  extra: list[Path] | None = None) -> dict:
    """Look for a built engine, and for the tools to build one if there isn't."""
    engine = None if force else build.find_existing(repo_root, extra=list(extra or []))
    return {
        "engine": engine,
        "buildable": can_build_here(repo_root),
        "build": deps.scan_build() if engine is None else None,
        "rip": deps.scan_rip(need_music=need_music),
    }


class EnginePage(QWizardPage):
    NAME = "engine"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.task: Task | None = None
        self.ready = False
        self.setTitle("The engine")
        self.setSubTitle("Checking for a build, and for what it takes to make one.")

        layout = QVBoxLayout(self)
        self.report = Html()
        layout.addWidget(self.report, 1)

        self.fetchSource = QCheckBox(
            "Download the EC7Wolf source and build it")
        self.fetchSource.setVisible(False)
        self.fetchSource.toggled.connect(self._fetch_toggled)
        layout.addWidget(self.fetchSource)

        row = QHBoxLayout()
        self.forceBuild = QCheckBox("Compile a fresh copy even if one is found")
        self.forceBuild.toggled.connect(self._force_toggled)
        row.addWidget(self.forceBuild)
        row.addStretch(1)
        self.recheck = QPushButton("Check again")
        self.recheck.clicked.connect(self.survey)
        row.addWidget(self.recheck)
        layout.addLayout(row)

    def initializePage(self) -> None:
        self.survey()

    def _force_toggled(self, checked: bool) -> None:
        self.state.force_build = checked
        self.survey()

    def _fetch_toggled(self, checked: bool) -> None:
        self.state.fetch_source = checked
        self.ready = checked
        self.completeChanged.emit()

    def survey(self) -> None:
        self.ready = False
        self.completeChanged.emit()
        self.recheck.setEnabled(False)
        self.report.show_html("<p>Looking&#8230;</p>")
        repo, force = self.state.repo_root, self.forceBuild.isChecked()
        music = self.state.with_music
        extra = list(self.state.extra_engine_paths)
        self.task = Task(lambda: survey_engine(repo, force, music, extra), self)
        self.task.ended.connect(self._surveyed)
        self.task.start()

    def _surveyed(self, result, error: str) -> None:
        self.recheck.setEnabled(True)
        colour = self.report.colours()
        if error:
            self.report.show_html(
                f"<p style='color:{colour['bad']};'>The check failed: {error}</p>")
            self.completeChanged.emit()
            return

        self.state.engine = result["engine"]
        self.forceBuild.setEnabled(result["buildable"])
        needs_source = result["engine"] is None and not result["buildable"]
        self.fetchSource.setVisible(needs_source)
        if needs_source and not self.fetchSource.isChecked():
            self.fetchSource.setChecked(True)
        self.state.build_report = result["build"]
        self.state.rip_report = result["rip"]

        parts = []
        if result["engine"] is not None:
            engine = result["engine"]
            parts.append(
                f"<p style='color:{colour['ok']};'>&#10003; <b>An engine is "
                "already built.</b></p>"
                f"<p style='color:{colour['dim']};'>{engine.source}<br>"
                f"{engine.executable}</p>"
                "<p>It will be used as it is, so there is nothing to compile. "
                "Tick the box below to build a fresh one anyway.</p>")
            self.ready = True
        elif not result["buildable"]:
            # No engine, and no source beside the installer -- which is the
            # normal state of the installer-only download. It can fetch the
            # source itself, so this is a choice rather than a dead end.
            parts.append(
                f"<p style='color:{colour['warn']};'><b>No engine was found "
                "here.</b></p>"
                "<p>This installer does not carry the engine's source, but it "
                "can download it and build it for you &#8212; that is what the "
                "box below does. The alternative is to put <tt>ec7wolf</tt> "
                "and <tt>ec7wolf.pk3</tt> beside this installer, or start it "
                "from a source checkout, and press <i>Check again</i>.</p>")
            self.ready = self.fetchSource.isChecked()
        else:
            report = result["build"]
            if report.satisfied:
                parts.append(
                    f"<p style='color:{colour['ok']};'>&#10003; <b>Everything "
                    "needed to compile the engine is installed.</b> The build "
                    "takes a few minutes; you can watch it if you like.</p>")
                self.ready = True
            else:
                parts.append(
                    f"<p style='color:{colour['bad']};'><b>Some things are "
                    "missing.</b> Install them, then press <i>Check again</i>. "
                    "The commands below are for this system.</p>")
                self.ready = False
            parts.append("<h4>To compile the engine</h4>")
            parts.append(requirement_rows(report, colour))

        rip = result["rip"]
        parts.append("<h4>To rip the soundtrack and cinematics</h4>")
        parts.append(requirement_rows(rip, colour))
        if rip.blocking:
            parts.append(
                f"<p style='color:{colour['warn']};'>Without these the game "
                "installs and plays; it just falls back to the AdLib "
                "soundtrack instead of the CD music.</p>")

        self.report.show_html("".join(parts))
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self.ready


# ---------------------------------------------------------------------------
# Destination
# ---------------------------------------------------------------------------

class DestinationPage(QWizardPage):
    NAME = "destination"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("Where to install")
        self.setSubTitle("The game, its data and its saves all live in this "
                         "one folder.")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.edit = QLineEdit(str(state.destination))
        self.browse = QPushButton("Browse…")
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse)
        layout.addLayout(row)

        layout.addSpacing(8)
        self.notes = Html()
        self.notes.setMinimumHeight(110)
        layout.addWidget(self.notes, 1)

        self.edit.textChanged.connect(self._changed)
        self.browse.clicked.connect(self._browse)

    def initializePage(self) -> None:
        self._changed()

    def _browse(self) -> None:
        start = self.edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Install EC7Wolf into", start)
        if path:
            self.edit.setText(str(Path(path) / "EC7Wolf"))

    def _changed(self, *_) -> None:
        colour = self.notes.colours()
        text = self.edit.text().strip()
        parts = []
        if not text:
            self.notes.show_html("")
            self.completeChanged.emit()
            return

        path = Path(text).expanduser()
        self.state.destination = path

        needed = install.estimate_size(self.state.with_music, self.state.with_video)
        if self.state.engine is None:
            needed += 400 * 1024 * 1024
        free = install.free_space(path)
        if free < needed:
            parts.append(
                f"<p style='color:{colour['bad']};'>&#10007; About "
                f"{megabytes(needed)} is needed here and only "
                f"{megabytes(free)} is free.</p>")
        else:
            parts.append(
                f"<p style='color:{colour['dim']};'>About {megabytes(needed)} "
                f"needed, {megabytes(free)} free.</p>")

        existing = install.read_manifest(path)
        if existing:
            parts.append(
                f"<p style='color:{colour['warn']};'>There is already an "
                "EC7Wolf install here. Continuing replaces it. Saved games "
                "in its <tt>saves</tt> folder are kept.</p>")
        elif path.exists() and any(path.iterdir()):
            parts.append(
                f"<p style='color:{colour['warn']};'>That folder is not empty. "
                "The installer only adds its own files, but choosing an empty "
                "folder is tidier.</p>")

        if not os.access(self._writable_parent(path), os.W_OK):
            parts.append(
                f"<p style='color:{colour['bad']};'>&#10007; You do not have "
                "permission to write there.</p>")

        self.notes.show_html("".join(parts))
        self.completeChanged.emit()

    @staticmethod
    def _writable_parent(path: Path) -> Path:
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return probe

    def isComplete(self) -> bool:
        text = self.edit.text().strip()
        if not text:
            return False
        path = Path(text).expanduser()
        if not os.access(self._writable_parent(path), os.W_OK):
            return False
        needed = install.estimate_size(self.state.with_music, self.state.with_video)
        if self.state.engine is None:
            needed += 400 * 1024 * 1024
        return install.free_space(path) >= needed


# ---------------------------------------------------------------------------
# What to include, and what to put on the desktop
# ---------------------------------------------------------------------------

class OptionsPage(QWizardPage):
    NAME = "options"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("Options")
        self.setSubTitle("What to take off the disc, and how to start the game.")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>From the CD</b>"))
        self.music = QCheckBox("Rip the CD soundtrack")
        self.video = QCheckBox("Extract the cinematics")
        layout.addWidget(self.music)
        layout.addWidget(self.video)
        self.contentNote = body("")
        self.contentNote.setContentsMargins(22, 0, 0, 0)
        layout.addWidget(self.contentNote)

        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>Shortcuts</b>"))
        self.menu = QCheckBox("Add EC7Wolf to the applications menu")
        self.desktop = QCheckBox("Put an icon on the desktop")
        layout.addWidget(self.menu)
        layout.addWidget(self.desktop)
        layout.addStretch(1)

        for box in (self.music, self.video, self.menu, self.desktop):
            box.toggled.connect(self._changed)

    def initializePage(self) -> None:
        probe = self.state.probe or {}
        has_music = bool(probe.get("tracks"))
        has_video = bool(probe.get("cinematics"))
        # Read every wanted value out of the state before touching a widget.
        # Setting one box emits toggled, which runs _changed, which writes the
        # whole state back from boxes that have not been set yet -- so a live
        # state read half way through this would see values it just clobbered.
        wanted = (has_music and self.state.with_music,
                  has_video and self.state.with_video,
                  self.state.menu_shortcut, self.state.desktop_shortcut)

        for box, value in zip((self.music, self.video, self.menu, self.desktop),
                              wanted):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        self.music.setEnabled(has_music)
        self.video.setEnabled(has_video)

        notes = []
        if not has_music:
            notes.append("This source carries no audio tracks, so there is no "
                         "soundtrack to rip; the game will use its AdLib music.")
        if not has_video:
            notes.append("This source carries no cinematics.")
        if self.state.rip_report is not None and self.state.rip_report.blocking:
            notes.append("Some ripping tools are missing &#8211; see the "
                         "previous page. Anything that cannot be produced is "
                         "reported and skipped.")
        self.contentNote.setText(
            "<span style='color:gray;'>" + "<br>".join(notes) + "</span>"
            if notes else "")
        self._changed()

    def _changed(self, *_) -> None:
        self.state.with_music = self.music.isChecked() and self.music.isEnabled()
        self.state.with_video = self.video.isChecked() and self.video.isEnabled()
        self.state.menu_shortcut = self.menu.isChecked()
        self.state.desktop_shortcut = self.desktop.isChecked()


# ---------------------------------------------------------------------------
# Summary: the last page before anything is written
# ---------------------------------------------------------------------------

class SummaryPage(QWizardPage):
    NAME = "summary"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("Ready to install")
        self.setSubTitle("Nothing has been written yet. This is what will happen.")
        self.setCommitPage(True)
        self.setButtonText(QWizard.CommitButton, "Install")

        layout = QVBoxLayout(self)
        self.summary = Html()
        layout.addWidget(self.summary, 1)

    def initializePage(self) -> None:
        state = self.state
        # Fixed now that the destination is known, and kept beside the install
        # rather than inside it, so it survives a failure that unwinds the
        # staging directory.
        state.log_path = state.destination.parent / "ec7wolf-install.log"
        colour = self.summary.colours()
        rows = []

        if state.mode == "remove":
            self.setTitle("Ready to remove")
            self.setSubTitle("Nothing has been deleted yet. This is what "
                             "will go.")
            self.setButtonText(QWizard.CommitButton, "Remove")
            manifest = state.existing or {}
            items = [str(state.destination)] + [
                str(p) for p in manifest.get("shortcuts", [])]
            saves = state.destination / "saves"
            warning = ""
            if saves.is_dir():
                count = sum(1 for f in saves.rglob("*") if f.is_file())
                if count:
                    warning = (f"<p style='color:{colour['warn']};'>"
                               f"This includes {plural(count, 'saved game file')}"
                               f" in {saves}. Copy them somewhere else first if "
                               "you want to keep them.</p>")
            self.summary.show_html(
                "<p>These will be deleted:</p><ul><li>"
                + "</li><li>".join(items) + "</li></ul>" + warning
                + f"<p style='color:{colour['dim']};'>Log: {state.log_path}</p>")
            return

        self.setTitle("Ready to install")
        self.setSubTitle("Nothing has been written yet. This is what will "
                         "happen.")
        self.setButtonText(QWizard.CommitButton, "Install")

        def row(name: str, value: str) -> None:
            rows.append(
                f"<tr><td style='color:{colour['dim']}; padding-right:14px;' "
                f"valign='top'>{name}</td><td valign='top'>{value}</td></tr>")

        row("Game data from", state.probe["describe"] if state.probe else "&#8211;")
        if state.engine is not None:
            row("Engine", f"the existing build at<br>{state.engine.executable}")
        else:
            row("Engine", f"compiled here, with {state.jobs} parallel jobs "
                          "(this is the slow part)")
        if state.existing:
            row("Install into", f"{state.destination}<br>"
                                "<i>replacing the copy already there; your "
                                "saved games and settings are kept</i>")
        else:
            row("Install into", str(state.destination))
        row("Soundtrack", "ripped from the CD" if state.with_music else "not installed")
        row("Cinematics", "extracted from the CD" if state.with_video else "not installed")
        shortcuts = [name for name, on in
                     (("applications menu", state.menu_shortcut),
                      ("desktop", state.desktop_shortcut)) if on]
        row("Shortcuts", ", ".join(shortcuts) if shortcuts else "none")
        row("Log", str(state.log_path) if state.log_path else "&#8211;")

        self.summary.show_html("<table cellspacing='6'>" + "".join(rows) + "</table>")


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------

class ProgressPage(QWizardPage):
    NAME = "progress"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.thread: InstallThread | None = None
        self.log: LogFile | None = None
        self.cancel = None
        self.setTitle("Installing")

        layout = QVBoxLayout(self)
        self.stepLabel = QLabel("Starting…")
        self.stepLabel.setWordWrap(True)
        layout.addWidget(self.stepLabel)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        layout.addWidget(self.bar)

        row = QHBoxLayout()
        self.toggle = QPushButton("Show details")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggle_details)
        row.addWidget(self.toggle)
        row.addStretch(1)
        self.currentFile = QLabel("")
        self.currentFile.setStyleSheet("color: gray;")
        row.addWidget(self.currentFile)
        layout.addLayout(row)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(mono_font())
        # A compile is tens of thousands of lines; keeping them all would cost
        # more memory than the build itself.
        self.details.setMaximumBlockCount(4000)
        self.details.setVisible(False)
        self.details.setMinimumHeight(160)
        layout.addWidget(self.details, 1)

    # -- running -----------------------------------------------------------

    def initializePage(self) -> None:
        import threading
        state = self.state
        if state.mode == "remove":
            self.setTitle("Removing")
            self.setSubTitle("This only takes a moment.")
        else:
            self.setTitle("Installing")
            self.setSubTitle(
                "Compiling the engine takes a few minutes; the rest is quick."
                if state.engine is None else
                "Taking the game's content off the disc.")

        self.bridge = Bridge()
        self.bridge.stepped.connect(self._stepped)
        self.bridge.progressed.connect(self._progressed)
        self.bridge.detailed.connect(self._detailed)
        self.bridge.warned.connect(self._warned)

        self.cancel = threading.Event()
        if state.log_path is None:
            state.log_path = state.destination.parent / "ec7wolf-install.log"
        self.log = LogFile(state.log_path, GuiReporter(self.bridge, self.cancel))

        if state.mode == "remove":
            plan = RemovalPlan(state.destination)
        else:
            plan = InstallPlan(
                repo_root=state.repo_root, source=state.source,
                destination=state.destination,
                with_music=state.with_music, with_video=state.with_video,
                menu_shortcut=state.menu_shortcut,
                desktop_shortcut=state.desktop_shortcut,
                engine=state.engine, jobs=state.jobs)

        self.thread = InstallThread(plan, self.log, self)
        self.thread.ended.connect(self._ended)
        self.thread.start()

    def _stepped(self, name: str, detail: str) -> None:
        self.stepLabel.setText(f"<b>{name}</b>" + (f" &#8212; {detail}" if detail else ""))
        self.details.appendPlainText(f"\n--- {name}")

    def _progressed(self, fraction: float) -> None:
        self.bar.setValue(int(fraction * 1000))

    def _detailed(self, line: str) -> None:
        self.details.appendPlainText(line)
        self.currentFile.setText(line[-70:])

    def _warned(self, message: str) -> None:
        self.state.warnings.append(message)
        self.details.appendPlainText(f"warning: {message}")

    def _toggle_details(self, shown: bool) -> None:
        self.details.setVisible(shown)
        self.toggle.setText("Hide details" if shown else "Show details")

    def _ended(self, outcome: str, message: str, destination: str) -> None:
        self.state.outcome = outcome
        self.state.message = message
        self.state.installed = Path(destination) if destination else None
        if self.thread is not None and self.thread.traceback:
            self.details.appendPlainText(self.thread.traceback)
        if self.log is not None:
            self.log.close()
        self.completeChanged.emit()
        wizard = self.wizard()
        if wizard is not None:
            wizard.installFinished(outcome)

    def request_cancel(self) -> bool:
        """Ask the worker to stop. True if there was anything to stop."""
        if self.thread is not None and self.thread.isRunning():
            self.cancel.set()
            self.stepLabel.setText("<b>Cancelling…</b> undoing what was written")
            return True
        return False

    def isComplete(self) -> bool:
        return bool(self.state.outcome)


# ---------------------------------------------------------------------------
# Finish
# ---------------------------------------------------------------------------

class FinishPage(QWizardPage):
    NAME = "finish"

    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.setTitle("Finished")

        layout = QVBoxLayout(self)
        self.text = Html()
        layout.addWidget(self.text, 1)

        self.launch = QCheckBox("Start EC7Wolf now")
        layout.addWidget(self.launch)

        row = QHBoxLayout()
        self.openFolder = QPushButton("Open the install folder")
        self.openFolder.clicked.connect(self._open_folder)
        self.openLog = QPushButton("Show the log")
        self.openLog.clicked.connect(self._open_log)
        row.addWidget(self.openFolder)
        row.addWidget(self.openLog)
        row.addStretch(1)
        layout.addLayout(row)

    def initializePage(self) -> None:
        state = self.state
        colour = self.text.colours()
        parts = []

        if state.outcome == "ok" and state.mode == "remove":
            self.setSubTitle("EC7Wolf has been removed.")
            parts.append(
                f"<p style='color:{colour['ok']};'>&#10003; <b>EC7Wolf was "
                "removed.</b></p>"
                "<p>The game, its shortcuts and its entry in the list of "
                "installed programs are all gone. Nothing else on the system "
                "was touched.</p>")
            self.launch.setVisible(False)
            self.openFolder.setVisible(False)
        elif state.outcome == "ok":
            self.setSubTitle("EC7Wolf is installed.")
            parts.append(
                f"<p style='color:{colour['ok']};'>&#10003; <b>Installed to "
                f"{state.installed}</b></p>")
            parts.append("<p>Start it from the applications menu, from the "
                         "desktop icon, or by running the launcher in that "
                         "folder. Configuration and saved games stay inside "
                         "the install, so nothing else on the system is "
                         "touched.</p>")
            parts.append(
                f"<p style='color:{colour['dim']};'>To remove it later, run "
                f"<tt>uninstall.sh</tt> in that folder; it takes the menu "
                "entry and the icons with it.</p>")
            self.launch.setVisible(True)
            self.launch.setChecked(True)
            self.openFolder.setVisible(True)
        elif state.outcome == "cancelled":
            self.setSubTitle("Cancelled.")
            parts.append("<p><b>The install was cancelled.</b> Everything it "
                         "had written was removed; nothing was left behind.</p>")
            self.launch.setVisible(False)
            self.openFolder.setVisible(False)
        else:
            self.setSubTitle("The install did not finish.")
            parts.append(
                f"<p style='color:{colour['bad']};'>&#10007; <b>{state.message}"
                "</b></p>")
            parts.append("<p>Nothing was left half-installed. The log has the "
                         "full detail, including the compiler's own messages "
                         "if the build was the thing that failed.</p>")
            self.launch.setVisible(False)
            self.openFolder.setVisible(False)

        if state.warnings:
            parts.append(f"<p style='color:{colour['warn']};'><b>Worth "
                         "knowing</b></p><ul><li>"
                         + "</li><li>".join(state.warnings) + "</li></ul>")

        parts.append(f"<p style='color:{colour['dim']};'>Log: {state.log_path}</p>")
        self.text.show_html("".join(parts))

    def _open_folder(self) -> None:
        if self.state.installed:
            self._open(self.state.installed)

    def _open_log(self) -> None:
        if self.state.log_path:
            self._open(self.state.log_path)

    @staticmethod
    def _open(path: Path) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def launch_requested(self) -> bool:
        return self.launch.isVisible() and self.launch.isChecked()
