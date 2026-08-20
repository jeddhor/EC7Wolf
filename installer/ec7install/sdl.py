"""The SDL2 development libraries: the system's, or ones obtained here.

ECWolf's build treats all three of SDL2, SDL2_mixer and SDL2_net as fatal if
missing, so a machine without them cannot build at all. Three ways to have
them, in order of preference:

  the system's    Every Linux distribution packages these, and a distribution's
                  build beats anything assembled in a cache directory. If they
                  are there, nothing below happens.
  prebuilt        On Windows, upstream ships official VC development packages.
                  They are correct, they are quick, and building the same thing
                  from source would take minutes to arrive at a worse copy.
  from source     Anywhere with neither -- which is where a port to something
                  unusual lands. Slow, but it is the difference between "you
                  cannot build this" and "this takes a while the first time".

Pinned versions, deliberately: a build that works the same way twice matters
more than the newest release of anything. An explicitly set SDL2_DIR (or
SDL2_mixer_DIR, or SDL2_net_DIR) always wins, for whoever wants their own.
"""

from __future__ import annotations

import os
import urllib.request
import zipfile
from pathlib import Path

from . import thirdparty
from .identity import is_windows
from .progress import Reporter

# name -> (version, config file to look for, download URL)
PACKAGES = {
    "SDL2": (
        "2.32.10", "sdl2-config.cmake",
        "https://github.com/libsdl-org/SDL/releases/download/"
        "release-2.32.10/SDL2-devel-2.32.10-VC.zip"),
    "SDL2_mixer": (
        "2.8.1", "sdl2_mixer-config.cmake",
        "https://github.com/libsdl-org/SDL_mixer/releases/download/"
        "release-2.8.1/SDL2_mixer-devel-2.8.1-VC.zip"),
    "SDL2_net": (
        "2.2.0", "sdl2_net-config.cmake",
        "https://github.com/libsdl-org/SDL_net/releases/download/"
        "release-2.2.0/SDL2_net-devel-2.2.0-VC.zip"),
}


# name -> (source archive URL, the CMake option that turns off its tests)
SOURCES = {
    "SDL2": ("https://github.com/libsdl-org/SDL/releases/download/"
             "release-2.32.10/SDL2-2.32.10.tar.gz", "SDL_TEST"),
    "SDL2_mixer": ("https://github.com/libsdl-org/SDL_mixer/releases/download/"
                   "release-2.8.1/SDL2_mixer-2.8.1.tar.gz", "SDL2MIXER_SAMPLES"),
    "SDL2_net": ("https://github.com/libsdl-org/SDL_net/releases/download/"
                 "release-2.2.0/SDL2_net-2.2.0.tar.gz", "SDL2NET_SAMPLES"),
}

SDLError = thirdparty.BuildFailed


def system_available() -> bool:
    """Whether the machine already has all three to link against."""
    from .deps import _have_header, _pkg_config
    if all(_pkg_config(name) for name in ("sdl2", "SDL2_mixer", "SDL2_net")):
        return True
    return all(_have_header(header) for header in
               ("SDL2/SDL.h", "SDL2/SDL_mixer.h", "SDL2/SDL_net.h"))


def _config_directory(root: Path, config: str) -> Path | None:
    """The directory holding a package's -config.cmake, wherever it landed."""
    if not root.is_dir():
        return None
    direct = root / "cmake" / config
    if direct.is_file():
        return direct.parent
    for found in root.rglob(config):
        return found.parent
    return None


def locate(cache: Path) -> dict[str, Path]:
    """What is already available, without downloading anything."""
    found: dict[str, Path] = {}
    for name, (version, config, _url) in PACKAGES.items():
        # Someone else's choice beats ours.
        override = os.environ.get(f"{name}_DIR")
        if override and (Path(override) / config).is_file():
            found[name] = Path(override)
            continue
        # Either route leaves something to find: a downloaded package under
        # its own directory, or a source build under the shared prefix.
        for root in (cache / f"{name}-{version}", cache / "sdl-prefix"):
            directory = _config_directory(root, config)
            if directory is not None:
                found[name] = directory
                break
    return found


