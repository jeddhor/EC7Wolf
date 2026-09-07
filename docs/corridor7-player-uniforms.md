# Multiplayer marine uniform colors

Multiplayer setup now has a **Uniform** row for the Marine: Blue (the original),
Red, Green, Gold, Purple, Magenta, Brown, and Gray. The Eitak warrior retains
its original artwork; its Uniform row is disabled. All marine colors have
identical weapons, health, speed, sounds, animation timing, and team membership.
Each human can choose a different color. Bots inherit their host's character
and uniform, as they already inherited the host's character before this change.

These are palette swaps of the installed marine, following the preservation,
palette, anchor, manifest, and validation rules in the
[monster sprite workflow](corridor7-monster-sprite-workflow.md). They reuse all
51 stock MARN frames: A–E in eight rotations, F pain, G–M death, and N–P firing.
No poses, equipment, shading clusters, or silhouettes were redrawn.

| Choice | Bank | Native source indices | Native destination indices |
| --- | --- | --- | --- |
| Blue | MARN | original | unchanged |
| Red | MRRD | 41–63 | 65–87 |
| Green | MRGN | 41–63 | 113–135 |
| Gold | MRGD | 41–63 | 89–111 |
| Purple | MRPR | 41–63 | 185–207 |
| Magenta | MRMG | 41–63 | 161–183 |
| Brown | MRBR | 41–63 | 137–159 |
| Gray | MRGY | 41–63 | 17–39 |

All other indices stay unchanged, including the source's small luminous muzzle
details at 212–213. The new uniform ramps introduce no luminous, cycling, or
transparent indices. Each swap preserves the ordering of all 23 uniform shades.

## How the sprites are supplied

The built-in `TEXTURES` definitions compose each sprite from the user's installed
MARN frame, with a palette translation and `UseOffsets`. They reconstruct the
same 64×64 canvas and `(32,64)` anchor from the retail frame's cropped offsets.
Both renderers consume the resulting indexed textures. This supplies 357 new
sprite textures without storing commercial artwork in the repository or PK3.
The generated cosmetic actors inherit C7Player gameplay and repeat its state
graph with their own sprite bank.

The existing multiplayer class exchange carries the selected cosmetic class.
The original Marine and Eitak retain indices 0 and 1; variants follow them.
Corridor 7 teams are determined by Eitak ancestry rather than cosmetic class
index, so differently colored marines remain teammates. All peers should run
the same updated game package.

Texture translations need the initialized game palette while parsing. Startup
therefore loads the palette before `TexMan.Init()`. Previously that order was
reversed, and index translations silently resolved through a zero-filled remap.

## Regeneration and private exports

From the project parent directory:

```sh
python3 ECWolf/tools/make_c7_player_colors.py
python3 ECWolf/tools/make_c7_player_colors.py --check
ECWolf/tools/package_corridor7_release.sh builds/release-build corr7/CORR7CD builds/release
xvfb-run -a python3 ECWolf/tools/test_c7_player_colors.py builds/release builds/player-colors
```

The test exports the resolved engine textures using the repeatable
`--capture-sprite-bank BANK PATH` diagnostic, verifies them, and writes:

- `manifest.csv`: every color, source frame, state, rotation, and anchor;
- `sprites/<color>/`: all 51 PNG frames for each color, including blue;
- `previews/`: a comparison sheet, all-angle sheet, complete frame sheets,
  turntables, walking, firing, and death animation previews;
- `palette-report.json`: per-frame indices, alpha, changed pixels, and source
  file hashes;
- `render-report.json`: near/far normal, night-vision, and infrared captures
  through software and OpenGL rendering.

PNG export is a format conversion of the engine's resolved native textures,
with binary alpha and explicit `grAb` offsets. The validator compares the engine
source against the retail decoder, then requires every variant pixel to equal
the exact expected index translation. It rejects any changed silhouette,
nonuniform pixel, anchor, missing frame, or unexpected frame.

The PNGs, palette dumps, and previews contain retail-derived artwork. Keep them
private under `builds/player-colors`; do not commit or redistribute them.
Runtime uses the text definitions in `ec7wolf.pk3` and does not need these
exported PNG files. No separate mod is needed to select the built-in colors.

`test_multiplayer_menu.sh` selects Red through the menu and checks that both
peers see the choice. `test_multiplayer_rules.sh` puts Red and Gray marines on
the same team and verifies that uniform color does not permit friendly fire;
it also checks a Green marine against an Eitak opponent.
