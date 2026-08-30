#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Corridor 7: Alien Invasion -- in-memory asset gallery.

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
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import zipfile
import zlib
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------
# Inlined from ECWolf/editor/ec7edit_core by editor/scripts/build_c7assets.py.
# GENERATED FILE -- do not edit tools/c7assets.py. Edit the modules or
# editor/scripts/c7assets_gallery.py and rebuild; a gate checks this.
# --------------------------------------------------------------------------

# --- ec7edit_core/errors.py ------------------------------------------

"""Diagnostics: the stable `C7E-*` codes from the design guide, appendix C.

A diagnostic is data, never a formatted string that the caller has to parse
back. The code is the contract -- tests assert on codes, the GUI groups by
them, and the message is free to improve without breaking either.
"""



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

# --- ec7edit_core/planes.py ------------------------------------------

"""The canonical in-memory plane model and the coordinate convention.

Frozen here so that no other module gets to have an opinion about it:

* origin `(0, 0)` is the native top-left cell;
* `x` grows to the right, `y` grows downward;
* the linear index is `y * width + x`;
* file plane order is 0, 1, 2.

The canvas is free to draw compass north upward. Raw coordinates never rotate
to suit a view -- the moment they do, an exported map stops matching the one
on screen in a way no test would catch.

A cell is not one value. Geometry lives in plane 0, objects in plane 1, and
plane 2 carries data this editor preserves without claiming to understand, so
all three are kept side by side and none is ever synthesised from another.
"""



from dataclasses import dataclass


#: Both dimensions are u16 in the file, but the engine refuses anything larger.
MAX_DIMENSION = 181
MIN_DIMENSION = 1

#: Exactly three, always. The four-plane case in the engine is Rise of the
#: Triad's, reached by a different loader path that Corridor 7 never takes.
PLANE_COUNT = 3


def linear_index(x: int, y: int, width: int) -> int:
    """The one place the row-major convention is spelled out."""
    return y * width + x


def coordinates(index: int, width: int) -> tuple[int, int]:
    """Inverse of `linear_index`, for turning a diagnostic offset into a cell."""
    return index % width, index // width


def validate_dimensions(width: int, height: int, *, where: str = "") -> None:
    """Reject what `FGamemaps::Open` would reject, with the same thresholds."""
    for name, value in (("width", width), ("height", height)):
        if not MIN_DIMENSION <= value <= MAX_DIMENSION:
            raise native_error(
                "C7E-BOUNDARY-001" if value == 0 else "C7E-NATIVE-001",
                f"{name} {value} is outside the engine's {MIN_DIMENSION}..{MAX_DIMENSION}",
                where,
            )


@dataclass(frozen=True)
class MapPlanes:
    """Three independent `width * height` arrays of unsigned 16-bit words.

    Immutable: editing produces a new snapshot. That is what makes undo cheap
    and what stops a background thread from seeing half an edit.
    """

    width: int
    height: int
    planes: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]

    def __post_init__(self) -> None:
        validate_dimensions(self.width, self.height)
        if len(self.planes) != PLANE_COUNT:
            raise native_error(
                "C7E-SCHEMA-002", f"expected {PLANE_COUNT} planes, got {len(self.planes)}"
            )
        expected = self.width * self.height
        for number, plane in enumerate(self.planes):
            if len(plane) != expected:
                raise native_error(
                    "C7E-SCHEMA-002",
                    f"plane {number} holds {len(plane)} cells, "
                    f"{self.width}x{self.height} needs {expected}",
                )

    @property
    def cell_count(self) -> int:
        return self.width * self.height

    def at(self, plane: int, x: int, y: int) -> int:
        """Read one cell. Bounds are the caller's business, deliberately."""
        return self.planes[plane][linear_index(x, y, self.width)]

    def rows(self, plane: int):
        """Iterate the plane a row at a time, top row first."""
        data = self.planes[plane]
        for y in range(self.height):
            begin = y * self.width
            yield data[begin : begin + self.width]

    @classmethod
    def empty(cls, width: int, height: int) -> "MapPlanes":
        blank = (0,) * (width * height)
        return cls(width, height, (blank, blank, blank))

    def with_plane(self, plane: int, values: tuple[int, ...]) -> "MapPlanes":
        replaced = list(self.planes)
        replaced[plane] = tuple(values)
        return MapPlanes(self.width, self.height, tuple(replaced))  # type: ignore[arg-type]

# --- ec7edit_core/names.py -------------------------------------------

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



from dataclasses import dataclass


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

# --- ec7edit_core/rlew.py --------------------------------------------

"""RLEW: the word-oriented run-length coding TED5 wraps every plane in.

The decoder is written to mirror `ValidateTed5RLEW` in
`src/resourcefiles/file_gamemaps.cpp` step for step, because the useful
question is never "is this stream reasonable" but "will the engine take it".
Where the engine accepts something the canonical writer would not produce, the
decoder accepts it too and says so with a diagnostic rather than refusing.

Stream layout, little-endian throughout:

    u16 expanded_bytes          -- decoded size, which is width*height*2
    then words until the decoded size is reached:
        w != 0xABCD             -- one literal word
        0xABCD, u16 n, u16 v    -- n copies of v

A literal that happens to equal the tag has no short form and must use the
triple, however few of them there are. The stream must end exactly as the last needed word is produced: the
engine checks both `out == expandedBytes` and `in == length`.
"""



import struct


#: Corridor 7 stores the tag in the archive only for `GAMEMAPS`; the
#: self-contained TED5 archive hardcodes it, and so does the engine.
RLEW_TAG = 0xABCD

#: `expanded_bytes` and each plane's stored length are both u16.
MAX_EXPANDED_BYTES = 0xFFFF
MAX_STREAM_BYTES = 0xFFFF

#: The run count is a u16. In practice the expanded-size ceiling binds first.
MAX_RUN = 0xFFFF

#: Shortest run the writer will emit, measured off the shipped archive rather
#: than reasoned about. A run of three costs six bytes and so do three
#: literals, so the choice at exactly three is free on size and the original
#: TED5 encoder spent it on literals: across all 180 planes of the retail
#: archive it never once emits a run shorter than four. Matching that is what
#: makes a re-encode byte-identical to what shipped, so an archive rewritten
#: by this editor differs from the original only where the author edited it.
RUN_THRESHOLD = 4


def decode_plane(
    stream: bytes,
    expected_words: int,
    *,
    where: str = "",
    log: DiagnosticLog | None = None,
) -> tuple[int, ...]:
    """Expand one stored plane, including its expanded-size prefix.

    `expected_words` is `width * height` from the record header. The declared
    size must agree with it exactly: a stream that expands correctly to the
    wrong size is still the wrong plane.
    """
    expanded_bytes = expected_words * 2
    if expanded_bytes > MAX_EXPANDED_BYTES:
        raise native_error(
            "C7E-NATIVE-002",
            f"{expected_words} words expand to {expanded_bytes} bytes, past the "
            f"{MAX_EXPANDED_BYTES}-byte limit of the size field",
            where,
        )
    length = len(stream)
    if length < 2 or length % 2:
        raise native_error(
            "C7E-NATIVE-002",
            f"stored length {length} is not a whole number of words above the size prefix",
            where,
        )

    declared = struct.unpack_from("<H", stream, 0)[0]
    if declared != expanded_bytes:
        raise native_error(
            "C7E-NATIVE-002",
            f"stream declares {declared} expanded bytes, header requires {expanded_bytes}",
            where,
        )

    output: list[int] = []
    cursor = 2
    produced = 0
    while produced < expanded_bytes:
        if cursor + 2 > length:
            raise native_error(
                "C7E-NATIVE-002",
                f"stream ends after {produced} of {expanded_bytes} bytes",
                where,
            )
        value = struct.unpack_from("<H", stream, cursor)[0]
        if value == RLEW_TAG:
            if cursor + 6 > length:
                raise native_error(
                    "C7E-NATIVE-002", "truncated run: tag without its count and value", where
                )
            count, repeated = struct.unpack_from("<HH", stream, cursor + 2)
            if count * 2 > expanded_bytes - produced:
                raise native_error(
                    "C7E-NATIVE-002",
                    f"run of {count} words overruns the {expanded_bytes}-byte plane",
                    where,
                )
            if count == 0 and log is not None:
                log.warning(
                    "C7E-NATIVE-006",
                    "stream contains a zero-count run; the meaning is preserved and the "
                    "canonical writer emits none",
                    where,
                )
            output.extend([repeated] * count)
            produced += count * 2
            cursor += 6
        else:
            output.append(value)
            produced += 2
            cursor += 2

    if cursor != length:
        raise native_error(
            "C7E-NATIVE-002",
            f"{length - cursor} trailing bytes after the plane was complete",
            where,
        )
    return tuple(output)


