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

### The CD soundtrack

The disc's music is redbook audio and is not in any of the files above. To use
it, rip your own disc into a `cdaudio` directory beside the game data, naming
each file for its physical track number:

```sh
tools/make_cdaudio.py Corridor7.cue /path/to/game-data/cdaudio
```

That writes `track02.ogg` … `track09.ogg`; the game plays tracks 3, 5, 7 and 9,
which are the four pieces of music. When they are present the AdLib songs are
not used at all, exactly as on the disc — including at the title screen and
between floors, where the CD release plays nothing and lets the current track
run on. Without the directory the game says so on startup and uses the AdLib
soundtrack. See the notes at the top of `src/c7_cdaudio.cpp` for how the disc
chose tracks.

### The floor objective banner

"Eliminate Aliens To Secure Floor" is drawn as a solid stencil in **(255,255,0)**,
measured from a DOSBox capture of the CD release on MAP01 rather than chosen.
Palette entry 3 — (215,215,0) — was used here previously and reads as dull olive
over the bright ceiling gradient MAP01 opens on, while looking right over the
darker walls most floors start on. `tools/test_corridor7_topmessage.sh` pins it.

### The pause label

Corridor 7 has its own pause picture — VGAGRAPH chunk 72, 64×32, the word
"paused" in chrome — and it is now named `PAUSED` in `co7map.txt` and drawn
through the same path as Wolf3D's. It used to be stencilled out of the small
font, because the chunk was still under its numeric name and `TexMan("PAUSED")`
found nothing. A DOSBox capture of the CD release matches that picture at
exactly (128, 64), which is where the stock call already put it.

Rebuilding an upscaled asset pack after this change is worth doing: a pack built
earlier carries the picture under the old name `c7g0072`, which no longer
matches anything the game draws. The game says so on startup and leaves the
pause label at its original resolution.

### Upscaled assets

The game can draw a neural-network upscale of its own art instead of the
original 64×64 pages. Build the pack from your own data files — nothing derived
from the commercial release is distributed, so there is no pack to download:

```sh
tools/make_c7_upscaled_pk3.py --dir /path/to/game-data
```

That runs every wall, sprite and picture through Real-ESRGAN (downloading the
ncnn/Vulkan build on first use) and writes `c7_assets_upscaled.pk3` beside the
data files. The game finds it there, or beside the executable, and uses it
automatically; **Advanced Graphics → Upscaled Assets** switches between the two
copies without a restart, because both stay loaded. Deleting the pack is not
required to go back, and the original art is still needed either way.

The pack is all-or-nothing. It carries a manifest of every image the build set
out to write, and the game checks each one against what actually arrived — an
upscaler that dies partway through still leaves a loadable pk3, and half an
upscale looks worse than none. A pack that fails the check is refused whole,
named in the startup log, and shown in the menu as *Pack Incomplete*.

Upscaled assets and xBRZ are mutually exclusive: xBRZ looks for staircases to
smooth, and there are none left in art a network has already enlarged four
times. Turning either on turns the other off.

**Choosing a model matters more than anything else here**, and no single choice
is right for the whole game. Measured on Corridor 7's own art:

| | `realesrgan-x4plus` (default) | `realesr-animevideov3` |
|---|---|---|
| Flat colour, hard geometry | keeps it — the SECURITY OFFICE sign stays yellow and legible | washes out, desaturates toward orange |
| Fine line work (stripes, drips) | crisp | smeared |
| Small bitmap text | rewrites it — ACCESS GRANTED became ACCE55 GRVNITED | survives, legible |
| Flat walls | invents film grain, which quantises to speckle | cleaner |

So the model is per group: `--model-walls`, `--model-sprites`,
`--model-graphics`, each defaulting to `--model`. Sprites and the full-screen
pages are what `realesrgan-x4plus` is good at, and they are the parts that come
out best.

**Nothing rescues five-pixel-tall bitmap text.** Any generative model guesses at
glyphs that small, and two automatic ways of detecting which tiles it ruined
were tried and both failed — they measure how much the model *changed* a tile,
which ranks a detailed tile it handled well above a sign it destroyed. So the
judgement is yours:

```sh
tools/make_c7_upscaled_pk3.py --dir /path/to/game-data --compare /tmp/c7compare
```

`--compare` writes an original-beside-upscaled strip for every image. Browse the
folder, note the names that came out worse, and rebuild with
`--keep c7w0009,c7w0030,...`. Kept lumps are left out of the pack *and* out of
its manifest, so the game keeps its own art for exactly those and still sees a
complete pack.

That review has already been done once for the default model, and its result is
`tools/c7_upscale_keep.txt` — 24 lumps, used automatically: the ACCESS GRANTED
and INTRUDER ALERT signs, the keypad panels, the status bar, the large HUD
digits, and the menu's LOAD/SAVE labels. Build with `--keep-file /dev/null` to
upscale everything anyway, and re-check with `--compare` if you change model,
because the list is specific to one.

Two notes for anyone rebuilding the pack:

