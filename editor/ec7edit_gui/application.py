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

import PySide6
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMessageBox

from ec7edit_core import __version__

from .main_window import MainWindow
from .settings import APPLICATION, ORGANIZATION, Settings


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


#: Messages from the Qt platform plugin that describe the platform rather than
#: anything this program did, and that nobody can act on.
#:
#: Wayland does not let an ordinary window grab the mouse -- only popups may,
#: by design -- so Qt says so and carries on. It comes up when Qt asks for a
#: grab internally, which dragging a dock panel does, and it names a plugin
#: nobody was thinking about in the middle of doing something else. The
#: offscreen plugin's two are the same kind of thing, and they turn a test
#: run's output into a wall of noise.
#:
#: Deliberately an exact list. A pattern like "starts with 'This plugin'" would
#: grow to cover messages that do matter.
_PLATFORM_NOISE = (
    "This plugin supports grabbing the mouse only for popup windows",
    "This plugin does not support propagateSizeHints()",
    "This plugin does not support raise()",
)


def _quieten_platform_noise() -> None:
    """Drop the messages above, and pass every other one through untouched."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def handler(kind, context, message):
        if message.strip() in _PLATFORM_NOISE:
            return
        stream = sys.stderr
        label = {QtMsgType.QtDebugMsg: "debug", QtMsgType.QtInfoMsg: "info",
                 QtMsgType.QtWarningMsg: "warning",
                 QtMsgType.QtCriticalMsg: "critical",
                 QtMsgType.QtFatalMsg: "fatal"}.get(kind, "qt")
        print(f"Qt {label}: {message}", file=stream)

    qInstallMessageHandler(handler)


def build_application(argv=None) -> QApplication:
    _quieten_platform_noise()
    application = QApplication.instance()
    if application is None:
        application = QApplication(argv if argv is not None else sys.argv)
    application.setOrganizationName(ORGANIZATION)
    application.setApplicationName(APPLICATION)
    application.setApplicationVersion(__version__)
    application.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    return application


def selftest() -> int:
    """Prove this build works, without a display and without game data.

    The packaged editor's own answer to "does this run on your machine". A
    frozen build can fail in ways a checkout never does -- a Qt plugin left out
    of the freeze, a resource path that was right relative to the source tree
    and wrong inside a bundle -- and every one of those looks the same to
    somebody who double-clicks it: a window that does not appear.
    `--version` proves only that the executable starts, which is the part that
    was never in doubt.

    So this builds the real main window offscreen, reads the real catalog,
    and prints key=value lines. Deliberately plain, like the engine's
    --editor-capabilities: something a support conversation can paste.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from ec7edit_core import __version__ as core_version
    from ec7edit_core.bundle import catalog_path, frozen, resource_root
    from ec7edit_core.catalog import load_catalog
    from ec7edit_core.document import SCHEMA_VERSION
    from ec7edit_core.engine_runner import PROTOCOL_VERSION

    print(f"editor=EC7Edit")
    print(f"version={__version__}")
    print(f"core={core_version}")
    print(f"frozen={'yes' if frozen() else 'no'}")
    print(f"python={sys.version.split()[0]}")
    print(f"qt={QtCore.qVersion()}")
    print(f"pyside={PySide6.__version__}")
    print(f"schema={SCHEMA_VERSION}")
    print(f"editor-protocol={PROTOCOL_VERSION}")
    print(f"resources={resource_root()}")

    try:
        catalog = load_catalog(catalog_path())
    except Exception as error:                       # noqa: BLE001 - reported, not raised
        print(f"catalog=missing ({error})")
        return 1
    print(f"catalog={len(catalog.entries)} entries, schema {catalog.schema}")

    application = build_application([])
    settings = Settings()
    window = MainWindow(settings, catalog=catalog)
    window.show()
    application.processEvents()
    docks = len(window.findChildren(QDockWidget))
    window.close()
    print(f"window={window.width()}x{window.height()}, {docks} docks")
    print("selftest=ok")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ec7edit-gui", description="EC7Edit")
    parser.add_argument("project", nargs="?", type=Path, help="a project to open")
    parser.add_argument("--setup", action="store_true", help="open first-run setup")
    parser.add_argument("--version", action="version", version=f"EC7Edit {__version__}")
    parser.add_argument("--selftest", action="store_true",
                        help="build the window, report what this build is, and exit")
    arguments = parser.parse_args(argv)

    if arguments.selftest:
        return selftest()

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
