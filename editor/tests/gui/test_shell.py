#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E4: the Qt shell, driven for real on the offscreen platform.

These are not mocked. A real `QApplication`, real widgets, real signals -- on
`QT_QPA_PLATFORM=offscreen`, so they run on a build machine with no display and
still exercise layout, painting and event delivery. A GUI test that stubs the
toolkit tests the stub.

Nothing here needs Corridor 7. Every project is synthetic and the palette runs
without artwork, which is also the state a first-time user is in before setup.
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

from PySide6.QtCore import QPoint, QSettings, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QListView

from ec7edit_core.archive import MapRecord, encode_archive
from ec7edit_core.catalog import load_catalog
from ec7edit_core.commands import paint_cells
from ec7edit_core.document import MapDocument, ProjectDocument
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.project import save_project

from ec7edit_gui.application import build_application, install_exception_hook
from ec7edit_gui.main_window import PALETTE_TABS, MainWindow
from ec7edit_gui.map_canvas import DEFAULT_ZOOM, MAX_ZOOM, MIN_ZOOM, MapCanvas
from ec7edit_gui.palette_models import CatalogModel, EntryRole
from ec7edit_gui.settings import Settings
from ec7edit_gui.workers import WorkerPool

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")

_application = build_application([])


def synthetic_map(slot=1, name="LAB", width=8, height=8) -> MapDocument:
    planes = tuple(
        tuple((plane * 17 + cell) % 300 for cell in range(width * height)) for plane in range(3)
    )
    return MapDocument(
        uuid=f"uuid-{slot}", slot=slot, native_name=NativeName.from_text(name),
        planes=MapPlanes(width, height, planes),
    )


def synthetic_project(maps=2) -> ProjectDocument:
    project = ProjectDocument.create("Offscreen")
    for index in range(maps):
        project = project.added(synthetic_map(index + 1, f"MAP{index}"))
    return project


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        backend = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        self.settings = Settings(backend)
        # Never the user's real ~/.local/share: a suite that autosaves there
        # leaves work behind and reads other runs' leftovers, which is exactly
        # how the recovery tests first failed -- each was offered the previous
        # test's project.
        self.settings.recovery_dir = self.root / "recovery"
        self.window = MainWindow(self.settings, catalog=CATALOG)

    def tearDown(self):
        # Closing a dirty project asks the user what to do, and a modal dialog
        # on the offscreen platform waits forever. Marking it saved is what a
        # user would have done, and keeps `DirtyClose` the only place that
        # dialog actually runs.
        self.close_quietly(self.window)
        QApplication.processEvents()
        self._tmp.cleanup()

    @staticmethod
    def close_quietly(window) -> None:
        window.project = window.project.marked_saved(window.project.revision)
        window.pool.cancel_all()
        window.pool.wait(2000)
        window.close()
        window.deleteLater()


class WindowStructure(Base):
    def test_the_window_has_its_menus(self):
        titles = [action.text() for action in self.window.menuBar().actions()]
        self.assertEqual(titles, ["&File", "&Edit", "&View", "&Tools", "&Help"])

    def test_the_docks_exist_and_are_named(self):
        for dock in (self.window.maps_dock, self.window.palette_dock, self.window.problems_dock):
            self.assertTrue(dock.objectName(), "a dock without a name cannot be restored")

    def test_the_palette_has_every_tab(self):
        titles = [self.window.palette_tabs.tabText(i)
                  for i in range(self.window.palette_tabs.count())]
        self.assertEqual(titles, [title for title, _ in PALETTE_TABS])

    def test_widgets_have_accessible_names(self):
        for widget in (self.window.map_list, self.window.search, self.window.tabs,
                       self.window.problems, self.window.palette_tabs):
            self.assertTrue(widget.accessibleName(), f"{widget} has no accessible name")

    def test_actions_have_object_names(self):
        # An action without an object name cannot be found by a test or bound
        # by a user's shortcut configuration.
        for action in (self.window.action_new, self.window.action_save,
                       self.window.action_undo, self.window.action_export):
            self.assertTrue(action.objectName())

    def test_undo_starts_disabled(self):
        self.assertFalse(self.window.action_undo.isEnabled())
        self.assertFalse(self.window.action_redo.isEnabled())


