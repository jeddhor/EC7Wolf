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
from . import proc
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
        # The tag segment may itself contain dashes: EC7Wolf tags releases
        # v1.0-beta188, so the description is 1.0-beta188-11-gHASH. A class
        # without the dash matched upstream's 1.5pre-45-gHASH and nothing this
        # project has ever built, which is why every EC7Wolf install has been
        # registering itself with a blank version.
        described = re.search(
            rb"\d+\.\d+[-.A-Za-z0-9]*-\d+-g[0-9a-f]{6,}(?:-m)?", blob)
        if described:
            return described.group().decode("ascii", "replace")
        plain = re.search(rb"\d+\.\d+\.\d+pre", blob)
        return plain.group().decode("ascii", "replace") if plain else ""


def tree_version(repo_root: Path) -> str:
    """What `git describe` calls the tree we would build, if it is a checkout.

    The same command UpdateRevision.cmake bakes into the binary, so this and
    Engine.version() are directly comparable. Empty when there is no git, no
    repository, or no tag to describe from -- all of which are ordinary for an
    installer that downloaded a source tarball, and none of which are grounds
    for refusing a perfectly good engine.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(repo_root), "describe", "--tags", "--first-parent"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    # The binary carries the description without the tag's leading "v".
    return done.stdout.strip().lstrip("v")


def find_existing(repo_root: Path, extra: list[Path] | None = None,
                  reporter: Reporter | None = None) -> Engine | None:
    """An already-built engine, if there is one.

    Both files have to be present and the pk3 has to be at least as new as the
    executable. A stale pk3 beside a fresh binary is the single most common way
    to get a build that runs but behaves like an older one -- the project's own
    notes record losing time to exactly that -- so it is treated as "no usable
    engine" rather than quietly shipped.

    The same reasoning applies to the build tree as a whole, and it took longer
    to notice. This searches four directories, one of which is an untracked
    "release" folder that a developer may have left behind months ago; whatever
    it found first was installed, silently, with the report saying no more than
    "already built in ...". A six-week-old engine shipped that way for weeks,
    and the install test that was supposed to catch it was testing that same
    old binary. So an engine that says it was built from a different revision
    than the tree being installed is not used. The dirty marker is ignored --
    uncommitted edits are normal while developing and are not on their own a
    reason to spend ten minutes rebuilding.
    """
    wanted = tree_version(repo_root)
    # An engine the caller named is used as given -- --engine DIR is someone
    # saying which build they mean, and second-guessing that is not this
    # function's business. Only the directories guessed below are checked.
    named: list[Path] = list(extra or [])
    candidates: list[Path] = list(named)
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
        # One second of slack was not enough to describe one build. CMake
        # packages the pk3 and then links the executable, so in a perfectly
        # consistent build the pk3 is always the older of the two -- by 1.6s in
        # this project's own release build, which this rule then threw out. It
        # threw out every real build, fell through to a leftover directory, and
        # installed a six-week-old engine instead. What it is meant to catch is
        # a pk3 from an entirely different build session, which is minutes to
        # days old, so five minutes separates the two cases with room to spare.
        if pk3.stat().st_mtime < executable.stat().st_mtime - 300:
            continue
        # Whatever else is in that folder comes too. A downloaded release, or
        # an unpacked -full archive, has SDL2.dll and libepoxy-0.dll sitting
        # beside the executable, and an install that took only the .exe and the
        # .pk3 produced a game that could not start -- which is exactly what
        # happened to the first person to install from a release zip.
        extra = sorted(directory.glob("*.dll")) if is_windows() else []
        engine = Engine(executable, pk3, f"already built in {directory}",
                        extra_files=extra)

        built = engine.version()
        guessed = directory not in named
        if guessed and wanted and built and built.removesuffix("-m") != wanted:
            if reporter is not None:
                reporter.detail(f"engine: ignoring {directory} -- it was built "
                                f"from {built}, and this is {wanted}")
            continue

        # Say which engine is being reused, not just where it came from. The
        # version is the whole point of the check above, and a log that records
        # it turns "why does the install behave like an old build" into one
        # readable line.
        if built:
            engine.source = f"already built in {directory} ({built})"
        return engine
    return None


def _cmake_version(cmake: str) -> tuple:
    """The version of this CMake, as a tuple, or () if it will not say."""
    try:
        text = subprocess.run([cmake, "--version"], capture_output=True,
                              text=True, timeout=60, **proc.quiet()).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    for word in text.split():
        if word[:1].isdigit() and "." in word:
            try:
                return tuple(int(part) for part in word.split(".")[:3])
            except ValueError:
                return ()
    return ()


def _policy_arguments(cmake: str, using_fetched_sdl: bool) -> list[str]:
    """Let CMake 4 read the config files upstream's SDL packages ship.

    sdl2_mixer-config.cmake and sdl2_net-config.cmake declare a
    cmake_minimum_required below 3.5. CMake 3.x calls that deprecated and
    carries on; CMake 4 removed the compatibility and makes it a hard error, so
    the same SDL packages that build fine on a developer's machine fail on a CI
    runner with a newer CMake. This is CMake's own escape hatch for exactly
    that, and it is applied only when we are the ones who supplied those files.
    """
    if not using_fetched_sdl:
        return []
    if _cmake_version(cmake) < (4, 0):
        return []
    return ["-DCMAKE_POLICY_VERSION_MINIMUM=3.5"]


def _cmake_generators(cmake: str) -> list[str]:
    """The generator names this CMake actually offers."""
    try:
        listing = subprocess.run([cmake, "--help"], capture_output=True,
                                 text=True, timeout=60, **proc.quiet()).stdout
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

    Off Windows this is simply Ninja where it exists. On Windows the order
    matters, and getting it wrong is not obvious:

      1. cl.exe already on the PATH -- a Developer Command Prompt. Ninja, and
         it will use MSVC because that is what is there.
      2. A Visual Studio generator matching the Visual Studio installed. It
         locates its own toolchain, so it needs no environment set up.
      3. Nothing else here; build() borrows Visual Studio's environment and
         comes back.

    What this must NOT do is reach for Ninja merely because ninja is on the
    PATH. A GitHub windows-latest runner has Ninja *and* MinGW at
    C:/mingw64,
    so "-G Ninja" with no toolchain named let CMake find gcc and build the
    release with MinGW -- linked against MSVC import libraries, warning about a
    missing _wmain entry symbol, and needing libgcc_s_seh-1.dll and
    libstdc++-6.dll that were never shipped. It ran on nobody's machine.
    """
    windows = is_windows()
    if not windows:
        if shutil.which("ninja") or shutil.which("ninja-build"):
            return ["-G", "Ninja"]
        return []

    if shutil.which("cl") and (shutil.which("ninja") or shutil.which("ninja-build")):
        return ["-G", "Ninja"]

    if cmake is not None:
        from .deps import visual_studio_version
        version = visual_studio_version()
        if version is not None:
            for name in _cmake_generators(cmake):
                if name.startswith(f"Visual Studio {version} "):
                    # -A x64: a Visual Studio generator builds 32-bit by
                    # default even on a 64-bit machine.
                    return ["-G", name, "-A", "x64"]

    if shutil.which("cl"):
        return ["-G", "NMake Makefiles"]

    from .deps import visual_studio_path
    if visual_studio_path():
        # build() will set the environment up and choose again with cl.exe on
        # the PATH; saying Ninja now would pick MinGW instead.
        return []

    # No Visual Studio anywhere. Whatever compiler is here will have to do --
    # MinGW, most likely -- and its runtime libraries are collected below so
    # the result can actually be run.
    if shutil.which("ninja") or shutil.which("ninja-build"):
        return ["-G", "Ninja"]
    return []


