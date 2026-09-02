#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E3: copy, paste, rotate and reflect -- and what happens to facings.

The geometry is checked on small hand-written grids where the right answer can
be read off. The interesting tests are the ones about direction: rotating a
selection has to rewrite the raw word of anything that faces a way, and it has
to do it through the catalog rather than by adding to the number, because the
consecutive-value layout is a coincidence of the table and not a rule.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import load_catalog
from ec7edit_core.document import MapDocument, new_uuid
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.transforms import (
    Clip,
    copy_region,
    flip_clip,
    mirror_direction,
    paste_writes,
    rotate_clip,
    rotate_direction,
)

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")

#: The Alioprobe's four facings, from the shipped translation.
EAST, NORTH, WEST, SOUTH = 108, 109, 110, 111


def make_map(width, height, plane0=None, plane1=None):
    cells = width * height
    plane0 = tuple(plane0 or range(cells))
    plane1 = tuple(plane1 or [18] * cells)
    return MapDocument(
        new_uuid(), 1, NativeName.from_text("T"),
        MapPlanes(width, height, (plane0, plane1, (0,) * cells)),
    )


class Directions(unittest.TestCase):
    def test_a_quarter_turn_clockwise(self):
        self.assertEqual(rotate_direction("east", 1), "south")
        self.assertEqual(rotate_direction("south", 1), "west")
        self.assertEqual(rotate_direction("west", 1), "north")
        self.assertEqual(rotate_direction("north", 1), "east")

    def test_diagonals_turn_too(self):
        self.assertEqual(rotate_direction("northeast", 1), "southeast")

    def test_four_turns_return(self):
        for name in ("east", "north", "west", "south", "northeast"):
            self.assertEqual(rotate_direction(name, 4), name)

    def test_an_unknown_name_is_left_alone(self):
        self.assertEqual(rotate_direction("", 1), "")
        self.assertEqual(rotate_direction("up", 1), "up")

    def test_mirroring(self):
        self.assertEqual(mirror_direction("east", "horizontal"), "west")
        self.assertEqual(mirror_direction("north", "horizontal"), "north")
        self.assertEqual(mirror_direction("north", "vertical"), "south")
        self.assertEqual(mirror_direction("northeast", "vertical"), "southeast")

    def test_a_bad_axis_is_an_error(self):
        with self.assertRaises(ValueError):
            mirror_direction("east", "diagonal")


class Copying(unittest.TestCase):
    def test_copies_all_three_planes(self):
        document = make_map(4, 4)
        clip = copy_region(document, 0, 0, 2, 2)
        self.assertEqual(len(clip.planes), 3)
        self.assertEqual(clip.planes[0], (0, 1, 4, 5))

    def test_clamps_to_the_map(self):
        clip = copy_region(make_map(4, 4), 2, 2, 10, 10)
        self.assertEqual((clip.width, clip.height), (2, 2))

    def test_an_empty_selection_is_an_error(self):
        with self.assertRaises(ValueError):
            copy_region(make_map(4, 4), 10, 10, 2, 2)

    def test_a_clip_of_the_wrong_size_is_refused(self):
        with self.assertRaises(ValueError):
            Clip(2, 2, ((1, 2), (0,) * 4, (0,) * 4))


class Rotation(unittest.TestCase):
    def test_geometry_of_a_quarter_turn(self):
        # 0 1     2 0
        # 2 3  -> 3 1
        clip = copy_region(make_map(2, 2), 0, 0, 2, 2)
        self.assertEqual(rotate_clip(clip, 1).planes[0], (2, 0, 3, 1))

    def test_a_non_square_clip_swaps_its_sides(self):
        rotated = rotate_clip(copy_region(make_map(4, 2), 0, 0, 4, 2), 1)
        self.assertEqual((rotated.width, rotated.height), (2, 4))

    def test_four_turns_return_the_original(self):
        clip = copy_region(make_map(3, 5), 0, 0, 3, 5)
        turned = clip
        for _ in range(4):
            turned = rotate_clip(turned, 1, CATALOG)
        self.assertEqual(turned.planes, clip.planes)
        self.assertEqual((turned.width, turned.height), (clip.width, clip.height))

    def test_zero_turns_is_a_no_op(self):
        clip = copy_region(make_map(3, 3), 0, 0, 3, 3)
        self.assertIs(rotate_clip(clip, 0), clip)

    def test_a_facing_is_rewritten(self):
        document = make_map(2, 2, plane1=[EAST, 18, 18, 18])
        clip = copy_region(document, 0, 0, 2, 2)
        rotated = rotate_clip(clip, 1, CATALOG)
        self.assertIn(SOUTH, rotated.planes[1])
        self.assertNotIn(EAST, rotated.planes[1])

    def test_a_facing_is_left_alone_without_a_catalog(self):
        clip = copy_region(make_map(2, 2, plane1=[EAST, 18, 18, 18]), 0, 0, 2, 2)
        self.assertIn(EAST, rotate_clip(clip, 1, None).planes[1])

    def test_a_non_directional_thing_is_untouched(self):
        # Static 000 has no facing; rotating must not walk it up the table.
        clip = copy_region(make_map(2, 2, plane1=[23, 18, 18, 18]), 0, 0, 2, 2)
        self.assertIn(23, rotate_clip(clip, 1, CATALOG).planes[1])

    def test_an_unknown_word_is_carried_through(self):
        clip = copy_region(make_map(2, 2, plane1=[60000, 18, 18, 18]), 0, 0, 2, 2)
        self.assertIn(60000, rotate_clip(clip, 1, CATALOG).planes[1])

    def test_walls_are_never_rewritten_as_facings(self):
        # Plane 0 word 108 is a wall, and 108 on plane 1 is an alien. Only the
        # object plane may be remapped.
        clip = copy_region(make_map(2, 2, plane0=[108, 1, 2, 3]), 0, 0, 2, 2)
        self.assertIn(108, rotate_clip(clip, 1, CATALOG).planes[0])

    def test_all_four_facings_rotate_consistently(self):
        for start, expected in ((EAST, SOUTH), (SOUTH, WEST), (WEST, NORTH), (NORTH, EAST)):
            clip = copy_region(make_map(1, 1, plane1=[start]), 0, 0, 1, 1)
            self.assertEqual(rotate_clip(clip, 1, CATALOG).planes[1], (expected,),
                             f"{start} should rotate to {expected}")

    def test_a_patrol_marker_rotates_through_eight(self):
        # 90 is east, and the band runs counter-clockwise in 45-degree steps.
        clip = copy_region(make_map(1, 1, plane1=[90]), 0, 0, 1, 1)
        rotated = rotate_clip(clip, 1, CATALOG).planes[1][0]
        entry = CATALOG.for_value(1, 90)
        self.assertEqual(dict(entry.directions)["south"], rotated)


