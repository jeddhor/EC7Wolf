#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E5: the playtest command line, built as a vector and checked before use."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.engine_runner import DATA_EXTENSION, LaunchError, build_launch_plan


class Plans(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.engine = self.root / "ec7wolf"
        self.engine.write_text("#!/bin/sh\n")
        self.engine.chmod(0o755)
        self.data = self.root / "data"
        self.data.mkdir()
        self.wad = self.root / "preview.wad"
        self.wad.write_bytes(b"PWAD")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, **overrides):
        arguments = dict(executable=self.engine, data_dir=self.data, preview_wad=self.wad)
        arguments.update(overrides)
        return build_launch_plan(**arguments)

    def test_the_argument_vector(self):
        plan = self.plan(marker="MAP07", skill=3)
        self.assertEqual(plan.arguments[:6],
                         ["--data", DATA_EXTENSION, "--tedlevel", "MAP07", "--skill", "3"])

    def test_the_override_is_last(self):
        # A WAD given later wins by lump name, which is the whole mechanism.
        plan = self.plan()
        self.assertEqual(plan.arguments[-2], "--file")
        self.assertEqual(plan.arguments[-1], str(self.wad.resolve()))

    def test_it_runs_in_the_data_directory(self):
        # The engine finds its data in the working directory; there is no flag
        # for the path, only for the extension.
        self.assertEqual(self.plan().cwd, self.data.resolve())

    def test_paths_are_absolute(self):
        plan = self.plan()
        self.assertTrue(Path(plan.argv[0]).is_absolute())
        self.assertTrue(Path(plan.arguments[-1]).is_absolute())

    def test_extra_arguments_are_appended(self):
        plan = self.plan(extra=["--nowait"])
        self.assertEqual(plan.arguments[-1], "--nowait")

    def test_it_is_a_vector_not_a_string(self):
        # No shell, so nothing in a filename can become a command.
        self.assertIsInstance(self.plan().argv, list)

    def test_a_space_in_a_path_needs_no_quoting(self):
        spaced = self.root / "my games"
        spaced.mkdir()
        wad = spaced / "preview one.wad"
        wad.write_bytes(b"PWAD")
        plan = self.plan(preview_wad=wad)
        self.assertEqual(plan.arguments[-1], str(wad.resolve()))

    def test_a_description_for_the_user(self):
        self.assertIn("--tedlevel", self.plan().described())


class Rejects(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.engine = self.root / "ec7wolf"
        self.engine.write_text("#!/bin/sh\n")
        self.data = self.root / "data"
        self.data.mkdir()
        self.wad = self.root / "preview.wad"
        self.wad.write_bytes(b"PWAD")

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, **overrides):
        arguments = dict(executable=self.engine, data_dir=self.data, preview_wad=self.wad)
        arguments.update(overrides)
        return build_launch_plan(**arguments)

    def assertRefused(self, **overrides):
        with self.assertRaises(LaunchError):
            self.build(**overrides)

    def test_a_missing_engine(self):
        self.assertRefused(executable=self.root / "absent")

    def test_a_missing_data_directory(self):
        self.assertRefused(data_dir=self.root / "absent")

    def test_a_missing_wad(self):
        self.assertRefused(preview_wad=self.root / "absent.wad")

    def test_a_bad_marker(self):
        for marker in ("E1M1", "map01", "MAP0", "", "MAP01; rm -rf /"):
            with self.subTest(marker=marker):
                self.assertRefused(marker=marker)

    def test_a_skill_outside_the_range(self):
        for skill in (0, 5, -1):
            with self.subTest(skill=skill):
                self.assertRefused(skill=skill)


if __name__ == "__main__":
    unittest.main(verbosity=1)
