# EC7Wolf Corridor 7 Level Editor — Master Design Guide and AI Agent Development Plan

**Status:** design and implementation plan; no production level editor exists
yet

**Scope:** a simple, point-and-click desktop level editor for Corridor 7:
Alien Invasion and EC7Wolf, including lossless native-level import, visual wall
painting, object and enemy placement, validation, safe export, one-click
playtesting in EC7Wolf, and a deliberately bounded 3D-preview path

**Working product name:** EC7Edit. The name is provisional; changing it does
not change this plan.

**Source snapshot reviewed:** EC7Wolf `main` at
`c7b34abcfe2613d068e1729fdefd59f9791615cc`, 29 August 2026. The source audit
and citations were rechecked against the committed tree at that hash. This
document and its README index entry are planning changes, not editor
implementation. Every implementation milestone must re-read the current source
rather than trusting line numbers in this document indefinitely.

**Lineage:** EC7Wolf is based on ECWolf 1.4.2-9-g1bff92d (18 February 2026),
on upstream's 1.5.0pre line. EC7Wolf's own version remains `1.0-betaX`; this
plan does not promote it or alter its save-product version fields.

**Commercial-data rule:** the editor, its source, tests, public packages, and
documentation contain no Corridor 7 retail maps, executable bytes, artwork,
palette, sound, or music. A user's legally owned data is read locally. Imported
maps, converted maps, thumbnails, screenshots, caches, and other decoded retail
content remain local commercial-derived material and are never committed or
redistributed.

This document is deliberately exhaustive. It is both the product design and
the engineering execution contract. It defines what a beginner should be able
to do, records what the current engine and data formats actually support,
chooses an architecture, specifies safe import/export and test behavior, and
breaks the implementation into evidence-gated milestones suitable for AI
coding agents or human developers.

The feasibility verdict is **yes**. Corridor 7's authored levels are fixed
grids with three 16-bit planes, and the repository already contains strict map
parsing and encoding, graphics decoders, semantic translation tables,
campaign validation, and engine launch/capture infrastructure. A polished 2D
editor is a bounded desktop application, not an engine rewrite.

The central product rule is:

> Raw map data is preserved losslessly, but ordinary users edit meanings:
> paint this wall, place this enemy, add this door, connect this transporter,
> and test this map.

The central scope rule for 3D is:

> The running EC7Wolf game is authoritative. The editor may show an exact
> engine-rendered snapshot and may later gain a clearly labeled approximate
> layout view, but it must not fork or impersonate EC7Wolf's gameplay renderer.

For review, the document is organized as follows:

- Sections 1–4 define the decisions, people, workflows, completion contract,
  and evidence-backed current-state audit.
- Sections 5–18 define legal boundaries, architecture, data model, asset
  catalog, user interface, editing semantics, validation, import, export,
  playtesting, 3D preview, reliability, security, and platform behavior.
- Sections 19–24 define testing, packaging, the milestone program, concrete
  source work, AI-agent operating rules, risks, and stop-the-line conditions.
- Sections 25–27 and the appendices give the final acceptance checklist,
  open decisions, references, schemas, shortcuts, diagnostics, and invariants.

---

## 1. Executive decisions

These are the decisions around which the plan is written. Changing one is a
design change and requires updating the relevant tests and this document.

1. **Ship a standalone desktop editor.** EC7Edit is a separate process. It
   neither embeds an editor in the game loop nor requires the game to be
   running while a map is edited.

2. **Use a Python 3.10-compatible core and a PySide6/Qt Widgets GUI.** The
   reference/frozen GUI runtime is Python 3.12, while the Qt-free core retains
   the repository tools' documented Python 3.10+ compatibility. E0 freezes the
   tested upper Python bound and Qt/PySide versions for each release target.
   Qt supplies native dialogs, docking, models, process control,
   accessibility, high-DPI behavior, and offscreen tests.

3. **Keep the production core completely Qt-free.** Parsing, encoding,
   project I/O, commands, catalog logic, validation, export, and launch-plan
   construction must be usable from unit tests and a command-line tool without
   importing PySide6.

4. **Make the GUI a thin adapter.** Widgets display core state and submit
   commands. They do not privately mutate map arrays, invent validation rules,
   write archives, or assemble shell commands.

5. **Make the raw three-plane map the source of truth.** Semantic layers are
   views over exact unsigned 16-bit values. Unknown imported values and the
   incompletely understood third plane are never discarded or normalized.

6. **Expose semantics, not raw arithmetic, by default.** A user chooses
   “Red access door,” “Alien Drone facing east, Captain+,” or “Transporter
   channel A.” The core translates that choice to native plane words.

7. **Make the primary loop genuinely point-and-click.** Choose a wall
   thumbnail and drag to paint. Choose an object or enemy and click to place.
   Click an existing element to inspect it. Keyboard shortcuts accelerate the
   workflow but are never required for ordinary editing.

8. **Use one custom-painted 2D canvas.** Do not create a widget per tile. A
   scrollable `QPainter` canvas provides predictable hit testing, zoom,
   overlays, large-map performance, and pixel-sharp rendering.

9. **Fix new maps at 64×64 for the first release.** Every shipped Corridor 7
   map is 64×64, and this is the best understood target. The codec remains
   capable of importing other legal dimensions. Arbitrary resize creation is
   enabled only after explicit engine tests.

10. **Open retail archives read-only by default.** Import never writes to the
    user's installed `MAPTEMP.CO7`. Work lives in a separate editor project;
    export goes to a new file.

11. **Never make the commercial data directory a workspace.** Projects,
    thumbnails, autosaves, playtest config, playtest saves, logs, and preview
    exports live elsewhere. This also prevents private packaging scripts from
    accidentally copying editor detritus.

12. **Support all three useful persistence forms.** The editor has a versioned
    project format for ongoing work, a small one-map WAD for normal test/share
    export, and an explicit private full-archive `MAPTEMP.CO7` export for a
    user's own complete archive workflow.

13. **Use a `MAPxx` marker plus uncompressed `PLANES` lump for normal export.**
    EC7Wolf already consumes this WDC3.1 representation. It is smaller and
    safer than copying a 60-map commercial archive and is more faithful than
    inventing a UWMF conversion.

14. **Keep full-archive export private and exceptional.** It is labeled
    “Export complete private archive,” never the default Test Map output, and
    never overwrites the source without a separate, explicit, backed-up
    advanced workflow.

15. **Use atomic saves and recoverable autosaves.** Every project or export is
    fully written and validated in a sibling temporary location before
    replacement. A crash must leave either the old valid file or the new valid
    file, not half of either.

16. **Treat one drag as one undo operation.** Commands record exact before and
    after values across all affected planes. Compound tools, fills, pastes,
    and prefabs are atomic from the user's perspective.

17. **Make special structures dedicated tools.** Doors, moving walls, masked
    walls, animated walls, elevators, transporters, exits, and health chambers
    are not ordinary texture swatches. Their tools update every required plane
    together and explain invalid topology before committing.

18. **Validate continuously and preflight strictly.** The Problems pane shows
    clickable errors and warnings while editing. Export is blocked only by
    conditions that cannot form a valid/safe map; suspicious but legal design
    choices remain overridable warnings.

19. **Preserve imported unknowns.** An unknown raw word is a visible warning,
    not permission to replace it. An unchanged imported map must remain
    semantically identical after project save/reopen and export.

20. **Launch EC7Wolf through an argument vector, never a shell.** Set the
    process working directory to the selected game-data directory, pass
    absolute paths, isolate config and saves, and capture stdout/stderr in a
    Test Log pane.

21. **Use `--file` overrides for playtesting.** A generated preview WAD loads
    after the commercial base resources and overrides only the selected
    `MAPxx`. Testing never modifies or stages over the installed archive.

22. **Treat `--data CO7` as a data-set extension selector.** It is not a path.
    The selected data directory is supplied as the child process's current
    working directory.

23. **Ship exact external playtesting in the first usable release.** The Test
    Map button enters the selected edited map in the actual engine. This is the
    authoritative interactive 3D preview.

24. **Attempt an exact software-rendered 3D Snapshot dock after the 2D vertical
    slice, but gate it.** EC7Wolf's capture harness can render a chosen tile
    and angle to a PNG when the live renderer is explicitly software. It ships
    only if a small, separately tested engine command-line seam makes capture
    readiness/tic, exit, and hidden behavior stable; otherwise E10 records the
    deferral and Test Map remains the exact 3D path. OpenGL capture is a later
    renderer-specific extension, not assumed to use the same framebuffer or
    file format.

25. **Gate any interactive in-editor 3D renderer.** A later approximate
    raycaster is acceptable only as a clearly labeled layout aid, only after a
    time-boxed spike, and only if it does not delay 2D editing, import/export,
    validation, or Test Map. Embedding EC7Wolf's renderer is a separate engine
    architecture project and is not planned here.

26. **Do not use EC7Wolf savegames as projects.** Savegames serialize live
    runtime state, depend on the loaded geometry, and can become invalid after
    edits. Playtest saves are isolated and associated with an export hash.

27. **Keep MAPINFO separate from native map content.** The native archive
    stores a header name, dimensions, planes, and implicit slot. Campaign
    routing, music, display names, and floor/ceiling presentation live in
    MAPINFO. Version 1 edits native maps and selects a target slot; custom
    campaign metadata generation is a later verified feature.

28. **Build one authoritative codec and one authoritative asset decoder.**
    Consolidate the repository's proven tools rather than maintaining several
    subtly different readers. Existing command-line tools should consume the
    shared core or thin compatibility shims.

29. **Use generated plus curated catalog data.** The engine's XLAT and actor
    definitions remain authoritative for raw mappings. Checked-in,
    noncommercial metadata supplies stable names, categories, descriptions,
    placement rules, and search terms, with a consistency gate against source.

30. **Integrate tests into `tools/run_gates.sh`.** There is one project gate
    entry point. Data-free hosted tests and legally owned data-dependent local
    tests remain explicitly separated.

31. **Ship the public editor without retail content.** A user-authored WAD may
    reference runtime texture and actor IDs without embedding art. An edited
    retail map remains commercial-derived even if converted to WAD or JSON and
    is not a public artifact under project policy.

32. **Target Windows x64 and Linux x64/arm64 first.** Android editing, browser
    editing, collaborative cloud editing, and macOS packaging are not first
    release commitments.

33. **Prefer recoverable, inspectable formats and behavior.** Project JSON is
    versioned and deterministic; exports can be reopened; diagnostics include
    stable codes; logs show the exact sanitized argument vector and file
    hashes; no opaque database is required.

34. **A first playable vertical slice comes early.** Before advanced specials
    or polish, the editor must import MAP01, paint a wall, place an enemy, undo,
    save/reopen, export one preview WAD, and make EC7Wolf enter it.

35. **Version the editor independently.** The first public editor release is
    `EC7Edit 0.1.0`; every build also reports its source commit, project-schema
    version, catalog version, and engine-protocol capability set. This identity
    is deliberately separate from EC7Wolf's commit-derived `1.0-betaX` and
    from the engine's save-product compatibility fields.

---

## 2. Product definition

### 2.1 Product promise

EC7Edit should feel like a drawing program for Corridor 7 levels:

1. Open or create a map.
2. Choose something visible from a palette.
3. Paint or place it on the map.
4. Fix the clearly explained problems, if any.
5. Press **Test Map** and play it.

The raw editor is available for experts, but it is not the product's front
door. No beginner should need to know that an east-facing Captain+ enemy is a
particular plane-1 integer, that doors infer their axis from adjacent floor
cells, or that a masked wall combines two planes.

### 2.2 Primary users

#### First-time mapper

This user owns Corridor 7, may have used a paint program, and does not know
TED5, RLEW, XLAT, WAD lumps, or MAPINFO. The editor must offer safe defaults,
plain language, discoverable controls, immediate visual feedback, and errors
that include a suggested fix.

#### Experienced Wolf-family mapper

This user understands grid maps and wants speed: keyboard shortcuts,
eyedropper, fills, rectangles, multi-selection, copy/paste, raw IDs, layers,
and precise diagnostics. Friendly abstraction must not prevent exact control.

#### EC7Wolf developer or researcher

This user needs lossless import, raw-plane inspection, deterministic output,
source archive hashes, diagnostics, synthetic fixtures, CLI validation, and
fast launch/capture integration. The same production core must serve automated
tests and investigations.

### 2.3 Required user-visible workflows

The first complete release supports all mandatory workflows below without
hand-editing files. The separately labeled Snapshot item is conditional on the
E10 gate and may be deferred without blocking the core release:

- Configure an EC7Wolf executable and legally owned Corridor 7 data directory.
- See whether the data set is complete and recognized, with a precise remedy
  for each missing or unsupported file.
- Create a safe 64×64 map with a solid border, one floor zone, and a placed
  player start.
- Import any map from the user's `MAPTEMP.CO7` through a visual archive/map
  chooser without modifying that archive.
- Save and reopen a versioned editor project.
- Browse searchable wall thumbnails and paint a wall by clicking or dragging.
- Eyedrop an existing wall or item back into the active palette/tool.
- Place, move, rotate, duplicate, replace, and erase statics, pickups, hazards,
  player starts, enemies, and patrol markers.
- Choose an enemy by name, then choose facing, stationary/patrolling behavior,
  and minimum rank without calculating a raw value.
- Paint floor/sound zones and see them as a colored overlay.
- Place validated doors, access doors, wall interactions, moving walls, masked
  walls, animated walls, transporters, elevators, and exits through semantic
  tools or prefabs.
- Select one cell or a rectangular/multi-cell region and inspect both friendly
  properties and exact raw plane values.
- Undo and redo every edit, including a whole drag/fill/prefab as one command.
- Cut, copy, paste, flip, and rotate a selection without corrupting direction
  semantics.
- See continuous, clickable validation diagnostics.
- Export a small one-map WAD and reopen it for verification.
- Export a complete private `MAPTEMP.CO7` working copy when explicitly chosen.
- Press Test Map to validate, export a disposable preview, and launch EC7Wolf
  directly into the chosen map/rank.
- Stop or relaunch a running playtest and inspect its log and exit status.
- Recover unsaved work after a simulated editor crash.
- **Conditional E10:** choose a tile and direction and request an exact
  software-rendered 3D snapshot if that gated feature lands.

### 2.4 User experience principles

1. **Show, then name, then number.** Palette entries show a thumbnail, friendly
   name, and short purpose. Raw IDs are visible in secondary text and search.

2. **One obvious primary action.** Selection changes expose relevant actions;
   the toolbar does not present every obscure raw feature with equal weight.

3. **Preview before destructive or compound edits.** A door ghost shows its
   inferred axis; a fill previews its region; a prefab shows all cells it will
   alter; invalid placements explain why before commit.

4. **Keep the canvas responsive.** Asset decoding, archive census, validation
   beyond the immediate edit, exports, and child-process work do not block the
   GUI thread.

5. **Make state visible.** Current tool, selected catalog item, target map
   slot, layer visibility, zoom, cursor coordinate, raw values, dirty state,
   validation counts, and playtest state are always discoverable.

6. **Do not hide loss.** If a feature cannot be represented, exported, or
   understood, say so before action. Never silently replace, clamp, or drop it.

7. **Errors point to fixes.** “Door at (17,22) has no opposite walkable sides;
   rotate its surrounding corridor or replace it with a wall” is useful.
   “Invalid map” is not.

8. **Advanced controls are progressive disclosure.** Raw layers, plane words,
   source fingerprints, archive replacement, MAPINFO experiments, and unusual
   dimensions live behind Advanced panels without being removed.

9. **Mouse and keyboard are peers.** Every core operation is clickable; every
   repetitive core operation receives a stable shortcut and tooltip.

10. **The original is safe.** Import, experimentation, failed export, and
    playtesting cannot modify the legally owned source archive.

### 2.5 Explicit non-goals for version 1

- A general ECWolf/Wolfenstein/Spear/Blake Stone editor. The core may be
  reusable, but the product is intentionally Corridor 7-specific.
- Editing arbitrary polygonal geometry, slopes, free-height sectors, 3D floors,
  or arbitrary sub-tile thing coordinates. Corridor 7 is a tile-grid game.
- An in-game editor, runtime hot reload, live engine memory editing, or engine
  DLL embedding.
- Exact interactive 3D inside the editor. The real engine Test Map window is
  the exact interactive renderer.
- A complete custom-campaign/MAPINFO authoring suite in the first release.
- A DECORATE, XLAT, ACS, weapon, monster, sprite, sound, palette, cinematic, or
  executable editor.
- Shipping or downloading Corridor 7 data, extracting data from sources the
  user is not authorized to use, or bypassing ownership checks.
- Cloud accounts, telemetry, advertising, subscriptions, online asset stores,
  real-time collaboration, or automatic map publishing.
- Android or touch-first editing.
- Guessing and rewriting plane-2 semantics.
- Guaranteeing that an arbitrary level is fun or mechanically completable.
  Validation proves structural properties and reports reachability evidence;
  playtesting remains essential.
- Maintaining compatibility with original DOS Corridor 7 as a first-release
  promise. Native archive preservation makes later DOS testing possible, but
  EC7Wolf is the defined runtime target.

---

## 3. Definition of done

### 3.1 Functional completion

The editor is functionally complete only when:

- A clean first launch guides the user to a valid EC7Wolf executable and
  Corridor 7 data directory.
- A user can complete every mandatory workflow in Section 2.3 with mouse-driven
  UI; the explicitly conditional E10 workflow is required only if Snapshot
  ships.
- Import of all 60 maps in the owned CD archive succeeds read-only and records
  exact source fingerprints.
- Project save/reopen preserves every map header, dimension, plane word,
  target-slot setting, and supported editor annotation.
- An untouched imported map round-trips with exact decoded plane equivalence;
  plane 2 and unknown values are unchanged.
- Wall painting and object/enemy placement have thumbnail palettes, meaningful
  names, immediate canvas feedback, and atomic undo/redo.
- Every compound Corridor 7 feature changes the correct planes together.
- A preview WAD contains only intended map lumps, reloads through both the core
  and EC7Wolf, and never modifies source data.
- Test Map launches the configured engine into the exported target map with
  isolated config/saves and actionable process diagnostics.
- The 3D Snapshot feature either passes its explicit milestone gate or remains
  visibly labeled as deferred; it never blocks the core release.
- Autosave recovery survives a force-killed editor test without losing the
  last completed edit transaction.
- Public packages and hosted CI artifacts are demonstrably free of commercial
  or commercial-derived content.
- Supported Windows and Linux packages pass startup, import-with-synthetic-
  data, editing, export, and launcher smoke tests.
- User documentation, built-in help, shortcuts, validation explanations,
  licensing notice, and a minimum bug-report template are present.

### 3.2 Quality completion

The feature is not done merely because a demo works. It also requires:

- No uncaught exception for malformed project, archive, or settings input.
- No shell construction, unsafe archive extraction, path traversal, source
  overwrite by default, or symlink-following write vulnerability.
- Deterministic project serialization and deterministic preview WAD output for
  equal documents and catalog versions.
- A bounded memory policy for images, undo history, validation, and logs.
- No UI-thread operation that causes a visible multi-second freeze on the
  supported 60-map archive and normal hardware.
- Keyboard-only reachability for every core control, visible focus, usable
  labels, scalable text, high-DPI correctness, and non-color-only diagnostics.
- Stable diagnostic codes and tests for every export-blocking validation rule.
- A source-backed explanation and test for every semantic catalog entry that
  writes more than one raw plane value.
- Clean data-free gates, clean data-dependent gates where owned data is
  available, and a fresh self-contained release package/startup check.

### 3.3 Honest limitations shown to the user

The UI and manual must say:

- Imported retail maps and screenshots are local commercial-derived content.
- Plane 2 is preserved but not fully interpreted.
- Target map slot affects campaign behavior; MAP30 and MAP40 are particularly
  special.
- Display names, floor/ceiling choices, music, and routing may come from
  MAPINFO rather than native map bytes.
- Door direction is inferred from topology rather than stored explicitly.
- Reachability checks are advisory, not a proof against every gameplay state.
- Test saves may be invalidated when the map export changes.
- An editor layout snapshot is not a substitute for running the game.

---

## 4. Current source and data audit

### 4.1 Evidence grades used by this plan

| Grade | Meaning | Use in implementation |
| --- | --- | --- |
| A | Current EC7Wolf source or a passing automated test directly establishes the behavior | May define a hard contract, with a regression test |
| B | A repository tool and read-only census of legally owned retail data agree | May guide implementation; add a data-dependent gate |
| C | Existing report, observed pattern, or inferred semantics without a complete runtime proof | Preserve data and expose cautiously; do not normalize |
| D | Product proposal or unresolved experiment | Must pass a milestone spike before becoming a commitment |

Line numbers are navigation aids, not APIs. Milestone E0 freezes exact symbols,
tests, and fixture hashes against the then-current tree.

### 4.2 Native `MAPTEMP.CO7` archive

Corridor 7's native map archive is a self-contained TED5 file. The production
implementation must be reconciled with both the existing local-workspace
Python codec at `../tools/python/corridor7_map.py` (outside the ECWolf git root)
and the
engine loader in
[`file_gamemaps.cpp`](../src/resourcefiles/file_gamemaps.cpp).

Established format properties:

| Property | Contract |
| --- | --- |
| Initial signature | 12 bytes: `TED5v1.0.\0\0\0` |
| Subsequent record marker | Four bytes: `!ID!` |
| Archive terminator | A final `!ID!` with no following complete record |
| Compression | RLEW over little-endian unsigned 16-bit words |
| RLEW tag | `0xABCD` |
| Planes | Exactly three |
| First record size | 46 bytes, including the signature and record fields |
| Later record size | 42 bytes, beginning with `!ID!` |
| Plane offsets | Absolute 32-bit file offsets; first plane of first record is implicitly after its header in the native layout |
| Plane lengths | Three unsigned 16-bit compressed byte lengths |
| Dimensions | Unsigned 16-bit width and height, each at most 181 in the EC7Wolf loader |
| Expanded plane bound | `width × height × 2` bytes must fit the format and decoder constraints |
| Name | Exact fixed 16-byte field; display normally stops at the first NUL, while new/renamed editor output is at most 15 ASCII bytes plus NUL/padding |
| Archive map bound | 1–100 maps in the production contract and current engine bound |

Each recorded plane length includes a leading little-endian 16-bit expanded-
byte count. The remainder is a word stream: a word other than `0xABCD` is one
literal; `0xABCD, count, value` expands to `count` copies of `value`. A literal
whose value is itself `0xABCD` must therefore use the triple form. The decoded
output must equal the declared expanded size exactly and the input must end at
the recorded plane length.

The existing Python implementation is a strong starting point, not yet the
production losslessness contract. It validates the principal RLEW streams,
lengths, offsets, and dimensions, but its inspected version also accepts an
empty or marker-only archive, accepts a last record without the conventional
final `!ID!`, does not enforce the later-record plane-0 lower bound as strictly
as the engine, and decodes/encodes names with replacement and truncation. The
engine independently validates dimensions, plane ranges, and streams before
exposing each map as `MAP01`, `MAP02`, and so on followed by a generated
`PLANES` lump. E1 closes the differences explicitly rather than calling either
implementation perfect. See local-workspace evidence
`../tools/python/corridor7_map.py`,
[`file_gamemaps.cpp`](../src/resourcefiles/file_gamemaps.cpp), and
[`wolfmapcommon.cpp`](../src/resourcefiles/wolfmapcommon.cpp).

The owned archive also contains four headers with nonzero bytes after the first
NUL in the 16-byte name field. Those bytes may be unused padding, but a lossless
editor does not guess: imported maps retain the exact 16 bytes separately from
their decoded display name. Editing the name deliberately replaces the full
field with the validated canonical ASCII/NUL/padding encoding.

Production canonicalization policy is explicit:

- reject empty and marker-only archives;
- accept an otherwise valid engine-compatible archive that ends immediately
  after its last plane without the conventional final `!ID!`, but report a
  noncanonical warning;
- always emit the final `!ID!` from the canonical native writer;
- accept a zero-count RLEW triple only when the bounded stream still consumes
  input and expands exactly, report it as noncanonical, and never emit one;
- enforce every later map's first plane begins at or after its complete
  42-byte header, matching the engine's lower-bound validation.

A read-only census of the owned CD archive found 60 maps, all 64×64. Campaign,
bonus, unused, and network/archive groupings are useful labels, but archive
order remains the canonical map number:

- MAP01–MAP40: the main campaign.
- MAP41–MAP46: bonus/secret floors.
- MAP47–MAP50: unused or empty archive slots.
- MAP51–MAP60: network/archive maps, including sparse entries.

This census is a local data-dependent fact, not a distributable fixture.

### 4.3 Canonical in-memory plane model

Every map has three independent arrays of `width × height` unsigned 16-bit
words. A cell is not one enum. Geometry and an object/special marker can coexist
at the same coordinate, and some semantic structures require both.

The coordinate convention must be frozen in code and tests:

- Origin `(0, 0)` is the native top-left cell.
- `x` increases right; `y` increases down in the 2D editor.
- Linear index is `y * width + x`.
- File plane order is plane 0, plane 1, plane 2.
- The canvas may display compass north as up, but raw coordinates never rotate.
- Direction rotations during selection transforms are catalog-driven, not
  inferred from numeric adjacency at paste time.

### 4.4 Plane 0: geometry, doors, zones, and floor actions

The authoritative mapping is
[`wadsrc/static/xlat/corridor7.txt`](../wadsrc/static/xlat/corridor7.txt),
interpreted by
[`gamemap_planes.cpp`](../src/gamemap_planes.cpp).

| Raw value | Established meaning | Friendly editor treatment |
| --- | --- | --- |
| `0` | Void/unassigned in tools and some maps; not a normal reachable floor zone | Advanced/raw; warn when reachable |
| `1–250` | Solid walls; map word `N` selects wall graphics page `N - 1` | Searchable wall-material palette, excluding semantics promoted to prefabs |
| `251` | Normal door | Door tool |
| `252` | Red-card locked door | Access-door tool |
| `253` | Blue-card locked door | Access-door tool |
| `254` | Special/standard door variant | Door tool with description from catalog |
| `255` | Direction-dependent wall using engine-selected pages | Dedicated directional-wall item; not ordinary paint |
| `256–277` | Sound/area zones | Colored zone brush and fill |
| `278` | Ambush/fill-zone behavior | Dedicated advanced zone type |
| `279–286` | Eight paired transporter channels | Paired transporter prefab/tool |
| `287` | Player-cross floor exit | Floor-exit prefab/tool |

Some ordinary-looking wall IDs also have interaction semantics in the XLAT,
including access/alarm panels, elevator art, and health/ammo/visor dispensers.
The catalog must route these through “place this functional panel” rather than
pretend appearance and behavior can be separated: in native data, painting that
raw wall ID necessarily installs its XLAT behavior. A user can search by visual
page or behavior, but the dedicated tool explains and validates the semantic
effect; there is no fake appearance-only encoding.

Door orientation is not encoded directly. The engine compares adjacent
north/south and east/west openings, chooses an axis, configures jambs/use sides,
and resolves a tie by its current rule. The editor therefore previews the
inferred axis and warns about corners, ties, blocked approaches, or lack of two
opposing walkable sides. The current source seam begins in
[`gamemap_planes.cpp`](../src/gamemap_planes.cpp).

That topology warning cannot be a general export error: a read-only census
found 88 shipped door cells with only one open neighbor under the engine's own
criterion, and the engine accepts/orients them. The friendly Place Door tool
may require confirmation for newly created one-sided topology, while unchanged
or intentionally imported doors remain exportable with a warning.

### 4.5 Plane 1: starts, things, enemies, and wall modifiers

Plane 1 holds one raw word per cell. Its normal empty value is **18**, not zero.
Erasing a thing must restore 18 unless a selected semantic operation explicitly
requires another marker.

| Raw value/range | Established meaning | Friendly editor treatment |
| --- | --- | --- |
| `18` | Empty object plane | Blank/no thing |
| `19–22` | Player start in four directions | One Start item with direction control |
| `23–85` | Static scenery, pickups, weapons, hazards | Categorized object palette |
| `86–88` | Animated wall phase markers | Animated-wall property/tool |
| `90–97` | Patrol direction markers | Path overlay and patrol-direction tool |
| `98` | Secret-counting sliding/push wall | Secret pushwall tool |
| `99` | Bonus/secret elevator marker modifying wall 63 | Secret elevator prefab |
| `101–102` | Ordinary moving/sliding wall variants | Moving-wall tool |
| `104` | Masked wall modifier that blocks sight | Masked-wall tool |
| `105` | Masked wall modifier that permits sight | Masked-wall property |
| `106` | Closed/repeatable animated or retractable wall | Animated-wall tool |
| `107` | Permanently open/ignored animated wall state | Advanced animated-wall state |
| `108+` | Enemies, bosses, difficulty and pathing variants, later special objects | Semantic enemy/special palettes |
| `268` | Boss/exit vortex | Slot-aware exit prefab |
| `318–320` | Later weapon pickups | Weapon palette |
| `321` | Transporter field/visual actor; not the teleport linkage itself | Added by the friendly transporter prefab by default, but optional at runtime |
| `322` | Floor-exit visual actor; not the floor trigger itself | Added by the friendly floor-exit prefab by default, but optional at runtime |

The exact raw tables, not the coarse ranges above, are authoritative. The
catalog generator must join XLAT entries with Corridor 7 actor definitions in
[`wadsrc/static/actors/corridor7/`](../wadsrc/static/actors/corridor7/).

Enemy translation entries encode a base class, facing variants, patrol state,
and minimum skill/rank. The editor presents one enemy card with properties:

- Facing: north, northeast, east, southeast, south, southwest, west, northwest
  where the native mapping supports those directions.
- Behavior: stationary or patrol/pathing where supported.
- Minimum rank: one of the source-defined bands—All ranks, Captain+, or
  Major+.
- Raw value: visible in Advanced details and preserved exactly on import.

The UI must not assume every enemy has the same number of angles or a simple
constant offset. Transform operations use generated catalog mappings with
tests for each rotation/reflection.

### 4.6 Plane 2: preserved advanced sector/flat data

Plane 2 is loaded and used to partition or select flat/sector state in
[`gamemap_planes.cpp`](../src/gamemap_planes.cpp), but Corridor 7's translator
does not provide a complete user-facing table. A local archive census found:

- value 0 in 241,643 cells;
- value 1 across all 4,096 cells of MAP02;
- value 3 in 21 cells of MAP04.

This disproves any assumption that the plane is always zero. Its authored
meaning is not sufficiently established for automatic rewriting. It also
contradicts a current MAPINFO comment that describes shipped flat planes as
uniformly zero; E0 must record that conflict and retain the measured-data-safe
preservation rule unless stronger runtime evidence resolves it.

Version-1 policy:

- Preserve every imported plane-2 word exactly.
- Default new maps to zero.
- Show the plane only under **Advanced → Raw sector plane**.
- Allow inspected, explicitly confirmed raw editing with undo.
- Never clear, remap, compact, or “repair” it automatically.
- Treat known nonzero values as informational, not invalid.
- Require data-dependent round-trip tests that include all observed values.

### 4.7 MAPINFO and slot-dependent behavior

Native TED5 records contain only the map name, dimensions, three planes, and
their archive order. The current Corridor 7 MAPINFO in
[`wadsrc/static/mapinfo/corridor7.txt`](../wadsrc/static/mapinfo/corridor7.txt)
defines display names, music, floor/ceiling presentation, routing, skills, and
special map progression. Explicit MAPINFO names override native header names in
[`g_mapinfo.cpp`](../src/g_mapinfo.cpp).

Consequences for the editor:

- Every map document has a **target slot** separate from its native header
  name.
- The UI shows inherited MAPINFO behavior for the selected stock slot.
- Changing a header name alone may not change the in-game display name.
- MAP30 and MAP40 receive explicit warnings because exit/victory behavior is
  slot-sensitive.
- A custom MAPINFO override is not silently generated in version 1.
- A later custom-campaign milestone must define its own schema, source
  generation, load-order behavior, and engine tests before exposing controls.

### 4.8 Zones, transporters, exits, and map topology

