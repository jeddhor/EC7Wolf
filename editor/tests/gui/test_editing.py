#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E5: the editing slice, driven through the real window.

Tools, the inspector, validation and the playtest plan, exercised the way a
person uses them: pick something in the palette, press on the canvas, drag,
release, undo. The document is checked after each step, because the thing that
goes wrong in an editor is not that a tool computes the wrong cells -- it is
that the cells go to the wrong map, or the wrong plane, or arrive after the
document has already moved on.

Offscreen, synthetic, no game data.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from ec7edit_core.catalog import load_catalog
from ec7edit_core.document import MapDocument, ProjectDocument
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes, linear_index

from ec7edit_gui.application import build_application
from ec7edit_gui.main_window import MainWindow
from ec7edit_gui.settings import Settings
from ec7edit_gui.tools import EMPTY_OBJECT, Tool

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")
_application = build_application([])

WALL_ENTRY = "wall.002"
RODEX_EAST = 216
ALIOPROBE_EAST = 108


def open_map(width=10, height=10) -> MapDocument:
    """A room with a solid border, which is where editing usually starts."""
    plane0 = []
    for y in range(height):
        for x in range(width):
            edge = x in (0, width - 1) or y in (0, height - 1)
            plane0.append(1 if edge else 0)
    return MapDocument("edit-uuid", 1, NativeName.from_text("ROOM"),
                       MapPlanes(width, height,
                                 (tuple(plane0), (EMPTY_OBJECT,) * (width * height),
                                  (0,) * (width * height))))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.settings = Settings(
            QSettings(str(self.root / "s.ini"), QSettings.IniFormat)
        )
        self.window = MainWindow(self.settings, catalog=CATALOG)
        self.window.set_project(ProjectDocument.create().added(open_map()))
        self.uuid = self.window.project.maps[0].uuid
        self.window.open_map(self.uuid)

    def tearDown(self):
        self.window.project = self.window.project.marked_saved(self.window.project.revision)
        self.window.pool.cancel_all()
        self.window.pool.wait(2000)
        self.window.close()
        self.window.deleteLater()
        QApplication.processEvents()
        self._tmp.cleanup()

    @property
    def document(self) -> MapDocument:
        return self.window.project.map_by_uuid(self.uuid)

    def choose(self, key: str) -> None:
        entry = CATALOG.by_key(key)
        self.assertIsNotNone(entry, key)
        self.window.selected_entry = entry
        self.window.tools.set_entry(entry)

    def stroke(self, tool: Tool, points) -> None:
        """Press, drag through the points, release -- one gesture."""
        self.window.select_tool(tool)
        first = points[0]
        self.window._on_press(first[0], first[1], Qt.LeftButton.value)
        for point in points[1:]:
            self.window.tools.drag(point[0], point[1], Qt.LeftButton.value)
        self.window.tools.release(*points[-1])


class Brush(Base):
    def test_a_click_paints_one_cell(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(3, 3)])
        self.assertEqual(self.document.cell(0, 3, 3), 2)

    def test_a_drag_paints_a_continuous_line(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(2, 2), (5, 2), (8, 2)])
        for x in range(2, 9):
            self.assertEqual(self.document.cell(0, x, 2), 2, f"gap at x={x}")

    def test_a_whole_stroke_is_one_undo(self):
        self.choose(WALL_ENTRY)
        before = self.document.planes.planes
        self.stroke(Tool.BRUSH, [(2, 2), (4, 2), (6, 2)])
        self.assertEqual(self.window.history.depth, 1)
        self.window.undo()
        self.assertEqual(self.document.planes.planes, before)

    def test_two_strokes_are_two_undos(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(2, 2)])
        self.stroke(Tool.BRUSH, [(4, 4)])
        self.assertEqual(self.window.history.depth, 2)

    def test_painting_an_object_writes_plane_one(self):
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(4, 4)])
        self.assertEqual(self.document.cell(1, 4, 4), RODEX_EAST)
        self.assertEqual(self.document.cell(0, 4, 4), 0, "plane 0 was disturbed")

    def test_the_plane_comes_from_the_catalogue_not_the_tool(self):
        # Same code path, different plane, because the entry says so.
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(3, 3)])
        self.choose("thing.player1start")
        self.stroke(Tool.BRUSH, [(5, 5)])
        self.assertEqual(self.document.cell(0, 3, 3), 2)
        self.assertEqual(self.document.cell(1, 5, 5), 19)

    def test_painting_the_same_value_twice_records_nothing(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(3, 3)])
        depth = self.window.history.depth
        self.stroke(Tool.BRUSH, [(3, 3)])
        self.assertEqual(self.window.history.depth, depth)


