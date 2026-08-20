"""libepoxy: the system's, or one built here.

Without it the build quietly drops the OpenGL backend and produces a
software-only game -- which runs, but is not the renderer this engine is
about. Every Linux distribution packages it, so there it is one apt-get away
and the installer should simply use it. Windows has no package to install and
upstream ships no prebuilt binaries, so the only way to have it is to build it,
and asking a player to do that by hand is asking them to give up.

Hence: use the system's if there is one, build it if there is not, and say
which. libepoxy builds with meson, which thirdparty.meson_tool puts in a
virtual environment inside the installer's cache rather than in anyone's
Python.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import thirdparty
from .progress import Reporter
from .thirdparty import BuildFailed

VERSION = "1.5.10"
URL = f"https://github.com/anholt/libepoxy/archive/refs/tags/{VERSION}.zip"

EpoxyError = BuildFailed


def system_available() -> bool:
    """Whether the machine already has libepoxy to link against."""
    from .deps import _have_header, _pkg_config
    if _pkg_config("epoxy"):
        return True
    # No pkg-config, or no .pc file: the header and the library are what the
    # engine's CMake actually looks for, so ask the same question it does.
    if not _have_header("epoxy/gl.h"):
        return False
    for directory in ("/usr/lib", "/usr/local/lib", "/usr/lib64",
                      "/usr/lib/x86_64-linux-gnu"):
        if list(Path(directory).glob("libepoxy.*")) if Path(directory).is_dir() else []:
            return True
    return False


def _built(prefix: Path) -> dict | None:
    """A previously built epoxy in this prefix, if it is complete."""
    include = prefix / "include"
    if not (include / "epoxy" / "gl.h").is_file():
        return None
    for pattern in ("epoxy.lib", "libepoxy.a", "libepoxy.dll.a", "libepoxy.so*",
                    "libepoxy.dylib"):
        for library in sorted((prefix / "lib").glob(pattern)):
            return {"include": include, "library": library,
                    "runtime": sorted(prefix.glob("bin/*.dll"))}
    return None


def ensure(cache: Path, reporter: Reporter, environment: dict | None = None,
           ninja: str | None = None) -> dict | None:
    """The system's libepoxy, or one built here. None means "use the system's"."""
    if system_available():
        reporter.detail("libepoxy: using the one already installed")
        return None

    cache.mkdir(parents=True, exist_ok=True)
    prefix = cache / f"epoxy-{VERSION}-prefix"
    existing = _built(prefix)
    if existing:
        reporter.detail(f"libepoxy: already built in {prefix}")
        return existing

    reporter.step("Building libepoxy", "for the OpenGL renderer")
    archive = thirdparty.download(URL, cache / f"libepoxy-{VERSION}.zip", reporter)
    source = thirdparty.unpack(archive, cache, reporter, "meson.build")
    thirdparty.meson_build(
        source, cache / f"libepoxy-{VERSION}-build", prefix, cache, reporter,
        arguments=["--default-library=shared", "-Dtests=false"],
        environment=environment, ninja=ninja)

    built = _built(prefix)
    if built is None:
        raise BuildFailed(
            f"libepoxy built but left nothing usable in {prefix}. The OpenGL "
            "backend cannot be compiled without it; the game will still build "
            "with the software renderer.")
    reporter.detail(f"libepoxy: {built['library']}")
    return built


def cmake_arguments(built: dict | None) -> list[str]:
    if not built:
        return []
    return [f"-DEPOXY_INCLUDE_DIR={built['include']}",
            f"-DEPOXY_LIBRARY={built['library']}"]


def runtime_libraries(built: dict | None) -> list[Path]:
    return list(built["runtime"]) if built else []