def encode_plane(words: tuple[int, ...] | list[int], *, where: str = "") -> bytes:
    """Encode one plane canonically: shortest form, no zero-count runs.

    Deterministic by construction -- the same words always give the same bytes,
    on every platform and every run, which is what lets an export digest be a
    contract instead of one machine's luck.
    """
    expanded_bytes = len(words) * 2
    if expanded_bytes > MAX_EXPANDED_BYTES:
        raise native_error(
            "C7E-NATIVE-003",
            f"{len(words)} words expand to {expanded_bytes} bytes, past the "
            f"{MAX_EXPANDED_BYTES}-byte limit of the size field",
            where,
        )

    output = bytearray(struct.pack("<H", expanded_bytes))
    cursor = 0
    total = len(words)
    while cursor < total:
        value = words[cursor]
        if not 0 <= value <= 0xFFFF:
            raise native_error(
                "C7E-CELL-001", f"word {value} at index {cursor} is outside 0..65535", where
            )
        end = cursor + 1
        while end < total and words[end] == value and end - cursor < MAX_RUN:
            end += 1
        count = end - cursor
        if value == RLEW_TAG or count >= RUN_THRESHOLD:
            output.extend(struct.pack("<HHH", RLEW_TAG, count, value))
        else:
            output.extend(struct.pack(f"<{count}H", *words[cursor:end]))
        cursor = end

    if len(output) > MAX_STREAM_BYTES:
        raise native_error(
            "C7E-NATIVE-003",
            f"encoded plane is {len(output)} bytes, past the {MAX_STREAM_BYTES}-byte "
            "limit of the stored length field",
            where,
        )
    return bytes(output)

# --- ec7edit_core/archive.py -----------------------------------------

"""The self-contained TED5 archive Corridor 7 ships as `MAPTEMP.CO7`.

Unlike Wolfenstein's split `MAPHEAD`/`GAMEMAPS` pair, this one file carries
both the headers and the plane streams, and each header is followed
immediately by its own three streams rather than all headers preceding all
data. The first record is 46 bytes and begins with the signature; every later
record is 42 bytes and begins with `!ID!`; a bare `!ID!` ends the archive.

The first record's plane-0 offset is **implicit**. It is not stored anywhere:
the stream simply begins at byte 46, and the engine hardcodes that
(`headers[0].PlaneOffset[0] = sizeof(first)`). Only planes 1 and 2 have stored
offsets in that record, which is why it is 46 bytes rather than 50.

Record layouts, little-endian::

    first (46)                       later (42)
    00  char[12] "TED5v1.0.\\0\\0\\0"   00  char[4]  "!ID!"
    (plane 0 offset is implicit 46)  04  u32[3]   plane offsets
    12  u32[2]   plane 1, 2 offsets  16  u16[3]   plane lengths
    20  u16[3]   plane lengths       22  u16      width
    26  u16      width               24  u16      height
    28  u16      height              26  char[16] name
    30  char[16] name

Every byte of both layouts is accounted for; the only field this editor cannot
fully explain is the tail of the name, which `names.py` preserves verbatim.

Validation is deliberately the engine's, not a tidier superset of it. Where
`FGamemaps::Open` accepts something the canonical writer would never emit, so
does this parser -- with a diagnostic. Refusing to open a map the game itself
loads would be a worse failure than any amount of noncanonical input.
"""



import struct
from dataclasses import dataclass, field
from pathlib import Path





TED5_SIGNATURE = b"TED5v1.0.\x00\x00\x00"
MAP_MARKER = b"!ID!"

FIRST_RECORD_BYTES = 46
LATER_RECORD_BYTES = 42

#: `Ted5MapHeader headers[MAX_TED5_MAPS]` in the engine is a fixed array, so
#: this is a hard bound and not a policy choice.
MAX_MAPS = 100

_U32_MAX = 0xFFFFFFFF


@dataclass(frozen=True)
class RecordSource:
    """Where a record's bytes were, exactly as the file stated them.

    Kept so that a re-export can be compared against its origin, and so a
    diagnostic can name a file offset instead of an abstract map number.
    """

    header_offset: int
    plane_offsets: tuple[int, int, int]
    plane_lengths: tuple[int, int, int]


@dataclass(frozen=True)
class MapRecord:
    """One map: its slot, its 16 raw name bytes, and its three planes."""

    number: int  # 1-based; the archive's order is the map number
    name: NativeName
    planes: MapPlanes
    source: RecordSource | None = None

    @property
    def lump_name(self) -> str:
        """What the engine will call this map: `MAP01`, `MAP02`, ...

        The engine formats with `%02d`, so slot 100 becomes `MAP100` -- five
        characters, which still fits a WAD's eight-byte name field.
        """
        return f"MAP{self.number:02d}"

    @property
    def width(self) -> int:
        return self.planes.width

    @property
    def height(self) -> int:
        return self.planes.height


@dataclass
class Archive:
    """A parsed archive plus everything noticed while parsing it."""

    records: tuple[MapRecord, ...]
    diagnostics: DiagnosticLog = field(default_factory=DiagnosticLog)
    #: False when the file ends immediately after its last plane. The engine
    #: accepts that; the canonical writer always adds the terminator.
    terminated: bool = True

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, index: int) -> MapRecord:
        return self.records[index]

    def by_number(self, number: int) -> MapRecord:
        for record in self.records:
            if record.number == number:
                return record
        raise native_error(
            "C7E-NATIVE-001", f"archive has no map {number} (it holds {len(self.records)})"
        )


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _parse_header(
    data: bytes, offset: int, index: int
) -> tuple[NativeName, int, int, tuple[int, int, int], tuple[int, int, int]]:
    """Read one record header. Returns name, width, height, offsets, lengths."""
    where = f"map {index + 1}"
    if index == 0:
        if len(data) < FIRST_RECORD_BYTES:
            raise native_error(
                "C7E-NATIVE-001",
                f"file is {len(data)} bytes, too short for a {FIRST_RECORD_BYTES}-byte "
                "first record",
                where,
            )
        if data[:12] != TED5_SIGNATURE:
            raise native_error(
                "C7E-NATIVE-001", f"signature is {data[:12]!r}, expected {TED5_SIGNATURE!r}", where
            )
        plane_offsets = (FIRST_RECORD_BYTES, _u32(data, 12), _u32(data, 16))
        plane_lengths = tuple(_u16(data, 20 + plane * 2) for plane in range(PLANE_COUNT))
        width = _u16(data, 26)
        height = _u16(data, 28)
        raw_name = data[30:46]
    else:
        if len(data) - offset < LATER_RECORD_BYTES:
            raise native_error(
                "C7E-NATIVE-001",
                f"{len(data) - offset} bytes left at 0x{offset:x}, too few for a "
                f"{LATER_RECORD_BYTES}-byte record",
                where,
            )
        if data[offset : offset + 4] != MAP_MARKER:
            raise native_error(
                "C7E-NATIVE-001",
                f"expected {MAP_MARKER!r} at 0x{offset:x}, found "
                f"{data[offset:offset + 4]!r}",
                where,
            )
        plane_offsets = tuple(_u32(data, offset + 4 + plane * 4) for plane in range(PLANE_COUNT))
        plane_lengths = tuple(_u16(data, offset + 16 + plane * 2) for plane in range(PLANE_COUNT))
        width = _u16(data, offset + 22)
        height = _u16(data, offset + 24)
        raw_name = data[offset + 26 : offset + 42]

    return (
        NativeName.from_raw(raw_name),
        width,
        height,
        plane_offsets,  # type: ignore[return-value]
        plane_lengths,  # type: ignore[return-value]
    )


def parse_archive(data: bytes, *, log: DiagnosticLog | None = None) -> Archive:
    """Parse a whole archive, applying the engine's acceptance rules."""
    diagnostics = log if log is not None else DiagnosticLog()
    if len(data) > _U32_MAX:
        raise native_error(
            "C7E-NATIVE-001", f"file is {len(data)} bytes; offsets are 32-bit"
        )

    records: list[MapRecord] = []
    offset = 0
    terminated = False

    while offset < len(data):
        # The engine only reads a terminator when exactly four bytes remain,
        # so `!ID!` anywhere else is a record marker or an error, never an end.
        if len(data) - offset == 4:
            if data[offset : offset + 4] == MAP_MARKER:
                offset += 4
                terminated = True
                break

        if len(records) >= MAX_MAPS:
            raise native_error(
                "C7E-NATIVE-001",
                f"archive holds more than {MAX_MAPS} maps, the engine's fixed limit",
                f"0x{offset:x}",
            )

        index = len(records)
        where = f"map {index + 1}"
        name, width, height, plane_offsets, plane_lengths = _parse_header(data, offset, index)
        validate_dimensions(width, height, where=where)

        header_bytes = FIRST_RECORD_BYTES if index == 0 else LATER_RECORD_BYTES
        minimum_plane_offset = offset + header_bytes
        previous_end = 0
        for plane in range(PLANE_COUNT):
            start = plane_offsets[plane]
            end = start + plane_lengths[plane]
            if end > len(data):
                raise native_error(
                    "C7E-NATIVE-001",
                    f"plane {plane} runs 0x{start:x}+{plane_lengths[plane]} past the "
                    f"end of the {len(data)}-byte file",
                    where,
                )
            if plane == 0 and start < minimum_plane_offset:
                raise native_error(
                    "C7E-NATIVE-001",
                    f"plane 0 starts at 0x{start:x}, inside its own "
                    f"{header_bytes}-byte header ending at 0x{minimum_plane_offset:x}",
                    where,
                )
            if plane and start < previous_end:
                raise native_error(
                    "C7E-NATIVE-001",
                    f"plane {plane} starts at 0x{start:x}, overlapping plane "
                    f"{plane - 1} which ends at 0x{previous_end:x}",
                    where,
                )
            previous_end = end

        expected_words = width * height
        planes = tuple(
            decode_plane(
                data[plane_offsets[plane] : plane_offsets[plane] + plane_lengths[plane]],
                expected_words,
                where=f"{where} ({name.text}) plane {plane}",
                log=diagnostics,
            )
            for plane in range(PLANE_COUNT)
        )

        name.report(diagnostics, where)
        records.append(
            MapRecord(
                number=index + 1,
                name=name,
                planes=MapPlanes(width, height, planes),  # type: ignore[arg-type]
                source=RecordSource(offset, plane_offsets, plane_lengths),
            )
        )
        offset = plane_offsets[PLANE_COUNT - 1] + plane_lengths[PLANE_COUNT - 1]

    if offset != len(data):
        raise native_error(
            "C7E-NATIVE-001",
            f"{len(data) - offset} unexplained bytes after the last record at 0x{offset:x}",
        )
    if not records:
        raise native_error(
            "C7E-NATIVE-001",
            "archive contains no maps; the engine rejects an empty or marker-only file",
        )
    if not terminated:
        diagnostics.warning(
            "C7E-NATIVE-005",
            f"file ends at 0x{offset:x} without the conventional final {MAP_MARKER!r}; "
            "the engine loads it and the canonical writer adds one",
        )
    return Archive(tuple(records), diagnostics, terminated)