Areas 256–277 participate in sound propagation and are linked as doors move.
They are gameplay structure, not decorative floor colors. New-map templates use
one valid zone, normally 256; a zone brush, flood fill, and overlay make splits
visible. The validator warns about reachable open cells that have no valid zone
and about suspicious door/area relationships.

Transporters 279–286 are channel-coded pairs. The current loader expects two
plane-0 endpoints and warns otherwise. A transporter tool places or assigns the
plane-0 channel and, by friendly default, plane-1 field visual 321, colors each
channel consistently, and shows its partner. The plane-1 actor is visual only;
a missing or orphan visual is a warning and repair opportunity, not an export
block. A channel count other than two remains an export-blocking structural
error for supported authoring unless later source evidence proves an exception.

Exits have several forms: floor crossings, ordinary elevators, secret
elevators, clearance/rank behavior, and slot-specific vortex/victory behavior.
Each is a semantic prefab with context checks. “Exit exists” is not sufficient;
the editor also verifies compatible base wall/floor and marker combinations and
advises about reachability.

### 4.9 Composite and mutable walls

The current engine interprets plane-1 markers over plane-0 wall cells for
moving, masked, and animated behavior. The editor must not expose these as
unrelated raw toggles.

Minimum semantic tools:

- Ordinary push/moving wall.
- Secret-counting pushwall.
- Secret/bonus elevator based on the required wall and marker.
- Masked wall that blocks sight.
- Masked wall that permits sight.
- Four-frame animated/retractable wall, including phase where supported.
- Permanently open animated-wall state under Advanced.
- Health chamber prefab with the required one-cell chamber, rear use panel,
  door/base wall, approach, and runtime assumptions.

Each tool owns a documented write set, precondition, preview, undo transaction,
validation rule, rotation rule, and source reference. A catalog consistency
test rejects a compound item without all six.

### 4.10 Retail assets and palette

Corridor 7 graphics come from `GFXTILES.CO7`; the required palette is extracted
at runtime from the recognized 250,776-byte `CORR7CD.EXE`. The editor requires
the same legally owned inputs and does not ship decoded pixels.

The existing read-only browser
[`tools/c7assets.py`](../tools/c7assets.py) already demonstrates:

- embedded palette decoding;
- GFX header and 64×64 wall-page decoding;
- Wolf column/post sprite decoding;
- VGA picture decoding;
- actor-definition parsing and cross-reference;
- in-memory wall, sprite, and map thumbnail endpoints;
- schematic map rendering without writing retail data.

The stricter local-workspace graphics helper
`../tools/python/corridor7_gfxtiles.py`
and the engine loaders/textures are additional evidence. Production work must
extract one bounded decoder rather than let the editor depend on the browser's
weaker duplicate map parser or regex-only categorization.

Observed archive shape: the retail GFX header contains 1,114 chunks—256 wall
pages followed by 858 sprite chunks. EC7Wolf exposes 1,115 resource lumps only
after synthesizing the additional `C7PAL` palette lump from the supported
executable. Only wall pages 0–249 map directly to ordinary plane-0 wall values
1–250; later pages and structural raw codes must not be offered as
interchangeable wall paint.

### 4.11 Existing reusable tooling

The repository has already solved important parts of the editor, but the code
is fragmented:

| Existing component | Value | Required action |
| --- | --- | --- |
| Local `../tools/python/corridor7_map.py` | Useful TED5/RLEW parse, encode, archive rebuild, and diagnostics with the E1 gaps recorded above | Reuse only after E0 provenance/license approval; otherwise independently implement and keep a compatible CLI shim |
| Local `../tools/python/test_corridor7_map.py` | Synthetic round-trip and malformed-input tests | Recreate/extend approved synthetic cases in editor core gates |
| [`c7assets.py`](../tools/c7assets.py) | Palette, walls, sprites, maps, actor browsing | Extract shared bounded decoders; make browser consume them |
| Local `../tools/python/corridor7_gfxtiles.py` | Defensive graphics parsing | Reconcile with browser after provenance review and avoid mandatory Pillow in core |
| Local `../tools/python/make_corridor7_lab_map.py` | Useful one-slot transformation/new-room patterns, but current direct-write behavior does not prevent source/output identity or provide atomic replacement | Rebase on the canonical codec and add source inequality, atomic output, readback, and source-hash regression tests |
| [`make_corridor7_ai_lab.py`](../tools/make_corridor7_ai_lab.py) | Generated AI test map/archive | Consume canonical codec; do not duplicate format behavior |
| [`make_corridor7_mp_lab.py`](../tools/make_corridor7_mp_lab.py) | Generated multiplayer lab maps | Same consolidation rule |
| Local `../tools/python/validate_corridor7_campaign.py` | Start, reachability, exits, campaign checks | Reuse only after provenance review or independently reimplement the documented advisory model |
| [`corridor7.txt`](../wadsrc/static/xlat/corridor7.txt) | Authoritative native code translation | Generate and audit catalog mappings |
| [`actors/corridor7`](../wadsrc/static/actors/corridor7/) | Actor classes, sprites, behavior metadata | Join with XLAT and curated labels |

The consolidation rule is important: a GUI that creates a third map decoder
would turn format fixes into a synchronization problem. Milestone E1 produces
one tested codec and ports callers to it incrementally.

### 4.12 Engine map-resource seam

EC7Wolf converts native maps to an internal uncompressed WDC3.1 `PLANES`
representation. [`gamemap.cpp`](../src/gamemap.cpp) accepts a `MAPxx` marker
followed by a `PLANES` lump. The layout consumed by
[`gamemap_planes.cpp`](../src/gamemap_planes.cpp) and emitted by
[`wolfmapcommon.cpp`](../src/resourcefiles/wolfmapcommon.cpp) is:

| Offset | Size | Meaning |
| ---: | ---: | --- |
| 0 | 6 | ASCII magic `WDC3.1` |
| 6 | 4 | Conventional little-endian map count; 1 for this one-map PLANES lump |
| 10 | 2 | Plane count, little-endian; 3 |
| 12 | 2 | Name-field length; 16 |
| 14 | 16 | Native name bytes |
| 30 | 2 | Width, little-endian |
| 32 | 2 | Height, little-endian |
| 34 | `width × height × 3 × 2` | Raw little-endian plane words in plane order |

The current reader deliberately seeks past bytes 6–9, while the current
`FMapLump::FillCache` path does not initialize all four bytes after copying the
magic. The editor must not reproduce that nondeterminism: it writes an explicit
little-endian 1 as documented by `ReadPlanesData`, then verifies the result with
an independent reader and EC7Wolf.

A minimal preview WAD therefore contains:

1. A zero-length marker named for the target, such as `MAP01`.
2. One `PLANES` lump with the layout above.

No retail texture or sprite pixels are embedded. EC7Wolf resolves those from
the user's base data.

### 4.13 Engine load order and direct map launch

The engine supports every needed launch option in
[`wl_main.cpp`](../src/wl_main.cpp):

- `--data CO7` selects the detected data extension; it does not identify a
  directory.
- `--file ABS_PREVIEW` appends an extra resource after base/core/autoload data.
- `--config ABS_CONFIG` isolates the configuration file.
- `--savedir ABS_DIR` isolates savegames.
- `--nowait` skips intro screens.
- `--tedlevel MAPxx` starts a named map.
- `--skill N` selects a 1-based rank/difficulty for direct launch.

WAD lookup searches loaded files backwards, so a later preview `MAP01` marker
and `PLANES` override the base map without copying or changing
`MAPTEMP.CO7`. A repository investigation also verified a generated temporary
map override entering MAP01 under Xvfb while the source archive remained
unchanged. Milestone E1/E9 converts that evidence into a permanent integration
gate.

The canonical direct playtest shape is an argument vector, shown wrapped only
for readability:

```text
working directory: /absolute/path/to/the/user's/Corridor7/data

/absolute/path/to/ec7wolf
  --data CO7
  --file /absolute/private/temp/editor-preview.wad
  --config /absolute/private/temp/playtest.cfg
  --savedir /absolute/private/temp/saves
  --nowait
  --tedlevel MAP01
  --skill 2
```

The editor can point directly at the EC7Wolf binary inside the private package.
Its POSIX
[`run-corridor7.sh`](../tools/corridor7-release/run-corridor7.sh) changes to the
package directory, sets local config/saves, and forwards arguments, but it is
only a future audited adapter candidate under Section 15.6—not a generic
cross-platform version-1 launch contract. An adapter must not append a second
renderer choice because the current engine honors the first renderer option.

### 4.14 Renderer and capture feasibility

EC7Wolf is a monolithic SDL application, not a supported render library.
`IRenderer::RenderScene()` renders current global engine state into the active
framebuffer; world building depends on global map, texture, timing, and dynamic
wall state. Embedding this in a Qt process would require a substantial engine
service/library extraction and lifecycle redesign.

The existing capture harness in
[`r_capture.h`](../src/r_capture.h) and
[`r_capture.cpp`](../src/r_capture.cpp) already supports a fixed RNG seed,
chosen rendered frame, PNG output, bounded frames/tics, and a player viewpoint
specified by tile and angle with `--capture-warp X Y DEG`. The normal PNG path
reads the software framebuffer; with the live OpenGL renderer that framebuffer
does not contain the GPU-owned 3D world. OpenGL's separate GL frame/present
capture paths currently write PPM. If Snapshot ships in version 1, it is
pinned to the software renderer unless E10 deliberately adds and tests a
renderer-specific artifact adapter.

A rendered frame number is also not a fixed simulation tic: frame pacing is
decoupled from the 70 Hz playsim, so the same `--capture-frame` can land on a
different tic. An image can still be an exact frame from EC7Wolf, but
byte-repeatable state and safe cache identity require a fixed-tic/readiness seam
or inclusion of the observed tic without claiming determinism.

Current argument seams must be treated honestly. `Capture::ParseArgs`
understands `--capture-warp`, but the inspected `CheckParameters` dispatch in
[`wl_main.cpp`](../src/wl_main.cpp) does not consume that option and its three
values alongside the other capture options. Likewise, the early renderer scan
uses `--vid-renderer` but ordinary dispatch does not consume its value, so
current launch logs can contain misleading “could not stat” resource errors.
E9 fixes renderer-option consumption; E10 audits every used capture option and
full arity before Snapshot can ship. Neither milestone may rely on
harmless-looking misparse behavior.

---

## 5. Commercial data, licensing, and trust boundaries

### 5.1 Ownership boundary

EC7Wolf engine code is distributed under its applicable free-software
licenses; Corridor 7 maps, art, sounds, music, executable, palette, and other
retail content are commercial. The existing ownership and required-file rules
are documented in [Corridor 7 single-player support](corridor7.md) and the
repository [README](../README.md).

The following are commercial-derived local content even when converted to a
different representation:

- an imported or edited retail map;
- a project JSON file containing retail plane data;
- a WAD or native archive containing a retail map;
- decoded wall, sprite, VGA, or palette pixels;
- map, palette, wall, object, or sprite thumbnails;
- exact 3D preview screenshots of retail content;
- thumbnail/image caches and autosave/recovery copies containing any of these;
- exported reports that include full retail plane arrays or decoded assets.

A filename-only scan for `*.CO7` is therefore insufficient. Public packaging
uses an allow-list and rejects project/cache/image/archive types from a build
that has touched retail data unless the artifact is independently proven
synthetic.

### 5.2 Allowed public content

The public source and editor package may contain:

- editor and engine code under their licenses;
- documentation and user-created UI artwork owned by the project;
- the existing project icon set, reused without regeneration;
- generated catalog metadata containing IDs, actor/class names, friendly
  descriptions, and rules derived from public source definitions;
- synthetic maps and synthetic image fixtures that cannot reconstruct retail
  content;
- user-authored map WADs that reference runtime IDs and embed no retail map or
  art, when the author chooses to distribute them.

Recipients of a user map still provide their own legally owned Corridor 7 data.

### 5.3 Filesystem separation

The editor defines four roots and never conflates them:

| Root | Content | Write policy |
| --- | --- | --- |
| Game-data root | User's retail Corridor 7 files | Read-only by default |
| Engine/package root | EC7Wolf executable, pk3, launcher | Read-only during editing |
| Workspace root | Projects, user exports, annotations, backups | User-selected writable location outside the first two roots |
| Private cache/session root | Thumbnails, autosaves, previews, logs, config, test saves | Per-user private application data, bounded and clearable |

The GUI resolves the private roots with
`QStandardPaths.AppLocalDataLocation` and `QStandardPaths.CacheLocation`, then
passes absolute paths to the Qt-free core. Command-line tools and tests require
explicit root overrides. New POSIX private roots use mode `0700`; Windows uses
the current user's inherited private ACL and rejects a root that is broadly
writable. The core never guesses a home-directory convention for itself.

The project packaging script copies the selected commercial data directory,
stages and validates a replacement, then currently removes and renames
`builds/release`; replacement of an existing package is not atomic and has a
brief gap. Consequently, workspaces and caches must never be created inside
either the game-data directory or `builds/release`. E12 either hardens that
swap to a recoverable platform protocol or records the current staged-replace
limitation without calling it atomic.

### 5.4 Read-only source proof

Before importing a retail archive, the editor records:

- canonical source path;
- file size;
- modification timestamp for display only;
- SHA-256 digest used for identity;
- whether the path or its parent appears writable;
- whether it is a symlink and its resolved target.

After any import, export, or playtest operation that references it, integration
tests compare the source hash. A changed source is a stop-the-line failure. The
production UI never writes the source merely to “verify” access.

### 5.5 Public release audit

Public editor release staging must:

1. Start from an empty staging directory.
2. Copy only allow-listed source/package outputs.
3. Scan files, nested zip/tar contents, executable resources, and generated
   manifests.
4. Reject retail filenames, project/cache extensions, preview WADs, screenshot
   types not explicitly owned, and known commercial hashes.
5. Reject a build manifest that identifies a retail-data integration run as
   the source of public test artifacts.
6. Record the audit command and file manifest as release evidence.

Private local `builds/release` is different: project policy intentionally
copies Jason's owned game data into a runnable local package. It must never be
committed or redistributed.

### 5.6 Editor and dependency licensing

E0 freezes the editor's repository-compatible license before implementation;
the default is GPL-3.0-or-later unless the repository license audit requires a
different compatible expression. No local helper is copied into the public
tree until its copyright, provenance, and reuse authorization are established;
when that cannot be established, the implementation is independently written
from the documented byte contracts and synthetic tests.

PySide6, the corresponding Qt runtime, PyInstaller, and every bundled plugin or
library receive a versioned license inventory. Packaging includes all notices,
license texts, source/relink information, and offer/mechanism required by the
selected versions and distribution form. E12 produces a machine-readable
package manifest and fails the public release audit for an unreviewed binary,
missing notice, incompatible license, or dependency not present in the lock or
allow-list. “Build dependency only” is not an exemption from this review.

---

## 6. Architecture

### 6.1 Selected system

EC7Edit is a standalone application with a Python 3.10-compatible pure-Python
headless core and a PySide6/Qt Widgets presentation shell. Python 3.12 is the
reference frozen GUI runtime, not a requirement that every supported Linux
distribution expose that exact system minor. EC7Wolf remains an external
process for authoritative validation, playtesting, and exact snapshot capture.

```text
┌──────────────────────────────── EC7Edit process ───────────────────────────────┐
│                                                                                │
│  PySide6 GUI                                                                   │
│  main window · canvas · palettes · inspector · problems · logs · snapshot     │
│              │ commands / immutable view data / events                         │
│              ▼                                                                 │
│  Qt-free core                                                                  │
│  document · command engine · codec · assets · catalog · validation · project  │
│                     │                         │                                 │
│                     │ deterministic files     │ launch plan                     │
└─────────────────────┼─────────────────────────┼─────────────────────────────────┘
                      ▼                         ▼
            project / preview WAD       EC7Wolf child process
                                             │
                         user's read-only Corridor 7 data + generated override
```

The arrows are dependency boundaries:

- Core never imports GUI modules.
- GUI never parses native archives or mutates raw planes directly.
- Engine runner creates a structured launch plan; GUI adapts it to `QProcess`.
- EC7Wolf never reads an editor project; it reads a validated disposable WAD.
- Retail data decoders return bounded core image/index buffers; the GUI creates
  `QImage`/pixmap objects at its boundary.

### 6.2 Why PySide6/Qt Widgets

The repository's installer already documents and implements the same split:
headless Python operations with a PySide6 wizard and offscreen GUI tests. Qt
Widgets is a strong fit for a document editor because it supplies:

- native menus, shortcuts, file dialogs, settings, docks, splitters, and tabs;
- `QAbstractItemModel`/views for large searchable palettes;
- Qt actions and menus adapted to the core-owned undo/redo service;
- `QProcess` for non-shell child execution and output capture;
- `QThreadPool`/signals for image and validation work;
- accessibility names, keyboard navigation, translations, and high-DPI APIs;
- deterministic custom 2D painting without a browser or GPU requirement;
- `QT_QPA_PLATFORM=offscreen` for real-widget automated interaction.

The Qt-free `CoreUndoStack` is the sole authority for command history, current
index, redo-branch disposal, retention, saved-content identity, and clean/dirty
state. Qt `QAction` objects and menu labels observe and invoke that service;
they do not own or mirror a second `QUndoStack` index. Headless tests and the
GUI therefore exercise the same history.

### 6.3 Alternatives considered

| Alternative | Strength | Why it is not selected |
| --- | --- | --- |
| In-engine editor | Exact rendering and resource access | Monolithic global game state, poor desktop editing framework, no clean document/undo boundary, presentation lifecycle coupled to simulation |
| Standalone C++/Qt | Native performance and types | Adds a new C++ Qt dependency/deployment stack and duplicates mature Python map/asset tools without a demonstrated need |
| Browser/local HTTP editor | Existing asset browser proves visual feasibility | Safe filesystem writes, process launch, lifecycle, browser security, and packaging are less direct; a web canvas does not improve the native desktop workflow |
| Electron/web desktop | Rich UI ecosystem | Chromium footprint and a second JS implementation add cost with no format/runtime advantage |
| GTK/Tk | Lighter alternatives | Less aligned with the established Windows/KDE installer path and needed model/dock/undo/process features |
| Embed EC7Wolf renderer in Qt | Exact in-app 3D | Requires an engine-library/global-state extraction large enough to be its own project |
| Independent full 3D raycaster first | Attractive demo | Risks duplicating subtle doors, masked walls, palette effects, sprites, and dynamic behavior before core editing is trustworthy |

### 6.4 Proposed source layout

The implementation milestone may adjust names, but the dependency boundaries
are mandatory:

```text
ECWolf/editor/
├── pyproject.toml
├── ec7edit_core/
│   ├── __init__.py
│   ├── archive.py          # native TED5/RLEW model and codec facade
│   ├── planes.py           # coordinates, values, immutable snapshots
│   ├── wad.py              # deterministic WAD + WDC3.1 PLANES codec
│   ├── assets.py           # bounded palette/wall/sprite decoders
│   ├── catalog.py          # generated + curated semantic catalog
│   ├── document.py         # project/archive/map documents
│   ├── commands.py         # atomic edits and transaction coalescing
│   ├── transforms.py       # selection rotation/reflection semantics
│   ├── rules.py            # C7 compound-placement rules
│   ├── validation.py       # diagnostics and reachability
│   ├── project.py          # schema, migrations, atomic save/recovery
│   ├── export.py           # validated preview/full-archive export
│   ├── discovery.py        # engine/data validation
│   ├── engine_runner.py    # structured argv/cwd/environment plans
│   └── cli.py              # inspect/validate/export/headless smoke CLI
├── ec7edit_gui/
│   ├── application.py
│   ├── main_window.py
│   ├── map_canvas.py
│   ├── palette_models.py
│   ├── inspector.py
│   ├── problems.py
│   ├── project_browser.py
│   ├── playtest.py
│   ├── preview3d.py
│   ├── settings.py
│   ├── workers.py
│   └── help.py
├── resources/
│   ├── editor_catalog.json
│   ├── catalog_sources.json
│   ├── shortcuts.json
│   └── synthetic/          # explicitly noncommercial fixtures only
├── scripts/
│   ├── generate_catalog.py
│   └── audit_release.py
├── tests/
│   ├── unit/
│   ├── property/
│   ├── gui/
│   └── integration/
└── ec7wolf-editor          # source-tree launcher
```

Compatibility entry points under `tools/` may remain where project convention
requires them, but implementation is imported from the authoritative package.

### 6.5 Core services and ownership

| Service | Owns | Must not own |
| --- | --- | --- |
| Archive codec | Binary parse/encode, bounds, RLEW, headers | GUI, semantic guesswork, retail paths |
| WAD codec | Deterministic directory/lumps, WDC3.1 layout | Campaign policy or child process |
| Asset decoder | Bounded indexed pixels and metadata | Qt pixmaps, persistent commercial cache policy |
| Catalog | IDs, labels, categories, placement/rotation mappings | Raw plane arrays or widget state |
| Document | Maps, project settings, dirty/revision state | Native file handles, GUI selections |
| Command engine | Exact before/after mutations and transactions | File writes or modal UI |
| Rules | Semantic preconditions and compound write sets | Direct canvas input |
| Validator | Stable diagnostics and locations | Silent repair or save blocking UI |
| Project store | Schema, migrations, autosave, atomic writes | Retail asset bytes |
| Exporter | Preflight, deterministic outputs, post-readback | Shell launch or user settings mutation |
| Discovery | Verify engine and legal data requirements | Download, install, or alter data |
| Engine runner | Structured executable/cwd/argv/env/session paths | Shell strings, GUI process ownership |
| GUI | Interaction, presentation, accessibility | Format truth or unsupervised mutations |

### 6.6 Thread and process model

The GUI thread owns widgets, Qt image objects, current view transforms, and
final application of completed results. Worker tasks may perform:

- SHA-256 hashing and data discovery;
- archive parsing and map thumbnail generation;
- wall/sprite decoding and scaling source buffers;
- full-document validation and reachability;
- project serialization and export to a private temporary file;
- subprocess log processing that does not touch widgets.

Workers operate on immutable document snapshots tagged with a revision. A
result is applied only if it is still relevant, or is clearly labeled as a
result for an older revision. Cancellation is cooperative. Closing a project
invalidates its task token; a late worker cannot write into the next document.

Every canonical project or export target also has one serialized writer queue.
Save requests carry a monotonically increasing generation; queued obsolete
generations may be coalesced, and an older generation can never replace the
result of a newer completed generation. Autosave uses the same rule for its own
canonical recovery target. Serialization may run in a worker, but final
identity comparison and replacement are ordered by this single authority.

EC7Wolf runs in its own OS process. One editor project may own at most one
managed playtest process and one snapshot process at a time by default.
Advanced concurrent tests can be considered later, but isolated directories
and logs remain per session.

### 6.7 Dependency policy

Production dependencies are intentionally small:

- Python 3.10+ standard library for the core; E0 freezes and CI tests the
  supported upper bound before release.
- PySide6 for the GUI and Qt image/process/platform services.
- PyInstaller on Windows packaging hosts, as a build dependency only.
- Test-only libraries must justify their value and remain optional for users.

The reference frozen GUI uses Python 3.12. Supported source installations use
the distribution's tested Python/PySide pair rather than requiring an exact
minor that the distribution does not ship. Pillow is not required in the core
merely to create thumbnails. Decoders return
indexed/RGBA byte buffers; the Qt boundary constructs images. If property-test
or packaging dependencies are added, their versions, licenses, hashes/lock
strategy, and offline build behavior become part of the milestone gate.

---

## 7. Canonical document and project model

### 7.1 Model hierarchy

```text
ProjectDocument
├── schema version and project UUID
├── project metadata
├── local source reference and SHA-256 fingerprint
├── local engine/data profile reference
├── ordered MapDocument list
│   ├── stable editor UUID
│   ├── native header name
│   ├── exact raw 16-byte native name field
│   ├── target MAPxx slot
│   ├── width and height
│   ├── plane 0: exact uint16 words
│   ├── plane 1: exact uint16 words
│   ├── plane 2: exact uint16 words
│   └── editor-only annotations
├── project export defaults
└── recovery/provenance metadata
```

An `ArchiveDocument` is the codec-level ordered collection from a native file.
Import creates project map documents from it. The project does not need to
embed the entire archive when the user imports one map, but a private
full-archive workflow retains an immutable source/archive snapshot reference or
an explicitly imported ordered collection so untouched slots can be preserved.

### 7.2 Raw map fields are canonical

Semantic display properties are derived from the exact raw name/plane fields
and the catalog. The decoded native name is an editable view over its preserved
16-byte field, just as a masked-wall label is a view over plane words. For
example, a masked wall view might be:

```text
cell (12, 8)
plane0 = 47
plane1 = 105
semantic = Masked wall, sight-transparent, texture page 46
```

Changing the semantic property submits a command that declares its raw write
set. There is no second serialized semantic representation that can drift from
the raw words. Editor-only annotations may refer to stable map/cell IDs but do
not override game semantics.

### 7.3 Stable identity

- A project receives a random UUID on creation.
- A map receives a UUID that survives rename, reorder, and target-slot change.
- Native archive position is not used as the editor identity.
- Cells use `(map UUID, x, y)`; no persistent object UUID is invented for the
  one-word native thing unless an annotation specifically needs one.
- Catalog entries have stable namespaced string keys such as
  `c7.wall.material.0046`, `c7.enemy.alien_drone`, and
  `c7.prefab.transporter.a`; raw IDs remain fields, not primary UI identity.
- Diagnostics have stable codes plus locations, never localized text as keys.

### 7.4 Project schema principles

The first schema is JSON because it is inspectable, diffable, portable, and
easy to validate. Requirements:

- UTF-8, no byte-order mark.
- An integer `schema_version` and stable project UUID.
- Deterministic key ordering and compact but readable formatting.
- Plane rows represented explicitly and validated against width/height.
- Values encoded as JSON integers in 0–65535, never base64 opaque blobs in the
  initial schema.
- Native names stored as user-facing text plus an exact bounded 16-byte raw
  field encoded as 32 lowercase hexadecimal characters. On import the raw
  field is authoritative for unchanged export; on an intentional rename it is
  replaced by a strictly validated canonical ASCII/NUL/padding field. No
  replacement characters or tail bytes are lost silently. Load rejects a
  mismatched text/raw pair: `native_name` must equal the defined safe display
  decode of `native_name_raw_hex`, and rename updates both atomically.
- Absolute retail/source paths kept in a local profile or clearly marked local
  section, not required for sharing a purely user-authored project.
- SHA-256 fingerprints identify external source content without embedding it.
- A project-supplied display path is inert text. Opening a shared project does
  not stat, hash, open, contact, or execute that path—including a Windows UNC
  or device path. External content resolves only through an already trusted
  local profile/fingerprint association stored outside the shared JSON, or an
  explicit user-confirmed relink; network paths are policy-gated.
- Unknown JSON properties rejected in security-sensitive structures or kept in
  a defined extensions object; never silently interpreted as executable data.
- No scripts, code, templates with evaluation, network URLs, or environment
  variable interpolation.

A complete example appears in Appendix B.

### 7.5 Schema migration

Every schema change provides:

1. A pure migration from version N to N+1.
2. Tests for the oldest supported version through current.
3. Deterministic output after migration.
4. A backup before replacing an on-disk project.
5. A readable error for a newer unsupported schema.
6. A command-line `inspect`/`migrate --output` path for recovery.

Migration never resolves catalog changes by rewriting unknown raw words. A
catalog version records how the UI interpreted them, while raw values survive.

### 7.6 Atomic project save

For a single project file:

1. Acquire/verify the per-project cooperative lock and enter the single-writer
   queue for the canonical destination with a monotonic request generation;
   coalesce a queued older generation when safe. A second EC7Edit instance
   opens read-only or requires **Save As**, never competes silently.
2. Serialize an immutable document snapshot.
3. Validate schema and all plane lengths in memory.
4. Create a sibling temporary file with restrictive permissions.
5. Write, flush, and fsync where supported.
6. Reopen and parse the temporary file.
7. Confirm semantic equality and expected digest.
8. Immediately before replacement, compare the destination's handle-backed
   disk identity/content digest with the identity observed for this request.
   Abort with an external-change conflict if it differs.
9. Verify that no newer generation has already committed, then replace through
   the reviewed parent-handle-anchored platform adapter. Plain `os.replace` is
   acceptable only for a verified trusted local sibling path where that
   adapter proves equivalent behavior.
10. Fsync the parent directory where supported.
11. Update the document's saved revision only if it still matches the snapshot;
   a newer edit remains dirty.

The atomic/durability claim applies to tested local filesystems. SMB/NFS,
removable media, and cloud-synchronized folders may not honor sibling replace,
directory fsync, advisory locks, or stable identities; discovery warns and
defaults such projects to a safe local workspace plus explicit copy/export.
The design prevents accidental and untrusted-file path races and coordinates
EC7Edit instances; it does not claim to sandbox a malicious process already
running as the same OS user and continuously racing filesystem operations.

For a project directory, write a complete sibling staging directory and swap
only with a separately designed recoverable protocol. Version 1 should prefer a
single `.ec7project` JSON file to reduce multi-file atomicity risk.

### 7.7 Autosave and recovery

- Autosave is revision-based, defaulting to 60 seconds after the latest
  completed edit and on focus loss when dirty.
- Autosaves use a single-writer queue and monotonic generation per canonical
  recovery target; an older worker may never replace a newer recovery.
- It writes to the private application-data recovery root, not beside retail
  data unless the user explicitly selects a safe project workspace.
- Autosave does not clear the normal dirty flag.
- Recovery records project/source identity, original path, saved revision,
  autosaved revision, timestamp, and digest.
- On startup, a recovery chooser offers **Open recovered copy**, **Compare
  summary**, **Discard**, and **Later**. It never overwrites the project merely
  because the autosave is newer.
- Successfully saved and closed projects remove their obsolete recovery file.
- Retention is bounded by project count, age, and total bytes; deletions target
  exact application-owned paths only.

### 7.8 Backups

Normal atomic save needs no growing backup chain, but a user-configurable
rolling project backup is useful. Full native archive overwrite, if ever
enabled, always creates a timestamped sibling backup and verifies both backup
and replacement before reporting success. The source retail archive is not an
eligible overwrite target in the normal workflow.

### 7.9 Dirty state and external changes

The document tracks monotonically increasing edit and saved revisions. External
file watchers may report that a project or source changed:

- If the project is clean, offer reload with a summarized identity check.
- If dirty, offer **Save As**, **Compare metadata**, or **Ignore until close**;
  never auto-merge plane arrays.
- If the retail source hash changes, disable full-archive export against that
  source until the user deliberately reimports/rebases.
- A preview/export from revision R is labeled stale once the document reaches
  R+1; test saves are tied to the export digest.

---

## 8. Data discovery and asset catalog

### 8.1 First-run profile

The first-run page asks for:

1. Direct EC7Wolf executable; an optional audited launcher adapter is an
   advanced later profile.
2. Corridor 7 game-data directory.
3. Default project/workspace directory.

It then shows a checklist rather than a generic failure:

- executable exists, is a regular file, and can report an EC7Wolf identity;
- product is EC7Wolf `1.0-betaX`, based on ECWolf
  1.4.2-9-g1bff92d—not incorrectly reported as ECWolf 1.0;
- data directory is separate from project/cache roots;
- every required retail file is present;
- `CORR7CD.EXE` has the supported identity/size needed for the palette;
- `MAPTEMP.CO7` parses read-only;
- `GFXTILES.CO7` and VGA/audio headers satisfy bounded probes;
- optional music/cinematic content is reported as optional, not an editor
  blocker;
- the editor can create its private session/cache roots;
- the engine and data combination passes a non-mutating recognition probe when
  that milestone supports one.

Profiles store paths and nonsecret preferences in per-user settings. Project
files refer to a profile ID plus expected data fingerprint, not a copied retail
directory.

A project-provided profile ID, executable path, data display path, or source
path is never trusted merely because it parsed. Shared files do not trigger
filesystem/network access (including UNC access) during open. The user must
select an existing locally trusted matching profile or explicitly relink and
confirm each new local/network location; trust associations remain in local
settings, not shareable project JSON.

### 8.2 Discovery behavior

