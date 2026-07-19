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
  solid and passable masked-wall behavior, collision-safe index-255-to-0
  normalization with freshly traced geometry behind transparent wall and door
  pixels, all four native 208..239 wall/force-field palette cycles, four-frame
  in-place force-field and animated-wall openings, four sliding door types with
  automatic orientation,
  red/blue access cards, one-shot secret and utility pushwalls with correct
  secret accounting, four-frame retracting barriers, paired intralevel
  transporters, floor exits, ordinary and marker-99 bonus elevators, and the
  level-30/40 exit vortex.
- The executable's complete plane-1 dispatch table, including static objects,
  pickups, difficulty/direction actor variants, bosses, ignored markers, and
  the original sprite families.
- A Corridor 7 player, the released eight-weapon arsenal (including the
  Ithaca shotgun's secondary animation), persistent proximity mines with the
  released floor sprite, owner-safe arming, player/monster triggering, and
  self-damaging radial explosions, all weapon pickups,
  ammunition/charge/health/armor items, non-wasteful health and ammunition
  pickup rules, monster combat, projectile attacks, score, event sounds, and
  native first-person weapon scaling. The original W+A+X equipment cheat and
  full-floor-plan pickup are supported.
- The original status bar art, number placement, segmented color gauges,
  aliens-remaining counter, M-16 start selection and native weapon anchoring,
  stable full-bright timed notifications with their original one-pixel drop
  shadow, the clean opening splash,
  original pixel-dissolve title transition, and paced fading credit sequence;
  episode and five rank choices (including randomized President placement),
  the documented 10/75/100/100-percent alien objective gate, body armor,
  normal/night/infrared visor modes and charge, infrared-revealed laser
  barriers and cloaked enemies, and electric wall IDs 6/14
  with their original palette shock, MAP01-MAP40 progression and victory, six routed bonus maps,
  the released per-floor hit/miss award, original loading/death/high-score
  pages, the rare non-counting C718-C725 red-skull taunt and its original
  ominous sound, and ECWolf save/load.
- The original graphical main menu: the full-screen menu picture (VGA chunk
  12) with its painted-in entries, the released 24x8 blinking arrow cursor at
  the original coordinates (x=56, item text tops 58/74/83/101/110/128/137/
  155/172), and the original entry wiring — NEW MISSION starts a game,
  ADJUST AUDIO/ADJUST VISUAL open the sound and display options, RETRIEVE/
  STORE MISSION load and save, RESUME/ABORT CURRENT MISSION return to or end
  the running game, HIGH SCORES shows the table, and EXIT BUILDING asks
  "Exit building?" in the original grey prompt window. Menu sounds follow a
  controlled DMA capture of the released game: every cursor move plays
  sample 9, activating an entry is silent, escaping back to the main menu
  plays 33, and the quit/confirm prompt announces itself with 31 with a
  silent cancel.
- Full-screen picture pages draw their text and cursor in the same stretched
  320x200 mapping as the picture itself, so the layouts hold at every window
  size. The menu arrow, the per-floor status report (values seated on the
  painted label rows at the colon column), the high-score page (large archive
  font, title/headers/rows and the name-entry line at the captured original
  positions), and the death report (large-font title, labels at x=80 every
  ten rows, values at x=240) were all verified against screenshots of the
  released game running in DOSBox.
- The executable's released campaign music selector, including its randomized
  late/bonus-floor behavior, with all 34 AdLib music chunks exposed directly
  from the original archive.
- Released per-rank enemy health tables, distinct directional/attack/pain/death
  sprite families, alarm and camouflage transformations, bosses and audible
  projectiles, alien energy regeneration/capacity, persistent mines, and the
  level-30/40 exit-vortex behavior.
- Stateful access/alarm computers, health and ammunition dispensers, the
  reusable visor charger, and health chambers that turn the player toward the
  exit, close the chamber door, consume stored power, heal, and report the
  remaining charge. Electric contact comes from the released wall IDs 6 and
  14; the C010/C011 lightposts do not create an inferred beam or an elevator
  hazard. Secret walls visibly slide but, as in the original executable, do
  not play sample 46.
- Visor-dependent hazards: the wall-ID 6/14 energized barriers are visible
  in every visor mode, stay solid, and zap the player on contact — and again
  on every repeated contact — with sample 13, the DAC shock, and a flat 2
  points roughly twice per second while pressed against them (the executable
  subtracts those points directly, before rank and armor scaling). The
  strategy guide's "Infrared Invisible Barrier" is the laser barrier
  static pair, map objects 28 and 84 (the three-rod C006 sprite and the
  C062 energy ring; on MAP01 both traps are object 28, planted in the
  corridor pinch beside each yellow health-unit door). The executable's
  10-point invisible-barrier routine (`2f28:06d3`) keys on exactly those
  two object IDs. In the port, as in side-by-side DOSBox captures of the
  released game, the statics are drawn only under the infrared visor —
  rendered as bright dashed energy behind an animated dissolve whose
  segment layout crawls over time rather than as their dark artwork — and
  they never block movement; walking through the hidden beams deals the
  10-point damage through the standard rank/armor path roughly once per
  second while the player stays in the beam. The wall-73 family remains an ordinary always-visible marker-106
  retracting doorway. All decorative statics (the C010 posts, C011 rods,
  and C012 strands) and the 57/61 glass panes are plainly visible in every
  visor mode, exactly as a controlled DOSBox run of the released game
  shows; a diagnostic-mode probe of that run also reads runtime tile 0
  inside the wall-237 glass-assembly core, so the port erases that cell at
  load just as the DOS engine does. The wall-16 vertical bars remain an
  ordinary visible fence, and wall tiles 28/84 (unrelated sign/decor
  pages that merely share the objects' ID numbers) stay ordinary walls.

## Known deviations

This is a source-port compatibility implementation, not a cycle-accurate DOS
reimplementation. Released enemy health, weapon resource costs, music routing,
map dispatch, and campaign rules are reproduced; several movement, attack,
pain-chance, damage, and frame-timing constants remain evidence-based
reconstructions where the executable did not yield an unambiguous value.
Masked screens preserve collision and sight behavior while transparent columns
are composited with walls and actors at their actual depth. Plane-1 masked-wall
configuration markers 86..88 are preserved distinctly, but their exact DOS
state differences remain unresolved. The final victory page remains an
evidence-based ECWolf reconstruction because the installation does not contain
the external cinematic files referenced by the executable. Plane 2 contains
editor grouping values
on two released maps and has no observed runtime effect. Original demos,
network protocol, multiplayer rules, and other executable editions are
deferred. Support is limited to the supplied 250,776-byte CD/Steam executable
family.
