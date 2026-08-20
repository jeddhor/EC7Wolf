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

def build_engine(into: Path, jobs: int | None) -> Path:
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
    return into


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

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


def package(engine_dir: Path | None, out: Path, kinds: list[str]) -> list[Path]:
    tag = platform_tag()
    release = version()
    windows = tag.startswith("windows")
    made: list[Path] = []

    if "binaries" in kinds and engine_dir:
        name = f"EC7Wolf-{release}-{tag}"
        path, archive = _make(out, name, windows)
        with archive:
            _add_tree(archive, engine_dir, name)
        made.append(path)

    if "full" in kinds and engine_dir:
        # Engine plus installer: everything except the game's own data.
        name = f"EC7Wolf-{release}-{tag}-full"
        path, archive = _make(out, name, windows)
        with archive:
            _add_tree(archive, engine_dir, name)
            for source, arcname in installer_files():
                target = f"{name}/{arcname}"
                if windows:
                    archive.write(source, target)
                else:
                    archive.add(source, target)
        made.append(path)

    if "installer" in kinds:
        # Platform-neutral: this one compiles and fetches everything itself.
        name = f"EC7Wolf-{release}-installer"
        path, archive = _make(out, name, True)
        with archive:
            for source, arcname in installer_files():
                archive.write(source, f"{name}/{arcname}")
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

    package_parser = sub.add_parser("package", help="make the release archives")
    package_parser.add_argument("--engine", type=Path)
    package_parser.add_argument("--out", type=Path, default=REPO / "dist")
    package_parser.add_argument("--kinds", default="binaries,full,installer,source")

    arguments = parser.parse_args()
    if arguments.command == "engine":
        build_engine(arguments.into, arguments.jobs)
    else:
        package(arguments.engine, arguments.out,
                [k.strip() for k in arguments.kinds.split(",") if k.strip()])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
