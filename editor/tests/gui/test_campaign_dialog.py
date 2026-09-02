#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E11: the campaign dialog, and the pack export behind it.

Driven on the offscreen platform against real widgets. The dialog's whole job
is to be a view over `campaign.validate` -- so what is tested is that the view
and the validator cannot disagree: what the table says round-trips, OK follows
the errors, and a build refuses exactly what the validator refuses.

Nothing here needs Corridor 7. Every map is drawn by the test.
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

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ec7edit_core.campaign import Campaign, CampaignEntry, Route, audit_pack
from ec7edit_core.document import MapDocument, ProjectDocument, SourceReference
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes

from ec7edit_gui.application import build_application
from ec7edit_gui.campaign_dialog import END, CampaignDialog
from ec7edit_gui.main_window import MainWindow
from ec7edit_gui.settings import Settings

_application = build_application([])


def a_map(slot: int, *, source=None) -> MapDocument:
    width = height = 8
    walls = [1] * (width * height)
    objects = [0] * (width * height)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            walls[y * width + x] = 256
    objects[1 * width + 1] = 19
    return MapDocument(
        uuid=f"uuid-{slot}", slot=slot, native_name=NativeName.from_text(f"M{slot}"),
        planes=MapPlanes(width, height,
                         (tuple(walls), tuple(objects), tuple([0] * (width * height)))),
        source=source,
    )


def a_project(slots=(61, 62)) -> ProjectDocument:
    project = ProjectDocument.create("Pack")
    for slot in slots:
        project = project.added(a_map(slot))
    return project


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        backend = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        self.settings = Settings(backend)
        self.settings.recovery_dir = self.root / "recovery"
        self.window = MainWindow(self.settings)
        self.window.project = a_project()

    def tearDown(self):
        self.window.project = self.window.project.marked_saved(
            self.window.project.revision)
        self.window.pool.cancel_all()
        self.window.pool.wait(2000)
        self.window.close()
        self.window.deleteLater()
        QApplication.processEvents()
        self._tmp.cleanup()


class Dialog(Base):
    def open(self, campaign=None):
        return CampaignDialog(campaign or Campaign(), self.window.project.maps)

    def test_an_empty_campaign_is_offered_the_project_maps(self):
        dialog = self.open()
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual([e.slot for e in dialog.campaign().entries], [61, 62])

    def test_the_offered_default_can_be_finished(self):
        # The rows a fresh dialog proposes must not themselves be an error, or
        # the first thing an author sees is a red panel they did not cause.
        dialog = self.open()
        self.assertTrue(dialog.ok.isEnabled())
        self.assertIn("ready", dialog.problems.text())

    def test_the_table_round_trips(self):
        campaign = Campaign(title="Trial", key="T", entries=(
            CampaignEntry(61, "One", next=Route(62), secret=Route(None),
                          music="C7MUS07", par=45, intermission=False),
            CampaignEntry(62, "Two", next=Route(None)),
        ))
        self.assertEqual(self.open(campaign).campaign(), campaign)

    def test_the_first_row_is_the_start_and_moving_changes_it(self):
        dialog = self.open()
        self.assertIn("MAP61", dialog.start.text())
        dialog.table.setCurrentCell(1, 0)
        dialog._move(-1)
        self.assertEqual(dialog.campaign().start, 62)
        self.assertIn("MAP62", dialog.start.text())

    def test_moving_a_row_keeps_its_values(self):
        # Reordering rebuilds both rows; a swap that lost a name or a route
        # would be the kind of bug nobody notices until the pack is built.
        campaign = Campaign(title="T", key="T", entries=(
            CampaignEntry(61, "First", next=Route(62), music="C7MUS07"),
            CampaignEntry(62, "Second", next=Route(None), par=30),
        ))
        dialog = self.open(campaign)
        dialog.table.setCurrentCell(0, 0)
        dialog._move(1)
        moved = dialog.campaign().entries
        self.assertEqual([e.name for e in moved], ["Second", "First"])
        self.assertEqual(moved[0].par, 30)
        self.assertEqual(moved[1].music, "C7MUS07")

    def test_ok_follows_the_errors(self):
        broken = Campaign(title="T", key="T", entries=(
            CampaignEntry(61, "One", next=Route(61)),   # a loop, never finishes
        ))
        dialog = self.open(broken)
        self.assertFalse(dialog.ok.isEnabled())
        self.assertIn("error", dialog.problems.text())

    def test_a_warning_does_not_block_ok(self):
        # "This slot replaces a stock level" is a thing an author may mean.
        self.window.project = a_project(slots=(1, 2))
        dialog = CampaignDialog(Campaign(), self.window.project.maps)
        self.assertTrue(dialog.ok.isEnabled())
        self.assertIn("warning", dialog.problems.text())

    def test_the_end_choice_is_not_a_slot(self):
        dialog = self.open()
        box = dialog.table.cellWidget(1, 2)
        self.assertEqual(box.itemData(0), END)
        self.assertNotIn(END, [e.slot for e in dialog.campaign().entries])

    def test_a_removed_row_is_gone_from_the_campaign(self):
        dialog = self.open()
        dialog.table.setCurrentCell(1, 0)
        dialog._remove_level()
        self.assertEqual([e.slot for e in dialog.campaign().entries], [61])


