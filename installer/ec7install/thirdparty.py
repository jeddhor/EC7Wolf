"""Fetching and building a dependency the machine does not have.

The rule everywhere this is used is the same: prefer what the system already
provides, and only build when there is nothing to prefer. A distribution's own
libsdl2-dev is better tested, better integrated and better patched than
anything this could produce in a cache directory, and using it costs nothing.
Building is what happens on the platforms with no package manager to ask --
Windows today, and whatever someone ports this to next.

Two build systems, because the dependencies use two: CMake for SDL, meson for
libepoxy. Both install into a prefix, so what comes back is always the same
shape -- an include directory and a library.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from .progress import Reporter


class BuildFailed(Exception):
    """A dependency could not be obtained. Says why, and what it costs."""


def download(url: str, target: Path, reporter: Reporter) -> Path:
    """Fetch a file, atomically. An interrupted download is not a file."""
    if target.is_file() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    reporter.detail(f"downloading {url}")
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=180) as response, \
                partial.open("wb") as out:
            while True:
                reporter.check_cancelled()
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
        partial.replace(target)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise BuildFailed(f"could not download {url}: {error}")
    return target


def _find_marker(root: Path, marker: str) -> Path | None:
    if (root / marker).is_file():
        return root
    for child in sorted(root.iterdir()) if root.is_dir() else []:
        if child.is_dir() and (child / marker).is_file():
            return child
    return None


def unpack(archive: Path, into: Path, reporter: Reporter, marker: str) -> Path:
    """Unpack, and return the directory that actually holds the source.

    `marker` is a file that must be in it -- meson.build, CMakeLists.txt --
    because release archives disagree about how deeply they nest and guessing
    from the archive's name is how that goes wrong.
    """
    into.mkdir(parents=True, exist_ok=True)
    existing = _find_marker(into, marker)
    if existing is not None:
        return existing

    reporter.detail(f"unpacking {archive.name}")
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(into)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(into)
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as error:
        archive.unlink(missing_ok=True)
        raise BuildFailed(
            f"{archive.name} could not be unpacked ({error}). It has been "
            "deleted, so running the installer again will fetch it afresh.")

    source = _find_marker(into, marker)
    if source is None:
        raise BuildFailed(f"{archive.name} was unpacked but has no {marker} "
                          "in it, so it cannot be built")
    return source


def _run(command: list[str], reporter: Reporter, what: str,
         environment: dict | None = None, timeout: int = 3600) -> None:
    reporter.detail("$ " + " ".join(command))
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, env=environment,
                                errors="replace")
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildFailed(f"{what} could not be run: {error}")
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip().splitlines()
        raise BuildFailed(f"{what} failed:\n  " + "\n  ".join(output[-12:]))


def cmake_build(source: Path, build: Path, prefix: Path, reporter: Reporter,
                arguments: list[str] | None = None,
                environment: dict | None = None,
                jobs: int | None = None) -> Path:
    """Configure, build and install a CMake project into a prefix."""
    cmake = shutil.which("cmake")
    if cmake is None:
        raise BuildFailed("CMake is needed to build this and is not installed")

    build.mkdir(parents=True, exist_ok=True)
    _run([cmake, "-S", str(source), "-B", str(build),
          f"-DCMAKE_INSTALL_PREFIX={prefix}",
          "-DCMAKE_BUILD_TYPE=Release", *(arguments or [])],
         reporter, "CMake", environment, timeout=1800)

    compile_command = [cmake, "--build", str(build), "--config", "Release"]
    if jobs:
        compile_command += ["--parallel", str(jobs)]
    _run(compile_command, reporter, "the build", environment)
    _run([cmake, "--install", str(build), "--config", "Release"],
         reporter, "the install step", environment, timeout=900)
    return prefix


def meson_tool(cache: Path, reporter: Reporter) -> list[str]:
    """A meson to build with, in a virtual environment of our own.

    Not installed into whatever Python is running the installer -- that may
    well be the system one, and an installer that adds packages to it has
    overstepped. It lives in the cache and goes away with it.
    """
    venv = cache / "buildtools"
    windows = os.name == "nt" or sys.platform.startswith("win")
    binaries = venv / ("Scripts" if windows else "bin")
    meson = binaries / ("meson.exe" if windows else "meson")

    if not meson.exists():
        reporter.detail("setting up a build environment for meson")
        python = binaries / ("python.exe" if windows else "python")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(venv)],
                           check=True, capture_output=True, text=True,
                           timeout=600)
            subprocess.run([str(python), "-m", "pip", "install",
                            "--disable-pip-version-check", "--quiet", "meson"],
                           check=True, capture_output=True, text=True,
                           timeout=1800)
        except (OSError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise BuildFailed("could not install meson, which this dependency "
                              f"is built with: {str(detail).strip()[:400]}")
    if not meson.exists():
        raise BuildFailed("meson was installed but is not where it should be")
    return [str(meson)]


def meson_build(source: Path, build: Path, prefix: Path, cache: Path,
                reporter: Reporter, arguments: list[str] | None = None,
                environment: dict | None = None,
                ninja: str | None = None) -> Path:
    """Configure, build and install a meson project into a prefix."""
    meson = meson_tool(cache, reporter)
    shutil.rmtree(build, ignore_errors=True)

    run_environment = dict(environment) if environment else None
    if run_environment is not None and ninja:
        # meson looks for ninja on the PATH, and the only one here may be the
        # copy inside Visual Studio.
        key = next((k for k in run_environment if k.upper() == "PATH"), "PATH")
        run_environment[key] = (str(Path(ninja).parent) + os.pathsep +
                                run_environment.get(key, ""))

    _run(meson + ["setup", str(build), str(source), "--buildtype=release",
                  f"--prefix={prefix}", *(arguments or [])],
         reporter, "meson", run_environment, timeout=1800)
    _run(meson + ["install", "-C", str(build)],
         reporter, "the build", run_environment)
    return prefix
