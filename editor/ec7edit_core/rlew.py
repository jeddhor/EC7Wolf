# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
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

from __future__ import annotations

import struct

from .errors import DiagnosticLog, native_error

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
