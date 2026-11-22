# GitHub #40 to #53

Thirteen reports against 1.0-beta310, all from one tester (there is no #50). Baseline: EC7Wolf
1.0-beta310. Engine base: ECWolf 1.4.2-9-g1bff92d (18 February 2026), on the
upstream 1.5.0pre line. Addresses follow
[github-issue-verification-2026-11-17.md](github-issue-verification-2026-11-17.md):
segment:offset is the Ghidra export's, five-digit numbers are physical
addresses in the memory image.

| # | Report | Finding | Change |
| --- | --- | --- | --- |
| 40 | Alien weapons reset capacity | DOS does it too | Optional rule, Classic by default |
| 41 | Visor tint survives death into menus | Port bug | Fixed |
| 42 | Mines placed too far forward | Port bug | Fixed: dropped under the player |
| 43 | Saves sort wrongly past ten | Port bug | Fixed: numeric order |
| 44 | Card icons do not animate | Port bug | Fixed |
| 45 | Quicksave asks to overwrite | DOS does not ask | Own slot, no question; option to ask |
| 46 | Red card icon cycles blue | DOS does too | Optional, off by default |
| 47 | DOS sprites are fullbright | Accepted | Optional, shaded by default |
| 48 | Duplicate weapons refused at full ammo | Port bug | Fixed |
| 49 | Every weapon sets mines off | Port bug | Fixed: only projectiles |
| 51 | Floor 17 secret unreachable | DOS map error | Optional fix, Classic by default |
| 52 | Automap shows a broken status bar | Port bug (GL) | Fixed |
| 53 | Floor 16 health chambers inert | Port bug | Fixed |

## #40: alien weapons and capacity

GiveWeapon (13ec1) begins `cmp [bp+6],4; jl; mov word [80f0],100`: every alien
weapon sets energy capacity (DS:80f0) to exactly 100, whatever it was. Every
alien-weapon case in GetBonus (13f3c, jump table CS:091a) calls it with no test
before, and GetBonus has no refusal path. So the reported behavior is DOS's.
Options > Gameplay > Alien Weapon Capacity offers **Keep Higher**, which only
raises a capacity below 100. Like the shotgun and alarm rules it applies to new
games, is decided by the host in multiplayer (new-game packet, protocol 17),
is kept in saves ("EC7Wolf Alien Weapon Capacity") and is in the sync checksum.

## #41: the visor after death

The play loop skips `FinishPaletteShifts` when the player died, inherited from
Wolf3D, where the red damage shift is meant to last through the death. The
visor's night or infrared DAC was left with it, so Corridor 7's death page, the
high scores and the menus behind them came up green or red. The Corridor 7
death branch of GameLoop now clears it on the black screen after its fade,
which is what the in-game menu already did.

## #42: where a mine lands

The drop routine (2f28:1a28, 22ec8) copies the dropper's x and y (actor +0x12,
+0x16) into the mine: it lands underfoot. The port put it 40/64 of a tile
along the facing, which could be inside a wall. The bots' model of where their
own mines land and how far the trigger reaches (0x9c40 since #37) was updated
with it.

## #43: save order

The save menu listed saves in directory order, which is alphabetical on
Windows (savegam10 between savegam1 and savegam2) and arbitrary elsewhere.
Saves are now sorted with runs of digits compared as numbers.

## #44 and #46: the card icons

DOS rotates the DAC ramps 208-239, so everything drawn in those colors
animates. The port cycles them per pixel in the world renderers; the status
bar's graphics never passed through that, so its card icons stood still. The
card and floor-plan icons (C7G0019-21, the only status-bar graphics that use
the ramps) are now drawn through a remap of the same tic-driven phase, in all
three HUD layouts.

The red card's icon (C7G0021) uses the blue ramp 216-223, as in DOS, though the
red card lying in the world (sprite C002) uses the red ramp 208-215.
Graphics > Red Access Card Icon reads the icon's blue ramp as the red one.

## #45: quicksave

The executable contains "Saving..." and "Loading..." and no confirmation text.
F8 now writes a slot of its own, `quicksav.ecs`, listed as "Quicksave", without
asking; the named saves are never touched by it. Options > Gameplay > Confirm
Quick Save brings the question back. F9 loads the quicksave, still asking
first, since loading discards the game in progress; with no quicksave it opens
the load menu.

## #47: fullbright sprites

Not measured against the original; the tester's description is consistent
with everything else they have reported. Graphics > Fullbright Sprites draws
every Corridor 7 sprite fullbright in both renderers. The default stays shaded,
as the tester prefers, since that is what makes the night-vision visor useful
in dark rooms.

## #48: duplicate weapons

GetBonus never refuses a weapon; GiveWeapon tops the ammunition up. The port
refused a duplicate human weapon whose ammunition was full, which was listed as
a known difference in beta306. It is now taken.

## #49: what sets a mine off

Mines are not objects in DOS: they are entries in a 25-slot table at DS:40e4.
The main loop (0xbfc2-0xbfec) runs every object in the actor list and then
passes it to the mine test (2f28:242e, 238ce), which sets off any armed mine
within 0x9c40 of it on both axes. A plasma bolt is an object; a hitscan shot is
not. So the Plasma Rifle sets mines off and the other player weapons cannot,
and since an explosion is not an object either, mines do not chain. The port's
mine was shootable, so every weapon hit it. It is no longer shootable, and its
trigger test now also accepts projectiles (alien ones too, as in DOS).

## #51: floor 17's secret

The secret pushwall at (13,2) is pushed south from the corridor at (13,1). It
slides into (13,3) and stops against a lone wall block (34) at (13,4), whose
neighbours (12,4) and (14,4) are floor; (13,3) is the only cell leading on to
(12,3) and (14,3), so the secret behind them cannot be reached. That is the
shipped map data, so DOS has it too. Options > Gameplay > Original Map Errors
**Fixed** makes (13,4) floor (259) at load, so the wall slides its two tiles;
**Classic**, the default, plays the data as shipped. The rule travels like the
others (new-game packet, save text, checksum), and the fix applies only while
the three cells still hold their shipped values, so a replacement floor 17 in
a map pack is left alone.

## #52: the automap's status bar on GL

The full automap draws the play screen as if the view were size 20, which
puts up the full status bar, while the 3D view stays the size the player chose.
At size 21 (the full-screen mini HUD) the bar therefore lies inside the 3D
view. The GL backend composites 2D over the world and keys out black texels it
was not told were painted, and the automap was the one overlay not drawn
through the seam that tells it -- so the LEVEL, SCORE, item and meter boxes,
which are black, showed the world behind them. The automap is now drawn
through that seam like every other overlay. Software was never affected.

## #53: floor 16's health chambers

Floor 16 has two wall-35 chamber panels at the ends of an outer corridor, and
no chamber door (wall 53) anywhere. The port required a door one cell behind
the player, so they did nothing. CORR7CD.EXE registers every wall-35 cell as a
chamber when the floor loads (9a35: `cmp [bp-0Ah],23h` then AddChamber, 226ad),
and its chamber, once it has turned the player, closes a door two cells along
its direction only if the door list has one there (2284e); otherwise it goes
straight on to heal. The port now does the same: a chamber without a door
keeps its reservoir on the panel's cell, turns the player away from the panel
and heals. With the reporter's save, the panel heals 226 to 326.

## Tests

- `corridor7_health_energy` (lab corridor): capacity under both #40 rules;
  a mine dropped facing the end wall lands in the player's cell (#42); an
  M-16 burst leaves a mine lying and a plasma bolt sets it off (#49).
- `corridor7_health_energy` also: a doorless chamber heals (#53); on the
  shipped floor 17 the pushwall stops short by default and slides clear with
  the map fix (#51).
- `corridor7_ui_fixes` (new, Xvfb): on GL with the full-screen view, the
  automap's SCORE box shows nothing of the world (#52); the death page after a night-vision death
  is not green (#41); the card icons change between frames (#44); with the
  option the red icon has no blue-ramp pixel left (#46); F8 writes and
  rewrites `quicksav.ecs` without asking, and with Confirm Quick Save on a
  second F8 waits (#45). On beta310 every one of these fails.
- `corridor7_definitions` pins the source of every change, including the
  numeric save order (#43), the fullbright option (#47) and duplicate weapons
  (#48).
- Checked by eye: twelve saves listed 0 to 11 in order; the fullbright option
  lights the props in MAP20 in both renderers.