class Shapes(Base):
    def test_a_line(self):
        self.choose(WALL_ENTRY)
        self.window.select_tool(Tool.LINE)
        self.window._on_press(2, 2, Qt.LeftButton.value)
        self.window.tools.release(6, 2)
        for x in range(2, 7):
            self.assertEqual(self.document.cell(0, x, 2), 2)

    def test_a_rectangle_outline(self):
        self.choose(WALL_ENTRY)
        self.window.filled_box.setChecked(False)
        self.window.select_tool(Tool.RECTANGLE)
        self.window._on_press(2, 2, Qt.LeftButton.value)
        self.window.tools.release(5, 5)
        self.assertEqual(self.document.cell(0, 2, 2), 2)
        self.assertEqual(self.document.cell(0, 5, 5), 2)
        self.assertEqual(self.document.cell(0, 3, 3), 0, "the middle was filled")

    def test_a_filled_rectangle(self):
        self.choose(WALL_ENTRY)
        self.window.filled_box.setChecked(True)
        self.window.select_tool(Tool.RECTANGLE)
        self.window._on_press(2, 2, Qt.LeftButton.value)
        self.window.tools.release(5, 5)
        self.assertEqual(self.document.cell(0, 3, 3), 2)

    def test_a_fill_stops_at_the_wall(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.FILL, [(5, 5)])
        # The interior is 8x8; the border must be untouched.
        self.assertEqual(self.document.cell(0, 5, 5), 2)
        self.assertEqual(self.document.cell(0, 0, 0), 1)

    def test_a_fill_is_one_undo(self):
        self.choose(WALL_ENTRY)
        before = self.document.planes.planes
        self.stroke(Tool.FILL, [(5, 5)])
        self.window.undo()
        self.assertEqual(self.document.planes.planes, before)


class Erasing(Base):
    def test_erasing_a_wall_leaves_floor(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(3, 3)])
        self.stroke(Tool.ERASER, [(3, 3)])
        self.assertEqual(self.document.cell(0, 3, 3), 0)

    def test_erasing_an_object_writes_the_empty_marker(self):
        # Not zero: Corridor 7's empty object-plane word is 18.
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(4, 4)])
        self.stroke(Tool.ERASER, [(4, 4)])
        self.assertEqual(self.document.cell(1, 4, 4), EMPTY_OBJECT)


class Eyedropper(Base):
    def test_it_selects_what_it_finds(self):
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(4, 4)])
        self.choose(WALL_ENTRY)
        self.stroke(Tool.EYEDROPPER, [(4, 4)])
        self.assertEqual(self.window.selected_entry.actor, "C7Rodex")

    def test_it_changes_nothing(self):
        self.choose(WALL_ENTRY)
        before = self.document.planes.planes
        self.stroke(Tool.EYEDROPPER, [(3, 3)])
        self.assertEqual(self.document.planes.planes, before)
        self.assertFalse(self.window.history.can_undo)


class Selection(Base):
    def test_dragging_the_pointer_selects_a_rectangle(self):
        self.window.select_tool(Tool.POINTER)
        self.window._on_press(2, 2, Qt.LeftButton.value)
        self.window.tools.drag(5, 4, Qt.LeftButton.value)
        selection = self.window.tools.selection
        self.assertEqual((selection.x, selection.y, selection.width, selection.height),
                         (2, 2, 4, 3))

    def test_selecting_changes_nothing(self):
        before = self.document.planes.planes
        self.window.select_tool(Tool.POINTER)
        self.window._on_press(2, 2, Qt.LeftButton.value)
        self.window.tools.drag(5, 5, Qt.LeftButton.value)
        self.window.tools.release(5, 5)
        self.assertEqual(self.document.planes.planes, before)


