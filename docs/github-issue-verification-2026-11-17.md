# Fences, health, energy, sounds and xBRZ: GitHub #30 to #35

Six reports against beta302 and beta304:

- **#30** any fixed xBRZ factor freezes the picture, while the game keeps
  running; Off and Auto are fine.
- **#31** floor 11 cannot be finished: its aliens stand behind electric fences
  that stop the player's shots. Some girder walls can be shot through in DOS
  and not in the port.
- **#32** health chambers do nothing at or above 100 health, though the
  player's maximum can be raised to 400.
- **#33** the Mechanoid Warrior makes the wrong movement sound, and it is heard
  across the whole floor.
- **#34** a Dual Blaster dropped by a Mechanoid gives no ammunition.
- **#35** the med bay's blast shield opens silently, and the medic pack inside
  does not flash the screen as pickups do.

All six are real. #31 to #35 were checked against the original executable; #30
is the port's own feature. Measured where a lab could show it.

Baseline: EC7Wolf 1.0-beta304. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

## Reference and method

The locally owned `CORR7CD.EXE`, through the project's Ghidra export of its
code and the same 1 MiB memory image of the running game used for
[github-issue-verification-2026-11-15.md](github-issue-verification-2026-11-15.md).
Addresses in segment:offset form are the Ghidra export's; five-digit
addresses are physical addresses in the image (DS = 0x37790), which is the
Ghidra linear address less 0xdde0. Sample numbers are the game's digitized
sounds, which the port loads as `C7DS0000`... in the same order. The listings
and dumps are private evidence in the parent workspace and are not part of
this change.

## #31: shots pass the fences, by map marker

The original's `CheckLine` (1ef0:1b83) walks the tiles between two actors.
A solid tile stops the line unless plane 1 at that cell holds marker 105 or
107, or holds 106 while the tile is the last frame of a force field's opening
animation (48, 52, 56, 76, 84, 120, 232, 236 or 244: each family's base wall
plus three). Doors use Wolf3D's door-position test. The same routine is called
by the player's gun routine (2163:17c6) and by every alien sight, chase and
`T_Shoot` check (2454:0ed8 to 2454:1e95), so the rule is symmetrical.

Marker 105 is the see-through screen. Across the 60 shipped floors it sits on
wall 6 (22 cells) and wall 14 (87), the electric fences; wall 24 (109), the
girder trusses in the reporter's screenshot; and walls 3, 57, 58, 60 and 84
(79 more). Floor 11 has 10 fence cells and 75 truss cells. Marker-104 glass
(775 cells) blocks.

The port blocked every solid cell except marker 107. A July change made that
choice on the stated belief that aliens cannot see through masked walls; it had
no native evidence and contradicted the port's own map comment that marker 105
"permits actor sight". It now passes 105 and 107 and nothing else, keyed on the
marker rather than on the render flag `corridor7SightTransparent`, which the
closed health-chamber shutter also carries.

New gate `corridor7_sight_screens`: a lab corridor cut by a row of wall-6,
marker-105 cells. The player shoots an Animated Probe through it; a Probe woken
by noise shoots the player through it. With marker-104 glass in the same place,
neither happens, although the Probe wakes.

The plasma rifle's bolt is a projectile and still stops at a fence, as a moving
actor does at any solid cell. Whether the original's bolt passes was not
checked.

## #32: the Adrenaline raises the maximum

Health is DS:80d0 and the maximum DS:8106. The Adrenaline Boost (GetBonus item
5, 13fd9) adds 300 to the maximum, caps it at 999, and then heals 300 through
the ordinary heal (13e66), which caps at that maximum. Every other heal uses the
same cap: the medic pack behind a med bay (14b03) refuses at the maximum and
adds 25; the health chamber (2f28:12d7) drains its reserve each frame while
health is below the maximum. The next floor's setup sets the maximum back to 100
and lowers health to it (216ba). So after a boost to 400, a chamber heals a
player at 250 up to 400, where the port refused.

The port gave the Adrenaline a fixed 400 cap and left the maximum at 100. It
now raises `maxhealth` (saved with the player already), and the floor setup
puts it back to the class's own value. The pickup message is the executable's,
"Adrenaline Boost".

## #34: alien weapons give capacity, not charge

Alien charge is DS:80de and its capacity DS:80f0; charge regenerates by two a
frame up to capacity once the best weapon owned is above the M-16, and firing
spends both. The give-weapon routine (13ec1) gives 100 bullets for a human
weapon, but for weapon 4 and up -- dual blaster, plasma rifle, assault cannon,
disintegrator -- it sets capacity to 100 and gives no charge. It never refuses a
duplicate. The Alien Charge Pack (140f6) adds 100 capacity, up to 999, and no
charge; at 999 it is left lying.

