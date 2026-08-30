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


class NewMap(Base):
    """Starting from nothing, which is the other way in besides importing."""

    def test_it_adds_a_map_and_opens_it(self):
        before = len(self.window.project)
        document = self.window.new_map(name="FRESH", slot=9, width=16, height=16)
        self.assertIsNotNone(document)
        self.assertEqual(len(self.window.project), before + 1)
        self.assertEqual(self.window.current_tab.map_uuid, document.uuid)

    def test_it_comes_walled(self):
        # A blank map is all floor, so the first thing the validator would say
        # is that the player can walk out of the world.
        document = self.window.new_map(name="WALLED", slot=9, width=12, height=12)
        document = self.window.project.map_by_uuid(document.uuid)
        for x in range(12):
            self.assertNotEqual(document.cell(0, x, 0), 0)
            self.assertNotEqual(document.cell(0, x, 11), 0)
        self.assertEqual(document.cell(0, 5, 5), 0)

    def test_the_object_plane_starts_empty_not_zero(self):
        # Corridor 7's empty marker is 18. A plane of zeros would place
        # whatever word 0 means on every single cell.
        document = self.window.new_map(name="EMPTY", slot=9, width=8, height=8)
        document = self.window.project.map_by_uuid(document.uuid)
        self.assertEqual(document.cell(1, 4, 4), EMPTY_OBJECT)

    def test_it_picks_a_free_slot(self):
        # The project already holds slot 1 from setUp.
        document = self.window.new_map(name="AUTO", width=8, height=8)
        self.assertEqual(document.slot, 2)

    def test_you_can_paint_on_it_immediately(self):
        document = self.window.new_map(name="PAINT", slot=9, width=10, height=10)
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(3, 3), (6, 3)])
        painted = self.window.project.map_by_uuid(document.uuid)
        for x in range(3, 7):
            self.assertEqual(painted.cell(0, x, 3), 2)

    def test_a_new_map_validates_once_it_has_a_start(self):
        document = self.window.new_map(name="VALID", slot=9, width=12, height=12)
        self.choose("thing.player1start")
        self.stroke(Tool.BRUSH, [(5, 5)])
        codes = [p.code for p in self.window.validate()]
        self.assertNotIn("C7E-BOUNDARY-001", codes)
        self.assertNotIn("C7E-START-001", codes)


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


class Structures(Base):
    """Compound tools: one click, one structure, one undo -- or a refusal."""

    def choose_prefab(self, key: str) -> None:
        from ec7edit_core.prefabs import by_key

        prefab = by_key(key)
        self.assertIsNotNone(prefab, key)
        self.window.tools.set_prefab(prefab)
        self.window.select_tool(Tool.PREFAB)

    def place(self, x: int, y: int) -> None:
        self.window._on_press(x, y, Qt.LeftButton.value)
        self.window.tools.release(x, y)

    def test_a_pushwall_writes_both_planes_at_once(self):
        self.choose_prefab("prefab.pushwall.secret")
        self.place(4, 4)
        self.assertEqual(self.document.cell(0, 4, 4), 1)
        self.assertEqual(self.document.cell(1, 4, 4), 98)

    def test_it_is_a_single_undo(self):
        self.choose_prefab("prefab.pushwall.secret")
        before = self.document.planes.planes
        self.place(4, 4)
        self.assertEqual(self.window.history.depth, 1)
        self.window.undo()
        self.assertEqual(self.document.planes.planes, before)

    def test_a_refused_placement_writes_nothing(self):
        # A dispenser needs floor in front. In the middle of the top wall of
        # the room from setUp, the cell below is floor, so aim at a corner.
        self.choose_prefab("prefab.dispenser.health")
        before = self.document.planes.planes
        self.place(0, 9)          # bottom-left corner: no floor below it
        self.assertEqual(self.document.planes.planes, before)
        self.assertFalse(self.window.history.can_undo)

    def test_a_refusal_is_reported(self):
        self.choose_prefab("prefab.dispenser.health")
        self.place(0, 9)
        self.assertGreater(self.window.problems.count(), 0)

    def test_a_dispenser_goes_in_a_wall_with_floor_in_front(self):
        self.choose_prefab("prefab.dispenser.health")
        self.place(4, 0)          # top wall, floor at (4,1)
        self.assertEqual(self.document.cell(0, 4, 0), 85)

    def test_turning_a_structure_moves_what_it_needs(self):
        # In the left wall, the floor is to the east, not the south.
        self.choose_prefab("prefab.dispenser.ammo")
        self.place(0, 4)
        self.assertNotEqual(self.document.cell(0, 0, 4), 111, "should have been refused")
        self.window.tools.rotate_prefab()
        self.window.tools.rotate_prefab()
        self.window.tools.rotate_prefab()
        self.place(0, 4)
        self.assertEqual(self.document.cell(0, 0, 4), 111)

    def test_the_structures_tab_lists_them(self):
        from ec7edit_core.prefabs import PREFABS

        self.assertEqual(self.window.prefab_list.count(), len(PREFABS))

    def test_choosing_from_the_list_arms_the_tool(self):
        self.window.prefab_list.setCurrentRow(0)
        QApplication.processEvents()
        self.assertIsNotNone(self.window.tools.prefab)
        self.assertEqual(self.window.tools.tool, Tool.PREFAB)


