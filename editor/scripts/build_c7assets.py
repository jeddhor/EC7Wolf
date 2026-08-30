#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Build the single-file asset gallery from the canonical modules.

    build_c7assets.py write     regenerate tools/c7assets.py
    build_c7assets.py verify    fail if the committed file is out of date

`tools/c7assets.py` promises that you can drop one file beside the game data
and run it with nothing installed. Keeping that promise used to mean a second
copy of every decoder living in it, which is exactly how two implementations of
one format end up disagreeing -- and the RLEW threshold E1 found is what that
looks like when it happens.

So the decoders live once, in `ec7edit_core`, and this splices them into the
gallery template ahead of its own code. The inlining is mechanical: relative
imports are dropped, because everything lands in one namespace, and nothing
else is touched. `verify` is a gate, so the shipped file cannot drift.

The result is still one stdlib-only file. That was never the problem; two
copies of the decoder was.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[1]
REPO = EDITOR.parent

TEMPLATE = EDITOR / "scripts" / "c7assets_gallery.py"
OUTPUT = REPO / "tools" / "c7assets.py"
MARKER = "# EC7EDIT-INLINE"

#: Dependency order. Each module may use names from the ones before it.
MODULES = ("errors", "planes", "names", "rlew", "archive", "assets", "decorate")

_RELATIVE_IMPORT = re.compile(r"^\s*from \.\w* import .*$", re.MULTILINE)
_FUTURE = re.compile(r"^from __future__ import .*$", re.MULTILINE)
_SPDX = re.compile(r"^# SPDX-License-Identifier:.*$|^# Copyright \(C\).*$", re.MULTILINE)


def _module_source(name: str) -> str:
    """One module, ready to be concatenated into a flat namespace."""
    text = (EDITOR / "ec7edit_core" / f"{name}.py").read_text(encoding="utf-8")
    text = _SPDX.sub("", text)
    text = _FUTURE.sub("", text)
    # Relative imports have nowhere to point once everything is one module.
    # Removing the line is safe: the names it bound are defined above it.
    text = _RELATIVE_IMPORT.sub("", text)
    # The module docstring becomes a stray expression statement, which is
    # harmless but noisy; keep it, since it is the explanation of the code
    # immediately below and a reader of the single file deserves it.
    return text.strip("\n")


def build() -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in template:
        raise SystemExit(f"{TEMPLATE} has no {MARKER} marker")

    banner = (
        "# " + "-" * 74 + "\n"
        "# Inlined from ECWolf/editor/ec7edit_core by editor/scripts/build_c7assets.py.\n"
        "# GENERATED FILE -- do not edit tools/c7assets.py. Edit the modules or\n"
        "# editor/scripts/c7assets_gallery.py and rebuild; a gate checks this.\n"
        "# " + "-" * 74 + "\n"
    )
    inlined = [banner]
    for name in MODULES:
        inlined.append(f"\n# --- ec7edit_core/{name}.py " + "-" * (48 - len(name)) + "\n\n")
        inlined.append(_module_source(name))
        inlined.append("\n")

    return template.replace(MARKER, "".join(inlined), 1)


HEADER_REPLACEMENT = '''"""Corridor 7: Alien Invasion -- in-memory asset gallery.

Drop this single file into a directory that holds the released Corridor 7 data
(GFXTILES.CO7, VGAGRAPH set, MAPTEMP.CO7, CORR7CD.EXE, ecwolf.pk3) and run it:

    python3 c7assets.py            # serves http://127.0.0.1:8777
    python3 c7assets.py --port 9000 --dir /path/to/release

Everything is decoded into memory; no files are written and no originals are
modified. Only the Python 3.10+ standard library is required.

GENERATED FILE. The decoders below are inlined from ECWolf/editor/ec7edit_core
so that this tool and the level editor cannot disagree about a format. Edit
those modules or editor/scripts/c7assets_gallery.py and run
editor/scripts/build_c7assets.py; a gate checks that this file matches.
"""'''


def main(argv: list[str]) -> int:
    verb = argv[1] if len(argv) > 1 else "write"
    if verb not in ("write", "verify"):
        print(__doc__.strip(), file=sys.stderr)
        return 2

    generated = build()
    # Replace the template's whole docstring with the shipped tool's.
    start = generated.index('"""Gallery half')
    end = generated.index('"""', generated.index("\n", start)) + 3
    generated = generated[:start] + HEADER_REPLACEMENT + generated[end:]

    if verb == "verify":
        if not OUTPUT.exists():
            print(f"{OUTPUT} has not been generated", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != generated:
            print(
                f"{OUTPUT} is out of date with ec7edit_core or the gallery template.\n"
                "Rebuild with 'build_c7assets.py write' and review the diff.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.name} matches the modules it is built from")
        return 0

    OUTPUT.write_text(generated, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(generated)} bytes from {len(MODULES)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
