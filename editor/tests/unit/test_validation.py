#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E5: the basic validator, and the rule that keeps it worth reading.

A validator that reports five problems on every map the game shipped is a
validator its user learns to ignore, and then the one that mattered is lost in
the list. So imported content is judged more gently than authored content --
the plan's rule, and the one that makes the difference between a panel people
read and a panel people close.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import load_catalog
from ec7edit_core.document import MapDocument, SourceReference
from ec7edit_core.errors import Severity
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes, linear_index
from ec7edit_core.validation import summarise, validate_map

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")

WALL = 1
#: A legal map's floor is a sound area. Word 0 is walkable but carries none,
#: which is its own diagnostic now.
FLOOR = 256
NO_AREA = 0
ZONE = 256
#: The plane-0 marker that finishes the floor when walked over.
FLOOR_EXIT = 287
PLAYER_START_EAST = 19
RODEX_EAST = 216
RED_DOOR = 253      # lock 2; lockdefs.txt Lock 2 Corridor7 is the red card
RED_CARD = 24
RED_TERMINAL = 9
EMPTY = 18


def build(width=8, height=8, *, imported=False, walls=True, exit=True):
    """A minimal legal map: solid border, open middle, one start, a way out.

    The exit matters: without one the floor cannot be finished, which the
    validator says so a map that is missing it is not called clean.
    """
    plane0 = []
    for y in range(height):
        for x in range(width):
            edge = x in (0, width - 1) or y in (0, height - 1)
            plane0.append(WALL if (edge and walls) else FLOOR)
    if exit:
        plane0[linear_index(width - 2, height - 2, width)] = FLOOR_EXIT
    plane1 = [EMPTY] * (width * height)
    plane1[linear_index(2, 2, width)] = PLAYER_START_EAST
    source = SourceReference("MAPTEMP.CO7", "a" * 64, 1) if imported else None
    return MapDocument("u", 1, NativeName.from_text("T"),
                       MapPlanes(width, height, (tuple(plane0), tuple(plane1),
                                                 (0,) * (width * height))),
                       source=source)


def codes(document):
    return [problem.code for problem in validate_map(document, CATALOG)]


class CleanMap(unittest.TestCase):
    def test_a_minimal_legal_map_has_no_problems(self):
        self.assertEqual(validate_map(build(), CATALOG), [])


class SoundAreas(unittest.TestCase):
    """Floor with no area is floor nothing can hear the player through."""

    def test_floor_without_an_area_is_an_error(self):
        document = build()
        planes = list(document.planes.planes)
        words = list(planes[0])
        words[linear_index(4, 4, document.width)] = NO_AREA
        planes[0] = tuple(words)
        document = document.with_planes(
            MapPlanes(document.width, document.height, tuple(planes)))
        problems = [p for p in validate_map(document, CATALOG)
                    if p.code == "C7E-ZONE-001"]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].severity, Severity.ERROR)
        self.assertIn("hear", problems[0].message)

    def test_it_counts_them_and_names_the_first(self):
        document = build(walls=False)
        planes = list(document.planes.planes)
        planes[0] = (NO_AREA,) * (document.width * document.height)
        document = document.with_planes(
            MapPlanes(document.width, document.height, tuple(planes)))
        problem = next(p for p in validate_map(document, CATALOG)
                       if p.code == "C7E-ZONE-001")
        self.assertIn(str(document.width * document.height), problem.message)
        self.assertIn("(0, 0)", problem.where)

    def test_an_area_floor_is_silent(self):
        self.assertNotIn("C7E-ZONE-001", codes(build()))

    def test_an_imported_map_only_warns(self):
        # An unexpected word in retail data is evidence about the original, not
        # a mistake to correct -- the same rule the other authored checks use.
        document = build(imported=True)
        planes = list(document.planes.planes)
        words = list(planes[0])
        words[linear_index(4, 4, document.width)] = NO_AREA
        planes[0] = tuple(words)
        document = document.with_planes(
            MapPlanes(document.width, document.height, tuple(planes)))
        problem = next(p for p in validate_map(document, CATALOG)
                       if p.code == "C7E-ZONE-001")
        self.assertEqual(problem.severity, Severity.WARNING)