The port gave 100 charge with each alien weapon and capped capacity at 100.
Charge is clamped to capacity every tic, so the gift vanished at once whenever
capacity had been spent, which is what the reporter saw. Now an alien weapon
resets capacity to 100 and is always picked up; a charge pack raises capacity to
at most 999; and charge exists, and regenerates, from the first weapon above
the M-16, so the first alien weapon arrives charged as it does in DOS.

New gate `corridor7_health_energy`, through the ordinary pickup code: two
Adrenalines give 400/400 and then 700/700, and the next floor 100/100; charge
starts at nothing on the M-343 pickup and only ever rises by two; a dual blaster
and a charge pack add no charge; the pack takes capacity to 200 and charge
follows past 100; firing a dual blaster spends capacity, and walking onto a
second one restores 100.

## #33: the Mechanoid's footsteps, where they can be heard

The Mechanoid's chase (states at 2d352) is 690 for 20 tics, 690 for 6, 691 for
8, 692 for 20, 692 for 6, 693 for 8. The 20-tic frames end with 17958, which
the Mechanoid alone uses: if `areabyplayer[ob->areanumber]` -- the alien's sound
area joined to the player's through open doors -- it plays sample 2 at the
alien's position. The short 690 ends with the ambient action (18346), which for
class 23 is sample 40 on a 1-in-7 roll, under the same area test. The
positional player (8d46) also drops low-numbered samples placed too far away.
Its death (17232) is one of samples 63, 76, 77 and 82.

The port played Solrac's ambient sound, sample 68, on every step, through
`A_PlaySound`, which has no area test: the wrong sound, heard everywhere. A new action, `A_C7AreaSound`, plays a sound only where the
listener's area is joined to the alien's, with the optional far-away cutoff and
a chance roll taken before the listener is consulted so that peers stay on the
same random stream. The Mechanoid uses it for sample 2 on its steps and sample
40 for its ambient, on the frames the original uses, and its own death sounds.

## #35: the med bay

Using a wall-85 med bay plays sample 16 before its shield opens (14c51). Using
the medic pack behind it (wall 88, 14af7) heals 25 and calls the bonus flash
(0ada:0ce6, which sets Wolf3D's `bonuscount` to 18), as GetBonus does for every
floor pickup. The ammunition and visor-battery units do not flash. The port now
plays the sample and flashes for the medic pack.

## #30: xBRZ never enlarges past the window

xBRZ enlarges the frame into the window, so it does nothing unless the frame is
drawn smaller than the window (Render Resolution below Native). *Auto* picks
that factor and, at Native, picks none. A fixed factor was applied regardless:
at Native it enlarged each frame two to six times past the window and the final
stretch shrank it back. Measured under Xvfb at 1920x1080 on the OpenGL path: 33
ms a frame with xBRZ off, 78 ms at 2x, and fewer than a hundred frames in
seventeen seconds at 6x. On a laptop or phone GPU, 2x is enough to stall; the
game keeps running underneath, which is the reported freeze.

A fixed factor is now a ceiling: never more than the smallest factor that
covers the window, allowing 5% short. At Native that turns it off. Choosing a
fixed factor in the menu while Render Resolution is Native also lowers it to
match, so 3x draws at a third of the window and enlarges it three times; Render
Resolution gains 1/5 and 1/6 so that every factor has one. Measured again at
1920x1080: 2x and 6x at Native cost what off does (33 to 40 ms, llvmpipe noise);
2x at 1/2 is 41 ms and 6x at 1/6 is 24 ms, both visibly filtered. The GL parity
gate now draws its 640x400 frame in a window the factor times larger.

## Tests

`corridor7_sight_screens` and `corridor7_health_energy` are new gates. The
definition checks pin the line rule (and that it keys on the marker), the
Adrenaline and charge-pack actions, the alien weapons' zero charge, the capacity
reset, the floor reset of the maximum, the Mechanoid's sounds and frames, and
the med bay's sound and flash. The verbs trace (`--capture-verbs`) now reports
alien charge, its capacity and the health maximum.

## Not changed

- The original switches back to the best alien weapon when a charge pack is
  picked up while holding something else (14111); the port does not.
- A duplicate human weapon is still refused when its ammunition is full; the
  original always takes it.
- The health chamber still heals in one step after its door closes, where the
  original drains its reserve a little each frame.
- Other classes' 1-in-7 ambient sounds (18346) remain off, as they were.
