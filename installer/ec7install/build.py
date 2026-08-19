"""Finding an existing engine, or building one.

The installer prefers an engine the user already compiled: that is both faster
and more respectful of a developer's own tree. Only when there is none does it
configure and build, streaming every line of output to the reporter so a front
end can show the compile happening.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .progress import Cancelled, Reporter

EXE_NAME = "ec7wolf.exe" if platform.system() == "Windows" else "ec7wolf"
PK3_NAME = "ec7wolf.pk3"


class BuildError(Exception):
    pass


class Engine:
    """A built engine: the executable and the data pk3 that must match it."""

    def __init__(self, executable: Path, pk3: Path, source: str):
        self.executable = executable
        self.pk3 = pk3
        self.source = source

    def __repr__(self) -> str:
        return f"<Engine {self.executable} ({self.source})>"


def find_existing(repo_root: Path, extra: list[Path] | None = None) -> Engine | None:
    """An already-built engine, if there is one.

    Both files have to be present and the pk3 has to be at least as new as the
    executable. A stale pk3 beside a fresh binary is the single most common way
    to get a build that runs but behaves like an older one -- the project's own
    notes record losing time to exactly that -- so it is treated as "no usable
    engine" rather than quietly shipped.
    """
    candidates: list[Path] = list(extra or [])
    candidates += [
        repo_root.parent / "builds" / "release-build",
        repo_root.parent / "builds" / "release",
        repo_root / "build",
        repo_root / "release",
    ]

    for directory in candidates:
        executable = directory / EXE_NAME
        pk3 = directory / PK3_NAME
        if not (executable.is_file() and pk3.is_file()):
            continue
        if not os.access(executable, os.X_OK) and platform.system() != "Windows":
            continue
        if pk3.stat().st_mtime < executable.stat().st_mtime - 1:
            continue
        return Engine(executable, pk3, f"already built in {directory}")
    return None


def _generator() -> list[str]:
    if shutil.which("ninja") or shutil.which("ninja-build"):
        return ["-G", "Ninja"]
    return []


def _stream(command: list[str], cwd: Path, reporter: Reporter,
            on_line=None) -> int:
    """Run a command, forwarding output line by line as it appears.

    Line-buffered on purpose: the point of the detail pane is watching the build
    move, and a pipe that only flushes at the end would show nothing for two
    minutes and then everything at once.
    """
    reporter.detail("$ " + " ".join(str(c) for c in command))
    process = subprocess.Popen(
        [str(c) for c in command], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="replace")
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            reporter.detail(line)
            if on_line is not None:
                on_line(line)
            if reporter.cancelled():
                process.terminate()
                raise Cancelled()
        return process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def build(repo_root: Path, build_dir: Path, reporter: Reporter,
          jobs: int | None = None) -> Engine:
    """Configure and build the engine into build_dir."""
    build_dir.mkdir(parents=True, exist_ok=True)

    cmake = shutil.which("cmake")
    if not cmake:
        raise BuildError("CMake is not installed")

    reporter.step("Configuring the engine", str(build_dir))
    configure = [cmake, "-S", str(repo_root), "-B", str(build_dir),
                 *_generator(),
                 "-DCMAKE_BUILD_TYPE=Release",
                 "-DECWOLF_RENDERER_OPENGL=ON",
                 "-DECWOLF_RENDERER_SOFTWARE=ON"]
    if _stream(configure, repo_root, reporter) != 0:
        raise BuildError(
            "CMake could not configure the build. The last lines of the log "
            "above usually name the missing library.")

    # Two passes. gitinfo.h is regenerated after gitinfo.cpp compiles, so a
    # single pass embeds the previous commit's version string -- every
    # packaging script in this project builds twice for the same reason.
    total_passes = 2
    for pass_number in range(1, total_passes + 1):
        reporter.step(f"Compiling the engine (pass {pass_number} of {total_passes})")
        command = [cmake, "--build", str(build_dir)]
        if jobs:
            command += ["--parallel", str(jobs)]

        # Ninja and Make both print "[current/total]"-ish progress; turning that
        # into a fraction is what lets the plain progress bar move during the
        # longest step of the install.
        state = {"seen": 0.0}

        def on_line(line: str, _pass=pass_number) -> None:
            if line.startswith("[") and "/" in line[:12]:
                try:
                    current, total = line[1:line.index("]")].split("/")
                    part = int(current) / max(1, int(total))
                    state["seen"] = part
                    reporter.progress(((_pass - 1) + part) / total_passes)
                except (ValueError, IndexError):
                    pass

        if _stream(command, repo_root, reporter, on_line) != 0:
            raise BuildError(
                "The engine failed to compile. The compiler's own message is "
                "in the log above and in the installer log file.")

    executable = build_dir / EXE_NAME
    pk3 = build_dir / PK3_NAME
    if not executable.is_file():
        raise BuildError(f"the build finished but produced no {EXE_NAME}")
    if not pk3.is_file():
        raise BuildError(
            f"the build produced {EXE_NAME} but no {PK3_NAME}. The game data "
            "lives in the pk3; without it the engine cannot start.")
    reporter.progress(1.0)
    return Engine(executable, pk3, f"compiled in {build_dir}")