- Never recursively scan the whole home directory by default.
- Offer project/package-relative candidates and explicitly chosen locations.
- Resolve symlinks for containment checks but preserve the display path.
- Do not execute an arbitrary selected binary merely to inspect it before the
  user confirms a validation probe.
- Use bounded reads and exact signatures for data detection.
- Cache only hashes/metadata until the user opens an asset palette.
- Explain the distinction between `--data CO7` and the data-directory path.

### 8.3 Catalog inputs

The catalog is a build-time merge of:

1. Authoritative raw translation entries from Corridor 7 XLAT.
2. Actor/class, sprite, state, blocking, pickup, and behavior metadata from the
   Corridor 7 actor definitions.
3. Engine map-loader rules for doors, zones, mutable walls, transporters,
   exits, and plane-2 handling.
4. Curated, checked-in, noncommercial labels, categories, search aliases,
   descriptions, icons when project-owned, placement rules, and warnings.
5. A local runtime asset resolver that joins catalog IDs to decoded retail
   thumbnails without persisting those pixels in the public catalog.

The generator emits a source manifest containing input paths, hashes, generator
version, raw-entry counts, and unresolved joins. CI regenerates to a temporary
location and fails on a diff.

### 8.4 Catalog entry contract

Each entry declares as applicable:

- stable key and schema version;
- category/subcategory and sort rank;
- friendly name, concise description, search aliases;
- raw plane value or parameterized mapping;
- actor/class and sprite reference;
- thumbnail source rule;
- ordinary placement cell requirements;
- footprint/blocking or “unknown” metadata;
- directions and their exact raw mappings;
- stationary/patrol variants;
- minimum-rank variants;
- rotation/reflection maps;
- compound raw write set and erase behavior;
- topology preconditions and diagnostics;
- whether it is safe for new maps, imported-only, or Advanced;
- source evidence path/symbol and evidence grade;
- test vector ID.

No generated entry with an unresolved write mapping is selectable in the
normal palette.

### 8.5 Runtime thumbnail pipeline

1. Request a catalog entry at a logical display size and device scale.
2. Resolve the user's current data profile and asset fingerprint.
3. Decode bounded indexed pixels in a worker.
4. Apply the retail palette without altering source indices.
5. Return an immutable RGBA/index buffer tagged with data fingerprint and
   catalog key.
6. Construct a Qt image on the appropriate boundary and cache by key, asset
   hash, size, scale, and palette mode.

The memory cache is an LRU with a byte cap. An optional disk cache is private,
commercial-derived, versioned, outside project/release roots, permission
restricted, and clearable from Settings. Public tests use synthetic pixels.

### 8.6 Palette organization

Primary tabs:

- **Walls** — ordinary paintable wall materials.
- **Doors & Specials** — doors, access panels, elevators, switches,
  dispensers, mutable walls, exits, health chamber, and other compound tools.
- **Objects** — scenery, pickups, weapons, hazards, effects.
- **Enemies** — one card per enemy/boss with property controls.
- **Starts & Paths** — player start and patrol/direction markers.
- **Zones & Transporters** — area brush and paired channel tools.
- **Raw** — advanced values and unknown imported entries.

Every palette supports search by friendly name, raw ID, actor/class, source
name, and aliases. Filters include used-in-map, favorites, recent, difficulty,
blocking/nonblocking, and category. A broken thumbnail still shows a named
placeholder and diagnostic; it never hides the semantic item.

### 8.7 Favorites and recent items

Favorites and recent catalog keys are user preferences, not project content.
Missing keys remain as labeled unavailable entries after a catalog update so
the user can remove or migrate them deliberately. No retail thumbnails are
serialized into settings.

---

## 9. Desktop user interface

### 9.1 Main-window layout

The default layout is familiar to anyone who has used a drawing or level-editing
application:

```text
┌─ Menu ────────────────────────────────────────────────────────────────────────┐
│ Main toolbar: New Open Save │ Undo Redo │ tools │ Validate Test [Snapshot]   │
├────────────────────┬──────────────────────────────────┬───────────────────────┤
│ Palette            │ Map tabs / 2D canvas             │ Inspector             │
│ Search             │                                  │ Selection properties  │
│ category tabs      │ grid, textures, things, zones    │ Raw values (Advanced) │
│ thumbnail grid     │ selection and tool preview       │                       │
│ item description   │                                  │                       │
├────────────────────┴──────────────────────────────────┴───────────────────────┤
│ Problems / Test Log / [3D Snapshot] docks                                   │
├───────────────────────────────────────────────────────────────────────────────┤
│ tool · selected item · cell x,y · zoom · target MAPxx · dirty · E/W counts  │
└───────────────────────────────────────────────────────────────────────────────┘
```

All side/bottom panels are dockable and recoverable through **View → Reset
Layout**. The first-run layout must work at 1280×720 without hiding the canvas,
and must scale cleanly at 100%, 150%, and 200% DPI. At narrow widths, the
palette and inspector can become tabs rather than crushing the map.

Bracketed Snapshot surfaces exist only when E10 ships. If E10 is deferred, the
toolbar action, Test-menu action, dock, shortcut, and View entry are omitted
and Help/feature status says that Test Map is the available exact 3D preview;
the default UI never presents an apparently broken control.

### 9.2 Menus

#### File

- New Project / New Map
- Open Project
- Import from Corridor 7 Archive
- Open Recent
- Save / Save As / Save Copy
- Export Preview/Share WAD
- Export Complete Private Archive
- Project Properties
- Close Project / Exit

#### Edit

- Undo / Redo with the command description
- Cut / Copy / Paste / Paste in Place
- Duplicate / Delete
- Select All / Select None / Invert Selection
- Rotate clockwise/counterclockwise / Flip horizontal/vertical
- Find Raw Value / Replace through a previewed semantic operation
- Preferences

#### View

- Zoom controls / Fit Map / 100%
- Grid and coordinate labels
- Layer/overlay toggles
- Palette, Inspector, Problems, Test Log, and—only after E10 passes—the 3D
  Snapshot dock
- Minimap and full-map overview
- Reset Layout

#### Map

- Map Properties / Target Slot
- Validate Now
- Problems summary
- Resize (disabled or 64×64-only in version 1, with explanation)
- Statistics / Used Assets
- Raw Plane Inspector

#### Test

- Test Map
- Test Map As… target slot/rank/renderer profile
- Stop Running Test
- Open Test Log / Session Folder
- Capture 3D Snapshot (present only after E10 passes)
- Configure EC7Wolf and Data

#### Help

- Quick Start
- Tool and prefab reference
- Validation-code reference
- Keyboard shortcuts
- Commercial-content and sharing guide
- Open log/cache/project folders
- Report a Bug
- About EC7Edit / EC7Wolf version and lineage

### 9.3 Toolbar

The default toolbar contains only high-frequency actions. Special structures
live in palette tabs, not as dozens of cryptic icons. Buttons have text in
tooltips, accessible names, shortcuts, and checked state for the active tool.
The Test Map button is visually distinct and disabled with a textual reason
while export-blocking diagnostics exist or discovery is incomplete.

### 9.4 Project browser and map tabs

An imported archive browser groups maps as Campaign, Bonus, Unused, and
Network/Archive while retaining exact MAP number. Each row shows:

- MAP number and native header name;
- target/inherited display name when known from current MAPINFO;
- 2D schematic thumbnail generated locally;
- dimensions;
- validation summary;
- modified/clean state;
- imported source identity and whether this slot is part of the project.

Double-click opens a map tab. Tabs show target slot, friendly name, and dirty
marker. Closing a tab does not delete the map from the project. Multiple map
views may be open, but each `MapDocument` has one command history shared by its
views to prevent divergent edits.

### 9.5 New-project workflow

1. Choose **New Project**.
2. Choose a safe workspace path; reject game-data, package, cache, and source
   tree containment by default.
3. Choose **Blank 64×64**, **Closed room**, or a future project-owned template.
4. Choose target slot and working header name.
5. The template creates a complete solid outer border, area 256 on walkable
   cells, plane-1 empty value 18, plane-2 zero, and no commercial pixels.
6. If the template does not include a start, the Problems pane gives one
   obvious “Place player start” action.
7. Save the project and open the map at fit-to-window zoom.

No stock map is silently used as a template because that would copy commercial
map content.

### 9.6 Import-existing-level workflow

1. Choose **Import from Corridor 7 Archive**.
2. Select a configured data profile or a specific `MAPTEMP.CO7`.
3. The editor verifies and hashes the archive read-only in a worker.
4. An archive map chooser shows local schematic thumbnails and metadata without
   persisting them into a public artifact—60 entries for the supported retail
   archive, or the validated 1–100 count for another private/editor archive.
5. Select one or more maps and choose a separate project destination.
6. A commercial-content notice explains that the resulting project is local
   commercial-derived material and must not be distributed.
7. The editor copies decoded map values into a project, records source/archive
   provenance, and leaves the source hash unchanged.
8. Unknown values and plane-2 data appear as non-destructive informational
   diagnostics.

“Extract” in product language means this safe import into an editor project or
an explicit new private export. It never means editing in place.

### 9.7 Canvas rendering

The canvas uses a tile display size chosen from discrete or smooth zoom levels.
At each level it paints, in order:

1. Background/void.
2. Floor/zone color or simple floor fill.
3. Wall texture thumbnails or schematic solid colors.
4. Door, mutable-wall, transporter, exit, and special overlays.
5. Objects, enemies, starts, and path direction glyphs.
6. Grid, selection, tool preview, diagnostics, and cursor highlight.

Texture mode is the default once assets are available. Schematic mode remains
available for speed, accessibility, missing assets, and diagnostics. At very
small zoom, detailed sprites become category-colored glyphs; at large zoom,
thumbnail pixels remain crisp through nearest-neighbor scaling.

### 9.8 Layer and overlay controls

Layers are views, not independently serialized maps:

- Wall/material geometry.
- Doors and structural specials.
- Objects and pickups.
- Enemies and starts.
- Paths/directions.
- Sound/area zones.
- Transporter channels.
- Plane-2 raw values.
- Validation issues.
- Coordinates and grid.

Visibility never changes edit data. The active tool automatically reveals the
layers needed to understand its result. If the user hides the object layer and
chooses an enemy tool, the editor temporarily reveals or clearly warns rather
than allowing invisible placement.

### 9.9 Navigation

- Mouse wheel zooms around the cursor by default; a preference may reserve it
  for vertical scrolling.
- Middle-button drag or Space+left drag pans.
- Scrollbars remain available.
- **Home** fits the full map; **1** selects a readable 1:1 tile-thumbnail
  scale.
- The status bar shows the cursor's native `(x, y)` coordinate.
- A minimap shows viewport, selection, start, exit, and error locations.
- Clicking a Problem moves and zooms the canvas just enough to expose context.

Zoom must preserve the map coordinate under the cursor within rounding error.
Panning and zooming never modify selection or document state.

### 9.10 Selection model

The editor supports:

- one-cell click selection;
- drag rectangle;
- Shift-add and Ctrl-toggle;
- select all cells matching the eyedropped semantic item;
- select connected floor/zone region;
- multi-cell selection bounds for transforms and copy/paste.

Selection is view state and is not in the undo history. When a command deletes
or replaces selected content, the selection remains if its coordinates are
still valid. A map switch retains per-view selection but not an active drag.

### 9.11 Inspector

For one selected cell, the friendly inspector shows:

- wall/floor/zone meaning and thumbnail;
- thing/enemy/start/special meaning and thumbnail;
- properties such as direction, patrol, difficulty, channel, animation, and
  sight blocking;
- target-slot context and relevant warnings;
- placement/source description;
- exact plane-0, plane-1, and plane-2 values in a collapsed Advanced section.

For multiple selected cells, it shows shared values, mixed-value indicators,
counts, bounds, and only batch-safe changes. Editing a batch property previews
how many cells and planes will change.

Raw value editing requires Advanced mode, numeric range validation, a summary
of semantic interpretation if known, and confirmation if it would introduce an
unknown value. It remains undoable.

### 9.12 Problems pane

The Problems pane has filters for errors, warnings, information, current map,
all maps, selection, and diagnostic family. Each row shows severity icon and
text, stable code, map/cell, and an optional **Fix…** action. Severity is never
encoded by color alone.

Auto-fix is limited to deterministic, reversible actions with an explicit
preview—such as optionally placing the conventional transporter visual on an
otherwise valid endpoint. “Make level reachable” is never an automatic
mutation.

### 9.13 Test Log pane

The Test Log shows:

- session state: preparing, validating, exporting, starting, running, stopping,
  exited, failed;
- sanitized executable, working directory, and argument vector;
- project revision and export SHA-256;
- combined or separately filterable stdout/stderr;
- parsed positive evidence such as selected IWAD and entered map;
- parsed warnings/fatals/assertions with links when locations are known;
- start time, duration, exit code/signal, and session directory;
- buttons to stop, relaunch same revision, test latest, copy diagnostics, and
  open the session folder.

The log is capped in memory and streamed to a private session file with default
per-session byte and duration limits plus a global byte/age retention cap.
After the disk cap, the controller continues draining the child pipe without
blocking it but discards ordinary bytes, retains bounded fatal/event summaries,
and marks truncation explicitly. Line parsing has a maximum fragment length,
incrementally replaces invalid UTF-8, and cannot be defeated by a no-newline
flood. The beginning, bounded tail, and parsed fatal lines are preserved within
the cap.

### 9.14 Destructive-action UX

- Closing dirty work offers Save, Discard, or Cancel.
- “Discard” identifies the project/map and last autosave; it does not delete
  recovery silently.
- Overwriting an ordinary user export requires a standard confirmation.
- Full native archive export is visually separated and explains commercial
  content.
- Attempting to target the source archive, data root, repository, or release
  root is rejected in normal mode.
- An eventual expert override requires exact target display, verified backup,
  typed/secondary confirmation, and a post-write source-independent readback.

### 9.15 Accessibility and localization readiness

- Every icon-only control has a visible tooltip, accessible name, and keyboard
  route.
- Tab order follows the visual workflow.
- Canvas actions are mirrored in menus/palette lists/inspector so a keyboard or
  assistive-technology user is not forced to pixel-point.
- Focus is clearly visible; shortcuts do not steal text-entry keystrokes.
- Zone/channel/difficulty overlays combine color with hatch, shape, text, or
  icon.
- User-selectable UI scaling and thumbnail size supplement OS DPI.
- Screen-reader announcements summarize tool selection, placement success,
  invalid preview, undo/redo, and validation changes without narrating every
  mouse move.
- Strings live outside logic and support pluralization from the start, although
  shipping translations are not a first-release gate.
- Reduced-animation mode disables pulsing selections and animated thumbnails.

### 9.16 Built-in help

The Quick Start is short and task-oriented. Context help for every special tool
shows:

- what the feature does in Corridor 7;
- what cells/planes the tool will write, in optional Advanced details;
- a valid mini-diagram made from synthetic/project-owned art;
- common invalid arrangements and fixes;
- target-slot or rank caveats;
- a link to the full validation-code reference.

No help screenshot may accidentally become a committed retail-derived image.

---

## 10. Editing and command system

### 10.1 Tool contract

Every tool implements a common interaction contract:

- stable tool ID, cursor, label, help topic, and accepted catalog kinds;
- `preview(document snapshot, pointer state) → overlay + diagnostics`;
- `begin`, `update`, `commit`, and `cancel` gesture lifecycle;
- exact proposed write set across maps/planes/cells;
- conflict policy and replacement summary;
- one core command transaction on commit;
- no document change during preview;
- deterministic result independent of frame rate or pointer event frequency;
- keyboard-accessible equivalent.

Losing focus, switching maps, pressing Escape, or receiving a stale document
revision cancels an uncommitted gesture without leaving partial edits.

### 10.2 Pointer/select tool

Click selects the topmost visible semantic element at a cell. Repeated click or
a small chooser cycles wall/zone, special, thing, and raw layer when several
coexist. Drag selects a rectangle. Dragging a selected thing previews a move;
Alt-drag duplicates. Moves preserve raw tuples and validate the destination
before commit.

### 10.3 Eyedropper

Eyedropper samples the semantic item under the cursor and activates the matching
tool/palette entry. Holding a modifier or choosing from the layer popover
samples a specific plane. Unknown raw tuples select the Raw tool with exact
values; they are never coerced into the nearest known entry.

### 10.4 Wall brush

This is the product's simplest and most important interaction:

1. Choose a thumbnail in **Walls**.
2. The cursor becomes a one-cell wall preview.
3. Click or drag over cells.
4. The tool writes the selected ordinary plane-0 wall value.
5. If an existing plane-1 thing/special is incompatible, the preview shows the
   conflict and the selected replacement policy.
6. Mouse release creates one “Paint wall X across N cells” command.

Default conflict policy is **ask/preview**, not silent deletion. A preference
may choose “replace incompatible things” for an experienced user, but the
status/preview must show the count. Compatible wall modifiers are retained only
when the catalog explicitly says the new base wall supports them.

### 10.5 Floor/zone brush

Removing a wall is not `plane0 = 0`. Walkable cells need a valid area/zone.
The floor tool writes the currently selected zone, default 256, and resolves or
reports incompatible plane-1 content. A context action **Carve floor using
neighboring zone** chooses a unique adjacent zone or asks when ambiguous.

Zone painting offers a translucent overlay, flood fill, and “split at doors”
assistant. It changes only plane 0 on walkable cells and refuses to turn a
solid wall into floor unless the user invokes a carve operation.

### 10.6 Line, rectangle, and fill

- Line uses a documented integer-grid algorithm with a visible footprint.
- Rectangle supports outline or filled mode.
- Flood fill uses the selected semantic equivalence, not merely a matching
  thumbnail; ordinary walls, zones, and exact raw values are separate modes.
- Fill is bounded to map dimensions, iterative rather than recursive, and
  previews the cell count before a large mutation.
- Shift constrains direction; modifier conventions are shown in the status bar.

One line/rectangle/fill is one command regardless of cells changed.

### 10.7 Object and enemy placement

Choose an entry and click a destination. Native things are tile-centered, so
there is no misleading sub-tile positioning. The ghost shows footprint,
blocking, direction, pathing, and rank badge.

Before placement the core checks:

- coordinate is in bounds and not in the protected outer boundary when the
  thing requires floor;
- plane-0 cell type supports the item;
- plane-1 is empty 18 or replacement was explicitly selected;
- footprint and adjacent-space rules where known;
- direction/patrol/rank variant exists in the catalog;
- compound object prerequisites are satisfied.

Clicking an existing same-class enemy with a different property uses a clear
Replace operation, not an invisible numeric tweak. The inspector can batch
change direction, patrol, or rank for a compatible multi-selection.

### 10.8 Eraser

The eraser has a visible target layer:

- **Thing eraser** writes plane-1 empty value 18 and leaves geometry intact.
- **Wall eraser/carve floor** writes a chosen or inferred valid zone and handles
  incompatible markers explicitly.
- **Special eraser** removes the full compound feature and restores values
  according to its catalog erase rule.
- **All-layers eraser** is Advanced, previews exact results, and still produces
  a structurally valid base cell rather than zeroing all planes.

Backspace/Delete applies the appropriate operation to selection and provides a
summary when layers are mixed.

### 10.9 Stamp and prefab tool

A prefab is a parameterized, rotatable set of preconditions and writes—not a
copied retail map fragment. The preview shows:

- footprint and anchor;
- every affected cell;
- new walls/zones/things/specials;
- cells to be replaced;
- inferred orientation/channel;
- errors and warnings.

Version-1 built-in prefabs include paired transporters, floor exit with an
optional/default visual,
ordinary/locked door arrangements, ordinary/secret elevator, and health
chamber if its exact structure passes E6 evidence. User-defined prefabs are
deferred until a secure, non-scriptable schema and commercial-content warning
are designed.

### 10.10 Command representation

A core edit command contains:

- command ID and human description;
- project/map UUID and base document revision;
- deterministic ordered list of `(plane, index, before, after)` cell diffs;
- optional before/after map metadata diffs;
- catalog/tool identity and parameters for diagnostics only;
- timestamp for UI grouping, never for semantic output.

Applying verifies every current value equals `before`; undo verifies it equals
`after`. A mismatch is an internal consistency failure, not permission to
overwrite newer work. Commands cannot span projects. Multi-map commands are
allowed only when an explicitly designed feature needs them.

### 10.11 Gesture coalescing

During a drag, the transaction builder stores each cell's first `before` and
latest `after`. Revisiting a cell does not create duplicate history. Cells
whose final value equals their first value drop out. Pointer sampling fills
between event positions, so a fast drag cannot leave random holes.

The document is not exposed in a half-committed state. The GUI may render a
gesture overlay; mouse release validates and applies the single transaction.

### 10.12 Undo/redo policy

- Default retention caps are 500 recent commands and 128 MiB of diff memory;
  reaching either cap evicts whole oldest commands until both caps are met.
  The UI reports history truncation and allows bounded configuration; this is
  a retention target, not a contradictory guarantee that 500 always fit.
- Saved state is a revision marker, not an assumption that undo stack index
  zero is clean.
- Undo after save makes the document dirty unless it returns exactly to the
  saved revision/content digest.
- New edits after undo discard the redo branch with ordinary warning-free
  editor semantics.
- Imports, migrations, and opening a project establish a baseline; they are not
  giant user undo commands.
- Export and playtest do not enter undo history because they do not mutate the
  document.
- Validation auto-fixes are ordinary named commands and undoable.

### 10.13 Copy and clipboard format

The internal clipboard payload is versioned JSON with:

- synthetic/local marker and schema version;
- source dimensions and selection mask;
- exact included plane values relative to an origin;
- semantic/catalog hints for transforms;
- no source absolute path, retail pixels, scripts, or executable content.

Copy can target visible layers or all raw planes; the UI states which. Pasting
from an untrusted external clipboard is size/schema bounded and never causes
file/network access. Unknown raw values are preserved and warned.

Because copied data from a retail level remains commercial-derived, **Copy as
text/file** carries the same sharing notice as an imported project. System
clipboard history is outside editor control; the manual notes this.

### 10.14 Rotation and reflection

Geometric transforms move selected cells and remap directional semantics:

- player starts;
- enemy facing and pathing variants;
- patrol markers;
- direction-dependent wall or special parameters;
- prefab orientation and anchors.

The catalog provides exact mapping tables. If any selected known directional
entry lacks a valid transform, preview blocks the transform or offers to leave
that entry unchanged with explicit confirmation. Numeric-offset guessing is
forbidden. Plane-2 values move spatially but are not semantically remapped.

### 10.15 Multi-layer conflicts

Each command declares whether it:

- preserves another plane value;
- requires another plane value;
- replaces an incompatible value;
- removes a compound feature through its erase rule;
- is invalid in the current combination.

Conflict UI uses a compact summary:

```text
Paint 14 wall cells
  11 empty/floor cells replaced
   2 ordinary objects would be removed
   1 transporter endpoint cannot be partially replaced
```

The user can cancel, exclude conflicts, or apply an allowed compound
replacement. There is no blanket “yes to all invalid raw combinations.”

### 10.16 Find, replace, and statistics

Find supports catalog name, class, raw plane/value, diagnostic code, zone,
channel, rank, and map slot. Replace always previews the exact affected cells
and uses semantic mappings. Statistics show counts for walls, zones, objects,
enemies by rank, starts, exits, keys/doors, transporters, unknown values, and
plane-2 values. Reports default to metadata/counts, not full commercial plane
dumps.

---

## 11. Corridor 7 semantic tools

### 11.1 Ordinary walls and functional wall art

The Walls palette lists only direct paintable material mappings. A functional
wall page may still appear there with a badge and explanation, but selecting
its interactive behavior routes through Doors & Specials. The catalog must
cover at least known access/alarm panels, energized walls, elevator panels,
health/ammo/visor dispensers, and other source-defined interactions.

The inspector distinguishes:

- **Appearance:** wall page and decoded thumbnail.
- **Native map value:** exact plane-0 word.
- **Behavior:** source-defined activation/hazard/exit semantics.
- **Modifier:** compatible plane-1 marker, if present.

### 11.2 Doors

Door types include normal, red-card, blue-card, and source-defined special
variant. Placement flow:

1. Hover target cell.
2. Inspect north/south and east/west walkable approaches.
3. Infer engine axis using the current source-equivalent rule.
4. Draw door slab orientation, use sides, and optional jamb preview.
5. Warn on a tie, corner, one-sided approach, adjacent door, outer boundary,
   incompatible modifier, or ambiguous zones.
6. Commit door and optional explicitly chosen jamb edits as one command.

The door raw code does not change merely because the visual axis changes;
topology is authoritative. A Rotate Door action either adjusts surrounding
geometry through a previewed compound command or explains that orientation is
not a stored property.

### 11.3 Keys and access logic

Locked doors receive key-type badges. Validation models reachable state as
location plus obtained access items for red/blue doors where current gameplay
rules are established. It reports:

- locked door with no matching key in the map;
- key that is reachable only beyond every matching locked door;
- start-to-exit route blocked by unavailable access;
- optional keys or locked bonus areas as warnings, not false hard failures.

Rank/clearance interactions that are not ordinary carried keys remain separate
catalog semantics and source-backed validation rules.

### 11.4 Push/moving walls

The tool chooses ordinary or secret-counting behavior and direction where the
native/runtime representation supports it. Preview checks destination runway,
wall/base compatibility, neighboring floor zones, triggers, and objects in the
movement path. The validator distinguishes a structurally encoded pushwall from
a likely usable one; dynamic gameplay interactions may remain warnings pending
playtest.

### 11.5 Masked walls

Masked wall placement combines a base plane-0 wall with plane-1 marker 104 or
105 according to desired sight behavior. The asset decoder can inspect indexed
transparency for preview, but source rules—not thumbnail appearance alone—own
collision/sight semantics. UI options:

- Blocks movement and sight.
- Blocks movement but permits sight, where marker 105 establishes that
  behavior.

The exact labels are verified against runtime tests before release. Imported
unusual combinations remain preserved with warnings.

### 11.6 Animated/retractable walls

The tool exposes only proven states and frame rules. It previews the four-frame
sequence from local assets, indicates collision/open state, and writes markers
86–88, 106, or 107 only through mapped operations. Validation checks that the
base page has required consecutive frames and the marker/base combination is
known. Reduced-animation accessibility mode displays a static strip or frame
number.

### 11.7 Elevators and exits

Separate entries cover:

- ordinary wall elevator/level exit;
- secret/bonus elevator marker over its required base wall;
- floor exit 287, with visual actor 322 added by default but not required for
  the trigger;
- boss/exit vortex 268 and MAP40-specific context;
- any rank-gated or source-defined exit panel.

Every exit preview shows target-slot consequences. The validator checks at
least one valid completion mechanism for a single-player profile and reports
multiple/optional exits without assuming they are wrong.

### 11.8 Transporters

Transporter channels are displayed as A–H plus raw 279–286. Placement modes:

- **Place pair:** click first endpoint, then second; Escape cancels both; one
  command writes both channel floors and, by default, field visuals.
- **Add/replace endpoint:** Advanced repair mode with channel count preview.
- **Select partner:** navigates between endpoints.
- **Reassign channel:** atomically changes both ends when unambiguous.

Endpoint cells must be walkable transporter floors. Plane-1 field/visual 321 is
the friendly prefab default, but the plane-0 pair owns teleport behavior; a
missing or orphan visual is a warning. Channel colors also have letters/hatches
for accessibility.

### 11.9 Zones and sound areas

Zone overlay assigns a stable distinguishable color/hatch to raw 256–277 and a
distinct style to 278. Tools include brush, flood fill, select region, merge,
and split-at-selected-doors assistant. Validation reports:

- reachable floor outside known zones;
- a door with the same zone on both sides as informational/suspicious, not
  universally invalid;
- an excessive fragmented zone;
- use of 278 without understood intent;
- isolated zone islands and unreachable areas.

No automatic “optimize zones” rewrites an imported map.

### 11.10 Starts

The Start palette presents one player-start item and a facing control. The
single-player validation profile requires exactly one. Placement of another
offers **Move existing start here** as the safe default rather than creating a
second accidentally. The start must be on a legal, unblocked floor cell with
sufficient immediate space.

Future multiplayer start/player-class semantics require their own source audit;
they are not inferred from single-player codes.

### 11.11 Objects, pickups, and hazards

Objects are categorized by player intent: health, access/key, weapon, ammo,
power-up, scenery, blocking scenery, hazard, effect, and Advanced/unknown.
Cards show blocking/collectible/hazard badges when source-established. The
editor validates placement geometry and obvious duplicates/conflicts but does
not claim to balance resources.

### 11.12 Enemies and difficulty/rank

An enemy card is independent of its raw variants. The property panel selects:

- class/name;
- facing among supported directions;
- stationary versus patrol/pathing;
- one of the three native minimum-rank bands defined by XLAT: **All ranks**,
  **Captain+**, or **Major+**;
- source-supported special behavior, if any.

The canvas badge makes minimum rank visible, and a rank-preview filter can show
what spawns at each chosen difficulty. Hidden-by-rank things are dimmed rather
than removed from the document. A raw import variant that cannot be joined to a
friendly enemy remains a selectable unknown entry.

The five playable rank choices remain Corporal, Lieutenant, Captain, Major,
and President, but they are not five independently encodable spawn bands:
Corporal/Lieutenant share the lower authored set and Major/President share the
upper filter. President also enables fast monsters and randomizes authored
monster and pickup locations by category at map load. The 2D rank preview must
therefore label President placement as runtime-randomized rather than promise
the exact authored coordinates shown on the canvas.

### 11.13 Patrol markers and paths

The path overlay displays directional markers and likely transitions. The
editor offers marker placement/rotation and warns about loops, dead ends,
markers under incompatible geometry, and enemies marked to patrol without a
plausible route. Because runtime AI can react dynamically, this is diagnostic,
not a complete simulation.

### 11.14 Health chamber and other composite prefabs

The health chamber's runtime behavior depends on multiple wall cells and a
walkable one-cell chamber rather than one object code. Milestone E6 must freeze
its exact panel, door, rear wall, approach, mutable state, and rotation rules
from current source and tests before enabling the prefab. Until then, imported
structures remain editable as raw constituent cells with a recognition badge.

The same rule applies to any future prefab: recognition may precede creation,
but creation is enabled only with exact write/erase/rotate tests.

### 11.15 Target-slot profiles

The map properties panel offers profiles:

- **Stock slot behavior:** selected MAP01–MAP60 inherits current MAPINFO.
- **Generic single-player test:** uses a verified ordinary slot, initially
  MAP01, while retaining the project's intended slot as metadata.
- **Exact intended slot test:** launches the selected stock slot and warns
  about special progression.
- **Custom campaign:** unavailable until the MAPINFO milestone lands.

Export diagnostics are evaluated against the chosen output profile. A map can
be structurally valid as MAP01 and semantically suspicious as MAP40.

---

## 12. Validation and preflight

### 12.1 Diagnostic model

Each diagnostic is structured data:

```text
code          stable ASCII identifier, e.g. C7E-DOOR-003
severity      error | warning | information
scope         project | archive | map | region | cell | export | runtime
map_uuid      optional
locations     zero or more coordinates/regions
summary       one sentence
explanation   source-backed reason
suggestion    concrete next action
fix           optional deterministic command factory
evidence      rule/catalog/source revision
revision      document revision validated
profile       target slot/rank/export profile
```

Messages may be localized; codes and fields are stable. Selecting a location
does not mutate the map. Results from older revisions are visibly stale and do
not block current export once a current synchronous preflight completes.

### 12.2 Severity policy

**Errors** mean the selected export cannot be parsed safely, violates a hard
native bound, would create a known invalid structure, lacks a required launch
condition, or introduces an unsupported value. Export/Test Map is blocked.

**Warnings** mean the map is legal or preserved but suspicious, possibly
unreachable, slot-sensitive, unknown, or dependent on behavior not completely
proven. Export remains available after review.

**Information** explains inherited behavior, preservation, statistics, or
opportunities without implying failure.

An unchanged imported unknown is a warning/information. Introducing a new
unknown through normal tools is impossible; introducing it through Raw mode is
an error until explicitly acknowledged under an Advanced export policy. Even
then, the native range and structural rules remain hard.

### 12.3 Validation layers

1. **Schema safety:** types, sizes, names, dimensions, array lengths, value
   bounds, IDs, paths, and versions.
