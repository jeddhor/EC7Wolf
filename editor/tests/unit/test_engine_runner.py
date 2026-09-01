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

from ec7edit_core.engine_runner import (
    DATA_EXTENSION,
    LaunchError,
    LaunchPlan,
    Session,
    SessionState,
    build_launch_plan,
    parse_event,
)
from ec7edit_core.errors import Ec7EditError


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

    def test_extra_arguments_are_added(self):
        plan = self.plan(extra=["--nowait"])
        self.assertIn("--nowait", plan.arguments)

    def test_the_preview_file_is_always_last(self):
        # A WAD loaded later overrides the base data by lump name, which is the
        # entire mechanism by which the edit reaches the game. Anything after
        # it could be another --file, and then the map under test would be the
        # one that lost.
        plan = self.plan(extra=["--nowait", "--vid-renderer", "software"])
        self.assertEqual(plan.arguments[-2], "--file")
        self.assertTrue(plan.arguments[-1].endswith(".wad"))

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


class Events(unittest.TestCase):
    """E9: the engine's event stream, and why it is anchored on the nonce."""

    def test_it_reads_an_event(self):
        event = parse_event("EC7EDIT s1 map-entry marker=MAP03 name=Lab", "s1")
        self.assertEqual(event.event, "map-entry")
        self.assertEqual(event.get("marker"), "MAP03")

    def test_another_session_is_not_ours(self):
        self.assertIsNone(parse_event("EC7EDIT other map-entry marker=MAP03", "s1"))

    def test_ordinary_output_is_not_an_event(self):
        for line in ("Could not stat foo.wad", "", "EC7EDIT", "EC7EDITs1 hello",
                     "  adding ./AUDIOT.CO7, 100 sounds"):
            with self.subTest(line=line):
                self.assertIsNone(parse_event(line, "s1"))

    def test_a_map_cannot_forge_one(self):
        # The map under test is user content, and user content that can print
        # is user content that can lie. Matching the prefix alone would let it.
        forged = "EC7EDIT ec7edit-0001 map-entry marker=MAP01"
        self.assertIsNone(parse_event(forged, "ec7edit-0002"))

    def test_a_value_with_no_key_is_ignored(self):
        event = parse_event("EC7EDIT s1 fatal message=x stray", "s1")
        self.assertEqual(event.fields, {"message": "x"})


