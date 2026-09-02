#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Regenerate the EC7Edit semantic catalog.

    generate_catalog.py write     rebuild editor/resources/editor_catalog.json
    generate_catalog.py verify    fail if the committed file is out of date
    generate_catalog.py report    print the joins that did not resolve

The catalog is committed rather than built at startup so the editor opens
without parsing the engine's translation every time, and so a change to it
shows up as a reviewable diff instead of as different behavior on somebody
else's machine. `verify` is what keeps the two honest: it is a gate, and it
fails the moment the translation changes and the catalog does not.

Metadata only. The catalog records *which* sprite page or wall page to draw;
the pixels are decoded from the user's own copy of the game at runtime, which
is what makes this file distributable when the artwork is not.
"""

from __future__ import annotations

import sys
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
REPO = EDITOR.parent
sys.path.insert(0, str(EDITOR))

from ec7edit_core.catalog import Curation, build_catalog, catalog_to_json  # noqa: E402
from ec7edit_core.decorate import read_actors_from_source  # noqa: E402
from ec7edit_core.xlat import read_xlat  # noqa: E402

XLAT = REPO / "wadsrc" / "static" / "xlat" / "corridor7.txt"
ACTORS = REPO / "wadsrc" / "static" / "actors" / "corridor7"
CURATED = EDITOR / "resources" / "catalog_sources.json"
OUTPUT = EDITOR / "resources" / "editor_catalog.json"


def generate() -> tuple[str, list[str]]:
    xlat = read_xlat(XLAT)
    actors = read_actors_from_source(ACTORS)
    curation = Curation.load(CURATED) if CURATED.exists() else Curation()
    catalog = build_catalog(xlat, actors, curation)
    return catalog_to_json(catalog), list(catalog.unresolved)


def main(argv: list[str]) -> int:
    verb = argv[1] if len(argv) > 1 else "write"
    if verb not in ("write", "verify", "report"):
        print(__doc__.strip(), file=sys.stderr)
        return 2

    for required in (XLAT, ACTORS):
        if not required.exists():
            print(f"missing input: {required}", file=sys.stderr)
            return 1

    text, unresolved = generate()

    if verb == "report":
        print(f"{len(unresolved)} unresolved join(s)")
        for line in unresolved:
            print(f"  {line}")
        return 0

    if verb == "verify":
        if not OUTPUT.exists():
            print(f"{OUTPUT} has not been generated", file=sys.stderr)
            return 1
        current = OUTPUT.read_text(encoding="utf-8")
        if current != text:
            print(
                f"{OUTPUT} is out of date with the translation or the actors.\n"
                "Regenerate with 'generate_catalog.py write' and review the diff.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.name} matches its inputs")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(text)} bytes, {len(unresolved)} unresolved join(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
