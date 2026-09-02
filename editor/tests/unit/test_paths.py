#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E1: source protection, atomic output, and readback.

The retail archive belongs to the user and this project has no right to write
to it, so the interesting cases are all the ways a path can turn out to be the
source after all -- a different spelling, a symlink, a hard link -- plus the
guarantee that a write that reports success actually landed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.errors import ExportError
from ec7edit_core.paths import (
    OutputGuard,
    SourceIdentity,
    atomic_write,
    canonical,
    digest_file,
    same_file,
)


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.source = self.data / "MAPTEMP.CO7"
        self.source.write_bytes(b"retail bytes, not ours")
        self.work = self.root / "work"
        self.work.mkdir()
        self.guard = OutputGuard.for_source(self.source)

    def tearDown(self):
        self._tmp.cleanup()

    def assertRefused(self, path, code):
        with self.assertRaises(ExportError) as caught:
            self.guard.check(path)
        self.assertEqual(caught.exception.diagnostic.code, code)


class RefusesToWriteTheSource(Fixture):
    def test_the_source_itself(self):
        self.assertRefused(self.source, "C7E-SOURCE-002")

    def test_a_different_spelling_of_it(self):
        self.assertRefused(self.data / "." / "MAPTEMP.CO7", "C7E-SOURCE-002")
        self.assertRefused(self.data / "sub" / ".." / "MAPTEMP.CO7", "C7E-SOURCE-002")

    def test_a_symlink_to_it(self):
        link = self.work / "alias.co7"
        link.symlink_to(self.source)
        self.assertRefused(link, "C7E-SOURCE-002")

    def test_a_hard_link_to_it(self):
        # No amount of string normalization finds this one; it needs the inode.
        link = self.work / "hard.co7"
        os.link(self.source, link)
        self.assertRefused(link, "C7E-SOURCE-002")

    def test_anything_in_a_game_data_directory(self):
        # The fixture's source is MAPTEMP.CO7, so its directory is game data.
        self.assertRefused(self.data / "new.wad", "C7E-EXPORT-001")

    def test_a_subdirectory_of_a_protected_root(self):
        self.assertRefused(self.data / "deep" / "new.wad", "C7E-EXPORT-001")

    def test_a_symlinked_directory_into_the_protected_root(self):
        link = self.work / "shortcut"
        link.symlink_to(self.data)
        self.assertRefused(link / "new.wad", "C7E-EXPORT-001")

    def test_a_directory_that_is_not_game_data_is_writable(self):
        # Protecting every source's parent was the first version of this rule,
        # and it refused to write a project into the user's own directory
        # because a scratch archive happened to be there too.
        scratch = self.work / "scratch"
        scratch.mkdir()
        source = scratch / "notes.c7map"
        source.write_bytes(b"synthetic")
        guard = OutputGuard.for_source(source)
        self.assertEqual(guard.check(scratch / "project.ec7project"),
                         canonical(scratch / "project.ec7project"))
        # The source itself is still protected, however it is spelled.
        with self.assertRaises(ExportError):
            guard.check(scratch / "." / "notes.c7map")

    def test_game_data_is_recognized_by_its_own_files(self):
        from ec7edit_core.paths import looks_like_game_data

        plain = self.work / "plain"
        plain.mkdir()
        self.assertFalse(looks_like_game_data(plain))
        (plain / "VGAGRAPH.CO7").write_bytes(b"x")
        self.assertTrue(looks_like_game_data(plain))

    def test_the_executable_alone_is_enough(self):
        from ec7edit_core.paths import looks_like_game_data

        directory = self.work / "exe-only"
        directory.mkdir()
        (directory / "CORR7CD.EXE").write_bytes(b"x")
        self.assertTrue(looks_like_game_data(directory))

    def test_an_extra_protected_root(self):
        guard = OutputGuard.for_source(self.source, extra_roots=[self.work])
        with self.assertRaises(ExportError) as caught:
            guard.check(self.work / "out.wad")
        self.assertEqual(caught.exception.diagnostic.code, "C7E-EXPORT-001")

    def test_a_safe_path_is_allowed_and_canonicalised(self):
        self.assertEqual(self.guard.check(self.work / "out.wad"), canonical(self.work / "out.wad"))


class AtomicWrite(Fixture):
    def test_writes_and_reads_back(self):
        target = atomic_write(self.work / "out.bin", b"payload", guard=self.guard)
        self.assertEqual(target.read_bytes(), b"payload")

    def test_creates_missing_directories(self):
        target = atomic_write(self.work / "a" / "b" / "out.bin", b"x", guard=self.guard)
        self.assertTrue(target.exists())

    def test_leaves_no_temporary_files_behind(self):
        atomic_write(self.work / "out.bin", b"payload", guard=self.guard)
        self.assertEqual([p.name for p in self.work.iterdir()], ["out.bin"])

    def test_replaces_an_existing_file_completely(self):
        target = self.work / "out.bin"
        target.write_bytes(b"a much longer previous version")
        atomic_write(target, b"short", guard=self.guard)
        self.assertEqual(target.read_bytes(), b"short")

    def test_refuses_a_guarded_destination(self):
        with self.assertRaises(ExportError):
            atomic_write(self.source, b"clobber", guard=self.guard)
        self.assertEqual(self.source.read_bytes(), b"retail bytes, not ours")

    def test_a_failed_write_leaves_no_debris(self):
        with self.assertRaises(ExportError):
            atomic_write(self.data / "nope.bin", b"x", guard=self.guard)
        self.assertEqual([p.name for p in self.data.iterdir()], ["MAPTEMP.CO7"])


class SourceIdentityTests(Fixture):
    def test_records_what_was_true_at_import(self):
        identity = SourceIdentity.probe(self.source)
        self.assertEqual(identity.size, self.source.stat().st_size)
        self.assertEqual(identity.digest, digest_file(self.source))
        self.assertFalse(identity.is_symlink)
        self.assertEqual(identity.resolved, canonical(self.source))

    def test_unchanged_source_passes(self):
        identity = SourceIdentity.probe(self.source)
        atomic_write(self.work / "out.bin", b"x", guard=self.guard)
        identity.verify_unchanged()

    def test_a_modified_source_stops_the_line(self):
        identity = SourceIdentity.probe(self.source)
        self.source.write_bytes(b"tampered")
        with self.assertRaises(ExportError) as caught:
            identity.verify_unchanged()
        self.assertEqual(caught.exception.diagnostic.code, "C7E-SOURCE-001")

    def test_a_deleted_source_stops_the_line(self):
        identity = SourceIdentity.probe(self.source)
        self.source.unlink()
        with self.assertRaises(ExportError) as caught:
            identity.verify_unchanged()
        self.assertEqual(caught.exception.diagnostic.code, "C7E-SOURCE-001")

    def test_notices_a_symlinked_source(self):
        link = self.work / "alias.co7"
        link.symlink_to(self.source)
        identity = SourceIdentity.probe(link)
        self.assertTrue(identity.is_symlink)
        self.assertEqual(identity.resolved, canonical(self.source))


class SameFile(Fixture):
    def test_hard_links_are_the_same_file(self):
        link = self.work / "hard.co7"
        os.link(self.source, link)
        self.assertTrue(same_file(self.source, link))

    def test_copies_are_not(self):
        copy = self.work / "copy.co7"
        copy.write_bytes(self.source.read_bytes())
        self.assertFalse(same_file(self.source, copy))

    def test_missing_paths_fall_back_to_comparing_names(self):
        self.assertTrue(same_file(self.work / "gone", self.work / "gone"))
        self.assertFalse(same_file(self.work / "gone", self.work / "other"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
