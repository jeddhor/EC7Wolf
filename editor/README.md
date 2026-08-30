# EC7Edit

A point-and-click level editor for Corridor 7, built alongside EC7Wolf.

The design and the milestone plan live in
[`docs/corridor7-level-editor.md`](../docs/corridor7-level-editor.md). This
directory holds the implementation as it arrives.

## State

**Milestone E0 — evidence freeze and synthetic fixtures.** No editor yet: E0
exists to make the ground firm before anything is built on it. What is here:

| Path | What it is |
| --- | --- |
| [`docs/e0-evidence-ledger.md`](docs/e0-evidence-ledger.md) | Every native contract traced to source, with grades, plus the strictness gaps and the open provenance question |
| [`scripts/make_fixtures.py`](scripts/make_fixtures.py) | Generates the synthetic corpus: archives, PLANES, a WAD, an indexed image, a project file, and eight malformed inputs |
| [`scripts/audit_links.py`](scripts/audit_links.py) | Fails on a Markdown link that escapes the git root, does not exist, or points at an untracked file |
| [`tests/unit/test_fixtures.py`](tests/unit/test_fixtures.py) | The fixtures are reproducible, synthetic, and well-formed |

Run it all with `tools/run_gates.sh ec7edit`.

## Why there are no fixture files in the repository

Corridor 7 is commercial software this project has no right to redistribute, so
no test may contain retail bytes. The fixtures are therefore *generated*, never
stored, and their plane words are drawn from `0xE000` upward — a band the game's
own data never uses, so a retail word could not be mistaken for one of ours.
`make_fixtures.py verify` regenerates and compares, which means a fixture edited
by hand, or quietly replaced with real data, stops the gate rather than passing
it.

The generator is deterministic: no randomness, seeded or otherwise, so the same
call produces the same bytes on every platform and a digest is a contract rather
than one machine's luck.

## Next

E1 implements the production codec from the contracts in the ledger. Note the
open question recorded there: the reference codec this project has been using
lives *outside* the git root and carries no licence, author or copyright, and
two tracked tools already import it — so a clean clone cannot run them. Until
its provenance is settled it is behavioural evidence only, and E1 writes an
independent implementation.