class ProjectFlow(Base):
    def test_a_new_project_is_empty(self):
        self.window.new_project()
        self.assertEqual(len(self.window.project), 0)
        self.assertEqual(self.window.map_list.count(), 0)

    def test_setting_a_project_lists_its_maps(self):
        self.window.set_project(synthetic_project(3))
        self.assertEqual(self.window.map_list.count(), 3)

    def test_opening_a_map_creates_a_tab(self):
        self.window.set_project(synthetic_project(2))
        self.window.open_map(self.window.project.maps[0].uuid)
        self.assertEqual(self.window.tabs.count(), 1)
        self.assertIn("MAP0", self.window.tabs.tabText(0))

    def test_opening_the_same_map_twice_reuses_the_tab(self):
        self.window.set_project(synthetic_project(1))
        uuid = self.window.project.maps[0].uuid
        self.window.open_map(uuid)
        self.window.open_map(uuid)
        self.assertEqual(self.window.tabs.count(), 1)

    def test_selecting_in_the_list_opens_the_map(self):
        self.window.set_project(synthetic_project(2))
        self.window.map_list.setCurrentRow(1)
        QApplication.processEvents()
        self.assertEqual(self.window.tabs.count(), 1)
        self.assertEqual(self.window.current_tab.map_uuid, self.window.project.maps[1].uuid)

    def test_save_and_reopen(self):
        path = self.root / "demo.ec7project"
        self.window.set_project(synthetic_project(2))
        self.window.project_path = path
        self.assertTrue(self.window.save_project())
        self.assertTrue(path.exists())

        other = MainWindow(self.settings, catalog=CATALOG)
        try:
            other.open_project(str(path))
            self.assertEqual(len(other.project), 2)
            self.assertFalse(other.project.dirty)
        finally:
            self.close_quietly(other)

    def test_the_menu_asks_for_a_file_rather_than_silently_returning(self):
        # QAction.triggered carries a `checked` bool and PySide6 hands it to any
        # slot that can take it, so File > Open project called
        # open_project(False). That reads as an empty path -- what a canceled
        # dialog looks like -- and it returned without ever opening one.
        from PySide6.QtWidgets import QFileDialog

        asked = []
        self.window._confirm_discard = lambda: True
        original = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(
            lambda *a, **k: (asked.append(True), ("", ""))[1]
        )
        try:
            self.window.action_open.trigger()
        finally:
            QFileDialog.getOpenFileName = original
        self.assertTrue(asked, "triggering Open project never opened a file dialog")

    def test_no_command_action_takes_the_checked_flag(self):
        # The same trap for every other one: New map would skip its name prompt,
        # Import map its file dialog.
        import inspect

        for action in (self.window.action_open, self.window.action_new_map,
                       self.window.action_import, self.window.action_export):
            with self.subTest(action=action.text()):
                self.assertFalse(action.isCheckable(),
                                 "a checkable action would actually want the flag")

    def test_saving_records_the_project_as_recent(self):
        path = self.root / "recent.ec7project"
        self.window.set_project(synthetic_project(1))
        self.window.project_path = path
        self.window.save_project()
        self.assertIn(str(path.resolve()), self.settings.recent_projects)

    def test_open_recent_lists_what_was_opened(self):
        paths = []
        for index in range(8):
            path = self.root / f"p{index}.ec7project"
            self.window.set_project(synthetic_project(1))
            self.window.project_path = path
            self.window.save_project()
            paths.append(path)
        self.window._rebuild_recent_menu()
        names = [a.text() for a in self.window.recent_menu.actions()
                 if not a.isSeparator()]
        # Newest first, capped, and the clear entry on the end.
        self.assertEqual(len(names), self.window.RECENT_SHOWN + 1)
        self.assertIn(paths[-1].name, names[0])
        self.assertEqual(names[-1], "Clear the list")

    def test_open_recent_is_empty_until_something_is_opened(self):
        self.window.clear_recent()
        self.window._rebuild_recent_menu()
        actions = self.window.recent_menu.actions()
        self.assertEqual([a.text() for a in actions], ["No recent projects"])
        self.assertFalse(actions[0].isEnabled())

    def test_a_recent_project_that_is_gone_is_forgotten(self):
        path = self.root / "vanished.ec7project"
        self.window.set_project(synthetic_project(1))
        self.window.project_path = path
        self.window.save_project()
        path.unlink()
        errors = []
        self.window._error = lambda title, body: errors.append(title)
        self.window.open_recent(str(path))
        self.assertTrue(errors)
        self.assertNotIn(str(path.resolve()), self.settings.recent_projects)

    def test_choosing_a_recent_entry_opens_it(self):
        path = self.root / "again.ec7project"
        self.window.set_project(synthetic_project(2))
        self.window.project_path = path
        self.window.save_project()
        self.window.set_project(synthetic_project(1))
        self.window._confirm_discard = lambda: True
        self.window._rebuild_recent_menu()
        entry = next(a for a in self.window.recent_menu.actions()
                     if a.objectName() == "recent-1")
        entry.trigger()
        QApplication.processEvents()
        self.assertEqual(len(self.window.project), 2)

    def test_save_a_copy_leaves_this_project_alone(self):
        # Save As moves where the project lives; a copy does not. The
        # distinction matters because Save As silently changes what the next
        # Ctrl+S overwrites.
        from PySide6.QtWidgets import QFileDialog

        here = self.root / "here.ec7project"
        there = self.root / "there.ec7project"
        self.window.set_project(synthetic_project(2))
        self.window.project_path = here
        self.window.save_project()
        self.window.project = self.window.project.touched()

        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(there), ""))
        try:
            self.assertTrue(self.window.save_copy())
        finally:
            QFileDialog.getSaveFileName = original

        self.assertTrue(there.exists())
        self.assertEqual(self.window.project_path, here)
        self.assertTrue(self.window.project.dirty,
                        "a copy is not a save; the project is still unsaved")

    def test_a_copy_refuses_to_overwrite_this_project(self):
        from PySide6.QtWidgets import QFileDialog

        here = self.root / "same.ec7project"
        self.window.set_project(synthetic_project(1))
        self.window.project_path = here
        self.window.save_project()
        errors = []
        self.window._error = lambda title, body: errors.append(title)
        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(here), ""))
        try:
            self.assertFalse(self.window.save_copy())
        finally:
            QFileDialog.getSaveFileName = original
        self.assertTrue(errors)

    def test_a_file_changed_underneath_is_never_silently_overwritten(self):
        from PySide6.QtWidgets import QMessageBox

        path = self.root / "shared.ec7project"
        self.window.set_project(synthetic_project(1))
        self.window.project_path = path
        self.window.save_project()

        # Somebody else writes the file: another editor, a sync client, a text
        # editor. The identity the window is holding is now stale.
        path.write_text(path.read_text() + "\n")
        self.window.project = self.window.project.touched()

        asked = []
        original = QMessageBox.question
        QMessageBox.question = staticmethod(
            lambda *a, **k: (asked.append(True),
                             QMessageBox.StandardButton.Cancel)[1])
        try:
            self.assertFalse(self.window.save_project())
        finally:
            QMessageBox.question = original
        self.assertTrue(asked, "it overwrote a changed file without asking")

    def test_autosave_writes_only_when_there_is_something_to_recover(self):
        self.window.set_project(synthetic_project(1))
        self.window.project_path = self.root / "auto.ec7project"
        self.window.save_project()
        self.assertFalse(self.window.autosave(), "a saved project has nothing to recover")
        self.window.project = self.window.project.touched()
        self.assertTrue(self.window.autosave())

    def test_saving_clears_the_recovery_copy(self):
        self.window.set_project(synthetic_project(1))
        self.window.project_path = self.root / "clear.ec7project"
        self.window.project = self.window.project.touched()
        self.window.autosave()
        self.assertTrue([r for r in self.window.recovery.list_recoveries()
                         if r.project_uuid == self.window.project.uuid])
        self.window.save_project()
        self.assertFalse([r for r in self.window.recovery.list_recoveries()
                          if r.project_uuid == self.window.project.uuid])

    def test_recovery_is_offered_and_can_be_declined(self):
        from PySide6.QtWidgets import QMessageBox

        self.window.set_project(synthetic_project(2))
        self.window.project = self.window.project.touched()
        self.window.autosave()
        uuid = self.window.project.uuid

        other = MainWindow(self.settings, catalog=CATALOG)
        other.recovery = self.window.recovery
        original = QMessageBox.question
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.No)
        try:
            self.assertEqual(other.offer_recovery(), 0)
        finally:
            QMessageBox.question = original
            self.close_quietly(other)
        # Declined means discarded: an offer that returns every launch is one
        # people learn to dismiss without reading.
        self.assertFalse([r for r in self.window.recovery.list_recoveries()
                          if r.project_uuid == uuid])

    def test_recovery_reopens_the_unsaved_work(self):
        from PySide6.QtWidgets import QMessageBox

        self.window.set_project(synthetic_project(3))
        self.window.project = self.window.project.touched()
        self.window.autosave()

        other = MainWindow(self.settings, catalog=CATALOG)
        other.recovery = self.window.recovery
        original = QMessageBox.question
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes)
        try:
            self.assertEqual(other.offer_recovery(), 1)
            self.assertEqual(len(other.project), 3)
        finally:
            QMessageBox.question = original
            self.close_quietly(other)

    def test_the_title_shows_unsaved_changes(self):
        self.window.set_project(synthetic_project(1))
        document = self.window.project.maps[0]
        self.window.run_command(paint_cells(document, 0, [(1, 1)], 99))
        self.assertIn("•", self.window.windowTitle())

    def test_importing_from_an_archive(self):
        archive = self.root / "source.c7map"
        records = [
            MapRecord(1, NativeName.from_text("IMPORTED"),
                      MapPlanes(4, 4, ((7,) * 16, (18,) * 16, (0,) * 16)))
        ]
        archive.write_bytes(encode_archive(records))
        before = archive.read_bytes()

        self.window.set_project(ProjectDocument.create())
        self.window.import_map(str(archive), 1)
        self.assertEqual(len(self.window.project), 1)
        self.assertEqual(self.window.project.maps[0].name, "IMPORTED")
        self.assertEqual(self.window.tabs.count(), 1)
        self.assertEqual(archive.read_bytes(), before, "the archive was written to")

    def test_an_import_records_where_it_came_from(self):
        archive = self.root / "source.c7map"
        archive.write_bytes(encode_archive([
            MapRecord(1, NativeName.from_text("SRC"), MapPlanes.empty(4, 4))
        ]))
        self.window.set_project(ProjectDocument.create())
        self.window.import_map(str(archive), 1)
        source = self.window.project.maps[0].source
        self.assertEqual(len(source.sha256), 64)
        self.assertEqual(source.map_number, 1)


