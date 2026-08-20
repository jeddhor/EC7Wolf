"""What the machine needs, what it has, and where to get the rest.

Two independent sets. Building the engine needs a toolchain; ripping the disc
needs almost nothing. They are reported separately because a user who already
has a compiled engine does not care about the first, and one who is installing
without a CD does not care about the second.

Every missing requirement carries a REMEDY -- the package to install, or the
page to download from, phrased for the platform and, on Linux, for the distro
family actually in use. "libsdl2-dev is missing" helps nobody; "sudo apt install
libsdl2-dev" is an instruction.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .identity import host_platform


class Requirement:
    def __init__(self, key: str, label: str, found: bool,
                 detail: str = "", remedy: str = "", optional: bool = False):
        self.key = key
        self.label = label
        self.found = found
        self.detail = detail
        self.remedy = remedy
        self.optional = optional

    @property
    def blocking(self) -> bool:
        return not self.found and not self.optional

    def __repr__(self) -> str:
        mark = "ok" if self.found else ("optional" if self.optional else "MISSING")
        return f"<{self.key} {mark}>"


class Report:
    def __init__(self, requirements: list[Requirement]):
        self.requirements = requirements

    @property
    def satisfied(self) -> bool:
        return not any(r.blocking for r in self.requirements)

    @property
    def missing(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.found]

    @property
    def blocking(self) -> list[Requirement]:
        return [r for r in self.requirements if r.blocking]

    def __iter__(self):
        return iter(self.requirements)


# ---------------------------------------------------------------------------
# Knowing which advice to give
# ---------------------------------------------------------------------------

def distro_family() -> str:
    """'debian', 'fedora', 'arch', 'suse', or 'linux' when it cannot tell."""
    try:
        fields = {}
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = value.strip().strip('"')
    except OSError:
        return "linux"

    ids = (fields.get("ID", "") + " " + fields.get("ID_LIKE", "")).lower().split()
    for family in ("debian", "ubuntu"):
        if family in ids:
            return "debian"
    for family in ("fedora", "rhel", "centos"):
        if family in ids:
            return "fedora"
    if "arch" in ids:
        return "arch"
    if "suse" in ids or "opensuse" in ids:
        return "suse"
    return "linux"


_PACKAGES = {
    # key: (debian, fedora, arch, suse)
    "cmake":    ("cmake", "cmake", "cmake", "cmake"),
    "compiler": ("build-essential", "gcc-c++ make", "base-devel", "gcc-c++ make"),
    "ninja":    ("ninja-build", "ninja-build", "ninja", "ninja"),
    "sdl2":     ("libsdl2-dev", "SDL2-devel", "sdl2", "libSDL2-devel"),
    "sdl2_mixer": ("libsdl2-mixer-dev", "SDL2_mixer-devel", "sdl2_mixer",
                   "libSDL2_mixer-devel"),
    "sdl2_net": ("libsdl2-net-dev", "SDL2_net-devel", "sdl2_net",
                 "libSDL2_net-devel"),
    "zlib":     ("zlib1g-dev", "zlib-devel", "zlib", "zlib-devel"),
    "jpeg":     ("libjpeg-dev", "libjpeg-turbo-devel", "libjpeg-turbo",
                 "libjpeg8-devel"),
    "bzip2":    ("libbz2-dev", "bzip2-devel", "bzip2", "libbz2-devel"),
    "gtk3":     ("libgtk-3-dev", "gtk3-devel", "gtk3", "gtk3-devel"),
    "ffmpeg":   ("ffmpeg", "ffmpeg", "ffmpeg", "ffmpeg"),
}

_INSTALL_COMMAND = {
    "debian": "sudo apt install",
    "fedora": "sudo dnf install",
    "arch":   "sudo pacman -S",
    "suse":   "sudo zypper install",
}


def linux_remedy(key: str) -> str:
    family = distro_family()
    names = _PACKAGES.get(key)
    if not names:
        return ""
    index = {"debian": 0, "fedora": 1, "arch": 2, "suse": 3}.get(family)
    if index is None:
        return f"install your distribution's development package for {key}"
    return f"{_INSTALL_COMMAND[family]} {names[index]}"


_WINDOWS_REMEDY = {
    "cmake": "winget install Kitware.CMake  --  or "
             "https://cmake.org/download/ (tick \"Add CMake to the system "
             "PATH\")",
    "compiler": "winget install Microsoft.VisualStudio.2022.BuildTools "
                "--override \"--add Microsoft.VisualStudio.Workload.VCTools "
                "--includeRecommended --quiet\"  --  or install Visual Studio "
                "from https://visualstudio.microsoft.com/downloads/ with the "
                "\"Desktop development with C++\" workload",
    "ninja": "winget install Ninja-build.Ninja  --  or it ships inside "
             "Visual Studio's C++ workload, which puts it on the PATH of a "
             "Developer Command Prompt",
    "sdl2": "Install the SDL2 development libraries with vcpkg "
            "(vcpkg install sdl2 sdl2-mixer sdl2-net zlib libjpeg-turbo bzip2) "
            "or download them from https://libsdl.org/",
    "ffmpeg": "winget install Gyan.FFmpeg  --  or "
              "https://ffmpeg.org/download.html, adding it to your PATH",
}


def remedy(key: str) -> str:
    host = host_platform()
    if host == "windows":
        return _WINDOWS_REMEDY.get(key, f"install {key}")
    if host == "macos":
        return f"brew install {key}"
    return linux_remedy(key)


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def _which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _version(executable: str, *args: str) -> str:
    try:
        out = subprocess.run([executable, *args], capture_output=True, text=True,
                             timeout=15)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return ""


def _pkg_config(name: str) -> bool:
    pkg = shutil.which("pkg-config")
    if not pkg:
        return False
    try:
        return subprocess.run([pkg, "--exists", name], timeout=15).returncode == 0
    except Exception:
        return False


def _have_header(header: str) -> bool:
    """Last resort where pkg-config knows nothing: look in the usual places."""
    roots = ["/usr/include", "/usr/local/include"]
    machine = platform.machine()
    roots.append(f"/usr/include/{machine}-linux-gnu")
    return any((Path(root) / header).exists() for root in roots)


def _library(key: str, label: str, pkg_name: str, header: str) -> Requirement:
    found = _pkg_config(pkg_name) or _have_header(header)
    return Requirement(key, label, found,
                       detail="found" if found else "",
                       remedy="" if found else remedy(key))


def visual_studio() -> str | None:
    """The newest Visual Studio with the C++ tools, via vswhere.

    cl.exe is not on the PATH outside a Developer Command Prompt, so looking
    for it finds nothing on a machine with a perfectly good Visual Studio --
    and telling that user to install the compiler they already have is worse
    than saying nothing. vswhere.exe is Microsoft's answer to this and lives at
    a fixed path on every machine with any VS 2017 or later.
    """
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(variable)
        if not base:
            continue
        vswhere = Path(base) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if not vswhere.is_file():
            continue
        try:
            found = subprocess.run(
                [str(vswhere), "-latest", "-products", "*", "-requires",
                 "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "displayName"],
                capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        name = found.stdout.strip().splitlines()
        if found.returncode == 0 and name:
            return name[0].strip()
    return None


def _windows_compiler() -> Requirement:
    """MSVC or MinGW -- either will build it, so either satisfies this."""
    studio = visual_studio()
    if studio:
        return Requirement("compiler", "C++ compiler", True, detail=studio)

    cl = _which("cl")
    if cl:
        return Requirement("compiler", "C++ compiler", True,
                           detail="MSVC (cl.exe on the PATH)")

    mingw = _which("g++", "clang++")
    if mingw:
        return Requirement("compiler", "C++ compiler", True,
                           detail=f"MinGW ({Path(mingw).name})")

    return Requirement("compiler", "C++ compiler", False,
                       remedy=remedy("compiler"))


def scan_build() -> Report:
    """What compiling the engine needs."""
    requirements: list[Requirement] = []

    cmake = _which("cmake")
    requirements.append(Requirement(
        "cmake", "CMake", cmake is not None,
        detail=_version(cmake, "--version") if cmake else "",
        remedy="" if cmake else remedy("cmake")))

    if host_platform() == "windows":
        requirements.append(_windows_compiler())
    else:
        compiler = _which("c++", "g++", "clang++")
        requirements.append(Requirement(
            "compiler", "C++ compiler", compiler is not None,
            detail=Path(compiler).name if compiler else "",
            remedy="" if compiler else remedy("compiler")))

    # A generator: Ninja is what the project builds with, but Make will do, so
    # a machine with only Make is not blocked -- it is just slower.
    ninja = _which("ninja", "ninja-build")
    make = _which("make", "nmake", "mingw32-make")
    requirements.append(Requirement(
        "ninja", "Ninja (recommended build tool)", ninja is not None,
        detail=_version(ninja, "--version") if ninja else "",
        remedy="" if ninja else remedy("ninja"),
        optional=make is not None))
    if not ninja and not make:
        requirements.append(Requirement(
            "make", "Make", False, remedy=remedy("compiler")))

    if host_platform() == "linux":
        requirements.append(_library("sdl2", "SDL2", "sdl2", "SDL2/SDL.h"))
        requirements.append(_library("sdl2_mixer", "SDL2_mixer", "SDL2_mixer",
                                     "SDL2/SDL_mixer.h"))
        requirements.append(_library("sdl2_net", "SDL2_net", "SDL2_net",
                                     "SDL2/SDL_net.h"))
        requirements.append(_library("zlib", "zlib", "zlib", "zlib.h"))
        requirements.append(_library("jpeg", "libjpeg", "libjpeg", "jpeglib.h"))
        requirements.append(_library("bzip2", "bzip2", "bzip2", "bzlib.h"))
        gtk = _pkg_config("gtk+-3.0")
        requirements.append(Requirement(
            "gtk3", "GTK3 (optional: native file dialogs)", gtk,
            remedy="" if gtk else remedy("gtk3"), optional=True))
    elif host_platform() == "windows":
        # There is no pkg-config to ask, and finding vcpkg's tree is guesswork;
        # CMake is the authority, so this is advisory rather than a probe.
        vcpkg = os.environ.get("VCPKG_ROOT") or _which("vcpkg")
        requirements.append(Requirement(
            "sdl2", "SDL2 development libraries", vcpkg is not None,
            detail="vcpkg found" if vcpkg else "",
            remedy="" if vcpkg else remedy("sdl2")))

    return Report(requirements)


def scan_rip(need_music: bool = True) -> Report:
    """What getting the game's content off the disc needs.

    Extracting the data files and the cinematics needs nothing but Python: the
    ISO9660 walk and the FLIC check are ours. Only the music needs help, because
    the tracks are raw CD audio that has to be encoded to something a modern
    machine will play.
    """
    requirements: list[Requirement] = []
    ffmpeg = _which("ffmpeg")
    requirements.append(Requirement(
        "ffmpeg", "FFmpeg (for the CD soundtrack)", ffmpeg is not None,
        detail=_version(ffmpeg, "-version").split(" Copyright")[0] if ffmpeg else "",
        remedy="" if ffmpeg else remedy("ffmpeg"),
        optional=not need_music))
    return Report(requirements)
