"""Running the install off the GUI thread, and getting the news back safely.

Qt widgets may only be touched from the thread that created them, so nothing in
here calls a widget. The worker owns a Reporter that emits signals instead; Qt
queues those across the thread boundary, and the pages update themselves when
they arrive. That indirection is the whole point of this module -- it is the
only place where the two threads meet.
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ec7install.progress import Canceled, Reporter


class Bridge(QObject):
    """The signals a reporter emits. Created on the GUI thread, always."""

    stepped = Signal(str, str)
    progressed = Signal(float)
    detailed = Signal(str)
    warned = Signal(str)


class GuiReporter(Reporter):
    """A Reporter that talks to the window through a Bridge.

    Deliberately not a QObject: mixing Qt's metaclass into the reporter
    hierarchy buys nothing and can only cause trouble, so the Qt half lives in
    a separate object this one holds.
    """

    def __init__(self, bridge: Bridge, cancel: threading.Event):
        self._bridge = bridge
        self._cancel = cancel
        self._last_progress = -1.0

    def step(self, name: str, detail: str = "") -> None:
        self._bridge.stepped.emit(name, detail)

    def progress(self, fraction: float) -> None:
        # A compile reports progress per file; forwarding every one of those
        # would post thousands of events that resolve to the same pixel.
        if abs(fraction - self._last_progress) < 0.001 and fraction < 1.0:
            return
        self._last_progress = fraction
        self._bridge.progressed.emit(float(fraction))

    def detail(self, line: str) -> None:
        self._bridge.detailed.emit(line)

    def warn(self, message: str) -> None:
        self._bridge.warned.emit(message)

    def canceled(self) -> bool:
        return self._cancel.is_set()


class InstallThread(QThread):
    """Runs one InstallPlan and reports how it ended.

    Every outcome leaves by the same signal, including the exceptions, because
    a front end that only hears about success has no way to show a failure.
    """

    ended = Signal(str, str, str)      # outcome, message, destination

    def __init__(self, plan, reporter: Reporter, parent=None):
        super().__init__(parent)
        self._plan = plan
        self._reporter = reporter
        self.traceback = ""

    def run(self) -> None:
        try:
            destination = self._plan.run(self._reporter)
            self.ended.emit("ok", "", str(destination))
        except Canceled:
            self.ended.emit("canceled", "", "")
        except Exception as error:                    # noqa: BLE001
            self.traceback = traceback.format_exc()
            self.ended.emit("failed", str(error) or error.__class__.__name__, "")


class Task(QThread):
    """A one-shot background call, for work too slow to do on the GUI thread.

    Probing a CD in a drive and scanning for compilers both take long enough to
    freeze a window, and a frozen window during a scan reads as a crash.
    """

    ended = Signal(object, str)        # result, error message

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self._function = function

    def run(self) -> None:
        try:
            self.ended.emit(self._function(), "")
        except Exception as error:                    # noqa: BLE001
            self.ended.emit(None, str(error) or error.__class__.__name__)


def run_detached(command: list[str], cwd: Path | None = None) -> bool:
    """Start the game and let go of it, so the installer can exit."""
    import subprocess
    try:
        subprocess.Popen(command, cwd=str(cwd) if cwd else None,
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
