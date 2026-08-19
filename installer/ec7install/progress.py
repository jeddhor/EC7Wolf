"""Progress reporting shared by every front end.

One object is passed down through the install. The GUI implements it with a bar
and a text pane, the CLI with lines on a terminal, the gates with a list they
assert against -- and none of the work below has to know which.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


class Cancelled(Exception):
    """Raised out of a step when the front end asked to stop."""


class Reporter:
    """Base reporter: records nothing, prints nothing, never cancels."""

    def step(self, name: str, detail: str = "") -> None:
        """A new phase started."""

    def progress(self, fraction: float) -> None:
        """Overall completion, 0.0 to 1.0."""

    def detail(self, line: str) -> None:
        """One line of verbose output -- compiler messages, file names."""

    def warn(self, message: str) -> None:
        """Something the user should know that is not fatal."""

    def cancelled(self) -> bool:
        """Front ends override this; steps poll it at safe points."""
        return False

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise Cancelled()


class LogFile(Reporter):
    """Wraps another reporter and writes everything to a file as well.

    An installer that fails without leaving a log behind is not much use to
    whoever has to work out why, so this is always on -- the front end decides
    whether to show it, never whether to keep it.
    """

    def __init__(self, path: Path, inner: Reporter | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8", errors="replace")
        self._inner = inner or Reporter()
        self._start = time.time()
        self._write("=== EC7Wolf install log ===")

    def _write(self, text: str) -> None:
        self._file.write(f"[{time.time() - self._start:7.2f}] {text}\n")
        self._file.flush()

    def step(self, name: str, detail: str = "") -> None:
        self._write(f"--- {name}" + (f": {detail}" if detail else ""))
        self._inner.step(name, detail)

    def progress(self, fraction: float) -> None:
        self._inner.progress(fraction)

    def detail(self, line: str) -> None:
        self._write(f"    {line}")
        self._inner.detail(line)

    def warn(self, message: str) -> None:
        self._write(f"!!! {message}")
        self._inner.warn(message)

    def cancelled(self) -> bool:
        return self._inner.cancelled()

    def close(self) -> None:
        self._write("=== end ===")
        self._file.close()


class ConsoleReporter(Reporter):
    """The command-line face: steps always, detail only when asked."""

    def __init__(self, verbose: bool = False, stream=sys.stdout):
        self.verbose = verbose
        self.stream = stream
        self._last = -1.0

    def step(self, name: str, detail: str = "") -> None:
        self.stream.write(f"\n==> {name}" + (f" ({detail})" if detail else "") + "\n")
        self.stream.flush()

    def progress(self, fraction: float) -> None:
        percent = int(fraction * 100)
        if percent != self._last and not self.verbose:
            self._last = percent
            self.stream.write(f"\r    {percent:3d}%")
            self.stream.flush()

    def detail(self, line: str) -> None:
        if self.verbose:
            self.stream.write(f"    {line}\n")
            self.stream.flush()

    def warn(self, message: str) -> None:
        self.stream.write(f"\n    warning: {message}\n")
        self.stream.flush()
