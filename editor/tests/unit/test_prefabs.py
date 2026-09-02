#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E6: compound structures, their contracts, and the rules they depend on.

Section 19.10 asks for table-driven neighborhoods per tool: the exact words
before and after, each precondition's diagnostic, what erase restores, how
rotation moves the footprint, and that undo puts everything back. That is what
this file is.

The door tests are the ones that matter most, because a door's axis is not
stored anywhere -- the engine infers it from the walls around the cell, and an
editor that inferred differently would show one thing and ship another.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import load_catalog
from ec7edit_core.commands import History, write_words
from ec7edit_core.document import MapDocument, ProjectDocument
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.prefabs import (
    EMPTY_OBJECT,
    PREFABS,
    TRANSPORTER_CHANNELS,
    Precondition,
    Prefab,
    Write,
    by_key,
    is_floor,
    is_wall,
)
from ec7edit_core.rules import (
    check_door,
    check_transporters,
    door_axis,
    free_channel,
    transporter_endpoints,
)

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")


def build(rows, objects=None):
    """A map from ASCII: '#' wall, '.' floor, digits index into `objects`."""
    height, width = len(rows), len(rows[0])
    plane0, plane1 = [], [EMPTY_OBJECT] * (width * height)
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            plane0.append(1 if cell == "#" else 0)
    for (x, y), value in (objects or {}).items():
        plane1[y * width + x] = value
    return MapDocument("u", 1, NativeName.from_text("T"),
                       MapPlanes(width, height,
                                 (tuple(plane0), tuple(plane1), (0,) * (width * height))))