class Transporters(Base):
    def arm(self):
        self.window.select_tool(Tool.TRANSPORTER)

    def click(self, x, y):
        self.window._on_press(x, y, Qt.LeftButton.value)
        self.window.tools.release(x, y)

    def test_one_click_writes_nothing(self):
        # A channel with one end is a broken map, not a half-built one.
        self.arm()
        before = self.document.planes.planes
        self.click(3, 3)
        self.assertEqual(self.document.planes.planes, before)
        self.assertIsNotNone(self.window.tools.pending_transporter)

    def test_two_clicks_make_a_pair(self):
        self.arm()
        self.click(3, 3)
        self.click(6, 6)
        self.assertEqual(self.document.cell(0, 3, 3), 279)
        self.assertEqual(self.document.cell(0, 6, 6), 279)

    def test_the_pair_is_one_undo(self):
        self.arm()
        before = self.document.planes.planes
        self.click(3, 3)
        self.click(6, 6)
        self.assertEqual(self.window.history.depth, 1)
        self.window.undo()
        self.assertEqual(self.document.planes.planes, before)

    def test_a_second_pair_takes_the_next_channel(self):
        self.arm()
        self.click(2, 2); self.click(3, 2)
        self.click(2, 4); self.click(3, 4)
        self.assertEqual(self.document.cell(0, 2, 2), 279)
        self.assertEqual(self.document.cell(0, 2, 4), 280)

    def test_clicking_the_same_cell_twice_does_not_pair_it_with_itself(self):
        self.arm()
        self.click(3, 3)
        self.click(3, 3)
        self.assertEqual(self.document.cell(0, 3, 3), 0)
        self.assertIsNotNone(self.window.tools.pending_transporter)

    def test_a_pad_needs_floor(self):
        self.arm()
        self.click(0, 0)          # a wall
        self.assertIsNone(self.window.tools.pending_transporter)

    def test_validation_reports_a_lone_endpoint(self):
        from ec7edit_core.commands import write_words

        document = self.document
        self.window.run_command(write_words(document, [(0, 4, 4, 279)]))
        codes = [p.code for p in self.window.validate()]
        self.assertIn("C7E-WARP-001", codes)

    def test_validation_is_quiet_about_a_proper_pair(self):
        self.arm()
        self.click(3, 3)
        self.click(6, 6)
        codes = [p.code for p in self.window.validate()]
        self.assertNotIn("C7E-WARP-001", codes)


