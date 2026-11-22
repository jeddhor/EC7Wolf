# GitHub #54 to #58

Five reports against 1.0-beta315, from the same tester as #40 to #53.
Baseline: EC7Wolf 1.0-beta315. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line. Addresses follow
[github-issue-verification-2026-11-17.md](github-issue-verification-2026-11-17.md):
segment:offset is the Ghidra export's, five-digit numbers are physical
addresses in the memory image.

| # | Report | Finding | Change |
| --- | --- | --- | --- |
| 54 | Quicksave is silent | DOS says "Game %s saved." | Fixed |
| 55 | Elevator resets alien charge | Port bug | Fixed |
| 56 | Mines too weak | Port bug | Fixed: the original's blast |
| 57 | Infrared renders walls strangely | Distance shading differs from DOS | Open |
| 58 | Closing a blocked door blocks shots | Port bug (saves) | Fixed |

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
(57,5), surrounded by wall 77, the port draws nearby walls with bright red
specks and distant ones almost black, and the pattern shifts as the view turns:
the "sheen" and the black. Both renderers do the same.

A DOSBox-X capture of the original, in a lab MAP01 holding floor 26's walls
with the player at (57,5), shows wall 77 much darker: near-black in infrared at
every distance, and in the normal view dark beyond a few tiles, where the port
still shows its pattern across the room. The difference is the distance
shading. The port uses ECWolf's light model, tuned so MAP01 looks right
(DefaultLighting 130, DefaultVisibility 10); the original darkens each texel by
steps through its own ramp, masked per index (the table at DS:2a1e). Matching
it means porting that model to both renderers, which changes every floor's
look, not just infrared. Left open for a decision.

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
- The verbs trace (`--capture-verbs`) now reports a change of the mine's tile
  on its own; a mine that went off used to show only when something else
  changed with it.
- Checked by hand: the reporter's floor 26 save loads with its thirteen open
  doors repaired.
