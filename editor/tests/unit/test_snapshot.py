# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E10: the camera, the cache key, and refusing a picture of nothing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.document import MapDocument
from ec7edit_core.errors import Ec7EditError
from ec7edit_core.snapshot import (
    RENDER_PROFILE,
    SNAPSHOT_TIC,
    Camera,
    check_camera,
    looks_like_a_world,
    snapshot_arguments,
    snapshot_key,
)


class Cameras(unittest.TestCase):
    def room(self):
        return MapDocument.new_room(width=16, height=16)

    def test_a_floor_tile_is_accepted(self):
        check_camera(self.room(), Camera(8, 8, 0))

    def test_outside_the_map_is_refused(self):
        for camera in (Camera(-1, 8), Camera(8, -1), Camera(16, 8), Camera(8, 16),
                       Camera(1e6, 1e6)):
            with self.subTest(camera=camera):
                with self.assertRaises(Ec7EditError):
                    check_camera(self.room(), camera)

    def test_inside_a_wall_is_refused(self):
        # The engine would draw it without complaining, and the cache would
        # keep the result.
        with self.assertRaises(Ec7EditError):
            check_camera(self.room(), Camera(0, 0))

    def test_a_camera_that_is_not_a_number_is_refused(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                with self.assertRaises(Ec7EditError):
                    check_camera(self.room(), Camera(bad, 8))

    def test_the_angle_wraps_rather_than_being_refused(self):
        self.assertEqual(Camera(1, 1, 450).normalised().angle, 90)
        self.assertEqual(Camera(1, 1, -90).normalised().angle, 270)


class Arguments(unittest.TestCase):
    def test_the_software_profile_is_pinned(self):
        # The PNG path is only a true picture of the world under software: with
        # OpenGL live the GPU owns the world and the framebuffer this reads
        # holds only the 2D overlay. A gate once passed comparing that.
        args = snapshot_arguments(Camera(3, 4, 90), "/tmp/s.png")
        self.assertEqual(args[args.index("--vid-renderer") + 1], "software")
        self.assertIn("--no-upscale", args)
        self.assertEqual(args[args.index("--res") + 1], str(RENDER_PROFILE["width"]))

    def test_the_shot_is_anchored_to_a_tic(self):
        args = snapshot_arguments(Camera(3, 4), "/tmp/s.png")
        self.assertEqual(args[-1], str(SNAPSHOT_TIC))
        self.assertEqual(args[-3], "--capture-snapshot")

    def test_the_camera_reaches_the_engine(self):
        args = snapshot_arguments(Camera(3.5, 4.5, 270), "/tmp/s.png")
        at = args.index("--capture-warp")
        self.assertEqual(args[at + 1:at + 4], ["3.5", "4.5", "270"])


class CacheKeys(unittest.TestCase):
    """A key that left anything out would hand back a stale picture after the
    very change somebody took the snapshot to see."""

    def key(self, **overrides):
        base = dict(engine=__file__, pk3=__file__, data_fingerprint="fp",
                    export_digest="abc", camera=Camera(1, 2, 0))
        base.update(overrides)
        return snapshot_key(**base)

    def test_the_same_request_is_the_same_key(self):
        self.assertEqual(self.key(), self.key())

    def test_every_input_changes_it(self):
        base = self.key()
        for name, value in (("data_fingerprint", "other"),
                            ("export_digest", "def"),
                            ("camera", Camera(1, 2, 90)),
                            ("camera", Camera(9, 2, 0))):
            with self.subTest(name=name):
                self.assertNotEqual(base, self.key(**{name: value}))

    def test_a_different_engine_changes_it(self):
        self.assertNotEqual(self.key(), self.key(engine="/does/not/exist"))

    def test_a_missing_file_is_keyed_not_crashed(self):
        self.assertTrue(self.key(engine="/nope", pk3="/nope"))


class BlankFrames(unittest.TestCase):
    """The one check that matters: this project has shipped a gate that passed
    while comparing a black frame nobody had looked at."""

    def png(self, colour, name):
        from PIL import Image

        path = Path(self._tmp.name) / name
        Image.new("RGB", (64, 40), colour).save(path)
        return path

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_black_frame_is_not_a_world(self):
        self.assertFalse(looks_like_a_world(self.png((0, 0, 0), "black.png")))

    def test_one_flat_colour_is_not_a_world(self):
        self.assertFalse(looks_like_a_world(self.png((30, 40, 50), "flat.png")))

    def test_a_missing_file_is_not_a_world(self):
        self.assertFalse(looks_like_a_world(Path(self._tmp.name) / "nope.png"))

    def test_something_that_is_not_a_png_is_not_a_world(self):
        path = Path(self._tmp.name) / "junk.png"
        path.write_bytes(b"not a png at all")
        self.assertFalse(looks_like_a_world(path))

    def test_a_varied_frame_is(self):
        from PIL import Image

        path = Path(self._tmp.name) / "world.png"
        image = Image.new("RGB", (64, 40))
        image.putdata([(x * 3 % 256, y * 5 % 256, 90) for y in range(40) for x in range(64)])
        image.save(path)
        self.assertTrue(looks_like_a_world(path))


class Facing(unittest.TestCase):
    """The angle convention, written down where it can be checked.

    0 east, 90 north -- the engine's, not a clock's. `--capture-warp` maps
    these degrees onto angle_t and assigns them to the player, and the engine
    sends an angle between 45 and 135 to `tiley - 1`, which is north.
    """

    def test_the_four_right_angles_are_named(self):
        self.assertIn("east", Camera(1.5, 1.5, 0).describe())
        self.assertIn("north", Camera(1.5, 1.5, 90).describe())
        self.assertIn("west", Camera(1.5, 1.5, 180).describe())
        self.assertIn("south", Camera(1.5, 1.5, 270).describe())

    def test_an_angle_between_them_keeps_its_number_and_invents_nothing(self):
        described = Camera(1.5, 1.5, 45).describe()
        self.assertIn("45", described)
        self.assertNotIn("(", described.split("facing")[1])

    def test_the_angle_reaches_the_engine_unchanged(self):
        self.assertIn("90", Camera(3, 4, 90).arguments())

    def test_turning_four_times_comes_back(self):
        angle = 0.0
        for _ in range(4):
            angle = (angle + 90.0) % 360.0
        self.assertEqual(Camera(1, 1, angle).normalised().angle, 0.0)


if __name__ == "__main__":
    unittest.main()
