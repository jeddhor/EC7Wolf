# EC7Edit — E0 evidence ledger

Milestone E0 of [`docs/corridor7-level-editor.md`](../../docs/corridor7-level-editor.md).

Every contract the editor will implement, traced to something a reviewer can
open. Grades are the plan's: **A** current source or a passing test, **B** a
repository tool agreeing with a read-only census of legally owned data, **C**
observed or inferred without a runtime proof, **D** proposal or unresolved.

Frozen against:

| | |
| --- | --- |
| Branch / commit | `main` @ `2db27b4` |
| Nearest tag | `v1.0-beta173` |
| Working tree | clean but for untracked planning documents |

Line numbers are navigation aids and go stale; symbol names are the contract.

---

## 1. Native archive contracts

| # | Contract | Grade | Source | Note |
| --- | --- | --- | --- | --- |
| A1 | Archive holds 1–100 maps | A | `MAX_TED5_MAPS` in [`file_gamemaps.cpp`](../../src/resourcefiles/file_gamemaps.cpp) | The loader refuses the 101st and says so |
| A2 | Width and height each ≤ 181 | A | `MAX_MAP_DIMENSION`, same file | Checked before any plane is read |
| A3 | Signature `TED5v1.0.\0\0\0`, 12 bytes | A | same file; fixture `archive/one-map.c7map` | |
| A4 | Later records begin `!ID!` | A | same file | |
| A5 | First record is 46 bytes, later records 42 | A | fixture generator, read back by the out-of-root parser | See §3 for the provenance of that parser |
| A6 | **The first record stores only planes 1 and 2's offsets**; plane 0 begins immediately after the 46-byte header | A | `parse_header` in the out-of-root codec; confirmed by round-trip | Cost one wrong assumption while writing the fixtures: a naive reading gives a 50-byte header |
| A7 | Each header is followed immediately by its own three plane streams | A | round-trip of `archive/three-maps.c7map` | Not "all headers, then all planes" |
| A8 | RLEW tag `0xABCD`; `tag,count,value` triples; a literal equal to the tag must use the triple form | A | `wolfmapcommon.cpp`; fixture `malformed/rlew-overrun.bin` | |
| A9 | Each plane stream begins with a little-endian expanded **byte** count | A | fixture round-trip | Bytes, not words |
| A10 | Name field is exactly 16 bytes | A | fixture round-trip | Display stops at the first NUL; the raw 16 must be kept |
| A11 | Archive ends with a bare `!ID!` | C | plan §4.2; fixture `archive/no-final-marker.c7map` exists to test the tolerant path | Plan says accept-with-warning on import, always emit on write |

## 2. Strictness gaps found by the synthetic corpus

The malformed fixtures were run through the existing out-of-root parser. Six
of eight are refused. The two accepted are recorded here rather than fixed,
because E0 does not move production code:

| Input | Existing parser | Required of the E1 codec |
| --- | --- | --- |
| `malformed/empty.bin` | **accepted** | reject |
| `malformed/marker-only.bin` | **accepted** | reject |
| `malformed/bad-signature.bin` | refused | reject |
| `malformed/truncated-signature.bin` | refused | reject |
| `malformed/oversize-dimensions.bin` | refused | reject |
| `malformed/plane-offset-in-header.bin` | refused | reject |
| `malformed/truncated-plane.bin` | refused | reject |
| `malformed/rlew-overrun.bin` | refused | reject |

Both accepted cases were predicted by plan §4.2. That the prediction survived
contact with a generated corpus is the useful part.

**E1 outcome:** all of them are refused by `ec7edit_core`, and the corpus grew
to eleven. E1 also found that two of the eight above were malformed in ways
they did not claim — see the E1 ledger, §2. The count in the first line of this
section was wrong when written (six, not seven); corrected 2026-08-29.

One correction belongs here too, because it is the kind of mistake this ledger
exists to catch. The `oversize-dimensions` fixture originally patched offset 30,
which is the *name* field; the parser accepted it and looked wrong. Width and
height are at offset 26 in the first record. The fixture was malformed in a way
it did not claim, and a fixture that lies about what it tests is worse than no
fixture.

## 3. Provenance: the codec outside the git root

