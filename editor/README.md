# EC7Edit

A point-and-click level editor for Corridor 7, built alongside EC7Wolf.

The design and the milestone plan live in
[`docs/corridor7-level-editor.md`](../docs/corridor7-level-editor.md). This
directory holds the implementation as it arrives.

## State

**Milestone E6 — the complete semantic palette.** EC7Edit opens a Corridor 7
map, lets you change it, and plays what you changed. Paint walls from a palette
of real thumbnails, place doors and dispensers and pushwalls as single clicks,
pair a transporter in two, turn aliens to face where you want, copy and rotate
a whole region, undo anything, save, and press **F5** to watch EC7Wolf load
your edit.

```console
$ editor/ec7edit
```

First run asks for three paths — the engine, your game data, and somewhere to
keep projects — and answers with a checklist rather than a verdict.

The **Doors and Specials** tab holds compound tools rather than the raw words
behind them — one click writes every word a structure needs. Painting the raw
value instead would give you, for instance, a pushwall marker on open floor
with no wall to push.

Tools: select, paint, line, rectangle, fill, erase, pick, place, transporter
(`S B L R F E I P T`). **F8** checks the open map; **F5** exports it and
launches the engine on it — and refuses first if the map is one the engine
would reject, rather than starting a game that closes again immediately.
Right-click a map in the list to rename, reslot, duplicate, test or delete it;
all of those undo. Your archive is only ever read.

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
| [`ec7edit`](ec7edit) | Run it from a checkout, without installing |
| [`ec7edit_core/`](ec7edit_core/) | The Qt-free half: codecs, catalogue, document, path safety, CLI. The GUI depends on this; it never depends on the GUI |
| [`ec7edit_gui/`](ec7edit_gui/) | The Qt layer: window, canvas, palette, first-run setup, background workers |
| [`docs/native-formats.md`](docs/native-formats.md) | The byte layouts as implemented, checked against the engine that loads them |
| [`docs/e0-evidence-ledger.md`](docs/e0-evidence-ledger.md) | E0: contracts traced to source, with grades |
| [`docs/e1-evidence-ledger.md`](docs/e1-evidence-ledger.md) | E1: what the codec proved, and what it found |
| [`docs/e2-evidence-ledger.md`](docs/e2-evidence-ledger.md) | E2: decoder equivalence, and three things the catalogue found in the data |
| [`docs/e3-evidence-ledger.md`](docs/e3-evidence-ledger.md) | E3: the modelled 10 000 operations, the eleven injected save failures, and two defects they found |
| [`docs/e4-evidence-ledger.md`](docs/e4-evidence-ledger.md) | E4: the measured packaging decision, and why the engine is not run until you ask |
| [`docs/e5-evidence-ledger.md`](docs/e5-evidence-ledger.md) | E5: the exit gate met end to end, and the drag bug that would have made painting unusable |
| [`docs/e6-evidence-ledger.md`](docs/e6-evidence-ledger.md) | E6: nineteen compound tools, the door rule copied from the engine, and the six gaps coverage found |
| [`scripts/make_fixtures.py`](scripts/make_fixtures.py) | Generates the synthetic corpus, including eleven malformed inputs |
| [`scripts/audit_links.py`](scripts/audit_links.py) | Fails on a Markdown link that escapes the git root or points at an untracked file |
| [`resources/editor_catalog.json`](resources/) | The generated catalogue: 457 entries joining raw map words to names, sprites and placement rules |
| [`scripts/generate_catalog.py`](scripts/generate_catalog.py) | Rebuilds it from the engine's translation and actors; `verify` is a gate |
| [`scripts/build_c7assets.py`](scripts/build_c7assets.py) | Builds `tools/c7assets.py` by inlining the decoders, so there is only one copy of them |
| [`tests/unit/`](tests/unit/) | 488 tests, plain `unittest`, no runner dependency |
| [`tests/gui/`](tests/gui/) | 122 more, real Qt widgets on the offscreen platform |

Run it all with `tools/run_gates.sh ec7edit_e0 ec7edit_e1 ec7edit_e2 ec7edit_e3
ec7edit_e4 ec7edit_e5 ec7edit_e6`, or add `ec7edit_override ec7edit_assets ec7edit_slice`
where the game data is present — the last of those edits a real map and watches
the engine load it.

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

The GUI needs PySide6. Set up the local runtime once:

```console
$ uv venv --python 3.12 editor/.venv
$ uv pip install --python editor/.venv/bin/python PySide6
```

The GUI gate finds that venv on its own and skips cleanly when there isn't
one, so the codec gates still run on a machine with no Qt.

The core has no third-party dependencies at all — everything it needs to read
and write these formats is in the standard library, which is what lets the
codec tests run on a CI machine with no display and no right to the game data.
PySide6 arrives with the GUI, as an optional extra.

## Next

E7 makes validation continuous — reachability, key-and-door routes, and the
problems panel updating as you draw rather than when you ask.