def _mingw_runtime(build_dir: Path) -> list[Path]:
    """The GCC runtime DLLs, when the build used GCC.

    A MinGW-built binary needs these beside it and they are not part of
    Windows, so an install without them opens a dialog about
    libgcc_s_seh-1.dll instead of a game. MSVC builds need nothing here: their
    runtime is the Universal CRT, which Windows has.

    Which compiler was used is read out of CMakeCache.txt rather than guessed,
    because by this point the build is over and the cache is the record of it.
    """
    cache = build_dir / "CMakeCache.txt"
    compiler = None
    try:
        for line in cache.read_text(errors="replace").splitlines():
            if line.startswith("CMAKE_CXX_COMPILER:"):
                compiler = Path(line.split("=", 1)[-1].strip())
                break
    except OSError:
        return []
    if compiler is None or not compiler.parent.is_dir():
        return []
    if "gcc" not in compiler.name.lower() and "++" not in compiler.name.lower():
        return []
    if shutil.which("cl") and "mingw" not in str(compiler).lower():
        return []

    wanted = ("libgcc_s_seh-1.dll", "libgcc_s_dw2-1.dll", "libstdc++-6.dll",
              "libwinpthread-1.dll")
    found = [compiler.parent / name for name in wanted
             if (compiler.parent / name).is_file()]
    return found


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
                                text=True, timeout=300, errors="replace",
                                **proc.quiet())
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
        text=True, bufsize=1, errors="replace", env=environment,
        **proc.quiet())
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
    # Resolved here so every path derived from them below is absolute: the
    # dependency caches hang off build_dir, and meson will not take a relative
    # prefix.
    repo_root, build_dir = Path(repo_root).resolve(), Path(build_dir).resolve()
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
                 *sdl_arguments, *epoxy_arguments,
                 *_policy_arguments(cmake, bool(sdl_arguments))]
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
        extra += _mingw_runtime(build_dir)
        have = {dll.name.lower() for dll in extra}
        extra += [dll for dll in sdl.runtime_libraries(sdl_directories)
                  if dll.name.lower() not in have]
        have |= {dll.name.lower() for dll in extra}
        extra += [dll for dll in epoxy_runtime
                  if dll.name.lower() not in have]

    reporter.progress(1.0)
    return Engine(executable, pk3, f"compiled in {build_dir}", extra_files=extra)