| | |
| --- | --- |
| Path | `../../tools/python/corridor7_map.py` — **outside the ECWolf git root** |
| Version control | none: the containing directory is not a git repository |
| Licence / copyright / author | **absent** — no SPDX tag, no header, no attribution anywhere in the file |
| Grade | C — it works, and nothing states where it came from |

**It is already a dependency.** Two *tracked* tools import it:

- `tools/make_corridor7_ai_lab.py`
- `tools/make_corridor7_mp_lab.py`

both via `sys.path.insert(0, parents[2] / "tools" / "python")`. From a clean
clone of ECWolf neither runs, because the module they import was never in the
repository. This is a live defect, not a hypothetical: the second of those two
tools was written during the multiplayer work and copied the idiom from the
first without noticing what it implied.

**Resolved, 2026-08-29.** The owner confirms the file is his own work and that
everything in this project carries one licence: *"Everything is under the same
license -- the map editor will be the same license as EC7Wolf."* The editor is
therefore **GPL-3.0-or-later**, matching the engine's effective licence, and
every new file carries an SPDX tag saying so. Reuse is authorised.

What E1 did with that permission is worth recording, because "authorised" and
"correct to reuse" are different questions. The reference codec is sound on
structure and was used as behavioural evidence throughout, but it is lossy in
two ways the editor cannot afford:

- it decodes a name to the text before the first NUL and re-encodes from that,
  destroying the trailing bytes — which the shipped archive really does carry,
  in maps 47 to 50;
- its RLEW run threshold is three, so it never reproduces the original
  encoder's bytes (74 of 180 planes by luck; see §7).

So E1 wrote `ec7edit_core` fresh against the engine's own loader rather than
adapting the reference. The out-of-root dependency is gone either way: both lab
tools now import the in-repository package, and the E1 gate checks that no
`tools/python` path escape comes back.

Grade **A**: licence stated by the owner, reuse authorised, and the production
code independent of the question.

## 4. Runtime and platform matrix

Measured on the development machine, not assumed:

| | Frozen | Observed here |
| --- | --- | --- |
| Editor version | `EC7Edit 0.1.0` | — |
| Core language floor | Python 3.10 (matches the repository tools) | — |
| Reference runtime | **CPython 3.12** (owner's decision, 2026-08-29) | 3.12.13, via `uv python install 3.12` |
| System interpreter here | — | Python 3.14.4 |
| Qt / PySide6 | PySide6 6.x | PySide6 6.10.2, Qt 6.10.2 |
| Acceptance targets | Windows 11 x64; Ubuntu 24.04 x64 and arm64 | Linux x64 |

**Resolved (A), 2026-08-29.** The owner chose 3.12 and gave the reason: *"more
people are going to have it."* The development machine has only 3.14.4, so the
reference is supplied by `uv python install 3.12`, which fetches a standalone
CPython build — no container, no system package, and the same mechanism works
on a CI runner. `test_ec7edit_e1.sh` prefers a `python3.12` on `PATH`, falls
back to `uv python find 3.12`, and prints which interpreter it used, so a run
on the wrong one is visible rather than assumed.

The floor stays 3.10 to match the repository's other tools. The tested range is
therefore **3.10 floor, 3.12 reference, 3.14.4 also exercised** — the last
because it is what this machine runs by default, not because it is supported.

## 5. Commercial-content boundary

| Rule | How it is enforced |
| --- | --- |
| No retail bytes in the repository | Fixtures are computed by `editor/scripts/make_fixtures.py`; plane words come from `0xE000`+, a band the game's own data never uses |
| Fixtures are provably synthetic | `make_fixtures.py verify` regenerates and compares; a hand-edited or substituted fixture fails the gate |
| Determinism | No randomness, seeded or otherwise; identical bytes on every platform |
| Links stay inside the repository | `editor/scripts/audit_links.py` fails on a link that escapes the git root, does not exist, or points at an untracked file |

## 6. Owned-data facts (grade B, not distributable)

From a read-only census of a legally owned CD, recorded as fact and not as a
fixture: 60 maps, all 64×64; MAP01–40 campaign, MAP41–46 bonus, MAP47–50 unused
or empty, MAP51–60 network. Four headers carry nonzero bytes after the first NUL
in the name field, which is why A10 keeps the raw 16 bytes.

## 7. What E0 deliberately did not do

No production GUI, no codec, no parser rewrite, no engine change, no catalogue.
No production code was moved. The two strictness gaps in §2 are recorded, not
fixed; they belong to E1.
