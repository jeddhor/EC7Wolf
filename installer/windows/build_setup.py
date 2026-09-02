#!/usr/bin/env python3
"""Freeze the installer into a single EC7Wolf-Setup.exe.

A Windows user who has to install Python and PySide6 before they can run the
installer does not have an installer, so this is not optional polish -- it is
what makes the graphical installer usable on the platform it was written for.

Run it with a *Windows* Python: on Windows directly, or under Wine, which is
how it is exercised from a Linux machine.

    python installer/windows/build_setup.py
    python installer/windows/build_setup.py --output dist

PyInstaller freezes for the platform it runs on; there is no cross-compiling a
Windows exe from a Linux Python, and pretending otherwise produces an ELF
binary named .exe.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SPEC = HERE / "ec7wolf-setup.spec"


def check_environment() -> list[str]:
    """What is missing, in the order it is worth fixing."""
    problems = []
    if sys.platform != "win32":
        problems.append(
            f"this is {sys.platform} Python, not Windows Python. PyInstaller "
            "freezes for the platform it runs on. On Linux, run it under Wine:\n"
            "    wine .../python.exe installer/windows/build_setup.py")
    for module, package in (("PyInstaller", "pyinstaller"), ("PySide6", "PySide6")):
        try:
            __import__(module)
        except ImportError:
            problems.append(f"{module} is not installed: pip install {package}")
    if not SPEC.is_file():
        problems.append(f"the spec file is missing: {SPEC}")
    return problems


def build(output: Path, clean: bool = True) -> Path:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm",
               "--distpath", str(output), "--workpath", str(output / "build"),
               str(SPEC)]
    if clean:
        command.insert(3, "--clean")

    print("$ " + " ".join(command), flush=True)
    started = time.time()
    result = subprocess.run(command, cwd=str(REPO))
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed ({result.returncode})")

    executable = output / "EC7Wolf-Setup.exe"
    if not executable.is_file():
        raise SystemExit(f"PyInstaller reported success but produced no "
                         f"{executable.name}")
    size = executable.stat().st_size
    print(f"\nbuilt {executable} -- {size / 2**20:.0f} MB in "
          f"{time.time() - started:.0f}s")
    return executable


def smoke_test(executable: Path) -> bool:
    """Start it once and make sure it is a working program.

    A frozen exe that fails on someone else's machine usually fails at the very
    first step -- an import PyInstaller did not collect -- and that shows up
    here, in the second before any window appears.
    """
    print("\nchecking that it starts...", flush=True)
    try:
        result = subprocess.run([str(executable), "--selftest"],
                                capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"  it would not run: {error}")
        return False

    # Exit codes, not printed output: this is a windowed executable with no
    # console, so whatever it writes to stdout may go nowhere at all.
    reasons = {0: "", 1: "the wizard's pages are not what they should be",
               2: "the license text did not make it into the bundle",
               3: "the icon did not make it into the bundle"}
    if result.returncode == 0:
        print("  it starts, builds every page and finds its bundled files")
        return True

    print(f"  it failed the self-test (exit {result.returncode}"
          + (f": {reasons[result.returncode]}" if result.returncode in reasons else "")
          + ")")
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if output:
        print("  " + output.replace("\n", "\n  ")[:800])

    if "icuuc" in output or "importing QtCore" in output:
        print("\n  This looks like Wine rather than a bad bundle. Qt6Core.dll\n"
              "  imports icuuc.dll, which Windows 10 and 11 provide in\n"
              "  System32 and Wine does not implement, so PySide6 cannot load\n"
              "  there at all -- frozen or not. The build itself is fine; the\n"
              "  wizard has to be started on Windows to be checked. CI does\n"
              "  that on a windows-latest runner.")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=REPO / "dist",
                        help="where to put the exe (default: %(default)s)")
    parser.add_argument("--no-clean", action="store_true",
                        help="keep PyInstaller's cache between builds")
    parser.add_argument("--skip-smoke-test", action="store_true")
    arguments = parser.parse_args()

    problems = check_environment()
    if problems:
        print("Cannot build the setup executable:\n")
        for problem in problems:
            print("  * " + problem)
        return 2

    executable = build(arguments.output, clean=not arguments.no_clean)
    if arguments.skip_smoke_test:
        return 0
    return 0 if smoke_test(executable) else 1


if __name__ == "__main__":
    raise SystemExit(main())
