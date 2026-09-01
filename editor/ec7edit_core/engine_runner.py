# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Building the command line that launches a playtest -- as data, not a string.

A launch is an argument *vector*, never a shell string. There is no quoting to
get wrong, no path with a space to break it, and nothing a project file could
put in a filename that would become a command. A project is untrusted input;
the only things from it that reach this are a map slot number and a WAD the
editor wrote itself.

The plan is returned rather than run, so the GUI can show the user exactly what
it is about to do, and so a test can assert on the arguments without starting a
game.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import Diagnostic, Ec7EditError, Severity

#: The engine wants the *extension* of its data files here, not a path. This is
#: the distinction that confuses everyone once: `--data CO7` selects Corridor 7,
#: and the directory comes from the working directory.
DATA_EXTENSION = "CO7"

_MARKER = re.compile(r"^MAP[0-9]{2,3}$")
#: What the engine will accept as a session id, copied from its own rule.
_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LaunchError(Ec7EditError):
    pass


def _error(message: str) -> LaunchError:
    return LaunchError(Diagnostic("C7E-ENGINE-001", Severity.ERROR, message))


#: The editor event protocol this build of the editor speaks. The engine is
#: asked for the same number and refuses if it speaks another, rather than
#: sending events the reader may interpret differently.
PROTOCOL_VERSION = 1

#: Lines the engine emits for us look like `EC7EDIT <session> <event> k=v ...`.
#: Anchored on the session id, not on the prefix: the engine prints plenty of
#: other things, a map under test can contain arbitrary text, and a reader that
#: matched the prefix alone could be handed a forged event by the very map it
#: is testing.
_EVENT = re.compile(r"^EC7EDIT (?P<session>[A-Za-z0-9_-]{1,64}) (?P<event>[a-z-]+)(?P<rest>.*)$")


@dataclass(frozen=True)
class EngineEvent:
    """One protocol line, already attributed to a session."""

    event: str
    fields: dict

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)


def parse_event(line: str, session: str) -> EngineEvent | None:
    """One line of engine output, or None if it is not ours.

    Every rejection here is deliberate. A line whose session is not this one
    belongs to another launch -- or to nobody, which is the case that matters:
    the map being tested is user content, and user content that can print is
    user content that can lie.
    """
    match = _EVENT.match(line.strip())
    if match is None or match.group("session") != session:
        return None
    fields = {}
    for token in match.group("rest").split():
        key, sep, value = token.partition("=")
        if sep:
            fields[key] = value
    return EngineEvent(match.group("event"), fields)


@dataclass(frozen=True)
class LaunchPlan:
    """Everything needed to start a playtest, and nothing else."""

    executable: Path
    arguments: list[str]
    cwd: Path
    environment: dict = field(default_factory=dict)
    #: The nonce the engine echoes on every event line.
    session: str = ""
    #: Where this session's config and saves go. Never the player's own: a
    #: playtest must not rewrite the settings or the saved games of somebody
    #: who also plays this game.
    session_dir: Path | None = None
    #: The map file this launch is testing. Named rather than recovered from
    #: the argument list: "which of these files is mine" is a question the plan
    #: already knows the answer to, and digging it back out of argv is the kind
    #: of guess that works until somebody appends an argument.
    preview: Path | None = None
    #: What was tested, so a log can be matched to it afterwards.
    export_digest: str = ""
    revision: int = -1

    @property
    def argv(self) -> list[str]:
        return [str(self.executable), *self.arguments]

    def described(self) -> str:
        """What to show the user before running it."""
        return f"{self.cwd}$ {' '.join(self.argv)}"

    def summary(self) -> dict:
        """The structured dump the plan asks a launch to be able to produce."""
        return {
            "executable": str(self.executable),
            "arguments": list(self.arguments),
            "cwd": str(self.cwd),
            "session": self.session,
            "session_dir": str(self.session_dir) if self.session_dir else "",
            "preview": str(self.preview) if self.preview else "",
            "export_digest": self.export_digest,
            "revision": self.revision,
        }


def build_launch_plan(
    *,
    executable: Path | str,
    data_dir: Path | str,
    preview_wad: Path | str,
    marker: str = "MAP01",
    skill: int = 2,
    extra: list[str] | None = None,
    session: str = "",
    session_dir: Path | str | None = None,
    renderer: str = "",
    export_digest: str = "",
    revision: int = -1,
) -> LaunchPlan:
    """The playtest command for one map of one preview WAD.

    `--file` last, because a WAD loaded later overrides the base data by lump
    name -- which is the entire mechanism by which the edit reaches the game.
    """
    executable = Path(executable).expanduser()
    data_dir = Path(data_dir).expanduser()
    preview = Path(preview_wad).expanduser()

    if not executable.is_file():
        raise _error(f"no engine at {executable}")
    if not data_dir.is_dir():
        raise _error(f"no game data directory at {data_dir}")
    if not preview.is_file():
        raise _error(f"no preview WAD at {preview}")
    if not _MARKER.match(marker):
        raise _error(f"{marker!r} is not a map marker the engine generates")
    if not 1 <= skill <= 4:
        raise _error(f"skill {skill} is outside 1..4")

    if session and not _SESSION.match(session):
        raise _error(f"{session!r} is not a usable session id; the engine "
                     "accepts 1-64 characters of A-Z a-z 0-9 - _")

    arguments = [
        "--data", DATA_EXTENSION,
        "--tedlevel", marker,
        "--skill", str(skill),
    ]

    resolved_session_dir = Path(session_dir).expanduser().resolve() if session_dir else None
    if resolved_session_dir is not None:
        # Isolated, always. The engine writes its config on exit and its saves
        # whenever asked, and a playtest that did either into the player's own
        # directories would change the game they play.
        arguments += [
            "--config", str(resolved_session_dir / "ec7wolf.cfg"),
            "--savedir", str(resolved_session_dir / "saves"),
        ]
    if session:
        arguments += [
            "--editor-protocol", str(PROTOCOL_VERSION),
            "--editor-session", session,
        ]
    if renderer:
        arguments += ["--vid-renderer", renderer]
    if extra:
        arguments.extend(str(item) for item in extra)

    # `--file` last, because a WAD loaded later overrides the base data by lump
    # name -- which is the entire mechanism by which the edit reaches the game.
    arguments += ["--file", str(preview.resolve())]

    return LaunchPlan(
        executable=executable.resolve(),
        arguments=arguments,
        # The engine finds its data in the working directory, which is why this
        # runs there rather than passing a path it has no argument for.
        cwd=data_dir.resolve(),
        session=session,
        session_dir=resolved_session_dir,
        preview=preview.resolve(),
        export_digest=export_digest,
        revision=revision,
    )


