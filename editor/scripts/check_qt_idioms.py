#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Catch the two PySide6 mistakes that parse, import, and then raise.

Both of these shipped once, and neither is visible until the code path runs:

  * `dialog.Accepted` -- PySide6 puts enum values on the *class*, so reading
    one off an instance raises `AttributeError`. `QDialog.Accepted` is fine;
    the instance is not. This one only fires when the dialog closes, which is
    past the point most tests look.
  * `int(event.button())` -- Qt 6 flag enums have no `__int__`. `.value` does.

This parses rather than greps, because a grep matches the comment explaining
the bug as readily as the bug.

    check_qt_idioms.py [PATH ...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Enum names that only ever live on a Qt class.
CLASS_ONLY = {
    "Accepted", "Rejected", "IconMode", "ListMode", "Adjust", "Fixed",
    "StandardButton", "DialogCode",
}

#: Qt classes, so `QDialog.Accepted` is allowed and `dialog.Accepted` is not.
def _looks_like_a_class(name: str) -> bool:
    return name[:1].isupper()


class Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.problems: list[str] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr in CLASS_ONLY
            or node.attr.startswith("Format_")
        ):
            base = node.value
            if isinstance(base, ast.Name) and not _looks_like_a_class(base.id):
                self.problems.append(
                    f"{self.path}:{node.lineno}: {base.id}.{node.attr} reads a Qt enum "
                    f"off an instance; use the class"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and len(node.args) == 1
        ):
            argument = node.args[0]
            text = ""
            if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute):
                text = argument.func.attr
            elif isinstance(argument, ast.Attribute):
                text = argument.attr
            if text in ("button", "buttons", "modifiers", "_button"):
                self.problems.append(
                    f"{self.path}:{node.lineno}: int() on a Qt flag enum raises; use .value"
                )
        self.generic_visit(node)


def check(path: Path) -> list[str]:
    visitor = Visitor(path)
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), str(path)))
    return visitor.problems


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or [Path(__file__).resolve().parents[1] / "ec7edit_gui"]
    files: list[Path] = []
    for root in roots:
        files.extend(sorted(root.rglob("*.py")) if root.is_dir() else [root])

    problems = []
    for path in files:
        problems.extend(check(path))
    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        return 1
    print(f"{len(files)} file(s): no Qt enum is read off an instance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