2. **Native format:** plane count, encoded length bounds, archive count,
   deterministic encode/readback, WAD/lump rules.
3. **Cell semantics:** known raw mappings, plane conflicts, floor/wall/thing
   compatibility, outer boundary.
4. **Compound structures:** door topology, mutable walls, transporters,
   elevators, exits, prefabs.
5. **Topology:** reachable cells, zones, keys/doors, start, exit paths, isolated
   objects, patrol hints.
6. **Target-slot context:** MAPINFO, special slots, rank spawn filters,
   campaign/bonus behavior.
7. **Export/launch:** path safety, data discovery, output classification,
   current preflight, session creation, executable identity.
8. **Engine load check:** optional/required gate outside continuous editing,
   parses real engine evidence without assuming silence is success.

### 12.4 Hard structural errors

At minimum, normal single-player export rejects:

- unsupported project schema or failed migration;
- width or height outside the verified engine/format range;
- `width × height` overflow or wrong plane lengths;
- raw value outside 0–65535;
- a newly created or deliberately renamed native name that cannot be encoded
  by the canonical 15-byte ASCII-plus-NUL policy, or a mismatched text/raw
  schema pair; an unchanged imported exact 16-byte field remains exportable;
- RLEW compressed plane exceeding the 16-bit length field for full-archive
  export;
- more than the verified archive map limit;
- malformed source archive needed for a private full-archive export;
- missing current target slot or invalid `MAPxx` lump name;
- WAD/PLANES size or offset overflow;
- missing or multiple single-player starts;
- a non-solid/open outer boundary under the supported safety contract;
- transporter channel with a count other than two;
- two incompatible meanings competing for the one plane-1 word;
- compound feature whose required base/modifier cells are absent;
- an editor-created unknown raw mapping without Advanced acknowledgment;
- output path resolving to retail source, data root, application source root,
  or protected release root;
- preflight/output readback semantic mismatch.

The boundary rule is conservative because runtime cell-neighbor operations can
assume a valid bounded map. Any future relaxation requires a targeted engine
test, not a checkbox named “ignore safety.”

### 12.5 Warnings

At minimum, warn about:

- imported unknown raw values preserved unchanged;
- any raw edit or newly introduced nonzero value in plane 2; unchanged imported
  nonzero data is information showing that it was preserved, not a warning;
- suspicious door axis, tie, one-sided approach, or same-area relationship;
- unreachable cells, enemies, pickups, keys, exits, or large regions;
- no start-to-exit route under the advisory model;
- locked door without an apparently reachable key, or key behind all matching
  doors;
- multiple completion mechanisms or optional unreachable secrets;
- transporter or floor-exit trigger missing its conventional visual, or an
  orphan visual without its corresponding plane-0 behavior;
- mutable wall without plausible movement space;
- animation marker/base frame mismatch;
- patrol enemy without a plausible marker route;
- isolated or excessively fragmented zones;
- use of ambush zone 278 without clear source-backed context;
- object on a suspicious but technically allowed cell;
- target MAP30/MAP40 or bonus/network slot behavior;
- native header name hidden by MAPINFO display name;
- imported dimensions other than the tested 64×64 authoring target;
- source archive changed since import;
- edited retail-derived content selected for an apparently public location;
- test save hash differs from the current export;
- approximate layout preview diverges from a feature it does not model.

### 12.6 Reachability model

The first graph model uses the local-workspace
`../tools/python/validate_corridor7_campaign.py` as evidence after E0 provenance
review and is upgraded or independently implemented as reusable rules. Nodes
are walkable cells plus a bounded key/
access state. Edges represent cardinal walking, passable/openable doors, and
paired transporters. Static blockers, wall state, and special exits are modeled
only where current source establishes them.

Outputs include:

- cells reachable from the player start;
- items/keys reachable by access state;
- doors that become traversable;
- completion mechanisms reachable in at least one modeled state;
- disconnected regions and likely gating cycles.

Limitations are explicit: enemy combat, ammo/health sufficiency, timed walls,
dynamic actor movement, secret discovery, rank rules, and every trigger
sequence are not a formal proof. The validator may say “no route found by the
structural model,” never “the level is impossible” without stronger evidence.

### 12.7 Incremental versus full validation

Cheap local rules run after each command for affected cells and neighbors.
Whole-map topology runs after a short debounce on an immutable revision in a
worker. Export always runs a synchronous/current full preflight in the core,
even if the Problems pane appears green. A performance budget and cancellation
prevent queued obsolete validations.

### 12.8 Validation profiles

Profiles are explicit inputs, not hidden global rules:

- `single_player_stock_slot`
- `single_player_generic_test`
- `private_archive_preservation`
- `preview_wad`
- future `multiplayer_map` after source audit
- future `custom_campaign`

An imported network/archive map is not damaged merely because a single-player
profile reports warnings. Export asks which supported profile the user intends.

### 12.9 Engine preflight

An optional **Validate with EC7Wolf** action exports a private preview and runs
a bounded engine load/start check. Success requires positive evidence that:

- the intended Corridor 7 data set was selected;
- the later preview file was loaded;
- the target `MAPxx` was found and parsed;
- game initialization entered that map.

A timeout is accepted only after the expected positive entry evidence, because
interactive gameplay naturally keeps running. Any parser error, fatal, assert,
sanitizer marker, wrong map, wrong IWAD, or early nonzero exit fails.

### 12.10 Validation-code catalog

Every code has documentation, severity rationale, source/evidence, example,
and remediation. The initial namespace:

| Prefix | Family |
| --- | --- |
| `C7E-SCHEMA` | project/schema/input safety |
| `C7E-NATIVE` | TED5/RLEW/native constraints |
| `C7E-WAD` | preview WAD/PLANES constraints |
| `C7E-CELL` | raw cell/layer compatibility |
| `C7E-BOUNDARY` | outer bounds and dimensions |
| `C7E-DOOR` | door/access topology |
| `C7E-WALL` | moving/masked/animated wall rules |
| `C7E-ZONE` | sound/area zones |
| `C7E-WARP` | transporter channels |
| `C7E-START` | player starts |
| `C7E-EXIT` | completion structures and slot context |
| `C7E-THING` | object/enemy placement |
| `C7E-ROUTE` | advisory reachability |
| `C7E-SOURCE` | source archive/provenance |
| `C7E-EXPORT` | paths, output, readback |
| `C7E-ENGINE` | discovery, launch, runtime evidence |
| `C7E-LICENSE` | commercial-content boundary |

---

## 13. Existing-level import and round-trip policy

### 13.1 Import transaction

Import is a read-only transaction:

1. Canonicalize and policy-check source path.
2. Open without write intent and record file identity/hash.
3. Parse with bounded strict codec into immutable archive data.
4. Validate every record and RLEW stream.
5. Build metadata and local thumbnails in memory/private cache.
6. Let the user choose maps and project destination.
7. Serialize project to a new atomic destination.
8. Reparse project and compare every imported header/plane word.
9. Rehash source and require equality.
10. Record provenance and display the commercial-derived-content notice.

Failure at any step leaves the source and destination unchanged except for an
application-owned temporary file that is safely cleaned or recoverable.

### 13.2 Losslessness contract

For an imported map with no edits:

- width, height, native name bytes/meaning, and all three plane arrays are
  preserved;
- unknown and nonzero plane-2 values are identical;
- target slot defaults to source archive position;
- project save/reopen is exact at the canonical model level;
- preview WAD readback is exact at the canonical model level;
- full native archive decoded readback is exact for every slot.

Byte-identical native re-encoding is desirable when the original bytes are
retained and no changes occurred, but it is not the fundamental semantic
contract: valid RLEW encoders may choose different equivalent runs. The safest
implementation may copy an unchanged original archive byte-for-byte for a
no-edit Save Copy and rebuild only when a map changed. Both paths require tests
and clear provenance.

### 13.3 Preserve-versus-edit policy

Imported values are tagged through provenance, not by altering the raw arrays.
When a user edits a cell, the command records exact old/new values. Validation
can therefore distinguish:

- unknown value preserved from source;
- known value changed through a semantic tool;
- unknown value explicitly introduced through Advanced raw editing.

This distinction informs warnings but never makes undo/history nondeterministic.

### 13.4 Multi-map projects

A project may contain one or many maps. Importing the entire archive is useful
for browsing and private full-archive export, but one-map projects remain the
simple default. Target-slot uniqueness is required within one normal export
set; two project maps may intentionally share a target slot only in separate
export profiles.

### 13.5 Reimport and rebase

If the source archive hash changes, the editor does not silently merge. A later
rebase tool may compare per-map canonical hashes and offer:

- retain project map;
- replace with newly imported map;
- duplicate both;
- cell/plane diff view.

Automatic three-way merges of map planes are out of scope until a dedicated
visual conflict UX exists.

### 13.6 Diff view

A useful post-MVP feature compares two map documents with:

- added/removed/changed cells by plane;
- friendly semantic before/after;
- metadata/slot differences;
- selection filters and synchronized pan/zoom;
- counts without exposing full data in public logs.

It must not be required for initial safe import/export.

---

## 14. Save, export, and mod-package contract

### 14.1 “Save” versus “Export”

- **Save** writes the editable `.ec7project` document.
- **Export Preview/Share WAD** writes one or more validated `MAPxx`/`PLANES`
  pairs for EC7Wolf.
- **Export Complete Private Archive** writes a new native `MAPTEMP.CO7` with an
  explicit commercial-content warning.
- **Test Map** creates a private disposable preview WAD automatically.

The UI never uses “Save” to mean “overwrite the retail archive.”

### 14.2 Deterministic preview WAD

For each selected target map, the exporter:

1. Takes an immutable current document snapshot.
2. Runs current full validation for `preview_wad` and target-slot profile.
3. Builds the exact WDC3.1 `PLANES` bytes from raw arrays.
4. Writes a zero-length `MAPxx` marker immediately followed by `PLANES`.
5. Writes the classic `PWAD` identifier/header/directory with checked 32-bit
   bounds, canonical lump order, uppercase eight-byte names, and no duplicate
   unintended names.
6. Writes no retail images, palette, actors, sounds, or other base resources.
7. Flushes, reopens, reparses the WAD and PLANES, and compares canonical map
   content.
8. Atomically replaces the user-selected output or promotes a private session
   temp file.
9. Records SHA-256, project revision, target slots, catalog/source version, and
   commercial classification in a sidecar only when appropriate.

Equal input and exporter version produce byte-identical WAD output.

### 14.3 One-map default

The normal export dialog defaults to the current map only. A multi-map WAD is
permitted when every target slot is unique and each marker is immediately
followed by its PLANES. The dialog summarizes exactly which `MAPxx` values will
be overridden at runtime.

### 14.4 Share classification

Before normal export the user chooses or confirms:

- **My original map:** eligible for sharing if it embeds no retail content.
- **Edited/imported retail map:** private commercial-derived output; show a
  strong do-not-redistribute notice.
- **Mixed/unknown provenance:** treat as private until resolved.

This is not a digital-rights-management system; it is an honest safety guard
and release policy. Metadata cannot magically make copied retail plane data
public.

### 14.5 Full private archive export

The advanced exporter requires an archive base or an explicitly ordered set of
maps. It:

- verifies source fingerprint/provenance;
- treats physical record order as the map number—record 1 is MAP01, record 17
  is MAP17—because the native record contains no independent slot field;
- requires target-slot/order equality and rejects a sparse archive unless every
  preceding gap can be filled from a verified base archive (a one-record native
  file “targeting MAP17” would actually load as MAP01);
- preserves untouched maps and every plane;
- enforces 100-map, dimension, name, RLEW, offset, and 16-bit length bounds;
- chooses deterministic compression for modified maps;
- defaults the engine-targeted basename to `MAPTEMP.CO7` and requires a
  basename beginning `MAPTEMP` for this self-contained TED5 form. `GAMEMAPS`
  selects the different separate-`MAPHEAD`/Carmack-compressed family in the
  current loader and is outside this exporter; any other parseable filename is
  rejected or labeled editor-only rather than promised to work with `--file`;
- writes to a new path outside protected roots;
- reparses the complete output and compares every map;
- rehashes the source unchanged;
- labels output as private commercial-derived content.

Direct overwrite of the selected retail archive is not needed to meet the
product promise. If implemented later, it is a separate advanced feature with
a verified backup and recovery test, never an incidental `Save` behavior.

### 14.6 MAPINFO/mod metadata

Version 1 relies on the base game's existing MAPINFO for stock target slots. A
custom map pack may eventually need a metadata-only MAPINFO override for names,
routing, music, and colors. That feature waits for a spike proving:

- exact supported syntax and lump naming;
- load-order interactions with the base pk3 and preview WAD;
- safe escaping and bounded values;
- campaign/secret/endgame behavior;
- no retail content copied into generated metadata;
- round-trip/project schema and engine-load tests.

Until then, the export dialog plainly says the selected stock slot controls
inherited presentation and progression.

### 14.7 Output paths and names

- Use native platform file dialogs and absolute canonical paths internally.
- Default user exports beside the project or in a configured user export root.
- Default automatic previews under a private temporary/session root.
- Reject empty, directory, device, FIFO/socket, path-traversal, symlink escape,
  game-data, source, and release-root targets.
- Sanitize suggested filenames but never silently change a chosen final path.
- Do not use map/header text directly as a path without strict normalization.

### 14.8 Post-export report

The success panel shows:

- output path and size;
- SHA-256;
- map marker(s), dimensions, and project revision;
- validation summary;
- private/share classification;
- source archive unchanged status when applicable;
- **Test**, **Open folder**, and **Copy technical details** actions.

No report includes full plane arrays or retail thumbnail pixels by default.

---

## 15. One-click EC7Wolf playtesting

### 15.1 User contract

Pressing **Test Map** performs one understandable operation: validate the
current map, export a disposable override, launch the configured EC7Wolf into
that exact target, and show what happened. It never asks the user to copy a
file into the game directory or open a terminal.

### 15.2 Test sequence

1. Freeze current map/project revision R.
2. Run full `preview_wad` and intended-slot preflight.
3. If errors exist, focus the Problems pane; do not create/launch a stale map.
4. Create a restrictive per-session directory outside game/release roots.
5. Export and read back `editor-preview.wad`.
6. Create isolated config path and save directory.
7. Build a structured launch plan and display a sanitized summary.
8. Start the child with argument-vector APIs and the chosen data-directory cwd.
9. Stream logs and parse positive/fatal evidence.
10. Mark Running only after successful process start; mark **Entered MAPxx**
    only after positive engine evidence.
11. Leave the editor responsive while the game runs.
12. On exit, show status and retain bounded diagnostics according to policy.

### 15.3 Canonical direct launch plan

```python
LaunchPlan(
    executable="/absolute/path/to/ec7wolf",
    cwd="/absolute/path/to/Corridor7/data",
    argv=[
        "--data", "CO7",
        "--file", "/absolute/private/session/editor-preview.wad",
        "--config", "/absolute/private/session/playtest.cfg",
        "--savedir", "/absolute/private/session/saves",
        "--editor-protocol", "1",
        "--editor-session", "0123456789abcdef0123456789abcdef",
        "--nowait",
        "--tedlevel", "MAP01",
        "--skill", "2",
    ],
    environment_overrides={...bounded documented overrides...},
)
```

This is conceptual Python, not permission to use a shell. On Qt, pass program
and argument list separately to `QProcess` and call `setWorkingDirectory`.

### 15.4 Rank selection

The UI uses Corridor 7's five friendly rank names and passes the verified
1-based numeric `--skill` value. It remembers a per-project test preference
without changing map content. The selected rank filter also updates the 2D
preview so users know which enemies/items are eligible to spawn. President
shares Major's spawn filter but enables fast monsters and runtime-randomizes
monster and pickup locations by category, so its preview is explicitly
nondeterministic in position.

### 15.5 Target slot

Default test uses the map's intended slot so slot-dependent behavior is
visible. **Test As…** can temporarily choose a generic verified slot such as
MAP01 for geometry debugging. The preview WAD marker and `--tedlevel` must
match. The UI prominently shows when intended and test slots differ.

### 15.6 Engine and launcher modes

The cross-platform version-1 contract requires the direct EC7Wolf executable.
The editor supplies cwd, `--data`, config/save paths, and every argument
without a shell. This works for both a source build and the executable inside
the private packaged directory.

An optional launcher adapter may ship later only for one specifically audited
launcher whose cwd, argument forwarding, renderer, config, and save behavior
passes hostile-path integration tests. The current POSIX private-package
`run-corridor7.sh` is eligible for that audit and is invoked directly through
its shebang/argv, never through a constructed shell command. Arbitrary scripts,
the installed launcher with different environment semantics, and Windows
`.cmd` forwarding are not supported in version 1; `.cmd` requires `cmd.exe`
and cannot satisfy the no-shell hostile-path contract without a native helper.
Profile discovery never generalizes behavior from one launcher to another.

### 15.7 Process lifecycle

- If no game is running, Test starts it.
- If the current revision is already running, Test focuses the editor's Test
  Log/status and offers relaunch. Platform game-window focus is optional and
  exists only behind a tested adapter.
- If an older revision is running, Test offers **Stop and test latest** as the
  default and identifies both revisions.
- Stop first requests termination, clearly warning that the current engine has
  no proven cooperative editor-quit protocol and isolated playtest progress or
  config flush may be lost. It waits a short bounded interval while keeping the
  UI responsive, then offers force termination.
- A captured `QProcess` child is never detached after launch. Editor exit with
  a managed game running offers **Stop game and exit** or **Cancel exit**; it
  does not claim it can safely leave the captured child and log pipes running.
  A future broker or detached-from-start/log-to-file design requires its own
  lifecycle gate.
- A crashed editor cleans orphan sessions conservatively on next start only
  after confirming no owning PID/process identity remains.

### 15.8 Isolated config and savegames

Playtests must not alter the user's ordinary game settings or saves. The editor
creates a stable per-project test config or seeds a minimal known-safe config,
and a per-export-hash save location. Geometry-changing exports do not reuse old
saves by default. An Advanced preference may retain hash-keyed test saves with
a size cap.

### 15.9 Renderer and window preferences

The test profile may choose software/OpenGL only using current verified CLI
semantics. A future audited launcher adapter does not receive contradictory
first-wins options.
Windowed testing is the usability default if the engine has a stable supported
configuration path; the implementation must test rather than invent flags.

### 15.10 Log interpretation

Success is not “process still alive.” Parse current engine output for:

- IWAD/data selection;
- extra preview resource load;
- target-map lookup/load;
- map entry/start evidence;
- parser and RLEW failures;
- fatal/error/assert/sanitizer markers;
- renderer/audio initialization problems;
- save/config path failures.

Patterns are versioned and tested against captured synthetic log fixtures. Raw
output remains available when a parser does not recognize a new line.

Ordinary `printf` output through a `QProcess` pipe is buffered and cannot be
the positive version-1 contract. E9 adds an opt-in versioned editor protocol,
advertised by a capability probe, that emits bounded machine-readable events
for data selection, preview-resource acceptance, target-map load, actual
gameplay entry, fatal startup, and session result. `PREVIEW_LOADED` may be
emitted after `GameMap::LoadMap`; it is not `MAP_ENTERED`. The authoritative
entry event is emitted only after `SetupGameLevel`, thing spawning, player-start
validation/setup, and the play loop's verified ready point succeed. Every event
is immediately flushed explicitly by the engine. The GUI may still parse human
logs for context, but it marks **Entered MAPxx** only from the matching
session/version `MAP_ENTERED`. Hosted tests prove the event arrives while the
child remains alive through ordinary pipes;
Linux-only `stdbuf` and a platform-specific PTY are not production fixes.

E9 freezes the wire form as one bounded UTF-8 line per event, prefixed
`EC7EDIT/1 ` and followed by compact JSON with an event sequence, event name,
random 128-bit session nonce, target map, and only event-specific bounded
fields. The editor passes the nonce as a dedicated argument, accepts monotonic
events only from that child/session, and never treats the nonce as a secret.
Unknown protocol versions/events are shown but do not satisfy a positive gate;
paths and human messages remain escaped untrusted text.

The matching early `--editor-capabilities` probe prints one flushed bounded
`EC7EDIT_CAPABILITIES/1` JSON line and exits before game-data/resource startup.
It reports product/lineage plus supported editor-protocol, renderer-option,
preview-WAD, and optional snapshot capabilities. The production launch uses
the exact `--editor-protocol 1 --editor-session NONCE` pair shown above; an
engine that lacks or contradicts the probe remains usable manually but is not
declared one-click compatible.

### 15.11 Environment

Ordinary interactive launch builds a documented platform allow-list rather than
copying the whole editor environment. E9 freezes exact names, including only
required locale/time-zone variables; Windows system/session variables; and on
Linux the selected display/session/runtime variables (`DISPLAY` or
`WAYLAND_DISPLAY`, `XAUTHORITY`, `XDG_RUNTIME_DIR`) plus reviewed graphics/audio
driver needs. Dynamic-loader injection (`LD_PRELOAD`, unreviewed
`LD_LIBRARY_PATH`, `DYLD_*`), Python variables, credentials, tokens, and
unrelated app state are dropped. A trusted development-build library-path
exception is explicit, visible, path-validated, and unavailable to shared
projects. Automated gates may add `SDL_AUDIODRIVER=dummy`, Xvfb, and the
existing tested video-driver convention. User-controlled arbitrary environment
injection is not a first-release UI feature.

### 15.12 Failure messages

Examples of actionable outcomes:

- “EC7Wolf executable no longer exists. Choose it in Test Settings.”
- “Corridor 7 data was not recognized in this working directory; `--data CO7`
  selects an extension, not a directory.”
- “Preview WAD was loaded, but MAP17 was not found. The export marker and test
  target differed.”
- “EC7Wolf rejected PLANES for MAP01. Open the export validation details; your
  retail archive was not changed.”
- “The game entered MAP01 and is still running. This is expected.”

---

## 16. 3D preview decision and design

### 16.1 What ships first

The first usable editor ships **Test Map**, which is exact, interactive, and
uses the real EC7Wolf engine. This satisfies the core need to see and play the
level in 3D without creating a second renderer.

### 16.2 Exact 3D Snapshot dock

An exact still preview is sufficiently bounded to include as a post-vertical-
slice milestone. User workflow:

1. Activate **3D Camera** in the 2D canvas.
2. Click a valid walkable tile and drag/choose facing angle.
3. The canvas shows camera position and field-of-view wedge.
4. Click **Refresh Snapshot** or enable debounced manual refresh.
5. The editor validates/exports the current revision.
6. EC7Wolf launches briefly with the software renderer and the editor snapshot
   harness, captures at the verified ready/fixed-tic point, writes a PNG, and
   exits under a bounded success/failure protocol.
7. The dock displays the exact result, revision, tile, angle, renderer, rank,
   and timestamp.

No continuous capture occurs while painting by default. It would be slow,
flash windows, and create unnecessary derived commercial images.

### 16.3 Proposed capture launch shape

After the engine-side CLI seam is fixed and gated, the argument vector is based
on the ordinary preview launch plus:

```text
--vid-renderer software
--no-upscale
--res VERIFIED_WIDTH VERIFIED_HEIGHT
--capture-rngseed 1
--capture-warp X Y ANGLE_DEGREES
--capture-frame VERIFIED_FRAME_OR_EDITOR_SNAPSHOT_SEAM
--capture-file /absolute/private/session/snapshot.png
--capture-maxframes VERIFIED_BOUND
```

The symbolic values are intentional: E10 must not bless frame 8 without proving
which simulation tic/readiness state it captures. The exact readiness/tic,
seed, resolution, software renderer, hidden/window behavior, and exit condition
are frozen by E10 tests. The camera cell must be legal floor; invalid placement
is caught in the editor. The output is accepted only when the PNG exists,
decodes within bounds, matches expected session identity, and the log contains
positive target-map, simulation-tic, camera, and capture evidence.

### 16.4 Required engine-side snapshot seam

The smallest acceptable engine change may include:

- consume every editor-used option and its full arity in ordinary parameter
  dispatch so values are not treated as resource files. E9 owns
  `--vid-renderer` plus its value for ordinary test launches; E10 audits and
  fixes `--capture-warp`, `--capture-glframe`, `--capture-glpresent`, and every
  other snapshot option it actually uses;
- strictly parse finite, bounded X/Y/angle values and revalidate the camera
  against the map that was actually loaded rather than trusting unchecked
  floating-point input;
- add a stable “map is entered and simulation tic T is ready” capture condition
  (for example as part of `--editor-snapshot`) rather than equating frame N
  with tic N;
- add a narrowly named `--editor-snapshot` or capture-hidden behavior if
  platform tests show window flashing is disruptive;
- guarantee exit after success/failure without relying on an external timeout;
- emit one stable machine-parseable result event with map, coordinates, angle,
  output identity, dimensions, and status through E9's explicitly flushed
  protocol;
- preserve normal gameplay behavior when no capture/editor option is supplied.

This is a command-line/harness improvement, not renderer extraction. If
Snapshot ships in version 1, it is clearly exposed as software-only. If the UI
later offers OpenGL Snapshot, it
uses and tests `--capture-glframe` or `--capture-glpresent`, accepts the actual
PPM artifact (or adds an explicit conversion/output contract), and never calls
the blank software-framebuffer PNG an OpenGL view.

### 16.5 Snapshot cache and privacy

Snapshots are retail-derived when retail assets/maps are shown. They live only
in the private session/cache root. The sealed version-1 profile disables asset
upscaling, fixes resolution/view/render config, and keys each entry by map
export hash, camera, software renderer/profile, rank, fixed/observed simulation
tic, platform, engine binary digest, `ecwolf.pk3` and loaded-resource digests,
and trusted data-profile/content digest—not a printable version string alone.
Cache size and age are bounded; **Clear Derived Preview Cache** deletes only
verified application-owned files. A user may explicitly save a screenshot,
receiving the commercial/sharing notice.

### 16.6 Snapshot limitations

A still frame does not demonstrate doors opening, enemy AI, wall animations,
triggers, palette cycles, sound areas, progression, or completion. The dock
links directly to **Test Map from this position** only if the engine supports a
safe verified interactive warp option; otherwise Test Map starts normally.

### 16.7 Optional approximate interactive layout view

A time-boxed post-core spike, which may occur before or after the first public
release, may build a standalone grid raycaster or isometric view that shows:

- fixed-height textured opaque walls;
- inferred door slabs;
- indexed transparent masked walls;
- simple billboard object/enemy sprites;
- flat floor/ceiling colors from target-slot metadata;
- camera movement and debug overlays.

It must be labeled **Layout Preview (not exact gameplay)**. It does not attempt
dynamic collision, AI, activation, damage, sound, palette cycling, end-level
logic, or perfect renderer parity.

### 16.8 Interactive-preview go/no-go gate

Proceed beyond the spike only if all are true:

- core editor milestones through import/export/playtest are complete and green;
- prototype is isolated behind a stable document-read interface;
- opaque walls, ordinary doors, masked transparency, sprites, and target-slot
  colors are acceptably useful on synthetic and locally owned test maps;
- panning/walking remains at least 60 Hz on baseline hardware at 64×64;
- implementation and maintained tests fit the agreed time budget;
- UI states limitations unmistakably;
- no retail asset is cached or packaged outside the private policy;
- no engine/runtime semantics are moved into the approximate renderer as a new
  authority.

If any criterion fails, close the spike, retain Test Map plus Snapshot only if
E10 shipped it, and schedule interactive preview as a different project. That
is a successful scope decision, not a failure of the editor.

### 16.9 Explicitly rejected 3D shortcuts

- Linking arbitrary engine object files into Python/Qt.
- Sharing live global engine memory between processes.
- Screen-scraping a game window as an “embedded renderer.”
- Shipping a WebGL service that uploads retail assets to a server.
- Claiming approximate raycasting is exact.
- Blocking basic wall painting or import on 3D feature work.

---

## 17. Reliability, performance, and observability

### 17.1 Reliability invariants

- Source retail files are never opened for writing in normal operation.
- A failed save/export never replaces the last known-valid output.
- Every asynchronous result is tagged with project/map revision and owner.
- Canceling a gesture makes no document change.
- One committed command is either fully applied or not applied.
- Project reopen and export readback compare canonical content.
- Unknown values survive all unrelated edits.
- User settings corruption falls back to defaults without harming projects.
- A broken thumbnail or asset does not make raw map content inaccessible.
- Crashed child processes cannot leave the editor believing a current test is
  valid/running.

### 17.2 Performance budgets

Baseline budgets are measured on a documented modest supported machine and
adjusted only with evidence:

| Operation | Target |
| --- | ---: |
| Pointer hover/tool preview | under 16 ms typical |
| Paint event during drag | under 16 ms typical; never proportional to all 60 maps |
| Open one 64×64 project map after assets warm | under 250 ms |
| Full 64×64 validation excluding engine | under 250 ms typical |
| Undo/redo 4,096-cell fill | under 100 ms |
| Save one-map project | under 250 ms typical |
| Export/readback one-map WAD | under 250 ms typical |
| Browse metadata for 60-map retail archive | under 2 s after file access, off UI thread |
| First local thumbnail availability | progressive; UI remains interactive |
| Memory for one map raw planes | bounded near native size plus command/view overhead |
| Steady canvas interaction | 60 visual updates/s on baseline where display permits |

Engine launch and snapshot timing depend on platform and are reported rather
than hidden. No budget justifies skipping validation or atomicity.

### 17.3 Rendering optimization

- Paint only the exposed tile rectangle plus overlay margin.
- Cache decoded source thumbnails independently from zoom-scaled Qt pixmaps.
- Batch grid lines and repeated glyphs.
- Switch to schematic glyphs below a zoom threshold.
- Avoid rebuilding the entire scene on cursor movement; overlay/tool preview is
  separate from stable layer tiles.
- Invalidate exact cells/regions after commands.
- Bound device-scale cache variants.
- Profile before introducing OpenGL canvas complexity.

### 17.4 Validation optimization

- Local cell/neighbor rules use the command's affected region.
- Topology caches walkability and invalidates touched components conservatively.
- Worker jobs coalesce to the latest revision.
- Expensive catalog/source checks run at generation/discovery, not every paint
  event.
- Export always performs a fresh authoritative pass regardless of caches.

### 17.5 Logs and diagnostics

Application logs include timestamps, severity, subsystem, project UUID prefix,
revision, operation/session ID, and exception traceback where relevant. They do
not include retail plane dumps, decoded pixels, secrets, full environment, or
unredacted personal paths in copy-to-bug-report mode. Local full logs may retain
paths because they are needed for diagnosis; the UI clearly distinguishes
**Copy redacted report** from **Open full local log**.

### 17.6 Crash handling

Top-level exception hooks:

- stop accepting new mutations;
- attempt a bounded recovery snapshot of the last consistent document revision
  without overwriting project files;
- flush a private crash log;
- identify running child process/session without unsafe forced termination;
- show or write concise recovery instructions;
- never collect/upload automatically.

Fault injection tests kill the process after transaction, during autosave temp
write, before replace, after replace, and during preview export.

### 17.7 Settings

Per-user settings contain UI layout, recent safe paths, profile IDs, shortcuts,
favorites, cache caps, and test preferences. They are schema-versioned and
written atomically. Credentials are not required. A **Reset UI Settings** action
does not delete projects, retail data, or derived cache unless separately
selected.

---

## 18. Security and untrusted-input design

### 18.1 Inputs considered untrusted

- `.ec7project` files from another person;
- clipboard JSON;
- native `MAPTEMP.*` and WAD files;
- data directories and executable paths;
- catalog-generation source text;
- child-process output;
- settings/recovery files after corruption;
- any future project bundle/archive;
- filenames and native map names displayed in the GUI.

Retail ownership does not imply a file is well formed.

### 18.2 Parser rules

- Bound file size before allocation where possible.
- Check every addition/multiplication for overflow before slicing/allocating.
- Bound map count, dimensions, cells, plane counts, RLEW expansion, names,
  lumps, directory entries, JSON depth/size, diagnostics, and strings.
- Reject overlapping/out-of-order offsets where the format contract requires
  order.
- RLEW output must equal the declared expanded word count exactly; neither
  underflow nor trailing expansion is accepted.