class Editing(Base):
    def test_an_edit_goes_through_the_history(self):
        self.window.set_project(synthetic_project(1))
        document = self.window.project.maps[0]
        self.window.open_map(document.uuid)
        self.window.run_command(paint_cells(document, 0, [(2, 2)], 123))
        self.assertEqual(self.window.project.maps[0].cell(0, 2, 2), 123)
        self.assertTrue(self.window.action_undo.isEnabled())

    def test_undo_and_redo_from_the_menu(self):
        self.window.set_project(synthetic_project(1))
        document = self.window.project.maps[0]
        before = document.cell(0, 3, 3)
        self.window.open_map(document.uuid)
        self.window.run_command(paint_cells(document, 0, [(3, 3)], 321))
        self.window.action_undo.trigger()
        self.assertEqual(self.window.project.maps[0].cell(0, 3, 3), before)
        self.window.action_redo.trigger()
        self.assertEqual(self.window.project.maps[0].cell(0, 3, 3), 321)

    def test_the_canvas_follows_the_document(self):
        self.window.set_project(synthetic_project(1))
        document = self.window.project.maps[0]
        tab = self.window.open_map(document.uuid)
        self.window.run_command(paint_cells(document, 0, [(1, 1)], 77))
        self.assertEqual(tab.canvas.document.cell(0, 1, 1), 77)


