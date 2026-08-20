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

from .identity import exe_name, is_windows
from .progress import Cancelled, Reporter

# Resolved per call rather than at import: the gate forces the Windows
# branch through identity.host_platform(), and a constant fixed at import
# time would have been decided before it could.
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

    def version(self) -> str:
        """The version string baked into the binary, for Add/Remove Programs.

        Read out of the executable rather than asked for: the engine has no
        --version flag, and the string it prints on startup is the same one
        that is sitting in its data section.
        """
        import re
        try:
            blob = self.executable.read_bytes()
        except OSError:
            return ""
        described = re.search(rb"\d+\.\d+[a-z0-9.]*-\d+-g[0-9a-f]{6,}", blob)
        if described:
            return described.group().decode("ascii", "replace")
        plain = re.search(rb"\d+\.\d+\.\d+pre", blob)
        return plain.group().decode("ascii", "replace") if plain else ""


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
    # A Visual Studio generator is multi-config and puts its output in a
    # per-configuration subdirectory, so the same build tree that holds
    # ec7wolf on Linux holds Release\ec7wolf.exe on Windows.
    if is_windows():
        candidates += [directory / config
                       for directory in list(candidates)
                       for config in ("Release", "RelWithDebInfo")]

    for directory in candidates:
        executable = directory / exe_name()
        pk3 = directory / PK3_NAME
        if not (executable.is_file() and pk3.is_file()):
            continue
        if not os.access(executable, os.X_OK) and not is_windows():
            continue
        if pk3.stat().st_mtime < executable.stat().st_mtime - 1:
            continue
        return Engine(executable, pk3, f"already built in {directory}")
    return None


def _generator() -> list[str]:
    """Which CMake generator to ask for, if any.

    Ninja everywhere it exists, because it is what the project builds with and
    it is the fastest of the three. On Windows without Ninja, let CMake pick:
    it finds the newest Visual Studio itself, and naming a version here would
    mean guessing which one is installed and being wrong every few years.
    """
    if shutil.which("ninja") or shutil.which("ninja-build"):
        return ["-G", "Ninja"]
    return []


def _configure_extras() -> list[str]:
    """Arguments CMake needs on Windows and nowhere else.

    A Visual Studio generator defaults to a 32-bit build even on a 64-bit
    machine, and Release has to be named at build time rather than configure
    time -- neither is true of Ninja or Make, which is why this is separate.
    """
    if not is_windows():
        return []
    if shutil.which("ninja") or shutil.which("ninja-build"):
        return []
    return ["-A", "x64"]


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
                 *_generator(), *_configure_extras(),
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
        if is_windows() and not (shutil.which("ninja") or shutil.which("ninja-build")):
            # A Visual Studio generator is multi-config: CMAKE_BUILD_TYPE means
            # nothing to it, and without this it quietly builds Debug.
            command += ["--config", "Release"]
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

    executable, pk3 = build_dir / exe_name(), build_dir / PK3_NAME
    if not executable.is_file():
        # Same multi-config story as in find_existing: with a Visual Studio
        # generator the binary is one directory further down, and the pk3 may
        # be in either place depending on how the target was declared.
        for config in ("Release", "RelWithDebInfo"):
            if (build_dir / config / exe_name()).is_file():
                executable = build_dir / config / exe_name()
                if (build_dir / config / PK3_NAME).is_file():
                    pk3 = build_dir / config / PK3_NAME
                break
    if not executable.is_file():
        raise BuildError(f"the build finished but produced no {exe_name()}")
    if not pk3.is_file():
        raise BuildError(
            f"the build produced {exe_name()} but no {PK3_NAME}. The game data "
            "lives in the pk3; without it the engine cannot start.")
    reporter.progress(1.0)
    return Engine(executable, pk3, f"compiled in {build_dir}")
