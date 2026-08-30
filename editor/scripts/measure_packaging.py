#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Measure PyInstaller onedir against onefile, and report rather than assume.

E4 has to choose a package form, and the choice usually gets made by copying
whatever the last project did. The installer in this repository is onefile, and
that is right for a program somebody runs once. An editor is not that: it gets
launched, closed, and launched again all day, and onefile pays its unpacking
cost on every single one of those.

So this measures, on a synthetic app that imports the same Qt modules EC7Edit
does. What it reports: package size, cold start, and the cost of five repeated
launches, which is the number that actually decides it.

    measure_packaging.py OUTPUT_DIR [--runs 5]

Nothing here is part of the shipped editor. It exists so the packaging decision
in the E4 ledger has numbers behind it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

PROBE = '''\
import sys, time
start = time.perf_counter()
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtWidgets import QApplication, QMainWindow, QListView, QDockWidget
app = QApplication([])
window = QMainWindow()
window.addDockWidget(Qt.LeftDockWidgetArea, QDockWidget("probe", window))
window.setCentralWidget(QListView(window))
window.show()
app.processEvents()
print("READY %.4f" % (time.perf_counter() - start))
'''


def directory_size(path: Path) -> int:
    """Bytes on disk. `lstat`, because Qt ships symlinked libraries.

    `stat()` follows a link and counts its target again, which inflated the
    first measurement of onedir by ninety megabytes.
    """
    if path.is_file() and not path.is_symlink():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        status = item.lstat()
        if not (status.st_mode & 0o170000) == 0o040000:  # not a directory
            total += status.st_size
    return total


def compressed_size(path: Path, work: Path) -> int:
    """What the package costs to download, which is the fair comparison.

    onefile is compressed and a onedir tree is not, so comparing them on disk
    makes onefile look four times smaller than it ships.
    """
    archive = work / f"{path.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(path, arcname=path.name)
    return archive.stat().st_size


def build(mode: str, work: Path, python: Path) -> Path:
    source = work / "probe.py"
    source.write_text(PROBE, encoding="utf-8")
    out = work / mode
    out.mkdir(parents=True, exist_ok=True)
    command = [
        str(python), "-m", "PyInstaller", "--noconfirm", "--clean",
        f"--{mode}", "--name", f"probe-{mode}",
        "--distpath", str(out / "dist"), "--workpath", str(out / "build"),
        "--specpath", str(out), str(source),
    ]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise SystemExit(f"{mode} build failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    binary = out / "dist" / f"probe-{mode}"
    if mode == "onedir":
        binary = binary / f"probe-{mode}"
    print(f"  built {mode} in {elapsed:.1f}s")
    return binary


def launch(binary: Path, runs: int) -> list[float]:
    times = []
    environment = {"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin",
                   "HOME": str(Path.home()), "LC_ALL": "C.UTF-8"}
    for _ in range(runs):
        started = time.perf_counter()
        result = subprocess.run([str(binary)], capture_output=True, text=True,
                                env=environment, timeout=120)
        elapsed = time.perf_counter() - started
        if result.returncode != 0 or "READY" not in result.stdout:
            raise SystemExit(f"launch failed: {result.stdout}\n{result.stderr}")
        times.append(elapsed)
    return times


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--python", type=Path,
                        default=Path(sys.executable))
    arguments = parser.parse_args(argv)

    work = arguments.output
    work.mkdir(parents=True, exist_ok=True)
    report = {"runs": arguments.runs, "modes": {}}

    for mode in ("onedir", "onefile"):
        print(f"{mode}:")
        binary = build(mode, work, arguments.python)
        root = binary.parent if mode == "onedir" else binary
        size = directory_size(root)
        download = compressed_size(root, work)
        times = launch(binary, arguments.runs)
        report["modes"][mode] = {
            "size_bytes": size,
            "size_mb": round(size / (1 << 20), 1),
            "download_mb": round(download / (1 << 20), 1),
            "cold_start_s": round(times[0], 3),
            "median_start_s": round(sorted(times)[len(times) // 2], 3),
            "total_for_runs_s": round(sum(times), 3),
            "files": 1 if mode == "onefile" else sum(1 for _ in root.rglob("*")),
        }
        print(f"  {report['modes'][mode]}")

    onedir = report["modes"]["onedir"]
    onefile = report["modes"]["onefile"]
    report["verdict"] = {
        "startup_penalty_s": round(onefile["median_start_s"] - onedir["median_start_s"], 3),
        "penalty_over_runs_s": round(onefile["total_for_runs_s"] - onedir["total_for_runs_s"], 3),
        "on_disk_difference_mb": round(onefile["size_mb"] - onedir["size_mb"], 1),
        "download_difference_mb": round(onefile["download_mb"] - onedir["download_mb"], 1),
    }
    (work / "packaging.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["verdict"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