class Sessions(unittest.TestCase):
    """The state machine, driven by lines rather than by a process."""

    def session(self):
        plan = LaunchPlan(Path("/engine"), ["--file", "/w/preview.wad"],
                          Path("/data"), session="s1",
                          preview=Path("/w/preview.wad"))
        state = Session(plan)
        state.started()
        return state

    def drive(self, lines, exit_code=0):
        state = self.session()
        for line in lines:
            state.feed(line)
        state.finished(exit_code)
        return state

    GOOD = [
        "EC7EDIT s1 hello engine=EC7Wolf version=1.0",
        "EC7EDIT s1 preview-load path=/w/preview.wad loaded=yes lumps=9",
        "EC7EDIT s1 map-entry marker=MAP01 name=Lab spawnfilter=1",
        "EC7EDIT s1 session-result outcome=quit",
    ]

    def test_a_good_run_reaches_the_map(self):
        state = self.drive(self.GOOD)
        self.assertIs(state.state, SessionState.FINISHED)
        self.assertTrue(state.reached_the_map)
        self.assertEqual(state.marker_entered, "MAP01")

    def test_a_missing_preview_is_a_failure_even_though_the_engine_is_happy(self):
        # The trap this whole protocol exists for: AddFile prints and returns
        # rather than failing, so the engine exits 0 having played the SHIPPED
        # map of that number. Exit code alone calls that a success.
        lines = list(self.GOOD)
        lines[1] = "EC7EDIT s1 preview-load path=/w/preview.wad loaded=no lumps=5"
        state = self.drive(lines, exit_code=0)
        self.assertIs(state.state, SessionState.FAILED)
        self.assertFalse(state.reached_the_map)
        self.assertIn("shipped map", state.failure)

    def test_a_fatal_is_reported_in_the_engine_s_own_words(self):
        lines = self.GOOD[:3] + [
            "EC7EDIT s1 fatal message=No_player_1_start!",
            "EC7EDIT s1 session-result outcome=error",
        ]
        state = self.drive(lines, exit_code=1)
        self.assertIs(state.state, SessionState.FAILED)
        self.assertEqual(state.failure, "No player 1 start!")

    def test_an_engine_that_says_nothing_is_diagnosed(self):
        state = self.drive([], exit_code=1)
        self.assertIs(state.state, SessionState.FAILED)
        self.assertIn("without answering", state.failure)

    def test_dying_midway_says_how_far_it_got(self):
        state = self.drive(self.GOOD[:2], exit_code=1)
        self.assertIn("before reaching the map", state.failure)

    def test_states_advance_in_order(self):
        state = self.session()
        self.assertIs(state.state, SessionState.STARTING)
        state.feed(self.GOOD[0])
        self.assertIs(state.state, SessionState.LOADING)
        state.feed(self.GOOD[1])
        state.feed(self.GOOD[2])
        self.assertIs(state.state, SessionState.PLAYING)

    def test_ordinary_output_is_kept_for_the_log(self):
        state = self.session()
        state.feed("adding ./AUDIOT.CO7")
        state.feed(self.GOOD[0])
        self.assertIn("adding ./AUDIOT.CO7", state.log)
        self.assertEqual(len(state.events), 1)

    def test_the_log_is_bounded(self):
        # A playtest prints for as long as somebody plays.
        state = self.session()
        for index in range(Session.LOG_LIMIT + 500):
            state.feed(f"line {index}")
        self.assertEqual(len(state.log), Session.LOG_LIMIT)
        self.assertEqual(state.log[-1], f"line {Session.LOG_LIMIT + 499}")


class SessionPlans(unittest.TestCase):
    def plan(self, **kwargs):
        return build_launch_plan(
            executable=self.engine, data_dir=self.data, preview_wad=self.wad,
            **kwargs)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.engine = root / "ec7wolf"; self.engine.write_text("#!/bin/sh\n")
        self.data = root / "data"; self.data.mkdir()
        self.wad = root / "p.wad"; self.wad.write_bytes(b"PWAD")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_session_adds_the_protocol_arguments(self):
        plan = self.plan(session="ec7edit-0001")
        self.assertIn("--editor-protocol", plan.arguments)
        self.assertEqual(plan.arguments[plan.arguments.index("--editor-session") + 1],
                         "ec7edit-0001")

    def test_no_session_means_no_protocol(self):
        self.assertNotIn("--editor-protocol", self.plan().arguments)

    def test_a_session_directory_isolates_config_and_saves(self):
        # A playtest must not rewrite the settings or the saved games of
        # somebody who also plays this game.
        plan = self.plan(session="s1", session_dir=Path(self._tmp.name) / "sess")
        config = plan.arguments[plan.arguments.index("--config") + 1]
        saves = plan.arguments[plan.arguments.index("--savedir") + 1]
        self.assertIn("sess", config)
        self.assertIn("sess", saves)

    def test_a_hostile_session_id_is_refused(self):
        for bad in ("with space", "semi;colon", "new\nline", "x" * 65, "back`tick"):
            with self.subTest(bad=bad):
                with self.assertRaises(Ec7EditError):
                    self.plan(session=bad)

    def test_the_summary_records_what_was_tested(self):
        plan = self.plan(session="s1", export_digest="abc123", revision=7)
        summary = plan.summary()
        self.assertEqual(summary["export_digest"], "abc123")
        self.assertEqual(summary["revision"], 7)
        self.assertEqual(summary["session"], "s1")