* The upscaled art is quantised back into the 256-colour palette on load. That
  is not a limitation to work around — Corridor 7 rewrites the palette for the
  infrared visor and for damage flashes, and art that had left the palette
  would stop responding to either. What survives quantisation is the resolution
  and the reshaped edges, which is the part that matters.
* Switching the pack on also raises **Texture Filter** to *Smooth* if it was on
  *Sharp*. Nearest sampling is right for the game's own 64×64 art, which the
  renderer nearly always magnifies, and wrong for art four times that size,
  where every wall is being reduced instead — point-sampling a reduction throws
  away most of the texels and picks different ones as the view moves, which is
  what turns the pack's detail into crawling speckle. A deliberate *Bilinear*
  choice is left alone.
* Wall pages that use index 255 as a transparency key (grates, force-field
  frames — 50 of the 256) are written as RGBA so their holes survive; the engine
  reads a hires wall's transparency from the PNG's alpha channel.

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
  Corridor 7 wall depth ramp and native-resolution-independent plane gradient
  (three-row shade progression with alternating four-pixel VGA groups), exact
  six-bit VGA palette expansion,
  solid and passable masked-wall behavior, collision-safe index-255-to-0
  normalization with freshly traced geometry behind transparent wall and door
  pixels, four-side transparency detection for auto-oriented doors (so masked
  faces remain transparent on either map axis while jambs remain opaque),
  unshaded C010 floor lamps, dedicated full-bright wall-lamp indices 15/254 and
  animated 208..239 light ramps (applied in texture space at every output
  resolution), all four native wall/force-field palette cycles, four-frame
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
  executable-selected silver floor sprite, owner-safe arming,
  player/monster triggering, and
  self-damaging radial explosions, all weapon pickups,
  ammunition/charge/health/armor items, non-wasteful health and ammunition
  pickup rules, monster combat, projectile attacks, score, event sounds, and
  native first-person weapon scaling. The original W+A+X equipment cheat and
  full-floor-plan pickup are supported.
- All eight weapons preserve the executable's 70 Hz frame cadence and support
  held-trigger refire. The Taser repeats its complete C746-C749 attack cycle.
  Refire branches occur after their visible frame instead
  of suppressing it, so the M-24 jiggle, M-343 barrel cycle, alternating alien
  muzzle flashes, and complete shotgun/disintegrator recovery sequences remain
  visible and repeat smoothly. Zero-duration movement/return pages are not
  inserted into firing sequences: the M-24 and most automatic alien weapons
  loop their final two firing pages, while the M-343 rapidly cycles all four.
  The plasma rifle emits the blue C706 traveling
  bolt from GFXTILES chunk 962 and its C707-C709 impact sequence, without
  borrowing the C738-C744 exit-vortex art. The native movement-pose table
  is separate from continuously rotating palette ramps. Walking and running
  alternate only each weapon family's base+4 moving pose and base+7 stationary
  pose, while the Taser scanner, plasma rangefinder, energy effects, and other
  instrument pixels continue animating at full brightness in dark rooms.
- The original status bar art, number placement, segmented color gauges,
  aliens-remaining counter, M-16 start selection and native weapon anchoring,
  stable full-bright timed notifications with their original one-pixel drop
  shadow, the clean opening splash,
  a Corridor 7-native text pause overlay (the game has no Wolf `PAUSED` art),
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
  font, title/headers/all seven rows and the name-entry line at the executable's
  original positions), and the death report (large-font title, labels at x=80 every
  ten rows, values at x=240) were all verified against screenshots of the
  released game running in DOSBox.
- The executable palette is captured in memory when the game data is opened;
  palette changes across death, high scores, and title pages therefore do not
  depend on reopening `CORR7CD.EXE` through a later relative path.
- The executable's released campaign music selector, including its randomized
  late/bonus-floor behavior, with all 34 AdLib music chunks exposed directly
  from the original archive.
- Released per-rank enemy health tables and executable-derived object/state
  mappings for the complete CD bestiary. Unique behavior includes local
  Alioprobe/Eitak alerts, vulnerable Bandor camouflage morphs, retreating
  Rodex/Tenaj, the melee-only Semaj, close-range-heavy Mechanoid fire and
  footsteps, permanently visible C653-C664 Eniram Boss versus cloaking
  C665-C689 ordinary Eniram, fast-dodging Tymok, sustained Solrac eye fire,
  and Tebazile's five fully animated forms. Glass remains visually transparent
  while blocking alien sight, and active alien-world enemies can cross paired
  transporters. Audible projectiles, alien energy regeneration/capacity,
  persistent mines, and the level-30/40 exit-vortex behavior are retained.
- Stateful access/alarm computers, health and ammunition dispensers, the
  reusable visor charger, and health chambers that turn the player toward the
  exit, immediately show their green-to-red meter, close the chamber door,
  heal from a persistent 100-point reservoir, and retain any unused charge.
  The remaining-power gradient fills the complete 42x5 recessed well in the
  original 48x32 panel and shares the panel's virtual-screen scaling.
  Electric contact comes from the released wall IDs 6 and
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
