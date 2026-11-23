# GitHub #54 to #58

Five reports against 1.0-beta315, from the same tester as #40 to #53.
Baseline: EC7Wolf 1.0-beta315. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line. Addresses follow
[github-issue-verification-2026-11-17.md](github-issue-verification-2026-11-17.md):
segment:offset is the Ghidra export's, five-digit numbers are physical
addresses in the memory image.

| # | Report | Finding | Change |
| --- | --- | --- | --- |
| 54 | Quicksave is silent | DOS says "Game %s saved." | Fixed (beta317) |
| 55 | Elevator resets alien charge | Port bug | Fixed (beta317) |
| 56 | Mines too weak | Port bug | Fixed (beta317): the original's blast |
| 57 | Infrared renders walls strangely | Distance shading differs from DOS | Fixed after beta317: the original's shading |
| 58 | Closing a blocked door blocks shots | Port bug (saves) | Fixed (beta317) |

## #54: quicksave message

Beside "Sound %s." and "Music %s." in CORR7CD.EXE's string table are
"Game %s saved." and "Game %s retrieved.": the original reports a save or a
load on the play screen's message line. F8 and F9, and saving or loading from
the menus, now do the same through the status bar's top message. The capture
harness's own saves and loads say nothing, so its screenshots are unchanged.

## #55: charge at the elevator

The floor setup (216b4) begins `mov ax,64h; mov [80f0],ax; mov [8106],ax`:
energy capacity and the health maximum back to 100. It does not touch the
charge (80de). The recharge in the palette-cycle routine (219a8) adds two only
while `80de < 80f0`, and nothing else in the executable lowers charge to
capacity except the debug key handler's ammunition cheat (1628:01c3). So a
player with 600 charge reaches the next floor with 600 and 100 capacity, and
recharges again only once below 100. The port clamped charge to capacity every
tic, which emptied it at every elevator, and also whenever an alien weapon was
picked up (#40's case). It no longer does.

## #56: the mine blast

MineTest (2f28:242e) only marks a mine as exploding: state 3 and the object
that came near, at +0x0a. The blast is the mine table's state-3 handler
(23720, jump table CS:2424). It advances the explosion's picture every five
tics, and on every frame while the fourth picture shows:

- rolls `US_RndT()*2 + 100`, 100 to 610;
- hits every shootable object in the tiles from three before the mine's to two
  after it on each axis (the loop stops short of +3) with the roll shifted right
  by its Manhattan distance in tiles -- full in the mine's tile, half one tile
  away;
- hits the object that set it off with the full roll again, unless it is the
  player;
- hits the player, in -3..+3 on each axis, with the roll shifted by distance.

`tics` (DS:8c9e, set by CalcTics at 0fcd5) advances the picture, so the number
of passes depends on the frame rate. At two tics a frame, the 35 frames a
second the port assumes everywhere else, it is three. The port exploded once
for 102..500 with a straight fall-off to nothing at two tiles, and never hit
the trigger again, so an alien walking onto a mine took a third of what it
does in DOS. A_C7MineBlast now does the above, three times, on the fourth
picture, after one frame of the mine itself as the original shows it. The
bots price a mine's danger out to three tiles.

## #57: infrared walls

Under infrared, the original's DAC (the port's Corridor7InfraredPal) turns
positions 0 to 7 of every 24-entry colour ramp black, so whatever the distance
shading pushes into them disappears. With the reporter's save on floor 26
(57,5), surrounded by wall 77, the port drew nearby walls with bright red
specks and distant ones almost black, and the pattern shifted as the view
turned: the "sheen" and the black. Both renderers did the same.

A DOSBox-X capture of the original, in a lab MAP01 holding floor 26's walls
with the player at (57,5), shows wall 77 near-black in infrared at every
distance, and in the normal view dark beyond a few tiles. The port used
ECWolf's light model, tuned so MAP01 looked right (DefaultLighting 130,
DefaultVisibility 10). Matching the original meant porting its model, which
changes every floor's look; Jason chose to do that, after beta317, as an
option that is on by default (Graphics > Lighting: Original or Enhanced).

**Walls and sprites.** Each compiled scaler (SetupScaling 1e37:0061 builds
one per height) sends every texel through a subroutine with the column's shade
in CH: `and cl,[bx+2a1e]; sub al,cl; mov bl,[bx+2b1e]; sub bx,ax; and al,bh`.
The texel moves SHADE entries down its ramp and becomes 0 (black) once it
reaches or passes the ramp's first entry. From a running game's data segment,
the mask at DS:2a1e is 255 for 16..207 and 0 elsewhere, and DS:2b1e holds
each ramp's first entry, 16 + 24n. The shade comes from DS:c0a2, which
2f28:042b fills with 16 at index 0 and one less every five entries to 0 at 76.
ScalePost (0f11c) indexes it with `(wallheight >> 3) + c1ac*2 + 8b5c`,
ScaleShape (10cec) with `(height >> 1) + ...`, and SimpleScaleShape, the
weapon, uses shade 0. `c1ac` is 4 while the muzzle flash is lit. `8b5c` is a
brightness level, 0 to 10, moved by `=` and `-` (DebugKeys places Keyboard[]
at DS:8b6d) and saved in CONFIG.DAT, 0 without one. Heights use Wolfenstein's
projection for a 320-wide view, heightnumerator 223232: a wall is unshaded
within about 1.4 tiles and at shade 11 by five; a sprite stays unshaded to
about five.