def encode_archive(records) -> bytes:
    """Write a canonical archive: implicit first offset, terminator, no runs of zero.

    Deterministic. Given the same records this returns the same bytes, which is
    what makes an export digest reproducible across machines.
    """
    records = tuple(records)
    if not 1 <= len(records) <= MAX_MAPS:
        raise native_error(
            "C7E-NATIVE-001",
            f"an archive holds 1..{MAX_MAPS} maps, not {len(records)}",
        )

    output = bytearray()
    for index, record in enumerate(records):
        where = f"map {index + 1}"
        planes = record.planes
        validate_dimensions(planes.width, planes.height, where=where)
        streams = tuple(
            encode_plane(planes.planes[plane], where=f"{where} plane {plane}")
            for plane in range(PLANE_COUNT)
        )

        header_offset = len(output)
        header_bytes = FIRST_RECORD_BYTES if index == 0 else LATER_RECORD_BYTES
        output.extend(b"\x00" * header_bytes)

        plane_offsets = []
        for stream in streams:
            plane_offsets.append(len(output))
            output.extend(stream)
        if plane_offsets[-1] + len(streams[-1]) > _U32_MAX:
            raise native_error("C7E-NATIVE-001", "archive exceeds the 32-bit offset space", where)

        raw_name = record.name.raw
        if len(raw_name) != NAME_FIELD_BYTES:
            raise native_error(
                "C7E-NATIVE-004",
                f"name field is {len(raw_name)} bytes, must be {NAME_FIELD_BYTES}",
                where,
            )
        lengths = tuple(len(stream) for stream in streams)

        if index == 0:
            # Plane 0's offset is not written: it is always immediately after
            # this header, which is exactly what the engine assumes.
            assert plane_offsets[0] == FIRST_RECORD_BYTES
            output[header_offset : header_offset + 12] = TED5_SIGNATURE
            struct.pack_into("<II", output, header_offset + 12, plane_offsets[1], plane_offsets[2])
            struct.pack_into("<HHH", output, header_offset + 20, *lengths)
            struct.pack_into("<HH", output, header_offset + 26, planes.width, planes.height)
            output[header_offset + 30 : header_offset + 46] = raw_name
        else:
            output[header_offset : header_offset + 4] = MAP_MARKER
            struct.pack_into("<III", output, header_offset + 4, *plane_offsets)
            struct.pack_into("<HHH", output, header_offset + 16, *lengths)
            struct.pack_into("<HH", output, header_offset + 22, planes.width, planes.height)
            output[header_offset + 26 : header_offset + 42] = raw_name

    output.extend(MAP_MARKER)
    return bytes(output)


def read_archive(path: Path | str, *, log: DiagnosticLog | None = None) -> Archive:
    """Parse an archive from disk. Read-only: the source is never opened for writing."""
    return parse_archive(Path(path).read_bytes(), log=log)

# --- ec7edit_core/assets.py ------------------------------------------

"""Bounded decoders for Corridor 7's graphics containers.

Every decoder here takes bytes and returns pixels. None of them opens a file,
none writes one, and none keeps a copy: the retail data is the user's, and the
editor's job is to look at it, not to own it. That is also why the cache at the
bottom is in memory and bounded -- an unbounded one would eventually be a copy
of the game on disk, with all the licensing that implies.

Three containers:

* the palette, which lives in `CORR7CD.EXE` rather than in any data file;
* `GFXTILES.CO7`, holding 64x64 wall pages and Wolfenstein column-post sprites;
* the `VGADICT`/`VGAHEAD`/`VGAGRAPH` set, holding Huffman-compressed planar
  pictures.

The decoders are deliberately defensive. This is third-party binary data of
unknown provenance -- a truncated file, a wrong file with the right name, a
sprite whose column posts point outside the page -- and the failure mode has
to be a clear exception, never a silent read past the end of a buffer.
"""



import struct
import zlib
from collections import OrderedDict
from dataclasses import dataclass

#: The 6-bit VGA DAC palette sits at this offset in the CD executable. There is
#: no copy of it in any .CO7 file, which is why the executable is one of the
#: required game files even though nothing ever runs it.
PALETTE_OFFSET = 0x2FFC0
PALETTE_SIZE = 768

WALL_SIZE = 64
SPRITE_SIZE = 64


class AssetError(ValueError):
    """A container did not decode. Always says which one and why."""


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


def load_palette(executable: bytes) -> list[int]:
    """Expand the embedded 6-bit DAC palette to 8-bit RGB triples.

    The six-bit check is the useful part: it is what tells a real Corridor 7
    executable from a file of the same name that happens to be long enough.
    """
    raw = executable[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE]
    if len(raw) != PALETTE_SIZE:
        raise AssetError(
            f"executable is {len(executable)} bytes; the palette needs "
            f"{PALETTE_OFFSET + PALETTE_SIZE}"
        )
    if any(component > 63 for component in raw):
        raise AssetError("no 6-bit VGA palette at the expected offset")
    # 6 bits to 8 by replicating the top two, which is what the DAC does.
    return [(component << 2) | (component >> 4) for component in raw]


def palette_rgb(palette: list[int], index: int) -> tuple[int, int, int]:
    return palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2]


