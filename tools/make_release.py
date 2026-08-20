#!/usr/bin/env python3
"""Build and package an EC7Wolf release.

Two subcommands, both meant to be driven by .github/workflows/release.yml but
runnable by hand:

    make_release.py engine  --into staging/EC7Wolf-linux-x64
    make_release.py package --engine staging/... --out dist

The engine is built through the installer's own build module rather than a
separate CMake invocation written for CI. That is deliberate: it means the
released binaries are produced by exactly the code that builds one on a user's
machine, so the two cannot drift apart, and every release exercises the
dependency fetching -- SDL2 and libepoxy -- that a person would otherwise be
the first to try.

Nothing here touches the game's own data. A release carries the engine and the
installer; the player brings their Corridor 7 CD.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "installer"))
sys.path.insert(0, str(HERE))

# What a binaries-only artifact holds beside the engine.
DOCUMENTS = ("README.md", "docs/license-gpl.txt", "docs/corridor7.md")


def version() -> str:
    """The product version, computed the way the build computes it."""
    anchor = None
    for line in (REPO / "src" / "versiondefs.cmake").read_text().splitlines():
        if line.startswith("set(EC7WOLF_BETA_ANCHOR"):
            anchor = line.split('"')[1]
    if anchor:
        try:
            count = subprocess.run(
                ["git", "rev-list", "--count", f"{anchor}..HEAD"],
                cwd=REPO, capture_output=True, text=True, timeout=60)
            if count.returncode == 0 and count.stdout.strip():
                return f"1.0-beta{count.stdout.strip()}"
        except (OSError, subprocess.SubprocessError):
            pass
    for line in (REPO / "src" / "versiondefs.cmake").read_text().splitlines():
        if line.startswith("set(EC7WOLF_BETA_FALLBACK"):
            return "1.0-beta" + line.split()[-1].rstrip(")")
    return "1.0-beta0"


def platform_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    architecture = {"amd64": "x64", "x86_64": "x64",
                    "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"{system}-{architecture}"


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def build_engine(into: Path, jobs: int | None,
                 allow_software: bool = False) -> Path:
    from ec7install import build, install
    from ec7install.progress import ConsoleReporter

    reporter = ConsoleReporter(verbose=True)
    # Beside the staging directory, not in the source tree: a release build
    # should leave nothing behind in the checkout it came from.
    engine = build.build(REPO, into.parent / "build", reporter, jobs)

    into.mkdir(parents=True, exist_ok=True)
    shutil.copy2(engine.executable, into / engine.executable.name)
    shutil.copy2(engine.pk3, into / engine.pk3.name)
    for extra in engine.extra_files:
        if Path(extra).is_file():
            shutil.copy2(extra, into / Path(extra).name)
    if not sys.platform.startswith("win"):
        (into / engine.executable.name).chmod(0o755)

    install.write_launcher(into)
    for document in DOCUMENTS:
        source = REPO / document
        if source.is_file():
            shutil.copy2(source, into / Path(document).name)

    print(f"\nstaged {into}:")
    for item in sorted(into.iterdir()):
        print(f"  {item.name}  {item.stat().st_size // 1024} KB")

    if not allow_software:
        check_opengl(into / engine.executable.name)
    check_dependencies(into / engine.executable.name, into)
    return into


# DLLs Windows itself provides. Everything else has to be in the folder.
SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "comctl32.dll", "comdlg32.dll", "winmm.dll",
    "ws2_32.dll", "wsock32.dll", "imm32.dll", "version.dll", "setupapi.dll",
    "shlwapi.dll", "opengl32.dll", "dwmapi.dll", "uxtheme.dll", "msvcrt.dll",
    "rpcrt4.dll", "crypt32.dll", "bcrypt.dll", "iphlpapi.dll", "dbghelp.dll",
    "psapi.dll", "userenv.dll", "secur32.dll", "hid.dll", "cfgmgr32.dll",
    "msimg32.dll", "gdiplus.dll", "wintrust.dll", "ntdll.dll",
}


def imported_dlls(executable: Path) -> list[str]:
    """The DLLs a PE binary imports, read out of its import table.

    Parsed rather than grepped: the file is full of strings that look like DLL
    names and are not imports, and the question here is specifically what the
    loader will go looking for.
    """
    import struct
    blob = executable.read_bytes()
    if blob[:2] != b"MZ":
        return []                     # not a PE; nothing to check
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[pe:pe + 4] != b"PE\0\0":
        return []
    sections = struct.unpack_from("<H", blob, pe + 6)[0]
    optional_size = struct.unpack_from("<H", blob, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", blob, optional)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    import_rva, _size = struct.unpack_from("<II", blob, directories + 8)
    if not import_rva:
        return []

    table = []
    section_start = optional + optional_size
    for index in range(sections):
        entry = section_start + index * 40
        virtual = struct.unpack_from("<I", blob, entry + 12)[0]
        raw_size = struct.unpack_from("<I", blob, entry + 16)[0]
        raw_ptr = struct.unpack_from("<I", blob, entry + 20)[0]
        table.append((virtual, raw_size, raw_ptr))

    def offset(rva: int) -> int | None:
        for virtual, raw_size, raw_ptr in table:
            if virtual <= rva < virtual + raw_size:
                return raw_ptr + (rva - virtual)
        return None

    names, cursor = [], offset(import_rva)
    if cursor is None:
        return []
    while True:
        descriptor = blob[cursor:cursor + 20]
        if len(descriptor) < 20 or descriptor == b"\0" * 20:
            break
        name_rva = struct.unpack_from("<I", descriptor, 12)[0]
        at = offset(name_rva)
        if at is not None:
            end = blob.index(b"\0", at)
            names.append(blob[at:end].decode("ascii", "replace"))
        cursor += 20
    return names


def check_dependencies(executable: Path, folder: Path) -> None:
    """Every DLL the binary needs must be here, or be part of Windows.

    beta118 and beta119 shipped a Windows build that wanted
    libgcc_s_seh-1.dll and libstdc++-6.dll -- the MinGW runtime, which is not
    part of Windows and was not in the archive. The binary looked fine, the
    archive looked fine, and the first person to run it got a stack of dialogs.
    Nothing had ever asked the binary what it needed.
    """
    needed = imported_dlls(executable)
    if not needed:
        return
    present = {item.name.lower() for item in folder.iterdir()}
    missing = [name for name in needed
               if name.lower() not in SYSTEM_DLLS
               and not name.lower().startswith("api-ms-win-")
               and not name.lower().startswith("ext-ms-win-")
               and name.lower() not in present]
    if not missing:
        print(f"dependencies:   all {len(needed)} imports resolve here or in Windows")
        return
    raise SystemExit(
        f"\n{executable.name} needs DLLs that are not in {folder} and are not "
        "part of Windows:\n  " + "\n  ".join(sorted(set(missing))) +
        "\n\nIt would fail to start on any machine that does not happen to "
        "have them. Either ship them beside it or build against something "
        "else.")


def check_opengl(executable: Path) -> None:
    """Refuse to release an engine built without its OpenGL backend.

    build() treats a missing libepoxy as a warning and carries on with the
    software renderer, which is right on someone's own machine -- a slower game
    beats no game. It is wrong for a release: the binary looks identical, says
    nothing, and quietly lacks the renderer this engine is about. beta116 and
    beta118 shipped that way, because meson had refused a relative --prefix and
    the warning scrolled past in a four-minute log.

    glCreateShader is epoxy's own symbol, and it is in the binary only if the
    GL sources were compiled and linked.
    """
    try:
        blob = executable.read_bytes()
    except OSError as error:
        raise SystemExit(f"cannot read {executable}: {error}")

    if b"glCreateShader" in blob:
        print("\nOpenGL backend: present")
        return
    raise SystemExit(
        f"\n{executable.name} was built WITHOUT the OpenGL backend.\n\n"
        "libepoxy is missing or failed to build -- look for 'Building "
        "libepoxy' in the log above. A release binary that renders in software "
        "is not one to publish, so this is a failure rather than a warning.\n"
        "Pass --allow-software to make one deliberately.")


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

INSTALL_TEXT = {
    "binaries": """\