class Canvas(unittest.TestCase):
    def setUp(self):
        self.document = synthetic_map(width=8, height=8)
        self.canvas = MapCanvas(self.document, CATALOG)

    def tearDown(self):
        self.canvas.deleteLater()
        QApplication.processEvents()

    def test_it_sizes_itself_to_the_map(self):
        self.assertEqual(
            self.canvas.size(), QSize(8 * DEFAULT_ZOOM, 8 * DEFAULT_ZOOM)
        )

    def test_zoom_is_clamped(self):
        self.canvas.set_zoom(1000)
        self.assertEqual(self.canvas.zoom, MAX_ZOOM)
        self.canvas.set_zoom(0)
        self.assertEqual(self.canvas.zoom, MIN_ZOOM)

    def test_zoom_resizes(self):
        self.canvas.set_zoom(20)
        self.assertEqual(self.canvas.size(), QSize(160, 160))

    def test_cell_hit_testing(self):
        self.canvas.set_zoom(10)
        self.assertEqual(self.canvas.cell_at(QPoint(0, 0)), (0, 0))
        self.assertEqual(self.canvas.cell_at(QPoint(9, 9)), (0, 0))
        self.assertEqual(self.canvas.cell_at(QPoint(10, 0)), (1, 0))
        self.assertEqual(self.canvas.cell_at(QPoint(35, 72)), (3, 7))

    def test_a_point_outside_the_map_is_no_cell(self):
        self.canvas.set_zoom(10)
        self.assertEqual(self.canvas.cell_at(QPoint(999, 0)), (-1, -1))
        self.assertEqual(self.canvas.cell_at(QPoint(0, 999)), (-1, -1))

    def test_hit_testing_survives_a_zoom_change(self):
        # The bug this guards: caching a scale and forgetting to update it, so
        # the cell painted is not the cell under the pointer.
        for zoom in (MIN_ZOOM, 7, 13, MAX_ZOOM):
            self.canvas.set_zoom(zoom)
            self.assertEqual(self.canvas.cell_at(QPoint(zoom * 2 + 1, zoom * 3 + 1)), (2, 3))

    def test_it_paints_without_a_document(self):
        blank = MapCanvas(None, CATALOG)
        image = QImage(QSize(64, 64), QImage.Format_RGB32)
        image.fill(0)
        blank.render(image)
        blank.deleteLater()

    def test_it_paints_a_map(self):
        image = QImage(self.canvas.size(), QImage.Format_RGB32)
        image.fill(0)
        self.canvas.render(image)
        # Something was actually drawn: more than one color on the surface.
        colors = {image.pixel(x, y) for x in range(0, image.width(), 3)
                   for y in range(0, image.height(), 3)}
        self.assertGreater(len(colors), 1)

    def test_hover_reports_the_cell(self):
        seen = []
        self.canvas.hovered.connect(lambda x, y: seen.append((x, y)))
        self.canvas.set_zoom(10)
        self.canvas._hover = (-1, -1)
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(QMouseEvent.MouseMove, QPoint(25, 35), Qt.NoButton,
                            Qt.NoButton, Qt.NoModifier)
        self.canvas.mouseMoveEvent(event)
        self.assertEqual(seen[-1], (2, 3))


class Palette(Base):
    def show_tab(self, category: str) -> None:
        """Select a palette tab by category, not by a number that moves."""
        index = [c for _, c in PALETTE_TABS].index(category)
        self.window.palette_tabs.setCurrentIndex(index)
        QApplication.processEvents()

    def test_every_tab_has_entries(self):
        for title, category in PALETTE_TABS:
            if category == "prefabs":
                self.assertGreater(self.window.prefab_list.count(), 0, "Structures is empty")
                continue
            self.show_tab(category)
            model = self.window.palette_models[category]
            self.assertGreater(model.rowCount(), 0, f"{title} is empty")

    def test_search_narrows_the_list(self):
        self.show_tab("enemies")
        model = self.window.palette_models["enemies"]
        everything = model.rowCount()
        self.window.search.setText("Rodex")
        QApplication.processEvents()
        self.assertLess(model.rowCount(), everything)
        self.assertGreater(model.rowCount(), 0)

    def test_searching_by_raw_value_works(self):
        self.show_tab("enemies")
        self.window.search.setText("108")
        QApplication.processEvents()
        model = self.window.palette_models["enemies"]
        names = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        self.assertIn("Alioprobe", names)

    def test_entries_carry_their_catalog_object(self):
        model = self.window.palette_models["walls"]
        model.set_entries(CATALOG.in_category("walls")[:5])
        entry = model.data(model.index(0, 0), EntryRole)
        self.assertEqual(entry.category, "walls")

    def test_a_placeholder_appears_without_game_data(self):
        # Before setup, and on a machine with no right to the artwork, every
        # entry still has a tile. A palette of gaps is not a palette.
        model = self.window.palette_models["walls"]
        model.set_entries(CATALOG.in_category("walls")[:3])
        icon = model.data(model.index(0, 0), Qt.DecorationRole)
        self.assertFalse(icon.isNull())

    def test_tooltips_name_the_raw_value(self):
        model = self.window.palette_models["enemies"]
        model.set_entries(CATALOG.in_category("enemies")[:1])
        tooltip = model.data(model.index(0, 0), Qt.ToolTipRole)
        self.assertIn("raw", tooltip)

    def test_accessible_text_is_provided(self):
        model = self.window.palette_models["objects"]
        model.set_entries(CATALOG.in_category("objects")[:1])
        text = model.data(model.index(0, 0), Qt.AccessibleTextRole)
        self.assertIn("raw value", text)


