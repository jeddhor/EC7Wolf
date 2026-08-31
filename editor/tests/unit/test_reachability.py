# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E7: what the player can get to, and whether the floor can be finished.

Every map here is drawn as ASCII so the case being tested is visible in the
test rather than in a list of raw words. The model's limits are in
`reachability.py`; these pin the behaviour the plan's section 19.11 asks for:
open, locked and keyed, transporter, isolated, and cyclic-key routes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import load_catalog
from ec7edit_core.document import MapDocument
from ec7edit_core.errors import Severity
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes, linear_index
from ec7edit_core.reachability import analyse, unreachable_floor
from ec7edit_core.validation import DEATHMATCH, validate_map

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")

#: What each ASCII character paints. Plane 0 first, then plane 1.
LEGEND = {
    "#": (1, 18),        # wall
    ".": (256, 18),      # floor with a sound area
    "@": (256, 20),      # the player, facing east
    "X": (287, 18),      # the floor exit marker
    "B": (252, 18),      # door needing the BLUE card
    "R": (253, 18),      # door needing the RED card
    "D": (254, 18),      # plain door
    "b": (256, 25),      # the BLUE access card, lying on the floor
    "r": (256, 24),      # the RED access card
    "T": (256, 18),      # a wall terminal is painted separately
    "1": (279, 18),      # transporter channel 1
    "2": (280, 18),      # transporter channel 2
}


def draw(rows, terminals=None):
    """A map from ASCII. `terminals` maps (x, y) to a plane-0 terminal word."""
    height, width = len(rows), len(rows[0])
    plane0, plane1 = [], []
    for row in rows:
        for cell in row:
            word0, word1 = LEGEND[cell]
            plane0.append(word0)
            plane1.append(word1)
    for (x, y), word in (terminals or {}).items():
        plane0[linear_index(x, y, width)] = word
    return MapDocument("u", 1, NativeName.from_text("T"),
                       MapPlanes(width, height,
                                 (tuple(plane0), tuple(plane1),
                                  (0,) * (width * height))))


def codes(document, **kwargs):
    return [p.code for p in validate_map(document, CATALOG, **kwargs)]


class OpenRoutes(unittest.TestCase):
    def test_it_reaches_an_open_room(self):
        reach = analyse(draw(["#####",
                              "#@..#",
                              "#####"]), CATALOG)
        self.assertTrue(reach.started)
        self.assertEqual(len(reach.reached), 3)

    def test_a_wall_stops_it(self):
        document = draw(["#####",
                         "#@#.#",
                         "#####"])
        self.assertEqual(len(analyse(document, CATALOG).reached), 1)

    def test_a_plain_door_does_not(self):
        # Every door in the game opens on use; only a lock stops anyone.
        document = draw(["#####",
                         "#@D.#",
                         "#####"])
        self.assertEqual(len(analyse(document, CATALOG).reached), 3)

    def test_isolated_floor_is_reported(self):
        document = draw(["#####",
                         "#@#.#",
                         "##X##"])
        self.assertEqual(len(unreachable_floor(document, analyse(document, CATALOG))), 2)

    def test_no_start_reaches_nothing(self):
        reach = analyse(draw(["###", "#.#", "###"]), CATALOG)
        self.assertFalse(reach.started)
        self.assertEqual(reach.reached, set())


