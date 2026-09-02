# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Map packs: escaping, graph rules, the generated lump, and the content audit.

The generator's output is read by a scanner this test cannot run, so the tests
that matter most are the ones about what must never reach it: a name that ends
a block early, a route to a level the pack does not carry, a campaign that
cannot be finished. `tools/test_ec7edit_e11.sh` runs the other half against the
real engine.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core.campaign import (
    Campaign, CampaignEntry, MAX_LEVEL_NAME, Route, STOCK_SLOTS, audit_pack,
    build_pack, generate_manifest, generate_mapinfo, quote, validate,
)
from ec7edit_core.document import MapDocument, SourceReference, new_uuid
from ec7edit_core.errors import ExportError, Severity
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.wad import decode_wad


def a_map(slot: int, *, secret_elevator: bool = False, source=None) -> MapDocument:
    """A small legal map, optionally with the marker-99 secret elevator on it."""
    w = h = 8
    walls = [1] * (w * h)
    objects = [0] * (w * h)
    zones = [1] * (w * h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            walls[y * w + x] = 0
    objects[1 * w + 1] = 19
    if secret_elevator:
        walls[2 * w + 2] = 63
        objects[2 * w + 2] = 99
    return MapDocument(
        uuid=new_uuid(), slot=slot, native_name=NativeName.from_text(f"M{slot}"),
        planes=MapPlanes(w, h, (tuple(walls), tuple(objects), tuple(zones))),
        source=source,
    )


def a_campaign(**kwargs) -> Campaign:
    entries = kwargs.pop("entries", (
        CampaignEntry(61, "One", next=Route(62)),
        CampaignEntry(62, "Two", next=Route(None)),
    ))
    return Campaign(title=kwargs.pop("title", "Trial"), key=kwargs.pop("key", "T"),
                    entries=entries)


def codes(problems) -> set:
    return {problem.code for problem in problems}


class Escaping(unittest.TestCase):
    """The three escapes `Scanner::Unescape` knows, and nothing invented."""

    def test_a_plain_name_is_quoted(self):
        self.assertEqual(quote("The Way In"), '"The Way In"')

    def test_a_quote_cannot_end_the_block_early(self):
        # Without the escape this would close the string and leave `}` loose in
        # the middle of a map block -- the whole reason names are not pasted in.
        self.assertEqual(quote('say "hi"'), '"say \\"hi\\""')

    def test_a_backslash_escapes_before_the_quote_does(self):
        # `\\` first, or escaping the quote would then re-escape its own
        # backslash. Same ordering rule as the engine's escapeCharacters table.
        self.assertEqual(quote('a\\b"c'), '"a\\\\b\\"c"')

    def test_a_control_byte_is_refused_rather_than_written(self):
        for hostile in ("line\nbreak", "tab\there", "nul\x00byte", "bell\x07"):
            with self.subTest(hostile=hostile):
                with self.assertRaises(ExportError) as caught:
                    quote(hostile)
                self.assertEqual(caught.exception.diagnostic.code, "C7E-PACK-002")

    def test_a_name_the_engine_has_no_glyph_for_is_refused(self):
        with self.assertRaises(ExportError):
            quote("café")

    def test_a_hostile_name_cannot_reach_the_lump(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, 'evil"\n}\nmap "MAP01" "pwned"', next=Route(None)),
        ))
        problems = validate(campaign, [a_map(61)])
        self.assertIn("C7E-PACK-002", codes(problems))
        with self.assertRaises(ExportError):
            build_pack(campaign, [a_map(61)])