class RepairingSoundAreas(unittest.TestCase):
    """The repair for a floor made of word 0, which every map drawn before
    2026-08-31 has. The fill tool reaches one connected region per click, and a
    map with rooms behind doors has as many regions as it has rooms."""

    def zoneless(self, rows):
        """A map from ASCII: '#' wall, 'D' door, '.' floor with no area,
        digits an existing area (256 + the digit)."""
        height, width = len(rows), len(rows[0])
        plane0, plane1 = [], [EMPTY] * (width * height)
        for row in rows:
            for cell in row:
                plane0.append({"#": WALL, "D": 254, ".": NO_AREA}.get(cell)
                              if cell in "#D." else 256 + int(cell))
        plane1[linear_index(1, 1, width)] = PLAYER_START_EAST
        return MapDocument("u", 1, NativeName.from_text("T"),
                           MapPlanes(width, height,
                                     (tuple(plane0), tuple(plane1),
                                      (0,) * (width * height))))

    def applied(self, document):
        from ec7edit_core.rules import assign_sound_areas

        words = list(document.planes.planes[0])
        for _, x, y, value in assign_sound_areas(document):
            words[linear_index(x, y, document.width)] = value
        return words

    def test_every_zoneless_cell_gets_an_area(self):
        document = self.zoneless(["#####", "#...#", "#...#", "#####"])
        self.assertNotIn(NO_AREA, self.applied(document))

    def test_one_region_gets_one_area(self):
        document = self.zoneless(["#####", "#...#", "#...#", "#####"])
        areas = {v for v in self.applied(document) if v >= 256}
        self.assertEqual(areas, {256})

    def test_a_door_separates_two_areas(self):
        # Which is the point of areas: sound crosses a doorway when the door
        # opens and links them, exactly as it does in the shipped maps.
        document = self.zoneless(["#####", "#.D.#", "#####"])
        words = self.applied(document)
        left = words[linear_index(1, 1, document.width)]
        right = words[linear_index(3, 1, document.width)]
        self.assertNotEqual(left, right)
        self.assertEqual({left, right}, {256, 257})

    def test_it_joins_an_area_that_is_already_there(self):
        # Repairing half a map must not cut it off from the half that was right.
        document = self.zoneless(["#####", "#.0.#", "#####"])
        words = self.applied(document)
        self.assertEqual({v for v in words if v >= 256}, {256})

    def test_a_clean_map_needs_no_writes(self):
        from ec7edit_core.rules import assign_sound_areas

        self.assertEqual(assign_sound_areas(build()), [])

    def test_the_summary_says_so(self):
        self.assertEqual(summarise([]), "No problems found")


class Boundary(unittest.TestCase):
    def test_an_open_edge_is_an_error(self):
        self.assertIn("C7E-BOUNDARY-001", codes(build(walls=False)))

    def test_one_gap_is_enough(self):
        document = build()
        planes = list(document.planes.planes)
        plane0 = list(planes[0])
        plane0[linear_index(3, 0, 8)] = FLOOR
        planes[0] = tuple(plane0)
        document = document.with_planes(MapPlanes(8, 8, tuple(planes)))
        self.assertIn("C7E-BOUNDARY-001", codes(document))

    def test_a_zone_on_the_edge_counts_as_open(self):
        # A sound zone is floor with a number on it; it is still walkable.
        document = build()
        planes = list(document.planes.planes)
        plane0 = list(planes[0])
        plane0[linear_index(0, 3, 8)] = ZONE
        planes[0] = tuple(plane0)
        self.assertIn("C7E-BOUNDARY-001",
                      codes(document.with_planes(MapPlanes(8, 8, tuple(planes)))))


class Starts(unittest.TestCase):
    def replace_plane1(self, document, changes):
        planes = list(document.planes.planes)
        plane1 = list(planes[1])
        for (x, y), value in changes.items():
            plane1[linear_index(x, y, document.width)] = value
        planes[1] = tuple(plane1)
        return document.with_planes(MapPlanes(document.width, document.height, tuple(planes)))

    def test_no_start_is_an_error(self):
        document = self.replace_plane1(build(), {(2, 2): EMPTY})
        self.assertIn("C7E-START-001", codes(document))

    def test_two_starts_are_an_error(self):
        document = self.replace_plane1(build(), {(4, 4): PLAYER_START_EAST})
        self.assertIn("C7E-START-002", codes(document))

    def test_a_start_in_a_wall_is_an_error(self):
        document = self.replace_plane1(build(), {(2, 2): EMPTY, (0, 0): PLAYER_START_EAST})
        found = codes(document)
        self.assertIn("C7E-START-003", found)

    def test_any_of_the_four_facings_counts(self):
        for value in (19, 20, 21, 22):
            document = self.replace_plane1(build(), {(2, 2): value})
            self.assertNotIn("C7E-START-001", codes(document), f"value {value}")


