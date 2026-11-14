# #23 and #24: bonus floors and the Intruder Alert

Jason approved the remediation plan for
[#23](https://github.com/jeddhor/EC7Wolf/issues/23) (secret-level inventory and
the missing hit/miss page) and
[#24](https://github.com/jeddhor/EC7Wolf/issues/24) (the Intruder Alert waking
the whole floor). This change implements both, including the optional map-wide
alert the #24 reporter asked for.

Baseline: EC7Wolf 1.0-beta297. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

## Reference and method

The reference is the locally owned CD executable `CORR7CD.EXE`, SHA-256
`1287a13c2ac16624a1eb70ae1d207ad293e3aef6b852fa3d3f5eb6591d1c30f7`, run
unmodified under the project's DOSBox-X build with GDB on emulated memory.
**Code addresses in this note and in the source comments it describes are
physical addresses in the running game's 1 MiB memory image** (DS = 0x37790),
not file or load-module offsets as in earlier notes; data addresses are DS
offsets. Private evidence -- disassembly excerpts, memory dumps and the DOS
captures -- is under `analysis/verification/issues-2026-11-14` in the parent
workspace and is not part of this source change.

## #23 — Bonus floors

**Entry state.** On a bonus elevator the exit handler (a14a) copies nine values
to DS:40d2..40e2, and on leaving a bonus floor (a0f6) copies them back: health
80d0, bullets 80d2, armor 8114, visor charge 80e6, alien weapon energy 80de,
selected weapon 80da, owned-weapon bits 80ce and two selection-history words
80d8/80dc. A live run (MAP01 -> MAP41 -> MAP02, debugger-seeded values) changed
every field on the bonus floor and found all nine restored, with ammo capacity
(8104, 200 -> 700) and mines (8116, 7 -> 2) keeping their bonus-floor values.
The reporter's "everything is reset" is right for the nine and wrong for those
two.

Lethal damage on a bonus floor (13dfb) sets the same result as the exit (exit
code 1 at 13e22) and never reaches the death path; the restore runs for both.
This route was verified from the code, not from a lethal-damage playtest.

The port now takes the entry state on arrival at a bonus floor -- by elevator,
warp or a new game started there -- in `C7CaptureBonusEntry`, and
`C7RestoreBonusEntry` hands it back after the report pages, before the next
floor's setup. Only amounts are restored, never maximums, which is what keeps a
capacity upgrade. Weapons are restored as a set: one found on the bonus floor
is removed, and the selected one is put back in hand.

**Floor setup.** Every floor's setup (216b4) caps health at 100, sets the
alien-weapon capacity (80f0) and the maximum-health boost (8106) back to 100,
and ends invulnerability (80e8). The port capped health but carried the other
two through every floor change; `C7NativeFloorSetup` now does all of it.

