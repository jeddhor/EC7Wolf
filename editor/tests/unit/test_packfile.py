# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The pk3 a pack becomes once it carries somebody's art.

The layout is the engine's and one part of it is easy to get wrong: maps go in
`maps/MAPxx.wad`. Archive entries are sorted alphabetically when a zip is read,
so a root MAP61 is followed by MAPINFO rather than PLANES and the engine
refuses the map. `tools/test_ec7edit_e13.sh` proves the other half -- that the
engine plays what this writes.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core.campaign import Campaign, CampaignEntry, Route
from ec7edit_core.custom import allocate
from ec7edit_core.document import MapDocument, new_uuid
from ec7edit_core.errors import ExportError
from ec7edit_core.names import NativeName
from ec7edit_core.packfile import audit_pk3, build_resource_pack
from ec7edit_core.planes import MapPlanes
from ec7edit_core.resources import inspect

DECORATE = """\
actor Flower : C7Rodex
{
    states
    {
    Spawn:
        FLWR A -1
        stop
    }
}
"""


def a_pack_file(path: Path, *, name="flower") -> Path:
    target = path / f"{name}.pk3"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("DECORATE", DECORATE)
        archive.writestr("sprites/FLWRA0.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
        archive.writestr("previews/sheet.png", b"not carried")
    return target


def a_map(word: int, slot: int = 61) -> MapDocument:
    w = h = 12
    walls = [1] * (w * h)
    objects = [0] * (w * h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            walls[y * w + x] = 256
    objects[3 * w + 3] = 19
    walls[2 * w + 3] = 63
    objects[6 * w + 6] = word
    return MapDocument(uuid=new_uuid(), slot=slot, native_name=NativeName.from_text("G"),
                       planes=MapPlanes(w, h, (tuple(walls), tuple(objects),
                                               tuple([0] * (w * h)))))


class Building(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.file = a_pack_file(self.root)
        self.resource = inspect(self.file)
        self.allocations, _ = allocate([], [self.resource])
        self.word = self.allocations[0].word
        self.campaign = Campaign(title="Trial", key="T", entries=(
            CampaignEntry(61, "The Garden", next=Route(None)),))
        self.pack = build_resource_pack(
            self.campaign, [a_map(self.word)], [self.resource], self.allocations,
            resource_files={self.resource.sha256: self.file})
        self.names = set(self.pack.audit.lump_names)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_map_is_an_embedded_wad_under_maps(self):
        # Not a root MAP61: entries are sorted when the zip is read, so a root
        # marker is followed by MAPINFO and the engine says "invalid map".
        self.assertIn("maps/MAP61.wad", self.names)
        self.assertNotIn("MAP61", self.names)

    def test_the_metadata_is_there(self):
        self.assertIn("MAPINFO", self.names)
        self.assertIn("PACKINFO", self.names)
        self.assertIn("xlat/ec7edit.txt", self.names)

    def test_each_resource_keeps_its_own_decorate_behind_one_root_include(self):
        # Two packs cannot both own the root lump name, and the engine's own
        # decorate.txt is written this way, so the parser is built for it.
        self.assertIn("decorate/flower.txt", self.names)
        self.assertIn("DECORATE", self.names)
        with zipfile.ZipFile(io.BytesIO(self.pack.pk3)) as archive:
            root = archive.read("DECORATE").decode()
        self.assertIn('#include "decorate/flower.txt"', root)

    def test_the_art_travels_and_the_authors_notes_do_not(self):
        self.assertIn("sprites/FLWRA0.png", self.names)
        self.assertNotIn("previews/sheet.png", self.names)

    def test_the_map_is_told_which_translator_to_use(self):
        self.assertIn('translator = "xlat/ec7edit.txt"', self.pack.mapinfo)

    def test_art_is_copied_byte_for_byte(self):
        # The editor has no reason to decode somebody's PNG and write it back,
        # and a re-encode is a chance to change art the author approved.
        with zipfile.ZipFile(self.file) as source, \
                zipfile.ZipFile(io.BytesIO(self.pack.pk3)) as built:
            self.assertEqual(source.read("sprites/FLWRA0.png"),
                             built.read("sprites/FLWRA0.png"))

    def test_the_same_project_builds_the_same_bytes(self):
        again = build_resource_pack(
            self.campaign, [a_map(self.word)], [self.resource], self.allocations,
            resource_files={self.resource.sha256: self.file})
        self.assertEqual(again.pk3, self.pack.pk3)

    def test_the_audit_accounts_for_everything(self):
        self.assertTrue(self.pack.audit.clean)
        self.assertEqual(self.pack.audit.markers, ("MAP61",))

    def test_the_audit_names_anything_it_did_not_expect(self):
        with zipfile.ZipFile(io.BytesIO(self.pack.pk3)) as archive:
            entries = {n: archive.read(n) for n in archive.namelist()}
        entries["surprise.exe"] = b"x"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        report = audit_pk3(buffer.getvalue())
        self.assertFalse(report.clean)
        self.assertIn("surprise.exe", report.unexpected)

    def test_a_resource_whose_file_is_missing_is_reported(self):
        pack = build_resource_pack(self.campaign, [a_map(self.word)],
                                   [self.resource], self.allocations,
                                   resource_files={})
        self.assertTrue(any(p.code == "C7E-RES-008" for p in pack.problems))
        self.assertNotIn("sprites/FLWRA0.png", set(pack.audit.lump_names))

    def test_a_campaign_that_cannot_be_built_is_refused(self):
        broken = Campaign(title="T", key="T", entries=(
            CampaignEntry(61, "Loop", next=Route(61)),))
        with self.assertRaises(ExportError):
            build_resource_pack(broken, [a_map(self.word)], [self.resource],
                                self.allocations,
                                resource_files={self.resource.sha256: self.file})


if __name__ == "__main__":
    unittest.main()