- Reject duplicate ambiguous map markers in project import unless an explicit
  last-wins WAD inspection mode handles them read-only.
- Never evaluate project/catalog text as Python, expressions, templates, or
  shell.
- Decode display strings with explicit error policy and escape them in rich
  text/log contexts.

### 18.3 Path and filesystem rules

- Canonicalize paths for containment checks and compare platform-aware roots.
- Inspect symlinks before writes; do not follow an output symlink outside the
  approved parent.
- Require regular files/directories for expected types; reject devices,
  sockets, and FIFOs.
- Create private session directories with restrictive permissions.
- Use exclusive temporary-file creation and atomic replace.
- Security-sensitive creation and replacement are anchored to an already-open
  trusted parent rather than “canonicalize then open.” POSIX uses `dir_fd` /
  `openat`-style no-follow operations and rename within that directory;
  Windows uses a reviewed handle/reparse-point adapter and rechecks the final
  handle path immediately before replacement. If a claimed platform cannot
  prove this property, protected-root output is disabled there rather than
  weakened silently.
- Never recursively delete a user-selected path. Cache cleanup enumerates only
  manifest-owned children under a verified application root.
- If project bundles are ever zip-based, reject absolute paths, `..`, drive
  prefixes, NULs, duplicate/conflicting entries, symlinks, decompression bombs,
  and extraction beyond size/count caps.

### 18.4 Process execution rules

- Use argument arrays; never `shell=True`, command concatenation, `system`, or
  an arbitrary terminal interpreter. The only possible script exception is the
  exact audited POSIX launcher adapter described in Section 15.6.
- Version 1 normally requires an explicitly configured direct engine regular
  file. Selecting and executing it is an explicit trust transition: the user
  confirms the first validation probe, and the editor pins and rechecks its
  identity/digest before every launch. Regular-file, version, and capability
  probes prevent mistakes; they do not sandbox malicious code running with the
  user's authority.
- Set exact cwd rather than embedding a directory into `--data`.
- Pass absolute preview/config/save paths.
- Inherit a controlled environment and override only documented keys.
- Treat stdout/stderr as untrusted text with bounded lines/buffers.
- Do not parse output into rich HTML without escaping.
- The editor passes no retail-source output path and redirects known EC7Wolf
  config/save writes to the session. That protects against normal engine
  behavior, not a malicious selected binary, which can write anywhere the user
  can. Source hashes are rechecked after the process and any change is a
  stop-the-line incident.

### 18.5 Catalog generation safety

Catalog generation runs as a build/developer tool against checked-in source. It
uses a real parser or narrowly bounded grammar where practical; regex joins
must fail closed on ambiguity. Generated content is data, not executable code.
Every mapping has source provenance and a reproducibility diff gate.

### 18.6 Project-content privacy

The editor has no telemetry or network client. Bug reports are generated
locally and copied/saved only by user action. Redacted reports omit:

- absolute home/data paths;
- full retail/source hashes unless the user includes them;
- raw plane arrays;
- retail thumbnail/snapshot pixels;
- config/save contents;
- environment variables unrelated to the app.

### 18.7 Security tests

At minimum:

- malformed/truncated/overlapping TED5 archives;
- RLEW bombs, zero runs, tag truncation, excess expansion, and boundary sizes;
- malicious WAD offsets/counts/names and duplicate markers;
- huge/deep/wrong-type JSON and unknown schemas;
- clipboard payload caps;
- path traversal, symlink/reparse output, protected-root containment, anchored
  no-follow replacement, immediate identity checks, and two-instance races;
- argument quoting with spaces, Unicode, leading dashes, and shell metacharacters;
- hostile log lines and rich-text escaping;
- no-newline/invalid-UTF-8 child-output floods and per-session/global log caps;
- cache-cleanup exact-target tests;
- public package scans for retail and derived-content artifacts.

### 18.8 Threat-response policy

A parser, path, process, or commercial-data leak finding stops feature work in
the affected milestone. Fix, regression-test, and re-run the relevant broader
gate before continuing. Do not downgrade it to documentation because the input
is “only a local map.”

---

## 19. Verification strategy and test matrix

### 19.1 Verification principle

The editor manipulates compact data with large consequences. Tests therefore
compare canonical content at every boundary:

```text
synthetic/native input
    → parser
    → project
    → commands
    → project save/reopen
    → preview/full export
    → independent readback
    → EC7Wolf load and map entry
```

No stage declares success solely because it did not throw. Every boundary has a
positive identity, count, hash, or semantic-equivalence assertion.

### 19.2 One gate entry point

All editor gates are integrated into [`tools/run_gates.sh`](../tools/run_gates.sh).
Developers and CI use the same selector and classification model; the editor
does not grow a second “real” test suite hidden behind a custom script.

Proposed selectors:

| Gate | Data class | Purpose |
| --- | --- | --- |
| `editor_core` | hosted/data-free | codec, model, commands, schema, validation, WAD, security |
| `editor_gui` | hosted/data-free; mandatory on every claimed release target | real offscreen application interaction |
| `editor_package_synthetic` | hosted/data-free | frozen/source package starts and edits synthetic content |
| `editor_corridor7_import` | owned-data/self-hosted | read-only import/census/round trip of all 60 maps and assets |
| `editor_export_load` | owned-data/self-hosted | exported maps load in actual EC7Wolf |
| `editor_playtest` | owned-data/self-hosted | structured one-click launch reaches target map |
| `editor_snapshot` | owned-data/self-hosted/render-capable | exact capture path and output evidence |
| `editor_release_startup` | local/release | packaged editor starts beside the fresh runnable package |

The aggregate selector `editor` runs every applicable editor gate. A developer
may intentionally run a documented core-only subset on a machine without Qt,
but a release/hosted job for a claimed platform must provision PySide6 and may
not legal-skip `editor_gui`. `--require-data` turns a missing data-dependent
editor gate into a failure, matching existing project policy. `editor_snapshot`
is absent—not falsely skipped—when E10 formally defers the feature.

### 19.3 Fixture policy

Checked-in fixtures are one of:

- programmatically generated synthetic map archives;
- synthetic WADs/PLANES with unmistakably nonretail word patterns;
- synthetic indexed walls/sprites/palettes drawn by code or project-owned;
- small malformed byte vectors constructed inside tests;
- redacted/synthetic logs;
- versioned project JSON built from synthetic planes.

Every binary fixture has a generator or a short provenance record. No fixture
is created by cropping, recoloring, compressing, converting, or transcribing a
retail asset/map. Repository and release scans enforce this.

Owned-data tests locate data from an explicit `-d`/environment input, never a
hard-coded personal path, and write only into a fresh private temporary root.

### 19.4 Codec unit tests

#### RLEW

- literal words, tagged words, shortest/longest useful runs;
- literal value equal to tag encoded safely;
- runs split deterministically when limits require it;
- exact expanded length and empty/edge inputs;
- truncated tag/count/value triples;
- zero or impossible counts according to source contract;
- over-expansion, under-expansion, trailing data, odd byte lengths;
- 16-bit boundary values and encoded-length overflow;
- deterministic encode and encode/decode property tests.

#### TED5 archive

- first and later header layout;
- one map, 60 synthetic maps, maximum supported count;
- exact terminator and trailing-garbage policy;
- offsets/lengths at boundaries;
- zero, minimum, 64×64, rectangular, maximum verified dimensions;
- invalid/overflow dimensions and cell products;
- three plane length equality;
- ASCII name rules, padding, embedded NUL, unrepresentable name;
- exact imported 16-byte name fields, including nonzero post-NUL bytes;
- unchanged noncanonical imported name remains exportable with
  `C7E-NATIVE-007`, not `C7E-NATIVE-004`;
- deliberate rename replaces the whole field with canonical validated
  ASCII/NUL/padding rather than retaining stale tail bytes;
- overlapping, descending, out-of-file offsets;
- source-safe output and full semantic round trip;
- independent comparison with an engine-derived PLANES result where possible.

Fuzz/property runs are deterministically seeded and bounded for CI. Every found
regression becomes a minimized fixed test.

### 19.5 WAD/PLANES tests

- exact WDC3.1 header fields and little-endian arrays;
- independent writer and reader, not a round trip through one shared bug;
- zero-length `MAPxx` marker immediately followed by `PLANES`;
- one and multiple unique map pairs;
- deterministic WAD directory order, offsets, padding, names, and digest;
- width/height/plane count/name validation;
- truncated header/data and excess data policy;
- malicious lump count/offset/size and 32-bit overflow;
- duplicate/ambiguous markers;
- exported raw words equal project raw words, including unknown/plane 2;
- no lumps other than the allow-listed map pairs in a normal preview.

At least one test uses a reader structurally independent from the writer. The
data-dependent gate then lets EC7Wolf provide a third implementation.

### 19.6 Asset-decoder tests

- supported executable identity and palette offset bounds;
- wrong executable size/signature produces precise discovery failure;
- GFX header offsets/counts and malformed tables;
- 64×64 wall index orientation and known synthetic corner pattern;
- sprite post/column ordering, transparency, clipping, overlap, bad offsets,
  and excessive dimensions/posts;
- VGA picture bounds where retained;
- indexed-to-RGBA palette mapping with no interpolation;
- decoder never writes source or persistent data;
- memory/cache caps and cancellation;
- Qt boundary constructs expected pixel image from synthetic bytes.

Owned-data tests compare only safe counts, dimensions, hashes stored privately,
and local behavior; they do not emit decoded images into CI artifacts.

### 19.7 Catalog tests

- regeneration is deterministic and checked-in output is current;
- every normal entry has a unique stable key, name, category, source, and test
  vector;
- every raw mapping in scope is classified as normal, semantic special,
  imported-only, or unresolved Advanced;
- no two normal items claim the same exact tuple with contradictory meaning;
- all enemy direction/patrol/rank variants round-trip;
- every supported rotation/reflection maps to an existing variant and satisfies
  group identities (four quarter-turns return original, two flips return
  original where defined);
- every compound tool has write, erase, placement, validation, and transform
  definitions;
- thumbnails resolve locally where source definitions promise them;
- unresolved joins fail generation or remain explicitly unavailable;
- catalog contains metadata only, no retail pixel/plane bytes.

### 19.8 Document and command tests

- coordinate/index conversions at every corner and invalid bounds;
- raw uint16 enforcement and independent planes;
- command apply/undo/redo exact equality;
- failed precondition leaves document/revision/history unchanged;
- drag coalesces repeated cells and bridges fast pointer segments;
- no-op command is omitted;
- compound command is atomic across planes/cells;
- undo limit evicts only complete oldest commands;
- saved/dirty revision behavior across save, undo, redo, branch;
- selection does not enter document/history;
- copy/paste masks, conflicts, clips/rejects bounds as specified;
- transforms preserve all selected cells and remap directions correctly;
- unknown and plane-2 values survive unrelated commands;
- immutable worker snapshots cannot mutate live arrays;
- stale worker results cannot apply to a newer/closed document.

Model-based randomized command sequences compare the production command engine
with a small reference array model, then undo all operations back to the exact
initial digest.

### 19.9 Project/schema tests

- current schema load/save deterministic equality;
- every supported old schema migrates step by step;
- newer schema rejected readably;
- wrong types, missing keys, unknown forbidden keys, duplicate IDs;
- huge/deep arrays and wrong row lengths rejected before runaway allocation;
- UTF-8/name behavior and stable ordering;
- local path/profile fields do not embed retail bytes;
- `native_name`/raw-hex mismatch is rejected and a rename updates both fields
  in one command;
- atomic save fault injection before/after write, flush, readback, replace;
- concurrent newer edit remains dirty after older snapshot save completes;
- per-target writer ordering is tested with both completion orders: an older
  worker never replaces a newer committed save or autosave;
- cooperative second-instance locking and an external destination change in
  the final pre-replace window produce a conflict, never silent last-writer
  loss;
- local-filesystem capability detection warns/redirects unsupported
  network/cloud-synchronized roots;
- autosave retention and recovery chooser states;
- external modification/source-hash conflict behavior;
- settings reset cannot delete project/cache unless separately requested.

### 19.10 Semantic-tool tests

For each tool/prefab, use table-driven synthetic neighborhoods:

- valid placement exact before/after planes;
- each invalid precondition diagnostic code;
- warning-only topology;
- erase returns defined safe base state;
- rotate/flip mappings;
- conflict with existing plane-1 meaning;
- apply/undo/redo;
- copy/paste across a selection edge;
- imported unusual combination remains preserved.

Door tests mirror current engine axis inference for north/south, east/west,
tie, corner, blocked, and boundary cases. Transporter tests cover all eight
channels, pair placement, orphan repair, reassign, and count error. Exits cover
ordinary, secret, floor, vortex, and target-slot profiles.

### 19.11 Validator tests

- every diagnostic code has at least one positive and negative fixture;
- local incremental result equals clean full validation for affected rules;
- outer boundary and dimensions;
- zero/one/multiple starts by profile;
- floor/wall/thing compatibility;
- each compound structure valid/invalid shape;
- zones and disconnected components;
- transporters and exit pairings;
- advisory reachability with open, locked/keyed, transporter, isolated, and
  cyclic-key cases;
- target-slot MAP30/MAP40/bonus warnings;
- unknown imported versus newly introduced value severity;
- nonzero plane 2 preserved informational result;
- deterministic diagnostic sort/order/text parameters;
- stale revision does not block current export;
- auto-fix command exactness and undo.

### 19.12 Export and path tests

- normal output never targets source/data/repository/release roots;
- canonical and symlink containment on Windows/Linux path models;
- spaces, Unicode, leading dashes, shell characters, long names;
- atomic replace faults and post-readback mismatch;
- exact source hash before/after import/export/test;
- private archive preserves untouched maps and edited target;
- normal WAD contains no unrelated maps or assets;
- classification/warning behavior for original/imported/mixed provenance;
- sidecar/report contains metadata but no full commercial planes;
- cleanup targets only manifest-owned private session files.

### 19.13 Engine-runner tests

The headless runner plan is tested without launching a process:

- direct executable argv and cwd exactly match Section 15;
- `--data` receives `CO7`, never the directory;
- every generated path is absolute;
- no shell string or quoting layer exists;
- skill is 1-based and target marker equals tedlevel;
- direct execution works against the binary inside a private package; any
  optional audited POSIX launcher adapter does not duplicate
  renderer/config/save semantics, and `.cmd` is rejected in version 1;
- environment allow-list and redaction;
- stale/current session transitions;
- log parsing requires positive map entry and detects fatal patterns;
- the explicitly flushed editor-protocol event arrives through ordinary pipes
  before a fake/real child exits and matches the session/map identity;
- a buffered human log line alone never produces **Entered MAPxx**;
- bounded termination escalation, editor-exit cancel/stop behavior, no captured
  child detach, and orphan reconciliation;
- output with no newline, invalid UTF-8, and bytes beyond session/global caps
  is drained without unbounded memory/disk growth or child deadlock.

A fake child executable/script receives arguments through the OS process API
and writes them as length-prefixed data, proving spaces and metacharacters are
literal arguments rather than shell syntax.

### 19.14 GUI offscreen tests

Following the real PySide6 installer precedent, set
`QT_QPA_PLATFORM=offscreen`, construct the actual application/main window, and
drive public interactions:

- first-run discovery with synthetic profile responses;
- new project and safe template;
- palette search/select, wall click/drag, object/enemy placement;
- inspector property change and raw Advanced reveal;
- undo/redo actions and labels;
- door/transporter preview and invalid placement feedback;
- layer visibility, zoom, selection, problem navigation;
- save/reopen and recovery prompt;
- Test Map disabled/enabled reasons with fake process;
- log output/state transitions;
- layout persistence/reset and high-DPI logical sizes;
- keyboard-only primary workflow and accessible names.

Tests assert document state through the public model/core, not private widget
coordinates alone. A small number of platform screenshot/layout goldens may be
used for project-owned synthetic content, with deliberate update review.

### 19.15 Owned-data import gate

Against an explicitly supplied legal data directory:

1. Hash every required input.
2. Parse `MAPTEMP.CO7` and require the expected locally reviewed 60-map archive
   shape without writing it into artifacts.
3. Import every map into a temporary project.
4. Save/reopen and compare every header/dimension/plane word.
5. Export/reparse a private full archive and compare canonical content.
6. Export each map as a one-map WAD and core-read it back.
7. Decode representative wall/sprite thumbnails in memory.
8. Rehash every input and require equality.
9. Delete only the verified temporary root or retain it on failure under a
   clearly private path.

The test prints counts and digests only as allowed local diagnostics. Hosted CI
does not receive the data or resulting artifacts.

### 19.16 EC7Wolf export-load gate

Use project runtime-harness conventions:

- build first;
- set cwd to data directory;
- use temp config/save/session paths;
- use `SDL_AUDIODRIVER=dummy`, Xvfb/current tested video convention;
- apply a bounded timeout;
- require positive target map-entry evidence before accepting a gameplay
  timeout;
- fail on parser, fatal, assertion, sanitizer, wrong-IWAD, or wrong-map output.

Test representative synthetic maps and, in the private data gate, each of the
60 decoded/re-exported maps under its intended marker. At least one test changes
a distinctive synthetic plane value and proves the later WAD override was used,
not the base map.

### 19.17 Playtest gate

Drive the same public controller used by the GUI:

1. Create/open synthetic project.
2. Export current revision.
3. Launch actual EC7Wolf with owned data.
4. Require preview file and target marker in evidence.
5. Require map entry.
6. Request bounded termination with the Section 15.7 progress-loss warning, or
   accept a gameplay timeout only after entry; do not label current SIGTERM
   behavior a proven cooperative engine quit.
7. Verify config/saves/session were isolated and retail source hashes unchanged.
8. Modify project, relaunch, and prove the new export hash/revision is used.

### 19.18 Snapshot gate

After E10:

- command-line capture options are consumed cleanly;
- chosen tile/angle reaches the log/result line;
- the required software path produces a valid bounded PNG containing the 3D
  world, not a blank/overlay-only framebuffer;
- capture occurs at a verified readiness/fixed simulation tic; repeated equal
  input, engine, renderer, and tic meets the tested determinism contract;
- any optional OpenGL path uses its GL-specific frame/present capture and PPM
  contract (or an explicitly added tested conversion), not `--capture-file`;
- output belongs to the current export hash and camera;
- invalid wall/out-of-bounds camera is rejected before launch;
- failure/timeout leaves no false-success cache entry;
- window/hidden behavior is exercised on supported platforms where automatable;
- source data and ordinary user config/saves remain unchanged.

### 19.19 Manual usability and accessibility matrix

Before release, a human tester completes the Quick Start without source-format
knowledge on each supported platform. Record:

- first launch to painted wall;
- first object and enemy placement;
- finding/placing a door and transporter pair;
- understanding and fixing a forced validation error;
- import of an existing map and awareness of sharing restriction;
- Test Map launch and return to editing;
- recovery from a simulated crash;
- keyboard-only path;
- 100/150/200% DPI, small/large text, dark/light theme, color-vision-safe
  overlays, reduced animation;
- 1280×720 minimum and a common high-resolution display.

Observed confusion becomes a UX issue, not a manual-only workaround when the
interface can reasonably solve it.

### 19.20 Performance and soak tests

- Repaint continuous strokes for ten minutes with validation active.
- Generate 10,000 deterministic mixed commands, save/reopen, undo/redo within
  retained history, and compare reference digest.
- Open/close all 60 maps and cycle thumbnails under memory instrumentation.
- Repeatedly launch/stop tests and snapshots; check process/session leakage.
- Fill/transform maximum verified dimensions under timing/memory caps.
- Corrupt/fail writes under fault injection and recover.
- Run 8-hour idle with autosave and periodic edits in a developer soak.

Budgets are recorded with machine, OS, Python, Qt, build, and data profile; one
fast developer workstation is not the baseline definition.

### 19.21 Test evidence format

Each gate reports:

- gate name and version;
- exact command and relevant sanitized paths;
- source commit/dirty-state note;
- platform/Python/PySide6/engine identity;
- synthetic/data-dependent classification;
- tests run, passed, failed, skipped and why;
- important positive evidence/digests/counts;
- duration;
- retained private artifact path on failure;
- final `PASS`, `FAIL`, or legal `SKIP`.

---

## 20. Build, CI, packaging, and distribution

### 20.1 Development entry points

From a source checkout:

- `editor/ec7wolf-editor` starts the GUI.
- `python -m ec7edit_core.cli` offers inspect, validate, export, and discovery
  actions.
- `tools/run_gates.sh ... editor_core` runs selected tests.

Exact commands are finalized when packaging exists and then documented in the
README and editor Quick Start. A developer does not need commercial data for
core, GUI, or synthetic work.

### 20.2 Windows package

Produce a Windows x64 GUI executable/package with PyInstaller on Windows; the
existing installer tooling correctly notes that Windows freezing is not
cross-compiled from Linux. Requirements:

- normal GUI subsystem without an unwanted console, plus a documented debug
  launcher/log path;
- the existing project-owned EC7Wolf icon set reused as-is and kept in step,
  never regenerated;
- PySide6 plugins/platform components allow-listed rather than copying an
  entire development environment;
- licenses/notices included;
- deterministic manifest and dependency scan as far as the toolchain permits;
- no retail data, cache, projects, screenshots, or test previews;
- starts on a clean supported Windows VM without a separately installed Python;
- handles spaces/Unicode in executable, data, and project paths.

### 20.3 Linux package

Initial supported forms use Python 3.10+ within the E0-tested range and the
minimum/maximum PySide6/Qt range demonstrated and locked by E0/E4; this plan
does not guess a Qt floor that a target distribution cannot provide:

- a source launcher using a tested distribution Python/PySide pair with clear
  dependency diagnostics; and
- a distribution-appropriate frozen/archive package produced on the target
  architecture after the E4 packaging spike.

The first-release acceptance matrix is Windows 11 x64 plus Ubuntu 24.04 LTS
x64 and arm64. E0 pins exact Python/PySide patch versions and E4 records whether
other distributions are supported or best-effort; a distribution is not
claimed merely because another Linux job passed.

KDE/Qt integration should be native. A `.desktop` entry, MIME association for
`.ec7project`, and menu icon are useful once uninstall/upgrade behavior is
defined. Do not require root for per-user installation.

### 20.4 Engine coupling

The editor is versioned and packaged separately enough that it can point at a
compatible EC7Wolf executable/package. Compatibility is established through a
small capability probe or version/feature check, not an assumption that any
binary named `ecwolf` supports Corridor 7 and capture options.

`editor/pyproject.toml` is the single release-version source (`0.1.0` for the
first public release). A packaging step generates a read-only build-info module
and manifest containing source commit/dirty flag, project schema, catalog,
supported editor-protocol range, dependency-lock identity, and build platform.
Package metadata, About, redacted bug reports, migration diagnostics, and the
CLI all read that same identity; none derives the editor version from
EC7Wolf's `1.0-betaX`.

Capabilities include:

- Corridor 7 data recognition;
- `--file` override;
- direct `--tedlevel`/`--skill`;
- isolated config/saves;
- WDC3.1 PLANES load;
- versioned, explicitly flushed editor session/map-entry events;
- snapshot command/result protocol when used.

Version 1 ships the public, data-free EC7Edit package separately and points it
at a compatible EC7Wolf installation or the executable inside a private
`builds/release`. It does not copy EC7Edit into that replaceable private package
and does not bundle an engine in the public editor artifact. Changing that
topology later requires a new license, size, update, launcher, and artifact
audit decision.

### 20.5 CI split

Hosted CI runs:

- static/type/lint checks adopted by the implementation;
- `editor_core` on supported Python versions/platforms;
- real PySide6 offscreen `editor_gui`, provisioned and mandatory on every
  claimed release target;
- synthetic package/startup tests;
- catalog regeneration diff;
- public artifact commercial-content audit.

Self-hosted/local owned-data CI runs:

- `editor_corridor7_import`;
- `editor_export_load`;
- `editor_playtest`;
- renderer-dependent `editor_snapshot`;
- private release startup.

Commercial data is never cached, uploaded, attached, printed, or put in a
hosted artifact. Missing data is a skip only when `--require-data` is absent.

### 20.6 Integration with existing gates

Editor gate classification, help, selected-run behavior, skip policy, and
failure summary are added to `tools/run_gates.sh` rather than replacing current
Corridor 7 gates. Existing `corridor7_release_startup` remains unchanged and
green; `editor_release_startup` is additive.

`editor_release_startup` takes two explicit inputs: a staged public EC7Edit
package and a freshly built private Corridor 7 package. In a private temporary
profile it starts the packaged editor, validates the direct engine binary/data
pair, opens and edits a synthetic project, exports/reads back a synthetic WAD,
and proves no editor file was written under either package root. Owned-data
engine entry remains the separate `editor_playtest` gate; no retail-derived
artifact is copied into the public package or gate output.

GUI shell tests follow
[`tools/test_installer_gui.sh`](../tools/test_installer_gui.sh). Engine runtime
tests follow [`tools/test_corridor7.sh`](../tools/test_corridor7.sh) and
[`tools/validate_corridor7_maps.sh`](../tools/validate_corridor7_maps.sh).

### 20.7 CMake and pk3 interactions

The Python editor should not force Qt into the EC7Wolf C++ link. CMake may gain
install/package targets and gate discovery, but editor core/GUI packaging is a
separate target. If catalog or engine snapshot work changes `wadsrc`, rebuild
`ecwolf.pk3` through the established build. A trustworthy embedded version
requires the repository's existing double-build convention.

### 20.8 Documentation integration

This document is indexed in the README documentation table. When the editor
implementation lands, documentation includes:

- Quick Start and first-run setup;
- file/project/export formats;
- map tools and Corridor 7 semantics;
- validation-code reference;
- import/extraction and commercial-content guide;
- Test Map and Snapshot troubleshooting;
- shortcuts/accessibility;
- CLI and developer architecture;
- package/install/uninstall instructions;
- limitations and known issues.

### 20.9 Release artifact audit

Extend the current release workflow's file-tree/archive/APK commercial-data
checks to editor artifacts. The editor audit is stricter than a `.CO7` scan and
uses:

- allow-listed package paths/extensions;
- deny-listed project/cache/session/preview patterns;
- archive recursion with bomb limits;
- known retail hashes where legally stored on the private runner only;
- catalog structure check for metadata-only content;
- synthetic-fixture provenance manifest;
- a final human-readable staged file list.

### 20.10 Mandatory final local verification

At the end of implementation work, follow repository policy with a fresh
release build and private package. The following concrete example is run from
the containing workspace root `/home/jason/Code/corr7port`; portable
instructions substitute explicit source/build/data/package paths. The canonical
sequence is:

```sh
cmake -S ECWolf -B builds/release-build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DECWOLF_RENDERER_OPENGL=ON \
  -DECWOLF_RENDERER_SOFTWARE=ON
cmake --build builds/release-build
cmake --build builds/release-build

# Build a data-free editor package at the conventional local staging path.
# E4/E12 implement this wrapper and its platform-specific freeze/spec backend.
ECWolf/tools/package_ec7edit.sh \
  --output builds/ec7edit-release

# During iteration: selected editor gates.
ECWolf/tools/run_gates.sh -b builds/release-build \
  -d corr7/CORR7CD editor

# Mandatory fresh private runnable package. This contains owned retail data
# locally and must never be committed or redistributed.
ECWolf/tools/package_corridor7_release.sh \
  builds/release-build corr7/CORR7CD builds/release

# Full final suite against the fresh build, legal data, and package.
ECWolf/tools/run_gates.sh -b builds/release-build \
  -d corr7/CORR7CD -r builds/release \
  --editor-package builds/ec7edit-release --require-data

# Explicit additive editor-package startup contract.
ECWolf/tools/test_ec7edit_release_startup.sh \
  builds/ec7edit-release builds/release

# Explicit mandatory packaged startup check. Keep its optional log outside the
# replaceable package root.
ECWolf/tools/test_corridor7_release_startup.sh builds/release \
  "$PWD/builds/release-startup.log"
```

E12 adds `--editor-package PATH` to `run_gates.sh`; it is mandatory when
`editor_release_startup` or the full release aggregate is selected. The path is
a data-free staged EC7Edit package produced by `package_ec7edit.sh`, while `-r`
remains the separate private engine/data package. The wrapper fails if its
output is inside either game-data or private-package roots and produces the
manifest/license/content audit consumed by the startup gate.

A documentation-only change may reasonably run a proportionate subset, but
the current top-level project instruction still requires the private package
refresh and packaged startup check before declaring the Corridor 7 work
finished. Implementation milestones must not treat the old package as evidence
for a new build.

### 20.11 Release contents

Public editor package (a separate artifact from `builds/release`):

- editor executable/source/runtime dependencies;
- project-owned icon and UI resources;
- generated semantic catalog metadata;
- synthetic templates/fixtures needed at runtime;
- licenses, notices, manual, changelog;
- **no Corridor 7 retail or derived content**.

Private `builds/release` continues to contain the optimized engine,
`ecwolf.pk3`, local-config/save launcher, and all files from the owned
`corr7/CORR7CD` source as required. Version 1 does not add EC7Edit to it; the
separate editor package defaults workspaces/caches outside both package roots.

---

## 21. Milestone development program

Every milestone is a reviewable vertical increment with dependencies, work,
deliverables, non-goals, tests, an exit gate, and required evidence. A milestone
is not complete because code exists; the exit gate must be met on the current
tree.

### E0 — Evidence freeze, contracts, and synthetic fixture foundation

**Dependencies:** approved master document; current `AGENTS.md`; cleanly
understood user-owned working-tree changes.

**Work:**

- Re-audit current branch, commit, status, and exact map, XLAT, actor, MAPINFO,
  launch, capture, gate, installer, and packaging symbols cited here.
- Audit the license, copyright, provenance, and authorization of every helper
  or report that currently exists only in the containing local workspace. Do
  not copy code into the ECWolf git root until that decision is recorded;
  independently reimplement documented contracts when reuse is uncertain.
- Write an evidence ledger with grade, source path/symbol, observed behavior,
  unresolved question, and owning milestone.
- Freeze coordinate, plane, name, dimension, error-severity, project-location,
  and commercial-content contracts.
- Define test naming, temporary-root, owned-data opt-in, and positive engine
  evidence conventions.
- Freeze the `EC7Edit 0.1.0` build-identity scheme, Windows 11 x64 and Ubuntu
  24.04 x64/arm64 acceptance matrix, tested Python range, PySide/Qt versions,
  license inventory, and public/private artifact topology.
- Build synthetic native archives, PLANES/WADs, indexed graphics, project
  files, and malformed-vector generators with provenance.
- Record current strict codec and asset-browser behavior without yet moving
  production code.
- Verify the existing design-doc README index entry and add a repository-root
  link audit that rejects relative Markdown links escaping the ECWolf git root.

**Deliverables:** evidence ledger; synthetic fixture generators; test skeleton;
source-area ownership map; confirmed requirement/decision list; signed-off
local-helper provenance/reuse ledger; dependency-license inventory; locked
platform/runtime/artifact matrix.

**Non-goals:** production GUI, parser rewrite, catalog completeness, engine
changes, retail artifacts.

**Tests:** fixture reproducibility/digests; repository scan proves fixtures are
synthetic; current existing format/tool tests remain green; every Markdown
local link resolves to a tracked path within the ECWolf git root; dependency
and local-code provenance audits have no unowned/unreviewed package input.

**Exit gate:** another reviewer can trace every hard native, launch, and
semantic contract to current source or a named unresolved spike; data-free
fixtures exercise every binary boundary without retail bytes; and the reviewer
can reproduce the license/provenance decision plus exact claimed-platform,
Python/Qt, editor-version, and artifact-topology matrix.

**Required evidence:** commands, source snapshot/status, evidence ledger diff,
fixture generator output hashes, commercial-content scan, local-helper
provenance/license decisions, dependency manifest, platform/runtime/artifact
matrix, root-contained link-audit output, and test results.

### E1 — Canonical native codec and minimal WAD export

**Dependencies:** E0.

**Work:**

- Implement the Qt-free production archive codec from the frozen contracts and
  synthetic tests; reuse local `corridor7_map.py` code only if E0 proves its
  provenance/license/authorization, otherwise treat it solely as behavioral
  evidence and write an independent implementation.