class Contract(unittest.TestCase):
    """Every prefab declares all six things, or it is not a prefab."""

    def test_each_has_writes_and_evidence(self):
        for prefab in PREFABS:
            with self.subTest(prefab=prefab.key):
                self.assertTrue(prefab.writes, "no write set")
                self.assertTrue(prefab.evidence, "no source reference")
                self.assertTrue(prefab.name and prefab.description)
                self.assertTrue(prefab.diagnostic.startswith("C7E-"))

    def test_a_prefab_without_writes_is_refused(self):
        with self.assertRaises(ValueError):
            Prefab(key="x", name="x", description="x", category="specials",
                   writes=(), evidence="somewhere")

    def test_a_prefab_without_evidence_is_refused(self):
        with self.assertRaises(ValueError):
            Prefab(key="x", name="x", description="x", category="specials",
                   writes=(Write(0, 0, 0, 1),), evidence="")

    def test_keys_are_unique(self):
        keys = [prefab.key for prefab in PREFABS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_erase_returns_a_defined_state(self):
        # Never "whatever was there before" -- that is undo's job. Erase has to
        # leave something specific behind.
        document = build(["#####", "#...#", "#####"])
        for prefab in PREFABS:
            with self.subTest(prefab=prefab.key):
                for plane, x, y, value in prefab.removal(2, 1):
                    self.assertIn(plane, (0, 1))
                    self.assertTrue(0 <= value <= 0xFFFF)


class RetractableDoors(unittest.TestCase):
    """The ten four-frame doors, and the frames that are not paint."""

    def test_each_door_writes_its_own_base_wall(self):
        # The bug this guards: an earlier version offered one generic
        # "disintegrating wall" over wall 1, whose next three pages are
        # unrelated materials -- a door that animates into rubbish.
        from ec7edit_core.prefabs import ANIMATED_DOORS

        for base, name, _ in ANIMATED_DOORS:
            prefab = by_key(f"prefab.door.animated.{base:03d}")
            with self.subTest(base=base):
                self.assertIsNotNone(prefab, name)
                writes = dict(((w.plane, w.value) for w in prefab.writes))
                self.assertEqual(prefab.writes[0].value, base)
                self.assertEqual(prefab.writes[1].value, 106)

    def test_every_frame_belongs_to_exactly_one_door(self):
        from ec7edit_core.prefabs import ANIMATED_DOORS, ANIMATION_FRAMES

        owners = {}
        for base, _, _ in ANIMATED_DOORS:
            for step in (1, 2, 3):
                owners.setdefault(base + step, []).append(base)
        for frame, bases in owners.items():
            self.assertEqual(len(bases), 1, f"{frame} claimed by {bases}")
        self.assertEqual(set(ANIMATION_FRAMES), set(owners) - {84})

    def test_the_open_force_field_is_not_treated_as_a_frame(self):
        # 84 is the one frame the shipped maps place directly, 59 times.
        from ec7edit_core.prefabs import ANIMATION_FRAMES

        self.assertNotIn(84, ANIMATION_FRAMES)

    def test_frames_are_not_offered_as_paint(self):
        for frame in (46, 74, 194, 234, 242):
            entry = CATALOG.for_value(0, frame)
            with self.subTest(frame=frame):
                self.assertEqual(entry.category, "raw")
                self.assertFalse(entry.safe_for_new_maps)

    def test_the_closed_bases_stay_paintable_and_are_named(self):
        # A closed door used as scenery is a real thing: word 193 is placed
        # 2620 times in the shipped maps and never opens.
        for base in (73, 193, 233, 241):
            entry = CATALOG.for_value(0, base)
            with self.subTest(base=base):
                self.assertEqual(entry.category, "walls")
                self.assertIn("door", entry.name.lower())

    def test_a_door_and_its_marker_land_together(self):
        document = build(["#####", "#...#", "#####"])
        prefab = by_key("prefab.door.animated.073")
        self.assertEqual(sorted(prefab.placement(2, 1)),
                         sorted([(0, 2, 1, 73), (1, 2, 1, 106)]))


class Placement(unittest.TestCase):
    def test_a_pushwall_is_a_wall_plus_a_marker(self):
        prefab = by_key("prefab.pushwall.secret")
        self.assertEqual(sorted(prefab.placement(4, 4)),
                         sorted([(0, 4, 4, 1), (1, 4, 4, 98)]))

    def test_the_two_pushwalls_differ_only_in_being_counted(self):
        secret = by_key("prefab.pushwall.secret").writes[1].value
        plain = by_key("prefab.pushwall.plain").writes[1].value
        self.assertEqual((secret, plain), (98, 101))

    def test_a_dispenser_is_one_word(self):
        self.assertEqual(by_key("prefab.dispenser.visor").placement(3, 3),
                         [(0, 3, 3, 110)])

    def test_the_vortex_goes_on_plane_one(self):
        self.assertEqual(by_key("prefab.exit.vortex").placement(2, 2),
                         [(1, 2, 2, 268)])

    def test_placing_and_undoing(self):
        document = build(["#####", "#...#", "#...#", "#####"])
        project = ProjectDocument.create().added(document)
        history = History()
        before = document.planes.planes

        prefab = by_key("prefab.pushwall.plain")
        project = history.do(project, write_words(
            document, prefab.placement(2, 1), label=prefab.name))
        edited = project.map_by_uuid(document.uuid)
        self.assertEqual(edited.cell(1, 2, 1), 101)

        project = history.undo(project)
        self.assertEqual(project.map_by_uuid(document.uuid).planes.planes, before)

    def test_a_whole_prefab_is_one_undo_step(self):
        document = build(["#####", "#...#", "#####"])
        project = ProjectDocument.create().added(document)
        history = History()
        prefab = by_key("prefab.pushwall.secret")
        history.do(project, write_words(document, prefab.placement(2, 1)))
        self.assertEqual(history.depth, 1)


class Preconditions(unittest.TestCase):
    def test_a_dispenser_needs_floor_beside_it(self):
        # Solid all round: nowhere to stand.
        document = build(["###", "###", "###"])
        problems = by_key("prefab.dispenser.health").check(document, 1, 0)
        self.assertEqual([p.code for p in problems], ["C7E-CELL-004"])

    def test_it_is_happy_with_floor_in_front(self):
        document = build(["###", "#.#", "###"])
        self.assertEqual(by_key("prefab.dispenser.health").check(document, 1, 0), [])

    def test_any_side_will_do(self):
        # The tile paints the same texture on all four faces and the trigger
        # names no side, so a wall unit is usable from whichever neighbor is
        # floor. Requiring one particular side made three walls in four
        # unusable for no reason the engine shares.
        for unit in ("prefab.dispenser.health", "prefab.dispenser.ammo",
                     "prefab.dispenser.visor", "prefab.terminal.blue",
                     "prefab.terminal.red", "prefab.elevator"):
            for rows, x, y, side in ((["###", "#.#", "###"], 1, 0, "south"),
                                     (["###", "#.#", "###"], 1, 2, "north"),
                                     (["###", "#.#", "###"], 0, 1, "east"),
                                     (["###", "#.#", "###"], 2, 1, "west")):
                with self.subTest(unit=unit, side=side):
                    self.assertEqual(by_key(unit).check(build(rows), x, y), [])

    def test_it_does_not_fit_off_the_edge(self):
        document = build(["###", "#.#", "###"])
        problems = by_key("prefab.dispenser.health").check(document, 1, 3)
        self.assertEqual([p.code for p in problems], ["C7E-BOUNDARY-001"])

    def test_the_vortex_needs_clear_floor(self):
        document = build(["###", "#.#", "###"], objects={(1, 1): 216})
        problems = by_key("prefab.exit.vortex").check(document, 1, 1)
        self.assertEqual([p.code for p in problems], ["C7E-CELL-004"])

    def test_the_vortex_is_fine_on_empty_floor(self):
        document = build(["###", "#.#", "###"])
        self.assertEqual(by_key("prefab.exit.vortex").check(document, 1, 1), [])


class Rotation(unittest.TestCase):
    """Nothing ships rotatable today -- every structure is a single word whose
    facing the engine reads off the map. The machinery stays because it is what
    a multi-cell structure would need, and the toolbar button hides itself
    until one exists."""

    def test_nothing_ships_rotatable(self):
        self.assertEqual([p.key for p in PREFABS if p.rotatable], [])

    def test_a_rotatable_footprint_turns(self):
        prefab = replace(by_key("prefab.dispenser.ammo"), rotatable=True,
                         preconditions=(Precondition(0, 1, "floor", "floor"),))
        turned = prefab.rotated(1)
        self.assertEqual((turned.preconditions[0].dx, turned.preconditions[0].dy), (-1, 0))

    def test_four_turns_return(self):
        prefab = replace(by_key("prefab.dispenser.ammo"), rotatable=True,
                         preconditions=(Precondition(0, 1, "floor", "floor"),))
        turned = prefab
        for _ in range(4):
            turned = turned.rotated(1)
        self.assertEqual(turned.preconditions[0].dx, prefab.preconditions[0].dx)
        self.assertEqual(turned.preconditions[0].dy, prefab.preconditions[0].dy)

    def test_a_non_rotatable_prefab_ignores_rotation(self):
        prefab = by_key("prefab.pushwall.secret")
        self.assertIs(prefab.rotated(1), prefab)


class Doors(unittest.TestCase):
    """The axis the engine infers, case by case, from `gamemap_planes.cpp`."""

    def axis(self, rows, x, y):
        return door_axis(build(rows), x, y)

    def test_north_south_corridor(self):
        axis = self.axis(["###", "#.#", "#D#", "#.#", "###"], 1, 2)
        self.assertTrue(axis.horizontal)
        self.assertIn("north-south", axis.label)
        self.assertTrue(axis.two_sided)

    def test_east_west_corridor(self):
        axis = self.axis(["#####", "#...#", "#####"], 2, 1)
        self.assertFalse(axis.horizontal)
        self.assertIn("east-west", axis.label)
        self.assertTrue(axis.two_sided)

    def test_a_tie_goes_vertical(self):
        # The engine's test is `>`, not `>=`, so equal openness is not
        # horizontal. Everything about a four-way opening depends on that.
        axis = self.axis(["...", "...", "..."], 1, 1)
        self.assertTrue(axis.tie)
        self.assertFalse(axis.horizontal)

    def test_a_corner_is_a_tie(self):
        axis = self.axis(["##.", "#D.", "..."], 1, 1)
        self.assertTrue(axis.tie)

    def test_a_blocked_door_has_no_approaches(self):
        axis = self.axis(["###", "#D#", "###"], 1, 1)
        self.assertEqual(axis.approaches, 0)
        self.assertFalse(axis.two_sided)

    def test_the_map_edge_counts_as_closed(self):
        # The engine's bounds checks make off-map neighbors closed, so a door
        # on the boundary is not open in that direction.
        axis = self.axis(["...", "...", "..."], 0, 1)
        self.assertFalse(axis.open_west)

    def test_a_zone_floor_counts_as_open(self):
        document = build(["###", "#.#", "###"])
        planes = list(document.planes.planes)
        plane0 = list(planes[0])
        plane0[1 * 3 + 1] = 256
        planes[0] = tuple(plane0)
        document = document.with_planes(MapPlanes(3, 3, tuple(planes)))
        self.assertTrue(door_axis(document, 1, 0).open_south)

    def test_a_one_sided_door_warns(self):
        codes = [p.code for p in check_door(build(["###", "#.#", "###"]), 1, 1)]
        self.assertIn("C7E-DOOR-001", codes)

    def test_a_tie_warns(self):
        codes = [p.code for p in check_door(build(["...", "...", "..."]), 1, 1)]
        self.assertIn("C7E-DOOR-002", codes)

    def test_a_good_door_is_quiet(self):
        self.assertEqual(check_door(build(["###", "#.#", "#D#", "#.#", "###"]), 1, 2), [])


class Transporters(unittest.TestCase):
    def place(self, cells):
        # Eight wide, because there are eight channels to lay out.
        document = build(["........", "........", "........", "........"])
        planes = list(document.planes.planes)
        plane0 = list(planes[0])
        for (x, y), channel in cells.items():
            plane0[y * 8 + x] = channel
        planes[0] = tuple(plane0)
        return document.with_planes(MapPlanes(8, 4, tuple(planes)))

    def test_a_pair_is_quiet(self):
        document = self.place({(1, 1): 279, (4, 2): 279})
        self.assertEqual(check_transporters(document), [])

    def test_one_endpoint_is_an_error(self):
        document = self.place({(1, 1): 279})
        codes = [p.code for p in check_transporters(document)]
        self.assertEqual(codes, ["C7E-WARP-001"])

    def test_three_endpoints_are_an_error(self):
        document = self.place({(1, 1): 280, (2, 1): 280, (3, 1): 280})
        self.assertEqual([p.code for p in check_transporters(document)], ["C7E-WARP-001"])

    def test_channels_are_independent(self):
        document = self.place({(1, 1): 279, (4, 2): 279, (2, 3): 281})
        codes = [p.code for p in check_transporters(document)]
        self.assertEqual(codes, ["C7E-WARP-001"])

    def test_all_eight_channels(self):
        cells = {}
        for index, channel in enumerate(TRANSPORTER_CHANNELS):
            cells[(index, 0)] = channel
            cells[(index, 3)] = channel
        document = self.place(cells)
        self.assertEqual(check_transporters(document), [])
        self.assertEqual(len(transporter_endpoints(document)), 8)

    def test_the_next_free_channel(self):
        self.assertEqual(free_channel(self.place({})), 279)
        self.assertEqual(free_channel(self.place({(1, 1): 279, (2, 1): 279})), 280)

    def test_no_free_channel_when_all_are_paired(self):
        cells = {}
        for index, channel in enumerate(TRANSPORTER_CHANNELS):
            cells[(index, 0)] = channel
            cells[(index, 3)] = channel
        self.assertIsNone(free_channel(self.place(cells)))


class CellPredicates(unittest.TestCase):
    def test_floor_and_wall(self):
        self.assertTrue(is_floor(0))
        self.assertTrue(is_floor(256))
        self.assertFalse(is_floor(1))
        self.assertTrue(is_wall(1))
        self.assertTrue(is_wall(250))
        self.assertFalse(is_wall(251), "a door is a tile, but not a plain wall")
        self.assertFalse(is_wall(0))


class CatalogAgreement(unittest.TestCase):
    def test_every_prefab_word_is_in_the_catalog(self):
        for prefab in PREFABS:
            for write in prefab.writes:
                if write.plane == 1 and write.value == EMPTY_OBJECT:
                    continue
                with self.subTest(prefab=prefab.key, value=write.value):
                    self.assertIsNotNone(
                        CATALOG.for_value(write.plane, write.value),
                        f"{prefab.key} writes plane {write.plane} word {write.value}, "
                        "which the catalog does not describe",
                    )

    def test_imported_only_prefabs_are_marked_advanced(self):
        for prefab in PREFABS:
            entry = CATALOG.for_value(prefab.writes[-1].plane, prefab.writes[-1].value)
            if entry is not None and not entry.safe_for_new_maps:
                self.assertTrue(prefab.advanced,
                                f"{prefab.key} places imported-only content but is "
                                "offered as ordinary")


if __name__ == "__main__":
    unittest.main(verbosity=1)