class Graph(unittest.TestCase):
    def test_a_route_to_a_level_the_pack_does_not_carry(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(99)),
        ))
        self.assertIn("C7E-PACK-003", codes(validate(campaign, [a_map(61)])))

    def test_a_campaign_that_can_never_end(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(62)),
            CampaignEntry(62, "Two", next=Route(61)),
        ))
        self.assertIn("C7E-PACK-007", codes(validate(campaign, [a_map(61), a_map(62)])))

    def test_a_secret_branch_counts_as_a_way_to_finish(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(62), secret=Route(None)),
            CampaignEntry(62, "Two", next=Route(61)),
        ))
        problems = validate(campaign, [a_map(61, secret_elevator=True), a_map(62)])
        self.assertNotIn("C7E-PACK-007", codes(problems))

    def test_an_entry_with_no_map(self):
        campaign = a_campaign(entries=(CampaignEntry(61, "One", next=Route(None)),))
        self.assertIn("C7E-PACK-004", codes(validate(campaign, [])))

    def test_a_map_no_route_reaches_is_a_warning_not_an_error(self):
        campaign = a_campaign()
        problems = [p for p in validate(campaign, [a_map(61), a_map(62), a_map(63)])
                    if p.code == "C7E-PACK-004"]
        self.assertEqual([p.severity for p in problems], [Severity.WARNING])

    def test_two_levels_cannot_claim_one_slot(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(None)),
            CampaignEntry(61, "Also one", next=Route(None)),
        ))
        self.assertIn("C7E-PACK-004", codes(validate(campaign, [a_map(61)])))


class Bounds(unittest.TestCase):
    def test_a_stock_slot_warns_that_it_replaces_a_shipped_level(self):
        campaign = a_campaign(entries=(CampaignEntry(1, "One", next=Route(None)),))
        problems = [p for p in validate(campaign, [a_map(1)]) if p.code == "C7E-PACK-005"]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].severity, Severity.WARNING)

    def test_a_slot_above_the_stock_range_does_not_warn(self):
        self.assertNotIn("C7E-PACK-005", codes(validate(a_campaign(), [a_map(61), a_map(62)])))
        self.assertGreater(61, STOCK_SLOTS)

    def test_an_overlong_name(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "x" * (MAX_LEVEL_NAME + 1), next=Route(None)),
        ))
        self.assertIn("C7E-PACK-006", codes(validate(campaign, [a_map(61)])))

    def test_music_must_be_a_lump_name(self):
        for bad in ("not a lump", "waytoolonganame", "9leading", "semi;colon"):
            with self.subTest(bad=bad):
                campaign = a_campaign(entries=(
                    CampaignEntry(61, "One", next=Route(None), music=bad),
                ))
                self.assertIn("C7E-PACK-006", codes(validate(campaign, [a_map(61)])))

    def test_a_real_music_lump_is_accepted(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(None), music="C7MUS07"),
        ))
        self.assertNotIn("C7E-PACK-006", codes(validate(campaign, [a_map(61)])))


class SecretExits(unittest.TestCase):
    """A secret route needs something in the map that can fire one."""

    def test_a_secret_route_without_the_marker_warns(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(None), secret=Route(62)),
            CampaignEntry(62, "Two", next=Route(None)),
        ))
        problems = validate(campaign, [a_map(61), a_map(62)])
        self.assertIn("C7E-PACK-008", codes(problems))

    def test_marker_99_on_an_elevator_switch_satisfies_it(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(None), secret=Route(62)),
            CampaignEntry(62, "Two", next=Route(None)),
        ))
        problems = validate(campaign, [a_map(61, secret_elevator=True), a_map(62)])
        self.assertNotIn("C7E-PACK-008", codes(problems))


class RetailContent(unittest.TestCase):
    """A pack is made to be given away, so it may not carry Corridor 7's maps."""

    def test_an_imported_map_blocks_the_pack(self):
        source = SourceReference(display_path="MAPTEMP.CO7", sha256="a" * 64,
                                 map_number=1, imported_at="2026-01-01T00:00:00Z")
        campaign = a_campaign(entries=(CampaignEntry(61, "One", next=Route(None)),))
        documents = [a_map(61, source=source)]
        problems = validate(campaign, documents)
        self.assertIn("C7E-PACK-009", codes(problems))
        with self.assertRaises(ExportError):
            build_pack(campaign, documents)

    def test_a_map_the_author_drew_is_fine(self):
        self.assertNotIn("C7E-PACK-009", codes(validate(a_campaign(), [a_map(61), a_map(62)])))