**Floor and ceiling.** ThreeDRefresh (1cb7:1088) first calls 1cb7:0a17, which
writes each plane row as words, so even four-pixel groups take one palette
entry and odd groups the next, swapping each row. The ceiling starts at the
byte DS:8dfa and steps down one entry every three rows to DS:8df8. The floor
starts at the horizon on DS:8df9, holds for 48 rows, then steps up every three
rows toward DS:8df7. 18b8:1177..11a3 sets the four per floor: 38/18 and
184/200, or from a jump table on MAP20 to MAP29, red 76/66/66/76 (MAP20, 21,
24, 26, 29) or green 122/114/114/122 (MAP22, 23, 25). These are MAPINFO's new
`C7Planes`.

**View height.** ECWolf's Wolfenstein status bar reports 41 lines, keeping a
spare line above the bar. Corridor 7's is 40 and its view 160, so the port's
view was a row short: its last row was black and the weapon sat a row high.
It is now 160 lines.

Measured against DOSBox-X captures at 640x400:

| Scene | Original (DOS) | Original lighting | Enhanced |
| --- | --- | --- | --- |
| Floor 26 lab, infrared: texels redder than 60 | 1852 | 1833 SW, 1824 GL | 10649 |
| Floor 26 lab, normal view: the same | 12464 | 12465 SW | 31096 |
| MAP01 start, wall band colour-histogram distance | 0 | 0.187 SW, 0.183 GL | 0.243 |
| MAP01 start, plane pixels sampled that differ | 0 | 121 SW, 109 GL of 1088, all at wall edges | 974 |

## #58: force-field doors after a load

A force-field door's plane-1 marker is its state: 106 while the barrier is up,
107 once the aperture is open. Shots and sight pass 107 and not 106 (CheckLine,
GitHub #31). The marker was not saved. A load rebuilds the map from MAPTEMP and
then applies the saved state, so every door that had been opened came back as
106 with its saved open texture, open sides and joined areas: drawn open,
walkable, sound passing, and stopping every shot both ways. Using it then ran
the opening sequence again, since 106 means closed, rather than closing it.

The reporter's save holds thirteen such doors on floor 26, including both
doors of the room in question. The alien that died in the doorway is
incidental: a body there does stop the door closing, since anything that
counts as a monster in the cell does, but the shots are stopped by the load.

Saves now keep the marker and the sight flag. An older save is repaired on
load: a 106 cell open on every side can only be an open door.

## Tests

- `corridor7_health_energy`: charge above 100 survives the next floor with
  capacity back at 100 (#55); a Solrac standing on a mine is hit three times,
  two tics apart, for at least 450 (#56). Both fail on beta315 (charge 300 to
  100; a single 456-point hit).
- `corridor7_saved_doors` (new): a force-field door is opened and the game
  saved; after a load, shots down the corridor reach a Mechanoid behind an
  electric fence beyond it. Fails on beta315.
- `corridor7_ui_fixes`: after the floor's opening objective has gone, F8 puts
  "Game Quicksave saved." on the message line (#54). Fails on beta315.
- `corridor7_definitions` pins the blast's three passes, its roll, windows and
  trigger hit.
- `corridor7_original_lighting` (new, #57): on MAP01 every pixel of the
  ceiling's top 40 original rows and the floor's bottom 30 (beside the weapon)
  is the original's pattern, in software and GL, and the view's last row is
  drawn. In a lab of floor 26's walls at the reporter's (57,5), the count of
  texels redder than 60 stays within 15% of the DOSBox-X captures (1852 under
  infrared, 12464 in the normal view) in both renderers, while Enhanced
  lighting is run too and must exceed twice that.
- `corridor7_definitions` pins the scaler tables, the per-floor plane values,
  and the 40-line status bar.
- `gl_live` compares exactly the status bar now. Its fixed 100-row band reached
  four rows into the view, which only matched while the view stopped a row
  short of the bar.
- The verbs trace (`--capture-verbs`) now reports a change of the mine's tile
  on its own; a mine that went off used to show only when something else
  changed with it.
- Checked by hand: the reporter's floor 26 save loads with its thirteen open
  doors repaired.