class Clipboard(Base):
    """Copy, paste and the transforms, through the window."""

    def select(self, x, y, w, h):
        self.window.select_tool(Tool.POINTER)
        self.window._on_press(x, y, Qt.LeftButton.value)
        self.window.tools.drag(x + w - 1, y + h - 1, Qt.LeftButton.value)
        self.window.tools.release(x + w - 1, y + h - 1)

    def test_copy_needs_a_selection(self):
        self.assertFalse(self.window.copy_selection())

    def test_copy_then_paste(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(2, 2)])
        self.select(2, 2, 2, 2)
        self.assertTrue(self.window.copy_selection())
        self.select(5, 5, 2, 2)
        self.assertTrue(self.window.paste_clipboard())
        self.assertEqual(self.document.cell(0, 5, 5), 2)

    def test_a_paste_is_one_undo(self):
        self.choose(WALL_ENTRY)
        self.stroke(Tool.BRUSH, [(2, 2)])
        self.select(2, 2, 2, 2)
        self.window.copy_selection()
        before = self.document.planes.planes
        self.select(5, 5, 2, 2)
        depth = self.window.history.depth
        self.window.paste_clipboard()
        self.assertEqual(self.window.history.depth, depth + 1)
        self.window.undo()
        self.assertEqual(self.document.planes.planes, before)

    def test_copy_takes_all_three_planes(self):
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(2, 2)])
        self.select(2, 2, 1, 1)
        self.window.copy_selection()
        self.select(6, 6, 1, 1)
        self.window.paste_clipboard()
        self.assertEqual(self.document.cell(1, 6, 6), RODEX_EAST)

    def test_rotating_the_clipboard_turns_a_facing(self):
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(2, 2)])
        self.select(2, 2, 1, 1)
        self.window.copy_selection()
        self.assertTrue(self.window.rotate_clipboard())
        self.select(6, 6, 1, 1)
        self.window.paste_clipboard()
        entry = CATALOG.for_value(1, self.document.cell(1, 6, 6))
        self.assertEqual(entry.actor, "C7Rodex")
        self.assertEqual(dict(entry.directions).get("south"), self.document.cell(1, 6, 6))

    def test_flipping_the_clipboard(self):
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(2, 2)])
        self.select(2, 2, 1, 1)
        self.window.copy_selection()
        self.assertTrue(self.window.flip_clipboard_h())
        self.select(6, 6, 1, 1)
        self.window.paste_clipboard()
        entry = CATALOG.for_value(1, self.document.cell(1, 6, 6))
        self.assertEqual(dict(entry.directions).get("west"), self.document.cell(1, 6, 6))

    def test_transforms_need_something_copied(self):
        self.assertFalse(self.window.rotate_clipboard())
        self.assertFalse(self.window.flip_clipboard_v())


class Statistics(Base):
    def test_it_counts_what_is_there(self):
        stats = self.window.map_statistics()
        self.assertEqual(stats["cells"], 100)
        self.assertGreater(stats["walls"], 0)
        self.assertGreater(stats["floor"], 0)

    def test_placing_an_enemy_shows_up(self):
        before = self.window.map_statistics()["enemies"]
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(4, 4)])
        self.assertEqual(self.window.map_statistics()["enemies"], before + 1)

    def test_the_used_filter_narrows_the_palette(self):
        from ec7edit_gui.main_window import PALETTE_TABS

        index = [c for _, c in PALETTE_TABS].index("enemies")
        self.window.palette_tabs.setCurrentIndex(index)
        QApplication.processEvents()
        everything = self.window.palette_models["enemies"].rowCount()
        self.window.used_only.setChecked(True)
        QApplication.processEvents()
        self.assertLess(self.window.palette_models["enemies"].rowCount(), everything)

    def test_the_filter_shows_what_the_map_does_use(self):
        self.choose("thing.c7rodex.stand.skill1")
        self.stroke(Tool.BRUSH, [(4, 4)])
        from ec7edit_gui.main_window import PALETTE_TABS

        index = [c for _, c in PALETTE_TABS].index("enemies")
        self.window.palette_tabs.setCurrentIndex(index)
        self.window.used_only.setChecked(True)
        QApplication.processEvents()
        model = self.window.palette_models["enemies"]
        names = [model.data(model.index(r, 0)) for r in range(model.rowCount())]
        self.assertIn("Rodex", names)


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
