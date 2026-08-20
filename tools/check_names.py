#!/usr/bin/env python3
"""Find names a module uses but does not have.

Python does not notice a call to a function that no longer exists until the
line runs, and in an installer plenty of lines run only on one platform or one
branch. developer_environment() was deleted by an edit that replaced the block
it sat in; the call site stayed, every test passed, and it would have raised
NameError on the first Windows machine whose CMake was older than its Visual
Studio -- a path nothing here can reach.

symtable answers the question exactly: for each scope it says which names are
resolved as globals, and those must exist at module level or be builtins.

Usage: check_names.py FILE...   (or a directory, which is walked)
"""

from __future__ import annotations

import builtins
import symtable
import sys
from pathlib import Path


def undefined(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        top = symtable.symtable(source, str(path), "exec")
    except SyntaxError as error:
        return [f"{path}: cannot parse: {error}"]

    known = set(top.get_identifiers()) | set(dir(builtins)) | {"__file__",
                                                               "__name__",
                                                               "__doc__"}
    problems: list[str] = []

    def walk(table: symtable.SymbolTable, where: str) -> None:
        for symbol in table.get_symbols():
            name = symbol.get_name()
            # A global that is only ever read has to come from somewhere.
            if (symbol.is_global() and not symbol.is_assigned()
                    and name not in known):
                problems.append(f"{path}:{table.get_lineno()}: {where} uses "
                                f"'{name}', which this module does not define")
        for child in table.get_children():
            walk(child, f"{where}.{child.get_name()}" if where else
                 child.get_name())

    walk(top, "")
    return problems


def main(argv: list[str]) -> int:
    targets: list[Path] = []
    for argument in argv or ["."]:
        path = Path(argument)
        targets += sorted(path.rglob("*.py")) if path.is_dir() else [path]

    problems: list[str] = []
    for target in targets:
        if "__pycache__" in target.parts:
            continue
        problems += undefined(target)

    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} undefined name(s)")
        return 1
    print(f"names: {len(targets)} files, nothing undefined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
