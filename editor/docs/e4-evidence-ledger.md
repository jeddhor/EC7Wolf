# EC7Edit — E4 evidence ledger

Milestone E4: the Qt application shell, first-run discovery, and the packaging
decision. The editor now starts, finds your game, and shows you your maps.

---

## 1. The packaging decision, measured

The plan asks for onedir and onefile to be compared rather than assumed. The
installer in this repository is onefile, and copying that choice would have
been the obvious thing to do.

Measured on this machine, five launches each, with a probe importing the same
Qt modules EC7Edit does (`scripts/measure_packaging.py`):

| | onedir | onefile |
| --- | --- | --- |
| On disk | 194.4 MB | 72.8 MB |
| **Download** (tar.gz) | **72.8 MB** | **72.1 MB** |
| Median start | **0.22 s** | 1.19 s |
| Five launches | 1.11 s | 5.95 s |
| Files | 310 | 1 |

**Decision: onedir.** The usual argument for onefile is download size, and once
both are compressed that argument is worth 0.7 MB. What onefile actually costs
is unpacking itself into a temporary directory on *every* launch — a second,
every time. That is right for the installer, which somebody runs once. An
editor is opened, closed and opened again all day.

Two corrections while measuring, both worth recording because both would have
produced a confident wrong number:

* the first run reported onedir at 285.6 MB because `stat()` follows symlinks
  and Qt ships its libraries as links, so every one was counted twice. `lstat`
  gives 194.4 MB;
* the first comparison put 285 MB against 72 MB and looked decisive. It was
  comparing an uncompressed tree with a compressed file. Compressed, they are
  the same size, and the entire size argument evaporates.

## 2. The engine is not run until you ask

Identifying an executable properly means running it, and running a binary
somebody selected in a file dialog is a real action. So the setup page shows
"not checked" until the user presses a button, and a test proves it: a fake
engine that touches a marker file, asserted absent before the click and present
after.

The probe uses `--help`, not `--version` — the engine has no `--version` flag,
and passing one falls through to a normal start, which on a headless machine is
a probe that never returns. That was found by writing the check and watching it
time out.

An upstream ECWolf binary is refused by name: it identifies itself as `ECWolf`
rather than `EC7Wolf`, and Corridor 7 support is only in the fork.

## 3. A checklist, not a verdict

"Could not find your game" is the least useful thing a program can say to
someone holding a CD. Setup reports eleven separate lines — the executable, its
identity, the data directory, each required file, the palette's presence at the
right offset, whether the map archive parses, whether the artwork parses, the
workspace, and whether the workspace is separate from the data — each with what
was found and what to do about it.

Optional content is a **note**, never a blocker. An editor that refuses to open
because the music is missing has its priorities wrong.

Discovery never scans. Candidates come from the package's own layout and from
paths the user picked. An editor that trawls a home directory looking for a
game is an editor that finds somebody's backup and edits that.

## 4. Two defects the offscreen tests found

**The exception hook could stack modals.** A second unhandled exception while
the first dialog was up would open another, and one raised inside the reporting
itself would recurse. It now shows one at a time, and the console and the
Problems panel always get the report regardless.

**A dock reported invisible.** `isVisible()` is false for any child of a window
that was never shown, so the layout-reset test was asserting something it could
not observe. The property that means what the test meant is `isHidden()`.

## 5. Staleness is dropped, not displayed

Every background result carries the document revision it was requested at, and
one that arrives after the document has moved on is discarded. Without it,
scrolling a palette fast enough shows thumbnails from three selections ago
landing on top of the current ones, and there is no way for the user to tell.
There is a signal for the discard specifically so a test can prove it happens
rather than assume it.

A worker that raises does not take the pool down, and resubmitting a key
cancels the job it replaces.

## 6. The licensing boundary, in the GUI

Decoded artwork lives in a bounded in-memory cache for the session and is never
written to disk. That is the difference between reading somebody's game and
making a copy of it, so the gate greps the thumbnail path for any write at all,
checks no game-data file is committed under `editor/`, and checks the GUI
embeds no binary blob.

The palette works with no game data: every entry gets a labelled placeholder
tile. That is not only for CI — it is the state a first-time user is in before
setup, and a palette of empty squares would look broken.

## 7. Tests

54 offscreen GUI tests in 0.37 s, under CPython 3.12.13 with PySide6 6.11.2.
Real `QApplication`, real widgets, real painting, real signal delivery; nothing
is mocked, because a GUI test that stubs the toolkit tests the stub.

| Area | What is covered |
| --- | --- |
| Window | menus, docks with restorable object names, accessible names on every widget |
| Projects | new, open, save, reopen, import from an archive, recent list, dirty marker |
| Editing | commands through the history, undo and redo from the menu, canvas following the document |
| Canvas | hit testing at four zooms, clamping, painting with and without a map |
| Palette | every tab populated, search by name and by raw value, placeholders without data |
| Workers | delivery, staleness, failure isolation, cancellation |
| Layout | round trip through settings, reset at three window sizes |
| First run | the eleven checks, and the engine not running unasked |

## 8. What E4 did not do

No editing tools — the canvas draws and hit-tests, and E5 makes it paint. No
Windows or arm64 measurement: the packaging numbers are from Linux x64, and the
other two acceptance targets in the E0 matrix are unmeasured. Recorded as
**grade C** rather than claimed.
