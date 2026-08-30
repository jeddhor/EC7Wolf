#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E1: the `ec7edit` command line.

Exercised through `main()` with real files in a temporary tree, because the
things worth testing about a CLI -- exit codes, refusing to write the wrong
path, leaving the source alone -- are exactly the things a unit test of the
handler functions would skip.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.archive import MapRecord, encode_archive
from ec7edit_core.cli import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from ec7edit_core.names import NativeName
from ec7edit_core.planes import MapPlanes
from ec7edit_core.wad import read_preview_wad


def record(number, name, width=4, height=4) -> MapRecord:
    planes = tuple(
        tuple((plane * 13 + cell + number) % 256 for cell in range(width * height))
        for plane in range(3)
    )
    return MapRecord(number, NativeName.from_text(name), MapPlanes(width, height, planes))


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.archive = self.data / "MAPTEMP.CO7"
        self.records = [record(1, "FIRST"), record(2, "SECOND"), record(3, "THIRD")]
        self.archive.write_bytes(encode_archive(self.records))
        self.before = self.archive.read_bytes()
        self.work = self.root / "work"
        self.work.mkdir()

    def tearDown(self):
        self.assertEqual(self.archive.read_bytes(), self.before, "the source was modified")
        self._tmp.cleanup()


class Inspect(Fixture):
    def test_lists_every_map(self):
        code, out, _ = run("inspect", str(self.archive))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("3 maps", out)
        for name in ("FIRST", "SECOND", "THIRD"):
            self.assertIn(name, out)

    def test_json_is_machine_readable(self):
        code, out, _ = run("inspect", str(self.archive), "--json")
        self.assertEqual(code, EXIT_OK)
        report = json.loads(out)
        self.assertEqual(report["map_count"], 3)
        self.assertEqual([m["lump"] for m in report["maps"]], ["MAP01", "MAP02", "MAP03"])
        self.assertEqual(report["maps"][0]["name_raw"], self.records[0].name.raw.hex())

    def test_a_malformed_archive_fails_cleanly(self):
        broken = self.work / "broken.co7"
        broken.write_bytes(b"not a TED5 archive at all")
        code, _, err = run("inspect", str(broken))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-NATIVE-001", err)

    def test_a_missing_file_fails_cleanly(self):
        code, _, err = run("inspect", str(self.work / "absent.co7"))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("No such file", err)


class Validate(Fixture):
    def test_a_good_archive_passes(self):
        code, out, _ = run("validate", str(self.archive))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("0 diagnostic", out)

    def test_a_preserved_noncanonical_name_is_not_an_error(self):
        raw = b"SLOT\x00\x001\x00" + b"\x00" * 8
        odd = self.work / "odd.co7"
        odd.write_bytes(encode_archive([MapRecord(1, NativeName.from_raw(raw), MapPlanes.empty(2, 2))]))
        code, out, _ = run("validate", str(odd))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("C7E-NATIVE-007", out)

    def test_strict_rejects_what_normal_accepts(self):
        raw = b"SLOT\x00\x001\x00" + b"\x00" * 8
        odd = self.work / "odd.co7"
        odd.write_bytes(encode_archive([MapRecord(1, NativeName.from_raw(raw), MapPlanes.empty(2, 2))]))
        self.assertEqual(run("validate", str(odd))[0], EXIT_OK)
        self.assertEqual(run("validate", str(odd), "--strict")[0], EXIT_ERROR)

    def test_a_malformed_archive_fails(self):
        broken = self.work / "broken.co7"
        broken.write_bytes(b"")
        self.assertEqual(run("validate", str(broken))[0], EXIT_ERROR)


class Preview(Fixture):
    def output(self, name="preview.wad") -> Path:
        return self.work / name

    def test_exports_one_map(self):
        target = self.output()
        code, out, _ = run("convert-to-preview-wad", str(self.archive),
                           "--map", "2", "--output", str(target))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("sha256", out)
        pairs = read_preview_wad(target.read_bytes())
        self.assertEqual([marker for marker, _ in pairs], ["MAP02"])
        self.assertEqual(pairs[0][1].planes.planes, self.records[1].planes.planes)

    def test_retargets_a_map_into_another_slot(self):
        target = self.output()
        code, _, _ = run("convert-to-preview-wad", str(self.archive), "--map", "3",
                         "--slot", "MAP01", "--output", str(target))
        self.assertEqual(code, EXIT_OK)
        pairs = read_preview_wad(target.read_bytes())
        self.assertEqual(pairs[0][0], "MAP01")
        self.assertEqual(pairs[0][1].planes.planes, self.records[2].planes.planes)

    def test_exports_several_maps(self):
        target = self.output()
        code, _, _ = run("convert-to-preview-wad", str(self.archive),
                         "--map", "1", "--map", "3", "--output", str(target))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([m for m, _ in read_preview_wad(target.read_bytes())], ["MAP01", "MAP03"])

    def test_exports_everything(self):
        target = self.output()
        code, _, _ = run("convert-to-preview-wad", str(self.archive), "--all", "--output", str(target))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(read_preview_wad(target.read_bytes())), 3)

    def test_output_is_reproducible(self):
        first, second = self.output("a.wad"), self.output("b.wad")
        run("convert-to-preview-wad", str(self.archive), "--all", "--output", str(first))
        run("convert-to-preview-wad", str(self.archive), "--all", "--output", str(second))
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_refuses_to_write_beside_the_source(self):
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--map", "1",
                           "--output", str(self.data / "preview.wad"))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-EXPORT-001", err)

    def test_refuses_to_overwrite_the_source(self):
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--map", "1",
                           "--output", str(self.archive))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-SOURCE-002", err)

    def test_honours_an_extra_protected_root(self):
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--map", "1",
                           "--protect", str(self.work), "--output", str(self.output()))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-EXPORT-001", err)

    def test_an_out_of_range_map_is_a_usage_error(self):
        # Not a C7E-NATIVE code: the archive is fine, the request is not.
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--map", "9",
                           "--output", str(self.output()))
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("no map 9", err)
        self.assertNotIn("C7E-NATIVE", err)

    def test_no_selection_is_a_usage_error(self):
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--output", str(self.output()))
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--map", err)

    def test_slot_with_several_maps_is_a_usage_error(self):
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--map", "1", "--map", "2",
                           "--slot", "MAP01", "--output", str(self.output()))
        self.assertEqual(code, EXIT_USAGE)

    def test_an_invalid_slot_fails(self):
        code, _, err = run("convert-to-preview-wad", str(self.archive), "--map", "1",
                           "--slot", "E1M1", "--output", str(self.output()))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-WAD-001", err)

    def test_nothing_is_written_when_the_export_is_refused(self):
        target = self.output()
        run("convert-to-preview-wad", str(self.archive), "--map", "9", "--output", str(target))
        self.assertFalse(target.exists())


