# EC7Edit — E1 evidence ledger

Milestone E1: the canonical native codec and minimal WAD export. Grades follow
[the E0 ledger](e0-evidence-ledger.md): **A** proven against running code or
the shipped data, **B** owned-data fact not distributable, **C** observed or
inferred without a runtime proof, **D** unresolved.

Frozen against `main` @ `d127be9`, tag `v1.0-beta173`. Reference runtime
CPython 3.12.13. Formats as implemented are documented in
[`native-formats.md`](native-formats.md).

---

## 1. The finding that mattered: the run threshold is four

A run of three identical words costs six bytes as an RLEW triple and six bytes
as three literals. The choice is free on size, so an encoder can go either way
and both are legal. The original TED5 encoder chose literals: **across all 180
planes of the shipped archive it never once emits a run shorter than four.**

| Threshold | Planes reproducing the retail bytes exactly |
| --- | --- |
| 3 | 74 / 180 |
| **4** | **180 / 180** |
| 5 | 77 / 180 |

At four, the whole 298 090-byte archive re-encodes byte for byte. Grade **A**,
measured on the owned CD; the measurement is repeated on every run of
`test_ec7edit_override.sh`.

This is the difference between an editor that rewrites a file and one that
rewrites a file *you can diff*. With threshold three every one of the sixty
maps comes out different, and an author who edited one map could not tell from
the bytes which one. It is also the sort of defect that passes every test you
would think to write: all 180 planes decode correctly at threshold three, and
the archive it produces loads and plays.

The reference codec outside the git root uses three, which is why it never
reproduced the original bytes and why nobody had noticed.

## 2. Fixtures that were malformed in ways they did not claim

E0 caught one of these (`oversize-dimensions` patching the name field). Running
the corpus through a second, stricter parser found two more:

| Fixture | Claimed | Actually was | Now |
| --- | --- | --- | --- |
| `truncated-plane.bin` | a plane cut short | the final `!ID!` cut to two bytes | truncated inside plane 2, header length untouched |
| `rlew-overrun.bin` | a run count past the plane | six bytes of tail replaced, corrupting the terminator | an overrunning run edited inside plane 0's stream |

Both were refused by both parsers, so both "passed" — for the wrong reason. A
fixture that fails for a reason other than the one it names is worth less than
no fixture, because it reports coverage that does not exist.

