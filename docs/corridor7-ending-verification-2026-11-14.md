# The ending: MISSION HIT/MISS RATIO and the high scores

The port ended the campaign on a page of its own: "CONGRATULATIONS! You have
destroyed the vortex" over floors secured, kill and secret ratios, score and a
SECURED/SURVIVOR rating, then the high-score table. The #23 work found that the
original instead shows a second hit/miss page there, MISSION HIT/MISS RATIO, and
listed it as a known deviation. Jason asked for the ending to be the original's.
This note is what the original does, how that was established, and what the
port now does.

Baseline: EC7Wolf 1.0-beta299. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

## Reference and method

The same as [the #23/#24 note](github-issue-verification-2026-11-14.md): the
locally owned `CORR7CD.EXE` (SHA-256 `1287a13c…1c30f7`), run unmodified under
the project's DOSBox-X build with GDB on emulated memory. Code addresses are
physical addresses in the running game's 1 MiB memory image (DS = 0x37790);
data addresses are DS offsets. The disassembly, memory dumps and DOS captures
are private evidence in the parent workspace and are not part of this change.

The DOS run started a game, seeded the campaign totals (1234 shots, 567 hits),
the floor's counts (113, 66) and the score (54321) through GDB, set the floor
number to 39 (MAP40) and ended the floor, then photographed every screen to the
attract loop. The port was run with the same numbers (`--capture-mission-shots`,
`--capture-shots`, `--capture-score`) and compared pixel for pixel at 320x200.

## What the original does

**Leaving MAP40 wins.** The floor-exit handler (a0ab) checks the floor number
against 39 and, if it matches, sets the playstate to 6 and calls the victory
routine (a2cc). The port already did the equivalent: its elevator sets
`ex_victorious` on MAP40.

**The victory routine (a2cc)** plays `SEQFOUR.CO7`, calls the floor report
(a335), then asks the high-score table for a rank (2a49). Only if the score
ranks does it show the table and take a name (2a7e), leaving it up for
`IN_UserInput(420)` -- six seconds or a key. Then it returns, and the game goes
back to its attract loop. The DOS run confirmed the order: cinematic, MAP40's
status report, MISSION HIT/MISS RATIO, a fade, the table with name entry, about
six seconds, the Capstone logo.

**There is no victory page.** The executable does contain one -- a routine at
18af9 that centers "CONGRATULATIONS!" at y=70 and "You have destroyed the
vortex" at y=110 -- but nothing calls it: no far call, near call or stored
pointer to it exists anywhere in the memory image, and the DOS run never showed
it. The port's page was built on those strings and on the labels of the death
report ("Total floors secured", "Overall rating"), which belong to YOU'RE DEAD.

**The floor report (a335) draws the second page in two cases** (a541): when the
playstate is 6, as MISSION HIT/MISS RATIO (entered at a559), and on a bonus
floor, as BONUS LEVEL HIT/MISS RATIO. The victory test comes first. The two are
one routine with one difference: the mission page adds the last floor's counts
to the campaign totals and divides both tallies by 100, so a block stands for a
hundred shots (rounded down). Title, labels, colours, positions, award formula
-- `floor(hits*100/shots) * (floor(shots/100)+1) * 10` -- and the score line are
shared. With the seeded numbers DOS drew 1347 and 633, 13 and 6 blocks,
"Accuracy = 46%", "Bonus = 6440 points" and "Score = 60761 points", and memory
showed the score raised by exactly 6440.

**The campaign totals** are two 32-bit counters at DS:813e (shots) and DS:8144
(hits). Every floor's setup (216b4) adds the previous floor's counts to them
and clears the floor's -- bonus floors included, since their counts are added
at the setup of the floor they return to. NewGame (6cfd) clears the whole block
they live in. A player reset (235b1, on a new game and on the respawn path at
9eee) clears the shot counters but not the hit counters; the respawn path is
not reachable in a single-player campaign, so this has no visible effect.

**The tallies count up only while a direction is held.** After each block the
routine redraws the screen and calls `TicDelay(50)` (a6a4, the Wolf3D routine at
e4bf), which waits while a direction is held and returns at once otherwise. A
second DOS run held Right through the page: the shot tally grew one block about
every 0.7 seconds and the rest appeared the moment the key was released.

**The high-score row being earned** (2a7e, from 241ab) is redrawn before the
name is asked for: a navy (0x30) bar at (20, 60+18n), 280x16, inside a yellow
(0x6f) frame from x=20 to 300 and y to y+16; the floor and score redrawn over
it in the row's colours; and the name typed at (24, 62+18n) in the score's
colour, at most 18 characters in 262 pixels. Every string on the table has a
black drop shadow -- including the floor and score on the navy bar, although
the caller sets DS:8b68 to 0x30 there, so that byte is not the shadow's colour
as the #23 note had assumed. The typed name has no shadow.

## What the port does now

- `GameLoop`: at a Corridor 7 campaign end the floor report is always shown --
  on a map pack's last floor too, with or without `forcetally` -- and told it is
  the finale; the port's victory page is not shown; the high scores are shown
  only if `HighScoreWouldRank` says the score would enter the table, otherwise
  the log says so. The cinematic still plays first, and the game then returns
  to the attract loop as before.
- `InterDoCorridor7(finale)`: after the status report, the finale shows
  MISSION HIT/MISS RATIO over each player's totals plus the floor's counts and
  pays each player their own award; a bonus floor shows its own page as
  before. Both print a `hit/miss:` line to the log.
- `C7DrawHitMissPage`: one routine for both pages, a block per hundred shots on
  the mission page. While a direction is held -- read from the live keyboard as
  well as the control state, because the key table is cleared when the status
  report is dismissed -- each block is shown and waits up to 50 tics.
- `player_t::c7MissionShotsFired/Hit`: added at `SetupGameLevel`, cleared by
  `Reborn` on a new game or warp, saved from save version 1794700000. An older
  save loads with zero totals and logs that the ending will count from the
  floor it was made on.
- `CheckHighScore`/`DrawHighScores`: black shadows on the whole table; the
  earned row's bar, frame and redrawn floor and score; the name typed in the
  row's colour through a new palette-colour mode of `US_LineInput` that erases
  only what it drew; and the original's 420-tic hold after the table, on the
  death path as well as the ending (the port had faded out at once after a
  name, and waited 500 tics without one).

With the seeded numbers the port's mission page matches the DOS capture in
every text and block pixel (0 of 3917); the remaining differences are scaler
noise in the tiled backdrop, as on the bonus page. The status report's values
match. The high-score table matches in every text pixel, the earned row
included; what differs is shading in the portrait behind it. Software and
OpenGL produce identical pages.

## Tests

`tools/test_corridor7_ending.sh` (gate `corridor7_ending`) runs the ending with
the DOS numbers and checks the log's totals and award, the block counts, the
earned row's bar, frame and typed name; an unranked ending that skips the
table; a held direction pacing the tally; MAP39's shooting reaching MAP40's
totals, through a save and a load; and a bonus floor's shooting joining them.
`test_corridor7_definitions.py` now requires the ending's structure and forbids
the invented page's text.

## Not verified

- What `SEQFOUR` does with the flag the victory routine sets around it
  (DS:0d72). The port plays the cinematic as it already did.
- A full campaign played to the end in DOS. The totals' accumulation is read
  from the code, and the port's is checked across a floor change, a bonus floor
  and a save; the end-to-end DOS evidence is the seeded run.
- Network games: each player is paid their own mission award, as on bonus
  floors; the original's network ending was not examined.
