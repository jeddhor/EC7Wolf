#!/usr/bin/env python3
"""E0: the synthetic corpus is reproducible, synthetic, and well-formed.

No editor code exists yet to test. What can be tested at E0 is the foundation
everything later stands on: that the fixtures are the same bytes every time,
that they are demonstrably not retail data, and that the ones claiming to be
malformed really are.

Plain unittest and the standard library, so this runs anywhere Python does and
does not decide the project's test-runner dependency before E1 needs one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
EDITOR = HERE.parents[2]

spec = importlib.util.spec_from_file_location(
    "make_fixtures", EDITOR / "scripts" / "make_fixtures.py")
make_fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_fixtures)


class Reproducible(unittest.TestCase):
    def test_two_runs_agree(self):
        """The generator is deterministic, so a digest is a contract."""
        self.assertEqual(make_fixtures.digests(), make_fixtures.digests())

    def test_written_bytes_match_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, blob in make_fixtures.fixture_set().items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            for name, digest in make_fixtures.digests().items():
                actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
                self.assertEqual(actual, digest, name)

    def test_verify_notices_tampering(self):
        """A fixture edited by hand must stop the gate, not pass it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, blob in make_fixtures.fixture_set().items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            victim = root / "archive" / "one-map.c7map"
            victim.write_bytes(victim.read_bytes() + b"tampered")
            argv = sys.argv
            try:
                sys.argv = ["make_fixtures.py", "verify", str(root)]
                self.assertEqual(make_fixtures.main(), 1)
            finally:
                sys.argv = argv


class Synthetic(unittest.TestCase):
    def test_plane_words_are_outside_the_games_range(self):
        """Every plane word sits in a band retail data never uses."""
        for salt in range(4):
            for word in make_fixtures.synth_plane(16, 16, salt):
                self.assertGreaterEqual(word, make_fixtures.SYNTH_BASE)
                self.assertLessEqual(word, 0xFFFF)

    def test_archives_are_marked(self):
        blob = make_fixtures.fixture_set()["archive/one-map.c7map"]
        self.assertIn(b"SYNTH", blob)

    def test_no_fixture_is_large_enough_to_be_a_retail_archive(self):
        """A retail MAPTEMP is hundreds of kilobytes; nothing here is."""
        for name, blob in make_fixtures.fixture_set().items():
            self.assertLess(len(blob), 200_000, name)


class WellFormed(unittest.TestCase):
    def test_rlew_round_trips(self):
        for words in ([0xE000] * 10,
                      [0xE000, 0xE001, 0xE002],
                      [make_fixtures.RLEW_TAG],
                      [make_fixtures.RLEW_TAG] * 5,
                      list(range(0xE000, 0xE040))):
            stream = make_fixtures.rlew_compress(words)
            self.assertEqual(self._expand(stream, len(words)), words)

    @staticmethod
    def _expand(stream: bytes, expect: int) -> list[int]:
        out, i = [], 0
        while i < len(stream):
            (word,) = struct.unpack_from("<H", stream, i)
            i += 2
            if word == make_fixtures.RLEW_TAG:
                count, value = struct.unpack_from("<HH", stream, i)
                i += 4
                out.extend([value] * count)
            else:
                out.append(word)
        assert len(out) == expect, (len(out), expect)
        return out

    def test_first_header_is_46_and_later_are_42(self):
        blob = make_fixtures.fixture_set()["archive/three-maps.c7map"]
        self.assertEqual(blob[:12], make_fixtures.TED5_SIGNATURE)
        # Plane 0 of the first map is implicit: it starts at 46.
        (plane1, plane2) = struct.unpack_from("<II", blob, 12)
        self.assertGreater(plane1, 46)
        self.assertGreater(plane2, plane1)
        (w, h) = struct.unpack_from("<HH", blob, 26)
        self.assertEqual((w, h), (8, 8))

    def test_malformed_cases_differ_from_the_good_one(self):
        good = make_fixtures.fixture_set()["archive/one-map.c7map"]
        for name, blob in make_fixtures.malformed().items():
            self.assertNotEqual(blob, good, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