- Reconcile every limit/error with the current EC7Wolf loader.
- Implement deterministic RLEW and TED5 writer/readback.
- Implement independent WDC3.1 PLANES reader/writer and minimal WAD codec.
- Preserve all three planes, exact unknown values, and all 16 raw native-name
  bytes, including bytes after the first NUL.
- Add CLI `inspect`, `validate`, `convert-to-preview-wad`, and safe output paths.
- Convert existing lab-map tools to shared imports or compatibility shims
  without breaking them. Every compatibility CLI canonicalizes source and
  output, rejects source/output identity (including symlink/hardlink aliases),
  writes atomically to a protected new destination, reads back, and proves the
  source hash unchanged. Current lab helpers are patterns to harden, not a
  source-protection precedent.
- Prove later `--file` map override with a permanent owned-data integration
  test.

**Deliverables:** production codec modules; CLI; compatibility adaptations;
codec/WAD tests; documented binary layouts.

**Non-goals:** GUI, semantic editing, asset thumbnails, full project schema,
MAPINFO generation.

**Tests:** Sections 19.4–19.5; malformed/fuzz corpus; existing tool tests; engine
loads a synthetic override; source archive hashes unchanged.

**Exit gate:** a generated synthetic map survives native parse → WAD export →
independent readback exactly, and a later WAD overrides one owned-data base map
in EC7Wolf with positive entry/content evidence.

**Required evidence:** test commands/results, cross-reader comparison, output
digest reproducibility, engine log excerpt under word/data policy, source hashes,
no commercial artifacts in tree.

### E2 — Shared asset decoders and semantic catalog

**Dependencies:** E0; E1 model types.

**Work:**

- Extract bounded palette/wall/sprite decoding from `c7assets.py` and reconcile
  with defensive helpers/engine behavior.
- Preserve `c7assets.py`'s documented standalone Python 3.10+ behavior by
  generating its single-file distribution artifact mechanically from the
  canonical stdlib-only decoder/codec modules, or stop and explicitly approve
  a documented multi-file installation contract. Hand-maintained duplicate
  decoder code is not an option; reproducibility and equivalence are gated.
- Build catalog generator from XLAT and Corridor 7 actor source.
- Curate stable user-facing categories, names, aliases, descriptions, placement
  classifications, enemy variants, direction transforms, and evidence.
- Separate ordinary wall paint from structural/special raw codes.
- Add in-memory LRU image buffers and private optional cache policy.
- Report unresolved catalog joins rather than guessing.

**Deliverables:** shared asset module; deterministic metadata-only catalog and
manifest; generator; catalog/asset tests; updated asset browser integration.

**Non-goals:** final palette widgets, every composite prefab, disk cache by
default, retail image fixtures.

**Tests:** Sections 19.6–19.7; synthetic indexed patterns; owned-data local count
and representative decode; catalog regeneration diff; retail-content scan.

**Exit gate:** every normal paint/place entry in the initial vertical slice has
a stable friendly identity and exact raw round trip, and one decoder serves
both editor core and existing browser without writing retail pixels.

**Required evidence:** catalog counts/unresolved list, deterministic diff,
source references, synthetic pixel assertions, private owned-data gate result,
memory/cache measurements.

### E3 — Project document, commands, undo, schema, and recovery core

**Dependencies:** E1; E2 catalog interfaces.

**Work:**

- Implement canonical document hierarchy, UUIDs, coordinates, raw arrays,
  revision/dirty state, immutable snapshots.
- Implement command diffs, transactions, gesture coalescing, undo/redo, and
  history caps.
- Implement copy/paste payload and catalog-driven transforms.
- Define schema v1, validation, deterministic serialization, migrations
  harness, atomic save, autosave, recovery, and settings store.
- Implement per-canonical-target writer queues/generations, cooperative
  instance locks, local-filesystem capability checks, and reviewed POSIX/
  Windows parent-handle-anchored replacement adapters.
- Add source provenance and commercial classification without embedding assets.
- Fault-inject every atomic-save stage.

**Deliverables:** headless project/model/command modules; CLI create/open/save;
schema and example; recovery implementation; exhaustive tests.

**Non-goals:** Qt widgets, native archive overwrite, semantic prefab suite,
child process launch.

**Tests:** Sections 19.8–19.9 plus model-based randomized sequences and crash
fault injection.

**Exit gate:** 10,000 deterministic mixed operations match the reference model,
retained commands undo exactly, save/reopen is identical, and every injected
write crash leaves a valid old, new, or recovery state.

**Required evidence:** seed and digests, memory/history measurement, fault
matrix, schema fixtures/migrations, path and commercial-content audit.

### E4 — Qt application shell and safe discovery

**Dependencies:** E1–E3; established installer PySide6 conventions.

**Work:**

- Create application entry, main window, menus/toolbars/docks/status bar,
  settings/layout reset, and exception reporting.
- Implement first-run engine/data/workspace discovery and profile UI using the
  headless discovery core.
- Implement project/new/open/import choosers and map tabs with synthetic data.
- Add palette list models with progressive synthetic/local thumbnails.
- Establish worker/revision/cancellation boundary.
- Add accessible names, tab order, high-DPI behavior, and offscreen harness.
- Freeze a synthetic source/frozen-package smoke on each initial architecture;
  compare PyInstaller onedir and onefile startup, size, updateability, plugin
  allow-list, and repeated-launch cost. A run-once installer's onefile delay is
  not assumed acceptable for a frequently launched editor.

**Deliverables:** startable EC7Edit shell; first-run wizard/page; project/map
browser; real offscreen GUI tests; no document mutation outside core commands.

**Non-goals:** full canvas editing, special tools, playtest, snapshot.

**Tests:** application creation/close, discovery outcomes, safe-root rejection,
project open/import flow, worker stale-result tests, accessibility names, layout
reset at multiple logical sizes, mandatory real offscreen GUI runs, and
source/frozen synthetic startup on the E0 platform matrix.

**Exit gate:** a new user can configure valid paths, create/open a synthetic
project, browse its maps/palettes, close/reopen safely, and complete the whole
flow in a real offscreen application test; the selected onedir/onefile package
form also starts repeatedly within the recorded E4 size/time budget on every
claimed architecture.

**Required evidence:** GUI test video/screenshots only from synthetic content as
appropriate, offscreen commands, platform/DPI matrix, dependency/package list,
no retail cache in tree.

### E5 — First playable 2D editing vertical slice

**Dependencies:** E1–E4.

**Work:**

- Implement scrollable custom canvas, texture/schematic layers, zoom/pan/grid,
  hit testing, selection, cursor/status.
- Implement pointer, eyedropper, ordinary wall brush, valid floor/zone brush,
  object/enemy/start placement, thing/wall erasers.
- Connect inspector properties for enemy direction, patrol, and rank.
- Implement the required line, rectangle, and bounded flood-fill tools.
- Connect core undo/redo and dirty/save/reopen.
- Wire the E1 authoritative preview-WAD exporter and a deliberately scoped
  basic validator service into the GUI; E7 extends that same validator rather
  than E5 creating duplicate codec or rule paths.
- Add a temporary developer Test command if E9 controller is not yet complete,
  using the structured core launch plan only.

**Deliverables:** real paint-and-place editor; import MAP01; save/reopen;
preview WAD; initial Quick Start.

**Non-goals:** every special/prefab, polished archive export, exact snapshot,
custom MAPINFO, approximate 3D.

**Tests:** GUI strokes with sparse pointer events, placement/conflicts,
inspector variants, undo/redo, save/reopen, WAD readback, owned-data MAP01
import, EC7Wolf entry through preview override.

**Exit gate — first playable vertical slice:** import owned MAP01 read-only,
paint a chosen wall from its thumbnail, place and configure an enemy, undo and
redo both, save/reopen the project, export a one-map WAD, and make EC7Wolf enter
that edited override while the source archive hash remains unchanged.

**Required evidence:** short workflow recording/screenshots retained privately
when retail-derived, GUI/core tests, before/after canonical diff, export digest,
positive engine log evidence, source hashes, memory/latency numbers.

### E6 — Complete Corridor 7 semantic editing

**Dependencies:** E5; E2 catalog evidence.

**Work:**

- Implement doors/access doors with engine-equivalent orientation preview.
- Implement wall panels/interactions, push/secret walls, masked walls,
  animated/retractable walls, elevators, floor/vortex exits.
- Implement paired transporter and zone tools.
- Implement starts/path markers and complete enemy variant UI.
- Freeze and implement health chamber and other proven composite prefabs.
- Complete selection transforms, clipboard conflict previews, statistics,
  used-in-map and favorite/recent palette features.
- Document every compound write/erase/rotate contract.

**Deliverables:** complete supported semantic palette/tool suite; source-backed
prefab catalog; context help; tests.

**Non-goals:** speculative plane-2 editor, custom scripts/prefabs, perfect
gameplay balance analysis, interactive 3D.

**Tests:** Section 19.10 full table; engine loads representative examples;
direction group properties; undo/redo of every compound feature; imported stock
structures recognized without normalization.

**Exit gate:** every established plane-0/plane-1 authoring semantic in the
defined version-1 catalog is either safely editable through a friendly tool or
explicitly labeled preserved/Advanced with a documented reason; no compound
feature requires manual raw arithmetic for its supported case.

**Required evidence:** catalog coverage report, unresolved list, exact
before/after vectors, runtime tests for ambiguous semantics, UX walkthrough,
commercial-content audit.

### E7 — Continuous validation and reachability

**Dependencies:** E3; E6 semantic rules.

**Work:**

- Implement structured diagnostic engine, stable codes, local incremental
  validation, full worker validation, and export preflight.
- Extract and upgrade campaign reachability with keys, doors, transporters,
  explicit model limitations, and target-slot context.
- Implement validation profiles and inherited MAPINFO information.
- Build Problems pane, navigation, filtering, stale-state handling, and safe
  auto-fixes.
- Write the validation-code reference and synthetic examples.

**Deliverables:** validator core; Problems UI; profile rules; diagnostic docs;
performance and cancellation behavior.

**Non-goals:** formal proof of completable gameplay, automatic map design or
balance, custom-campaign generation.

**Tests:** Section 19.11; incremental/full equivalence; all diagnostic codes;
reachability fixtures; stale-result behavior; latency budget.

**Exit gate:** every export-blocking invariant has a stable tested diagnostic,
clicking it exposes the problem and suggested fix, warnings do not destroy
imported unknowns, and full 64×64 validation meets the baseline budget.

**Required evidence:** code catalog coverage, positive/negative fixture list,
performance profile, UI navigation test, and false-positive review against all
60 owned maps without publishing their data.

### E8 — Production import, save, export, backups, and recovery

**Dependencies:** E1, E3, E7.

**Work:**

- Finish one-map and multi-map import UX and provenance.
- Implement production project Save, Save As, Save Copy, and external-change
  behavior.
- Implement deterministic one-map and multi-map preview/share WAD export.
- Implement explicit private full-archive export and untouched-slot
  preservation.
- Complete autosave/recovery, backup policy, path protection, output reports,
  provenance classification, and derived-cache separation.
- Add the minimal diff summary needed to understand export changes.

**Deliverables:** reliable persistence workflows; commercial notices;
post-export report; owned-data all-map round-trip gate.

**Non-goals:** normal source overwrite, cloud sharing, custom MAPINFO campaign,
arbitrary archive merge.

**Tests:** Sections 19.9, 19.12, and 19.15; fault injection; protected paths;
source hashes; all maps/planes/unknowns; output content scan.

**Exit gate:** import all 60 owned maps read-only, save/reopen, export/reparse
both intended output forms with exact canonical equality, recover a force-killed
unsaved edit, and prove every retail source byte is unchanged.

**Required evidence:** hashes and safe counts, fault matrix, path/security
tests, deterministic output digests, private artifact location on failure, and
public-tree scan.

### E9 — One-click playtest and engine diagnostics

**Dependencies:** E5 basic path; E7–E8 production preflight/export.

**Work:**

- Implement the capability-aware direct-engine profile; optional POSIX
  launcher work remains outside version 1 unless its exact adapter gate passes.
- Implement structured launch plan, `QProcess` controller, session directories,
  isolated config/saves, log parsing, state machine, stop/relaunch, orphan
  reconciliation, and UI.
- Add a versioned opt-in editor capability/event protocol with explicitly
  flushed data-selection, preview-load, map-entry, fatal, and session-result
  events; prove it works through ordinary `QProcess` pipes while gameplay is
  still running.
- Add and gate the early data-free `--editor-capabilities` probe plus the
  nonce-bearing `--editor-protocol 1 --editor-session` launch contract.
- Consume `--vid-renderer`, `--editor-protocol`, `--editor-session`, and their
  values in normal parameter dispatch and fail a gate for any editor launch
  option/value misreported as a resource path.
- Validate `--data CO7`, cwd, load order, marker/tedlevel, skill/rank, renderer
  precedence, and source protection.
- Associate test saves/logs with export hash and revision.
- Add actual engine integration gate following existing harness conventions.

**Deliverables:** Test Map button and settings; Test Log; fake-process unit/GUI
tests; real owned-data playtest gate.

**Non-goals:** engine hot reload, live sync, embedded engine, arbitrary command
line or environment editor.

**Tests:** Sections 19.13 and 19.16–19.17; arguments with hostile path
characters; positive/fatal protocol evidence; buffered-log rejection; repeated
stop/relaunch/editor-exit behavior; config, save, and source hashes.

**Exit gate:** from a dirty current map, one click validates and launches the
actual engine into the exact exported target/rank, UI stays responsive, errors
are actionable, and neither retail data nor ordinary user config/saves change.

**Required evidence:** structured launch-plan dump and redacted log, map-entry
proof, revision/export digest, process lifecycle matrix, source/config hashes,
and platform results.

### E10 — Exact 3D Snapshot and interactive-preview decision

**Dependencies:** E9; current capture harness.

**Work:**

- Audit, fix, and gate full-arity consumption for every editor-used capture
  option, including `--capture-warp` and any GL frame/present option; zero
  “could not stat” misparse lines are allowed.
- Strictly parse finite bounded camera coordinates/angle and validate them
  against the map actually loaded before moving the player.
- Add the smallest stable editor-snapshot readiness/fixed-tic result, exit, and
  hidden seam justified by platform tests.
- Implement 2D camera tool, capture controller, output validation, private
  cache, dock, stale-revision label, and cleanup.
- Pin the required v1 PNG path to software; test OpenGL only through its
  separate GL-frame/present PPM path if the UI deliberately offers it.
- Seal the software profile (`--no-upscale`, fixed resolution/config) and key
  cache entries with engine/pk3/resource/data/render-profile digests.
- Conduct a separately budgeted prototype for approximate interactive layout
  preview only after snapshot is green.
- Record the Section 16.8 go/no-go decision; remove failed prototype code rather
  than leaving an unsupported half-feature.

**Deliverables:** exact Snapshot or a documented blocked gate with Test Map
retained; engine CLI tests; optional spike report and explicit live-preview
decision.

**Non-goals:** embedding `IRenderer`, exact interactive in-app gameplay,
renderer fork, continuous screenshot generation.

**Tests:** Section 19.18; current and invalid camera; fixed-tic deterministic
software capture; any optional renderer-specific path; cache/privacy; no
normal-engine behavior change; malformed/nonfinite/out-of-map camera input;
every used option/value consumed exactly once.

**Exit gate:** selecting a valid tile/angle produces and displays a bounded
exact EC7Wolf frame for the current export with positive result evidence and no
window/process leak; or, if a platform-blocking issue survives the time-boxed
attempt, Snapshot is explicitly deferred without delaying the completed editor.

**Required evidence:** capture commands/results including observed/fixed tic,
engine unit/integration tests, PNG metadata/digests stored only privately for
retail tests, source hashes, and the go/no-go report for approximate live view.

### E11 — Optional custom map-pack and MAPINFO workflow

**Dependencies:** E8–E9; explicit approval to expand beyond stock-slot export.

**Work:**

- Audit current MAPINFO grammar, load order, map names, music, colors, routing,
  secrets, skills, MAP30/MAP40/endgame behavior.
- Define a bounded project metadata schema and friendly campaign graph UI.
- Generate metadata-only lumps with escaping and validation.
- Add multi-map package manifest, dependency statement, and recipient-owned-data
  requirement.
- Engine-test campaign starts, normal/secret routing, return paths, and ending.

**Deliverables:** only if approved and proven: custom metadata editor/export,
documentation, and a test pack built entirely from synthetic maps.

**Non-goals:** arbitrary DECORATE/XLAT scripting, embedding retail art, general
mod IDE.

**Tests:** parser/generator, hostile strings, graph validation, load order,
synthetic campaign end-to-end, package content audit.

**Exit gate:** a wholly synthetic multi-map campaign starts, routes normal and
secret exits, and ends as specified using generated metadata, with no retail
content and no stock behavior regression.

**Required evidence:** source grammar audit, generated-lump diff, engine traces,
package manifest, security/content scan, and UX review.

**Decision:** E11 is optional and cannot block version 1 unless product scope is
deliberately revised.

**Status: shipped.** Approved 2026-09-01 and built. See
[ec7edit-mappack.md](ec7edit-mappack.md) for the surface and the engine
behavior behind it; `ec7edit_e11` is the gate.

The audit's three load-bearing findings:

- A `map` block **replaces** the level record rather than merging into it
  (`LevelInfoBlockParser` assigns `existing = newMap`), so a block for a stock
  slot is a replacement. Packs therefore default to MAP61 and up, above the
  MAP01-MAP60 the stock mapinfo defines, and a stock slot warns.
- `next = "EndTitle"` is the ending. Corridor 7 defines exactly one
  intermission (`DemoLoop`), so the `EndSequence, "..."` form has nothing to
  name in this game and is not offered.
- **Corridor 7 has no secret-exit tile.** `Exit_Normal` takes `ex_secretlevel`
  only when `arg0` is 2, and no translator entry sets that; what does is plane
  1, where `gamemap_planes.cpp` promotes a wall-63 cell's trigger when object
  99 sits on it. `secretnext` is therefore real but reachable only through that
  marker, which the validator asks for.

Two things the milestone listed are deliberately not built. Colors and skills
are not in the schema: `defaultfloor`/`defaultceiling` are palette-index
decisions that belong to a map rather than to a campaign, and a `skill` block
is global, so a pack that carried one would change the stock game's difficulty
levels -- the opposite of "no stock behavior regression". Both can be added
later without moving anything already written.

### E12 — Hardening, accessibility, documentation, CI, and release

**Dependencies:** all chosen release milestones; E11 optional.

**Work:**

- Complete security tests, fuzz regression corpus, performance, soak, fault
  testing, accessibility/manual matrix, and platform packaging.
- Freeze and report EC7Edit `0.1.0` plus commit/schema/catalog/capability build
  identity; run the exact E0 Windows/Ubuntu architecture and Python/Qt matrix.
- Finish Quick Start, tool/prefab help, validation reference, import/sharing
  guide, Test/Snapshot troubleshooting, CLI/developer docs, and release notes.
- Integrate all gates and legal skips into `run_gates.sh` and CI.
- Build Windows and Linux packages, license manifests, and uninstall/upgrade
  behavior.
- Run public artifact commercial-content audit.
- Rebuild EC7Wolf twice as required, run full data-free/data-dependent suites,
  refresh private `builds/release`, and run packaged startup from its directory.
- Perform final independent review through format, UX/accessibility,
  security/legal, and runtime/release lenses.

**Deliverables:** releasable editor packages; green gates; complete docs;
private fresh runnable package; evidence bundle; known-limitations list.

**Non-goals:** hiding known limitations, promoting EC7Wolf beyond beta, or
unapproved cloud/live-3D scope.

**Tests:** every applicable Section 19 gate; Windows/Linux clean-system startup;
manual matrix; full release commands in Section 20.10.

**Exit gate:** every Section 25 release checkbox is evidenced, public artifacts
are data-free, the private package starts and enters Corridor 7, no stop-line
item is open, and a first-time tester completes the core workflow without
source-format knowledge.

**Required evidence:** complete gate summary, package manifests/hashes, audit
report, manual test record, performance baseline, fresh package/startup output,
review signoffs, and final git status/diff check.

**Status: shipped, with two items explicitly outstanding.**

Built:

- `tools/package_ec7edit.sh` freezes the editor -- onedir, per the E4
  measurement -- into a directory that runs with no Python and no Qt on the
  machine. 74 MB compressed, 204 MB unpacked.
- `tools/test_ec7edit_release_startup.sh` runs that package from a copy
  elsewhere under `env -i`, with no python3 on PATH and a HOME of its own, and
  audits it for game data and for absolute paths from the build machine.
- `ec7edit --selftest` reports the build's identity -- version, Python, Qt,
  catalog, schema and protocol -- without a display or game data. It is the
  capability probe the plan asked for, and the thing to paste into a report.
- `docs/ec7edit-manual.md`: eighteen sections covering the whole product, with
  nine screenshots generated from the real editor by
  `editor/scripts/manual_shots.py` and regenerated on demand. The generator
  refuses to run with a data directory configured, which is what makes the
  images publishable.
- Gates `ec7edit_e12` (release consistency, data-free) and `ec7edit_package`
  (the packaged editor), both in `run_gates.sh` and in CI.
- CI builds and uploads the editor package. `make_release.py` emits it as its
  own download and inside the `-full` archive; the publish job's game-data
  audit already covers both.
- **EC7Edit carries the engine's version**, `1.0-betaN`, counted from the same
  commit by the same rule. This supersedes the plan's "freeze and report
  EC7Edit 0.1.0": one product under two version schemes made every report
  carry a relationship the reader had to work out.

Outstanding, and not claimed:

- **Windows and macOS packages are wired but unbuilt here.** The release
  workflow freezes the editor on each platform's own runner, and the packager
  handles the `.exe`/`.zip` cases, but only Linux x64 has actually been built
  and started. The first Windows release is the test.
- **The first-time-tester run has not happened.** The exit gate asks for
  somebody who has not seen the source to complete the core workflow, and no
  automated check substitutes for that.

### E13 — Custom resource packs

**Dependencies:** E11 (map packs); E12 (packaging). Approved 2026-09-02.

**The problem.** Everything up to here ships Corridor 7's own content. A map
pack carries maps and generated metadata and, by E11's explicit non-goal,
nothing else -- so a custom monster, a custom wall or a custom track has
nowhere to come from. Authors want a campaign of their own, not a rearrangement
of this one.

**What the engine already does, verified rather than assumed.** No engine work
is required for anything in this milestone:

- A `.pk3` is a zip and `--file` loads one. Which folder an entry sits in
  decides what the engine does with it -- `sprites/`, `textures/`, `graphics/`,
  `patches/`, `music/`, `sounds/`, `flats/`, and the root as ordinary lumps
  (`resourcefiles/resourcefile.cpp`). A pack produced by
  [corridor7-monster-sprite-workflow.md](corridor7-monster-sprite-workflow.md)
  is already in exactly this shape.
- **Maps inside a pk3 go in `maps/MAPxx.wad`**, not at the root. Archive
  entries are sorted alphabetically (`PostProcessArchive`), so a root `MAP61`
  is followed by `MAPINFO` rather than `PLANES` and the load fails with
  "Invalid map format". `gamemap.cpp` looks for `maps/<map>.wad` first and
  opens it as an embedded resource file. Confirmed working.
- **MAPINFO's per-map `translator` is honoured** at load
  (`gamemap_planes.cpp`), and **a translator may `include` another and keeps
  its tables** (`LoadXlat(..., included=true)` does not clear them). So a
  generated translator can ADD a word to Corridor 7's table rather than
  replacing it, and does so for one floor only.
- `DECORATE` supports `#include`, so several resource packs can be merged into
  one distributable without their actor files colliding.
- Per-map `music`, `Sky1`, `TitlePatch`, `HighScoresGraphic` and
  `CompletionString` already exist, and `intermission` blocks (`Image`,
  `Fader`, `Cast`, `Link`, `GotoTitle`) can be defined by a pack and reached
  with `next = EndSequence, "Name"`.

Proven end to end against a real resource pack before any of this was designed:
a map with object word 900 at tile (7,7), a generated translator including
`xlat/corridor7.txt` and mapping 900 to a custom actor, and the engine spawns
it at (7,7) on a pack-only floor with no stock behaviour changed.

**Work:**

- `ec7edit_core/resources.py`: open a `.pk3`, describe what is in it -- actors
  with what they inherit, replace and draw; sprites, textures, music, graphics;
  and the entries the engine ignores but the pack should still carry. Refuse a
  hostile one: names that escape the archive, absolute paths, Corridor 7's own
  data, absurd entry counts or sizes.
- Project schema: attached resources, stored the way map sources are -- the
  digest identifies it, the path is inert text, and opening a shared project
  never touches either.
- **Word allocation.** Custom things need map words. Object words are allocated
  from a high band Corridor 7 never uses; a custom wall re-textures a wall ID
  the map does not otherwise use, which the per-map translator confines to that
  floor. Allocation is recorded in the project so a word does not move under a
  map that already uses it.
- Translator generation: one `xlat/` lump per pack, `include`-ing the game's.
- Palette: custom actors and textures appear as placeable entries, marked as
  belonging to a resource, and disappear when it is detached.
- Pack export becomes a **single `.pk3`** when resources are attached -- maps
  as `maps/MAPxx.wad`, generated `MAPINFO` and translator, the resources merged
  in with their DECORATE `#include`d from the root, and the manifest. One file
  to hand somebody.
- Campaign: per-map music from an attached resource, and custom `intermission`
  screens for the ending.
- Validation: two resources declaring one actor name; a map using a word whose
  resource has been detached; `replaces` announced as the global switch it is.

**Deliverables:** resource import and inspection, custom placement, a
single-file pk3 pack, the campaign extras, documentation, and a gate that
builds a pack from a real resource and plays it.

**Non-goals:** authoring art or DECORATE in the editor (that is what the sprite
workflow is for); arbitrary XLAT scripting beyond generated placement entries;
sound effects; **custom videos, which are E14** because they need engine work.

**Tests:** pack reading and refusal; allocation stability across edits;
generated translator and MAPINFO; the pk3 layout; an end-to-end engine run
placing a custom actor from a real pack; no stock behaviour regression;
public-artifact audit of the built pack.

**Exit gate:** a project with an attached resource pack exports one `.pk3`
which, loaded beside nothing else, starts a campaign whose floors contain the
resource's actors at the tiles the editor placed them, with the stock game
unchanged.

### E14 — Custom cinematics

**Dependencies:** E13. **Not started.**

**The problem.** `C7Flic_Play` takes hard-coded names -- `SEQONE`, `SEQTHREE`,
`SEQFOUR` -- and reads `<name>.CO7` from a `video/` directory beside the game
data (`c7_flic.cpp`). A campaign cannot supply its own cinematic, and a
resource pack cannot carry one at all, because that path never looks in a
loaded archive.

**The two questions, and the answers this plan proposes:**

*Where does a video come from?* The engine gains the ability to play a
cinematic from a loaded resource, and MAPINFO gains a way to name it, so a
campaign's ending can be its own animation rather than Corridor 7's.

*What format?* **FLIC, and the editor learns to write it.** The engine already
decodes FLIC and has been doing so reliably since the cinematics work; adding a
modern container would mean bundling a video decoder, with its dependencies and
its licences, to play a fifteen-second animation. FLIC is 8-bit paletted, which
is what this game is, and the palette discipline the sprite workflow already
enforces applies unchanged. So the conversion belongs in the editor: frames in,
`.CO7` out, no new engine dependency and no new format. A modern video becomes
frames with one ffmpeg command, or the editor takes a folder of PNGs directly.

**Non-goals:** audio in cinematics; a general video player; replacing the CD's
own animations.

---

---

## 22. Concrete work breakdown and change management

### 22.1 Dependency graph

The critical path is intentionally 2D-first:

```text
E0 evidence/fixtures
 ├── E1 codec/WAD ───────────────┐
 └── E2 assets/catalog ───────┐  │
                              ▼  ▼
                         E3 model/project
                              │
                              ▼
                         E4 Qt shell
                              │
                              ▼
                         E5 playable 2D slice
                         ├───────────────┐
                         ▼               ▼
                  E6 semantics      basic launch seam
                         │               │
                         ▼               │
                  E7 validation          │
                         │               │
                         ▼               │
                  E8 persistence/export │
                         └───────┬───────┘
                                 ▼
                           E9 Test Map
                                 │
                                 ▼
                         E10 exact Snapshot
                                 │
                       optional live-view spike

E11 custom MAPINFO is optional after E8/E9.
E12 hardening/release closes every selected branch.
```

E2 may proceed in parallel with E1 after E0 freezes interfaces. E4 may begin
with synthetic adapters once E3 public interfaces stabilize. E6 semantic
families can be split among agents only when catalog/rule files have non-
overlapping ownership and one integrator controls shared interfaces.

### 22.2 Source-area checklist

| Source area | Expected work | Contract owner |
| --- | --- | --- |
| `editor/pyproject.toml`, generated build-info manifest | EC7Edit release/build/schema/catalog/protocol identity | Packaging/integrator lane |
| `editor/ec7edit_core/archive.py` | TED5/RLEW codec facade | Format lane |
| `editor/ec7edit_core/wad.py` | WAD and PLANES codec | Format lane |
| `editor/ec7edit_core/assets.py` | Palette/wall/sprite decode | Asset lane |
| `editor/ec7edit_core/catalog.py` | Stable semantic mappings | Asset/semantic lane |
| `editor/ec7edit_core/document.py` | Raw canonical model/revisions | Model lane |
| `editor/ec7edit_core/commands.py` | Transactions/undo | Model lane |
| `editor/ec7edit_core/transforms.py` | Copy/rotation/reflection | Model/semantic lane |
| `editor/ec7edit_core/rules.py` | Compound Corridor 7 write rules | Semantic lane |
| `editor/ec7edit_core/validation.py` | Diagnostics/reachability | Validation lane |
| `editor/ec7edit_core/project.py` | Schema/atomic save/recovery | Persistence lane |
| `editor/ec7edit_core/export.py` | Preflight and outputs | Format/persistence lane |
| `editor/ec7edit_core/discovery.py` | Engine/data profiles | Integration lane |
| `editor/ec7edit_core/engine_runner.py` | Safe launch plans | Integration lane |
| `editor/ec7edit_gui/*` | Thin Qt interaction/presentation | GUI lane |
| `editor/resources/editor_catalog.json` | Generated metadata | Generated; no hand drift |
| `editor/scripts/generate_catalog.py` | Reproducible source join | Asset/semantic lane |
| `tools/c7assets.py` | Consume shared decoders | Asset lane |
| existing lab-map tools | Consume shared codec | Format lane |
| `src/wl_main.cpp` | E9 editor capability/renderer-option dispatch; E10 capture-option dispatch | Engine lane, E9/E10 |
| `src/id_ca.cpp`, `src/wl_game.cpp`, or new `src/editor_protocol.*` | Distinct explicitly flushed preview-load and post-player-setup map-entry/session events | Engine lane, E9 |
| `src/r_capture.*` | Stable snapshot result/exit if required | Engine lane, E10 only |
| `tools/run_gates.sh` | Editor gate registry/classification | Integrator |
| new `tools/package_ec7edit.sh` and `editor/packaging/*` | Data-free platform package wrapper and freeze/spec backends | Packaging lane |
| new `tools/test_ec7edit*.sh` including release startup | Hosted/owned-data/two-package harnesses | QA lane |
| `tools/make_release.py` | Public allow-listed staging and editor artifact audit | Release lane |
| `.github/workflows/ci.yml`, `.github/workflows/release.yml` | Hosted/self-hosted gates and public release audit | Release lane |
| `docs/*`, README | User/developer truth | Integrator/docs lane |

Actual paths are confirmed in E0. Creating both `tools/ec7edit` and
`editor/ec7edit_core` as competing implementations is forbidden.

### 22.3 Suggested pull-request/change slices

Small reviewable changes, each green on arrival:

