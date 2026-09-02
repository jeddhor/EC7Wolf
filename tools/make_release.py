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
    check_icon(into / engine.executable.name)
    return into


def check_icon(executable: Path) -> None:
    """The executable must carry an icon big enough to be worth having.

    Windows shows a 256-pixel icon in several places and upscales whatever it
    is given. windows.rc guarded the good icon behind _MSC_VER, which rc.exe
    does not define, so for a long time every build embedded the Windows 9x
    file and nobody noticed -- an upscaled 48-pixel icon looks like a slightly
    soft icon, not like a bug.
    """
    from ec7install.windows import icon_sizes

    sizes = icon_sizes(executable)
    if not sizes:
        print("icon:           none in the executable (not fatal)")
        return
    largest = max(sizes)
    if largest >= 128:
        print(f"icon:           {len(sizes)} sizes, up to {largest}px")
        return
    raise SystemExit(
        f"\n{executable.name} carries icons only up to {largest}px "
        f"({sorted(sizes)}). Windows wants 256 and will upscale anything "
        "smaller. Check which .ico src/win32/windows.rc actually compiled.")


def check_dependencies(executable: Path, folder: Path) -> None:
    """Every DLL the binary needs must be here, or be part of Windows.

    beta118 and beta119 shipped a Windows build that wanted
    libgcc_s_seh-1.dll and libstdc++-6.dll -- the MinGW runtime, which is not
    part of Windows and was not in the archive. The binary looked fine, the
    archive looked fine, and the first person to run it got a stack of dialogs.
    Nothing had ever asked the binary what it needed.
    """
    from ec7install.windows import SYSTEM_DLLS, imported_dlls

    if not imported_dlls(executable):
        return
    present = {item.name.lower() for item in folder.iterdir()}

    def unmet(binary: Path) -> list[str]:
        return [name for name in imported_dlls(binary)
                if name.lower() not in SYSTEM_DLLS
                and not name.lower().startswith("api-ms-win-")
                and not name.lower().startswith("ext-ms-win-")
                and name.lower() not in present]

    # The DLLs being shipped are checked too. A dependency of a dependency
    # fails exactly as loudly as one of the executable's own -- libepoxy-0.dll
    # is built by whichever compiler meson found, which need not be the one
    # that built the engine -- and checking only the executable would let that
    # through.
    problems: dict[str, list[str]] = {}
    checked = 0
    for binary in [executable] + sorted(folder.glob("*.dll")):
        missing = unmet(binary)
        checked += len(imported_dlls(binary))
        if missing:
            problems[binary.name] = missing

    if not problems:
        print(f"dependencies:   all {checked} imports across "
              f"{1 + len(list(folder.glob('*.dll')))} binaries resolve here "
              "or in Windows")
        return

    lines = [f"  {name} needs: " + ", ".join(sorted(set(missing)))
             for name, missing in sorted(problems.items())]
    raise SystemExit(
        f"\nSomething in {folder} needs DLLs that are not there and are not "
        "part of Windows:\n" + "\n".join(lines) +
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
    "editor": """\
EC7Edit {version} for {platform}
=================================

A level editor for Corridor 7: Alien Invasion.

Run ./ec7edit (ec7edit.exe on Windows) from this folder. Everything it needs is
in here -- a Python and a Qt of its own -- so nothing has to be installed
first, and nothing on your machine can conflict with it.

THIS DOWNLOAD CONTAINS NO PART OF CORRIDOR 7. It is an editor and nothing else:
no maps, no artwork, no sounds. You need your own copy of the game, and EC7Wolf
to play what you make. The editor asks for both the first time it starts, and
runs without them if you would rather look around first.

MANUAL.md is the full manual. If it will not start, run

    ./ec7edit --selftest

which reports what this build is and where it stopped, and is the thing to
paste into a bug report.
""",

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
            setup_exe: Path | None = None,
            editor_dir: Path | None = None) -> list[Path]:
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
            # The editor travels with -full, which is the download for
            # somebody who wants the whole thing rather than just the game.
            if editor_dir and Path(editor_dir).is_dir():
                _add_tree(archive, Path(editor_dir), f"{name}/EC7Edit")
            _add_text(archive, f"{name}/INSTALL.txt",
                      _install_text("full", tag, release))
        made.append(path)

    if "editor" in kinds and editor_dir and Path(editor_dir).is_dir():
        # EC7Edit on its own. Someone who wants the level editor does not want
        # to download the engine to get it, and someone who wants the engine
        # usually does not want a 74 MB editor attached -- so it is a download
        # of its own as well as traveling inside -full below.
        name = f"EC7Edit-{release}-{tag}"
        path, archive = _make(out, name, windows)
        with archive:
            _add_tree(archive, Path(editor_dir), name)
            _add_text(archive, f"{name}/INSTALL.txt",
                      _install_text("editor", tag, release))
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
    package_parser.add_argument("--kinds",
                                default="binaries,full,editor,installer,source")
    package_parser.add_argument("--editor", type=Path, default=None,
                                metavar="DIR",
                                help="a packaged EC7Edit to ship beside and "
                                     "inside the engine archives")
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
                arguments.setup_exe, arguments.editor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