EC7Wolf {version} -- {platform}

This folder holds the game engine. It does NOT hold Corridor 7 itself; you need
your own copy of the game.

  1. Copy these files from your Corridor 7 CD or installation into this folder:

       CORR7CD.EXE   MAPTEMP.CO7   GFXTILES.CO7  VGADICT.CO7
       VGAHEAD.CO7   VGAGRAPH.CO7  AUDIOHED.CO7  AUDIOT.CO7
       AUDIOMUS.CO7  (optional, but it holds most of the game's sounds)

  2. Run {launcher}

That is all. The CD soundtrack and the cinematics are not set up this way -- if
you want those, use the installer instead: see the -full download, or
EC7Wolf-Setup.exe on Windows.

Full instructions: https://github.com/jeddhor/EC7Wolf#installing-and-running
""",
    "full": """\
EC7Wolf {version} -- {platform}, with the installer

Two ways to use this folder.

THE EASY WAY -- run the installer, and let it do everything:

    {installer_line}

  It takes the game's data, the CD soundtrack and the cinematics off your
  Corridor 7 CD (or a BIN/CUE image of it), puts them together with the engine
  in a folder you choose, and adds a menu entry. It never needs administrator
  rights.

BY HAND -- if you would rather not:

  Copy these files from your Corridor 7 CD into this folder, then run
  {launcher}:

       CORR7CD.EXE   MAPTEMP.CO7   GFXTILES.CO7  VGADICT.CO7
       VGAHEAD.CO7   VGAGRAPH.CO7  AUDIOHED.CO7  AUDIOT.CO7

  Doing it this way gets you the game but not the CD music or the cinematics.

You need your own copy of Corridor 7: Alien Invasion. Nothing here contains it.

Full instructions: https://github.com/jeddhor/EC7Wolf#installing-and-running
""",
    "installer": """\
EC7Wolf {version} -- the installer, on its own

This is the installer and nothing else: no engine, no game. Run it and it will
download the engine's source, build it, and take the game's data, soundtrack
and cinematics off your Corridor 7 CD.

  ON WINDOWS: you probably want EC7Wolf-Setup.exe from the same release page
  instead. It is one self-contained file and needs nothing installed. This zip
  is the Python version, and needs Python and PySide6 set up first.

  ON LINUX AND MACOS:

      python3 -m pip install --user PySide6      # once
      ./installer/ec7wolf-setup                  # the window
      ./installer/ec7wolf-install --help         # or the terminal version,
                                                 # which needs no PySide6

You need your own copy of Corridor 7: Alien Invasion. Nothing here contains it.

Full instructions: https://github.com/jeddhor/EC7Wolf#installing-and-running
""",
}


def _install_text(kind: str, tag: str, release: str) -> str:
    windows = tag.startswith("windows")
    return INSTALL_TEXT[kind].format(
        version=release,
        platform={"windows": "Windows", "linux": "Linux", "macos": "macOS"}.get(
            tag.split("-")[0], tag),
        launcher="EC7Wolf.cmd" if windows else "./run-ec7wolf.sh",
        installer_line=("EC7Wolf-Setup.exe" if windows
                        else "./installer/ec7wolf-setup     (or ec7wolf-install "
                             "for a terminal)"),
    )


def _add_text(archive, name: str, text: str) -> None:
    """Write a generated file straight into the archive."""
    data = text.replace("\n", "\r\n").encode() if isinstance(archive, zipfile.ZipFile) \
        else text.encode()
    if isinstance(archive, zipfile.ZipFile):
        archive.writestr(name, data)
    else:
        import io
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(data))


def _add_tree(archive, root: Path, base: str, skip_git: bool = True) -> None:
    for path in sorted(root.rglob("*")):
        if skip_git and any(part in (".git", "__pycache__") for part in path.parts):
            continue
        if path.is_file():
            arcname = f"{base}/{path.relative_to(root)}"
            if isinstance(archive, zipfile.ZipFile):
                archive.write(path, arcname)
            else:
                archive.add(path, arcname)


def _make(out: Path, name: str, windows: bool) -> tuple:
    out.mkdir(parents=True, exist_ok=True)
    if windows:
        path = out / f"{name}.zip"
        return path, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
    path = out / f"{name}.tar.gz"
    return path, tarfile.open(path, "w:gz")


def installer_files() -> list[tuple[Path, str]]:
    """The installer, and the few things outside its folder that it needs."""
    files = [(path, str(path.relative_to(REPO)))
             for path in sorted((REPO / "installer").rglob("*"))
             if path.is_file() and "__pycache__" not in path.parts]
    for extra in ("tools/c7disc.py", "docs/license-gpl.txt",
                  "docs/org.ec7wolf.EC7Wolf.metainfo.xml",
                  "src/posix/icon.svg", "src/posix/engine.desktop.in",
                  "src/macosx/icon.iconset/icon_256x256.png",
                  "docs/installer.md"):
        path = REPO / extra
        if path.is_file():
            files.append((path, extra))
    return files


def package(engine_dir: Path | None, out: Path, kinds: list[str],
            setup_exe: Path | None = None) -> list[Path]:
    tag = platform_tag()
    release = version()
    windows = tag.startswith("windows")
    made: list[Path] = []

    if "binaries" in kinds and engine_dir:
        name = f"EC7Wolf-{release}-{tag}"
        path, archive = _make(out, name, windows)
        with archive:
            _add_tree(archive, engine_dir, name)
            _add_text(archive, f"{name}/INSTALL.txt",
                      _install_text("binaries", tag, release))
        made.append(path)

    if "full" in kinds and engine_dir:
        # Engine plus installer: everything except the game's own data.
        name = f"EC7Wolf-{release}-{tag}-full"
        path, archive = _make(out, name, windows)
        with archive:
            _add_tree(archive, engine_dir, name)
            # On Windows the installer that belongs here is the frozen one --
            # a folder of .py files with no extension on the entry point is not
            # something anybody can run, which is the whole reason the exe is
            # built. Elsewhere the Python installer is the runnable thing.
            if windows and setup_exe and Path(setup_exe).is_file():
                archive.write(setup_exe, f"{name}/EC7Wolf-Setup.exe")
            else:
                for source, arcname in installer_files():
                    target = f"{name}/{arcname}"
                    if windows:
                        archive.write(source, target)
                    else:
                        archive.add(source, target)
            _add_text(archive, f"{name}/INSTALL.txt",
                      _install_text("full", tag, release))
        made.append(path)

    if "installer" in kinds:
        # Platform-neutral, and deliberately still Python: this is the small
        # download that fetches and builds everything, and putting a 22 MB
        # Windows executable in it would make it neither small nor neutral.
        # Windows users are pointed at EC7Wolf-Setup.exe instead.
        name = f"EC7Wolf-{release}-installer"
        path, archive = _make(out, name, True)
        with archive:
            for source, arcname in installer_files():
                archive.write(source, f"{name}/{arcname}")
            _add_text(archive, f"{name}/INSTALL.txt",
                      _install_text("installer", tag, release))
        made.append(path)

    if "source" in kinds:
        name = f"EC7Wolf-{release}-source"
        path = out / f"{name}.tar.gz"
        out.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "archive", "--format=tar.gz", f"--prefix={name}/",
             "-o", str(path), "HEAD"], cwd=REPO, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"git archive failed: {result.stderr.strip()}")
        made.append(path)

    for path in made:
        print(f"  {path.name}  {path.stat().st_size // 1024} KB")
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("engine", help="build and stage the engine")
    build_parser.add_argument("--into", type=Path, required=True)
    build_parser.add_argument("--jobs", type=int, default=os.cpu_count())
    build_parser.add_argument("--allow-software", action="store_true",
                              help="permit a build with no OpenGL backend")

    package_parser = sub.add_parser("package", help="make the release archives")
    package_parser.add_argument("--engine", type=Path)
    package_parser.add_argument("--out", type=Path, default=REPO / "dist")
    package_parser.add_argument("--kinds", default="binaries,full,installer,source")
    package_parser.add_argument("--setup-exe", type=Path,
                                help="the frozen EC7Wolf-Setup.exe, to put in "
                                     "the Windows -full archive")

    arguments = parser.parse_args()
    if arguments.command == "engine":
        build_engine(arguments.into.resolve(), arguments.jobs,
                     arguments.allow_software)
    else:
        package(arguments.engine, arguments.out,
                [k.strip() for k in arguments.kinds.split(",") if k.strip()],
                arguments.setup_exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
