"""The installer window.

A QWizard, because that is what an installer is and Qt already knows how one
behaves: Back and Next, a commit page that turns into "Install", no way back
once it has started writing. Building that out of a stack of plain widgets
would mean reimplementing the parts users already have expectations about.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QWizard

from ec7install import identity, install

from . import pages
from .worker import run_detached

PAGE_CLASSES = (pages.WelcomePage, pages.LicensePage, pages.SourcePage,
                pages.EnginePage, pages.DestinationPage, pages.OptionsPage,
                pages.SummaryPage, pages.ProgressPage, pages.FinishPage)


def find_icon(repo_root: Path) -> Path | None:
    for candidate in ("src/macosx/icon.iconset/icon_128x128.png",
                      "src/macosx/icon.iconset/icon_256x256.png",
                      "src/posix/icon.svg"):
        path = repo_root / candidate
        if path.is_file():
            return path
    return None


class InstallerWizard(QWizard):
    def __init__(self, repo_root: Path, source: Path | None = None,
                 destination: Path | None = None):
        super().__init__()
        self.state = pages.State(repo_root)
        if source is not None:
            self.state.source_path = source
        if destination is not None:
            self.state.destination = destination

        self.setWindowTitle("EC7Wolf Setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.NoCancelButtonOnLastPage, True)
        self.setOption(QWizard.HaveHelpButton, False)
        self.resize(720, 560)

        icon = find_icon(repo_root)
        if icon is not None:
            pixmap = QPixmap(str(icon))
            if not pixmap.isNull():
                self.setWindowIcon(QIcon(pixmap))
                self.setPixmap(QWizard.LogoPixmap, pixmap.scaled(
                    48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.ids: dict[str, int] = {}
        for page_class in PAGE_CLASSES:
            page = page_class(self.state)
            self.ids[page_class.NAME] = self.addPage(page)

    # -- helpers -----------------------------------------------------------

    def page_named(self, name: str):
        return self.page(self.ids[name])

    @property
    def progress_page(self) -> pages.ProgressPage:
        return self.page_named("progress")

    def installFinished(self, outcome: str) -> None:
        """Called from the progress page when the worker reports back."""
        if self.currentId() == self.ids["progress"]:
            self.next()

    # -- closing -----------------------------------------------------------

    def reject(self) -> None:
        """Cancel, Escape, and the window's close button all arrive here.

        An install in flight is the case that matters: closing the window while
        a worker thread is writing files would leave a half-made install and a
        thread with nothing to report to, so the request is passed to the
        worker and the window stays until it has unwound.
        """
        progress = self.progress_page
        if self.currentId() == self.ids["progress"] and not self.state.outcome:
            answer = QMessageBox.question(
                self, "Stop the install?",
                "The install is still running. Stop it and undo what has been "
                "written so far?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                progress.request_cancel()
            return

        if self.currentId() not in (self.ids["welcome"], self.ids["finish"]):
            answer = QMessageBox.question(
                self, "Quit?", "Quit the installer? Nothing has been installed.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        super().reject()

    def accept(self) -> None:
        finish = self.page_named("finish")
        if finish.launch_requested() and self.state.installed:
            manifest = install.read_manifest(self.state.installed) or {}
            launcher = manifest.get("launcher")
            if launcher and Path(launcher).exists():
                run_detached([str(launcher)], cwd=self.state.installed)
        super().accept()


def selftest(repo_root: Path) -> int:
    """Construct the whole wizard offscreen and report by exit code.

    This is what a frozen build is checked with. Exit codes are the only thing
    a windowed executable can report reliably -- it has no console to print to,
    so anything written to stdout may go nowhere -- and constructing every page
    is a far better test than --help: it loads Qt, builds the widgets and reads
    the bundled licence, which is where a bundle missing a file or a Qt plugin
    actually fails.
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    QApplication([])
    wizard = InstallerWizard(repo_root)
    expected = ["welcome", "license", "source", "engine", "destination",
                "options", "summary", "progress", "finish"]
    if list(wizard.ids) != expected:
        return 1
    licence = wizard.page_named("license")
    licence.initializePage()
    if len(licence.text.toPlainText()) < 1000:
        return 2              # the licence did not travel with the bundle
    if wizard.windowIcon().isNull():
        return 3              # nor did the icon
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Install EC7Wolf, with a window rather than a terminal.")
    parser.add_argument("--source", type=Path,
                        help="pre-fill the CD, image or folder to install from")
    parser.add_argument("--dest", type=Path, help="pre-fill the install folder")
    parser.add_argument("--repo", type=Path, help="the EC7Wolf source tree")
    parser.add_argument("--selftest", action="store_true",
                        help="build the wizard without showing it and exit; "
                             "used to check a frozen build actually works")
    arguments = parser.parse_args(argv)

    if arguments.repo:
        repo_root = arguments.repo
    elif identity.is_frozen():
        # Frozen: the bundled licence and icons are in the unpacked directory,
        # and the engine -- which cannot be compiled without a source tree --
        # is looked for beside the setup executable, where whoever assembled
        # the download would have put it.
        repo_root = identity.bundled_root()
    else:
        repo_root = Path(__file__).resolve().parent.parent.parent

    if arguments.selftest:
        # Before the QApplication below: Qt permits exactly one per process,
        # and the self-test needs to make its own offscreen.
        return selftest(repo_root)

    application = QApplication(sys.argv)
    application.setApplicationName("EC7Wolf Setup")
    application.setApplicationDisplayName("EC7Wolf Setup")
    application.setOrganizationName("EC7Wolf")
    application.setDesktopFileName("ec7wolf-setup")

    wizard = InstallerWizard(repo_root, arguments.source, arguments.dest)
    if identity.is_frozen():
        wizard.state.extra_engine_paths.append(Path(sys.executable).resolve().parent)
    icon = find_icon(repo_root)
    if icon is not None:
        application.setWindowIcon(QIcon(str(icon)))
    wizard.show()
    return application.exec()
