#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E2: the XLAT and DECORATE readers, and the catalogue they join into.

The catalogue is generated from files that live in this repository and change,
so most of these tests are about the join staying honest as they do: every raw
value the translation can spawn must resolve to exactly one entry, no two
entries may claim the same key, and anything that will not join must be
reported rather than filled in with a guess.

The committed catalogue is checked against its inputs here as well as in the
gate, because a stale catalogue is the failure that would otherwise show up as
the editor quietly describing a game the engine no longer plays.
"""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
REPO = EDITOR.parent
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import (
    CATEGORIES,
    Curation,
    build_catalog,
    catalog_from_json,
    catalog_to_json,
    load_catalog,
)
from ec7edit_core.decorate import classify, parse_decorate, read_actors_from_source, resolve_roles
from ec7edit_core.xlat import DIRECTIONS_4, DIRECTIONS_8, parse_xlat, read_xlat

XLAT_PATH = REPO / "wadsrc" / "static" / "xlat" / "corridor7.txt"
ACTOR_PATH = REPO / "wadsrc" / "static" / "actors" / "corridor7"
CURATED = EDITOR / "resources" / "catalog_sources.json"
GENERATED = EDITOR / "resources" / "editor_catalog.json"

SYNTHETIC_XLAT = """
/* a comment { with a brace } to confuse a naive parser */
tiles
{
    trigger 251 { action = "Door_Open"; arg1 = 16; playeruse = true; }
    tile 1 { texturenorth = "C7W0000"; texturesouth = "C7W0000"; }
    tile 2 { texturenorth = "C7W0001"; texturesouth = "C7W0001"; }
    zone 256 {}
    modzone 278 fillzone ambush;
}
things
{
    ignore 18;
    trigger 98 { action = "Pushwall_Move"; arg1 = 8; secret = true; }
    {19, $Player1Start, 4, 0, 0}
    {23, C7Static000, 0, 0, 0}   // a static
    {108, C7Alien, 4, 0, 1}
    {112, C7Alien, 4, PATHING, 1}
    {90, PatrolPoint, 8, 0, 0}
}
"""

SYNTHETIC_DECORATE = """
// A comment above the actor becomes its note.
actor C7Alien : C7Monster
{
    states { Spawn: C100 A -1 stop
             See: C101 ABCD 6 loop }
}
actor C7Monster : WolfensteinMonster { }
actor C7Static000 { states { Spawn: C001 A -1 stop } }
actor C7Card : Key { states { Spawn: C002 A -1 stop } }
"""


class XlatParsing(unittest.TestCase):
    def setUp(self):
        self.xlat = parse_xlat(SYNTHETIC_XLAT)

    def test_reads_tiles_and_their_textures(self):
        self.assertEqual(self.xlat.tiles[1].texture, "C7W0000")
        self.assertTrue(self.xlat.tiles[1].uniform)

    def test_reads_triggers_in_both_sections(self):
        self.assertEqual(self.xlat.tile_triggers[251].action, "Door_Open")
        self.assertIn("playeruse", self.xlat.tile_triggers[251].flags)
        self.assertEqual(self.xlat.thing_triggers[98].action, "Pushwall_Move")
        self.assertIn("secret", self.xlat.thing_triggers[98].flags)

    def test_reads_zones_and_modifiers(self):
        self.assertEqual(self.xlat.zones[256].modifiers, ())
        self.assertEqual(self.xlat.zones[278].modifiers, ("fillzone", "ambush"))

    def test_reads_ignores_per_section(self):
        self.assertIn(18, self.xlat.ignored["things"])

    def test_a_brace_in_a_comment_does_not_end_the_block(self):
        # The block finder counts braces; a comment containing one would close
        # `tiles` early and lose everything after it.
        self.assertEqual(len(self.xlat.tiles), 2)

    def test_four_angles_expand_to_four_values(self):
        alien = self.xlat.thing_for(108)
        self.assertEqual(list(alien.values), [108, 109, 110, 111])
        self.assertEqual(
            [alien.direction_for(v) for v in alien.values], list(DIRECTIONS_4)
        )

    def test_eight_angles_expand_to_eight(self):
        patrol = self.xlat.thing_for(90)
        self.assertEqual(len(list(patrol.values)), 8)
        self.assertEqual(patrol.direction_for(97), DIRECTIONS_8[7])

    def test_pathing_flag(self):
        self.assertFalse(self.xlat.thing_for(108).pathing)
        self.assertTrue(self.xlat.thing_for(112).pathing)

    def test_a_value_with_no_facing_has_no_direction(self):
        self.assertEqual(self.xlat.thing_for(23).direction_for(23), "")

    def test_the_dollar_prefix_is_stripped(self):
        self.assertEqual(self.xlat.thing_for(19).classname, "Player1Start")


class DecorateParsing(unittest.TestCase):
    def setUp(self):
        self.actors = resolve_roles(parse_decorate(SYNTHETIC_DECORATE, "monsters"))

    def test_finds_every_actor(self):
        self.assertEqual(
            set(self.actors), {"C7Alien", "C7Monster", "C7Static000", "C7Card"}
        )

    def test_spawn_sprite_is_the_spawn_states_page(self):
        self.assertEqual(self.actors["C7Alien"].spawn_sprite, 100)
        self.assertIn(101, self.actors["C7Alien"].sprites)

    def test_states_are_recorded_per_page(self):
        self.assertIn("See", self.actors["C7Alien"].states[101])

    def test_the_comment_above_becomes_the_note(self):
        self.assertIn("note", self.actors["C7Alien"].note)

    def test_role_follows_the_inheritance_chain(self):
        # C7Alien -> C7Monster -> WolfensteinMonster, two links away.
        self.assertEqual(self.actors["C7Alien"].role, "enemy")

    def test_a_key_is_an_item_wherever_it_is_declared(self):
        self.assertEqual(self.actors["C7Card"].role, "item")

    def test_an_unrooted_actor_beside_monsters_is_an_effect(self):
        actors = resolve_roles(parse_decorate("actor C7Bolt { }", "monsters"))
        self.assertEqual(actors["C7Bolt"].role, "effect")

    def test_an_unrooted_actor_among_statics_is_a_decoration(self):
        actors = resolve_roles(parse_decorate("actor C7Thing { }", "statics"))
        self.assertEqual(actors["C7Thing"].role, "decoration")

    def test_classification_terminates_on_a_cycle(self):
        # A malformed pair that inherits from each other must not hang.
        actors = resolve_roles(
            parse_decorate("actor A : B { }\nactor B : A { }", "statics")
        )
        self.assertEqual(actors["A"].role, "decoration")


class SyntheticCatalog(unittest.TestCase):
    def setUp(self):
        self.catalog = build_catalog(
            parse_xlat(SYNTHETIC_XLAT),
            resolve_roles(parse_decorate(SYNTHETIC_DECORATE, "monsters")),
        )

    def test_every_category_is_a_known_one(self):
        for entry in self.catalog:
            self.assertIn(entry.category, CATEGORIES)

    def test_walls_come_from_tiles(self):
        entry = self.catalog.by_key("wall.001")
        self.assertEqual(entry.texture, "C7W0000")
        self.assertEqual(entry.placement, "wall")

    def test_the_enemy_carries_its_directions(self):
        entry = self.catalog.for_value(1, 109)
        self.assertEqual(entry.actor, "C7Alien")
        self.assertEqual(dict(entry.directions)["north"], 109)

    def test_stand_and_patrol_are_separate_entries(self):
        stand = self.catalog.for_value(1, 108)
        patrol = self.catalog.for_value(1, 112)
        self.assertNotEqual(stand.key, patrol.key)
        self.assertEqual(patrol.variant, "patrol")

    def test_an_unplaceable_actor_is_reported(self):
        self.assertTrue(any("C7Card" in line for line in self.catalog.unresolved))

    def test_lookup_by_value_covers_the_whole_band(self):
        for value in (108, 109, 110, 111):
            self.assertIsNotNone(self.catalog.for_value(1, value))


class RealCatalog(unittest.TestCase):
    """Against the repository's own translation and actors."""

    @classmethod
    def setUpClass(cls):
        cls.xlat = read_xlat(XLAT_PATH)
        cls.actors = read_actors_from_source(ACTOR_PATH)
        cls.curation = Curation.load(CURATED)
        cls.catalog = build_catalog(cls.xlat, cls.actors, cls.curation)

    def test_every_spawnable_value_resolves(self):
        missing = [v for v in self.xlat.thing_values() if self.catalog.for_value(1, v) is None]
        self.assertEqual(missing, [], "plane-1 values with no catalogue entry")

    def test_every_tile_resolves(self):
        missing = [v for v in self.xlat.tiles if self.catalog.for_value(0, v) is None]
        self.assertEqual(missing, [])

    def test_keys_are_unique(self):
        duplicates = [k for k, n in Counter(e.key for e in self.catalog).items() if n > 1]
        self.assertEqual(duplicates, [])

    def test_no_two_entries_claim_the_same_value_on_a_plane(self):
        seen = {}
        clashes = []
        for entry in self.catalog:
            for value in entry.values:
                key = (entry.plane, value)
                if key in seen:
                    clashes.append(f"plane {entry.plane} value {value}: "
                                   f"{seen[key]} and {entry.key}")
                seen[key] = entry.key
        self.assertEqual(clashes, [])

    def test_the_curated_names_are_applied(self):
        self.assertEqual(self.catalog.by_key("thing.c7static001").name, "RED access card")
        self.assertEqual(
            self.catalog.for_value(1, 108).name, "Alioprobe"
        )

    def test_enemies_have_sprites_to_draw(self):
        for entry in self.catalog.in_category("enemies"):
            self.assertIsNotNone(entry.sprite, entry.key)

    def test_every_entry_can_be_searched_for_by_its_raw_value(self):
        for entry in self.catalog:
            self.assertIn(entry, self.catalog.search(str(entry.value)))

    def test_search_finds_a_curated_alias(self):
        names = [e.name for e in self.catalog.search("keycard")]
        self.assertIn("RED access card", names)

    def test_generation_is_deterministic(self):
        again = build_catalog(self.xlat, self.actors, self.curation)
        self.assertEqual(catalog_to_json(again), catalog_to_json(self.catalog))

    def test_json_round_trip(self):
        self.assertEqual(catalog_from_json(catalog_to_json(self.catalog)).entries,
                         self.catalog.entries)

    def test_the_committed_catalogue_matches_its_inputs(self):
        self.assertTrue(GENERATED.exists(), "run scripts/generate_catalog.py write")
        self.assertEqual(
            GENERATED.read_text(encoding="utf-8"),
            catalog_to_json(self.catalog),
            "editor_catalog.json is stale; regenerate it and review the diff",
        )

    def test_the_committed_catalogue_loads(self):
        self.assertEqual(len(load_catalog(GENERATED)), len(self.catalog))

    def test_no_pixels_are_serialised(self):
        # The catalogue names sprite pages. If it ever carried image data it
        # would stop being a file this project may distribute.
        text = GENERATED.read_text(encoding="utf-8")
        for marker in ("data:image", "iVBOR", "base64", "\\u0000"):
            self.assertNotIn(marker, text)

    def test_unresolved_joins_are_reported_not_hidden(self):
        for line in self.catalog.unresolved:
            self.assertTrue(line.strip())


if __name__ == "__main__":
    unittest.main(verbosity=1)