# ---------------------------------------------------------------------------
# The session: what a launch is, and what it becomes
# ---------------------------------------------------------------------------


class SessionState(enum.Enum):
    """Where a playtest is.

    A state machine rather than a pair of booleans because the interesting
    answers are the ones in between: a process that started but never selected
    data is a different failure from one that loaded the map and then died, and
    an editor that only knew "running" or "not" could not say which.
    """

    IDLE = "idle"
    STARTING = "starting"      # process spawned, no event yet
    LOADING = "loading"        # engine answered; data and files are being read
    PLAYING = "playing"        # the map was entered
    STOPPING = "stopping"      # we asked it to end
    FINISHED = "finished"      # ended, having reached the map
    FAILED = "failed"          # ended without reaching it, or said fatal


#: Which states mean the process is no longer running.
TERMINAL_STATES = (SessionState.IDLE, SessionState.FINISHED, SessionState.FAILED)


@dataclass
class Session:
    """One playtest, and everything learned about it.

    Deliberately free of Qt: everything here is driven by feeding it lines, so
    the whole state machine is testable without starting a process, and the GUI
    layer is only the part that produces the lines.
    """

    plan: LaunchPlan
    state: SessionState = SessionState.IDLE
    events: list = field(default_factory=list)
    log: list = field(default_factory=list)
    #: What the engine said went wrong, if it said anything.
    failure: str = ""
    marker_entered: str = ""
    preview_loaded: bool = False
    exit_code: int | None = None

    #: How many log lines to keep. A playtest can print for as long as somebody
    #: plays, and an editor that grew a list forever would be an editor that
    #: eventually stopped.
    LOG_LIMIT = 4000

    def started(self) -> None:
        self.state = SessionState.STARTING

    def feed(self, line: str) -> "EngineEvent | None":
        """One line of engine output. Returns the event if it was one."""
        text = line.rstrip("\r\n")
        self.log.append(text)
        if len(self.log) > self.LOG_LIMIT:
            del self.log[: len(self.log) - self.LOG_LIMIT]

        event = parse_event(text, self.plan.session) if self.plan.session else None
        if event is None:
            return None
        self.events.append(event)

        if event.event == "hello":
            self.state = SessionState.LOADING
        elif event.event == "preview-load":
            # Only our own file counts. The engine reports every resource it
            # loads, and the game's own data loading is not evidence that the
            # map under test did.
            mine = self.plan.preview.name if self.plan.preview else ""
            if mine and event.get("path").endswith(mine):
                self.preview_loaded = event.get("loaded") == "yes"
                if not self.preview_loaded:
                    self.failure = (
                        f"the engine could not read {event.get('path')}. It would "
                        "have played the shipped map of that number instead.")
        elif event.event == "map-entry":
            self.marker_entered = event.get("marker")
            self.state = SessionState.PLAYING
        elif event.event == "fatal":
            self.failure = event.get("message", "").replace("_", " ")
        elif event.event == "session-result":
            self.state = (SessionState.FINISHED
                          if self.reached_the_map and not self.failure
                          else SessionState.FAILED)
        return event

    def stopping(self) -> None:
        self.state = SessionState.STOPPING

    def finished(self, exit_code: int) -> None:
        """The process is gone. Decide what that means."""
        self.exit_code = exit_code
        if self.state in TERMINAL_STATES:
            return
        if self.reached_the_map and not self.failure:
            self.state = SessionState.FINISHED
            return
        self.state = SessionState.FAILED
        if not self.failure:
            # The engine died without saying why, which is its own diagnosis:
            # what it managed to do first is the most useful thing to report.
            if self.state is SessionState.STARTING or not self.events:
                self.failure = (
                    f"the engine exited with code {exit_code} without answering. "
                    "It may be a different build, or one too old to speak the "
                    "editor protocol.")
            elif not self.preview_loaded:
                self.failure = f"the engine exited with code {exit_code} before loading the map."
            else:
                self.failure = f"the engine exited with code {exit_code} before reaching the map."

    @property
    def reached_the_map(self) -> bool:
        """The one question a playtest exists to answer."""
        return bool(self.marker_entered) and self.preview_loaded

    @property
    def running(self) -> bool:
        return self.state not in TERMINAL_STATES

    def describe(self) -> str:
        if self.state is SessionState.FINISHED:
            return f"Played {self.marker_entered}, exit code {self.exit_code}"
        if self.state is SessionState.FAILED:
            return self.failure or "The engine did not reach the map"
        return {
            SessionState.IDLE: "Not started",
            SessionState.STARTING: "Starting the engine…",
            SessionState.LOADING: "Loading the map…",
            SessionState.PLAYING: f"Playing {self.marker_entered}",
            SessionState.STOPPING: "Stopping…",
        }[self.state]