1. Evidence ledger, synthetic generators, and empty gate hooks.
2. Strict RLEW/TED5 core with migrated tests.
3. WDC3.1/WAD writer-reader and engine override gate.
4. Safe adapters for existing lab tools.
5. Shared palette/wall/sprite decoders and asset-browser migration.
6. Catalog generator and ordinary walls/objects.
7. Enemy/direction/rank mappings and transform tests.
8. Project schema/document/revisions.
9. Commands/undo/clipboard/transforms.
10. Atomic save/autosave/recovery and fault tests.
11. Qt shell/discovery/project browser.
12. Canvas/navigation/selection.
13. Wall/floor brushes and object/enemy/start placement.
14. Save/reopen/export and first playable vertical slice.
15. Doors/zones/transporters.
16. Moving/masked/animated walls, elevators, exits, prefabs.
17. Validator/Problems/reachability.
18. Production import/private archive export and all-map gate.
19. Test Map controller/log/session integration.
20. Snapshot engine seam, controller, and dock.
21. Packaging, CI, security, accessibility, docs, and release hardening.
22. Optional MAPINFO work only after a separate scope approval.

Slices may be smaller. They should not be combined merely to reduce PR count if
that hides format, GUI, engine, and packaging changes in one review.

### 22.4 Per-change review checklist

Every implementation change answers:

- Which requirement, decision, milestone, and diagnostic/catalog entry does it
  implement?
- What current source evidence establishes the behavior?
- Does it alter a raw format, project schema, catalog, command, UI, launch,
  packaging, or commercial-data contract?
- Are unknown values and plane 2 preserved?
- Can it write anywhere near retail data, source, release, or user-selected
  paths?
- Is every write atomic/recoverable and every process non-shell?
- Does any async result need a revision/owner guard?
- Are normal and failure paths tested without retail data?
- Is an owned-data or actual-engine gate also required?
- Does the GUI expose a friendly action and an accessible keyboard route?
- Are messages actionable and diagnostic codes stable?
- Does output/package auditing need a new rule?
- Are current docs and help updated in the same change?
- Were unrelated user working-tree changes left untouched?

### 22.5 Generated-file policy

Generated catalog or manifest changes include:

- generator source change;
- source-input manifest/digest update;
- generated diff;
- regeneration command;
- tests proving determinism and completeness.

Never hand-edit a generated raw mapping to make a test pass. Curated labels live
in a clearly separate source file merged by the generator.

### 22.6 Compatibility policy

During development, existing tools retain their documented CLI behavior while
their internals move to shared modules. A compatibility break needs an explicit
migration note and updated callers/tests in the same change. EC7Wolf normal
game launch/render behavior must remain identical when no editor/capture option
is supplied.

### 22.7 Evidence bundle per milestone

Store or report, without committing retail artifacts:

- branch/commit and dirty-state summary;
- changed-file list and ownership;
- commands and exact gate results;
- synthetic fixture/output hashes;
- owned-data test counts and source-before/after hashes in private logs;
- screenshots/recordings classification and private location if retail-derived;
- performance/fault/accessibility results as relevant;
- unresolved items and why they do not violate the exit gate;
- reviewer findings and dispositions;
- package/audit results for release milestones.

### 22.8 Definition of a safe handoff

An agent handing work to another provides:

- objective and milestone;
- files changed and files exclusively owned;
- current public interfaces and invariants;
- tests run with results;
- work not completed;
- known failures and reproduction;
- commercial-data artifacts created and their private location/cleanup status;
- exact next safe action.

“Mostly done, see the diff” is not a handoff.

---

## 23. Master AI-agent execution protocol

This section is mandatory for AI-agent implementation. It is also a useful
discipline for human contributors.

### 23.1 Authority and scope

Applicable system/platform/developer instructions and repository `AGENTS.md`
come first, followed by the active user request and this approved master plan;
current source/tests supply the factual implementation evidence. Higher-level
instructions always win on conflict. An agent may make small in-scope
implementation assumptions that do not change product behavior. It must stop
and request direction before:

- expanding to a general game editor, cloud service, or embedded engine;
- shipping approximate 3D as authoritative;
- changing commercial-data policy;
- enabling retail archive overwrite by default;
- adding a major dependency or platform;
- inventing unknown plane/actor semantics;
- changing EC7Wolf version/save-product fields or project icon artwork;
- discarding user-owned working-tree changes;
- weakening an exit gate to claim completion.

### 23.2 Primary integrator

One primary agent owns:

- current plan and milestone status;
- repository/status review and user communication;
- cross-lane interfaces and conflict resolution;
- final integration, tests, documentation, and package refresh;
- confirmation that no live child agent or process has unreported work;
- final evidence-backed completion report.

Subagents do bounded work; they do not independently redefine architecture or
declare the project complete.

### 23.3 Parallel-agent lanes

With four total agent slots, a useful maximum is one integrator plus three
bounded lanes:

| Lane | Good parallel work | Must not overlap |
| --- | --- | --- |
| Format/model | codec, WAD, schema, commands, pure tests | GUI and current engine source unless assigned |
| Assets/semantics | decoders, catalog, rule evidence, catalog tests | Generated output owned by another lane |
| GUI/QA/integration | Qt shell/canvas or gate harness/docs review | Core implementation files without interface agreement |

Later milestones may use engine snapshot, security/reliability, or packaging as
the third lane. File ownership is explicit before spawning work. Two agents do
not edit the same file concurrently, even if their conceptual tasks differ.

### 23.4 Required pre-work audit

Before editing in every milestone, the active agent:

1. Reads the applicable `AGENTS.md` files completely.
2. Reads this document's decisions, milestone, risks, and cited current source.
3. Runs `git status --short`, identifies pre-existing/unrelated changes, and
   records them as user-owned.
4. Re-reads exact current symbols and tests; line numbers in this plan may have
   moved.
5. Confirms no commercial files/artifacts are staged or about to be placed in
   source/package roots.
6. Confirms predecessor exit evidence and public interfaces.
7. Defines the bounded change, file ownership, tests, and exit evidence.
8. Updates the working plan before implementation.

If current source contradicts this plan, do not force the code to match stale
text. Record the evidence, assess product impact, and update/seek review of the
design decision.

### 23.5 Task brief for a subagent

Every delegated task states:

- canonical task name and milestone;
- concrete deliverable;
- exact files/directories it may edit;
- files/interfaces it may read but not change;
- source evidence to inspect;
- safety/commercial constraints;
- required tests and evidence;
- what is explicitly out of scope;
- how to report blockers and handoff.

Avoid delegating vague goals such as “work on the editor.”

### 23.6 During implementation

Agents must:

- preserve unrelated user changes and avoid cleanup churn;
- use the canonical core rather than copy format logic;
- apply small, reviewable patches;
- write or update tests with behavior changes;
- run the narrowest relevant test frequently, then the broader milestone gate;
- use only synthetic fixtures in the working tree;
- keep owned-data work in verified private temporary roots;
- record source hashes before and after any owned-data integration test;
- keep GUI thread and worker/revision boundaries explicit;
- keep process execution as structured argv/cwd/environment;
- update docs/help/catalog evidence with behavior changes;
- communicate progress at meaningful boundaries and before long-running gates;
- stop on a safety, source-corruption, or commercial-content anomaly.

### 23.7 Research and experiment rules

Read-only source/data inspection is encouraged. Experiments must be:

- hypothesis-driven with a written expected observation;
- isolated from source retail data;
- reproducible by command/tool/test;
- bounded in time and output;
- classified as synthetic or private commercial-derived;
- converted into an automated regression test if they establish a product
  contract;
- removed if they are a rejected spike and have no continuing test value.

Do not treat a one-off launch that “looked right” as final evidence.

### 23.8 Commercial-data agent protocol

Before any task touches `corr7/CORR7CD` or `builds/release`:

1. Confirm the operation is required and local/private.
2. Hash or otherwise fingerprint exact read-only inputs where relevant.
3. Create a dedicated private temporary/output path outside source and data.
4. Ensure commands cannot resolve outputs through symlinks into the input.
5. Do not print, attach, or commit decoded content.
6. Recheck source hashes afterward.
7. Inspect `git status` and public artifact roots for leaks.
8. Report private output location and cleanup/retention state.

The release package intentionally contains commercial files locally; its path
must remain ignored/uncommitted and its contents must not be sent as evidence.

### 23.9 Test discipline

An agent does not change a test solely to make new code green without first
showing why the old expectation was wrong. For a format or semantic change:

- cite current source/evidence;
- add a focused failing test first when practical;
- implement the smallest coherent fix;
- run focused, module, gate, and regression scopes proportional to risk;
- distinguish pass, expected/legal skip, and unexecuted;
- never accept a timeout before positive expected evidence;
- never report a gate as passing when output was truncated before its result.

### 23.10 Review lenses

Before milestone closure, conduct separate reviews:

#### Format and preservation

- Binary bounds and independent readback.
- All planes/unknowns preserved.
- Catalog/raw mappings exact.
- Determinism and compatibility.

#### UX and accessibility

- Point-and-click primary workflow.
- Plain-language names and feedback.
- Keyboard/accessibility/high-DPI.
- No expert-format knowledge required.

#### Security, privacy, and legal

- Untrusted input, paths, processes, writes, caches.
- No commercial or derived content leaks.
- Honest provenance/sharing warnings.
- No unsafe cleanup or overwrite.

#### Runtime and release

- Actual EC7Wolf load/entry evidence.
- Config/save/source isolation.
- CI/gate integration and platform package.
- Fresh private release package/startup.

One reviewer may perform multiple lenses, but findings/results remain separated
so a polished UI cannot obscure a format or legal defect.

### 23.11 Milestone closure

The integrator closes a milestone only after:

1. Work/deliverables are complete or an explicitly optional item is deferred.
2. Non-goals were not silently pulled into scope.
3. Exit gate is met literally.
4. Required focused and broader tests pass on the current tree.
5. Evidence bundle is complete and contains no retail data.
6. Review findings are resolved or explicitly accepted by authorized scope
   decision.
7. Docs/catalog/schema/version notes are current.
8. Git status/diff shows no accidental, generated, or commercial artifacts.
9. All subagents have returned and handoffs are incorporated.
10. The plan is updated to the next milestone.

### 23.12 Blocker protocol

On a blocker, agents first exhaust safe in-scope evidence:

- reproduce on a minimal synthetic case;
- inspect current source and existing tools/tests;
- compare independent parser/runtime behavior;
- try a safe alternate path that preserves product contracts;
- ask another bounded agent for an independent review when useful.

Then report:

- exact blocker and repeated observation;
- milestone/exit gate affected;
- commands, logs, and source evidence;
- what was ruled out;
- smallest choices available with tradeoffs;
- whether work can continue safely elsewhere.

Never bypass a blocker by disabling validation, writing retail source, treating
warnings as success, or deleting a failing test.

### 23.13 Commit and branch hygiene

- One conceptual change per commit when commits are requested/authorized.
- EC7Wolf's `1.0-betaX` derives from commit count; do not manually edit it.
- Do not modify `VERSION_MAJOR/MINOR/PATCH` to resemble the EC7Wolf marketing
  version; those fields protect save-product compatibility.
- Never regenerate or “improve” the user-owned application icon set.
- Do not commit private `builds/release`, retail data, projects, caches,
  screenshots, session directories, or owned-data logs.
- Recheck diff against the milestone's owned files and preserve pre-existing
  dirty work.
- Generated files require their generator/source in the same reviewed change.

### 23.14 Final project closure

The primary agent performs, in order:

1. Re-read current top-level instructions and Section 25.
2. Confirm all selected milestone exit gates and optional-defer decisions.
3. Confirm no live agents/processes or missing handoffs.
4. Run formatting/static checks and `git diff --check`.
5. Run complete hosted/data-free gates.
6. Build twice and run required owned-data/self-hosted gates.
7. Audit public artifacts for commercial/derived content.
8. Refresh `builds/release` with the required package script.
9. Run packaged startup from the fresh package directory.
10. Inspect final status/diff and retained private artifacts.
11. Report outcome first, then changed files, key decisions, tests, known
    limitations, and safe next step.

The final report never claims that optional approximate interactive 3D exists
when only Test Map (and, if E10 passed, Snapshot) shipped, and never calls the plan itself an
implemented editor.

---

## 24. Risk register and stop-the-line conditions

### 24.1 Risk register

Likelihood and impact are planning estimates, reviewed at each affected
milestone.

| ID | Risk | Likelihood | Impact | Mitigation and trigger |
| --- | --- | --- | --- | --- |
| R01 | A third subtly different map codec appears | Medium | Critical | One canonical core, compatibility shims, independent cross-reader tests; stop any GUI-local parser |
| R02 | RLEW/header edge case corrupts archive | Medium | Critical | Strict bounds, property/malformed tests, atomic write, full readback, engine gate |
| R03 | Unknown or plane-2 data is normalized | Medium | High | Raw arrays canonical, preservation tests, Advanced-only interpretation; any diff on untouched values stops release |
| R04 | Catalog mislabels a raw code or enemy variant | Medium | High | Generated source join, curated layer, coverage/test vectors, runtime spot tests; unresolved entries remain unavailable |
| R05 | Door orientation shown differs from engine | Medium | High | Share/mirror exact current inference with table tests; tie/corner warnings and engine examples |
| R06 | Compound tool leaves conflicting planes | Medium | High | Explicit write/erase contracts, atomic commands, per-prefab tests, validation |
| R07 | Removing walls writes zero instead of a valid zone | Medium | High | Separate carve/floor operation, default zone, tests and conflict preview |
| R08 | Thing erasure writes zero instead of 18 | Low after tests | High | Central empty constant/rule; no raw widget mutation; regression tests |
| R09 | Imported retail data leaks into source/public artifact | Medium | Critical | Root separation, allow-list package, derived-content classification, private gates, scans; immediate stop/removal/audit |
| R10 | Packaging copies editor cache from data directory | Medium | Critical | Never place cache/workspace in data/package roots; containment rejection; package audit |
| R11 | Editor overwrites `MAPTEMP.CO7` | Low by design | Critical | Read-only import, protected roots, new-path export, source hashes; normal source overwrite absent |
| R12 | Atomic save fails on Windows/filesystem edge | Medium | High | Platform-native temp/replace, readback, fault injection, recovery; document unsupported network FS behavior |
| R13 | Autosave/recovery deletes or replaces user work | Low | Critical | Separate recovery root, explicit chooser, exact manifest-owned cleanup, fault tests |
| R14 | UI freezes on decode/validation/export | Medium | Medium | Worker snapshots/cancellation, progressive images, incremental validation, budgets/profiling |
| R15 | Worker applies stale result to new document | Medium | High | Owner token and revision on every result, closure tests, immutable snapshots |
| R16 | Undo history diverges after compound/async edit | Medium | High | Core command preconditions, atomic transaction, reference-model randomized tests; no async mutation |
| R17 | Project schema becomes opaque or unmigratable | Medium | High | Versioned deterministic JSON, migrations and old/new tests, no semantic duplication |
| R18 | Preview WAD unintentionally includes all retail maps/assets | Medium | Critical | Allow-listed `MAPxx`/`PLANES` writer and lump scan; one-map default |
| R19 | `--data` is treated as a directory | Medium | Medium | Structured launch tests require cwd=data and `--data CO7`; actionable discovery message |
| R20 | Argument quoting permits injection or broken paths | Low with design | Critical | QProcess/argv only, fake-child hostile-path tests, no shell/environment editor |
| R21 | Test modifies ordinary config/saves | Medium | High | Absolute isolated `--config`/`--savedir`, hash/path tests, session ownership |
| R22 | Engine timeout is mistaken for map success | Medium | High | Require positive IWAD/preview/map-entry evidence; fatal-pattern scan |
| R23 | Test is launched against stale revision | Medium | Medium | Revision/export digest in state/log, stale badge, stop/test-latest flow |
| R24 | Renderer/editor/capture options are misparsed as files | High in inspected seam | Medium | E9 consumes ordinary renderer/protocol options; E10 audits every capture option/arity; zero bogus resource diagnostics |
| R25 | Snapshot flashes/leaks a game window or process | Medium | Medium | Hidden/editor mode only if tested, bounded exit, process/session leak gate; defer if not solved |
| R25a | Frame-number capture lands on varying simulation tics | High in current harness | Medium | Add fixed-tic/readiness snapshot seam or record observed tic without deterministic-cache claim |
| R25b | `--capture-file` under live OpenGL omits the GPU 3D world | High/current behavior | High | Pin v1 Snapshot to software; any GL support uses tested GL-specific PPM capture |
| R26 | Approximate 3D consumes project or is mistaken for exact | Medium | High | Post-core gated spike, strong label, time budget, remove on no-go, real Test Map authority |
| R27 | Embedding renderer expands into engine rewrite | Low if enforced | Critical schedule | Explicit non-goal/stop line; separate future project proposal |
| R28 | Reachability reports false certainty | Medium | Medium | Advisory wording, documented model limits, profile tests, playtest requirement |
| R29 | Target MAP30/MAP40 behavior surprises user | Medium | High | Target-slot model, inherited MAPINFO display, explicit warnings, exact-slot test |
| R30 | Header-name changes appear ineffective | High without UX | Low | Explain MAPINFO override in inspector/export report; future metadata milestone |
| R31 | Existing lab/asset tools regress during consolidation | Medium | Medium | Compatibility shims, preserve CLIs, existing tests, small migration slices |
| R32 | PySide6 packaging is too large or platform-fragile | Medium | Medium | Early E4 packaging smoke, allow-listed plugins, target-native build, clean VM tests |
| R33 | Qt is pulled into headless core | Medium | Medium | Import-boundary test, core runs without PySide6, architecture review |
| R34 | Retail asset decode consumes excessive memory | Medium | High | Bounded parsers, LRU byte cap, progressive decode, malformed tests |
| R35 | A malicious project causes path traversal/code execution | Low with controls | Critical | No executable schema, strict JSON, canonical paths, no bundle until hardened, security tests |
| R36 | Child log/output causes memory/disk exhaustion or rich-text injection | Medium | High | Bounded fragments/memory/session disk/global retention, continuous drain, escaping, flood/truncation tests |
| R37 | New map dimensions work in codec but fail gameplay | Medium | High | 64×64 creation fixed in v1; other dimensions imported/preserved with warning; engine gate before enabling resize |
| R38 | User interprets edited retail WAD as distributable | Medium | High legal/project | Provenance classification and repeated honest notices; private default path/report |
| R39 | Public catalog accidentally contains pixel/plane data | Low | Critical | Metadata schema and size/content audit, generated manifest, review |
| R40 | Unrelated dirty-tree work is overwritten | Medium in active repo | High | Pre-work status, explicit file ownership, narrow patches, final diff review |
| R41 | Documentation drifts from current source | Medium | Medium | E0 re-audit, source-linked contracts, docs with behavior changes, milestone closure review |
| R42 | Tests pass only with Jason's local layout | Medium | High | Explicit arguments, temp roots, synthetic hosted gates, clean VM/package tests |
| R43 | First release becomes a general mod IDE | Medium | High schedule | Version-1 non-goals and change-control authority; defer scripting/assets/MAPINFO breadth |
| R44 | Accessibility is postponed until UI architecture resists it | Medium | Medium | E4 names/tab order/scaling, offscreen checks each slice, manual matrix before release |
| R45 | Private release is stale after implementation | Medium | High project policy | Mandatory fresh package script and startup test in E12/final protocol |

### 24.2 Stop-the-line conditions

Stop the affected work immediately and do not claim milestone completion if:

- a retail source file hash changes after editor/tool/test activity;
- any commercial or derived map/image/cache appears in git status, a public
  staging directory, CI artifact, or proposed commit;
- a save/export can target source/data/release roots through a symlink or path
  normalization trick;
- parser arithmetic can overflow or allocate from an unbounded untrusted count;
- project/archive readback differs from intended canonical planes or metadata;
- an untouched imported unknown or plane-2 value changes;
- undo/redo cannot return exact model digest after a committed operation;
- an async worker mutates live state or applies across owner/revision boundaries;
- Test Map uses a shell, modifies ordinary config/saves, launches wrong IWAD,
  or reports success without positive map-entry evidence;
- capture options are treated as resource filenames or leave an unbounded child;
- approximate 3D is presented as engine-exact;
- a major dependency/license/package content cannot be audited;
- existing Corridor 7 gates regress and the cause is not understood;
- a failing test is weakened without evidence that its contract changed;
- current source contradicts a hard catalog/prefab rule;
- an agent cannot distinguish its changes from pre-existing user work;
- the fresh private package cannot pass its mandatory startup test.

### 24.3 Stop-line response

1. Preserve reproducible evidence without exposing retail content.
2. Halt writes/processes in the affected path.
3. Confirm source/user data safety and hashes.
4. Minimize the failure with synthetic input where possible.
5. Identify the violated invariant and affected outputs.
6. Fix root cause and add regression coverage.
7. Re-run the focused test, milestone gate, and relevant commercial/security
   audit.
8. Resume only when evidence shows the invariant restored.

### 24.4 Accepted bounded uncertainties

These do not block initial planning but remain visible:

- plane-2 authored semantics are incomplete; preservation is the resolution;
- target-slot/MAPINFO scope beyond stock behavior: settled by E11 (map packs);
- arbitrary dimensions wait behind 64×64 product default and engine tests;
- exact hidden snapshot behavior needs E10 platform evidence;
- approximate interactive layout view may receive a no-go decision;
- reachability is advisory rather than formal gameplay proof.

An uncertainty is not permission to invent behavior. The selected safe default
is part of the plan until evidence changes it.

---

## 25. Final completion checklist

The project is complete only when every applicable item is checked with current
evidence. “Deferred” is valid only for an item this plan explicitly marks
optional and must include the recorded decision.

### 25.1 Product and basic workflow

- [ ] First launch discovers/configures a compatible EC7Wolf and legal data
  directory with precise feedback.
- [ ] A user can create a safe 64×64 map without raw-format knowledge.
- [ ] A user can import any owned retail map read-only into a separate project.
- [ ] A searchable thumbnail palette supports choose-and-drag wall painting.
- [ ] Searchable object/enemy palettes support click placement.
- [ ] Enemy direction, patrol, and rank are friendly properties.
- [ ] Pointer, eyedropper, floor/zone, line/rectangle/fill, eraser, and selection
  behavior meet the defined contract.
- [ ] Undo/redo covers every edit and a drag/prefab is one command.
- [ ] Save/reopen and autosave recovery are reliable.
- [ ] Problems are continuous, clickable, actionable, and profile-aware.
- [ ] One-click Test Map enters the exact current override in EC7Wolf.
- [ ] Exact Snapshot either passes E10 or is explicitly deferred without
  misrepresenting Test Map.

### 25.2 Corridor 7 fidelity

- [ ] Plane 0, plane 1, and plane 2 are stored independently as exact uint16
  words.
- [ ] Plane-1 empty is 18; floor carve chooses a valid zone rather than zero.
- [ ] Unknown imported values survive every unrelated workflow.
- [ ] Nonzero plane-2 values survive import, project save, WAD export, and
  private archive export.
- [ ] Ordinary walls map to correct local thumbnails and native values.
- [ ] Doors use engine-equivalent topology/orientation and warnings.
- [ ] Locked doors and keys/access are labeled and reachability-aware.
- [ ] Moving, secret, masked, and animated walls use tested compound mappings.
- [ ] Zones, transporters, elevators, floor exits, and vortex/slot-specific
  behavior use semantic tools and validation.
- [ ] Starts, objects, hazards, weapons, enemies, paths, and rank filters map
  through the authoritative catalog.
- [ ] Every enabled composite prefab has source evidence and exact apply, erase,
  transform, undo, and engine tests.
- [ ] Native name versus MAPINFO display name and target-slot behavior are
  clearly represented.

### 25.3 Import, project, and export integrity

- [ ] Canonical codec is shared by editor and migrated repository tools.
- [ ] All format bounds and malformed inputs are tested.
- [ ] Project schema is versioned, deterministic, bounded, documented, and
  migration-tested.
- [ ] Save/export is atomic with post-write independent readback.
- [ ] Recovery fault matrix passes.
- [ ] One-map WAD contains exactly `MAPxx` + `PLANES` and no retail assets.
- [ ] Multi-map WAD markers are unique and ordered correctly.
- [ ] Private full archive preserves all untouched maps exactly at canonical
  level and obeys native length/count constraints.
- [ ] Retail source hashes are unchanged after import/export/playtest.
- [ ] Protected roots and symlink/path attacks are rejected.
- [ ] Provenance/share classification is visible in projects and exports.

### 25.4 Engine integration

- [ ] Direct launch uses cwd=data directory and `--data CO7`.
- [ ] `--file` preview loads after base data and provably overrides the intended
  marker.
- [ ] Config and saves are absolute, isolated, and outside retail/package roots.
- [ ] Rank is passed with verified 1-based semantics.
- [ ] Marker and `--tedlevel` always match.
- [ ] The direct engine profile, including a binary inside the private package,
  is capability-tested; any future POSIX launcher adapter passes its separate
  exact-launcher contract before being exposed.
- [ ] Process execution uses structured argv without a shell.
- [ ] Log parser requires positive IWAD/preview/map-entry evidence and detects
  fatal/parser/assert/sanitizer output.
- [ ] Stop/relaunch/orphan/session behavior is bounded and tested.
- [ ] Test saves are export-hash isolated or invalidated after edits.

### 25.5 3D scope

- [ ] Interactive exact preview is provided by the real Test Map flow.
- [ ] Snapshot capture arguments, fixed-tic/readiness, software PNG content,
  exit, output, and source isolation pass if Snapshot ships; any optional GL
  adapter passes its separate artifact contract.
- [ ] Snapshot cache is private, bounded, and classed commercial-derived.
- [ ] Any approximate layout view is unmistakably labeled nonauthoritative.
- [ ] The Section 16.8 go/no-go decision is recorded.
- [ ] No EC7Wolf renderer embedding or duplicated gameplay authority slipped
  into version 1.

### 25.6 UX, accessibility, and performance

- [ ] Core workflow is entirely point-and-click and entirely keyboard
  reachable.
- [ ] Every icon/control has accessible labeling and visible focus.
- [ ] Diagnostic/channel/zone/rank meaning is not color-only.
- [ ] 1280×720 and 100/150/200% DPI layouts are usable.
- [ ] Light/dark, large text, reduced animation, and keyboard-only manual checks
  pass.
- [ ] GUI remains responsive during archive, asset, validation, save/export,
  and engine work.
- [ ] Performance budgets and soak tests pass on documented baseline machines.
- [ ] Memory/cache/log/undo bounds are enforced.
- [ ] A first-time usability tester completes Quick Start without TED5/XLAT/WAD
  knowledge.

### 25.7 Security, privacy, and legal

- [ ] All untrusted parser, JSON, clipboard, path, log, and process tests pass.
- [ ] No scripts/eval/network behavior exists in project/catalog input.
- [ ] Cleanup targets exact application-owned paths only.
- [ ] No telemetry or automatic upload exists.
- [ ] Redacted bug reports exclude retail arrays/images and sensitive paths.
- [ ] Checked-in fixtures are synthetic with provenance.
- [ ] Public source/package/artifacts contain no retail or derived content.
- [ ] Imported retail projects/WADs/screenshots/caches are clearly classed local
  commercial-derived content.
- [ ] User-authored sharing guidance requires recipients to supply owned data.
- [ ] License and ownership notices are present.

### 25.8 Tests and release

- [x] `editor_core`, `editor_gui`, and synthetic package gates pass.
  *(`ec7edit_e0`..`e12`, `ec7edit_package`; 841 unit/GUI tests.)*
- [ ] Owned-data import of all 60 maps passes with source hashes unchanged.
- [ ] Engine export-load and playtest gates pass.
- [ ] Snapshot gate passes if feature ships.
- [ ] Existing noneditor Corridor 7 gates remain green.
- [x] Catalog regeneration and public artifact audit pass.
  *(`ec7edit_e12`: no game data in 1230 tracked files, and the manual's
  screenshot generator refuses to run with a data directory configured.)*
- [ ] Windows x64 and Linux supported packages start on clean systems.
  *Linux x64 evidenced by `ec7edit_package`, which starts the package from a
  copy under `env -i` with no Python on PATH. Windows is wired into the release
  workflow and not yet built.*
- [x] Documentation and validation references match current behavior.
  *(`ec7edit_e12` regenerates both and compares; the manual's tools, commands
  and panels are checked against the code that implements them.)*
- [ ] Format, UX/accessibility, security/legal, and runtime/release reviews have
  no unresolved stop-line finding.
- [ ] Fresh release build was built twice as required.
- [ ] `builds/release` was freshly rebuilt with
  `tools/package_corridor7_release.sh` from the optimized build and owned data.
- [ ] `tools/test_corridor7_release_startup.sh builds/release` passed from the
  packaged copy.
- [ ] Final status/diff contains only intended code/docs/generated metadata and
  no commercial/private artifacts.

---

## 26. Decision ledger and open questions

### 26.1 Closed decisions

| Decision | Selected answer | Reopen only if |
| --- | --- | --- |
| Product form | Standalone desktop editor | A demonstrably lower-risk architecture satisfies all native workflow and tests |
| UI stack | Python 3.10-compatible core; PySide6/Qt Widgets GUI with Python 3.12 reference frozen runtime | E4 packaging/prototype fails a hard supported-platform requirement |
| Core dependency | Qt-free pure Python | Never for convenience; only a reviewed fundamental constraint |
| Canonical map model | Exact three uint16 planes | Native format/runtime evidence changes |
| New-map size | 64×64 in version 1 | Arbitrary-size authoring passes engine and UX milestone |
| Normal export | Small WAD with `MAPxx` + `PLANES` | Engine compatibility disproves the established seam |
| Native export | Explicit private full archive | Product/legal policy changes with equal safety |
| Source import | Read-only | No ordinary reason; in-place overwrite is separate Advanced scope |
| Playtest | External EC7Wolf process with later override | Engine gains a stable safer API in a separate project |
| Exact interactive 3D | Test Map | A supported embeddable engine renderer is deliberately built |
| In-editor 3D | Attempt exact external Snapshot after core; ship only if E10 passes; approximate live view separately gated | E10 evidence changes cost/utility |
| UWMF | Not needed for MVP | A later interoperability requirement justifies a lossless writer |
| MAPINFO | Stock slot context for previews; generated campaign metadata for packs (E11) | Superseded: approved and tested |
| Plane 2 | Preserve, Advanced raw only | Source/runtime research establishes complete authoring semantics |
| Commercial data | Local/read-only/no public derivatives | Never weakened by convenience |
| Gate entry | `tools/run_gates.sh` | Project-wide test policy changes |

### 26.2 Open product choices with defaults

#### Final name

Default: **EC7Edit** in working copy and **EC7Wolf Corridor 7 Level Editor** in
user-facing title until Jason selects a final name. Resolve before package/MIME
registration. Renaming must not churn internal stable schema/catalog IDs.

#### Source directory name

Default: `ECWolf/editor/` with `ec7edit_core` and `ec7edit_gui`. Resolve at E0
against current packaging conventions. Do not split implementation between
`tools/` and `editor/`; compatibility launchers may live in `tools/`.

#### Project extension and container

Default: one UTF-8 `.ec7project` JSON file. Revisit only if measured project
size or future project-owned assets require a bundle. A bundle triggers the
full archive-extraction threat model first.

#### Private path storage

Default: engine/data paths live in per-user profile settings; projects store a
profile hint and fingerprints, with optional clearly local source provenance.
Resolve portability details during E3/E4.

#### Full archive source overwrite

Default: do not implement. “Export complete private archive” to a new path
satisfies the requested extraction/edit flow. A future overwrite feature needs
separate explicit authorization, backup UX, and fault/security gates.

#### Snapshot renderer and frame

Default: explicitly force the software renderer and capture only after a tested
map-ready/fixed-simulation-tic condition. A raw frame number is not that
condition. E10 measures window behavior and visual utility; OpenGL is exposed
only through its separate tested GL capture/artifact path.

#### Approximate interactive layout preview

Default: no commitment. Run only the post-Snapshot time-boxed spike and apply
Section 16.8. Test Map alone is a complete acceptable version-1 outcome when
E10 defers; Test Map plus Snapshot is complete when E10 passes.

#### Rectangular and resized maps

Default: import/preserve legal dimensions with warning; create only 64×64; no
resize tool. Enable more only after codec, engine, tools, canvas, prefab,
boundary, reachability, and UI tests.

#### Multiplayer map authoring profile

