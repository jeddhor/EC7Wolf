# Combat against the original: GitHub #25, #26 and #27

Three reports from one player who plays the original on Major:

- **#25** the plasma rifle recharges almost instantly; in DOS it takes one to
  two seconds.
- **#26** an Animated Probe next to the player does about 0-65 a hit in DOS and
  about 0-15 in the port.
- **#27** aliens die far too easily: the Taser kills a Probe in one hit on
  Major, and the reporter's "CAW" clears rooms in seconds.

All three are real, and none of them comes from the per-rank health change in
beta299 (#19), which the #27 report suspected. Major's health rows did not
change in that work; the gate that pins them still reads 150 for a Probe. The
two damage faults date from July, when the combat code was first written.

Baseline: EC7Wolf 1.0-beta300. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

## Reference and method

The locally owned `CORR7CD.EXE` (SHA-256 `1287a13c…1c30f7`), read from a 1 MiB
memory image of the running game under the project's DOSBox-X build. Code
addresses are physical addresses in that image (DS = 0x37790); the image's
load module starts at 0x2220, so a load-module offset from an earlier note
plus 0x2220 is the address used here. Data addresses are DS offsets. The
listings and dumps are private evidence in the parent workspace and are not
part of this change.

## What the original does

**Every random number is Wolf3D's `US_RndT`.** The routine at 1fc5e steps an
index through a 256-byte table and returns a byte: 0..255. Every damage roll
below draws from it.

**The player's guns (151b5, one shot per call).** The weapon dispatcher calls
it with the current weapon: 0 Taser, 1 shotgun, 2 M-16, 3 M-343, 4 dual blaster,
6 assault cannon, 7 disintegrator. It picks the nearest visible shootable actor
near the crosshair and, if a line reaches it:

| Tile distance | Damage | Shotgun adds |
| --- | --- | --- |
| under 2, or any distance for the M-343 and assault cannon | rnd/4 (0-63) | 100 |
| under 4, or any distance for the dual blaster | rnd/6 (0-42) | 50 |
| farther | miss if rnd/12 < distance (not the shotgun), else rnd/6 | 25 |

The disintegrator instead hits every visible target in a wide band for 1000.
The damage routine (1290e) doubles a hit on an alien that has not yet noticed
the player, as Wolf3D does.

**How many shots a cycle (the attack table at DS:132a).** Each weapon has five
four-byte entries -- tics, attack code, frame -- and every frame lasts six tics.
Code 1 fires and pays for it; code 2 (1560d) fires again with no ammunition, no
sound and nothing on the hit/miss page; code 3 is the held-trigger refire; code
4 (154ec) is the dual blaster's second shot. So:

- Taser: one shot on its third frame, through the gun routine above. It is a
  short-ranged gun, not a melee punch.
- M-343 and assault cannon: codes 1, 2, 2 on the first three frames -- three
  rounds a cycle, one paid -- and held fire restarts at the first frame.
- Dual blaster: fires on its third and fourth frames, and held fire returns to
  the third: a shot every six tics.
- M-16, plasma rifle, disintegrator: one shot, held fire returns to the
  firing frame.

**Alien gunfire is Wolf3D's `T_Shoot`, unchanged (185f5).** Tile distance,
two-thirds of it for classes 8 and up (the SS/boss rule); a hit chance of 256
or 160 (if the player is running) less 16 or 8 per tile depending on whether
the player can see the shooter; then rnd/4, rnd/8 or rnd/16 at under 2, under 4
and beyond. A Probe beside the player therefore hits for 0-63, which is what
#26 measured in DOS. Its own sound plays only for classes 3, 4 and 8-11.

**The "attack sound" action also shoots (18455).** It plays the class's attack
sample and then calls `T_Shoot`. Every frame that carries it is a shot.

**Some aliens shoot every frame.** The state tables (18-byte entries between
2b000 and 2f800) put `T_Shoot` in the *think* slot for Nerraw (shape 580)
and Eniram (672), and the Semaj's bite (185b0: rnd/16, no accuracy roll) in the
think slot of shape 566. The actor loop (bc70) calls a think every frame drawn,
so for those ten tics each fires once per frame.

**Recharge (21959).** The palette-cycling routine, called once per play-loop
pass (c145), also adds 2 to the alien charge (DS:80de) while it is below the
capacity (DS:80f0) and the best weapon held is above the M-16. A plasma shot
costs 33 charge and 4 capacity (155b0). In the reference runs DOSBox drew a
frame every three tics, about 46 charge a second: two seconds from empty to a
full 100.

**Alien plasma (17512, 169c6).** Only the Eniram Boss and Tymok fire it. On
reaching the player it does rnd/8 + 30 (30-61). The player's own bolt explodes
for rnd + 25 (25-280), halved per tile of Manhattan distance across a 5x5 area
(23b0f).

## What the port did

- Player damage drew `GenRand32() & 1023`, 0..1023, so every gun did four times
  the original's damage; the shotgun at point blank was 100-355 rather than
  100-163. The M-343 and assault cannon rolled three and four times in one
  call, the dual blaster fired once a cycle, and the Taser was a 0..255 melee
  punch. (#27)
- Aliens used `A_WolfAttack` with damage caps that were estimates -- 12 for the
  Probe, 16 for the Organic Eye, 24 to 112 elsewhere -- and none applied the
  two-thirds distance. A Probe beside the player did 1-12, about a fifth of the
  original. Shots carried by the attack-sound action were missing (Tenaj,
  Rodex, Ttocs, Otrebor, Tymok, Mechanoid each fired fewer rounds), the
  per-frame shooters fired once, and Solrac and Tebazile's Eniram, Tymok and
  Solrac forms threw projectiles where the original fires hitscan. (#26)
- Charge refilled by 2 every 70Hz tic, twice the period-correct frame rate and
  three times what the reference DOSBox runs showed, and only while an alien
  weapon was in hand. (#25)

## What the port does now

- `A_C7GunAttack` rolls `US_RndT` once per call. A new flag marks the
  attack-code-2 follow-up rounds (no ammunition, sound or hit/miss count). The
  Taser goes through it as weapon 0; the M-343 and assault cannon fire on
  their first three frames; the dual blaster on its last two.
- Every alien `Missile` sequence follows its released state chain frame for
  frame: `A_WolfAttack`'s defaults (which are `T_Shoot`'s numbers), snipe 0.667
  for classes 8 and up, a shot wherever 18455 or `T_Shoot` sits, five one-tic
  shots or bites for the per-frame shooters (two tics a frame, the
  period-correct rate the palette ramps already use), and Ttocs's 1-in-7
  second shot from 18346. Solrac and Tebazile's forms are hitscan; the alien
  plasma bolt does 30-61. The Mechanoid fires with class 23's sample 41, the
  dual blaster it drops.
- Charge refills by 2 every two tics while the player holds any weapon above
  the M-16, whichever is in hand.

## Measured in the port

A lab corridor with one Animated Probe, on Major, with the player's health
raised and the new `--capture-actors-player` trace:

- 159 Probe hits on the player from the adjacent tile: 1 to 64, mean 30.8.
  Before: 1 to 12.
- The Probe has 150 health. Point-blank it takes seven hits from any gun (the
  first doubled, since it has not seen the player yet): about 2.4 seconds
  with the Taser, which fires every 24 tics, and under a second with the
  M-343. Before, a Taser hit was 0-255 doubled, often a kill.

## Seen, not changed

- **The red damage flash flickers on a big hit in DOS** (#26's side note). The
  play loop sets the red palette shift (baa8, Wolf3D's
  `UpdatePaletteShifts`, called at c0c0), draws the view, and then the palette-cycling routine
  sets the normal palette back (21990) on every frame. While a shift lasts, the
  screen alternates between the two at the retrace's mercy, and a 50-point hit
  keeps the shift up long enough to see several pulses. That is read from the
  code, not timed against a DOS capture; the port keeps its steady fade.
- **Pain can lead straight into an attack.** Each class's pain routine picks a
  state by health parity: for Ttocs, Otrebor and Eitak one of the two pain
  states leads into the attack sequence rather than back to the chase. The port
  returns to the chase. It changes how aggressive those three are when hurt,
  and is worth its own change.
- **The hit/miss page counts a long-range miss as a hit.** The original sets
  its hit flag once a line reaches the target, before the long-range miss
  roll. The port counts only hits that do damage.
- **The Semaj's bite has no range check** in the original; the port keeps
  `A_MeleeAttack`'s, so stepping away during the bite still avoids it.
- **The alien plasma's blast** also damages actors around the player in the
  original; the port's bolt damages only what it hits.
