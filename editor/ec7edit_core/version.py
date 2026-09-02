# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""One version number for the editor and the engine.

EC7Edit ships with EC7Wolf, is tested against EC7Wolf, and speaks a protocol
whose version has to match EC7Wolf's. Giving it a version of its own -- 0.1.0,
as the plan originally said -- meant every bug report carried two numbers whose
relationship a reader had to guess. So it carries the engine's: `1.0-betaN`,
where N counts commits since the same anchor `src/versiondefs.cmake` uses.

Computed the same way, from the same commit, so the two can never disagree:

* a packaged build reads `_build_version.py`, written into the bundle when the
  package was frozen. There is no repository inside a package to ask;
* a checkout asks git, which is always right and never stale;
* anything else -- a source zip, an exported tree -- falls back to the constant
  below, which the release process bumps exactly as it bumps
  `EC7WOLF_BETA_FALLBACK`.

The work happens once and only when somebody asks. `import ec7edit_core` runs
no subprocess; reading `ec7edit_core.__version__` does, at most once.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

#: "feat(corridor7): implement complete single-player Corridor 7 support", the
#: last milestone of the original development plan. The same anchor
#: `src/versiondefs.cmake` counts from.
ANCHOR = "20ee748cd9f45846f6002abfaf99e0a47294eb07"

#: Used when there is no git to ask and no frozen stamp to read. Bump when
#: cutting a release, beside EC7WOLF_BETA_FALLBACK.
BETA_FALLBACK = 209


def _from_stamp() -> str:
    """The number written into a package when it was frozen, if this is one."""
    try:
        from ._build_version import VERSION       # type: ignore[import-not-found]
    except Exception:                             # noqa: BLE001 - absent is normal
        return ""
    return str(VERSION)


def _from_git() -> str:
    """What the checkout this file lives in would call itself."""
    try:
        done = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent),
             "rev-list", "--count", f"{ANCHOR}..HEAD"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    count = done.stdout.strip()
    return f"1.0-beta{count}" if count.isdigit() else ""


@functools.lru_cache(maxsize=1)
def version() -> str:
    """`1.0-betaN`, matching the engine built from the same tree."""
    return _from_stamp() or _from_git() or f"1.0-beta{BETA_FALLBACK}"


def pep440() -> str:
    """The same number, spelled the way packaging tools insist on.

    `1.0-beta209` is not a PEP 440 version; `1.0b209` is the normalized form of
    it. Only build backends care, and only they should see this.
    """
    text = version()
    return text.replace("-beta", "b") if "-beta" in text else text


__all__ = ["ANCHOR", "BETA_FALLBACK", "pep440", "version"]
