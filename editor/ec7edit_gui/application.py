# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Application entry: create the window, and catch what would otherwise vanish.

An unhandled exception in a Qt slot prints to stderr and the program carries on
with the user none the wiser, which is how an editor ends up in a state nobody
can explain. The hook here puts it somewhere visible instead.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from ec7edit_core import __version__

from .main_window import MainWindow
from .settings import APPLICATION, ORGANISATION, Settings


def install_exception_hook(window=None, *, show_dialog: bool = True) -> None:
    """Report an unhandled exception rather than losing it to stderr.

    The console always gets the traceback and the Problems panel always gets a
    line. The dialog is one at a time: a second exception raised while the
    first is on screen would otherwise stack modals, or recurse if it happened
    inside the reporting itself.
    """
    showing = []

    def hook(kind, value, tb):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        sys.stderr.write("".join(traceback.format_exception(kind, value, tb)))
        if window is not None:
            try:
                window._note_problem(f"Unexpected error: {value}")
            except Exception:
                pass
        if not show_dialog or showing or QApplication.instance() is None:
            return
        showing.append(True)
        try:
            QMessageBox.critical(
                None, "EC7Edit hit a problem",
                f"{value}\n\nThe details are in the Problems panel and on the console.",
            )
        finally:
            showing.clear()

    sys.excepthook = hook


def build_application(argv=None) -> QApplication:
    application = QApplication.instance()
    if application is None:
        application = QApplication(argv if argv is not None else sys.argv)
    application.setOrganizationName(ORGANISATION)
    application.setApplicationName(APPLICATION)
    application.setApplicationVersion(__version__)
    application.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    return application


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ec7edit-gui", description="EC7Edit")
    parser.add_argument("project", nargs="?", type=Path, help="a project to open")
    parser.add_argument("--setup", action="store_true", help="open first-run setup")
    parser.add_argument("--version", action="version", version=f"EC7Edit {__version__}")
    arguments = parser.parse_args(argv)

    application = build_application()
    settings = Settings()
    window = MainWindow(settings)
    install_exception_hook(window)

    if arguments.setup or not settings.configured:
        window.show()
        window.run_setup()
    else:
        window.show()

    if arguments.project:
        window.open_project(str(arguments.project))

    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
