#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E1: the RLEW codec, against the engine's acceptance rules.

The decoder's contract is not "sensible streams work" but "exactly what
`ValidateTed5RLEW` accepts is accepted", so most of this file is about the
edges: truncation, overrun, trailing bytes, the tag as a literal, and the
zero-count run that the engine tolerates and the writer must never emit.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ec7edit_core.errors import DiagnosticLog, NativeFormatError
from ec7edit_core.rlew import (
    MAX_EXPANDED_BYTES,
    RLEW_TAG,
    RUN_THRESHOLD,
    decode_plane,
    encode_plane,
)


def stream(*tokens: int) -> bytes:
    """Assemble a raw word stream after its expanded-size prefix."""
    return struct.pack(f"<{len(tokens)}H", *tokens)


def framed(expanded_words: int, *tokens: int) -> bytes:
    return struct.pack("<H", expanded_words * 2) + stream(*tokens)


class RoundTrip(unittest.TestCase):
    def check(self, words):
        encoded = encode_plane(tuple(words))
        self.assertEqual(decode_plane(encoded, len(words)), tuple(words))
        return encoded

    def test_literals(self):
        self.check([1, 2, 3, 4, 5])

    def test_single_word(self):
        self.check([7])

    def test_one_long_run(self):
        self.check([9] * 1000)

    def test_alternating(self):
        self.check([1, 2] * 200)

    def test_all_zero(self):
        self.check([0] * 64)

    def test_boundary_values(self):
        self.check([0x0000, 0xFFFF, 0x0001, 0xFFFE, 0x8000])

    def test_encoding_is_deterministic(self):
        words = tuple((index * 7) % 11 for index in range(500))
        self.assertEqual(encode_plane(words), encode_plane(words))


class TagHandling(unittest.TestCase):
    def test_lone_tag_literal_uses_the_triple(self):
        encoded = encode_plane((RLEW_TAG,))
        self.assertEqual(encoded, framed(1, RLEW_TAG, 1, RLEW_TAG))
        self.assertEqual(decode_plane(encoded, 1), (RLEW_TAG,))

    def test_tag_among_literals_survives(self):
        words = (1, RLEW_TAG, 2, RLEW_TAG, RLEW_TAG, 3)
        self.assertEqual(decode_plane(encode_plane(words), len(words)), words)

    def test_a_tag_run_is_one_triple(self):
        encoded = encode_plane((RLEW_TAG,) * 2)
        self.assertEqual(encoded, framed(2, RLEW_TAG, 2, RLEW_TAG))


class RunThreshold(unittest.TestCase):
    """The threshold is measured from the shipped archive, so pin it."""

    def test_below_the_threshold_stays_literal(self):
        words = (5,) * (RUN_THRESHOLD - 1)
        self.assertEqual(encode_plane(words), framed(len(words), *words))

    def test_at_the_threshold_becomes_a_run(self):
        words = (5,) * RUN_THRESHOLD
        self.assertEqual(encode_plane(words), framed(len(words), RLEW_TAG, RUN_THRESHOLD, 5))

    def test_three_is_the_free_choice_the_original_spent_on_literals(self):
        # Three literals and one run are both six bytes. The original encoder
        # chose literals; matching it is what makes a re-encode byte-exact.
        self.assertEqual(RUN_THRESHOLD, 4)
        self.assertEqual(len(encode_plane((5, 5, 5))), 2 + 6)
        self.assertEqual(encode_plane((5, 5, 5)), framed(3, 5, 5, 5))