class Things(unittest.TestCase):
    def bury(self, document, value):
        planes = list(document.planes.planes)
        plane1 = list(planes[1])
        plane1[linear_index(0, 0, document.width)] = value
        planes[1] = tuple(plane1)
        return document.with_planes(MapPlanes(document.width, document.height, tuple(planes)))

    def test_an_authored_thing_in_a_wall_is_an_error(self):
        problems = validate_map(self.bury(build(), RODEX_EAST), CATALOG)
        buried = [p for p in problems if p.code == "C7E-THING-001"]
        self.assertEqual(buried[0].severity, Severity.ERROR)

    def test_an_imported_thing_in_a_wall_is_a_warning(self):
        # The shipped maps really do have twelve of these. Reporting somebody's
        # legally purchased game as broken teaches them to close the panel.
        problems = validate_map(self.bury(build(imported=True), RODEX_EAST), CATALOG)
        buried = [p for p in problems if p.code == "C7E-THING-001"]
        self.assertEqual(buried[0].severity, Severity.WARNING)
        self.assertIn("preserved", buried[0].message)

    def test_a_pushwall_inside_a_wall_is_fine(self):
        # 98, 101, 102 and 106 belong in a wall: that is what they modify.
        for value in (98, 101, 102, 106):
            problems = validate_map(self.bury(build(), value), CATALOG)
            self.assertEqual([p for p in problems if p.code == "C7E-THING-001"], [],
                             f"word {value} was reported as buried")


class UnknownWords(unittest.TestCase):
    def test_an_unknown_plane1_word_is_a_warning(self):
        document = build()
        planes = list(document.planes.planes)
        plane1 = list(planes[1])
        plane1[linear_index(4, 4, 8)] = 60000
        planes[1] = tuple(plane1)
        problems = validate_map(
            document.with_planes(MapPlanes(8, 8, tuple(planes))), CATALOG
        )
        unknown = [p for p in problems if p.code == "C7E-CELL-002"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0].severity, Severity.WARNING)
        self.assertIn("preserved", unknown[0].message)


class Doors(unittest.TestCase):
    def place(self, document, plane, x, y, value):
        planes = list(document.planes.planes)
        words = list(planes[plane])
        words[linear_index(x, y, document.width)] = value
        planes[plane] = tuple(words)
        return document.with_planes(MapPlanes(document.width, document.height, tuple(planes)))

    def test_a_locked_door_without_its_key_warns(self):
        document = self.place(build(), 0, 4, 4, RED_DOOR)
        self.assertIn("C7E-DOOR-003", codes(document))

    def test_the_key_being_present_silences_it(self):
        document = self.place(build(), 0, 4, 4, RED_DOOR)
        document = self.place(document, 1, 3, 3, RED_CARD)
        self.assertNotIn("C7E-DOOR-003", codes(document))

    def test_the_terminal_that_grants_it_also_silences_it(self):
        # Corridor 7 hands out its cards at wall terminals, not off the floor.
        document = self.place(build(), 0, 4, 4, RED_DOOR)
        document = self.place(document, 0, 0, 3, RED_TERMINAL)
        self.assertNotIn("C7E-DOOR-003", codes(document))

    def test_the_wrong_colour_terminal_does_not(self):
        document = self.place(build(), 0, 4, 4, RED_DOOR)
        document = self.place(document, 0, 0, 3, 11)   # blue terminal
        self.assertIn("C7E-DOOR-003", codes(document))


class Reporting(unittest.TestCase):
    def test_errors_come_before_warnings(self):
        document = build(walls=False)
        problems = validate_map(document, CATALOG)
        severities = [problem.severity.value for problem in problems]
        self.assertEqual(severities, sorted(severities, reverse=True))

    def test_a_diagnostic_names_a_cell(self):
        problems = validate_map(build(walls=False), CATALOG)
        self.assertTrue(any(p.where.startswith("cell (") for p in problems))

    def test_summary_counts(self):
        self.assertEqual(summarise(validate_map(build(walls=False), CATALOG)).split(",")[0],
                         "1 error")

    def test_it_runs_without_a_catalogue(self):
        # Structural checks still work before setup has found the game.
        self.assertEqual([p.code for p in validate_map(build(), None)], [])
        self.assertIn("C7E-BOUNDARY-001", [p.code for p in validate_map(build(walls=False), None)])


if __name__ == "__main__":
    unittest.main(verbosity=1)