class Workers(unittest.TestCase):
    def setUp(self):
        self.pool = WorkerPool(max_threads=2)
        self.completed = []
        self.discarded = []
        self.failed = []
        self.pool.completed.connect(lambda key, result: self.completed.append((key, result)))
        self.pool.discarded.connect(self.discarded.append)
        self.pool.failed.connect(lambda key, text: self.failed.append(key))

    def tearDown(self):
        self.pool.cancel_all()
        self.pool.wait(2000)

    def drain(self):
        self.pool.wait(5000)
        QApplication.processEvents()

    def test_a_job_delivers_its_result(self):
        self.pool.submit("a", lambda job: 42)
        self.drain()
        self.assertEqual(self.completed, [("a", 42)])

    def test_a_stale_result_is_discarded(self):
        # The document moved on while the job was in flight. Delivering the old
        # answer would show the user the wrong thing with no way to tell.
        self.pool.set_revision(1)
        self.pool.submit("b", lambda job: "old")
        self.pool.set_revision(2)
        self.drain()
        self.assertEqual(self.discarded, ["b"])
        self.assertEqual(self.completed, [])

    def test_work_that_does_not_track_the_document_survives_an_edit(self):
        # A thumbnail is the user's artwork; it does not go stale because they
        # painted a cell. Tagging those with the revision meant painting
        # anything discarded every thumbnail still decoding.
        self.pool.set_revision(1)
        self.pool.submit("art", lambda job: "pixels", tracks_revision=False)
        self.pool.set_revision(2)
        self.drain()
        self.assertEqual(self.completed, [("art", "pixels")])
        self.assertEqual(self.discarded, [])

    def test_a_failing_job_does_not_take_the_pool_down(self):
        def explode(job):
            raise RuntimeError("boom")

        self.pool.submit("c", explode)
        self.pool.submit("d", lambda job: 7)
        self.drain()
        self.assertEqual(self.failed, ["c"])
        self.assertIn(("d", 7), self.completed)

    def test_resubmitting_a_key_cancels_the_earlier_job(self):
        first = self.pool.submit("e", lambda job: 1)
        self.pool.submit("e", lambda job: 2)
        self.drain()
        self.assertTrue(first.canceled)

    def test_cancel_all_stops_delivery(self):
        self.pool.submit("f", lambda job: 1)
        self.pool.cancel_all()
        self.drain()
        self.assertEqual(self.completed, [])


class Layout(Base):
    def test_layout_survives_a_round_trip(self):
        self.window.palette_dock.setFloating(True)
        self.settings.save_layout(self.window.saveGeometry(), self.window.saveState())
        restored = MainWindow(self.settings, catalog=CATALOG)
        try:
            self.assertTrue(restored.palette_dock.isFloating())
        finally:
            self.close_quietly(restored)

    def test_reset_puts_the_docks_back(self):
        self.window.palette_dock.setFloating(True)
        self.window.palette_dock.hide()
        self.window.reset_layout()
        self.assertFalse(self.window.palette_dock.isFloating())
        self.assertFalse(self.window.palette_dock.isHidden())

    def test_reset_works_at_several_sizes(self):
        for size in (QSize(800, 600), QSize(1920, 1080), QSize(1024, 768)):
            self.window.resize(size)
            QApplication.processEvents()
            self.window.reset_layout()
            self.assertFalse(self.window.palette_dock.isHidden())


class DirtyClose(Base):
    def test_closing_a_dirty_project_asks_before_discarding(self):
        from PySide6.QtWidgets import QMessageBox

        self.window.set_project(synthetic_project(1))
        document = self.window.project.maps[0]
        self.window.run_command(paint_cells(document, 0, [(1, 1)], 5))
        self.assertTrue(self.window.project.dirty)

        asked = []
        original = QMessageBox.question

        def answer(*args, **kwargs):
            asked.append(args)
            return QMessageBox.Discard

        QMessageBox.question = staticmethod(answer)
        try:
            self.assertTrue(self.window._confirm_discard())
        finally:
            QMessageBox.question = original
        self.assertEqual(len(asked), 1)

    def test_a_clean_project_closes_without_asking(self):
        from PySide6.QtWidgets import QMessageBox

        self.window.set_project(synthetic_project(1))
        self.window.project = self.window.project.marked_saved(self.window.project.revision)
        original = QMessageBox.question

        def refuse(*args, **kwargs):
            raise AssertionError("asked about a clean project")

        QMessageBox.question = staticmethod(refuse)
        try:
            self.assertTrue(self.window._confirm_discard())
        finally:
            QMessageBox.question = original