class Export(Base):
    def test_a_pack_needs_a_campaign(self):
        errors = []
        self.window._error = lambda title, detail: errors.append(title)
        self.assertFalse(self.window.export_pack())
        self.assertEqual(errors, ["There is no campaign yet"])

    def test_a_retail_map_is_refused_before_any_file_is_written(self):
        source = SourceReference(display_path="MAPTEMP.CO7", sha256="b" * 64,
                                 map_number=1, imported_at="2026-01-01T00:00:00Z")
        project = ProjectDocument.create("Pack").added(a_map(61, source=source))
        campaign = Campaign(title="T", key="T", entries=(
            CampaignEntry(61, "One", next=Route(None)),))
        self.window.project = project.with_campaign(campaign.to_json())

        shown = []
        self.window._error = lambda title, detail: shown.append(detail)
        self.assertFalse(self.window.export_pack())
        self.assertTrue(any("C7E-PACK-009" in text for text in shown), shown)
        self.assertEqual(list(self.root.glob("*.wad")), [])

    def test_a_written_pack_passes_its_own_audit(self):
        campaign = Campaign(title="Trial", key="T", entries=(
            CampaignEntry(61, "One", next=Route(62)),
            CampaignEntry(62, "Two", next=Route(None)),
        ))
        self.window.project = self.window.project.with_campaign(campaign.to_json())
        destination = self.root / "trial.wad"

        import ec7edit_gui.main_window as module
        original = module.QFileDialog.getSaveFileName
        module.QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (str(destination), ""))
        try:
            self.assertTrue(self.window.export_pack())
        finally:
            module.QFileDialog.getSaveFileName = original

        report = audit_pack(destination.read_bytes())
        self.assertTrue(report.clean)
        self.assertEqual(report.markers, ("MAP61", "MAP62"))
        # The manifest travels with it, asked for or not.
        self.assertTrue((self.root / "trial.txt").is_file())
        self.assertIn("Corridor 7", (self.root / "trial.txt").read_text())


class ProjectState(Base):
    def test_a_campaign_is_an_edit_and_survives_a_save(self):
        from ec7edit_core.project import load_project, save_project

        campaign = Campaign(title="Trial", key="T", entries=(
            CampaignEntry(61, "One", next=Route(None)),))
        before = self.window.project.revision
        self.window.project = self.window.project.with_campaign(campaign.to_json())
        self.assertGreater(self.window.project.revision, before)
        self.assertTrue(self.window.project.dirty)

        path = self.root / "p.ec7project"
        save_project(self.window.project, path)
        again = Campaign.from_json(load_project(path).campaign)
        self.assertEqual(again, campaign)


if __name__ == "__main__":
    unittest.main()
