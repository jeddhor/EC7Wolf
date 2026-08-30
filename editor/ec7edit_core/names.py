# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The 16-byte native map name, kept raw.

Every other Corridor 7 tool treats this field as a C string and throws away
whatever follows the terminator. Four records in the retail archive have
nonzero bytes back there. They may well be nothing -- TED5 reusing a buffer --
but a lossless editor does not get to decide that on the author's behalf, so
an imported name carries its exact 16 bytes alongside the text it displays,
and only a deliberate rename replaces the field.

That gives three outcomes, matching appendix C:

* imported and canonical      -- silent;
* imported and noncanonical   -- `C7E-NATIVE-007`, information, still exportable;
* renamed to something unencodable -- `C7E-NATIVE-004`, error, nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import DiagnosticLog, native_error

#: The field is fixed width in both record layouts and in the PLANES lump.
NAME_FIELD_BYTES = 16

#: A new or renamed map keeps a byte for the terminator, so the engine and
#: every downstream C string agree about where the text stops.
MAX_CANONICAL_TEXT = NAME_FIELD_BYTES - 1

_PRINTABLE = range(0x20, 0x7F)


@dataclass(frozen=True)
class NativeName:
    """Exactly 16 bytes, plus the text a human should see for them."""

    raw: bytes
    #: True when these bytes came from a file rather than from a rename.
    imported: bool = False

    def __post_init__(self) -> None:
        if len(self.raw) != NAME_FIELD_BYTES:
            raise native_error(
                "C7E-NATIVE-004",
                f"name field is {len(self.raw)} bytes, must be exactly {NAME_FIELD_BYTES}",
            )

    @property
    def text(self) -> str:
        """Display form: bytes up to the first NUL, unprintables shown as `.`.

        Never used for writing. The raw field is what gets written.
        """
        head = self.raw.split(b"\x00", 1)[0]
        return "".join(chr(b) if b in _PRINTABLE else "." for b in head)

    @property
    def is_canonical(self) -> bool:
        """Would the canonical writer produce exactly these bytes?"""
        terminator = self.raw.find(b"\x00")
        if terminator < 0:
            return False  # 16 printable bytes and nowhere for the NUL
        head = self.raw[:terminator]
        tail = self.raw[terminator:]
        return (
            len(head) <= MAX_CANONICAL_TEXT
            and all(b in _PRINTABLE for b in head)
            and tail == b"\x00" * len(tail)
        )

    def describe_noncanonical(self) -> str:
        """Why `is_canonical` is False, for a diagnostic a person can act on."""
        terminator = self.raw.find(b"\x00")
        if terminator < 0:
            return f"all {NAME_FIELD_BYTES} bytes are used, leaving no terminator"
        head = self.raw[:terminator]
        if any(b not in _PRINTABLE for b in head):
            return "the displayed part contains bytes outside printable ASCII"
        tail = self.raw[terminator:]
        if tail != b"\x00" * len(tail):
            nonzero = sum(1 for byte in tail if byte)
            return (
                f"{nonzero} nonzero byte(s) follow the terminator "
                f"(tail {tail.hex(' ')})"
            )
        return "canonical"

    def report(self, log: DiagnosticLog, where: str = "") -> None:
        """Note a preserved noncanonical field. Information, not a complaint."""
        if self.imported and not self.is_canonical:
            log.information(
                "C7E-NATIVE-007",
                f"name field preserved exactly: {self.describe_noncanonical()}",
                where,
            )

    @classmethod
    def from_raw(cls, raw: bytes) -> "NativeName":
        """Import: keep the bytes, whatever they are."""
        return cls(bytes(raw), imported=True)

    @classmethod
    def from_text(cls, text: str) -> "NativeName":
        """Rename: replace the whole field, or refuse.

        Refusing is the point. Silently truncating to 15 bytes, or substituting
        `?` for a character the format cannot hold, would let an author think
        they had named a map something they did not.
        """
        try:
            encoded = text.encode("ascii")
        except UnicodeEncodeError as error:
            raise native_error(
                "C7E-NATIVE-004",
                f"name {text!r} is not ASCII: {error.reason} at position {error.start}",
            ) from error
        if any(b not in _PRINTABLE for b in encoded):
            raise native_error(
                "C7E-NATIVE-004",
                f"name {text!r} contains a control character; printable ASCII only",
            )
        if len(encoded) > MAX_CANONICAL_TEXT:
            raise native_error(
                "C7E-NATIVE-004",
                f"name {text!r} is {len(encoded)} bytes; the limit is "
                f"{MAX_CANONICAL_TEXT} plus a terminator",
            )
        return cls(encoded.ljust(NAME_FIELD_BYTES, b"\x00"), imported=False)