class Generated(unittest.TestCase):
    def setUp(self):
        self.campaign = a_campaign(entries=(
            CampaignEntry(61, "The Way In", next=Route(62), secret=Route(63),
                          music="C7MUS07", par=90, floor_number=1),
            CampaignEntry(62, "The Way Out", next=Route(None)),
            CampaignEntry(63, "Bonus", next=Route(62)),
        ))
        self.documents = [a_map(61, secret_elevator=True), a_map(62), a_map(63)]
        self.text = generate_mapinfo(self.campaign)

    def test_the_episode_replaces_the_stock_one(self):
        # Without clearepisodes the menu offers Corridor 7's episode as well,
        # and the player has to know which one starts the pack.
        self.assertIn("clearepisodes", self.text)
        self.assertIn('episode "MAP61"', self.text)

    def test_routing_is_written_as_the_engine_reads_it(self):
        self.assertIn('\tnext = "MAP62"', self.text)
        self.assertIn('\tsecretnext = "MAP63"', self.text)
        self.assertIn('\tnext = "EndTitle"', self.text)

    def test_the_tally_is_on_unless_it_is_turned_off(self):
        # The engine's key is the negative one, so "default" means writing
        # nothing. A generator that emitted `nointermission` by accident would
        # silently remove the tally from every level of every pack.
        self.assertNotIn("nointermission", self.text)
        quiet = generate_mapinfo(Campaign(title="T", key="T", entries=(
            CampaignEntry(61, "One", next=Route(None), intermission=False),)))
        self.assertIn("\tnointermission", quiet)

    def test_optional_keys_appear_only_when_set(self):
        self.assertIn('\tmusic = "C7MUS07"', self.text)
        self.assertIn("\tpar = 90", self.text)
        self.assertEqual(self.text.count("music ="), 1)
        self.assertEqual(self.text.count("par ="), 1)

    def test_generation_is_deterministic(self):
        self.assertEqual(generate_mapinfo(self.campaign), self.text)
        first = build_pack(self.campaign, self.documents).wad
        second = build_pack(self.campaign, self.documents).wad
        self.assertEqual(first, second)

    def test_the_manifest_says_the_recipient_needs_their_own_game(self):
        manifest = generate_manifest(self.campaign, self.documents)
        self.assertIn("Corridor 7", manifest)
        self.assertIn("own", manifest)
        self.assertIn("MAP61", manifest)


class Audit(unittest.TestCase):
    def setUp(self):
        self.pack = build_pack(a_campaign(), [a_map(61), a_map(62)])

    def test_a_built_pack_holds_only_what_it_should(self):
        report = self.pack.audit
        self.assertTrue(report.clean)
        self.assertEqual(report.markers, ("MAP61", "MAP62"))
        self.assertEqual(report.lump_names,
                         ("MAP61", "PLANES", "MAP62", "PLANES", "MAPINFO", "PACKINFO"))

    def test_the_audit_reads_the_file_rather_than_the_intention(self):
        # Anything else in the file is named, including a lump this tool would
        # never write. A pack is handed to other people; "I only wrote what I
        # meant to" is not a check.
        from ec7edit_core.wad import WadLump, encode_wad
        lumps = decode_wad(self.pack.wad)
        smuggled = encode_wad(list(lumps) + [WadLump("C7W0000", b"retail art")])
        report = audit_pack(smuggled)
        self.assertFalse(report.clean)
        self.assertIn("C7W0000", report.unexpected)

    def test_a_marker_without_planes_is_reported(self):
        from ec7edit_core.wad import WadLump, encode_wad
        report = audit_pack(encode_wad([WadLump("MAP61", b""), WadLump("MAPINFO", b"x")]))
        self.assertFalse(report.clean)


class Schema(unittest.TestCase):
    def test_a_campaign_survives_json(self):
        campaign = a_campaign(entries=(
            CampaignEntry(61, "One", next=Route(62), secret=Route(None), par=30),
            CampaignEntry(62, "Two", next=Route(None)),
        ))
        again = Campaign.from_json(campaign.to_json())
        self.assertEqual(again, campaign)

    def test_a_secret_route_to_the_end_is_not_lost(self):
        # `secret` is None for "no secret exit" and Route(None) for "the secret
        # exit finishes the campaign". Both serialise with a null slot, which is
        # why `has_secret` exists.
        entry = CampaignEntry(61, "One", next=Route(None), secret=Route(None))
        self.assertIsNotNone(CampaignEntry.from_json(entry.to_json(), "x").secret)
        plain = CampaignEntry(61, "One", next=Route(None))
        self.assertIsNone(CampaignEntry.from_json(plain.to_json(), "x").secret)

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(ExportError):
            Campaign.from_json({"title": "x", "surprise": 1})


if __name__ == "__main__":
    unittest.main()