class Reflection(unittest.TestCase):
    def test_horizontal_geometry(self):
        clip = copy_region(make_map(2, 2), 0, 0, 2, 2)
        self.assertEqual(flip_clip(clip, "horizontal").planes[0], (1, 0, 3, 2))

    def test_vertical_geometry(self):
        clip = copy_region(make_map(2, 2), 0, 0, 2, 2)
        self.assertEqual(flip_clip(clip, "vertical").planes[0], (2, 3, 0, 1))

    def test_flipping_twice_returns(self):
        clip = copy_region(make_map(3, 4), 0, 0, 3, 4)
        for axis in ("horizontal", "vertical"):
            self.assertEqual(
                flip_clip(flip_clip(clip, axis, CATALOG), axis, CATALOG).planes, clip.planes
            )

    def test_a_facing_mirrors(self):
        clip = copy_region(make_map(1, 1, plane1=[EAST]), 0, 0, 1, 1)
        self.assertEqual(flip_clip(clip, "horizontal", CATALOG).planes[1], (WEST,))

    def test_north_survives_a_horizontal_mirror(self):
        clip = copy_region(make_map(1, 1, plane1=[NORTH]), 0, 0, 1, 1)
        self.assertEqual(flip_clip(clip, "horizontal", CATALOG).planes[1], (NORTH,))


class Pasting(unittest.TestCase):
    def test_writes_every_plane(self):
        source = make_map(2, 2, plane0=[1, 2, 3, 4])
        target = make_map(4, 4)
        writes = paste_writes(target, copy_region(source, 0, 0, 2, 2), 1, 1)
        self.assertEqual(len(writes), 3 * 4)

    def test_can_be_restricted_to_one_plane(self):
        source = make_map(2, 2)
        writes = paste_writes(make_map(4, 4), copy_region(source, 0, 0, 2, 2), 0, 0, planes=[1])
        self.assertTrue(all(plane == 1 for plane, _, _, _ in writes))

    def test_cells_outside_the_map_are_dropped(self):
        source = make_map(4, 4)
        writes = paste_writes(make_map(4, 4), copy_region(source, 0, 0, 4, 4), 2, 2)
        self.assertEqual(len(writes), 3 * 4)

    def test_a_paste_entirely_outside_writes_nothing(self):
        source = make_map(2, 2)
        self.assertEqual(paste_writes(make_map(4, 4), copy_region(source, 0, 0, 2, 2), 99, 99), [])

    def test_round_trip_through_a_command(self):
        from ec7edit_core.commands import History, write_words
        from ec7edit_core.document import ProjectDocument

        source = make_map(2, 2, plane0=[7, 8, 9, 10])
        target = make_map(4, 4)
        project = ProjectDocument.create().added(target)
        history = History()
        clip = copy_region(source, 0, 0, 2, 2)
        project = history.do(
            project, write_words(target, paste_writes(target, clip, 1, 1), label="Paste")
        )
        pasted = project.map_by_uuid(target.uuid)
        self.assertEqual([pasted.cell(0, 1, 1), pasted.cell(0, 2, 1)], [7, 8])
        project = history.undo(project)
        self.assertEqual(project.map_by_uuid(target.uuid).planes.planes, target.planes.planes)


if __name__ == "__main__":
    unittest.main(verbosity=1)
