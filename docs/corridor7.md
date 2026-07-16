# Corridor 7 single-player support

ECWolf can detect the supplied Steam/CD release of **Corridor 7: Alien
Invasion**, read its original files directly, and play its 40-floor
single-player campaign plus all six bonus floors through final victory. The
remaining archived maps also load, but multiplayer is outside this support
target. ECWolf does not include commercial Corridor 7 data; provide files from
a legally owned installation.

Keep these files together in one game-data directory:

- `CORR7CD.EXE`
- `MAPTEMP.CO7`
- `GFXTILES.CO7`
- `VGADICT.CO7`, `VGAHEAD.CO7`, `VGAGRAPH.CO7`
- `AUDIOHED.CO7`, `AUDIOT.CO7`

The recognized CD executable is 250,776 bytes. ECWolf reads its gameplay
palette at runtime; the palette and other commercial resources are not
embedded or redistributed.

Launch through the normal IWAD picker or directly from the data directory:

```sh
ecwolf --data CO7 --nowait --tedlevel MAP01 --skill 2
```

To create a self-contained local release directory containing an optimized
ECWolf build and a copy of a legally owned installation:

```sh
tools/package_corridor7_release.sh /path/to/ecwolf-build \
    /path/to/CORR7CD /path/to/builds/release
/path/to/builds/release/run-corridor7.sh
```

The release directory contains commercial game data and must not be committed
or redistributed. The launcher keeps its configuration and saved games in the
release directory.

The packaged startup path (title/credits, menu, and starting MAP01) can be
tested with:

```sh
tools/test_corridor7_release_startup.sh /path/to/builds/release
```

For a repeatable development smoke test:

```sh
tools/test_corridor7.sh /path/to/ecwolf-build /path/to/CORR7CD
```

For a representative campaign/bonus/archive-map validation:

```sh
tools/validate_corridor7_maps.sh /path/to/ecwolf-build /path/to/CORR7CD
```

Append an output directory and `--all` to load-check every map in the archive.

## Implemented support

- Bounds-checked, self-contained TED5 map loading for all 60 archived maps.
- Direct GFXTILES, VGAGRAPH, AUDIOHED/AUDIOT, executable-palette, wall,
  sprite, font, HUD, menu-cursor, sound-effect, and music resource exposure.
- Zero-based wall pages (`map wall ID - 1`) across the complete solid-wall
  range, including marker-104/105 masked overrides,
  Corridor 7 wall and plane depth ramps, exact six-bit VGA palette expansion,
  solid and
  passable masked-wall behavior, collision-safe index-255-to-0 normalization
  with depth-correct wall and door opacity,
  in-place force-field removal, four door types with automatic orientation,
  red/blue access cards, push walls, paired intralevel transporters, floor
  exits, ordinary and marker-99 bonus elevators, and the level-30/40 exit vortex.
- The executable's complete plane-1 dispatch table, including static objects,
  pickups, difficulty/direction actor variants, bosses, ignored markers, and
  the original sprite families.
- A Corridor 7 player, the released eight-weapon arsenal (including the
  Ithaca shotgun's secondary animation), proximity mines, all weapon pickups,
  ammunition/charge/health/armor items, monster combat, score, event sounds,
  and native first-person weapon scaling.
- The original status bar art, number placement, segmented color gauges,
  aliens-remaining counter, M-16 start selection and native weapon anchoring,
  episode and four rank choices, the documented 10/75/100/100-percent alien
  objective gate, body armor, visor modes and charge, MAP01-MAP40 progression
  and victory, six routed bonus maps, the released per-floor hit/miss award,
  high scores, and ECWolf save/load.
- The executable's released campaign music selector, including its randomized
  late/bonus-floor behavior, with all 34 AdLib music chunks exposed directly
  from the original archive.
- Released per-rank enemy health tables, directional/pain/death sprite
  families, bosses and projectiles, alien energy regeneration/capacity, and
  the level-30/40 exit-vortex behavior.

## Known deviations

This is a source-port compatibility implementation, not a cycle-accurate DOS
reimplementation. Released enemy health, weapon resource costs, music routing,
map dispatch, and campaign rules are reproduced; several movement, attack,
pain-chance, damage, and frame-timing constants remain evidence-based
reconstructions where the executable did not yield an unambiguous value.
Masked screens preserve collision and sight behavior while transparent columns
are composited with walls and actors at their actual depth. Plane-1 masked-wall
configuration markers 86..88 are preserved distinctly, but their exact DOS
state differences remain unresolved. The port uses a native ECWolf results/victory
presentation rather than every
DOS briefing and palette-cycle effect. Plane 2 contains editor grouping values
on two released maps and has no observed runtime effect. Original demos,
network protocol, multiplayer rules, and other executable editions are
deferred. Support is limited to the supplied 250,776-byte CD/Steam executable
family.
