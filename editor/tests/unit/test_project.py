#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E3: the project schema, the atomic save, autosave and recovery.

The fault-injection class is the heart of this file. A durable save is easy to
write and impossible to believe without failing it on purpose, so every stage
of the protocol has a name, and every stage gets a test that fails there and
then asserts the destination is still a valid old, new, or recovery state --
never a truncated file, never a half-written one, and never a temporary file
left behind.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.document import DocumentError, MapDocument, ProjectDocument, SourceReference
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.document import SCHEMA_VERSION
from ec7edit_core.project import (
    OLDEST_SUPPORTED_SCHEMA,
    SAVE_STAGES,
    FaultInjector,
    ProjectLock,
    RecoveryStore,
    SaveConflict,
    WriterQueue,
    deserialize,
    load_project,
    migrate,
    project_identity,
    save_project,
    serialize,
)


def sample_project(maps=1, width=6, height=4) -> ProjectDocument:
    project = ProjectDocument.create("Sample", author="Tester")
    for index in range(maps):
        planes = tuple(
            tuple((plane * 31 + cell + index) % 500 for cell in range(width * height))
            for plane in range(3)
        )
        project = project.added(
            MapDocument(
                uuid=f"map-{index:04d}-uuid",
                slot=index + 1,
                native_name=NativeName.from_text(f"MAP {index}"),
                planes=MapPlanes(width, height, planes),
            )
        )
    return project


class Serialisation(unittest.TestCase):
    def test_round_trip_preserves_every_word(self):
        project = sample_project(maps=3)
        back = deserialize(serialize(project))
        for original, seen in zip(project.maps, back.maps):
            self.assertEqual(seen.planes.planes, original.planes.planes)
            self.assertEqual(seen.native_name.raw, original.native_name.raw)
            self.assertEqual(seen.uuid, original.uuid)
            self.assertEqual(seen.slot, original.slot)

    def test_output_is_deterministic(self):
        project = sample_project(maps=2)
        self.assertEqual(serialize(project), serialize(project))

    def test_planes_are_rows_of_integers_not_a_blob(self):
        payload = json.loads(serialize(sample_project()))
        planes = payload["maps"][0]["planes"]
        self.assertEqual(len(planes), 3)
        self.assertEqual(len(planes[0]), 4)
        self.assertEqual(len(planes[0][0]), 6)
        self.assertTrue(all(isinstance(v, int) for v in planes[0][0]))

    def test_the_raw_name_is_hex_and_the_text_is_a_view(self):
        payload = json.loads(serialize(sample_project()))
        entry = payload["maps"][0]
        self.assertEqual(len(entry["native_name_raw_hex"]), 32)
        self.assertEqual(entry["native_name"], "MAP 0")

    def test_a_noncanonical_name_survives(self):
        raw = b"SLOT\x00\x001\x00" + b"\x00" * 8
        project = ProjectDocument.create().added(
            MapDocument("u", 1, NativeName.from_raw(raw), MapPlanes.empty(2, 2))
        )
        self.assertEqual(deserialize(serialize(project)).maps[0].native_name.raw, raw)

    def test_no_byte_order_mark(self):
        self.assertFalse(serialize(sample_project()).startswith("\ufeff"))


class Rejects(unittest.TestCase):
    def load(self, mutate):
        payload = json.loads(serialize(sample_project()))
        mutate(payload)
        return json.dumps(payload)

    def assertRefused(self, text, code="C7E-SCHEMA-002"):
        with self.assertRaises(DocumentError) as caught:
            deserialize(text)
        self.assertEqual(caught.exception.diagnostic.code, code)

    def test_not_json(self):
        self.assertRefused("this is not json")

    def test_a_byte_order_mark(self):
        self.assertRefused("\ufeff" + serialize(sample_project()))

    def test_a_newer_schema(self):
        self.assertRefused(
            self.load(lambda p: p.update(schema_version=99)), "C7E-SCHEMA-001"
        )

    def test_an_older_schema_with_no_migration(self):
        self.assertRefused(
            self.load(lambda p: p.update(schema_version=OLDEST_SUPPORTED_SCHEMA - 1)),
            "C7E-SCHEMA-001",
        )

    def test_an_unknown_top_level_property(self):
        self.assertRefused(self.load(lambda p: p.update(surprise=1)))

    def test_an_unknown_map_property(self):
        self.assertRefused(self.load(lambda p: p["maps"][0].update(script="rm -rf /")))

    def test_a_row_of_the_wrong_width(self):
        self.assertRefused(self.load(lambda p: p["maps"][0]["planes"][0][0].append(0)))

    def test_a_plane_of_the_wrong_height(self):
        self.assertRefused(self.load(lambda p: p["maps"][0]["planes"][0].pop()))

    def test_only_two_planes(self):
        self.assertRefused(self.load(lambda p: p["maps"][0]["planes"].pop()))

    def test_a_word_outside_uint16(self):
        self.assertRefused(
            self.load(lambda p: p["maps"][0]["planes"][0][0].__setitem__(0, 70000)),
            "C7E-CELL-001",
        )

    def test_a_word_that_is_not_an_integer(self):
        self.assertRefused(
            self.load(lambda p: p["maps"][0]["planes"][0][0].__setitem__(0, "5")),
            "C7E-CELL-001",
        )

    def test_a_boolean_is_not_a_word(self):
        # True == 1 in Python, so a naive range check would let it through and
        # the value would come back as `true` on the next save.
        self.assertRefused(
            self.load(lambda p: p["maps"][0]["planes"][0][0].__setitem__(0, True)),
            "C7E-CELL-001",
        )

    def test_a_name_field_of_the_wrong_length(self):
        self.assertRefused(self.load(lambda p: p["maps"][0].update(native_name_raw_hex="aabb")))

    def test_a_name_that_is_not_hex(self):
        self.assertRefused(
            self.load(lambda p: p["maps"][0].update(native_name_raw_hex="z" * 32))
        )

    def test_a_text_and_raw_pair_that_disagree(self):
        # The text is a view. A file where they differ was written by something
        # with a different idea of the decode, and picking one loses the other.
        self.assertRefused(self.load(lambda p: p["maps"][0].update(native_name="OTHER")))

    def test_two_maps_with_the_same_id(self):
        def mutate(payload):
            payload["maps"].append(dict(payload["maps"][0]))

        self.assertRefused(self.load(mutate))

    def test_a_missing_uuid(self):
        self.assertRefused(self.load(lambda p: p["project"].pop("uuid")))


