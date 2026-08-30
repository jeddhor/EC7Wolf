# EC7Edit — E3 evidence ledger

Milestone E3: the document model, commands and undo, the project schema,
atomic save and recovery. Still headless; nothing here needs a display.

---

## 1. Ten thousand operations against a reference model

`test_commands.ModelBased` runs 10 000 mixed operations — paint, rename, undo,
redo, gesture boundaries — against a plain nested-list model kept alongside the
real document, comparing every 250 steps and at the end. The model keeps its
own undo and redo stacks, so a disagreement about what an edit *meant* shows up
as a mismatch rather than as a bug report months later. Seed `20260829`, so a
failure is reproducible rather than a story about one CI run.

A second test does 500 edits and then undoes all of them, asserting the planes
are identical to where they started. Grade **A**.

The design decision that makes this pass is that a command stores both the old
and the new word for every cell it writes. Recomputing the old value on undo
would be a second implementation of the edit, and the two would eventually
disagree — most visibly on a flood fill over a shape somebody had already
changed. Because both halves are stored, undo is applying the inverse, and the
inverse is the same structure with the two swapped. One apply path, one thing
to get right.

## 2. Eleven injected save failures

`save_project` has eleven named stages and `FaultInjector` fails at any one.
The test fails at each in turn and asserts that what is on disk afterwards
parses, and is either the old project or the new one — never a truncated file,
never a mixture, and never with a temporary file left behind.

| Stage | What it defends |
| --- | --- |
| serialize, validate | a document that cannot be written is not written |
| tempfile, write, flush | the bytes reach the disk before anything is renamed |
| reopen, verify | the file on disk parses back to the same document — this is what catches a serialiser that lost a plane, which a length check would not |
| identity | someone else changed the destination since it was opened |
| generation | a newer save already committed; this one is abandoned |
| replace, dirsync | the rename is atomic, and itself durable |

Grade **A**. The claim is scoped: this is tested on local filesystems. SMB,
NFS, removable media and cloud-synchronised folders may not honour sibling
replace, directory fsync or stable identities, and the design says so rather
than pretending otherwise.

## 3. Two defects the tests found in my own code

**The lock treated its own process as stale.** `ProjectLock._stale()` returned
true when the lock file's pid was our own, meaning a second lock on the same
project inside one process would be granted — which is exactly the case the
lock exists to refuse. The rule is now simply "is that process alive", and a
lock left by a crashed run is still reclaimed.

**The writer queue could not be used.** `save_project` took its generation
itself, so it was always the newest and the supersession check could never
fire. A background autosave has to take its generation *before* it starts
serialising, or finishing late is indistinguishable from being current, so the
generation is now a parameter. The test that exposed this was written asserting
behaviour the API could not deliver.

## 4. A rule that was too strong

`OutputGuard.for_source` protected the source file *and its whole directory*.
That is right for a retail data folder — an export landing beside
`MAPTEMP.CO7` is one typo from being `MAPTEMP.CO7` — and wrong everywhere
else: it refused to write a project file into the user's own working directory
because a scratch archive happened to be there too.

The directory is now protected when it *looks like game data*: it holds a
`.CO7` file or `CORR7CD.EXE`. That is a real signal, it is checkable, and
neither appears by accident in a directory of somebody's own work. Callers
wanting a directory protected for another reason pass `--protect`.

## 5. Facings are catalogue-driven, never arithmetic

Rotating a selection has to rewrite the raw word of anything that faces a
direction. The tempting way — add one, since the four facings are consecutive
— is wrong in a way that looks right on the first thing you try: the bands are
not all four long, they do not all start on the same rotation, patrol markers
have eight, and nothing in the numbering says which value means which way.
Adjacency is a coincidence of the table.

So rotation reads the value's direction *by name* from the catalogue, turns the
name, and looks the new name back up. A word the catalogue does not describe as
directional is carried through untouched — right for a wall, and right for an
imported word nobody has identified. Tested on all four facings, on the
eight-way patrol markers, on a plane-0 word that shares a number with a
directional plane-1 word, and on an unknown word.

## 6. The schema

JSON, because a project is something a person may want to read and a reviewer
may want to diff. Plane words are integers, not base64: forty thousand small
numbers costs a few hundred kilobytes and buys the ability to see what changed.

Refused on load, each with a test: unknown properties at any level, a row of
the wrong width, a plane of the wrong height, two planes instead of three, a
word outside 0–65535, a word that is a string, **a word that is `true`** —
which a naive range check passes, since `True == 1` — a name field of the wrong
length, a name that is not hexadecimal, a text and raw name pair that disagree,
two maps sharing an id, a byte-order mark, a newer schema, and an older schema
with no migration.

The text/raw name pair matters most. The text is a *view* over the sixteen raw
bytes. A file where they disagree was written by something with a different
idea of the decode, and picking one loses the other, so load refuses.

A shared project is untrusted input. A path inside one is inert text: opening
the project does not stat, hash, open or contact it, and a test passes UNC
paths, `/dev/zero` and `~/.ssh/id_rsa` through a round trip to prove nothing
acts on them.

## 7. Migration

The harness exists at schema 1 with no migrations registered, which is
deliberate: the first real schema change should be a data change, not also an
infrastructure change. Tested that the current schema passes through
unchanged, that a registered step runs and bumps the version, and that a gap
in the chain is a readable error rather than a crash.

## 8. Autosave and recovery

Autosave writes into the application's own recovery directory and nowhere else
— never beside the retail data, never beside the project unless the user chose
a workspace. It records both the saved and the autosaved revision, so the
recovery chooser can say what would be gained, and it **does not clear the
dirty flag**: telling someone their work is saved because a timer wrote a copy
into a directory they have never seen would be a lie.

Retention is bounded by count and bytes, deletions target exact paths this
store owns, and a damaged recovery file is skipped rather than failing startup.

## 9. Test results

| Suite | Tests |
| --- | --- |
| `test_document` | 21 |
| `test_commands` | 26 (including the 10 000-operation model) |
| `test_transforms` | 31 |
| `test_project` | 48 (including eleven injected save failures) |
| **E3 total** | **126** |

Whole editor suite: 382 tests, all under CPython 3.12.13.

## 10. What E3 did not do

No Qt, no canvas, no semantic validation beyond the schema's own. Native
archive overwrite is deliberately not implemented — the retail archive is not
an eligible target in the normal workflow, and E1's preview WAD is how an edit
reaches the game.
