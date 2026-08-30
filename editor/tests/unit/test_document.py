#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E3: the document model, its identity rules and its revision counting."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.archive import MapRecord
from ec7edit_core.document import (
    DocumentError,
    MapDocument,
    ProjectDocument,
    SourceReference,
    new_uuid,
)
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes


class Identity(unittest.TestCase):
    def test_every_map_gets_its_own_uuid(self):
        first, second = MapDocument.blank(), MapDocument.blank()
        self.assertNotEqual(first.uuid, second.uuid)

    def test_a_uuid_survives_a_rename(self):
        document = MapDocument.blank(name="OLD")
        self.assertEqual(document.renamed("NEW").uuid, document.uuid)

    def test_a_uuid_survives_a_slot_change(self):
        from dataclasses import replace

        document = MapDocument.blank(slot=1)
        self.assertEqual(replace(document, slot=40).uuid, document.uuid)

    def test_position_is_not_identity(self):
        # Reordering must not change which map is which; an editor that used
        # archive position would lose every annotation on a reorder.
        first, second = MapDocument.blank(slot=1), MapDocument.blank(slot=2)
        project = ProjectDocument.create().added(first).added(second)
        reordered = project.with_maps([second, first])
        self.assertEqual(reordered.map_by_uuid(first.uuid).uuid, first.uuid)

    def test_a_slot_outside_the_engines_range_is_refused(self):
        for slot in (0, 101, -1):
            with self.assertRaises(DocumentError):
                MapDocument.blank(slot=slot)


class Names(unittest.TestCase):
    def test_display_name_is_a_view_over_the_raw_field(self):
        raw = b"LOBBY\x00\x00\x01" + b"\x00" * 8
        document = MapDocument(new_uuid(), 1, NativeName.from_raw(raw), MapPlanes.empty(2, 2))
        self.assertEqual(document.name, "LOBBY")
        self.assertEqual(document.native_name.raw, raw)

    def test_renaming_replaces_the_whole_field(self):
        raw = b"OLD\x00\x00\x99" + b"\x00" * 10
        document = MapDocument(new_uuid(), 1, NativeName.from_raw(raw), MapPlanes.empty(2, 2))
        renamed = document.renamed("NEW")
        self.assertEqual(renamed.native_name.raw, b"NEW" + b"\x00" * 13)
        self.assertNotIn(0x99, renamed.native_name.raw)


class Revisions(unittest.TestCase):
    def test_a_new_project_is_clean(self):
        self.assertFalse(ProjectDocument.create().dirty)

    def test_adding_a_map_dirties_it(self):
        self.assertTrue(ProjectDocument.create().added(MapDocument.blank()).dirty)

    def test_marking_saved_cleans_it(self):
        project = ProjectDocument.create().added(MapDocument.blank())
        self.assertFalse(project.marked_saved(project.revision).dirty)

    def test_an_edit_during_a_save_leaves_it_dirty(self):
        # The save captured revision 1; revision 2 happened while it was in
        # flight, so the document on disk is not the document in memory.
        project = ProjectDocument.create().added(MapDocument.blank())
        in_flight = project.revision
        project = project.with_map(project.maps[0].renamed("EDITED"))
        self.assertTrue(project.marked_saved(in_flight).dirty)

    def test_the_saved_marker_never_moves_backwards(self):
        project = ProjectDocument.create().added(MapDocument.blank())
        project = project.marked_saved(1)
        project = project.with_map(project.maps[0].renamed("A"))
        self.assertEqual(project.marked_saved(1).saved_revision, 1)

    def test_cannot_claim_to_have_saved_the_future(self):
        project = ProjectDocument.create()
        with self.assertRaises(DocumentError):
            project.marked_saved(project.revision + 5)


class Structure(unittest.TestCase):
    def test_lookup_by_uuid(self):
        document = MapDocument.blank()
        project = ProjectDocument.create().added(document)
        self.assertEqual(project.map_by_uuid(document.uuid).uuid, document.uuid)

    def test_lookup_of_an_absent_map_is_an_error(self):
        with self.assertRaises(DocumentError):
            ProjectDocument.create().map_by_uuid("nope")

    def test_a_map_cannot_be_added_twice(self):
        document = MapDocument.blank()
        with self.assertRaises(DocumentError):
            ProjectDocument.create().added(document).added(document)

    def test_removal(self):
        document = MapDocument.blank()
        project = ProjectDocument.create().added(document).removed(document.uuid)
        self.assertEqual(len(project), 0)

    def test_documents_are_immutable(self):
        project = ProjectDocument.create().added(MapDocument.blank())
        with self.assertRaises(Exception):
            project.maps[0].slot = 9


class NewRoom(unittest.TestCase):
    """`new_room` is walled with an empty object plane; `blank` is all zeros."""

    def test_blank_really_is_blank(self):
        document = MapDocument.blank(width=6, height=6)
        for plane in range(3):
            self.assertTrue(all(v == 0 for v in document.planes.planes[plane]))

    def test_a_room_is_walled(self):
        document = MapDocument.new_room(width=10, height=8)
        for x in range(10):
            self.assertEqual(document.cell(0, x, 0), MapDocument.SOLID_WALL)
            self.assertEqual(document.cell(0, x, 7), MapDocument.SOLID_WALL)
        for y in range(8):
            self.assertEqual(document.cell(0, 0, y), MapDocument.SOLID_WALL)
            self.assertEqual(document.cell(0, 9, y), MapDocument.SOLID_WALL)

    def test_the_middle_is_open(self):
        self.assertEqual(MapDocument.new_room(width=10, height=8).cell(0, 5, 4), 0)

    def test_the_object_plane_is_the_empty_marker(self):
        # Zero is a word that means something; 18 is the one that means nothing.
        document = MapDocument.new_room(width=6, height=6)
        self.assertTrue(all(v == MapDocument.EMPTY_OBJECT
                            for v in document.planes.planes[1]))

    def test_plane_two_starts_at_zero(self):
        document = MapDocument.new_room(width=6, height=6)
        self.assertTrue(all(v == 0 for v in document.planes.planes[2]))

    def test_the_two_constructors_differ(self):
        self.assertNotEqual(MapDocument.blank(width=6, height=6).planes.planes,
                            MapDocument.new_room(width=6, height=6).planes.planes)


class Interop(unittest.TestCase):
    def test_import_from_a_record_keeps_the_exact_name_bytes(self):
        raw = b"SLOT\x00\x001\x00" + b"\x00" * 8
        record = MapRecord(7, NativeName.from_raw(raw), MapPlanes.empty(4, 4))
        document = MapDocument.from_record(record)
        self.assertEqual(document.native_name.raw, raw)
        self.assertEqual(document.slot, 7)

    def test_export_to_a_record_round_trips(self):
        document = MapDocument.blank(slot=12, name="EXPORT", width=4, height=4)
        record = document.to_record()
        self.assertEqual(record.number, 12)
        self.assertEqual(record.name.raw, document.native_name.raw)
        self.assertEqual(record.planes.planes, document.planes.planes)

    def test_a_source_reference_is_inert(self):
        # Nothing here may touch the filesystem: a shared project's path is a
        # string, and opening the project must not act on it.
        source = SourceReference(display_path="/does/not/exist/MAPTEMP.CO7", sha256="abc")
        document = MapDocument.blank()
        from dataclasses import replace

        self.assertEqual(replace(document, source=source).source.display_path,
                         "/does/not/exist/MAPTEMP.CO7")
        self.assertTrue(source.identified)


if __name__ == "__main__":
    unittest.main(verbosity=1)
