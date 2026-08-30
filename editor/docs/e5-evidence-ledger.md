# EC7Edit — E5 evidence ledger

Milestone E5: the first playable vertical slice. You can now open a Corridor 7
map, change it, and play what you changed.

---

## 1. The exit gate, met verbatim

`test_ec7edit_slice.sh` does what the milestone says a person must be able to
do, in one run, through the real window against the real game:

| Step | Result |
| --- | --- |
| Import MAP01 from the owned archive | `'Corr7 Level 1'` 64×64, digest recorded |
| Decode a wall thumbnail from the artwork | 64×64, not a flat colour |
| Paint that wall from the palette | wall 2 written at (2, 1) |
| Place an enemy | Rodex at (4, 2) facing east, raw 216 |
| Configure it in the inspector | turned north, raw 217 |
| Undo both, redo both | history returns to the same depth |
| Save and reopen | every word and all sixteen name bytes identical |
| Export a one-map WAD | the exported words are the project's words |
| **EC7Wolf enters it** | **player spawns at (2, 62), not the stock (7, 31)** |
| The archive | SHA-256 unchanged |

The engine evidence is the player start, moved by the edit. An override that
silently did nothing would spawn on the stock tile, so the assertion cannot be
satisfied by a preview that failed to load. Grade **A**.

## 2. A defect that would have made painting unusable

Documents are immutable, so every edit hands the tool controller a fresh
snapshot mid-stroke. `set_document` cleared the drag anchor — correct when the
user switches maps, catastrophic on a refresh: **every drag stopped after its
first cell.** Painting would have looked like it worked on a click and been
broken on a stroke, which is the sort of thing you notice on day one of using
it and not before.

It now clears the anchor only when the map's identity actually changes. Found
by `test_a_drag_paints_a_continuous_line`, which asserts no gaps.

A second one in the same area: `int()` on a Qt 6 flag enum raises, and the
canvas did exactly that when emitting a press. The first click in a real
session would have thrown.

## 3. The validator earns being read

A first version reported five errors on every map the game shipped. A validator
like that teaches people to close the panel, and then the one that mattered is
lost with the rest.

Two things fixed it, and one of them was a real catalogue bug:

**Pushwalls belong inside walls.** Plane-1 words 98, 101, 102 and 106 configure
the wall cell they sit in — that is what a pushwall *is*. The catalogue had
them as floor placements, so every shipped map reported its moving walls as
things buried in stone. Corrected in `catalog.py`, and the validator was what
found it.

**Imported content is judged more gently than authored content.** The shipped
maps really do have twelve cells with a thing inside a wall. Reporting somebody's
legally purchased game as broken is not useful; making the same placement by
hand *is* an error, because it is a mistake being made now.

After both, across the 60 shipped maps:

* **35 fully clean**, no diagnostics at all;
* **4 with errors** — MAP47 to MAP50, which are exactly the empty archive slots
  the E0 census identified, and which really are unwalled;
* the rest carry warnings only.

The validator independently rediscovering the four empty slots is the useful
kind of agreement.

## 4. The catalogue decides the plane, not the tool

A wall brush and an enemy brush are the same code. The difference is that the
catalogue entry says plane 0 or plane 1, which is why placing a door and
placing an alien did not need two implementations, and why a test can assert
that painting a wall leaves plane 1 alone.

The eyedropper picks what is *there*, most specific first: an object if the
cell holds one, otherwise the wall under it. The first version picked from
whichever plane the previous selection happened to use, which made the tool
depend on invisible state.

## 5. Facings are words, and the inspector says so

Turning an alien to face north is not a property assignment; 108 and 109 are
different words for the same alien. The inspector shows the raw value
throughout and writes the word the catalogue names for the result.

Where a combination does not exist the control is **disabled**, not
approximated: there is no patrolling Eniram, because the translation has no
entry for one, and offering the control would promise something the format
cannot express.

## 6. One stroke, one undo

A drag opens a gesture, tags every command with it, and closes on release, so
the history coalesces the whole stroke. Ctrl+Z takes back the line you drew,
not its last cell. A fill is one step; a rectangle is one step; two separate
clicks are two.

Painting a value that is already there records nothing at all — an undo step
that does nothing when pressed is worse than no step.

## 7. The playtest launch

An argument vector, never a shell string: nothing in a filename can become a
command, and a path with a space needs no quoting. The plan is built and
validated before anything runs, and the marker is matched against the pattern
the engine actually generates, so `MAP01; rm -rf /` is refused as a marker
rather than escaped as one.

`--file` goes last, because a WAD loaded later overrides by lump name — that is
the entire mechanism by which the edit reaches the game.

The export lands in the workspace, never beside the game data.

## 8. The fill is bounded

`FILL_BUDGET` is 33 000 — enough to fill the largest map the engine allows
(181×181 is 32 761 cells) and no more. An unbounded fill on a map whose outer
wall has a gap — which is exactly the map somebody is editing when they reach
for the fill — walks every cell inside the GUI thread. The budget turns a hang
into a message.

Four-connected, not eight: a diagonal gap is a gap you can see and cannot walk
through, and a fill leaking across one would surprise whoever drew the wall.

## 9. Tests

| Suite | Tests |
| --- | --- |
| `test_tools` | 24 |
| `test_validation` | 19 |
| `test_engine_runner` | 13 |
| `test_editing` (offscreen GUI) | 31 |
| **E5 total** | **87** |

Whole editor suite: **523** — 438 headless, 85 offscreen GUI — plus the
owned-data slice gate.

## 10. What E5 did not do

No copy and paste in the GUI (the transforms exist and are tested; nothing is
bound to them yet), no prefabs, no reachability analysis, no MAPINFO. Full
archive export is still deliberately absent: the retail archive is not an
eligible write target, and the preview WAD is how an edit reaches the game.