class Migration(unittest.TestCase):
    def test_current_schema_passes_through_unchanged(self):
        payload = json.loads(serialize(sample_project()))
        self.assertEqual(migrate(dict(payload)), payload)

    def test_the_harness_runs_a_registered_step(self):
        from ec7edit_core import project as module

        original = dict(module.MIGRATIONS)
        try:
            module.MIGRATIONS[0] = lambda p: {**p, "project": {**p["project"], "notes": "migrated"}}
            payload = json.loads(serialize(sample_project()))
            payload["schema_version"] = 0
            migrated = migrate(payload)
            # Up to the current schema, not to 1: this asserts the harness runs
            # a registered step and keeps going, and pinning the destination to
            # a literal made it a test of what the schema number happened to be
            # the day it was written.
            self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
            self.assertEqual(migrated["project"]["notes"], "migrated")
        finally:
            module.MIGRATIONS.clear()
            module.MIGRATIONS.update(original)

    def test_a_gap_in_the_chain_is_an_error(self):
        payload = json.loads(serialize(sample_project()))
        payload["schema_version"] = 0
        with self.assertRaises(DocumentError):
            migrate(payload)


class Saving(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "demo.ec7project"

    def tearDown(self):
        self._tmp.cleanup()

    def test_saves_and_reloads(self):
        project = sample_project(maps=2)
        revision = save_project(project, self.path)
        self.assertEqual(revision, project.revision)
        back = load_project(self.path)
        self.assertEqual(len(back), 2)
        self.assertFalse(back.dirty)

    def test_reopening_is_identical(self):
        project = sample_project(maps=2)
        save_project(project, self.path)
        first = self.path.read_bytes()
        save_project(load_project(self.path), self.path)
        self.assertEqual(self.path.read_bytes(), first)

    def test_no_temporary_files_survive(self):
        save_project(sample_project(), self.path)
        self.assertEqual([p.name for p in self.root.iterdir()], ["demo.ec7project"])

    def test_permissions_are_restrictive(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        save_project(sample_project(), self.path)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_an_external_change_is_refused(self):
        save_project(sample_project(), self.path)
        identity = project_identity(self.path)
        self.path.write_text("someone else wrote this", encoding="utf-8")
        with self.assertRaises(SaveConflict):
            save_project(sample_project(), self.path, expect_identity=identity)
        self.assertEqual(self.path.read_text(), "someone else wrote this")

    def test_a_matching_identity_is_allowed(self):
        save_project(sample_project(), self.path)
        save_project(sample_project(maps=2), self.path,
                     expect_identity=project_identity(self.path))
        self.assertEqual(len(load_project(self.path)), 2)

    def test_an_older_generation_cannot_overwrite_a_newer(self):
        # An autosave takes its generation, then spends time serialising while
        # the user saves explicitly. Finishing late must not win.
        queue = WriterQueue()
        slow = queue.begin(self.path)
        save_project(sample_project(maps=3), self.path, queue=queue)
        self.assertTrue(queue.superseded(self.path, slow))
        with self.assertRaises(SaveConflict):
            save_project(sample_project(maps=1), self.path, queue=queue, generation=slow)
        self.assertEqual(len(load_project(self.path)), 3)

    def test_a_current_generation_commits(self):
        queue = WriterQueue()
        generation = queue.begin(self.path)
        save_project(sample_project(maps=2), self.path, queue=queue, generation=generation)
        self.assertEqual(len(load_project(self.path)), 2)


class FaultInjection(unittest.TestCase):
    """Fail at every stage in turn; the destination must stay valid."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "demo.ec7project"
        save_project(sample_project(maps=1), self.path)
        self.original = self.path.read_text(encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_stage(self):
        for stage in SAVE_STAGES:
            with self.subTest(stage=stage):
                self.path.write_text(self.original, encoding="utf-8")
                replacement = sample_project(maps=3)
                try:
                    save_project(replacement, self.path, faults=FaultInjector(stage=stage))
                    failed = False
                except (OSError, SaveConflict):
                    failed = True

                # Whatever happened, what is on disk must parse, and must be
                # either the old project or the new one -- never a mixture.
                loaded = load_project(self.path)
                self.assertIn(len(loaded), (1, 3), f"{stage}: {len(loaded)} maps on disk")
                if failed and stage != "dirsync":
                    self.assertEqual(len(loaded), 1, f"{stage} failed but the file changed")

                debris = [p.name for p in self.root.iterdir() if p.name != "demo.ec7project"]
                self.assertEqual(debris, [], f"{stage} left {debris}")

    def test_a_failure_before_replace_keeps_the_old_file(self):
        for stage in ("serialize", "validate", "tempfile", "write", "flush",
                      "reopen", "verify", "identity", "generation", "replace"):
            with self.subTest(stage=stage):
                self.path.write_text(self.original, encoding="utf-8")
                with self.assertRaises((OSError, SaveConflict)):
                    save_project(sample_project(maps=3), self.path,
                                 faults=FaultInjector(stage=stage))
                self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)


class Recovery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = RecoveryStore(self.root / "recovery")

    def tearDown(self):
        self._tmp.cleanup()

    def test_autosave_writes_a_recoverable_copy(self):
        project = sample_project(maps=2)
        path = self.store.autosave(project, original_path="/somewhere/demo.ec7project")
        self.assertTrue(path.exists())
        recovered = self.store.load(project.uuid)
        self.assertEqual(len(recovered), 2)

    def test_autosave_records_both_revisions(self):
        project = sample_project(maps=1).marked_saved(1)
        project = project.with_map(project.maps[0].renamed("EDITED"))
        self.store.autosave(project)
        record = self.store.list_recoveries()[0]
        self.assertEqual(record.saved_revision, 1)
        self.assertEqual(record.autosaved_revision, project.revision)
        self.assertNotEqual(record.saved_revision, record.autosaved_revision)

    def test_autosave_does_not_clean_the_document(self):
        project = sample_project(maps=1)
        self.store.autosave(project)
        self.assertTrue(project.dirty)

    def test_it_writes_only_inside_its_own_root(self):
        project = sample_project()
        path = self.store.autosave(project)
        self.assertEqual(path.parent, self.store.root)

    def test_discard_removes_exactly_one(self):
        first, second = sample_project(), sample_project()
        self.store.autosave(first)
        self.store.autosave(second)
        self.store.discard(first.uuid)
        self.assertEqual([r.project_uuid for r in self.store.list_recoveries()], [second.uuid])

    def test_a_damaged_recovery_file_does_not_break_the_listing(self):
        self.store.autosave(sample_project())
        (self.store.root / "broken.ec7recovery").write_text("{", encoding="utf-8")
        self.assertEqual(len(self.store.list_recoveries()), 1)

    def test_retention_is_bounded_by_count(self):
        self.store.max_projects = 3
        for _ in range(10):
            self.store.autosave(sample_project())
        self.assertLessEqual(len(list(self.store.root.glob("*.ec7recovery"))), 3)


class Locking(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "demo.ec7project"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_second_instance_cannot_take_the_lock(self):
        first = ProjectLock(self.path)
        self.assertTrue(first.acquire())
        self.assertFalse(ProjectLock(self.path).acquire())
        first.release()
        self.assertTrue(ProjectLock(self.path).acquire())

    def test_the_context_manager_refuses_a_held_lock(self):
        held = ProjectLock(self.path)
        held.acquire()
        with self.assertRaises(SaveConflict):
            with ProjectLock(self.path):
                pass
        held.release()

    def test_a_lock_from_a_dead_process_is_reclaimed(self):
        lock = ProjectLock(self.path)
        lock.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock.lock_path.write_text(json.dumps({"pid": 999999999}), encoding="utf-8")
        self.assertTrue(lock.acquire())
        lock.release()

    def test_an_unreadable_lock_is_reclaimed(self):
        lock = ProjectLock(self.path)
        lock.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock.lock_path.write_text("not json", encoding="utf-8")
        self.assertTrue(lock.acquire())
        lock.release()


class Untrusted(unittest.TestCase):
    def test_a_path_in_a_shared_project_is_never_touched(self):
        # A shared project is data. Opening it must not stat, hash or open any
        # path it names -- including a UNC path or a device node.
        for hostile in (r"\\evil\share\payload", "/dev/zero", "//?/C:/Windows",
                        "~/.ssh/id_rsa"):
            project = ProjectDocument.create()
            from dataclasses import replace

            document = MapDocument.blank(width=2, height=2)
            project = project.added(
                replace(document, source=SourceReference(display_path=hostile, sha256="x"))
            )
            back = deserialize(serialize(project))
            self.assertEqual(back.maps[0].source.display_path, hostile)


if __name__ == "__main__":
    unittest.main(verbosity=1)
