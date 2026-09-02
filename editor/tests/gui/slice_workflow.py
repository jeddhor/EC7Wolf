#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E5's exit gate, driven through the real window against real game data.

    slice_workflow.py DATA_DIR WORK_DIR

Does, in order, what the milestone says a person must be able to do:

  1. import MAP01 from the owned archive, read-only;
  2. confirm the palette decoded a real thumbnail from the artwork;
  3. paint a wall chosen from that palette;
  4. place an enemy and change its facing in the inspector;
  5. undo both and redo both;
  6. save the project, reopen it in a second window, compare;
  7. move the player start, so the engine has something to prove;
  8. export a one-map preview WAD.

It then writes `expected.json` for the shell gate, which runs the engine and
checks the player spawns where the edit put them. Splitting it there keeps the
Qt half offscreen and the engine half under xvfb, which is what each needs.

The archive is only ever read. Its digest is checked at both ends.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from ec7edit_core.catalog import load_catalog
from ec7edit_core.discovery import Profile, data_fingerprint
from ec7edit_core.planes import linear_index
from ec7edit_core.project import load_project
from ec7edit_core.validation import _is_floor

from ec7edit_gui.application import build_application
from ec7edit_gui.main_window import MainWindow
from ec7edit_gui.settings import Settings
from ec7edit_gui.tools import EMPTY_OBJECT, Tool

PLAYER_START_KEY = "thing.player1start"
ENEMY_KEY = "thing.c7rodex.stand.skill1"
WALL_KEY = "wall.002"

failures = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)
    return condition


