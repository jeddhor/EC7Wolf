# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Diagnostics: the stable `C7E-*` codes from the design guide, appendix C.

A diagnostic is data, never a formatted string that the caller has to parse
back. The code is the contract -- tests assert on codes, the GUI groups by
them, and the message is free to improve without breaking either.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Severity(enum.Enum):
    """Ordered so a caller can ask for "error or worse" with a comparison."""

    INFORMATION = 10
    WARNING = 20
    ERROR = 30

    def __lt__(self, other: "Severity") -> bool:
        return self.value < other.value

    def __le__(self, other: "Severity") -> bool:
        return self.value <= other.value

    def __gt__(self, other: "Severity") -> bool:
        return self.value > other.value

    def __ge__(self, other: "Severity") -> bool:
        return self.value >= other.value


@dataclass(frozen=True)
class Diagnostic:
    """One problem, one place, one stable code."""

    code: str
    severity: Severity
    message: str
    #: Free-form location -- "map 3 plane 1", a file offset, a path. Display
    #: only; never parsed.
    where: str = ""

    def __str__(self) -> str:
        location = f" [{self.where}]" if self.where else ""
        return f"{self.code} {self.severity.name.lower()}: {self.message}{location}"


class Ec7EditError(Exception):
    """Base class carrying a diagnostic rather than only a message."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(str(diagnostic))
        self.diagnostic = diagnostic


class NativeFormatError(Ec7EditError):
    """A `C7E-NATIVE-*` failure: the TED5 archive or an RLEW stream."""


class WadFormatError(Ec7EditError):
    """A `C7E-WAD-*` failure: the preview WAD or its PLANES lump."""


class ExportError(Ec7EditError):
    """A `C7E-EXPORT-*` or `C7E-SOURCE-*` failure: paths, writes, readback."""


def native_error(code: str, message: str, where: str = "") -> NativeFormatError:
    return NativeFormatError(Diagnostic(code, Severity.ERROR, message, where))


def wad_error(code: str, message: str, where: str = "") -> WadFormatError:
    return WadFormatError(Diagnostic(code, Severity.ERROR, message, where))


def export_error(code: str, message: str, where: str = "") -> ExportError:
    return ExportError(Diagnostic(code, Severity.ERROR, message, where))


@dataclass
class DiagnosticLog:
    """A collecting parameter: parsers append, callers inspect by code."""

    entries: list[Diagnostic] = field(default_factory=list)

    def add(self, code: str, severity: Severity, message: str, where: str = "") -> None:
        self.entries.append(Diagnostic(code, severity, message, where))

    def information(self, code: str, message: str, where: str = "") -> None:
        self.add(code, Severity.INFORMATION, message, where)

    def warning(self, code: str, message: str, where: str = "") -> None:
        self.add(code, Severity.WARNING, message, where)

    def codes(self) -> list[str]:
        return [entry.code for entry in self.entries]

    def worst(self) -> Severity | None:
        return max((entry.severity for entry in self.entries), default=None)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)