class InspectorPanel(Base):
    def place_alioprobe(self, x=4, y=4):
        self.choose("thing.c7organiceye.stand.skill1")
        self.stroke(Tool.BRUSH, [(x, y)])
        self.window.inspector.show_cell(self.document, x, y)

    def test_it_names_what_is_there(self):
        self.place_alioprobe()
        self.assertIn("Alioprobe", self.window.inspector.heading.text())

    def test_it_shows_the_raw_words(self):
        self.place_alioprobe()
        self.assertIn(str(ALIOPROBE_EAST), self.window.inspector.raw.text())

    def test_changing_the_facing_writes_a_different_word(self):
        self.place_alioprobe()
        inspector = self.window.inspector
        index = inspector.direction.findText("North")
        self.assertGreaterEqual(index, 0)
        inspector.direction.setCurrentIndex(index)
        QApplication.processEvents()
        self.assertEqual(self.document.cell(1, 4, 4), ALIOPROBE_EAST + 1)

    def test_a_facing_change_is_undoable(self):
        self.place_alioprobe()
        self.window.inspector.direction.setCurrentIndex(
            self.window.inspector.direction.findText("West")
        )
        QApplication.processEvents()
        self.window.undo()
        self.assertEqual(self.document.cell(1, 4, 4), ALIOPROBE_EAST)

    def test_switching_to_patrolling_writes_the_patrol_band(self):
        self.place_alioprobe()
        inspector = self.window.inspector
        self.assertTrue(inspector.movement.isEnabled())
        inspector.movement.setCurrentIndex(1)
        QApplication.processEvents()
        value = self.document.cell(1, 4, 4)
        entry = CATALOG.for_value(1, value)
        self.assertEqual(entry.variant, "patrol")
        self.assertEqual(entry.actor, "C7OrganicEye")

    def test_the_difficulty_band_can_be_changed(self):
        self.place_alioprobe()
        inspector = self.window.inspector
        self.assertTrue(inspector.rank.isEnabled())
        inspector.rank.setCurrentIndex(inspector.rank.count() - 1)
        QApplication.processEvents()
        entry = CATALOG.for_value(1, self.document.cell(1, 4, 4))
        self.assertEqual(entry.minskill, 3)
        self.assertEqual(entry.actor, "C7OrganicEye")

    def test_a_thing_with_no_facing_disables_the_control(self):
        self.choose("thing.c7static000")
        self.stroke(Tool.BRUSH, [(6, 6)])
        self.window.inspector.show_cell(self.document, 6, 6)
        self.assertFalse(self.window.inspector.direction.isEnabled())

    def test_an_actor_with_no_patrol_variant_disables_movement(self):
        # There is no patrolling Eniram, so the control must not promise one.
        self.choose("thing.c7eniram.skill1")
        self.stroke(Tool.BRUSH, [(6, 6)])
        self.window.inspector.show_cell(self.document, 6, 6)
        self.assertFalse(self.window.inspector.movement.isEnabled())

    def test_empty_floor_says_so(self):
        self.window.inspector.show_cell(self.document, 5, 5)
        self.assertIn("Empty", self.window.inspector.heading.text())


class Validation(Base):
    def test_a_room_without_a_start_reports_it(self):
        problems = self.window.validate()
        self.assertIn("C7E-START-001", [p.code for p in problems])
        self.assertGreater(self.window.problems.count(), 0)

    def test_placing_a_start_clears_it(self):
        self.choose("thing.player1start")
        self.stroke(Tool.BRUSH, [(5, 5)])
        problems = self.window.validate()
        self.assertNotIn("C7E-START-001", [p.code for p in problems])

    def test_a_problem_carries_its_cell(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.ERASER, [(0, 3)])  # a hole in the boundary
        self.window.validate()
        items = [self.window.problems.item(i) for i in range(self.window.problems.count())]
        self.assertTrue(any(item.data(Qt.UserRole) for item in items))


class Playtest(Base):
    def test_it_refuses_without_a_configured_engine(self):
        from PySide6.QtWidgets import QMessageBox

        original = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        try:
            self.assertFalse(self.window.playtest())
        finally:
            QMessageBox.warning = original
        self.assertTrue(any("No engine configured" in self.window.problems.item(i).text()
                            for i in range(self.window.problems.count())))


if __name__ == "__main__":
    unittest.main(verbosity=1)