def note(message):
    print(f"  ..   {message}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv) -> int:
    data_dir = Path(argv[1]).resolve()
    work = Path(argv[2]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    archive = data_dir / "MAPTEMP.CO7"
    before = digest(archive)

    application = build_application([])
    catalog = load_catalog(EDITOR / "resources" / "editor_catalog.json")
    settings = Settings(QSettings(str(work / "settings.ini"), QSettings.IniFormat))
    settings.profile = Profile(
        profile_id="gate", data_dir=str(data_dir), workspace_dir=str(work),
        data_fingerprint=data_fingerprint(data_dir),
    )
    window = MainWindow(settings, catalog=catalog)

    print("Import")
    window.import_map(str(archive), 1)
    if not check(len(window.project) == 1, "MAP01 imported"):
        return 1
    uuid = window.project.maps[0].uuid
    document = window.project.map_by_uuid(uuid)
    note(f"{document.name!r} {document.width}x{document.height}")
    check(document.source is not None and document.source.sha256 == before,
          "the import recorded the archive's digest")

    print("\nArtwork")
    entry = catalog.by_key(WALL_KEY)
    pixels, edge, alpha = window.thumbnails.pixels_for(entry)
    check(len(pixels) == edge * edge * (4 if alpha else 3),
          f"a wall thumbnail decoded from the game data ({edge}x{edge})")
    check(len(set(pixels)) > 4, "the thumbnail is not a flat color")

    print("\nPaint a wall from the palette")
    # Somewhere with floor under it, so the change is visible and legal.
    floor = None
    for y in range(1, document.height - 1):
        for x in range(1, document.width - 1):
            # A released map's floor carries a sound-zone number, not zero.
            if _is_floor(document.cell(0, x, y)) and document.cell(1, x, y) == EMPTY_OBJECT:
                floor = (x, y)
                break
        if floor:
            break
    if not check(floor is not None, "found open floor to edit"):
        return 1

    window.selected_entry = entry
    window.tools.set_entry(entry)
    window.select_tool(Tool.BRUSH)
    window._on_press(floor[0], floor[1], Qt.LeftButton.value)
    window.tools.release(*floor)
    document = window.project.map_by_uuid(uuid)
    check(document.cell(0, *floor) == entry.value,
          f"wall {entry.value} painted at {floor}")

    print("\nPlace and configure an enemy")
    enemy_cell = None
    for y in range(1, document.height - 1):
        for x in range(1, document.width - 1):
            if (x, y) != floor and _is_floor(document.cell(0, x, y)) \
                    and document.cell(1, x, y) == EMPTY_OBJECT:
                enemy_cell = (x, y)
                break
        if enemy_cell:
            break

    enemy = catalog.by_key(ENEMY_KEY)
    window.selected_entry = enemy
    window.tools.set_entry(enemy)
    window._on_press(enemy_cell[0], enemy_cell[1], Qt.LeftButton.value)
    window.tools.release(*enemy_cell)
    document = window.project.map_by_uuid(uuid)
    check(document.cell(1, *enemy_cell) == enemy.value,
          f"{enemy.name} placed at {enemy_cell} facing east ({enemy.value})")

    window.inspector.show_cell(document, *enemy_cell)
    index = window.inspector.direction.findText("North")
    window.inspector.direction.setCurrentIndex(index)
    application.processEvents()
    document = window.project.map_by_uuid(uuid)
    facing_north = dict(enemy.directions)["north"]
    check(document.cell(1, *enemy_cell) == facing_north,
          f"the inspector turned it to face north ({facing_north})")

    print("\nUndo and redo")
    depth = window.history.depth
    window.undo()
    window.undo()
    document = window.project.map_by_uuid(uuid)
    check(document.cell(1, *enemy_cell) == EMPTY_OBJECT,
          "undo took back the enemy and its facing")
    window.redo()
    window.redo()
    document = window.project.map_by_uuid(uuid)
    check(document.cell(1, *enemy_cell) == facing_north, "redo put both back")
    check(window.history.depth == depth, "the history is where it started")

    print("\nMove the player start, so the engine has something to prove")
    start_entry = catalog.by_key(PLAYER_START_KEY)
    old_start = None
    for index in range(document.planes.cell_count):
        if document.planes.planes[1][index] in start_entry.values:
            old_start = (index % document.width, index // document.width)
            break
    if not check(old_start is not None, "MAP01 has a player start"):
        return 1

    # Somewhere clearly elsewhere, on open floor with nothing on it.
    new_start = None
    for y in range(document.height - 2, 0, -1):
        for x in range(document.width - 2, 0, -1):
            if _is_floor(document.cell(0, x, y)) and document.cell(1, x, y) == EMPTY_OBJECT \
                    and (x, y) not in (floor, enemy_cell) and (x, y) != old_start:
                new_start = (x, y)
                break
        if new_start:
            break

    from ec7edit_core.commands import write_words

    window.run_command(write_words(
        window.project.map_by_uuid(uuid),
        [(1, old_start[0], old_start[1], EMPTY_OBJECT),
         (1, new_start[0], new_start[1], start_entry.value)],
        label="Move start",
    ))
    document = window.project.map_by_uuid(uuid)
    check(document.cell(1, *new_start) == start_entry.value,
          f"the start moved from {old_start} to {new_start}")

    print("\nSave and reopen")
    project_path = work / "slice.ec7project"
    window.project_path = project_path
    check(window.save_project(), f"saved {project_path.name}")

    reopened = load_project(project_path)
    check(reopened.maps[0].planes.planes == document.planes.planes,
          "every word survived save and reopen")
    check(reopened.maps[0].native_name.raw == document.native_name.raw,
          "the 16-byte name survived")
    check(not reopened.dirty, "the reopened project is clean")

    print("\nExport")
    wad = work / "slice.wad"
    from ec7edit_core.paths import OutputGuard, atomic_write
    from ec7edit_core.wad import build_preview_wad, read_preview_wad

    blob = build_preview_wad([(document.lump_name, document.to_record())])
    atomic_write(wad, blob, guard=OutputGuard(protected_roots=(data_dir,)))
    pairs = read_preview_wad(wad.read_bytes())
    check(len(pairs) == 1 and pairs[0][0] == "MAP01", "a one-map preview WAD")
    check(pairs[0][1].planes.planes == document.planes.planes,
          "the exported words are the project's words")

    (work / "expected.json").write_text(json.dumps({
        "wad": str(wad),
        "marker": document.lump_name,
        "old_start": list(old_start),
        "new_start": list(new_start),
        "painted": list(floor),
        "wall_value": entry.value,
    }, indent=2) + "\n", encoding="utf-8")

    print("\nThe archive was only read")
    check(digest(archive) == before, "MAPTEMP.CO7 is unchanged")

    window.project = window.project.marked_saved(window.project.revision)
    window.pool.cancel_all()
    window.pool.wait(2000)
    window.close()
    QApplication.processEvents()

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
