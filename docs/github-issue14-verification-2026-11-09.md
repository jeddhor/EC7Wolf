# Alien counter correction: issue 14

This records the investigation and validation for
[#14](https://github.com/jeddhor/EC7Wolf/issues/14), reported on Major difficulty:
early clearance, 191% kills on Level 5, and 245% on Level 6.

## Cause and reproduction

The reporter's Level 5 save contains 47 living counted aliens and a total of
47. Disguised Bandors are included from the beginning. Their absence from the
population is not the cause.

In beta287, a controlled attack against the chair Bandor at (36,10) calls
`AActor::Die` three times through `A_C7GunAttack`. Its health at those calls is
-62, -246, and -420. The last two calls occur after SHOOTABLE was cleared.
One alien dies, but killcount becomes 3: the HUD reports 44 remaining while 46
are alive. This reproduces the defect, rather than the reporter's exact final
percentages from a complete playthrough.

The M-343 caches a target for its three hits; the Assault Cannon does the same
for four. `DamageActor` previously processed an already-dead target again.
Each call to `Die` awarded points, credited a kill, rolled drops, and restarted
death states. This affects ordinary aliens as well as Bandors.

## Original-game verification

The unchanged retail CD executable was playtested in DOSBox-X 2026.01.02 using
two disposable maps. Its SHA-256 is
`1287a13c2ac16624a1eb70ae1d207ad293e3aef6b852fa3d3f5eb6591d1c30f7`.
Each map has one visible target and a second alien behind a solid partition.
The first supplies the native M-343 pickup (29) and an ordinary Alioprobe
(108); the second supplies the Assault Cannon (319) and a chair Bandor (126).

In both tests the ALIENS counter moves from 2 to 1 after killing the visible
target. Continued firing at the corpse leaves it at 1 and does not award
further points (100 for the Alioprobe, 500 for the Bandor). The pickup, firing,
death, and corpse phases were captured separately. Original game files and the
executable were not modified; only disposable map copies were substituted.
DOSBox-X's exit confirmation was disabled with `quit warning=false`.

These tests verify single death credit for the two relevant weapons. They do
not measure the original RNG sequence, drop probabilities, every rank's
clearance boundary, or the reported complete Level 5/6 playthroughs. The fix
does not change weapon formulas or rank thresholds.

## Correction and compatibility

`DamageActor` now ignores an already-dead non-player before health, targeting,
and death side effects. The player damage path is unchanged, and revival
restores positive health before an actor can take damage again. Direct `Die`
callers for players and the scripted runner do not pass through the new guard.
Weapon targeting, ammunition costs, and weapon RNG draws remain unchanged;
redundant death/drop processing is removed.

After loading a Corridor 7 single-player save, the loader counts living and
dead COUNTKILL actors. If they account for the saved total, it reconciles kills
to the dead population, including overcounts still below 100%. It clears
premature clearance/secured notification flags when the corrected count no
longer qualifies. Healthy saves retain their counters. A corpse-removing mod
fails the population check and keeps its statistics. The save format and its
product-version fields are unchanged.

Historical excess score, extra pickups, and statistics from already-completed
floors cannot be reconstructed safely and are preserved. A real beta287 save
with one dead alien, three credited kills, and 9,651 points loads as one kill,
two living aliens, no clearance/secured flags, and the same 9,651 points.

Multiplayer protocol 9 rejects older peers: the old damage behavior would
otherwise diverge during cooperative burst attacks even though packet layouts
are unchanged. All players must use matching builds.

## Validation

`tools/test_corridor7_alien_counter.sh BUILD_DIR DATA_DIR` is included in the
data-dependent gate suite. It exercises the real firing states and damage
code with disposable maps and derived test actors:

- Both burst weapons, all four Bandor disguises, and an ordinary alien, with
  first-hit and later-hit lethality: one kill, one score award, one drop.
- M-16, shotgun, plasma, and mine controls; repeated world checksums.
- Healthy saves, premature 100% and below-total corrupt counts, actual elevator
  denial after repair, and reconciliation skipped for removed corpses.
- All five ranks, actual elevator transitions, 100% completion and next-floor
  counter reset; retail MAP05/MAP06 Major populations and save/load.

Additional local checks cover a genuinely corrupted beta287 save and its stale
notification flags, the reporter's actual save, Level 5 software/OpenGL and
interpolation determinism, multiplayer damage/scoring agreement, source
contracts, and the packaged launcher's startup test. Commercial game data and
the reporter's save are not included in source or public artifacts.

Original screenshots, debugger logs, runtime traces, and local-only fixtures
are retained in the workspace's `analysis/verification` directory.
