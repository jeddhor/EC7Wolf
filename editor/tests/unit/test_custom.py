# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Map words for custom content, and the translator that gives them meaning.

The property everything else rests on is that an allocation never moves. A word
is written into map data the moment somebody paints with it, so a word that
changed between sessions would silently make a map spawn something else -- with
the map file unchanged and looking perfectly correct.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core.custom import (
    OBJECT_BASE, WALL_FIRST, WALL_LAST, Allocation, allocate,
    generate_translator, load, store, used_by,
)
from ec7edit_core.document import MapDocument, new_uuid
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.resources import Resource, ResourceActor


def a_resource(digest="a" * 64, actors=("Flower",), textures=(), sprites=None) -> Resource:
    return Resource(
        display_path=f"/packs/{digest[:4]}.pk3", sha256=digest, entries=9,
        total_bytes=1000,
        actors=tuple(ResourceActor(name, "C7Rodex", "", name[:4].upper(), "DECORATE")
                     for name in actors),
        sprites=tuple(sprites if sprites is not None
                      else (f"{n[:4].upper()}A0" for n in actors)),
        textures=tuple(textures))


def a_map(words=(), slot=61) -> MapDocument:
    w = h = 12
    walls = [1] * (w * h)
    objects = [0] * (w * h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            walls[y * w + x] = 256
    for index, word in enumerate(words):
        objects[(3 + index) * w + 3] = word
    return MapDocument(uuid=new_uuid(), slot=slot,
                       native_name=NativeName.from_text("M"),
                       planes=MapPlanes(w, h, (tuple(walls), tuple(objects),
                                               tuple([0] * (w * h)))))


class Allocating(unittest.TestCase):
    def test_an_actor_gets_a_word_from_the_high_band(self):
        allocations, problems = allocate([], [a_resource()])
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0].word, OBJECT_BASE)
        self.assertEqual(allocations[0].plane, 1)
        self.assertEqual(problems, [])

    def test_a_word_once_given_never_moves(self):
        # The whole point. Allocating again with the resource listed in a
        # different order, or with another pack in front of it, must not
        # renumber anything: maps already contain these words.
        first, _ = allocate([], [a_resource(actors=("Flower",))])
        second, _ = allocate(first, [a_resource(digest="b" * 64, actors=("Beetle",)),
                                     a_resource(actors=("Flower",))])
        flower = next(a for a in second if a.name == "Flower")
        self.assertEqual(flower.word, first[0].word)

    def test_a_second_actor_gets_the_next_word(self):
        allocations, _ = allocate([], [a_resource(actors=("Flower", "Beetle"))])
        self.assertEqual(sorted(a.word for a in allocations),
                         [OBJECT_BASE, OBJECT_BASE + 1])

    def test_an_actor_that_cannot_be_placed_gets_nothing(self):
        resource = Resource(display_path="/p.pk3", sha256="c" * 64, entries=1,
                            total_bytes=1,
                            actors=(ResourceActor("Base", "", "", "", "DECORATE"),))
        allocations, _ = allocate([], [resource])
        self.assertEqual(allocations, [])

    def test_two_packs_defining_one_class_is_an_error(self):
        _, problems = allocate([], [a_resource(digest="d" * 64, actors=("Flower",)),
                                    a_resource(digest="e" * 64, actors=("Flower",))])
        self.assertTrue(any(p.code == "C7E-CUSTOM-002" for p in problems))

    def test_a_detached_pack_keeps_its_words_and_says_so(self):
        # The words may already be in a map. Forgetting them would be worse
        # than reporting them.
        first, _ = allocate([], [a_resource()])
        kept, problems = allocate(first, [])
        self.assertEqual(kept, first)
        self.assertTrue(any(p.code == "C7E-CUSTOM-005" for p in problems))

    def test_a_texture_repoints_a_wall_id_rather_than_taking_a_new_word(self):
        # 256 and up is a floor cell carrying a sound area, so a custom texture
        # cannot have a high word; it re-points a wall ID instead.
        allocations, _ = allocate([], [a_resource(actors=(), textures=("MYWALL",))])
        self.assertEqual(allocations[0].plane, 0)
        self.assertTrue(WALL_FIRST <= allocations[0].word <= WALL_LAST)

    def test_a_wall_id_a_map_already_uses_is_not_taken(self):
        taken = a_map()
        planes = list(taken.planes.planes)
        walls = list(planes[0])
        walls[0] = WALL_LAST
        document = taken.with_planes(MapPlanes(taken.width, taken.height,
                                               (tuple(walls), planes[1], planes[2])))
        allocations, _ = allocate([], [a_resource(actors=(), textures=("MYWALL",))],
                                  [document])
        self.assertNotEqual(allocations[0].word, WALL_LAST)

    def test_a_texture_name_the_engine_cannot_look_up(self):
        _, problems = allocate([], [a_resource(actors=(), textures=("a name with spaces",))])
        self.assertTrue(any(p.code == "C7E-CUSTOM-004" for p in problems))

    def test_the_table_survives_the_project_file(self):
        allocations, _ = allocate([], [a_resource(actors=("Flower", "Beetle"))])
        self.assertEqual(load(store(allocations)), allocations)

    def test_which_allocations_a_map_actually_uses(self):
        allocations, _ = allocate([], [a_resource(actors=("Flower", "Beetle"))])
        document = a_map(words=(allocations[0].word,))
        self.assertEqual([a.name for a in used_by(document, allocations)],
                         [allocations[0].name])


class Translator(unittest.TestCase):
    def setUp(self):
        self.allocations, _ = allocate([], [a_resource(actors=("Flower",),
                                                       textures=("MYWALL",))])
        self.text = generate_translator(self.allocations)

    def test_it_builds_on_the_games_own(self):
        # include, not a copy: LoadXlat keeps the included tables, so this adds
        # a word rather than replacing everything Corridor 7 defines.
        self.assertIn('include "xlat/corridor7.txt"', self.text)

    def test_an_actor_becomes_a_things_entry(self):
        word = next(a.word for a in self.allocations if a.kind == "actor")
        self.assertIn(f"{{{word}, Flower, 0, 0, 0}}", self.text)

    def test_a_texture_becomes_a_tile_on_all_four_sides(self):
        word = next(a.word for a in self.allocations if a.kind == "texture")
        self.assertIn(f"tile {word}", self.text)
        self.assertEqual(self.text.count('"MYWALL"'), 4)

    def test_nothing_allocated_writes_no_blocks(self):
        text = generate_translator([])
        self.assertNotIn("things", text)
        self.assertNotIn("tiles", text)

    def test_generation_is_deterministic(self):
        self.assertEqual(generate_translator(self.allocations), self.text)


if __name__ == "__main__":
    unittest.main()