def ensure(cache: Path, reporter: Reporter,
           environment: dict | None = None,
           jobs: int | None = None) -> dict[str, Path]:
    """Everything the build needs. An empty result means "use the system's"."""
    if system_available():
        reporter.detail("SDL2: using the libraries already installed")
        return {}

    cache.mkdir(parents=True, exist_ok=True)
    found = locate(cache)
    missing = [name for name in PACKAGES if name not in found]
    if not missing:
        return found

    if is_windows():
        return _fetch_prebuilt(cache, reporter, found, missing)
    return _build_from_source(cache, reporter, found, missing, environment, jobs)


def _fetch_prebuilt(cache: Path, reporter: Reporter, found: dict,
                    missing: list) -> dict[str, Path]:
    """Upstream's official VC development packages."""
    reporter.step("Fetching the SDL2 development libraries", ", ".join(missing))
    for index, name in enumerate(missing):
        reporter.check_cancelled()
        version, config, url = PACKAGES[name]
        archive = thirdparty.download(
            url, cache / f"{name}-devel-{version}-VC.zip", reporter)
        target = cache / f"{name}-{version}"
        thirdparty.unpack(archive, target, reporter, f"cmake/{config}")

        directory = _config_directory(target, config)
        if directory is None:
            raise SDLError(
                f"{name} was downloaded but {config} is not in it, so the "
                "build would not find it. This usually means the release "
                "layout changed upstream.")
        found[name] = directory
        reporter.progress((index + 1) / len(missing))
    return found


def _build_from_source(cache: Path, reporter: Reporter, found: dict,
                       missing: list, environment: dict | None,
                       jobs: int | None) -> dict[str, Path]:
    """The last resort, for a platform with neither packages nor binaries.

    Each one installs into its own prefix and is then found the same way a
    downloaded package would be, so nothing downstream can tell the difference.
    SDL2 has to be built before the other two, which look for it.
    """
    reporter.step("Building the SDL2 libraries from source", ", ".join(missing))
    prefix = cache / "sdl-prefix"

    for index, name in enumerate(n for n in PACKAGES if n in missing):
        reporter.check_cancelled()
        version, config, _vc_url = PACKAGES[name]
        url, tests_option = SOURCES[name]
        archive = thirdparty.download(url, cache / Path(url).name, reporter)
        source = thirdparty.unpack(archive, cache / f"{name}-src-{version}",
                                   reporter, "CMakeLists.txt")
        thirdparty.cmake_build(
            source, cache / f"{name}-build-{version}", prefix, reporter,
            arguments=[f"-D{tests_option}=OFF", "-DBUILD_SHARED_LIBS=ON",
                       f"-DCMAKE_PREFIX_PATH={prefix}"],
            environment=environment, jobs=jobs)

        directory = _config_directory(prefix, config)
        if directory is None:
            raise SDLError(
                f"{name} was built but {config} is not in {prefix}, so the "
                "engine's build would not find it.")
        found[name] = directory
        reporter.progress((index + 1) / len(missing))
    return found


def cmake_arguments(found: dict[str, Path]) -> list[str]:
    """Where each package lives, in the form CMake's find_package wants."""
    return [f"-D{name}_DIR={directory}" for name, directory in sorted(found.items())]


def runtime_libraries(found: dict[str, Path]) -> list[Path]:
    """The DLLs the built game needs beside it to start at all.

    A Windows build links against import libraries and loads the real ones at
    run time, so an install with the exe and no DLLs is an install that opens a
    dialog about a missing SDL2.dll instead of a game.
    """
    libraries: list[Path] = []
    for directory in found.values():
        # cmake/ sits beside lib/x64/, which is where the DLLs are.
        for candidate in (directory.parent / "lib" / "x64",
                          directory.parent.parent / "lib" / "x64"):
            if candidate.is_dir():
                libraries += sorted(candidate.glob("*.dll"))
                break
    return libraries
