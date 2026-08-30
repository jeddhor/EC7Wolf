#!/usr/bin/env python3
"""Check that every local Markdown link resolves inside the ECWolf git root.

Milestone E0 of docs/corridor7-level-editor.md, which requires that "every
Markdown local link resolves to a tracked path within the ECWolf git root".

Two failures matter and they are different:

  * a link to a path that does not exist, which is an ordinary broken link;
  * a link that resolves *outside* the git root, which is worse. Those read
    fine on the machine that wrote them and are simply absent for everyone
    else, because the thing they point at was never in the repository. The
    editor plan is written around exactly that hazard -- its own reference
    codec lives outside the root -- so the audit exists to keep the documents
    honest about it.

Untracked-but-present files are reported separately: a link to a file that
exists only in someone's working tree is a link nobody else can follow.

Usage:
  audit_links.py [--all] [PATH ...]

With no paths, audits every tracked Markdown file. Anchors, external URLs and
mailto: are ignored; only local paths are resolved.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# [text](target) but not images with a leading !, and not reference-style.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
EXTERNAL = ("http://", "https://", "mailto:", "ftp://", "#")


def git_root() -> Path:
    """The repository this script lives in, not the one the caller stands in.

    Gates run from whatever directory suits them -- the data directory, a
    temporary work tree -- so asking git about the current directory finds
    either the wrong repository or none at all.
    """
    out = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent),
                          "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip()).resolve()


def tracked_files(root: Path) -> set[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files"],
                         capture_output=True, text=True, check=True)
    return {(root / line).resolve() for line in out.stdout.splitlines() if line}


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--all"]
    root = git_root()
    tracked = tracked_files(root)

    if argv:
        targets = [Path(a).resolve() for a in argv]
    else:
        targets = sorted(p for p in tracked if p.suffix.lower() == ".md")

    escaping: list[str] = []
    missing: list[str] = []
    untracked: list[str] = []

    for doc in targets:
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for match in LINK.finditer(text):
            target = match.group(1).strip()
            if target.startswith(EXTERNAL) or not target:
                continue
            # Strip a trailing anchor and any title.
            target = target.split(" ")[0].split("#")[0]
            if not target:
                continue
            resolved = (doc.parent / target).resolve()
            where = f"{doc.relative_to(root)} -> {target}"
            try:
                resolved.relative_to(root)
            except ValueError:
                escaping.append(where)
                continue
            if not resolved.exists():
                missing.append(where)
            elif resolved not in tracked and resolved.is_file():
                untracked.append(where)

    for label, rows in (("escapes the git root", escaping),
                        ("does not exist", missing),
                        ("exists but is untracked", untracked)):
        if rows:
            print(f"\n{len(rows)} link(s) {label}:")
            for row in rows:
                print(f"  {row}")

    total = len(escaping) + len(missing) + len(untracked)
    if total == 0:
        print(f"{len(targets)} Markdown file(s): every local link resolves to a "
              f"tracked path inside {root.name}")
        return 0
    print(f"\n{total} problem(s) across {len(targets)} Markdown file(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