class Projects(Fixture):
    """The headless path a GUI will later drive: import, inspect, export."""

    def project(self) -> Path:
        return self.work / "demo.ec7project"

    def test_new_project(self):
        code, out, _ = run("project-new", "--output", str(self.project()), "--name", "Demo")
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(self.project().exists())
        self.assertIn("Demo", out)

    def test_import_creates_a_project(self):
        code, out, _ = run("project-import", str(self.archive),
                           "--project", str(self.project()), "--map", "2")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("SECOND", out)
        self.assertIn("unchanged", out)

    def test_import_preserves_the_planes(self):
        run("project-import", str(self.archive), "--project", str(self.project()), "--map", "2")
        code, out, _ = run("project-inspect", str(self.project()), "--json")
        report = json.loads(out)
        self.assertEqual(report["maps"][0]["name"], "SECOND")
        self.assertEqual(report["maps"][0]["lump"], "MAP02")

    def test_import_records_the_source_digest(self):
        run("project-import", str(self.archive), "--project", str(self.project()), "--map", "1")
        report = json.loads(run("project-inspect", str(self.project()), "--json")[1])
        self.assertEqual(len(report["maps"][0]["source_sha256"]), 64)

    def test_import_can_retarget_the_slot(self):
        run("project-import", str(self.archive), "--project", str(self.project()),
            "--map", "3", "--slot", "1")
        report = json.loads(run("project-inspect", str(self.project()), "--json")[1])
        self.assertEqual(report["maps"][0]["lump"], "MAP01")

    def test_two_imports_accumulate(self):
        run("project-import", str(self.archive), "--project", str(self.project()), "--map", "1")
        run("project-import", str(self.archive), "--project", str(self.project()), "--map", "2")
        report = json.loads(run("project-inspect", str(self.project()), "--json")[1])
        self.assertEqual(len(report["maps"]), 2)

    def test_import_refuses_to_write_beside_the_source(self):
        code, _, err = run("project-import", str(self.archive),
                           "--project", str(self.data / "sneaky.ec7project"), "--map", "1")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-EXPORT-001", err)

    def test_export_produces_a_loadable_preview(self):
        run("project-import", str(self.archive), "--project", str(self.project()), "--map", "1")
        run("project-import", str(self.archive), "--project", str(self.project()),
            "--map", "2", "--slot", "2")
        target = self.work / "preview.wad"
        code, out, _ = run("project-export", str(self.project()), "--output", str(target))
        self.assertEqual(code, EXIT_OK)
        pairs = read_preview_wad(target.read_bytes())
        self.assertEqual([m for m, _ in pairs], ["MAP01", "MAP02"])

    def test_the_exported_words_are_the_projects_words(self):
        run("project-import", str(self.archive), "--project", str(self.project()), "--map", "2")
        target = self.work / "preview.wad"
        run("project-export", str(self.project()), "--output", str(target))
        _, record = read_preview_wad(target.read_bytes())[0]
        self.assertEqual(record.planes.planes, self.records[1].planes.planes)
        self.assertEqual(record.name.raw, self.records[1].name.raw)

    def test_export_of_an_empty_project_is_a_usage_error(self):
        run("project-new", "--output", str(self.project()))
        code, _, _ = run("project-export", str(self.project()),
                         "--output", str(self.work / "x.wad"))
        self.assertEqual(code, EXIT_USAGE)

    def test_inspecting_a_broken_project_fails_cleanly(self):
        broken = self.work / "broken.ec7project"
        broken.write_text("{\"schema_version\": 99}", encoding="utf-8")
        code, _, err = run("project-inspect", str(broken))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("C7E-SCHEMA", err)


class Usage(unittest.TestCase):
    def test_no_verb_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            with redirect_stderr(io.StringIO()):
                main([])
        self.assertEqual(caught.exception.code, 2)

    def test_version(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()) as out:
            main(["--version"])
        self.assertIn("EC7Edit", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=1)
