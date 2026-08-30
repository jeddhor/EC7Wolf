# EC7Edit — E6 evidence ledger

Milestone E6: the structures that are more than one word, the two rules
Corridor 7 decides by topology rather than storing, and the coverage report
that is the milestone's exit gate.

---

## 1. Coverage, which is the exit gate

The promise is not "every word has a tool". Some words are preserved-only by
design and one is Advanced. The promise is that **nothing is silent**: every
value the translation defines is either offered through a friendly tool or
carries a written reason why it is not.

`scripts/coverage_report.py --check` is that gate. It fails on anything that is
neither, and it found six gaps the first time it ran:

| Value | What it turned out to be |
| --- | --- |
| 11 | the **BLUE** access terminal — 9 is RED, and my catalogue called both "Access terminal" |
| 30 | the intruder alarm terminal, which wakes the floor |
| 88 | the health chamber's alternate wall page, used directly by two maps |
| 102 | the second word for a plain moving wall |
| 254 | the second word for a plain door |
| 287 | the floor exit crossed rather than used |

Two of those were naming bugs rather than missing tools. `lnspec.cpp` maps
door argument 1 to `C7Static001` and 2 to `C7Static002`, and the terminals pass
exactly those, so 9 grants red and 11 grants blue. The catalogue now says so.

Current state: **457 entries — 28 placed by a compound tool, 400 single words
the brush handles directly, 29 preserved from imported maps.** Nothing
unaccounted for.

## 2. Nineteen compound tools, each with its contract

The design guide asks each prefab to own six things: a write set, a
precondition, a preview, an undo transaction, a validation rule and a rotation
rule — plus a source reference. Five are structural and a test enforces them; a
prefab constructed without writes or without evidence raises.

The seventh is the one a reviewer actually needs, and the gate checks it
separately: every tool cites the translation entry its words come from, so the
word set can be checked rather than trusted.

The rule that shapes all of them: **a prefab writes raw words and nothing
else.** There is no second representation, so a map built with these tools is
exactly a map somebody could have built by hand, and the editor never becomes
something the file format has to know about.

## 3. The door rule, copied rather than reasoned about

A door's axis is not in the map. The engine counts its open neighbours:

```cpp
const bool horizontal = (openNorth + openSouth) > (openWest + openEast);
```

Note the `>`. A tie is *not* horizontal, so a door with equal openness both ways
falls to the default vertical plane, and everything about a four-way opening
depends on that one character. `rules.door_axis` reproduces it, boundary checks
included — off the edge of the map counts as closed, because the engine's
bounds tests make it so.

The engine's own name for the result is `horizontal`, meaning the tile's
horizontal offset, which is the *opposite* of the corridor it blocks and reads
backwards to everyone. The editor labels it by the corridor instead: "blocks a
north-south corridor". Same boolean, comprehensible sentence.

Tested for north-south, east-west, the tie, a corner, a fully blocked door, the
map edge, and a zone-numbered floor counting as open.

## 4. A transporter is a pair, so the tool is too

Eight channels, each needing exactly two endpoints. The tool remembers the
first click rather than writing it, and places both ends as one command when
the second arrives — because a channel with one end is not a half-built
transporter, it is a broken map, and leaving one behind after an interrupted
click would be a defect the raw words cannot show you.

Clicking the same cell twice does not pair it with itself, a pad refuses to go
anywhere but floor, and the validator reports any channel that does not have
exactly two ends.

## 5. Rotation moves the footprint, the catalogue moves the facings

Two different things, deliberately kept apart:

* a **prefab** rotates its *offsets*. A dispenser needs floor in front of it,
  and in the left-hand wall "in front" is east, not south. `Prefab.rotated`
  turns the preconditions with the writes, and a test places one in a left wall
  that is refused upright and accepted after three turns;
* a **selection** rotates its *values*, through the catalogue, by name — the
  E3 mechanism, now reachable from Edit → Rotate selection.

## 6. What the tools refuse

Refusing is the useful half. A dispenser with no floor in front of it is a wall
unit nobody can reach, and finding that out at playtest is much worse than
being told at the click. Every refusal names the cell and the reason, and
writes nothing at all — a test asserts the planes are byte-identical after one.

## 7. Tests

| Suite | Tests |
| --- | --- |
| `test_prefabs` | 40 — contracts, placement, preconditions, rotation, doors, transporters |
| `test_editing` (offscreen GUI) | 64 — including structures, transporters, clipboard, statistics |
| **E6 additions** | **~40 new** |

Whole editor suite: **610** — 488 headless, 122 offscreen GUI.

## 8. What E6 did not do

No plane-2 editor — it stays preserved and untouched, which is the plan's
position and the honest one, since nothing here knows what plane 2 means. No
custom or user-defined prefabs. No masked-wall tools beyond the two markers the
translation defines: the design guide lists "masked wall that blocks sight" and
"masked wall that permits sight" as separate tools, but the words behind them
(86, 87, 88 on plane 1) appear only inside wall cells in the shipped maps and
the translation ignores them, so they remain **Raw, imported-only** with that
reason recorded rather than being given a tool that guesses.

The secret elevator is likewise not a tool. Its wall/marker combination is
described in the plan as "based on the required wall and marker", and I could
not establish which pairing that is from the translation alone — word 99 is
ignored with a comment saying map setup promotes a tile-63 elevator to a bonus
exit, which is engine behaviour rather than something the editor writes. It is
reachable as raw words and labelled, not silently missing.