class DecoderRejects(unittest.TestCase):
    def assertRefused(self, data, words, fragment=""):
        with self.assertRaises(NativeFormatError) as caught:
            decode_plane(data, words)
        self.assertEqual(caught.exception.diagnostic.code, "C7E-NATIVE-002")
        if fragment:
            self.assertIn(fragment, str(caught.exception))

    def test_empty(self):
        self.assertRefused(b"", 4)

    def test_prefix_only(self):
        self.assertRefused(struct.pack("<H", 8), 4)

    def test_odd_length(self):
        self.assertRefused(framed(2, 1, 2) + b"\x00", 2)

    def test_declared_size_disagrees_with_the_header(self):
        self.assertRefused(framed(3, 1, 2, 3), 4, "header requires 8")

    def test_truncated_before_the_last_word(self):
        self.assertRefused(framed(4, 1, 2, 3), 4)

    def test_truncated_tag_triple(self):
        self.assertRefused(framed(8, RLEW_TAG, 4), 8, "truncated run")

    def test_run_overruns_the_plane(self):
        self.assertRefused(framed(4, RLEW_TAG, 0xFFFF, 7), 4, "overruns")

    def test_trailing_bytes_after_completion(self):
        self.assertRefused(framed(2, 1, 2), 1, "header requires 2")
        self.assertRefused(framed(1, 1, 2), 1, "trailing")

    def test_plane_too_large_for_the_size_field(self):
        with self.assertRaises(NativeFormatError):
            decode_plane(framed(1, 1), MAX_EXPANDED_BYTES // 2 + 1)


class NoncanonicalButLegal(unittest.TestCase):
    """What the engine accepts, this decoder accepts -- loudly, not silently."""

    def test_zero_count_run_is_accepted_and_reported(self):
        data = framed(1, RLEW_TAG, 0, 9, 4)
        log = DiagnosticLog()
        self.assertEqual(decode_plane(data, 1, log=log), (4,))
        self.assertEqual(log.codes(), ["C7E-NATIVE-006"])

    def test_the_writer_never_emits_a_zero_count_run(self):
        for words in ([0] * 64, [1, 2, 3], [RLEW_TAG] * 5, list(range(100))):
            encoded = encode_plane(tuple(words))
            cursor = 2
            while cursor < len(encoded):
                value = struct.unpack_from("<H", encoded, cursor)[0]
                if value == RLEW_TAG:
                    count = struct.unpack_from("<H", encoded, cursor + 2)[0]
                    self.assertGreater(count, 0)
                    cursor += 6
                else:
                    cursor += 2

    def test_a_run_of_three_decodes_even_though_we_would_not_write_one(self):
        # Exactly what the E0 fixture generator produces. A decoder that only
        # understood its own encoder's output would be useless on real files.
        self.assertEqual(decode_plane(framed(3, RLEW_TAG, 3, 8), 3), (8, 8, 8))


class EncoderRejects(unittest.TestCase):
    def test_word_outside_uint16(self):
        for bad in (-1, 0x10000):
            with self.assertRaises(NativeFormatError) as caught:
                encode_plane((1, bad, 2))
            self.assertEqual(caught.exception.diagnostic.code, "C7E-CELL-001")

    def test_plane_too_large_for_the_size_field(self):
        with self.assertRaises(NativeFormatError) as caught:
            encode_plane((0,) * (MAX_EXPANDED_BYTES // 2 + 1))
        self.assertEqual(caught.exception.diagnostic.code, "C7E-NATIVE-003")

    def test_incompressible_plane_overflows_the_length_field(self):
        # Alternating tag literals cost six bytes each, so a plane well inside
        # the expanded limit can still be unencodable. Refuse, never truncate.
        # Each tag literal costs six bytes and each ordinary literal two, so
        # alternating them runs four bytes per word: 20000 words expand to a
        # legal 40000 bytes but encode to 80002, past the length field.
        words = tuple(RLEW_TAG if index % 2 else index for index in range(20000))
        with self.assertRaises(NativeFormatError) as caught:
            encode_plane(words)
        self.assertEqual(caught.exception.diagnostic.code, "C7E-NATIVE-003")


class Property(unittest.TestCase):
    """Deterministically seeded, bounded, and reproducible on any machine."""

    def test_round_trip_over_a_seeded_corpus(self):
        import random

        generator = random.Random(20260829)
        for case in range(200):
            length = generator.randint(1, 400)
            alphabet = [0, 1, 2, RLEW_TAG, 0xFFFF, generator.randint(0, 0xFFFF)]
            words = tuple(generator.choice(alphabet) for _ in range(length))
            with self.subTest(case=case, length=length):
                self.assertEqual(decode_plane(encode_plane(words), length), words)


if __name__ == "__main__":
    unittest.main(verbosity=1)
