# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Background work, and the two rules that keep it from lying to the user.

**A stale result is dropped, not shown.** Every request carries the document
revision it was made against. When it finishes, if the document has moved on,
the answer is thrown away. Without this, scrolling a palette fast enough shows
thumbnails from three selections ago arriving over the current one, and the
user is looking at the wrong picture with no way to tell.

**Cancellation is cooperative and checked.** A canceled job stops at its next
checkpoint and reports nothing. It is never killed mid-write, because a
half-written cache entry is worse than a slow one.

The pool is small on purpose. Decoding a wall page takes a millisecond or two;
the cost that matters is the round trip, not the throughput, and thirty threads
fighting over one palette would be slower as well as harder to reason about.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


@dataclass
class Job:
    """One unit of background work, tagged with what it was asked about."""

    key: str
    revision: int
    work: callable
    #: Set to stop at the next checkpoint. Read by the work function.
    canceled: bool = False
    metadata: dict = field(default_factory=dict)
    #: Whether the answer goes stale when the document changes. False for work
    #: that does not depend on the document at all.
    tracks_revision: bool = True

    def cancel(self) -> None:
        self.canceled = True


class _Signals(QObject):
    finished = Signal(object, object)  # job, result
    failed = Signal(object, str)  # job, traceback text


class _Task(QRunnable):
    def __init__(self, job: Job, signals: _Signals) -> None:
        super().__init__()
        self.job = job
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        if self.job.canceled:
            return
        try:
            result = self.job.work(self.job)
        except BaseException:  # a worker must never take the application down
            self.signals.failed.emit(self.job, traceback.format_exc())
            return
        if not self.job.canceled:
            self.signals.finished.emit(self.job, result)


class WorkerPool(QObject):
    """Runs jobs off the GUI thread and delivers only the answers still wanted.

    `completed` carries `(key, result)` for a job whose revision still matches
    the document. `discarded` carries the key of one that finished too late,
    which exists so a test can prove staleness is handled rather than assume it.
    """

    completed = Signal(str, object)
    discarded = Signal(str)
    failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None, *, max_threads: int = 4) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._jobs: dict[str, Job] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def set_revision(self, revision: int) -> None:
        """Tell the pool where the document is now.

        Jobs already in flight against an older revision will be discarded when
        they finish. They are not canceled: they may be nearly done, and the
        cost of letting them finish and dropping the answer is lower than the
        bookkeeping to stop them.
        """
        self._revision = revision

    def submit(self, key: str, work, *, metadata: dict | None = None,
               tracks_revision: bool = True) -> Job:
        """Queue work under `key`, replacing any earlier job with that key.

        `tracks_revision=False` for work whose answer does not depend on the
        document. Decoding a wall page is the example: the artwork is the
        user's copy of the game, and it does not change because they painted a
        cell. Tagging those with the revision meant that painting *anything*
        discarded every thumbnail still in flight, and the palette stopped
        filling in.
        """
        existing = self._jobs.get(key)
        if existing is not None:
            existing.cancel()
        job = Job(key=key, revision=self._revision, work=work, metadata=metadata or {},
                  tracks_revision=tracks_revision)
        self._jobs[key] = job
        self._pool.start(_Task(job, self._signals))
        return job

    def cancel(self, key: str) -> None:
        job = self._jobs.pop(key, None)
        if job is not None:
            job.cancel()

    def cancel_all(self) -> None:
        for job in self._jobs.values():
            job.cancel()
        self._jobs.clear()

    def wait(self, timeout_ms: int = 5000) -> bool:
        """Block until the queue drains. For tests and for shutdown."""
        return self._pool.waitForDone(timeout_ms)

    @property
    def active(self) -> int:
        return self._pool.activeThreadCount()

    def _on_finished(self, job: Job, result) -> None:
        if self._jobs.get(job.key) is job:
            del self._jobs[job.key]
        if job.canceled:
            return
        if job.tracks_revision and job.revision != self._revision:
            self.discarded.emit(job.key)
            return
        self.completed.emit(job.key, result)

    def _on_failed(self, job: Job, message: str) -> None:
        if self._jobs.get(job.key) is job:
            del self._jobs[job.key]
        self.failed.emit(job.key, message)