**Saves.** The entry state is saved with the player (save version gate
1794600000, after beta297's 1794469260). An older save made on a bonus floor
cannot say what was carried in; loading one takes the loaded inventory as the
run's baseline and logs that it did, rather than guessing.

**Reports.** The status report (a335) pays its own award: the efficiency rating
times 100, where the rating is the mean of aliens eliminated (capped at 100) and
restricted areas found, each zero when the floor has none; a bonus floor shows
N/A and is rated on aliens alone. Values are printed at x=208 on rows
70/85/100/126/140/155 in the original's `%3d%%` and `%6ld` formats, green (0x87)
then yellow (0x6f). The port had been printing the hit/miss accuracy and its
award there instead, on every floor.

After a bonus floor the original then draws **BONUS LEVEL HIT/MISS RATIO**
(a552) over the skull backdrop: the title in the large font at y=10; "Shots
fired:" and "Shots hit:" in the small font at x=10, their counts at x=13 ten
pixels lower in white (0x27); a 3x3 block per shot from x=90, four pixels apart,
53 to a row, salmon (0x57) and magenta (0xb7); then the accuracy and bonus in
blue (0x3f) and the score in yellow, centered, twenty pixels apart. The award
(a73c) is `floor(hits*100/shots) * (floor(shots/100)+1) * 10`, nothing for no
shots. Every string has a black drop shadow one pixel down and right (the text
routine's DS:8b68 color). With the DOS run's 113 shots and 66 hits the port's
page matches the DOS capture glyph for glyph, block for block, and the status
report's values likewise; the remaining differences are scaler noise in the
background art. The original draws the second page without a fade, and the
port waits for the key that dismissed the first to be released, so one long
press no longer skips both.

Each player is paid for their own shots, so a netgame's machines agree on the
score whichever screen shows it.

Not done: the original shows the same page as **MISSION HIT/MISS RATIO** after
the final floor, over campaign totals with a block per hundred shots (a559).
That needs campaign-wide shot counts and belongs with the unreproduced victory
page; it is listed under known deviations in `corridor7.md`.

## #24 — The Intruder Alert

The alarm panel (14bfd) plays one of two sounds and sets DS:b3d7, the noise
flag gunfire sets, which the main loop clears before the next frame (bf8e).
Nothing else: no level-wide alert, no radius around the terminal. Who reacts is
decided by SightPlayer (136e1):

- an alien whose area is not reachable from the player's (DS:43a8) reacts to
  nothing -- that is the open-door test the port's `CheckLink` already makes;
- an ordinary alien reacts to the noise without needing sight, after its usual
  reaction delay;
- an ambush alien (flag 0x40, floor word 278) draws `US_RndT()`; above 230 it
  loses its ambush and gets a delay of `(US_RndT()+1) << 5` tics (13777), after
  which it comes looking whether or not it can see the player, and seeing the
  player before then ends the delay at once (1371c). Otherwise it still needs
  sight. Ambush is not deafness, and there is no boss exemption: MAP05's boss
  stands on an ordinary floor and MAP40's on 278, and each follows its floor's
  rule.

The port woke every live monster at once. Now `P_Corridor7IntruderAlert` makes
the noise and nothing more, and SightPlayer applies the native ambush draw in
Corridor 7 -- to gunfire too, which had left ambushers entirely deaf. The
delayed wake reuses the actor's reaction countdown, marked by an internal flag,
so it survives save/load without a format change.

**Map-wide alert.** The reporter preferred the panic of the old behavior for its
own sake, so Options > Gameplay > Intruder Alert offers Classic (default, the
DOS rule) and Map-wide, which lets the alarm's noise through every door and
wall and changes nothing else -- ambushers and bosses are judged by the same
draw. Like the shotgun rule it is fixed per game: the host's choice travels in
the new-game packet (network protocol 11), saves record it (absent means
Classic), and demos use Classic.

Not done: the plan's live DOS alarm matrix (near/far, open/closed door,
ambusher and boss cases under DOSBox with deterministic RNG) was not run; the
rule is taken from the executable's code, which is unambiguous about the noise
flag, the area test and the ambush draw. The port's hearing still lets an
alien's own `maxheardist` apply, so the four disguised Bandor furniture pieces
keep their four-tile hearing for the alarm as they do for gunfire.

## Tests

- `tools/test_corridor7_bonus_floor.sh`: warp, elevator-and-death, save/load
  and the six bonus routes; capacity and mines kept; the accuracy award paid
  exactly once.
- `tools/test_corridor7_intruder_alert.sh`: a lab map with an alien in the
  player's area, one behind a closed door and twenty-seven ambushers, under no
  alarm, the classic and map-wide rules, a loaded map-wide save and sustained
  gunfire. Run against beta297 it fails on the door, the ambushers and their
  deafness to gunfire.
- `tools/test_corridor7_definitions.py`: the old "intruder alert wakes every
  live monster" and combined-tally assertions replaced by the native rules.
- New capture options for these: `--capture-shots`, `--capture-secretexit`,
  `--capture-inventory`, and a repeatable `--capture-give`.
