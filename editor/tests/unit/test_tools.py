#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E5: what the drawing tools compute, asserted on coordinates.

The geometry lives in the core so it can be tested this way rather than by
driving a pointer. A line with a gap in it, or a fill that leaks through a
diagonal, is a bug you can only see on a specific map at a specific zoom -- and
can catch here in a list of tuples.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.document import MapDocument
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.tools import (
    FILL_BUDGET,
    flood_cells,
    line_cells,
    pick,
    rectangle_bounds,
    rectangle_cells,
)


def grid(width, height, plane0):
    return MapDocument("u", 1, NativeName.from_text("T"),
                       MapPlanes(width, height,
                                 (tuple(plane0), (18,) * (width * height),
                                  (0,) * (width * height))))


class Lines(unittest.TestCase):
    def test_a_single_point(self):
        self.assertEqual(line_cells(3, 4, 3, 4), [(3, 4)])

    def test_horizontal(self):
        self.assertEqual(line_cells(0, 0, 3, 0), [(0, 0), (1, 0), (2, 0), (3, 0)])

    def test_vertical(self):
        self.assertEqual(line_cells(2, 0, 2, 3), [(2, 0), (2, 1), (2, 2), (2, 3)])

    def test_diagonal(self):
        self.assertEqual(line_cells(0, 0, 3, 3), [(0, 0), (1, 1), (2, 2), (3, 3)])

    def test_backwards(self):
        self.assertEqual(line_cells(3, 0, 0, 0), [(3, 0), (2, 0), (1, 0), (0, 0)])

    def test_no_gaps_on_a_shallow_diagonal(self):
        # The failure this guards: interpolating with floats drops cells, and a
        # wall drawn along a shallow slope turns out to have holes in it.
        cells = line_cells(0, 0, 10, 3)
        for (x0, y0), (x1, y1) in zip(cells, cells[1:]):
            self.assertLessEqual(abs(x1 - x0) + abs(y1 - y0), 2)
        self.assertEqual(len(set(cells)), len(cells), "a cell was visited twice")

    def test_every_step_advances(self):
        cells = line_cells(0, 0, 40, 7)
        self.assertEqual(cells[0], (0, 0))
        self.assertEqual(cells[-1], (40, 7))


class Rectangles(unittest.TestCase):
    def test_outline_of_a_square(self):
        self.assertEqual(len(rectangle_cells(0, 0, 3, 3)), 12)

    def test_outline_has_no_duplicates(self):
        cells = rectangle_cells(0, 0, 5, 4)
        self.assertEqual(len(set(cells)), len(cells))

    def test_filled(self):
        self.assertEqual(len(rectangle_cells(0, 0, 3, 3, filled=True)), 16)

    def test_a_single_cell(self):
        self.assertEqual(rectangle_cells(2, 2, 2, 2), [(2, 2)])

    def test_a_one_wide_rectangle_is_a_line(self):
        self.assertEqual(sorted(rectangle_cells(1, 0, 1, 3)),
                         [(1, 0), (1, 1), (1, 2), (1, 3)])

    def test_dragging_backwards_is_the_same_rectangle(self):
        self.assertEqual(sorted(rectangle_cells(3, 3, 0, 0)),
                         sorted(rectangle_cells(0, 0, 3, 3)))

    def test_bounds_normalise_any_drag_direction(self):
        for corners in ((0, 0, 3, 2), (3, 2, 0, 0), (0, 2, 3, 0), (3, 0, 0, 2)):
            self.assertEqual(rectangle_bounds(*corners), (0, 0, 4, 3))


class Fill(unittest.TestCase):
    def test_fills_an_open_area(self):
        cells, truncated = flood_cells(grid(4, 4, [0] * 16), 0, 0, 0)
        self.assertEqual(len(cells), 16)
        self.assertFalse(truncated)

    def test_stops_at_a_wall(self):
        #  . . | .
        plane0 = [0, 0, 1, 0] * 4
        cells, _ = flood_cells(grid(4, 4, plane0), 0, 0, 0)
        self.assertEqual(len(cells), 8)
        self.assertNotIn((3, 0), cells)

    def test_does_not_leak_through_a_diagonal(self):
        # A gap you can see but cannot walk through must not let a fill past,
        # or the result surprises whoever drew the wall.
        plane0 = [
            0, 1, 1, 1,
            1, 0, 1, 1,
            1, 1, 0, 1,
            1, 1, 1, 0,
        ]
        cells, _ = flood_cells(grid(4, 4, plane0), 0, 0, 0)
        self.assertEqual(cells, [(0, 0)])

    def test_a_click_outside_the_map_fills_nothing(self):
        cells, _ = flood_cells(grid(4, 4, [0] * 16), 0, 99, 99)
        self.assertEqual(cells, [])

    def test_the_budget_stops_it(self):
        cells, truncated = flood_cells(grid(8, 8, [0] * 64), 0, 0, 0, budget=10)
        self.assertEqual(len(cells), 10)
        self.assertTrue(truncated)

    def test_the_default_budget_covers_the_largest_legal_map(self):
        self.assertGreaterEqual(FILL_BUDGET, 181 * 181)

    def test_it_fills_the_region_it_started_in(self):
        plane0 = [0] * 8 + [1] * 8 + [0] * 8
        cells, _ = flood_cells(grid(8, 3, plane0), 0, 0, 2)
        self.assertEqual(len(cells), 8)
        self.assertTrue(all(y == 2 for _, y in cells))


class Eyedropper(unittest.TestCase):
    def test_reads_the_word(self):
        document = grid(4, 4, list(range(16)))
        self.assertEqual(pick(document, 0, 2, 1), 6)

    def test_outside_the_map_is_none(self):
        self.assertIsNone(pick(grid(4, 4, [0] * 16), 0, 9, 9))

    def test_reads_any_plane(self):
        self.assertEqual(pick(grid(4, 4, [0] * 16), 1, 0, 0), 18)


if __name__ == "__main__":
    unittest.main(verbosity=1)