class Keys(unittest.TestCase):
    def test_a_card_on_the_floor_opens_its_door(self):
        document = draw(["#######",
                         "#@.b.B#",
                         "#######"])
        reach = analyse(document, CATALOG)
        self.assertIn("BLUE", reach.keys)

    def test_a_door_without_its_card_stays_shut(self):
        document = draw(["######",
                         "#@.B.#",
                         "######"])
        reach = analyse(document, CATALOG)
        self.assertNotIn("BLUE", reach.keys)
        self.assertIn("BLUE", reach.blocked)
        # The cell past the door was never reached.
        self.assertNotIn(linear_index(4, 1, 6), reach.reached)

    def test_a_terminal_grants_its_card(self):
        # Terminals are how Corridor 7 usually hands cards out: the player
        # stands next to the wall unit and uses it.
        document = draw(["######",
                         "#@.T.#",
                         "######"], terminals={(3, 1): 11})
        reach = analyse(document, CATALOG)
        self.assertIn("BLUE", reach.keys)

    def test_a_card_behind_its_own_door_is_a_warning(self):
        # The one key layout that is always a mistake: the fixpoint stops with
        # the colour still blocking and its card still out of reach.
        document = draw(["#######",
                         "#@.B.b#",
                         "#######"])
        self.assertIn("C7E-DOOR-004", codes(document))

    def test_a_card_in_front_of_its_door_is_not(self):
        document = draw(["#######",
                         "#@.b.B#",
                         "#######"])
        self.assertNotIn("C7E-DOOR-004", codes(document))

    def test_two_colours_in_sequence_resolve(self):
        # Blue opens the way to red, which opens the way onward: the fixpoint
        # has to run more than once to see it.
        document = draw(["##########",
                         "#@.b.B.r.#",
                         "##########"])
        reach = analyse(document, CATALOG)
        self.assertEqual(reach.keys, {"BLUE", "RED"})


class Transporters(unittest.TestCase):
    def test_a_pair_links_both_ends(self):
        # Both endpoints on the SAME channel: a pair, not two channels.
        document = draw(["#######",
                         "#@1#1.#",
                         "#######"])
        reach = analyse(document, CATALOG)
        self.assertIn(linear_index(5, 1, 7), reach.reached)

    def test_an_unpaired_channel_links_nothing(self):
        # Three endpoints is its own error; guessing which two were meant would
        # turn one clear problem into a wrong route.
        document = draw(["########",
                         "#@1#1.1#",
                         "########"])
        reach = analyse(document, CATALOG)
        self.assertNotIn(linear_index(5, 1, 8), reach.reached)


class Exits(unittest.TestCase):
    def test_a_reachable_exit_is_fine(self):
        self.assertNotIn("C7E-EXIT-001", codes(draw(["#####",
                                                     "#@.X#",
                                                     "#####"])))

    def test_no_exit_at_all_warns(self):
        problems = validate_map(draw(["#####", "#@..#", "#####"]), CATALOG)
        exit_problems = [p for p in problems if p.code == "C7E-EXIT-001"]
        self.assertEqual(len(exit_problems), 1)
        self.assertEqual(exit_problems[0].severity, Severity.WARNING)

    def test_an_unreachable_exit_warns(self):
        self.assertIn("C7E-EXIT-001", codes(draw(["#####",
                                                  "#@#X#",
                                                  "#####"])))

    def test_a_switch_in_a_wall_counts_as_reachable(self):
        # An elevator switch is a wall the player stands next to and uses; they
        # never stand on it, and asking whether the cell itself was flooded
        # would report every elevator in the game as unreachable.
        document = draw(["#####",
                         "#@..#",
                         "#####"], terminals={(3, 2): 63})
        self.assertNotIn("C7E-EXIT-001", codes(document))

    def test_a_deathmatch_arena_needs_no_exit(self):
        document = draw(["#####", "#@..#", "#####"])
        self.assertNotIn("C7E-EXIT-001", codes(document, profile=DEATHMATCH))


class Profiles(unittest.TestCase):
    def test_a_second_start_is_an_error_for_one_player(self):
        self.assertIn("C7E-START-002", codes(draw(["######",
                                                   "#@..@#",
                                                   "######"])))

    def test_and_is_fine_in_an_arena(self):
        self.assertNotIn("C7E-START-002", codes(draw(["######",
                                                      "#@..@#",
                                                      "######"]),
                                                profile=DEATHMATCH))


if __name__ == "__main__":
    unittest.main()