class FirstRun(unittest.TestCase):
    """Setup shows a checklist, not a verdict, and never runs anything unasked."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.workspace = self.root / "projects"

    def tearDown(self):
        self._tmp.cleanup()
        QApplication.processEvents()

    def make_data(self) -> None:
        """A synthetic game directory: right names, right shapes, no retail bytes."""
        from ec7edit_core.assets import PALETTE_OFFSET, PALETTE_SIZE

        executable = bytearray(b"\x00" * PALETTE_OFFSET)
        for index in range(256):
            executable += bytes(((index // 4) & 63, (index // 8) & 63, (index // 16) & 63))
        (self.data / "CORR7CD.EXE").write_bytes(bytes(executable))
        (self.data / "MAPTEMP.CO7").write_bytes(encode_archive([
            MapRecord(1, NativeName.from_text("SYNTH"), MapPlanes.empty(8, 8))
        ]))
        import struct

        chunks = 2
        header = struct.pack("<HHH", chunks, 1, 2)
        header += struct.pack(f"<{chunks}I", 6 + chunks * 6, 6 + chunks * 6)
        header += struct.pack(f"<{chunks}H", 0, 0)
        (self.data / "GFXTILES.CO7").write_bytes(header)

    def dialog(self, **paths):
        from ec7edit_gui.first_run import FirstRunDialog
        from ec7edit_core.discovery import Profile

        return FirstRunDialog(Profile(**paths))

    def test_an_empty_profile_cannot_be_saved(self):
        dialog = self.dialog(engine_path="", data_dir="", workspace_dir="")
        try:
            self.assertFalse(dialog.usable)
        finally:
            dialog.deleteLater()

    def test_a_missing_data_directory_is_reported(self):
        dialog = self.dialog(data_dir=str(self.root / "nope"),
                             workspace_dir=str(self.workspace))
        try:
            self.assertFalse(dialog.usable)
            rows = [dialog.checklist.topLevelItem(i).text(1)
                    for i in range(dialog.checklist.topLevelItemCount())]
            self.assertIn("Data directory", rows)
        finally:
            dialog.deleteLater()

    def test_a_complete_profile_is_usable(self):
        self.make_data()
        dialog = self.dialog(data_dir=str(self.data), workspace_dir=str(self.workspace))
        try:
            self.assertTrue(dialog.usable, [
                (dialog.checklist.topLevelItem(i).text(1),
                 dialog.checklist.topLevelItem(i).text(2))
                for i in range(dialog.checklist.topLevelItemCount())
            ])
        finally:
            dialog.deleteLater()

    def test_optional_content_is_a_note_not_a_blocker(self):
        self.make_data()
        dialog = self.dialog(data_dir=str(self.data), workspace_dir=str(self.workspace))
        try:
            statuses = {dialog.checklist.topLevelItem(i).text(1):
                        dialog.checklist.topLevelItem(i).text(0)
                        for i in range(dialog.checklist.topLevelItemCount())}
            self.assertEqual(statuses.get("Optional content"), "note")
            self.assertTrue(dialog.usable)
        finally:
            dialog.deleteLater()

    def test_a_workspace_inside_the_game_data_is_refused(self):
        self.make_data()
        dialog = self.dialog(data_dir=str(self.data),
                             workspace_dir=str(self.data / "projects"))
        try:
            self.assertFalse(dialog.usable)
        finally:
            dialog.deleteLater()

    def test_the_profile_carries_a_fingerprint(self):
        self.make_data()
        dialog = self.dialog(data_dir=str(self.data), workspace_dir=str(self.workspace))
        try:
            self.assertEqual(len(dialog.profile().data_fingerprint), 64)
        finally:
            dialog.deleteLater()

    def test_the_engine_is_not_run_until_asked(self):
        # Executing a binary the user selected is a real action; it waits for a
        # real decision, and until then the checklist says it does not know.
        self.make_data()
        marker = self.root / "was-run"
        script = self.root / "fake-engine"
        script.write_text(f"#!/bin/sh\ntouch {marker}\necho EC7Wolf 1.0-beta1\n")
        script.chmod(0o755)

        dialog = self.dialog(engine_path=str(script), data_dir=str(self.data),
                             workspace_dir=str(self.workspace))
        try:
            self.assertFalse(marker.exists(), "the engine was run without being asked")
            statuses = {dialog.checklist.topLevelItem(i).text(1):
                        dialog.checklist.topLevelItem(i).text(0)
                        for i in range(dialog.checklist.topLevelItemCount())}
            self.assertEqual(statuses.get("Engine identity"), "note")

            dialog.probe_button.click()
            QApplication.processEvents()
            self.assertTrue(marker.exists(), "the probe did not run the engine")
            self.assertIn("EC7Wolf", dialog.profile().engine_version)
        finally:
            dialog.deleteLater()

    def test_a_binary_that_is_not_ec7wolf_is_refused(self):
        self.make_data()
        script = self.root / "upstream"
        script.write_text("#!/bin/sh\necho ECWolf 1.4.2\n")
        script.chmod(0o755)
        dialog = self.dialog(engine_path=str(script), data_dir=str(self.data),
                             workspace_dir=str(self.workspace))
        try:
            dialog.probe_button.click()
            QApplication.processEvents()
            self.assertFalse(dialog.usable)
        finally:
            dialog.deleteLater()


class Setup(Base):
    """First-run setup, driven from the window the way `main()` drives it.

    Nothing exercised this path before, which is how `dialog.Accepted` shipped:
    in PySide6 that enum is a class attribute, so reading it off an instance
    raises, and the failure only happens after the dialog closes -- past the
    point any earlier test looked.
    """

    def make_data(self) -> Path:
        from ec7edit_core.assets import PALETTE_OFFSET

        data = self.root / "game"
        data.mkdir()
        executable = bytearray(b"\x00" * PALETTE_OFFSET)
        for index in range(256):
            executable += bytes(((index // 4) & 63, (index // 8) & 63, (index // 16) & 63))
        (data / "CORR7CD.EXE").write_bytes(bytes(executable))
        (data / "MAPTEMP.CO7").write_bytes(encode_archive([
            MapRecord(1, NativeName.from_text("SYNTH"), MapPlanes.empty(8, 8))
        ]))
        import struct

        header = struct.pack("<HHH", 2, 1, 2)
        header += struct.pack("<2I", 18, 18) + struct.pack("<2H", 0, 0)
        (data / "GFXTILES.CO7").write_bytes(header)
        return data

    def run_setup_answering(self, answer):
        from PySide6.QtWidgets import QDialog

        from ec7edit_gui import first_run

        data = self.make_data()
        original_exec = first_run.FirstRunDialog.exec
        original_profile = first_run.FirstRunDialog.profile

        def fake_exec(dialog):
            dialog.data.path = str(data)
            dialog.workspace.path = str(self.root / "projects")
            dialog._revalidate()
            return answer

        first_run.FirstRunDialog.exec = fake_exec
        try:
            return self.window.run_setup()
        finally:
            first_run.FirstRunDialog.exec = original_exec
            first_run.FirstRunDialog.profile = original_profile

    def test_accepting_saves_the_profile(self):
        from PySide6.QtWidgets import QDialog

        self.assertTrue(self.run_setup_answering(QDialog.DialogCode.Accepted))
        self.assertTrue(self.settings.configured)
        self.assertTrue(self.settings.profile.data_dir)

    def test_cancelling_changes_nothing(self):
        from PySide6.QtWidgets import QDialog

        before = self.settings.profile.data_dir
        self.assertFalse(self.run_setup_answering(QDialog.DialogCode.Rejected))
        self.assertEqual(self.settings.profile.data_dir, before)

    def test_the_dialog_code_is_a_class_attribute(self):
        # The mistake itself, pinned: PySide6 puts enum values on the class,
        # and an instance does not carry them.
        from PySide6.QtWidgets import QDialog

        from ec7edit_gui.first_run import FirstRunDialog

        dialog = FirstRunDialog()
        try:
            self.assertFalse(hasattr(dialog, "Accepted"))
            self.assertTrue(hasattr(QDialog, "Accepted"))
        finally:
            dialog.deleteLater()


class ExceptionReporting(unittest.TestCase):
    def test_the_hook_records_rather_than_losing_it(self):
        seen = []

        class Fake:
            def _note_problem(self, message):
                seen.append(message)

        previous = sys.excepthook
        try:
            install_exception_hook(Fake(), show_dialog=False)
            try:
                raise ValueError("something went wrong")
            except ValueError:
                sys.excepthook(*sys.exc_info())
            self.assertTrue(any("something went wrong" in message for message in seen))
        finally:
            sys.excepthook = previous


if __name__ == "__main__":
    unittest.main(verbosity=1)


class PlaytestSessions(Base):
    """E9: the process controller, driven by a fake engine rather than the real
    one, so the lifecycle is testable without a game or a display."""

    def fake_engine(self, script: str) -> Path:
        path = self.root / "fake-engine.sh"
        path.write_text("#!/bin/sh\n" + script)
        path.chmod(0o755)
        return path

    def plan_for(self, engine: Path, session="s1"):
        from ec7edit_core.engine_runner import LaunchPlan

        return LaunchPlan(engine, [], self.root, session=session,
                          session_dir=self.root / "sess",
                          preview=self.root / "preview.wad")

    def run_to_end(self, engine, session="s1", timeout=8000):
        from PySide6.QtCore import QProcess

        self.assertTrue(self.window.start_session(self.plan_for(engine, session), "TEST"))
        if self.window.process.state() != QProcess.ProcessState.NotRunning:
            self.window.process.waitForFinished(timeout)
        QApplication.processEvents()
        return self.window.session

    def test_a_good_run_is_reported_as_reaching_the_map(self):
        from ec7edit_core.engine_runner import SessionState

        engine = self.fake_engine(
            'echo "EC7EDIT s1 hello engine=Fake"\n'
            'echo "adding ./AUDIOT.CO7"\n'
            'echo "EC7EDIT s1 preview-load path=preview.wad loaded=yes lumps=9"\n'
            'echo "EC7EDIT s1 map-entry marker=MAP01 name=Lab"\n'
            'echo "EC7EDIT s1 session-result outcome=quit"\n'
            'exit 0\n')
        session = self.run_to_end(engine)
        self.assertIs(session.state, SessionState.FINISHED)
        self.assertTrue(session.reached_the_map)

    def test_a_silent_engine_is_reported_as_failed(self):
        # In the Test Log and the status bar, not a modal: this arrives on a
        # signal from a process ending, at any moment, including mid-gesture.
        from ec7edit_core.engine_runner import SessionState

        session = self.run_to_end(self.fake_engine("exit 1\n"))
        self.assertIs(session.state, SessionState.FAILED)
        self.assertIn("without answering",
                      self.window.test_log_status.text())

    def test_ordinary_output_reaches_the_test_log(self):
        engine = self.fake_engine('echo "Could not stat something.wad"\nexit 0\n')
        self.run_to_end(engine)
        shown = [self.window.test_log.item(i).text()
                 for i in range(self.window.test_log.count())]
        self.assertIn("Could not stat something.wad", shown)

    def test_stderr_is_captured_too(self):
        # "No player 1 start!" goes to stderr, and it is the failure an
        # editor-exported map hits most.
        engine = self.fake_engine('echo "No player 1 start!" >&2\nexit 1\n')
        self.window._error = lambda title, body: None
        session = self.run_to_end(engine)
        self.assertIn("No player 1 start!", session.log)

    def test_a_log_is_written_beside_the_session(self):
        engine = self.fake_engine('echo "EC7EDIT s1 hello x=1"\nexit 0\n')
        self.window._error = lambda title, body: None
        self.run_to_end(engine)
        log = self.root / "sess" / "playtest.log"
        self.assertTrue(log.exists())
        self.assertIn("# session s1", log.read_text())

    def test_two_playtests_at_once_are_refused(self):
        from PySide6.QtCore import QProcess

        engine = self.fake_engine("sleep 5\n")
        errors = []
        self.window._error = lambda title, body: errors.append(title)
        self.assertTrue(self.window.start_session(self.plan_for(engine), "A"))
        try:
            self.assertFalse(self.window.start_session(self.plan_for(engine, "s2"), "B"))
            self.assertTrue(errors)
        finally:
            self.window.stop_session()
        self.assertEqual(self.window.process.state(), QProcess.ProcessState.NotRunning)

    def test_stopping_ends_the_process(self):
        from PySide6.QtCore import QProcess

        engine = self.fake_engine("sleep 30\n")
        self.window.start_session(self.plan_for(engine), "LONG")
        self.assertTrue(self.window.stop_session())
        self.assertEqual(self.window.process.state(), QProcess.ProcessState.NotRunning)

    def test_a_running_playtest_is_not_orphaned_when_the_editor_closes(self):
        from PySide6.QtCore import QProcess

        engine = self.fake_engine("sleep 30\n")
        self.window.start_session(self.plan_for(engine), "LONG")
        self.assertTrue(self.window.reconcile_orphan())
        self.assertEqual(self.window.process.state(), QProcess.ProcessState.NotRunning)

    def test_reconciling_with_nothing_running_is_harmless(self):
        self.assertFalse(self.window.reconcile_orphan())

    def test_a_missing_engine_is_reported_rather_than_thrown(self):
        errors = []
        self.window._error = lambda title, body: errors.append(title)
        plan = self.plan_for(self.root / "not-here")
        self.assertFalse(self.window.start_session(plan, "X"))
        self.assertTrue(errors)

    def test_each_playtest_gets_its_own_session(self):
        # A stray counter reset made every launch after the first reuse
        # ec7edit-0001 -- the same nonce AND the same session directory, so two
        # playtests shared a config, a savedir and a log.
        first = self.window._next_session_id()
        engine = self.fake_engine('echo "EC7EDIT x hello y=1"\nexit 0\n')
        self.run_to_end(engine, session="s-a")
        self.run_to_end(engine, session="s-b")
        self.assertNotEqual(self.window._next_session_id(), first)

    def test_stopping_on_purpose_is_not_reported_as_a_crash(self):
        from ec7edit_core.engine_runner import SessionState

        engine = self.fake_engine("sleep 30\n")
        self.window.start_session(self.plan_for(engine), "LONG")
        self.window.stop_session()
        QApplication.processEvents()
        self.assertIsNot(self.window.session.state, SessionState.FINISHED)
        self.assertNotIn("exited with code", self.window.session.failure)
        self.assertIn("stopped", self.window.session.failure)

    def test_an_orphan_is_stopped_after_the_engine_says_it_is_done(self):
        # The engine says session-result on its way out and then keeps running
        # for a while. Anything that took that as "the process is gone" would
        # leave a live engine behind -- which is the orphan itself. Liveness is
        # asked of the process, never of the session.
        from PySide6.QtCore import QProcess

        engine = self.fake_engine(
            'echo "EC7EDIT s1 session-result outcome=quit"\nsleep 30\n')
        self.window.start_session(self.plan_for(engine), "LATE")
        for _ in range(50):
            QApplication.processEvents()
            if self.window.session.events:
                break
            self.window.process.waitForReadyRead(100)
        self.assertTrue(self.window.session.events, "the engine never reported")
        self.assertTrue(self.window.reconcile_orphan(), "a live engine was not stopped")
        self.assertEqual(self.window.process.state(), QProcess.ProcessState.NotRunning)

    def test_a_crash_after_session_result_is_not_a_success(self):
        # The verdict waits for the process. Freezing it on session-result
        # reported a crash on the way out as a clean finish.
        from ec7edit_core.engine_runner import SessionState

        engine = self.fake_engine(
            'echo "EC7EDIT s1 hello x=1"\n'
            'echo "EC7EDIT s1 preview-load path=preview.wad loaded=yes lumps=9"\n'
            'echo "EC7EDIT s1 map-entry marker=MAP01 name=Lab"\n'
            'echo "EC7EDIT s1 session-result outcome=quit"\n'
            'exit 3\n')
        session = self.run_to_end(engine)
        self.assertIs(session.state, SessionState.FAILED)
        self.assertIn("exited with code 3", session.failure)

    def test_a_second_playtest_cannot_start_over_a_live_one(self):
        engine = self.fake_engine(
            'echo "EC7EDIT s1 session-result outcome=quit"\nsleep 30\n')
        errors = []
        self.window._error = lambda title, body: errors.append(title)
        self.window.start_session(self.plan_for(engine), "A")
        for _ in range(50):
            QApplication.processEvents()
            if self.window.session.events:
                break
            self.window.process.waitForReadyRead(100)
        try:
            self.assertFalse(self.window.start_session(self.plan_for(engine, "s2"), "B"))
            self.assertTrue(errors)
        finally:
            self.window.reconcile_orphan()

    def test_relaunching_after_one_finishes_works(self):
        from ec7edit_core.engine_runner import SessionState

        engine = self.fake_engine(
            'echo "EC7EDIT s1 hello x=1"\n'
            'echo "EC7EDIT s1 preview-load path=preview.wad loaded=yes lumps=9"\n'
            'echo "EC7EDIT s1 map-entry marker=MAP01 name=Lab"\n'
            'echo "EC7EDIT s1 session-result outcome=quit"\nexit 0\n')
        self.assertIs(self.run_to_end(engine).state, SessionState.FINISHED)
        self.assertIs(self.run_to_end(engine).state, SessionState.FINISHED)

    def test_the_panel_log_is_bounded_too(self):
        from ec7edit_core.engine_runner import Session

        engine = self.fake_engine(
            f'i=0; while [ $i -lt {Session.LOG_LIMIT + 200} ]; do echo "line $i"; '
            'i=$((i+1)); done\nexit 0\n')
        self.run_to_end(engine, timeout=20000)
        self.assertLessEqual(len(self.window._session_lines), Session.LOG_LIMIT)
