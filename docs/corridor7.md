# Corridor 7 support (experimental)

ECWolf can detect the supplied Steam/CD release of **Corridor 7: Alien
Invasion**, read its original files directly, and run all 60 maps. ECWolf does
not include commercial Corridor 7 data; provide files from a legally owned
installation.

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

For a repeatable development smoke test:

```sh
tools/test_corridor7.sh /path/to/ecwolf-build /path/to/CORR7CD
```

For a representative campaign/secret/network-map validation:

```sh
tools/validate_corridor7_maps.sh /path/to/ecwolf-build /path/to/CORR7CD
```

Append an output directory and `--all` to load-check every map in the archive.

## Implemented support

- Bounds-checked, self-contained TED5 map loading for all 60 maps.
- Direct GFXTILES, VGAGRAPH, AUDIOHED/AUDIOT, executable-palette, wall,
  sprite, font, HUD, menu-cursor, sound-effect, and music resource exposure.
- Ordinary and special wall pages, Corridor 7 lighting defaults, solid and
  passable masked-wall behavior, four door types with automatic orientation,
  red/blue access cards, push walls, paired intralevel transporters, floor
  exits, ordinary and marker-99 bonus elevators, and the level-30/40 exit vortex.
- The executable's complete plane-1 dispatch table, including static objects,
  pickups, difficulty/direction actor variants, bosses, ignored markers, and
  the original sprite families.
- A Corridor 7 player, nine defined weapon/animation families, three verified late-weapon
  pickups, ammunition/health/armor items, monster combat, score, sounds, and
  native first-person weapon scaling.
- The original status bar art and number glyphs, aliens-remaining counter,
  episode and four rank choices, the documented 10/75/100/100-percent alien
  objective gate, MAP01-MAP40 progression and victory, six routed secret
  maps, intermission flow, and ECWolf save/load.

## Known deviations

This is a source-port compatibility implementation, not a cycle-accurate DOS
reimplementation. Actor health, speed, attack damage, projectile choice,
animation timing, and weapon balance are reconstructed approximations where
the released executable and design documents did not establish exact values.
Masked walls use ECWolf's solid-wall renderer rather than Corridor 7's exact
transparent column composition. The original map-to-song schedule, bespoke
briefing/victory screens, palette cycling, demo compatibility, and original
network protocol are not reproduced; exposed music currently uses a common
default track. Network maps can be loaded, but multiplayer was not part of the
single-player validation pass. Support is currently limited to the supplied
250,776-byte CD/Steam executable family.
