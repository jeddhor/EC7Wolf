# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Resource packs: what is in one, and what a pack may not be.

A pack arrives from somebody else and is a zip, and zips lie -- about their
names, their sizes and their contents. Most of what is here is about refusing
one, which is the part that has to work when nobody is watching.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core.errors import ExportError, Severity
from ec7edit_core.resources import (
    MAX_ENTRIES, Resource, ResourceActor, inspect, make_additive,
    read_decorate,
)

DECORATE = """\
// A rooted melee ambusher.
actor GlassStalker : C7Rodex replaces C7Rodex
{
    health 50
    states
    {
    Spawn:
        GSTK AB 10 NOP A_Look
        loop
    Death:
        GSTK M 5 A_Scream
        stop
    }
}

actor GlassShard : C7Inert
{
    states
    {
    Spawn:
        SHRD A -1
        stop
    }
}

actor AbstractBase
{
}
"""


def a_pack(path: Path, *, decorate: str = DECORATE, sprites=("GSTKA0", "GSTKB0",
                                                             "GSTKM0", "SHRDA0"),
           extra: dict | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if decorate is not None:
            archive.writestr("DECORATE", decorate)
        for name in sprites:
            archive.writestr(f"sprites/{name}.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return path


class Reading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pack = a_pack(self.root / "stalker.pk3")

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_finds_the_actors_and_their_art(self):
        resource = inspect(self.pack)
        self.assertEqual([a.name for a in resource.actors],
                         ["GlassStalker", "GlassShard", "AbstractBase"])
        self.assertEqual(len(resource.sprites), 4)

    def test_an_actor_knows_what_it_inherits_and_replaces(self):
        stalker = inspect(self.pack).actors[0]
        self.assertEqual(stalker.parent, "C7Rodex")
        self.assertEqual(stalker.replaces, "C7Rodex")

    def test_the_sprite_comes_from_the_spawn_state(self):
        # Not the first frame in the file: what an editor should draw is what
        # the map looks like before anything moves.
        self.assertEqual(inspect(self.pack).actors[0].sprite, "GSTK")

    def test_a_class_with_no_frames_is_not_placeable(self):
        base = next(a for a in inspect(self.pack).actors if a.name == "AbstractBase")
        self.assertFalse(base.placeable)

    def test_replacing_a_stock_class_is_said_out_loud(self):
        # It is a global switch -- every map in the game, not only yours -- so
        # the editor says both that the pack asks for it and that it will not
        # be doing it unless told to.
        problems = inspect(self.pack).problems
        self.assertTrue(any("replace C7Rodex" in p.message for p in problems),
                        [p.message for p in problems])

    def test_art_an_actor_needs_but_the_pack_lacks_is_a_warning(self):
        pack = a_pack(self.root / "bare.pk3", sprites=("SHRDA0",))
        problems = inspect(pack).problems
        self.assertTrue(any(p.severity == Severity.WARNING and "GSTK" in p.message
                            for p in problems))

    def test_folders_the_engine_ignores_are_carried_not_lost(self):
        pack = a_pack(self.root / "docs.pk3",
                      extra={"previews/all.png": b"x", "docs/brief.md": b"y"})
        resource = inspect(pack)
        self.assertIn("docs/brief.md", resource.ignored)
        self.assertIn("previews/all.png", resource.ignored)


class Additive(unittest.TestCase):
    """`replaces` and placing something on a map contradict each other.

    A pack written to replace a stock class turns every one of them into its
    own actor while it is loaded -- so the word the editor allocated and the
    word the game already had both spawn the same thing, and the original
    cannot be placed at all. Proven against the engine in
    `tools/test_ec7edit_e13.sh`; this is the transformation behind it.
    """

    def test_replaces_comes_off_the_declaration(self):
        self.assertEqual(
            make_additive("actor A : B replaces B\n{\n}\n"),
            "actor A : B\n{\n}\n")

    def test_an_actor_with_no_parent_too(self):
        self.assertEqual(make_additive("actor A replaces B\n{\n}\n"),
                         "actor A\n{\n}\n")

    def test_everything_else_is_left_exactly_alone(self):
        # Including the comments, which are the author's explanation of what
        # the actor is, and the states, which are the whole file.
        before = ("// A rooted ambusher.\n"
                  "actor Flower : C7Semaj replaces C7Semaj\n"
                  "{\n    speed 0, 0\n"
                  "    // replaces nothing here; this is prose\n"
                  "    states\n    {\n    Spawn:\n        FLWR A -1\n"
                  "        stop\n    }\n}\n")
        after = make_additive(before)
        self.assertNotIn("replaces C7Semaj", after)
        self.assertIn("// replaces nothing here; this is prose", after)
        self.assertIn("FLWR A -1", after)
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))

    def test_a_file_with_nothing_to_change_is_unchanged(self):
        text = "actor A : B\n{\n}\n"
        self.assertEqual(make_additive(text), text)

    def test_a_pack_says_what_it_would_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = a_pack(Path(tmp) / "p.pk3")
            self.assertEqual(inspect(pack).replacements, ("C7Rodex",))

    def test_additive_is_the_default(self):
        # Placing something from the palette is supposed to mean placing it,
        # not swapping it for every instance of something else.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(inspect(a_pack(Path(tmp) / "p.pk3")).additive)

    def test_the_choice_survives_the_project_file(self):
        from dataclasses import replace as dc_replace
        with tempfile.TemporaryDirectory() as tmp:
            resource = dc_replace(inspect(a_pack(Path(tmp) / "p.pk3")), additive=False)
            self.assertFalse(Resource.from_json(resource.to_json()).additive)