Three were added: `plane0-inside-header.bin` (only a *later* record can express
this fault, since the first record's plane-0 offset is implicit),
`plane-size-mismatch.bin`, and `trailing-garbage.bin`. The corpus is eleven,
and every one now fails with the diagnosis its name promises.

A fourth correction: `build_planes_lump` emitted the plane payload with no
WDC3.1 header, so `wad/one-map.wad` contained a `PLANES` lump the engine could
not have loaded. It now emits the full 34-byte header, restated from the engine
rather than imported, which is what makes it usable as an independent
cross-check.

## 3. Strictness gaps closed

All three gaps E0 recorded are closed, each against the engine's own rule:

| Gap | Engine rule | Test |
| --- | --- | --- |
| Empty archive accepted | `mapCount == 0` fails | `test_archive.Rejects.test_empty_file` |
| Marker-only archive accepted | same | `test_marker_only_file` |
| Later record's plane 0 not bounded below | `start < minimumPlaneOffset` fails | `test_later_plane_zero_inside_its_own_header` |

The tolerant paths are equally deliberate. A missing final `!ID!` loads with
`C7E-NATIVE-005` and a zero-count RLEW run decodes with `C7E-NATIVE-006`,
because the engine accepts both and an editor that refused them would reject
maps the game plays.

## 4. Losslessness

| Property | Grade | Evidence |
| --- | --- | --- |
| All three planes preserved | A | `test_archive.RoundTrip.test_all_three_planes_are_independent` |
| Plane 2 carried, never synthesised | A | `test_wad.PlanesRoundTrip.test_plane_two_is_carried_not_synthesised` |
| All 16 raw name bytes, including after the first NUL | A | `test_bytes_after_the_nul_survive_a_round_trip` |
| Preserved noncanonical name is information, not an error | A | `test_a_preserved_noncanonical_name_reports_007_not_004` |
| A rename replaces the whole field | A | `test_renaming_replaces_the_whole_field` |
| No unknown or reserved bytes remain | A | Both record layouts are fully accounted for; see `native-formats.md` §1 |

The shipped archive's noncanonical names are real: maps 47 to 50 each carry a
stray `0x31` after the terminator. Grade **B** — owned-data fact.

## 5. Independence of readers and writers

The plan asks that at least one test read with an implementation structurally
independent of the writer, so a shared misunderstanding cannot pass as a round
trip. Three independent implementations are in play:

1. `ec7edit_core` — the production codec;
2. `editor/scripts/make_fixtures.py` — the E0 generator, which imports none of
   it and deliberately keeps the threshold-3 encoding, so reading its archives
   tests the decoder rather than the writer's mirror image;
3. `independent_wad_reader` in `test_wad.py`, written from the byte layout.

And a fourth, which is the only one that counts for the exit gate: EC7Wolf
itself.

## 6. The engine loads what the exporter writes

`test_ec7edit_override.sh`, an owned-data gate. Three runs of the real binary:

| Run | Player spawns at |
| --- | --- |
| stock `MAP01` | tile 7, 31 |
| stock `MAP51` | tile 25, 37 |
| `MAP01` with a preview WAD holding MAP51's planes | **tile 25, 37** |

Positive entry evidence (the level was reached and the pawn spawned for the
full four traced tics) and positive content evidence (the geometry that spawned
it came from the WAD, not the archive). An override that silently did nothing
would land on 7, 31 and fail. Grade **A**.

The archive's SHA-256 is compared before and after every run of that gate and
is unchanged.

## 7. Source protection

`C7E-SOURCE-002` / `C7E-EXPORT-001` refuse an output that resolves to the
source or into a protected root. The alias cases are the point: a different
spelling, a symlink, a symlinked parent directory, and a **hard link**, which
no amount of string normalisation finds — that one needs the inode, and
`same_file` uses `os.path.samefile`. Every write is atomic and read back
(`C7E-EXPORT-002`), and the source digest is re-checked afterwards
(`C7E-SOURCE-001`).

Both lab tools previously guarded this with `if out.is_symlink()`, which
catches one of the five. They now go through the shared guard.

## 8. Test results

Under CPython 3.12.13, the reference runtime:

| Suite | Tests |
| --- | --- |
| `test_rlew` | 29 |
| `test_archive` | 38 |
| `test_wad` | 44 |
| `test_paths` | 23 |
| `test_cli` | 23 |
| `test_fixtures` (E0) | 9 |
| **total** | **166** |

Plus `test_ec7edit_e1.sh` (data-free: CLI end to end, export reproducibility,
source protection, Qt-free check, clean-clone check) and
`test_ec7edit_override.sh` (owned data: full re-encode, engine override).

Property tests are seeded (`random.Random(20260829)`) and bounded, so a failure
is reproducible rather than a story about one CI run.

## 9. Commercial content

Nothing retail is in the tree. Every fixture is generated, plane words come
from `0xE000` upward — a band the game's own data never uses — and the two
owned-data facts in this ledger (§1's threshold measurement and §4's stray
`0x31`) are stated as numbers, not shipped as bytes. The two gates that touch
the CD read it only, and prove it.

## 10. What E1 did not do

No GUI, no semantic catalogue, no asset decoders, no MAPINFO generation, no
project schema. `Archive`/`MapRecord` are the file's model, not the editor's
document model; E5 layers the document, undo and identity on top.

Two things deferred with reasons rather than forgotten:

- **Carmack compression** is unimplemented. Corridor 7's `MAPTEMP` is RLEW
  only (`carmacked` is false for any file named `maptemp.*`), so the editor
  does not need it, but a `GAMEMAPS` from another game would.
- **A `MAP100` archive** is representable and tested at the codec level, but
  no engine run has loaded one; the marker fits an eight-byte field by
  inspection of `mysnprintf`. Grade **C** until something loads it.