Default: preserve/import network/archive slots, but do not advertise a complete
multiplayer authoring validator until current multiplayer spawn/object/map
semantics are audited. This can be an additive profile.

#### Public package with bundled EC7Wolf

Version-1 decision: do not bundle EC7Wolf. The separate public editor locates a
compatible installed engine or the direct binary in the private package.
Reconsider only post-v1 through a new size, licenses/notices, update model,
capability, launcher, platform, and public-artifact audit; no future choice may
bundle retail data.

#### Persistent retail thumbnail cache

Default: memory cache on; bounded private disk cache off until user enables it
with a clear commercial-derived-content explanation. E4/E5 performance decides
whether an opt-in disk cache materially helps.

#### Custom user prefabs

Default: deferred. Built-ins are code/catalog-reviewed. User prefab files need
a bounded non-scriptable schema, provenance warnings, transforms, validation,
and commercial-content guidance.

### 26.3 Research questions assigned to milestones

| Question | Milestone | Safe default until resolved |
| --- | --- | --- |
| Exact catalog coverage and names for all raw enemy/special values | E2/E6 | Unresolved values Advanced/import-only |
| Complete health-chamber rotation/erase structure | E6 | Recognize/preserve; do not offer creation prefab |
| Exact role of each nonzero plane-2 value | future research | Preserve raw, no semantic edits |
| Whether any legal map has an intentionally open boundary | E7 owned-data/source audit | Hard boundary error for supported authoring |
| Exact key/rank reachability semantics | E7 | Source-backed subset and advisory warnings |
| Stable machine-readable engine map-entry output | E9 | Versioned log parser plus raw log |
| Clean fixed-tic software snapshot on Windows/Linux; optional GL-specific adapter | E10 | Ship software only, or defer Snapshot if even that path is unreliable |
| Custom MAPINFO grammar/export surface | E11 | Settled: bounded schema, MAP61+ by default, no colors or skills |
| Linux frozen versus system-PySide6 package | E4/E12 | Source/system package with precise dependency check |

---

## 27. Primary references and provenance

This plan relies first on current repository source and executable tests. The
implementation must update links/symbol notes as files move. Paths labeled
“local workspace” are current evidence outside the ECWolf git root; they are
intentionally not hyperlinks, are not distributed in a normal clone/source
archive, and cannot be copied into public source before E0 provenance and
license approval. The document restates every contract needed to reimplement
them independently.

### 27.1 Project policy and user documentation

- Local workspace `../AGENTS.md` — private release refresh, commercial-data
  prohibition, versioning, and icon policy; platform/repository instructions
  still govern even though this local policy file is not distributed here.
- [Repository README](../README.md) — product identity, data requirements,
  build/package commands, version lineage, and documentation index.
- [Corridor 7 single-player support](corridor7.md) — required retail inputs,
  ownership boundary, supported maps/features, launch examples, and established
  deviations/evidence.
- [Continuous integration](ci.md) — one gate entry point and hosted versus
  self-hosted data split.
- [Installer design](installer.md) — established headless Python core,
  PySide6 shell, Windows freeze, and offscreen-gate approach.
- [Renderer phase-0 baseline](renderer/phase0-baseline.md) — tracked precedent
  for source-grounded commands, explicit matrices, evidence, and milestone exit
  gates. Local untracked planning documents are not assumed to ship with this
  guide.

### 27.2 Native map format and codecs

- Local workspace `../tools/python/corridor7_map.py` — useful TED5 model, RLEW
  reader/writer, archive parse/rebuild, and diagnostic CLI with the documented
  production gaps.
- Local workspace `../tools/python/test_corridor7_map.py` — synthetic native
  format tests.
- [`file_gamemaps.cpp`](../src/resourcefiles/file_gamemaps.cpp) — EC7Wolf
  native archive recognition, bounds, records, RLEW validation, MAP/PLANES
  exposure.
- [`wolfmapcommon.cpp`](../src/resourcefiles/wolfmapcommon.cpp) — decompression
  and WDC3.1 PLANES construction.
- Local workspace `../analysis/reports/corridor7-map-format.md` and
  `../analysis/reports/corridor7-file-formats.md` — prior evidence and format
  notes, subordinate to current source/tests.

### 27.3 Runtime map semantics

- [Corridor 7 XLAT](../wadsrc/static/xlat/corridor7.txt) — authoritative
  plane-value translations, walls, doors, areas, specials, things, enemies,
  directions, and rank mappings.
- [`gamemap_planes.cpp`](../src/gamemap_planes.cpp) — WDC3.1 consumption,
  door topology, walls/masked/animated behavior, sectors, transporters, and
  native-plane conversion.
- [`gamemap.cpp`](../src/gamemap.cpp) and
  [`gamemap.h`](../src/gamemap.h) — map resource selection, PLANES acceptance,
  runtime map/cell state, serialization, and boundary-sensitive access.
- [`lnspec.cpp`](../src/lnspec.cpp) — areas, dynamic walls, elevators/exits, and
  Corridor-specific specials.
- [`a_playerpawn.cpp`](../src/g_shared/a_playerpawn.cpp) — interactive wall
  panels and health-chamber behavior.
- [Corridor 7 MAPINFO](../wadsrc/static/mapinfo/corridor7.txt) and
  [`g_mapinfo.cpp`](../src/g_mapinfo.cpp) — skills, display metadata, campaign,
  bonus/network slots, routing, and native-name override.
- [Corridor 7 actors](../wadsrc/static/actors/corridor7/) — statics, monsters,
  player classes, sprite/state/behavior metadata.
- Local workspace `../analysis/reports/corridor7-resource-id-map.md` and
  `../analysis/reports/open-questions.md` — prior mapping and unresolved
  evidence, never stronger than current runtime source.

### 27.4 Assets

- [`tools/c7assets.py`](../tools/c7assets.py) and
  [asset-browser README](../tools/README-c7assets.md) — existing read-only
  in-memory palette, wall, sprite, VGA, actor, and map browser.
- Local workspace `../tools/python/corridor7_gfxtiles.py` — defensive graphics
  helper pending provenance review.
- [`file_vswap.cpp`](../src/resourcefiles/file_vswap.cpp) — graphics archive
  recognition, headers, and Corridor palette extraction.
- [`flattexture.cpp`](../src/textures/flattexture.cpp) and
  [`wolfshapetexture.cpp`](../src/textures/wolfshapetexture.cpp) — wall and
  post/column sprite decoding.
- [`lumpremap.cpp`](../src/lumpremap.cpp) and
  [IWAD info](../wadsrc/static/iwadinfo.txt) — runtime lump naming/remapping and
  required Corridor 7 resources.

### 27.5 Existing generation and validation tools

- Local workspace `../tools/python/make_corridor7_lab_map.py` — map
  replacement/new-room transformation patterns with a known unsafe
  source/output and non-atomic direct-write gap; not a safety precedent.
- [`make_corridor7_ai_lab.py`](../tools/make_corridor7_ai_lab.py) and
  [`make_corridor7_mp_lab.py`](../tools/make_corridor7_mp_lab.py) — generated
  test-map consumers of the native codec.
- Local workspace `../tools/python/validate_corridor7_campaign.py` —
  player-start, reachability, exit, and campaign/secret checks pending
  provenance review.

### 27.6 Load order, CLI, and capture

- [`wl_main.cpp`](../src/wl_main.cpp) — `--data`, `--file`, `--config`,
  `--savedir`, `--tedlevel`, `--skill`, `--nowait`, resource load order, and
  current capture-option consumption.
- [`w_wad.cpp`](../src/w_wad.cpp) — later-loaded lump lookup precedence.
- [`config.cpp`](../src/config.cpp) — explicit config-path behavior.
- [`r_capture.h`](../src/r_capture.h) and
  [`r_capture.cpp`](../src/r_capture.cpp) — screenshot/checksum harness,
  bounded frame/tic, RNG seed, tile/angle warp, and the explicit distinction
  between rendered frames and simulation tics.
- [`r_renderer.h`](../src/render/r_renderer.h),
  [`r_worldbuilder.h`](../src/render/r_worldbuilder.h), and
  [`r_worldbuilder.cpp`](../src/render/r_worldbuilder.cpp) — renderer/global
  game-state coupling that makes embedding a separate project.
- [Packaged launcher](../tools/corridor7-release/run-corridor7.sh) — package cwd,
  local config/saves, renderer default, and argument forwarding.

### 27.7 Gates and packaging

- [`tools/run_gates.sh`](../tools/run_gates.sh) — canonical test entry and gate
  classification.
- [`tools/test_installer_gui.sh`](../tools/test_installer_gui.sh) — real PySide6
  offscreen test precedent.
- [`tools/test_corridor7.sh`](../tools/test_corridor7.sh) and
  [`tools/validate_corridor7_maps.sh`](../tools/validate_corridor7_maps.sh) —
  data-dependent Xvfb/runtime harness conventions.
- [`tools/package_corridor7_release.sh`](../tools/package_corridor7_release.sh)
  — fresh private package, double build, validation, and staged replacement;
  replacing an existing directory currently has a non-atomic remove/rename
  gap.
- [`tools/test_corridor7_release_startup.sh`](../tools/test_corridor7_release_startup.sh)
  — mandatory title/menu/MAP startup against the package from its directory.
- [CI workflow](../.github/workflows/ci.yml) and
  [release workflow](../.github/workflows/release.yml) — hosted/self-hosted
  execution and public commercial-data audits.

### 27.8 Provenance rule

When source, tool, report, and observation disagree:

1. Preserve the raw data.
2. Reproduce with a minimal test.
3. Prefer current runtime source plus executable behavior.
4. Record whether behavior is an EC7Wolf target, original-retail observation,
   or product proposal.
5. Update the catalog/evidence ledger and this document in the same reviewed
   change.

---

## Appendix A — Compact user workflows

### A.1 Create, paint, place, and test

```text
New Project
  → choose safe workspace
  → Closed Room 64×64
  → select Walls tab and texture
  → drag on canvas
  → select Enemies and enemy card
  → choose direction/rank
  → click floor cell
  → place/move player start if needed
  → inspect Problems
  → Save
  → Test Map
  → play in EC7Wolf
```

### A.2 Import and edit a stock map safely

```text
Import from Corridor 7 Archive
  → choose configured legal data profile
  → read-only hash/parse
  → choose MAPxx thumbnail
  → acknowledge local commercial-derived project
  → choose separate project path
  → edit through semantic tools
  → Save project
  → export private preview WAD
  → Test Map through --file override
  → source hash confirmed unchanged
```

### A.3 Place a locked door

```text
Doors & Specials → Red Access Door
  → hover corridor cell
  → preview engine-inferred axis and approaches
  → click to place
  → Problems warns if no red key is reachable
  → place/redesign key route
  → validation clears or remains an intentional warning
```

### A.4 Place a transporter pair

```text
Zones & Transporters → Channel A → Place Pair
  → click first valid floor cell
  → preview pending link
  → click second valid floor cell
  → one command writes both floors and both visuals
  → overlay shows A on both ends
  → undo removes both together
```

### A.5 Recover work

```text
Editor restarts after crash
  → recovery chooser shows project, saved revision, autosaved revision
  → Open Recovered Copy
  → compare summary / inspect map
  → Save As or replace normal project deliberately
  → obsolete recovery removed only after successful save/close
```

### A.6 Exact 3D snapshot

This workflow is present only when E10 passes; otherwise the product points
directly to Test Map.

```text
3D Camera tool
  → click walkable tile and choose angle
  → Refresh Snapshot
  → current revision validates and exports privately
  → EC7Wolf captures bounded exact frame
  → dock shows image plus revision/camera/renderer
  → Test Map for interactive behavior
```

---

## Appendix B — Project schema example

This compact 5×5 synthetic example illustrates schema shape. It is not the
normal 64×64 creation template and is intentionally free of retail content.
The exact v1 keys are frozen during E3.

```json
{
  "schema_version": 1,
  "project_id": "6b0986a7-58ce-4769-8f24-24785e7537e7",
  "name": "Synthetic Example",
  "content_provenance": "user_original",
  "catalog_version": "c7-editor-1",
  "source": null,
  "maps": [
    {
      "map_id": "fae0dd98-2af5-4f59-88e3-7efec5a30771",
      "native_name": "SYNTH",
      "native_name_raw_hex": "53594e54480000000000000000000000",
      "target_slot": "MAP01",
      "width": 5,
      "height": 5,
      "planes": [
        [
          [1, 1, 1, 1, 1],
          [1, 256, 256, 256, 1],
          [1, 256, 256, 256, 1],
          [1, 256, 256, 256, 1],
          [1, 1, 1, 1, 1]
        ],
        [
          [18, 18, 18, 18, 18],
          [18, 18, 18, 18, 18],
          [18, 18, 19, 18, 18],
          [18, 18, 18, 18, 18],
          [18, 18, 18, 18, 18]
        ],
        [
          [0, 0, 0, 0, 0],
          [0, 0, 0, 0, 0],
          [0, 0, 0, 0, 0],
          [0, 0, 0, 0, 0],
          [0, 0, 0, 0, 0]
        ]
      ],
      "annotations": {
        "notes": [],
        "regions": []
      }
    }
  ],
  "export_defaults": {
    "format": "preview_wad",
    "validation_profile": "single_player_stock_slot",
    "test_rank": "lieutenant"
  },
  "extensions": {}
}
```

An imported local source reference, if stored in the project rather than only
the profile store, has explicit provenance fields such as:

```json
{
  "kind": "corridor7_native_archive",
  "classification": "commercial_derived_local",
  "display_path": "/user-selected/local/path/MAPTEMP.CO7",
  "sha256": "hex digest",
  "imported_map_index": 0,
  "imported_map_hash": "canonical map digest"
}
```

`display_path` may remain as inert project-local UX text, but it is never
opened, statted, contacted, or trusted automatically. The actual trusted path
association is per-user profile state and requires explicit relink as described
in Sections 7.4 and 8. No source bytes or thumbnails are embedded.

---

## Appendix C — Initial validation catalog

Codes are provisional until E7 freezes the machine-readable catalog, but
their conditions and severity policy are requirements.

| Provisional code | Default severity | Condition | Suggested action |
| --- | --- | --- | --- |
| `C7E-SCHEMA-001` | Error | Unsupported newer project schema | Open with a newer editor or export through a compatible version |
| `C7E-SCHEMA-002` | Error | Plane row/count/type mismatch | Restore project/recovery copy; inspect schema details |
| `C7E-NATIVE-001` | Error | Native signature or record structure is invalid | Choose a valid archive; preserve source for diagnosis |
| `C7E-NATIVE-002` | Error | RLEW stream malformed or wrong expanded size | Reject import/export; inspect exact map/plane |
| `C7E-NATIVE-003` | Error | Encoded plane exceeds 16-bit native length | Simplify value pattern or use preview WAD; do not truncate |
| `C7E-NATIVE-004` | Error | Newly created/renamed canonical name is not encodable in the safe 15-byte policy, or its text/raw pair mismatches | Shorten/use supported ASCII, or undo the rename; unchanged imported raw bytes are not rejected |
| `C7E-NATIVE-005` | Warning | Engine-compatible archive omits the conventional final `!ID!` | Preserve on import; canonical writer adds the terminator |
| `C7E-NATIVE-006` | Warning | Valid stream contains a noncanonical zero-count RLEW triple | Preserve decoded meaning; canonical writer emits no zero-count run |
| `C7E-NATIVE-007` | Information | Unchanged imported 16-byte name has noncanonical post-NUL or display bytes | Preserve exact raw field; rename only if the user wants canonical replacement |
| `C7E-WAD-001` | Error | Target marker invalid or mismatched | Choose a valid supported marker such as stock `MAP01`–`MAP60`; the codec can represent the loader's bounded `MAP100` case |
| `C7E-WAD-002` | Error | PLANES size/header does not match document | Re-export; report internal mismatch if generated by editor |
| `C7E-BOUNDARY-001` | Error | Outer boundary contains a walkable/open cell | Paint a solid border wall |
| `C7E-CELL-001` | Error | Raw value is outside uint16 range | Restore/replace exact invalid value |
| `C7E-CELL-002` | Warning | Unknown imported raw tuple preserved | Inspect Advanced details; leave unchanged if intentional |
| `C7E-CELL-003` | Error | Newly introduced unknown raw tuple | Choose a catalog item or explicitly resolve Advanced mapping |
| `C7E-CELL-004` | Error | Incompatible meanings share plane-1 cell | Remove/replace one semantic feature |
| `C7E-CELL-005` | Information | Nonzero plane-2 value preserved | No action unless intentionally researching raw plane 2 |
| `C7E-CELL-006` | Warning | Plane-2 value changed in Advanced mode | Confirm intent and retain backup/source comparison |
| `C7E-START-001` | Error | No single-player start | Place one player start on legal floor |
| `C7E-START-002` | Error | Multiple single-player starts | Move/delete extras for the selected profile |
| `C7E-START-003` | Error/Warning | Start is blocked or suspicious | Move start to clear reachable floor |
| `C7E-DOOR-001` | Warning | Door lacks two opposing floor approaches | Reshape corridor or confirm the one-sided/stock-compatible topology; new placement may require confirmation |
| `C7E-DOOR-002` | Warning | Door axis tie/corner ambiguity | Adjust neighboring geometry and inspect preview |
| `C7E-DOOR-003` | Warning | Locked door has no matching key | Place key or change door type |
| `C7E-DOOR-004` | Warning | Key appears trapped behind all matching doors | Redesign access route or verify special route in game |
| `C7E-WALL-001` | Error | Wall modifier has incompatible base wall | Choose a supported base/material or remove modifier |
| `C7E-WALL-002` | Warning | Pushwall has no plausible movement runway | Clear destination/path or verify intentional behavior |
| `C7E-WALL-003` | Error | Animated wall lacks required frame mapping | Choose a valid animated base or ordinary wall |
| `C7E-WALL-004` | Error | Secret elevator marker lacks required base wall | Place through Secret Elevator prefab |
| `C7E-ZONE-001` | Error/Warning | Reachable floor has no supported area zone | Error for newly authored normal single-player floor; warning for preserved imported/network/Advanced content; paint/infer a zone such as 256 |
| `C7E-ZONE-002` | Warning | Area is unusually fragmented/isolated | Inspect sound-zone overlay and merge if unintended |
| `C7E-ZONE-003` | Information/Warning | Ambush/fill area 278 used | Confirm source-backed intended behavior |
| `C7E-WARP-001` | Error | Transporter channel has other than two endpoints | Add/remove/reassign endpoint through pair tool |
| `C7E-WARP-002` | Warning | Endpoint lacks conventional field visual or visual is orphaned | Optionally apply transporter visual repair |
| `C7E-EXIT-001` | Warning/Error | No supported completion mechanism for profile | Place valid intended-slot exit |
| `C7E-EXIT-002` | Warning | Floor exit lacks conventional visual or visual is orphaned | Optionally apply Floor Exit visual repair |
| `C7E-EXIT-003` | Warning | MAP30/MAP40/bonus behavior is slot-sensitive | Test exact intended slot and review MAPINFO context |
| `C7E-THING-001` | Error | Floor thing is placed on incompatible wall/void | Move item or carve valid floor |
| `C7E-THING-002` | Warning | Blocking thing obstructs start/critical corridor | Move it or verify intended obstacle |
| `C7E-THING-003` | Error | Enemy property has no exact native variant | Choose supported direction/patrol/rank combination |
| `C7E-THING-004` | Warning | Patrolling enemy has no plausible marker route | Add/fix path markers or make stationary |
| `C7E-ROUTE-001` | Warning | No modeled start-to-exit path | Inspect unreachable overlay, keys, doors, and warps |
| `C7E-ROUTE-002` | Warning | Significant unreachable region/content | Connect it or confirm secret/decoration intent |
| `C7E-SOURCE-001` | Error | Source archive changed since import | Reimport/rebase or choose verified original source |
| `C7E-SOURCE-002` | Error | Operation would write protected retail source | Choose separate project/export path |
| `C7E-EXPORT-001` | Error | Output resolves inside protected root | Choose a safe workspace/export directory |
| `C7E-EXPORT-002` | Error | Atomic output readback differs | Retain old file; report exporter/internal error |
| `C7E-LICENSE-001` | Warning | Imported retail-derived map targets public-looking export | Keep private; export only original author-owned content publicly |
| `C7E-ENGINE-001` | Error | Engine/data profile incomplete or incompatible | Repair profile using exact checklist |
| `C7E-ENGINE-002` | Error | Preview loaded but intended map entry not observed | Inspect marker/tedlevel/load log |
| `C7E-ENGINE-003` | Error | Engine fatal/parser/assert/sanitizer output | Stop test and inspect highlighted raw log |
| `C7E-ENGINE-004` | Warning | Running test is older than current document | Stop and test latest revision |

Severity may vary by validation profile only through an explicit table and
test; it is never changed ad hoc by the GUI.

---

## Appendix D — Default keyboard and mouse contract

All shortcuts are configurable where platform conventions permit. Menus remain
the discoverable authority, and text fields suppress conflicting map shortcuts.

| Action | Default |
| --- | --- |
| New project | `Ctrl+N` |
| Open project/import chooser | `Ctrl+O` |
| Save / Save As | `Ctrl+S` / `Ctrl+Shift+S` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` (and platform `Ctrl+Y` alias if appropriate) |
| Cut / Copy / Paste / Duplicate | `Ctrl+X` / `Ctrl+C` / `Ctrl+V` / `Ctrl+D` |
| Delete selected semantic target | `Delete` or `Backspace` |
| Pointer/select | `S` |
| Wall brush | `B` |
| Floor/zone brush | `G` or tool-configured key |
| Eyedropper | `I`; temporary while holding `Alt` if conflict-free |
| Eraser | `E` |
| Line / Rectangle / Fill | `L` / `R` / `F` only when not reserved by view context |
| Pan | middle drag or hold `Space` + left drag |
| Zoom | `Ctrl++`, `Ctrl+-`, wheel around cursor |
| Fit map | `Home` or menu-visible configured key |
| Select all / none | `Ctrl+A` / `Ctrl+Shift+A` |
| Rotate clockwise/counterclockwise | `]` / `[` on a transformable selection/tool |
| Flip horizontal/vertical | menu plus configurable shortcuts |
| Toggle grid | `Ctrl+'` or platform-safe configured key |
| Validate now | `F7` |
| Test Map | `F9` |
| Stop Test | `Shift+F9` |
| Refresh Snapshot | `F10` after E10 |
| Focus palette search | `Ctrl+F` |
| Focus Problems | `Ctrl+Shift+M` or configurable |
| Cancel current gesture/tool substep | `Esc` |

Pointer behavior:

- Primary click commits the active tool when valid.
- Primary drag paints/selects according to active tool.
- Secondary click opens a context menu; it never erases by surprise.
- Middle drag pans.
- Wheel zoom/pan preference is explicit.
- Shift adds/constrains; Ctrl toggles selection; modifier behavior appears in
  the status bar.

Final shortcuts receive a conflict/accessibility/platform review during E4/E5.

---

## Appendix E — Minimum bug report

The built-in **Copy Redacted Bug Report** produces:

```text
EC7Edit version/build:
EC7Wolf version/lineage/capabilities:
OS/architecture:
Python/PySide6 (source package only):
Renderer/test profile:
Operation and stable diagnostic code:
Expected result:
Observed result:
Minimal reproduction using synthetic/original user map if possible:
Project schema/catalog version:
Map dimensions and target slot:
Project revision/export hash prefix:
Validation counts:
Child exit status and redacted relevant log lines:
Recovery/session state:
Tests already tried:
```

It asks separately whether the user wants to attach a project, screenshot, or
full local log and warns that imported retail maps/screenshots are commercial-
derived and should not be posted. The default report includes no raw planes,
retail pixels, absolute home/data paths, save/config contents, or unrelated
environment variables.

For a format bug that cannot be reproduced synthetically, keep the private
input local and provide metadata, hashes, code paths, and a minimized abstract
description; do not attach the retail file to a public issue.

---

## Appendix F — Implementation invariants

These are suitable for code comments, assertions, and property tests:

1. A map has exactly three planes and every plane has exactly
   `width × height` uint16 words.
2. `(x, y)` indexes `y × width + x`; origin and axes never change with view
   transforms.
3. Raw planes are canonical; semantic views never serialize competing truth.
4. The imported 16-byte native-name field, unknown values, and plane 2 survive
   unrelated operations exactly; an intentional rename replaces all 16 name
   bytes with a validated canonical field and updates the serialized display
   text atomically; a mismatched text/raw pair never loads.
5. Plane-1 empty is 18.
6. Carving floor selects a valid zone; generic erase does not blindly write
   plane-0 zero.
7. A compound feature is one atomic command with an exact write and erase set.
8. A drag stores first-before/latest-after per cell and commits once.
9. Apply/undo verify expected current values before mutation.
10. Workers receive immutable snapshots and return owner/revision-tagged data.
11. The GUI never parses archives, encodes WADs, or directly writes plane arrays.
12. Core imports no PySide6 module.
13. Normal retail import opens source without write intent and verifies hash
    unchanged afterward.
14. Projects, caches, previews, configs, and saves never default inside game or
    release roots.
15. Every editor project/export replacement is serialized per target,
    handle-anchored, atomic on a supported local filesystem, and read back
    before success.
16. A normal preview WAD contains only intended `MAPxx`/`PLANES` pairs.
17. Equal canonical input and exporter version produce equal output bytes.
18. `--data` receives `CO7`; cwd identifies the data directory.
19. Child processes use program plus argv, never a shell string.
20. Test success requires positive intended-map evidence.
21. Playtest config and saves are isolated and absolute.
22. A snapshot is tied to export hash, camera/tic/rank, sealed render profile,
    platform, and engine-binary, pk3/resource, and data-profile digests.
23. Approximate 3D is never gameplay authority.
24. Public artifacts contain no retail or derived map/image/cache content.
25. An unchanged normal EC7Wolf launch behaves identically without editor
    options.
26. No milestone is complete without its exit-gate evidence.

---

## Appendix G — Preview WAD and launch checklist

### G.1 Preview WAD checklist

- [ ] WAD identification and directory are current-engine compatible.
- [ ] Marker is uppercase valid `MAPxx`, zero length.
- [ ] Next lump is exactly `PLANES`.
- [ ] PLANES magic is `WDC3.1`.
- [ ] Header values and legacy fields match the current engine writer contract.
- [ ] Plane count is 3 and name length is 16.
- [ ] Width/height equal document.
- [ ] Payload is exact little-endian plane 0, 1, 2.
- [ ] No retail graphics, palette, sounds, actors, MAPINFO, or unrelated maps.
- [ ] Independent readback equals frozen document revision.
- [ ] Output path is private/safe and digest recorded.

### G.2 Direct launch checklist

- [ ] Program is the configured compatible EC7Wolf regular executable.
- [ ] Working directory is the selected Corridor 7 data directory.
- [ ] Argument list, not shell, is used.
- [ ] `--data CO7` is present.
- [ ] `--file` path is absolute and points to read-back preview.
- [ ] `--config` path is absolute/private.
- [ ] `--savedir` path is absolute/private and exists safely.
- [ ] `--nowait` is present.
- [ ] `--tedlevel MAPxx` equals exported marker.
- [ ] `--skill N` is valid 1-based rank.
- [ ] Renderer/config options are not duplicated with launcher behavior.
- [ ] Revision, digest, cwd, and sanitized argv are logged.
- [ ] Source hash remains unchanged.

### G.3 Positive runtime evidence

The integration controller must be able to distinguish:

```text
process started
  ≠ Corridor 7 data selected
  ≠ preview resource loaded
  ≠ intended map found
  ≠ intended map entered
  ≠ capture artifact written
```

Only the last applicable evidence completes that stage. A long-running game
after intended map entry is normal; a long-running process before map entry is
not proof.

---

## Appendix H — First-release acceptance walkthrough

Conduct this on a clean supported system with a first-time tester while an
observer records time, mistakes, questions, and accessibility issues:

1. Start EC7Edit with no settings.
2. Configure EC7Wolf and the legally owned data directory.
3. Create a new Closed Room project in a safe suggested workspace.
4. Find a wall by browsing/search and paint a small room extension.
5. Eyedrop a wall and repaint one mistaken cell.
6. Carve floor using a visible valid zone.
7. Place/move the player start and change its direction.
8. Find an enemy, set direction and rank, and place it.
9. Place one pickup/object.
10. Place a door and understand its orientation preview.
11. Deliberately create an invalid transporter, find the problem, and repair it
    by completing the pair.
12. Undo and redo the pair.
13. Save, close, reopen, and verify work visually.
14. Export a one-map original/share WAD and read the output summary.
15. Press Test Map and reach the edited map in EC7Wolf.
16. Return, edit one wall, and observe that the running/previous export is
    stale before testing latest.
17. If Snapshot ships, choose a valid camera and refresh it.
18. Import an existing stock map into a different project and correctly explain
    why that project/export is private commercial-derived.
19. Simulate crash/restart and recover a final unsaved edit.
20. Find Quick Start, shortcuts, validation help, local logs, and bug-report
    action without developer assistance.

Pass criteria: the tester completes the flow without terminal use, raw-number
calculation, source-file copying, source overwrite, or help from the observer
beyond the written UI/help. Confusion that causes an unsafe choice is a release
blocker; ordinary discoverability friction becomes a prioritized UX finding.

---

## Appendix I — Glossary

| Term | Meaning in this document |
| --- | --- |
| EC7Wolf | Corridor 7-focused product based on ECWolf; version `1.0-betaX` |
| ECWolf | Upstream engine lineage, here 1.4.2-9-g1bff92d base |
| EC7Edit | Provisional name for this planned editor |
| TED5 | Native editor/archive family used by `MAPTEMP.CO7` |
| RLEW | Run-length encoding over 16-bit words with tag `0xABCD` |
| Native archive | Full self-contained `MAPTEMP.CO7` ordered map file |
| Plane 0 | Geometry, walls, doors, zones, transporters, floor actions |
| Plane 1 | Empty/things/starts/enemies/path and wall modifiers |
| Plane 2 | Preserved sector/flat data with incomplete authored semantics |
| Raw tuple | Plane values at one cell interpreted together |
| Catalog | Generated/curated metadata mapping raw values to friendly semantics |
| Semantic tool | User action that writes exact raw value(s) for a game meaning |
| Prefab | Tested parameterized multi-cell/multi-plane semantic placement |
| WDC3.1 | Uncompressed PLANES representation EC7Wolf consumes internally |
| Preview WAD | Small override containing selected `MAPxx` and `PLANES` lumps |
| Target slot | Runtime `MAPxx`; affects inherited MAPINFO behavior |
| Project | Versioned editor-owned document, not an engine savegame/archive |
| Provenance | Record of whether content is user-original, imported retail, or mixed |
| Commercial-derived | Converted/decoded content still originating from retail data |
| Test Map | External authoritative interactive EC7Wolf launch into current export |
| Snapshot | Exact still frame rendered by an external bounded EC7Wolf capture |
| Layout Preview | Optional approximate nonauthoritative in-editor 3D view |
| Exit gate | Objective evidence required to close an implementation milestone |
| Stop line | Condition that halts affected work until safety/correctness is restored |

---

## Appendix J — Final feasibility statement

The requested editor is attainable without turning EC7Wolf into a level-design
suite or building a second game engine. The native maps already fit a friendly
2D paint-and-place model, existing code supplies most difficult binary and
asset groundwork, and the engine's later-resource override provides a safe,
fast test loop.

The recommended first release is therefore:

- a native-feeling PySide6 desktop application;
- a lossless Qt-free core over all three native planes;
- searchable local texture/object/enemy palettes;
- direct wall painting and click placement;
- semantic doors, specials, zones, transporters, exits, and enemy properties;
- read-only extraction/import of every owned existing level;
- atomic project/save/export with one-map WAD as the normal output;
- continuous actionable validation;
- one-click launch into the real EC7Wolf map;
- if E10 succeeds, an exact software-rendered 3D Snapshot after the core editor
  is proven.

An interactive in-editor 3D walkthrough is useful but not necessary to deliver
the requested simple editor. It receives a measured post-core spike and is kept
only if it remains small, fast, honest about limitations, and independent of
gameplay authority. The real game remains one click away either way.
