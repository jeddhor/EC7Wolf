# November issue corrections and original-game verification

Jason approved the remediation plans for #16–#22, with #21 transparency rendering
reserved for a later, joint visual review. This change implements the supported
campaign, minimap, pickup and optional UI corrections. Audio #4 remains deferred.
No transparency geometry, ray traversal, texture-mask or OpenGL world-builder
code is changed.

Engine base: ECWolf 1.4.2-9-g1bff92d (18 February 2026), on the upstream
1.5.0pre line. EC7Wolf retains its separate commit-count beta version.

## Reference and method

The reference is the locally owned CD executable `CORR7CD.EXE`, 250,776 bytes,
SHA-256 `1287a13c2ac16624a1eb70ae1d207ad293e3aef6b852fa3d3f5eb6591d1c30f7`.
The exact hash is also recorded in the private verification artifacts; check it
before applying offsets to another edition. Binary offsets below include the
0x4200-byte executable header unless explicitly labeled load-module offsets.

Original-game tests used an unmodified executable under the project's DOSBox-X
source build, with temporary map copies and GDB inspection of emulated memory.
Controlled state changes were confined to the emulated test game. The retail
installation was not edited. `quit warning=false` disables DOSBox exit prompts.
Private evidence is under `analysis/verification/issues-2026-11-11/implementation`
in the parent workspace. Commercial files, memory dumps and reporter saves are
not part of this source change.

## #16 — Ammo capacity and duplicate plans

The native initial bullet capacity is 200. The pickup routine adds 500 and
clamps to 999; it does not supply ammunition. In a controlled native corridor,
with ammunition set to its existing 200 maximum before collection, capacity
became 700 and then 999 while ammunition stayed 200. A third pack was consumed
at the cap: its native static sprite became -1. Thus the report's statement
that only two packs can be collected is not reproduced. Two floor plans were
also consumed, leaving the entitlement set.

The port now follows that behavior. The existing Ammo-derived `C7AmmoPack`
class and serialized layout are preserved, so saved world packs use the new
pickup behavior without a class migration. Only bullet capacity changes.
Already-consumed packs cannot be reconstructed from old saves and receive no
speculative retroactive upgrade. Duplicate floor plans collect successfully.

Native capacity field: DS:8104. Current bullets: DS:80d2. Capacity arithmetic:
load-module 11d97. Saved capacity and campaign travel use the ordinary inventory
serialization and travel paths.

## #18 — Adrenaline at floor boundaries

Native floor setup compares health against 100 and lowers only excess health
(load-module 1f49d). The port applies that cap after campaign travel, synchronizing
player and pawn health. Wounded players are not healed. Same-floor save loads
bypass the travel cap. Deathmatch round reset is unchanged.

Runtime tests cover 63, 100, 101 and 400 health, boosted same-floor save/load,
and actual campaign transition. The boundary is shared by ordinary and bonus
floor entry; no separate per-elevator workaround is introduced.

## #19 — Five native health rows, not a guessed multiplier

The native table at file offset 3b23a contains five rows of 24 words, not four.
The old 192-byte research export omitted the fifth row. Native spawn code
indexes the table by rank times 48 bytes, independently of map spawn bands.

The port now selects health by actual rank and supplies the explicit President
row, while preserving Major's existing values and population eligibility.
For Animated Probe the five values are 25 / 50 / 100 / 150 / 200. Some species
have identical Major and President values; there is no blanket twofold health
multiplier. Serialized health in an existing save is retained rather than
healing or damaging every previously spawned alien during load.

The native main incoming-damage routine (load-module 11b7a) quarters damage for
Corporal and has no Major/President doubling branch. Native hitscan damage also
uses its ordinary distance/random branches. No unsupported damage multiplier
was added. A claim about additional species-specific damage differences needs
a matched case before further changes.

## #17 — Inset map

The native map routine (load-module 2103c) uses a precomputed wall bitmap,
independent of live door connectivity. Without a plan it samples 24 by 24 tiles,
with the x origin aligned down to a multiple of eight. The plan reveals the
whole floor and stationary/disguised aliens. Native alien and placed-mine
markers use palette ramps 224 and 208 respectively, which the DOS DAC cycles.

The port removes the zone-connectivity gate, corrects the sampling window,
reveals stationary aliens with the plan, draws living placed mines, and
explicitly cycles yellow/red marker ramps in both renderers. Corpses and
exploded mines are excluded. The native open-wall marker 107 is not a map wall.

**Still pending:** the claim that box mazes should disappear from the map.
A native MAP04 bitmap inspection included the checked marker-104 glass cells
(24 wall-57, four wall-58, two wall-61 cells). The bitmap constructor does not
contain a blanket 104/105 or transparent-texture exclusion. We therefore did
not guess such a rule. An exact native maze location/edition comparison should
settle this alongside the later visual review. World transparency rendering
remains entirely deferred to #21.

## #22 — Pickup lighting

Native pickup scenes show bright supplies against dark surroundings. The
correction uses existing fullbright Spawn frames for the actual weapon,
ammunition/capacity, armor, adrenaline, energy, mine-pack, invulnerability and
floor-plan pickup classes. It does not blanket-mark scenery, disguised aliens
or planted mines. Both renderers already support frame brightness. Frame
counts and order are unchanged, allowing saved world pickup states to resolve
to the corrected definitions. Jason's visual comparison remains useful for
fine differences across visor modes and individual assets.

## #20 — Optional presets and HUDs

The native shotgun code has distinct distance branches and adds 100, 50 or 25
at the corresponding ranges (load-module 12fe7, 13011, 13045). The no-falloff
claim is not supported. Classic retains that calculation. The approved optional
Minimum 100 preset joins Classic and Minimum 50. Old enhanced saves and settings
retain Minimum 50; saves without either rule field retain Classic. The effective
numeric minimum is saved and chosen by the multiplayer host. Legacy demos
retain Classic. Network protocol 10 rejects incompatible older peers.

The numeric status bar now overlays health, armor, ammo, mines and visor values
on their colored gauges. White numerals with dark shadows retain contrast.
The existing Modern compact HUD remains selectable alongside Classic.

**Correction to the November 8 finding:** the original compact HUD was
reproduced. DOS restricts the largest view according to available conventional
memory. With the default test allocation it capped view size at 20; enabling
UMB kernel allocation and lowering the DOS MCB reservation permitted view 21.
The original then displayed the compact numeric meters and three right-hand
readout boxes. The port's Classic style uses the verified native coordinates
and existing tiny font, gauges, icons and HUD digit assets. It requires no
invented mini-HUD image. Holding Show Status still displays the regular bar.

## Validation and handoff

Focused gates cover real full-ammo pickup touches, redundant pickup consumption,
capacity persistence, boosted and wounded travel, five rank health rows,
legacy saves/settings, three shotgun presets at three distances, host/client
agreement, all five numeric fields, Classic compact readouts and held status
in software and live OpenGL. Existing alien-counter/elevator, determinism,
malformed-network and retail minimap regressions are also run.

The optimized self-contained local package is refreshed with
`tools/package_corridor7_release.sh` and tested from its own directory with
`tools/test_corridor7_release_startup.sh`. Public issue closures and another
published beta wait for the requested user verification. The remaining review
list is #21, the #17 maze claim, any concrete #19 damage discrepancy, pickup/UI
visual feedback, and the previously deferred #4 audio comparison.
