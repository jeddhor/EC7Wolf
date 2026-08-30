# EC7Edit

A point-and-click level editor for Corridor 7, built alongside EC7Wolf.

The design and the milestone plan live in
[`docs/corridor7-level-editor.md`](../docs/corridor7-level-editor.md). This
directory holds the implementation as it arrives.

## State

**Milestone E3 — the document model.** There is no GUI yet, but everything a
GUI needs is here and driveable from a shell: read and write Corridor 7's map
archive, decode the artwork, know that plane-1 word 108 is an Alioprobe facing
east, hold a project with undo and redo, save it so that a crash mid-write
loses nothing, and export a map the running game loads in place of a stock
one.

Shown against a generated archive rather than a retail one, since the map
names in the shipped file are not this project's to publish:

```console
$ ec7edit inspect synthetic.c7map
synthetic.c7map: 3 maps, TED5 self-contained
  MAP01    8x8    SYNTH01
  MAP02   16x16   SYNTH02
  MAP03   64x64   SYNTH03

$ ec7edit convert-to-preview-wad synthetic.c7map --map 3 --slot MAP01 \
      --output ~/work/preview.wad
~/work/preview.wad: 1 map(s), 24654 bytes, sha256 af0c449d542dc351
  MAP01  <- map 3 'SYNTH03' 64x64 x3 planes
  source /…/synthetic.c7map unchanged (f750b87e568aa290)

$ ec7wolf --data CO7 --tedlevel MAP01 --file ~/work/preview.wad
```

Projects work end to end too — import a map, edit it, save, export:

```console
$ ec7edit project-import synthetic.c7map --project ~/work/demo.ec7project --map 2
$ ec7edit project-inspect ~/work/demo.ec7project
$ ec7edit project-export  ~/work/demo.ec7project --output ~/work/preview.wad
```

There is also `ec7edit validate`, which reports what is noncanonical about an
archive without refusing to open it.

## Layout

| Path | What it is |
| --- | --- |
| [`ec7edit_core/`](ec7edit_core/) | The Qt-free half: codecs, path safety, CLI. The GUI will depend on this; it will never depend on the GUI |
| [`docs/native-formats.md`](docs/native-formats.md) | The byte layouts as implemented, checked against the engine that loads them |
| [`docs/e0-evidence-ledger.md`](docs/e0-evidence-ledger.md) | E0: contracts traced to source, with grades |
| [`docs/e1-evidence-ledger.md`](docs/e1-evidence-ledger.md) | E1: what the codec proved, and what it found |
| [`docs/e2-evidence-ledger.md`](docs/e2-evidence-ledger.md) | E2: decoder equivalence, and three things the catalogue found in the data |
| [`docs/e3-evidence-ledger.md`](docs/e3-evidence-ledger.md) | E3: the modelled 10 000 operations, the eleven injected save failures, and two defects they found |
| [`scripts/make_fixtures.py`](scripts/make_fixtures.py) | Generates the synthetic corpus, including eleven malformed inputs |
| [`scripts/audit_links.py`](scripts/audit_links.py) | Fails on a Markdown link that escapes the git root or points at an untracked file |
| [`resources/editor_catalog.json`](resources/) | The generated catalogue: 457 entries joining raw map words to names, sprites and placement rules |
| [`scripts/generate_catalog.py`](scripts/generate_catalog.py) | Rebuilds it from the engine's translation and actors; `verify` is a gate |
| [`scripts/build_c7assets.py`](scripts/build_c7assets.py) | Builds `tools/c7assets.py` by inlining the decoders, so there is only one copy of them |
| [`tests/unit/`](tests/unit/) | 382 tests, plain `unittest`, no runner dependency |

Run it all with `tools/run_gates.sh ec7edit_e0 ec7edit_e1 ec7edit_e2 ec7edit_e3`,
or add `ec7edit_override ec7edit_assets` where the game data is present.

## Two things worth knowing

**The run threshold is four.** A run of three identical words costs six bytes
whether you spell it as a run or as three literals, so an encoder may choose
either. The original chose literals, and matching that is what makes a
re-encoded archive byte-identical to the one that shipped — all 60 maps,
298 090 bytes. At three, every map comes out different and an author cannot
tell from a diff which one they edited. See the
[E1 ledger](docs/e1-evidence-ledger.md) §1.

**Fixtures are generated, never stored.** Corridor 7 is commercial software
this project has no right to redistribute, so no test may contain retail bytes.
Plane words are drawn from `0xE000` upward, a band the game's own data never
uses, and `make_fixtures.py verify` regenerates and compares, so a fixture
edited by hand or quietly replaced with real data stops the gate rather than
passing it. The generator is deterministic — no randomness, seeded or
otherwise — which is what makes a digest a contract instead of one machine's
luck.

## Runtime

CPython **3.12** is the reference; 3.10 is the floor, matching the repository's
other tools. If your system Python is newer, the gate finds a 3.12 through
`uv python install 3.12` and says which interpreter it actually used.

The core has no third-party dependencies at all — everything it needs to read
and write these formats is in the standard library, which is what lets the
codec tests run on a CI machine with no display and no right to the game data.
PySide6 arrives with the GUI, as an optional extra.

## Next

E4 puts a Qt shell around it — the window, the first-run discovery of your game
data, and the project browser — and E5 makes the canvas editable.
