"""Finding an existing engine, or building one.

The installer prefers an engine the user already compiled: that is both faster
and more respectful of a developer's own tree. Only when there is none does it
configure and build, streaming every line of output to the reporter so a front
end can show the compile happening.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import epoxy, sdl
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

    def __init__(self, executable: Path, pk3: Path, source: str,
                 extra_files: list | None = None):
        self.executable = executable
        self.pk3 = pk3
        self.source = source
        # Files that have to travel with the engine for it to start -- on
        # Windows, the SDL DLLs it loads at run time.
        self.extra_files = list(extra_files or [])

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


def _cmake_generators(cmake: str) -> list[str]:
    """The generator names this CMake actually offers."""
    try:
        listing = subprocess.run([cmake, "--help"], capture_output=True,
                                 text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in listing.splitlines():
        # "* Visual Studio 17 2022        = Generates Visual Studio ..."
        if "=" not in line:
            continue
        name = line.split("=", 1)[0].strip().lstrip("*").strip()
        if name and not name.startswith("-"):
            names.append(name.replace(" [arch]", ""))
    return names


def _generator(cmake: str | None = None) -> list[str]:
    """Name the generator; never leave CMake to guess and then argue with it.

    Ninja wherever it exists: it is what the project builds with and the
    fastest of them. Otherwise, on Windows, the Visual Studio generator that
    matches the Visual Studio actually installed -- found by year, because that
    is how CMake names them.

    The alternative, letting CMake choose its own default, is what produced the
    bug this replaces: on a machine with Visual Studio 2026 and CMake 3.31 --
    whose newest Visual Studio generator is 2022, matching 17.x and not 18.x --
    CMake quietly fell back to NMake Makefiles, and then rejected the -A x64
    that had been added on the assumption it was building a solution.
    """
    if shutil.which("ninja") or shutil.which("ninja-build"):
        return ["-G", "Ninja"]
    if not is_windows() or cmake is None:
        return []

    from .deps import visual_studio_version
    version = visual_studio_version()
    if version is not None:
        for name in _cmake_generators(cmake):
            if name.startswith(f"Visual Studio {version} "):
                # -A x64: a Visual Studio generator builds 32-bit by default
                # even on a 64-bit machine.
                return ["-G", name, "-A", "x64"]

    # No usable solution generator. Inside a Developer Command Prompt the
    # compiler is on the PATH and NMake will do; outside one, nothing here can
    # build, and build() says so before running anything.
    if shutil.which("cl"):
        return ["-G", "NMake Makefiles"]
    return []


def developer_environment() -> dict | None:
    """The environment a Developer Command Prompt would have set up.

    Visual Studio's compiler is deliberately not on the ordinary PATH; the
    Developer Command Prompt exists to put it there, and VsDevCmd.bat is what
    it runs. Asking that script for its environment and using it for the build
    is what lets the installer compile on a machine where CMake is older than
    Visual Studio -- the alternative being to tell the user to go and find the
    right Start menu entry themselves, which is not what an installer is for.

    The trick is the standard one: run the batch file and then `set`, and read
    back what it changed.
    """
    from .deps import visual_studio_path
    installation = visual_studio_path()
    if not installation:
        return None
    batch = Path(installation) / "Common7" / "Tools" / "VsDevCmd.bat"
    if not batch.is_file():
        return None

    # Through a batch file rather than `cmd /c "call ... && set"`. cmd strips
    # the outer quotes from a command line that begins with one, which turns
    # the quoted path to VsDevCmd.bat into something it then reports as "not
    # recognized as an internal or external command". Writing the two lines to
    # a file sidesteps the whole of cmd's quoting rules.
    scratch = Path(tempfile.mkdtemp(prefix="ec7wolf-vsenv-"))
    script = scratch / "capture.bat"
    script.write_bytes(
        ("@echo off\r\n"
         f'call "{batch}" -arch=amd64 -host_arch=amd64 >nul\r\n'
         "set\r\n").encode("utf-8"))
    try:
        result = subprocess.run(["cmd", "/c", str(script)], capture_output=True,
                                text=True, timeout=300, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if result.returncode != 0:
        return None

    environment = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            environment[key] = value
    # PATH is the whole point; anything without it did not work.
    return environment if any(k.upper() == "PATH" for k in environment) else None


def _which_in(environment: dict, *names: str) -> str | None:
    """shutil.which, but against a PATH we were handed rather than our own."""
    path = next((v for k, v in environment.items() if k.upper() == "PATH"), "")
    extensions = [e.lower() for e in
                  environment.get("PATHEXT", ".EXE").split(os.pathsep) if e]
    wanted = {f"{n.lower()}{e}" for n in names for e in extensions}
    for directory in path.split(os.pathsep):
        if not directory:
            continue
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            if entry.lower() in wanted:
                return os.path.join(directory, entry)
    return None


def _windows_build_problem(cmake: str) -> str | None:
    """Why this Windows machine cannot build yet, if it cannot.

    Checked before CMake runs, because CMake's own answer to this arrives as
    "CMAKE_C_COMPILER not set, after EnableLanguage", which tells the reader
    nothing about what to do.
    """
    if not is_windows():
        return None
    if shutil.which("ninja") or shutil.which("ninja-build") or shutil.which("cl"):
        return None

    from .deps import visual_studio, visual_studio_path, visual_studio_version
    version = visual_studio_version()
    generators = [g for g in _cmake_generators(cmake) if g.startswith("Visual Studio")]
    if version is not None and any(
            g.startswith(f"Visual Studio {version} ") for g in generators):
        return None

    if visual_studio_path():
        # There is a Visual Studio to borrow an environment from, so this is
        # not a dead end; build() sets it up rather than reporting a problem.
        return None

    if visual_studio() and generators:
        # CMake lists its generators newest first, so the newest is the one to
        # name -- reading from the wrong end of that list is how this message
        # first claimed the ceiling was Visual Studio 2015.
        def major(name: str) -> int:
            parts = name.split()
            return int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        newest = max(generators, key=major)
        return (f"CMake does not know about your Visual Studio. The newest it "
                f"offers is \"{newest}\"; you have {visual_studio()}, which "
                f"is version {version}.\n\n"
                "Two ways forward, either is fine:\n"
                "  * Update CMake, which will then have a generator for it.\n"
                "  * Start this installer from a Developer PowerShell for "
                "Visual Studio, which puts the compiler and Ninja on the PATH "
                "-- then no solution generator is needed at all.")
    return ("No C++ compiler was found. Install Visual Studio with the "
            "\"Desktop development with C++\" workload, or start this "
            "installer from a Developer PowerShell if you already have it.")


def _stream(command: list[str], cwd: Path, reporter: Reporter,
            on_line=None, kept_lines: list | None = None,
            environment: dict | None = None) -> int:
    """Run a command, forwarding output line by line as it appears.

    Line-buffered on purpose: the point of the detail pane is watching the build
    move, and a pipe that only flushes at the end would show nothing for two
    minutes and then everything at once.
    """
    reporter.detail("$ " + " ".join(str(c) for c in command))
    tail = kept_lines if kept_lines is not None else []
    process = subprocess.Popen(
        [str(c) for c in command], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="replace", env=environment)
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            reporter.detail(line)
            # Kept so a failure can quote the tool rather than paraphrase it.
            tail.append(line)
            del tail[:-40]
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
        from .deps import remedy
        raise BuildError(f"CMake is needed to build the engine, and is not "
                         f"installed. {remedy('cmake')}")

    problem = _windows_build_problem(cmake)
    if problem:
        raise BuildError(problem)

    # SDL2: the system's where there is one, upstream's prebuilt packages on
    # Windows, and a source build anywhere else that has neither. The build
    # treats all three libraries as fatal, so something has to provide them.
    cache = build_dir.parent / ".ec7wolf-cache"
    sdl_directories = sdl.ensure(cache / "sdl", reporter, jobs=jobs)
    sdl_arguments = sdl.cmake_arguments(sdl_directories)
    for name, directory in sorted(sdl_directories.items()):
        reporter.detail(f"{name}: {directory}")

    environment = None
    generator = _generator(cmake)
    if is_windows() and not generator:
        reporter.step("Setting up the Visual Studio build environment")
        environment = developer_environment()
        if environment is None:
            raise BuildError(
                "no usable compiler could be set up. Visual Studio is "
                "installed but its build environment could not be read, and "
                "CMake has no generator for it. Starting this installer from "
                "a Developer PowerShell for Visual Studio works around it.")
        if _which_in(environment, "ninja"):
            generator = ["-G", "Ninja"]
            reporter.detail("using Ninja from Visual Studio")
        else:
            generator = ["-G", "NMake Makefiles"]
            reporter.detail("using NMake from Visual Studio")

    # A build directory remembers which generator made it and refuses to be
    # reconfigured with another -- so a first attempt that picked the wrong one
    # would poison every attempt after it, and the second failure reads like a
    # new problem rather than a leftover of the first.
    wanted = next((generator[i + 1] for i, a in enumerate(generator)
                   if a == "-G"), None)
    # Not "cache": that name belongs to the dependency cache directory a few
    # lines up, and shadowing it here pointed libepoxy's cache at a file.
    cmake_cache = build_dir / "CMakeCache.txt"
    if wanted and cmake_cache.is_file():
        previous = None
        for line in cmake_cache.read_text(errors="replace").splitlines():
            if line.startswith("CMAKE_GENERATOR:"):
                previous = line.split("=", 1)[-1].strip()
                break
        if previous and previous != wanted:
            reporter.detail(f"the last build here used {previous}; starting "
                            f"again for {wanted}")
            shutil.rmtree(build_dir, ignore_errors=True)
            build_dir.mkdir(parents=True, exist_ok=True)

    # libepoxy, for the OpenGL renderer: the system's where there is one, built
    # from source where there is not. Failure is not fatal -- the game builds
    # without the GL backend, it just renders in software -- so it is reported
    # and stepped over rather than raised.
    epoxy_arguments: list[str] = []
    epoxy_runtime: list[Path] = []
    try:
        built = epoxy.ensure(
            cache / "epoxy", reporter, environment,
            _which_in(environment, "ninja") if environment
            else shutil.which("ninja"))
        epoxy_arguments = epoxy.cmake_arguments(built)
        epoxy_runtime = epoxy.runtime_libraries(built)
    except epoxy.EpoxyError as error:
        reporter.warn(
            f"{error}\n\nThe game will be built with the software renderer "
            "instead, which works but is slower and lacks the OpenGL "
            "renderer's filtering and scaling.")

    reporter.step("Configuring the engine", str(build_dir))
    configure = [cmake, "-S", str(repo_root), "-B", str(build_dir),
                 *generator,
                 "-DCMAKE_BUILD_TYPE=Release",
                 "-DECWOLF_RENDERER_OPENGL=ON",
                 "-DECWOLF_RENDERER_SOFTWARE=ON",
                 *sdl_arguments, *epoxy_arguments]
    said: list[str] = []
    if _stream(configure, repo_root, reporter, kept_lines=said,
               environment=environment) != 0:
        # CMake's own words. Paraphrasing them cost an hour once: the message
        # said to look for a missing library when the actual complaint was that
        # the generator did not accept a platform argument.
        interesting = [line for line in said
                       if line.strip() and not line.startswith("-- ")]
        raise BuildError(
            "CMake could not configure the build.\n\nIt said:\n  "
            + "\n  ".join(interesting[-12:] or said[-12:]))

    # Two passes. gitinfo.h is regenerated after gitinfo.cpp compiles, so a
    # single pass embeds the previous commit's version string -- every
    # packaging script in this project builds twice for the same reason.
    total_passes = 2
    for pass_number in range(1, total_passes + 1):
        reporter.step(f"Compiling the engine (pass {pass_number} of {total_passes})")
        command = [cmake, "--build", str(build_dir)]
        if any(g.startswith("Visual Studio") for g in generator):
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

        if _stream(command, repo_root, reporter, on_line,
                   environment=environment) != 0:
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
        raise BuildError(
            f"the build reported success but produced no {exe_name()} in "
            f"{build_dir}. The compiler's own output is in the installer log; "
            "deleting that directory and building again is usually the fix.")
    if not pk3.is_file():
        raise BuildError(
            f"the build produced {exe_name()} but no {PK3_NAME}. The game data "
            "lives in the pk3; without it the engine cannot start.")
    # The DLLs: whatever the build already put beside the executable, plus
    # SDL's own, which CMake has no reason to copy anywhere. Without them the
    # installed game opens a dialog about a missing SDL2.dll instead of
    # starting.
    extra = []
    if is_windows():
        extra = sorted(executable.parent.glob("*.dll"))
        have = {dll.name.lower() for dll in extra}
        extra += [dll for dll in sdl.runtime_libraries(sdl_directories)
                  if dll.name.lower() not in have]
        have |= {dll.name.lower() for dll in extra}
        extra += [dll for dll in epoxy_runtime
                  if dll.name.lower() not in have]

    reporter.progress(1.0)
    return Engine(executable, pk3, f"compiled in {build_dir}", extra_files=extra)