# ---------------------------------------------------------------------------
# PNG, with nothing but zlib
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytes, *, alpha: bool) -> bytes:
    """Encode raw RGB or RGBA bytes as a PNG.

    Deterministic: fixed filter, fixed compression level, so the same pixels
    give the same file and a thumbnail digest means something.
    """
    channels = 4 if alpha else 3
    stride = width * channels
    if len(pixels) != stride * height:
        raise AssetError(f"{width}x{height} needs {stride * height} bytes, got {len(pixels)}")

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter 0, none
        raw += pixels[y * stride : (y + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# GFXTILES: walls and sprites
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GfxHeader:
    """The chunk directory at the head of GFXTILES.CO7."""

    chunk_count: int
    sprite_start: int
    sound_start: int
    offsets: tuple[int, ...]
    lengths: tuple[int, ...]

    def wall_pages(self) -> range:
        return range(0, self.sprite_start)

    def sprite_pages(self) -> range:
        return range(self.sprite_start, self.sound_start)

    def chunk(self, data: bytes, index: int) -> bytes:
        """One chunk's bytes, bounds-checked against the file."""
        if not 0 <= index < self.chunk_count:
            raise AssetError(f"chunk {index} is outside 0..{self.chunk_count - 1}")
        start, length = self.offsets[index], self.lengths[index]
        if start + length > len(data):
            raise AssetError(
                f"chunk {index} runs 0x{start:x}+{length} past the {len(data)}-byte file"
            )
        return data[start : start + length]


def parse_gfx_header(data: bytes) -> GfxHeader:
    if len(data) < 6:
        raise AssetError(f"GFXTILES is {len(data)} bytes, too short for a header")
    chunk_count, sprite_start, sound_start = struct.unpack_from("<HHH", data)
    directory = 6 + chunk_count * 6
    if chunk_count == 0 or directory > len(data):
        raise AssetError(
            f"GFXTILES declares {chunk_count} chunks, needing {directory} bytes of "
            f"directory in a {len(data)}-byte file"
        )
    if not sprite_start <= sound_start <= chunk_count:
        raise AssetError(
            f"GFXTILES boundaries are out of order: walls|{sprite_start}|"
            f"{sound_start}|{chunk_count}"
        )
    offsets = struct.unpack_from(f"<{chunk_count}I", data, 6)
    lengths = struct.unpack_from(f"<{chunk_count}H", data, 6 + chunk_count * 4)
    return GfxHeader(chunk_count, sprite_start, sound_start, offsets, lengths)


def wall_rgb(page: bytes, palette: list[int]) -> bytes:
    """Decode a 64x64 wall page to row-major RGB.

    Wall pages are stored column-major, which is the transpose everyone forgets
    once and then never again.
    """
    expected = WALL_SIZE * WALL_SIZE
    if len(page) < expected:
        raise AssetError(f"wall page is {len(page)} bytes, needs {expected}")

    out = bytearray(expected * 3)
    for y in range(WALL_SIZE):
        for x in range(WALL_SIZE):
            index = page[x * WALL_SIZE + y] * 3
            destination = (y * WALL_SIZE + x) * 3
            out[destination] = palette[index]
            out[destination + 1] = palette[index + 1]
            out[destination + 2] = palette[index + 2]
    return bytes(out)


def sprite_rgba(page: bytes, palette: list[int]) -> bytes:
    """Decode a Wolfenstein column-post sprite to 64x64 RGBA.

    Sprites are sparse: a left and right column bound, one command offset per
    column in between, and each command a chain of `(end, source, start)`
    triples terminated by a zero end. Everything an untrusted file could lie
    about here is checked, because every one of those values is an index.
    """
    if len(page) < 4:
        raise AssetError(f"sprite page is {len(page)} bytes, too short for its bounds")
    left, right = struct.unpack_from("<HH", page)
    if left > right or right >= SPRITE_SIZE:
        raise AssetError(f"sprite column range {left}..{right} is outside 0..{SPRITE_SIZE - 1}")
    if 4 + (right - left + 1) * 2 > len(page):
        raise AssetError("sprite page is too short for its column table")

    rgba = bytearray(SPRITE_SIZE * SPRITE_SIZE * 4)
    for x in range(left, right + 1):
        command = struct.unpack_from("<H", page, 4 + (x - left) * 2)[0]
        posts = 0
        while True:
            if command + 2 > len(page):
                raise AssetError(f"sprite column {x} post table runs past the page")
            end_word = struct.unpack_from("<H", page, command)[0]
            if end_word == 0:
                break
            if command + 6 > len(page):
                raise AssetError(f"sprite column {x} has a truncated post")
            source = struct.unpack_from("<h", page, command + 2)[0]
            start_word = struct.unpack_from("<H", page, command + 4)[0]
            start, end = start_word >> 1, end_word >> 1
            if start > end or end > SPRITE_SIZE or source + start < 0 or source + end > len(page):
                raise AssetError(f"sprite column {x} post {start}..{end} is out of range")
            for y in range(start, end):
                index = page[source + y] * 3
                destination = (y * SPRITE_SIZE + x) * 4
                rgba[destination] = palette[index]
                rgba[destination + 1] = palette[index + 1]
                rgba[destination + 2] = palette[index + 2]
                rgba[destination + 3] = 255
            command += 6
            posts += 1
            if posts > SPRITE_SIZE:
                raise AssetError(f"sprite column {x} has more posts than it has pixels")
    return bytes(rgba)


def average_color(rgb: bytes) -> tuple[int, int, int]:
    """The mean colour of an RGB buffer, for a palette swatch."""
    count = len(rgb) // 3
    if not count:
        return 0, 0, 0
    return sum(rgb[0::3]) // count, sum(rgb[1::3]) // count, sum(rgb[2::3]) // count


def is_blank(pixels: bytes, *, channels: int) -> bool:
    """True when nothing would be visible: all one colour, or fully transparent."""
    if not pixels:
        return True
    if channels == 4:
        return not any(pixels[3::4])
    return len(set(zip(pixels[0::3], pixels[1::3], pixels[2::3]))) <= 1


# ---------------------------------------------------------------------------
# VGAGRAPH: Huffman-compressed planar pictures
# ---------------------------------------------------------------------------


def _huff_expand(source: bytes, nodes: list[tuple[int, int]], expected: int) -> bytes:
    out = bytearray()
    node = 254
    for value in source:
        for bit in range(8):
            child = nodes[node][(value >> bit) & 1]
            if child < 256:
                out.append(child)
                if len(out) == expected:
                    return bytes(out)
                node = 254
            else:
                node = child - 256
    raise AssetError(f"Huffman chunk ended at {len(out)} of {expected} bytes")


@dataclass(frozen=True)
class VgaPicture:
    """One decoded VGAGRAPH picture, row-major RGB."""

    number: int  # the C7G#### id the engine uses
    width: int
    height: int
    rgb: bytes


def extract_vga(
    vgadict: bytes, vgahead: bytes, vgagraph: bytes, palette: list[int]
) -> list[VgaPicture]:
    """Decode every picture chunk.

    Chunk 0 is PICTABLE (the dimensions), 1 and 2 are fonts, 3 is TILE8, and
    the pictures start at 4 -- so picture *i* is chunk *i+4* and carries the
    engine's id *i+3*. A chunk whose size does not match its declared
    dimensions is skipped rather than guessed at.
    """
    if len(vgadict) < 255 * 4:
        raise AssetError(f"VGADICT is {len(vgadict)} bytes, needs {255 * 4}")
    nodes = list(struct.iter_unpack("<HH", vgadict[: 255 * 4]))
    offsets = [
        int.from_bytes(vgahead[i : i + 3], "little") for i in range(0, len(vgahead) - 2, 3)
    ]

    decoded: list[bytes] = []
    for index, start in enumerate(offsets):
        if start >= len(vgagraph):
            break
        end = offsets[index + 1] if index + 1 < len(offsets) else len(vgagraph)
        if not start + 4 <= end <= len(vgagraph):
            raise AssetError(f"VGAGRAPH chunk {index} spans 0x{start:x}..0x{end:x}")
        expected = struct.unpack_from("<I", vgagraph, start)[0]
        decoded.append(_huff_expand(vgagraph[start + 4 : end], nodes, expected))

    if not decoded:
        raise AssetError("VGAGRAPH decoded to no chunks")

    table = decoded[0]
    dimensions = []
    for width, height in struct.iter_unpack("<HH", table[: len(table) & ~3]):
        if not (0 < width <= 640 and 0 < height <= 480):
            break
        dimensions.append((width, height))

    pictures: list[VgaPicture] = []
    for index in range(min(len(dimensions), max(0, len(decoded) - 4))):
        width, height = dimensions[index]
        data = decoded[index + 4]
        if len(data) != width * height or width % 4:
            continue
        pictures.append(
            VgaPicture(index + 3, width, height, _unplane(data, width, height, palette))
        )
    return pictures


def _unplane(data: bytes, width: int, height: int, palette: list[int]) -> bytes:
    """Undo VGA's four-plane interleave into row-major RGB."""
    plane = width * height // 4
    rgb = bytearray(width * height * 3)
    for y in range(height):
        row = y * (width // 4)
        for x in range(width):
            index = data[(x & 3) * plane + row + (x >> 2)] * 3
            destination = (y * width + x) * 3
            rgb[destination] = palette[index]
            rgb[destination + 1] = palette[index + 1]
            rgb[destination + 2] = palette[index + 2]
    return bytes(rgb)


# ---------------------------------------------------------------------------
# A bounded cache
# ---------------------------------------------------------------------------


class ImageCache:
    """Least-recently-used, bounded by total bytes rather than entry count.

    Entry count is the wrong unit here: a 320x200 picture is fifty times a
    wall page, so a hundred-entry cache is somewhere between 1 and 60 MB
    depending on what the user happened to click. Bytes are what the machine
    actually has.
    """

    def __init__(self, budget_bytes: int = 32 << 20) -> None:
        self.budget = budget_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._size = 0
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def size_bytes(self) -> int:
        return self._size

    def get(self, key: str):
        if key in self._entries:
            self._entries.move_to_end(key)
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        return None

    def put(self, key: str, value: bytes) -> None:
        if key in self._entries:
            self._size -= len(self._entries.pop(key))
        # An item larger than the whole budget is not cached; caching it would
        # evict everything and then itself.
        if len(value) > self.budget:
            return
        self._entries[key] = value
        self._size += len(value)
        while self._size > self.budget:
            _, evicted = self._entries.popitem(last=False)
            self._size -= len(evicted)

    def fetch(self, key: str, produce):
        """Get, or produce and store. The only method callers normally need."""
        found = self.get(key)
        if found is None:
            found = produce()
            self.put(key, found)
        return found

    def clear(self) -> None:
        self._entries.clear()
        self._size = 0

# --- ec7edit_core/decorate.py ----------------------------------------

"""Reader for the Corridor 7 DECORATE actors the engine defines.

XLAT says which class a map word spawns; DECORATE says what that class *is* --
what it inherits from, which sprite page it shows when it is standing still,
and what the person who wrote it said about it in the comment above. All three
matter to a catalogue entry, and all three are already in the repository, so
the alternative to reading them is maintaining a copy that goes stale the first
time somebody fixes an actor.

Sprite pages are the join to the artwork: a DECORATE frame `C001 A -1` names
page 1 of `GFXTILES.CO7`'s sprite range, which is what the palette browser has
to draw. The `Spawn` state's first page is the one an editor should show,
because that is what the map looks like before anything moves.

This reads either the source tree (`wadsrc/static/actors/corridor7/`) or a
built `ec7wolf.pk3`. Same parser, same result -- the pk3's copies are the same
text.
"""



import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

#: A DECORATE sprite frame: four-character page name, then frame letters.
#: Corridor 7's are all `C` plus three digits.
_SPRITE = re.compile(r"\bC(\d{3})\s+[A-Z]")
_ACTOR = re.compile(r"^\s*actor\s+(\w+)\s*(?::\s*(\w+))?", re.IGNORECASE)
_STATE_LABEL = re.compile(
    r"^\s*(Spawn|See|Path|Missile|Melee|Pain|Death|Raise|Idle)\s*:", re.IGNORECASE
)

SOURCES = ("monsters", "statics", "player")

#: Engine base classes, by what an actor inheriting from one of them *is*.
#: Matched against the root of the inheritance chain, not the immediate parent,
#: so `C7Disintegrator : C7Weapon : Weapon` reaches "item" in one step of
#: resolution rather than needing its own rule.
_ROOT_ROLES = {
    "weapon": "item",
    "ammo": "item",
    "health": "item",
    "key": "item",
    "inventory": "item",
    "custominventory": "item",
    "scoreitem": "item",
    "maprevealer": "item",
    "armor": "item",
    "basicarmorpickup": "item",
    "powerup": "item",
    "powerupgiver": "item",
    "wolfensteinmonster": "enemy",
    "playerpawn": "player",
}


@dataclass
class ActorInfo:
    """One DECORATE actor, as much as an editor needs to describe it."""

    name: str
    parent: str
    source: str  # which file it came from
    role: str  # enemy | item | decoration | effect | player
    note: str  # the comment above the declaration, if any
    spawn_sprite: int | None = None
    sprites: set[int] = field(default_factory=set)
    states: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def blocking(self) -> bool:
        """Whether walking into it is refused. Decorations mostly block."""
        return self.role in ("enemy", "decoration")


def classify(actors: dict[str, "ActorInfo"], name: str) -> str:
    """Decide what an actor is by following its inheritance to the root.

    The file an actor is declared in is not the answer: `player.txt` holds the
    weapons and the inventory as well as the pawn, and the projectiles live
    beside the monsters that fire them. Only the chain says what something is.

    Deliberately conservative at the end of the chain: an actor that reaches a
    root nothing recognises becomes a decoration, which is the safest thing for
    an editor to draw and the least likely to imply behaviour it lacks.
    """
    seen: set[str] = set()
    current = name
    while current and current not in seen:
        seen.add(current)
        info = actors.get(current)
        parent = info.parent if info else ""
        role = _ROOT_ROLES.get(parent.lower())
        if role:
            return role
        if not parent:
            break
        if parent not in actors:
            # An unresolved parent is a fact, not a guess to paper over.
            return _ROOT_ROLES.get(parent.lower(), "decoration")
        current = parent

    # Nothing in the chain named a known base. Fall back on where it lives:
    # an actor declared among the monsters that has no monster root is one of
    # their projectiles or effects.
    info = actors.get(name)
    if info and info.source == "monsters":
        return "effect"
    return "decoration"


def parse_decorate(text: str, source: str) -> dict[str, ActorInfo]:
    """Parse one DECORATE file into actors keyed by class name."""
    actors: dict[str, ActorInfo] = {}
    lines = text.splitlines()
    pending: list[str] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("//"):
            pending.append(stripped.lstrip("/ ").strip())
            index += 1
            continue

        match = _ACTOR.match(lines[index])
        if not match:
            # Any other content ends a comment's association with what follows.
            if stripped and not stripped.startswith(("/*", "*")):
                pending = []
            index += 1
            continue

        name, parent = match.group(1), (match.group(2) or "")
        note = " ".join(part for part in pending if part).strip()
        pending = []

        body: list[str] = []
        depth = 0
        started = False
        while index < len(lines):
            line = lines[index]
            depth += line.count("{") - line.count("}")
            body.append(line)
            if "{" in line:
                started = True
            index += 1
            if started and depth <= 0:
                break

        info = ActorInfo(name, parent, source, "", note)
        label = None
        for line in body:
            found = _STATE_LABEL.match(line)
            if found:
                label = found.group(1).capitalize()
            for sprite in _SPRITE.finditer(line):
                page = int(sprite.group(1))
                info.sprites.add(page)
                if label:
                    info.states[page].add(label)
                if info.spawn_sprite is None and label in (None, "Spawn"):
                    info.spawn_sprite = page
        if info.spawn_sprite is None and info.sprites:
            info.spawn_sprite = min(info.sprites)
        actors[name] = info

    return actors


def resolve_roles(actors: dict[str, ActorInfo]) -> dict[str, ActorInfo]:
    """Fill in every actor's role once the whole graph is known."""
    for name, info in actors.items():
        info.role = classify(actors, name)
    return actors


def read_actors_from_source(root: Path | str) -> dict[str, ActorInfo]:
    """Read `wadsrc/static/actors/corridor7/` out of a checkout."""
    root = Path(root)
    actors: dict[str, ActorInfo] = {}
    for source in SOURCES:
        path = root / f"{source}.txt"
        if path.exists():
            actors.update(parse_decorate(path.read_text(encoding="latin-1"), source))
    return resolve_roles(actors)


def read_actors_from_pk3(path: Path | str) -> dict[str, ActorInfo]:
    """Read the same files out of a built `ec7wolf.pk3`."""
    actors: dict[str, ActorInfo] = {}
    with zipfile.ZipFile(path) as archive:
        for source in SOURCES:
            try:
                raw = archive.read(f"actors/corridor7/{source}.txt")
            except KeyError:
                continue
            actors.update(parse_decorate(raw.decode("latin-1"), source))
    return resolve_roles(actors)



# --------------------------------------------------------------------------
# Adapters: the shapes this gallery grew up with, over the canonical codecs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GameMap:
    """The flat view of a map this gallery was written against."""

    index: int
    name: str
    width: int
    height: int
    planes: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]


def parse_maps(data: bytes) -> list[GameMap]:
    """Read MAPTEMP through the production codec, then flatten it."""
    return [
        GameMap(
            record.number - 1,
            record.name.text,
            record.width,
            record.height,
            record.planes.planes,
        )
        for record in parse_archive(data)
    ]


def parse_actors(pk3: zipfile.ZipFile) -> dict[str, ActorInfo]:
    """DECORATE actors from an already-open pk3, for the browser's sprite join."""
    actors: dict[str, ActorInfo] = {}
    for source in SOURCES:
        try:
            raw = pk3.read(f"actors/corridor7/{source}.txt")
        except KeyError:
            continue
        actors.update(parse_decorate(raw.decode("latin-1"), source))
    return resolve_roles(actors)


# Curated knowledge base (from the Technical & Strategy Compendium + repo docs)
# --------------------------------------------------------------------------

ENEMY_MANUAL = [
    # name, type, health, damage, levels, score, notes
    ("Alioprobe", "Guard / sentry", "25", "Low", "20-39", "100",
     "Slow alarm unit, dangerous in packs; clear quickly before it draws traffic."),
    ("Animated Probe", "Centurion", "100", "Low", "1-40", "400",
     "Extremely fast, sound-reactive, sometimes ambush placed; electronic whine."),
    ("Bandor", "Guard / morpher", "50", "High", "5-39", "500",
     "Disguises as furniture/plants; morph sound; other Bandors may rush a kill site."),
    ("Eitak", "Guard", "100", "Medium", "30-40", "800",
     "Primary alien-world guard; accurate in groups; use sustained fire and open space."),
    ("Eniram", "Warrior / cloaked", "200", "Medium", "2-40", "1,000",
     "Invisible until firing; infrared or proximity map required; distinct decloak sound."),
    ("Eniram Boss", "Boss", "2,000", "Very high", "5 and 30", "2,500",
     "Solid / non-cloaking; Plasma Rifle; avoid narrow corridors."),
    ("Mechanoid Warrior", "Boss", "1,000", "Very high", "10-40", "2,500",
     "Slow, audible footsteps, brutal close-range fire; may drop Dual Blaster."),
    ("Otrebor", "Sub-boss / technician", "200", "High", "24-40", "700",
     "Usually alone; evil laugh; burst down from range."),
    ("Rodex", "Centurion", "50", "Medium", "2-40", "700",
     "Pack attacker; may retreat/turn away; distinctive squeal."),
    ("Semaj", "Low-floor predator", "100", "Low", "31-40", "100",
     "Purple slime that attacks legs; no ranged weapon; easy to miss in larger fights."),
    ("Solrac", "Leader / boss", "3,000", "Very high", "25 and 30", "2,500",
     "Eye-energy attack; apparitions elsewhere are untouchable; alien weapons preferred."),
    ("Tebazile", "Guardian boss", "1,000 x5", "High", "40", "10,000",
     "Five-stage morph: Tebazile -> Eniram Boss -> Tymok -> Solrac -> Tebazile."),
    ("Tenaj", "Technician", "150", "Medium", "6-40", "700",
     "Smart, quick, ambush-prone; often turns away; may drop charge packs."),
    ("Ttocs", "Warrior", "150", "Medium", "14-40", "700",
     "Slow and not bright, but durable; maintain distance; squishy alert sound."),
    ("Tymok", "Boss", "2,000", "Very high", "15-39", "2,500",
     "Fast dodger with Plasma Rifle; works alone; keep moving and mine approach lanes."),
    ("Nerraw", "Surprise", "Unknown", "Extremely lethal", "31-39", "-",
     "Small and apparently harmless; can kill a strong Marine in seconds. First seen on 31."),
]

WEAPON_MANUAL = [
    ("1", "Taser", "None", "Short", "0-255", "Unlimited but slow; emergency fallback."),
    ("2", "Assault Shotgun", "5 std/shot", "Medium", "25-350", "CD-only; strongest at close range."),
    ("3", "M-24 C.A.W.", "1 std/shot", "Medium", "0-255", "Fast automatic; the Marine's starter."),
    ("4", "M-343 Tribarrel", "1 std/round, 3-round burst", "Long", "(0-255) x3", "Preferred human weapon at distance."),
    ("5", "Alien Dual Blaster", "2 energy/shot", "Medium", "0-255", "Economical alien sidearm."),
    ("6", "Alien Plasma Rifle", "3-5 net energy/shot", "Short-med", "(0-255)+25 splash", "Traveling plasma; ~10ft blast; can detonate mines."),
    ("7", "Alien Assault Cannon", "0-2 energy/burst", "Long", "0-255", "Four-round burst; very efficient; CD-only."),
    ("8", "Alien Disintegrator", "44-46 energy/shot", "Long", "1,000", "Boss/emergency weapon; enormous energy cost; CD-only."),
    ("M", "Proximity Mine", "1 mine", "Triggered", "(2-400)+100", "15ft blast; lethal to the Marine; max 25 carried."),
]

# Plane-0 (map geometry) semantics, keyed by the raw map word.
WALL_CODE_NOTES = {
    63: "Player-use normal elevator switch.",
    105: "Sight-transparent special wall page.",
    107: "Sight-transparent special wall page.",
    251: "Door (axis inferred from map topology).",
    252: "Door requiring the RED access card.",
    253: "Door requiring the BLUE access card.",
    254: "Door (axis inferred from map topology).",
}

# Plane-1 static object table: map word -> static index (word 23 == static 0).
STATIC_WORD_BASE = 23


# --------------------------------------------------------------------------
# Catalog assembly
# --------------------------------------------------------------------------


@dataclass
class Asset:
    id: str
    category: str
    subcategory: str
    name: str
    width: int
    height: int
    kind: str  # png | wav
    meta: dict
    search: str
    blank: bool = False


class Library:
    def __init__(self, root: Path):
        self.root = root
        self.media: dict[str, bytes] = {}
        self.assets: dict[str, Asset] = {}
        self.order: list[str] = []
        self._load()

    # -- helpers ----------------------------------------------------------
    def _read(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def _add(self, asset: Asset, media: bytes) -> None:
        self.assets[asset.id] = asset
        self.media[asset.id] = media
        self.order.append(asset.id)

    # -- loading ----------------------------------------------------------
    def _load(self) -> None:
        exe = self._read("CORR7CD.EXE")
        palette = load_palette(exe)

        maps = parse_maps(self._read("MAPTEMP.CO7"))
        actors = {}
        try:
            with zipfile.ZipFile(self.root / "ecwolf.pk3") as pk3:
                actors = parse_actors(pk3)
        except (FileNotFoundError, KeyError, zipfile.BadZipFile):
            actors = {}

        # Cross-reference tables from the maps.
        wall_usage: dict[int, Counter] = defaultdict(Counter)  # wall page -> {map_index: cells}
        object_usage: dict[int, Counter] = defaultdict(Counter)  # plane1 word -> {map_index: cells}
        for gm in maps:
            for word in gm.planes[0]:
                if 1 <= word <= 250:
                    wall_usage[word - 1][gm.index] += 1
            for word in gm.planes[1]:
                if word != 18:
                    object_usage[word][gm.index] += 1

        # sprite page -> list of (actor, role, states)
        sprite_actors: dict[int, list[ActorInfo]] = defaultdict(list)
        for info in actors.values():
            for page in info.sprites:
                sprite_actors[page].append(info)

        self._load_walls(palette, wall_usage, maps)
        self._load_sprites(palette, sprite_actors, object_usage, maps)
        self._load_pictures(palette)
        self._load_maps(maps, palette)
        self.maps = maps

    def _load_walls(self, palette, wall_usage, maps):
        data = self._read("GFXTILES.CO7")
        h = parse_gfx_header(data)
        self._gfx = h
        self._gfx_data = data
        self._palette = palette
        for i in range(h.sprite_start):
            page = data[h.offsets[i] : h.offsets[i] + h.lengths[i]]
            rgb = wall_rgb(page, palette)
            r, g, b = average_color(rgb)
            used_in = sorted(wall_usage.get(i, {}).keys())
            total = sum(wall_usage.get(i, {}).values())
            note = WALL_CODE_NOTES.get(i + 1, "")
            meta = {
                "GFXTILES page": i,
                "Map word (plane 0)": i + 1,
                "Avg color": f"#{r:02x}{g:02x}{b:02x}",
                "Cells placed": total,
                "Appears in levels": [maps[m].name for m in used_in] if used_in else [],
                "Note": note,
            }
            asset = Asset(
                id=f"wall-{i:03d}",
                category="Walls",
                subcategory="Doors & Elevators" if note else ("In use" if total else "Unused"),
                name=f"Wall {i:03d}",
                width=64, height=64, kind="png",
                meta=meta,
                search=f"wall {i} {note}".lower(),
            )
            self._add(asset, encode_png(64, 64, rgb, alpha=False))

    def _load_sprites(self, palette, sprite_actors, object_usage, maps):
        h = self._gfx
        data = self._gfx_data
        role_to_sub = {
            "enemy": "Enemies",
            "decoration": "Decorations",
            "item": "Items & Pickups",
            "effect": "Effects & Projectiles",
            "player": "Player",
        }
        for i in range(h.sprite_start, h.sound_start):
            page = data[h.offsets[i] : h.offsets[i] + h.lengths[i]]
            sub_index = i - h.sprite_start  # C### number
            infos = sprite_actors.get(sub_index, [])
            # choose the most descriptive owner: enemy > item > decoration > effect
            priority = {"enemy": 0, "item": 1, "decoration": 2, "player": 3, "effect": 4}
            infos_sorted = sorted(infos, key=lambda a: priority.get(a.role, 9))
            owner = infos_sorted[0] if infos_sorted else None
            blank = False
            try:
                rgba = sprite_rgba(page, palette)
                if not any(rgba[3::4]):
                    blank = True
            except Exception:
                rgba = bytes(64 * 64 * 4)
                blank = True

            role = owner.role if owner else "decoration"
            subcategory = role_to_sub.get(role, "Uncategorized")
            if not owner:
                subcategory = "Uncategorized"

            name = f"C{sub_index:03d}"
            title = name
            if owner:
                title = f"{name} · {_pretty_actor(owner.name)}"

            meta = {
                "Sprite name": name,
                "GFXTILES chunk": i,
                "Owner actor": owner.name if owner else "(none identified)",
                "Role": role.title() if owner else "Unidentified",
                "Also used by": [a.name for a in infos_sorted[1:]] if len(infos_sorted) > 1 else [],
                "Appears in states": sorted(owner.states.get(sub_index, [])) if owner else [],
                "Actor note": owner.note if owner and owner.note else "",
            }
            asset = Asset(
                id=f"sprite-{sub_index:03d}",
                category="Sprites",
                subcategory=subcategory,
                name=title,
                width=64, height=64, kind="png",
                meta=meta,
                search=f"{name} {owner.name if owner else ''} {role} {subcategory}".lower(),
                blank=blank,
            )
            self._add(asset, encode_png(64, 64, rgba, alpha=True))

    def _load_pictures(self, palette):
        pics = extract_vga(
            self._read("VGADICT.CO7"),
            self._read("VGAHEAD.CO7"),
            self._read("VGAGRAPH.CO7"),
            palette,
        )
        for picture in pics:
            w, h, rgb, chunk_id = picture.width, picture.height, picture.rgb, picture.number
            name = f"C7G{chunk_id:04d}"
            sub = "HUD & Status" if 23 <= chunk_id <= 74 else "Screens & UI"
            meta = {
                "Picture id": name,
                "VGAGRAPH chunk": chunk_id,
                "Dimensions": f"{w} x {h}",
            }
            asset = Asset(
                id=f"pic-{chunk_id:04d}",
                category="Pictures",
                subcategory=sub,
                name=name,
                width=w, height=h, kind="png",
                meta=meta,
                search=f"{name} picture vga".lower(),
            )
            self._add(asset, encode_png(w, h, rgb, alpha=False))

    def _load_maps(self, maps, palette):
        for gm in maps:
            png, census = render_map(gm, self)
            enemies = sum(c for w, c in census.items() if w >= 108)
            statics = sum(c for w, c in census.items() if 23 <= w <= 105)
            meta = {
                "Internal name": gm.name,
                "Level number": gm.index + 1,
                "Dimensions": f"{gm.width} x {gm.height}",
                "Wall cells": sum(1 for v in gm.planes[0] if 1 <= v <= 250),
                "Door cells": sum(1 for v in gm.planes[0] if 251 <= v <= 254),
                "Object placements": statics,
                "Actor/enemy markers": enemies,
            }
            low = gm.name.lower()
            if "secret" in low:
                sub = "Secret / Bonus Floors"
            elif "network" in low:
                sub = "Network Levels"
            else:
                sub = "Campaign Floors"
            asset = Asset(
                id=f"map-{gm.index:02d}",
                category="Maps",
                subcategory=sub,
                name=f"{gm.index + 1:02d} · {gm.name}",
                width=gm.width, height=gm.height, kind="png",
                meta=meta,
                search=f"map level {gm.index + 1} {gm.name}".lower(),
            )
            self._add(asset, png)

    # -- serialization ----------------------------------------------------
    def catalog(self) -> dict:
        cats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        items = []
        for aid in self.order:
            a = self.assets[aid]
            cats[a.category][a.subcategory] += 1
            items.append({
                "id": a.id,
                "category": a.category,
                "subcategory": a.subcategory,
                "name": a.name,
                "w": a.width,
                "h": a.height,
                "blank": a.blank,
                "search": a.search,
            })
        categories = []
        for cat, subs in cats.items():
            categories.append({
                "name": cat,
                "count": sum(subs.values()),
                "subcategories": [{"name": s, "count": n} for s, n in subs.items()],
            })
        return {
            "title": "Corridor 7: Alien Invasion",
            "categories": categories,
            "items": items,
            "reference": {
                "enemies": ENEMY_MANUAL,
                "weapons": WEAPON_MANUAL,
            },
        }

    def detail(self, aid: str) -> dict | None:
        a = self.assets.get(aid)
        if not a:
            return None
        return {
            "id": a.id,
            "name": a.name,
            "category": a.category,
            "subcategory": a.subcategory,
            "w": a.width,
            "h": a.height,
            "blank": a.blank,
            "kind": a.kind,
            "meta": a.meta,
        }


def _pretty_actor(name: str) -> str:
    n = re.sub(r"^C7", "", name)
    n = re.sub(r"(?<!^)(?=[A-Z])", " ", n)
    return n.strip()


def render_map(gm: GameMap, lib: "Library") -> tuple[bytes, Counter]:
    """Render a schematic top-down automap and return (png, object census)."""
    scale = max(3, min(8, 640 // max(gm.width, gm.height)))
    w, h = gm.width, gm.height
    img = bytearray(w * scale * h * scale * 3)

    def put(cx, cy, color):
        for dy in range(scale):
            for dx in range(scale):
                px = cx * scale + dx
                py = cy * scale + dy
                d = (py * w * scale + px) * 3
                img[d], img[d + 1], img[d + 2] = color

    plane0, plane1 = gm.planes[0], gm.planes[1]
    for idx, v in enumerate(plane0):
        cx, cy = idx % w, idx // w
        if 1 <= v <= 250:
            color = (150, 150, 160)  # wall
        elif 251 <= v <= 254:
            color = (220, 180, 60)   # door
        elif v == 63:
            color = (80, 220, 120)   # elevator
        elif 256 <= v <= 287:
            color = (26, 30, 40)     # area / floor
        else:
            color = (12, 14, 18)
        put(cx, cy, color)

    census: Counter = Counter()
    for idx, v in enumerate(plane1):
        if v == 18:
            continue
        census[v] += 1
        cx, cy = idx % w, idx // w
        if 19 <= v <= 22:
            dot = (255, 255, 255)   # player start
        elif v >= 108:
            dot = (235, 70, 70)     # actor / enemy
        elif 23 <= v <= 105:
            dot = (70, 200, 235)    # static object
        else:
            continue
        # small centered dot
        for dy in range(max(1, scale - 2)):
            for dx in range(max(1, scale - 2)):
                px = cx * scale + 1 + dx
                py = cy * scale + 1 + dy
                d = (py * w * scale + px) * 3
                img[d], img[d + 1], img[d + 2] = dot

    return encode_png(w * scale, h * scale, bytes(img), alpha=False), census


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    library: Library = None  # set on the class before serving

    def log_message(self, *args):  # keep the console quiet
        pass

    def _send(self, code, body, ctype, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/catalog":
            body = json.dumps(self.library.catalog()).encode("utf-8")
            self._send(200, body, "application/json")
        elif path.startswith("/api/asset/"):
            detail = self.library.detail(path[len("/api/asset/"):])
            if detail is None:
                self._send(404, b"{}", "application/json")
            else:
                self._send(200, json.dumps(detail).encode("utf-8"), "application/json")
        elif path.startswith("/media/"):
            aid = path[len("/media/"):].rsplit(".", 1)[0]
            blob = self.library.media.get(aid)
            if blob is None:
                self._send(404, b"", "text/plain")
            else:
                self._send(200, blob, "image/png", cache=True)
        else:
            self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser(description="Corridor 7 asset gallery")
    ap.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent,
                    help="directory containing the Corridor 7 release files")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    print(f"Loading Corridor 7 assets from {args.dir} ...")
    library = Library(args.dir)
    print(f"  decoded {len(library.assets)} assets into memory")
    Handler.library = library
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Serving the Corridor 7 asset browser at {url}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


# --------------------------------------------------------------------------
# Front-end (single embedded page)
# --------------------------------------------------------------------------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Corridor 7 — Asset Browser</title>
<style>
  :root{
    --bg:#0c0e13; --panel:#141821; --panel2:#1b2130; --line:#262d3d;
    --text:#e6e9f0; --dim:#8a93a6; --accent:#38e1b0; --accent2:#5aa9ff;
    --danger:#ff5a5a;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font:14px/1.5 "Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  a{color:var(--accent2);text-decoration:none}
  header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:18px;
    padding:14px 22px;background:linear-gradient(180deg,#11141c,#0c0e13);
    border-bottom:1px solid var(--line)}
  header h1{font-size:16px;margin:0;letter-spacing:.5px;font-weight:700}
  header h1 span{color:var(--accent)}
  .tag{font-size:11px;color:var(--dim);border:1px solid var(--line);
    padding:2px 8px;border-radius:20px}
  #search{margin-left:auto;background:var(--panel2);border:1px solid var(--line);
    color:var(--text);padding:9px 14px;border-radius:8px;width:280px;outline:none}
  #search:focus{border-color:var(--accent)}
  .layout{display:flex;min-height:calc(100vh - 55px)}
  nav{width:220px;flex:none;border-right:1px solid var(--line);padding:14px 10px;
    background:var(--panel)}
  .cat{margin-bottom:6px}
  .cat>button{width:100%;text-align:left;background:none;border:none;color:var(--text);
    font-size:13px;font-weight:600;padding:8px 10px;border-radius:7px;cursor:pointer;
    display:flex;justify-content:space-between;align-items:center}
  .cat>button:hover{background:var(--panel2)}
  .cat.active>button{background:var(--panel2);color:var(--accent)}
  .cat .n{color:var(--dim);font-weight:500;font-size:11px}
  .subs{margin:2px 0 6px 6px;display:none}
  .cat.open .subs{display:block}
  .subs button{width:100%;text-align:left;background:none;border:none;color:var(--dim);
    font-size:12px;padding:5px 10px;border-radius:6px;cursor:pointer;
    display:flex;justify-content:space-between}
  .subs button:hover{background:var(--panel2);color:var(--text)}
  .subs button.active{color:var(--accent)}
  main{flex:1;padding:18px 22px;overflow:auto}
  .crumbs{color:var(--dim);font-size:12px;margin-bottom:14px}
  .crumbs b{color:var(--text)}
  .grid{display:grid;gap:12px;
    grid-template-columns:repeat(auto-fill,minmax(108px,1fr))}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:8px;cursor:pointer;transition:.12s;display:flex;flex-direction:column;gap:6px}
  .card:hover{border-color:var(--accent);transform:translateY(-2px)}
  .thumb{width:100%;aspect-ratio:1;background:
      linear-gradient(45deg,#0a0c10 25%,transparent 25%,transparent 75%,#0a0c10 75%) 0 0/16px 16px,
      linear-gradient(45deg,#0a0c10 25%,#111 25%,#111 75%,#0a0c10 75%) 8px 8px/16px 16px;
    border-radius:6px;display:flex;align-items:center;justify-content:center;overflow:hidden}
  .thumb img{max-width:100%;max-height:100%;image-rendering:pixelated}
  .card .lbl{font-size:11px;color:var(--dim);white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}
  .card.blank .thumb::after{content:"empty";color:#3a4256;font-size:10px}
  .count{color:var(--dim);font-size:12px;margin-bottom:10px}
  /* modal */
  .overlay{position:fixed;inset:0;background:rgba(4,6,10,.72);backdrop-filter:blur(3px);
    display:none;align-items:center;justify-content:center;z-index:50;padding:24px}
  .overlay.show{display:flex}
  .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;
    width:min(860px,100%);max-height:90vh;overflow:auto;display:grid;
    grid-template-columns:340px 1fr}
  .preview{background:#07090d;border-right:1px solid var(--line);padding:22px;
    display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px}
  .preview .stage{width:280px;height:280px;display:flex;align-items:center;justify-content:center;
    background:
      linear-gradient(45deg,#0a0c10 25%,transparent 25%,transparent 75%,#0a0c10 75%) 0 0/24px 24px,
      linear-gradient(45deg,#0a0c10 25%,#101319 25%,#101319 75%,#0a0c10 75%) 12px 12px/24px 24px;
    border-radius:10px;overflow:hidden}
  .preview .stage img{image-rendering:pixelated;max-width:100%;max-height:100%}
  .zoomrow{display:flex;gap:8px;align-items:center;color:var(--dim);font-size:12px}
  .zoomrow input{flex:1}
  .details{padding:22px}
  .details h2{margin:0 0 2px;font-size:20px}
  .details .sub{color:var(--accent);font-size:12px;margin-bottom:16px}
  table.meta{width:100%;border-collapse:collapse;font-size:13px}
  table.meta td{padding:7px 4px;border-bottom:1px solid var(--line);vertical-align:top}
  table.meta td.k{color:var(--dim);width:150px}
  table.meta a.chip,span.chip{display:inline-block;background:var(--panel2);border:1px solid var(--line);
    border-radius:5px;padding:1px 7px;margin:2px 3px 0 0;font-size:11px;color:var(--text)}
  .close{position:absolute;top:18px;right:22px;background:var(--panel2);border:1px solid var(--line);
    color:var(--text);width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:16px}
  .lore{margin-top:16px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;
    padding:14px;font-size:13px}
  .lore h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--dim)}
  .manual{overflow:auto}
  .manual table{width:100%;border-collapse:collapse;font-size:12px}
  .manual th,.manual td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
  .manual th{color:var(--dim);position:sticky;top:0;background:var(--panel)}
  .empty{color:var(--dim);padding:40px;text-align:center}
</style>
</head>
<body>
<header>
  <h1>CORRIDOR&nbsp;<span>7</span> · Asset Browser</h1>
  <span class="tag" id="assetcount">…</span>
  <input id="search" placeholder="Search all assets…" autocomplete="off">
</header>
<div class="layout">
  <nav id="nav"></nav>
  <main id="main"><div class="empty">Loading assets…</div></main>
</div>

<div class="overlay" id="overlay">
  <div class="modal" id="modal"></div>
  <button class="close" id="closebtn" style="display:none">✕</button>
</div>

<script>
let CATALOG=null, STATE={cat:null,sub:null,query:""};

async function boot(){
  CATALOG = await (await fetch('/api/catalog')).json();
  document.getElementById('assetcount').textContent = CATALOG.items.length + ' assets';
  STATE.cat = CATALOG.categories[0].name;
  renderNav(); renderGrid();
}

function renderNav(){
  const nav=document.getElementById('nav');
  nav.innerHTML='';
  for(const c of CATALOG.categories){
    const div=document.createElement('div');
    div.className='cat'+(c.name===STATE.cat?' active open':'');
    const subs=c.subcategories.map(s=>
      `<button data-sub="${s.name}" class="${STATE.cat===c.name&&STATE.sub===s.name?'active':''}">
         <span>${s.name}</span><span class="n">${s.count}</span></button>`).join('');
    div.innerHTML=`<button data-cat="${c.name}">
        <span>${c.name}</span><span class="n">${c.count}</span></button>
        <div class="subs">${subs}</div>`;
    div.querySelector('[data-cat]').onclick=()=>{
      STATE.cat=c.name; STATE.sub=null; STATE.query=''; document.getElementById('search').value='';
      renderNav(); renderGrid();
    };
    div.querySelectorAll('[data-sub]').forEach(b=>b.onclick=e=>{
      e.stopPropagation();
      STATE.cat=c.name; STATE.sub=b.dataset.sub; STATE.query='';
      document.getElementById('search').value='';
      renderNav(); renderGrid();
    });
    nav.appendChild(div);
  }
  // reference manuals entry
  const ref=document.createElement('div');
  ref.className='cat';
  ref.innerHTML=`<button data-ref="1"><span>📖 Field Manual</span></button>`;
  ref.querySelector('button').onclick=()=>{STATE.cat='__manual';STATE.sub=null;renderNav();renderManual();};
  nav.appendChild(ref);
}

function filtered(){
  const q=STATE.query.trim().toLowerCase();
  return CATALOG.items.filter(it=>{
    if(q) return it.search.includes(q)||it.name.toLowerCase().includes(q);
    if(it.category!==STATE.cat) return false;
    if(STATE.sub && it.subcategory!==STATE.sub) return false;
    return true;
  });
}

function renderGrid(){
  const main=document.getElementById('main');
  const items=filtered();
  const where = STATE.query ? `Search “${STATE.query}”`
      : `<b>${STATE.cat}</b>${STATE.sub?' › '+STATE.sub:''}`;
  let html=`<div class="crumbs">${where}</div>
            <div class="count">${items.length} asset${items.length!==1?'s':''}</div>`;
  if(!items.length){ main.innerHTML=html+`<div class="empty">Nothing here.</div>`; return; }
  html+='<div class="grid">';
  for(const it of items){
    html+=`<div class="card${it.blank?' blank':''}" data-id="${it.id}">
      <div class="thumb">${it.blank?'':`<img loading="lazy" src="/media/${it.id}.png">`}</div>
      <div class="lbl" title="${it.name}">${it.name}</div>
    </div>`;
  }
  html+='</div>';
  main.innerHTML=html;
  main.querySelectorAll('.card').forEach(c=>c.onclick=()=>openAsset(c.dataset.id));
}

function renderManual(){
  const main=document.getElementById('main');
  const e=CATALOG.reference.enemies, w=CATALOG.reference.weapons;
  const erows=e.map(r=>`<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td>
     <td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td><td>${r[6]}</td></tr>`).join('');
  const wrows=w.map(r=>`<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td>
     <td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td></tr>`).join('');
  main.innerHTML=`<div class="crumbs"><b>Field Manual</b> · from the Technical &amp; Strategy Compendium</div>
    <div class="lore manual"><h3>Alien roster (16 CD-edition actors)</h3>
      <table><tr><th>Actor</th><th>Type</th><th>Health</th><th>Damage</th>
      <th>Levels</th><th>Score</th><th>Behavior / counterplay</th></tr>${erows}</table></div>
    <div class="lore manual"><h3>Weapons &amp; mines</h3>
      <table><tr><th>Key</th><th>Weapon</th><th>Consumption</th><th>Range</th>
      <th>Guide damage</th><th>Operational role</th></tr>${wrows}</table></div>`;
}

async function openAsset(id){
  const d=await (await fetch('/api/asset/'+id)).json();
  const modal=document.getElementById('modal');
  let rows='';
  for(const [k,v] of Object.entries(d.meta)){
    let val=v;
    if(Array.isArray(v)){
      if(!v.length) continue;
      val=v.map(x=>`<span class="chip">${x}</span>`).join('');
    } else if(v===''||v===null){ continue; }
    rows+=`<tr><td class="k">${k}</td><td>${val}</td></tr>`;
  }
  modal.innerHTML=`
    <div class="preview">
      <div class="stage"><img id="stageimg" src="/media/${d.id}.png"></div>
      <div class="zoomrow" style="width:280px">
        <span>zoom</span><input type="range" min="1" max="8" value="4" id="zoom">
      </div>
      <div style="color:var(--dim);font-size:12px">${d.w}×${d.h}px · ${d.category}</div>
    </div>
    <div class="details">
      <h2>${d.name}</h2>
      <div class="sub">${d.subcategory}</div>
      <table class="meta">${rows}</table>
    </div>`;
  const img=modal.querySelector('#stageimg');
  const base=Math.min(280/d.w,280/d.h);
  const zoom=modal.querySelector('#zoom');
  const apply=()=>{const s=base*zoom.value/4*d.w;img.style.width=Math.min(280,s*(280/(base*d.w)))+'px';};
  zoom.oninput=()=>{img.style.width=(d.w*zoom.value)+'px';img.style.height=(d.h*zoom.value)+'px';};
  document.getElementById('overlay').classList.add('show');
  document.getElementById('closebtn').style.display='block';
}
function closeModal(){document.getElementById('overlay').classList.remove('show');
  document.getElementById('closebtn').style.display='none';}
document.getElementById('closebtn').onclick=closeModal;
document.getElementById('overlay').onclick=e=>{if(e.target.id==='overlay')closeModal();};
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
document.getElementById('search').addEventListener('input',e=>{
  STATE.query=e.target.value; if(STATE.query){STATE.cat=null;STATE.sub=null;}
  renderGrid();
});
boot();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
