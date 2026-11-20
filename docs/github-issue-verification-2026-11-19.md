# Mine arming and armor cap: GitHub #37 and #38

- **#37** a mine in DOS beeps once it is armed -- when the player has moved off
  it -- with the sound the menus use; the port's mines are silent.
- **#38** armor stacks to 999 in DOS; the port let three suits on floor 11 take
  it past 1100.

Both are real, and both are in CORR7CD.EXE.

Baseline: EC7Wolf 1.0-beta306. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

The method and address conventions are those of
[github-issue-verification-2026-11-17.md](github-issue-verification-2026-11-17.md):
segment:offset addresses are the Ghidra export's, five-digit ones physical
addresses in the memory image, and sample N is the port's `C7DS000N`.

## #37: the mine's two sounds

Dropped mines live in a 25-entry table at DS:40e4, 0x1c bytes each, with a
state word at +0x14: 2 placed, 1 armed, 3 set off (2f28:1a28 drops one).
The mine routine (2f28:2177, which Ghidra could not decompile) holds a placed
mine until its owner is more than 0xc350 away along either axis, then sets it
to armed and plays sample 33 (2370e: `mov [si+14h],1; push 21h; call
SD_PlaySound`). Sample 33 is the menus' sound, as the report says; the port's
menus already play it. The actor loop then tests every actor against every
armed mine (2f28:242e, called after each actor thinks): one within 0x9c40 along
both axes sets the mine off, with sample 1 (23985).

The port's mine was silent at both moments -- its definition even said the
original's arming path plays no sound -- and used half a tile (0x8000) for both
distances. It now beeps with sample 33 as it arms, for the player who dropped
it; plays sample 1 as it is set off; arms beyond 0xc350 (about three quarters
of a tile); and goes off within 0x9c40 (about six tenths).

## #38: armor stops at 999

GetBonus item 9, Body Armor (13f7c), adds 200 to armor (DS:8114), caps it at
999 (`cmp 3e7h`), shows "Body Armor" and flashes; nothing refuses the suit. The
port's armor had a 65535 cap. It is now 999, and a suit picked up at 999 is
still taken, as in DOS.

## Tests

`corridor7_health_energy` walks the lab corridor over six suits: armor reads
200, 400, 600, 800 and 999, and all six are picked up. The verbs trace now
reports armor and the player's pickup count. The definition checks pin the
mine's distances and sounds and the armor cap. The mine sounds themselves are
not observable headlessly.