class Refusing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def refuses(self, path, code):
        with self.assertRaises(ExportError) as caught:
            inspect(path)
        self.assertEqual(caught.exception.diagnostic.code, code)

    def test_something_that_is_not_a_zip(self):
        path = self.root / "not.pk3"
        path.write_bytes(b"this is not a zip file at all")
        self.refuses(path, "C7E-RES-002")

    def test_a_path_that_escapes_the_archive(self):
        # Nothing stops a zip naming ../../.bashrc. The editor never extracts a
        # pack, so this check has to be where the names are believed.
        path = self.root / "evil.pk3"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("sprites/A0.png", b"x")
            archive.writestr("../../../etc/passwd", b"x")
        self.refuses(path, "C7E-RES-003")

    def test_an_absolute_path(self):
        path = self.root / "abs.pk3"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("sprites/A0.png", b"x")
            archive.writestr("/etc/shadow", b"x")
        self.refuses(path, "C7E-RES-003")

    def test_corridor_sevens_own_data(self):
        path = self.root / "retail.pk3"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("sprites/A0.png", b"x")
            archive.writestr("MAPTEMP.CO7", b"x" * 100)
        self.refuses(path, "C7E-RES-004")

    def test_a_zip_holding_nothing_the_engine_reads(self):
        path = self.root / "empty.pk3"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", b"hello")
        self.refuses(path, "C7E-RES-006")

    def test_far_too_many_entries(self):
        path = self.root / "many.pk3"
        with zipfile.ZipFile(path, "w") as archive:
            for index in range(MAX_ENTRIES + 1):
                archive.writestr(f"sprites/S{index:05d}.png", b"x")
        self.refuses(path, "C7E-RES-005")


class Decorate(unittest.TestCase):
    def test_the_scan_stops_at_the_next_actor(self):
        # Two actors' bodies must not run together, or the second one's sprite
        # would be read out of the first.
        actors = read_decorate(DECORATE, "DECORATE")
        self.assertEqual(actors[1].sprite, "SHRD")

    def test_an_actor_with_no_parent(self):
        actors = read_decorate("actor Lonely\n{\nstates\n{\nSpawn:\nLONE A -1\nstop\n}\n}",
                               "DECORATE")
        self.assertEqual(actors[0].parent, "")
        self.assertEqual(actors[0].sprite, "LONE")


class Schema(unittest.TestCase):
    def test_a_resource_survives_json(self):
        resource = Resource(display_path="/x/y.pk3", sha256="a" * 64, entries=3,
                            total_bytes=99,
                            actors=(ResourceActor("A", "B", "C", "SPRT", "DECORATE"),),
                            sprites=("SPRTA0",))
        again = Resource.from_json(resource.to_json())
        self.assertEqual(again.actors[0].name, "A")
        self.assertEqual(again.sprites, ("SPRTA0",))

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(ExportError):
            Resource.from_json({"display_path": "x", "surprise": 1})


if __name__ == "__main__":
    unittest.main()
