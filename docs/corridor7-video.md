# The CD cinematics

The CD release of Corridor 7 ships three animations that the floppy release does
not, and the port has never played any of them. This is the plan for that, and
the record of what the disc actually contains.

## What is on the disc

The data track's `/CORR7CD` directory holds three files the installer leaves
behind, because they are meant to be streamed from the CD:

| File | Size | Frames | Length | What it is |
| --- | --- | --- | --- | --- |
| `SEQONE.CO7` | 81,392 | 90 | 6.4 s | The Capstone "Pinnacle of Entertainment Software" logo |
| `SEQTHREE.CO7` | 5,108,672 | 605 | 43.0 s | Opening cinematic: the probe leaving Mars, arriving at Delta Base |
| `SEQFOUR.CO7` | 21,702,102 | 1,100 | 78.1 s | Ending cinematic: the alien object, the countdown, the Medal of Honor over Washington |

There is no `SEQTWO`. The executable carries the three names as a contiguous
table at file offset 247,109, which is what a "play sequence *n*" call indexes,
and the compendium's asset table independently reads them as *"Capstone logo,
opening cinematic, ending cinematic"*.

**They are Autodesk FLIC animations** — `FLC`, magic `0xAF12`, 320×200, 8 bits,
71 ms per frame (14.08 fps), each carrying its own 256-entry palette. The header
size field matches the file length exactly in all three cases, which is the
cheapest possible integrity check and is what the extractor uses.

That format is a gift. It is 8-bit indexed at exactly the resolution every other
full-screen page in this game already uses, so the frames can be played through
the same path as the title and credit screens rather than needing a video
pipeline. It is also simple enough to decode correctly: a handful of chunk
types, all of them run-length or delta encodings over an indexed framebuffer.

## Why this closes a known deviation

`docs/corridor7.md` has said, since the port was first documented, that *"the
final victory page remains an evidence-based ECWolf reconstruction because the
installation does not contain the external cinematic files referenced by the
executable."* `SEQFOUR.CO7` is that file. It was never in the installation
because it never leaves the CD.

## The plan

### 1. Extraction (`tools/extract_c7_video.py`)

Modelled on `tools/make_cdaudio.py`, which does the same job for the redbook
audio: point it at the disc, get playable files beside the game data.

* Accept a `.cue` (finding its `.bin`), a plain `.iso`, or an already-mounted
  directory. The CD is `MODE1/2352`, so the raw track needs its 16-byte sync and
  header and 288 bytes of ECC stripped per sector to become a 2048-byte
  filesystem — the extractor does that itself rather than requiring `bchunk`.
* Walk ISO9660 directly, in Python, with no third-party modules. `isoinfo` can
  list this disc but would not extract from it here, and depending on a tool
  that is not installed everywhere is worse than 60 lines of directory parsing.
* Validate each file as FLC before writing: magic, 320×200, 8-bit, and the
  header's size field against the real length. A truncated cinematic that plays
  half way and stops is worse than one that is absent.
* Write to a `video/` subdirectory beside the game data, under the original
  names, exactly parallel to `cdaudio/`.

### 2. Playback (`src/c7_flic.{h,cpp}`)

A FLIC decoder and a player, self-contained.

* Chunk types that matter for these three files: `FLI_COLOR256` (4),
  `FLI_SS2` (7), `FLI_COLOR64` (11), `FLI_LC` (12), `FLI_BLACK` (13),
  `FLI_BRUN` (15), `FLI_COPY` (16). `FLI_PSTAMP` (18) is a thumbnail and is
  skipped. Anything else is skipped by size rather than treated as fatal.
* Decode into a persistent 320×200 index buffer plus a 256-entry palette. FLIC
  is a delta format: every frame after the first is a patch on the one before,
  so the buffer has to persist and the decoder cannot be restarted mid-stream.
* Present each frame by handing the buffer to the existing full-screen page
  path. The frames are indices, the game's canvas is indexed, and both renderers
  already composite a full-screen 2D page correctly — so this needs no renderer
  work at all, and works under software and OpenGL alike.
* Set the screen palette to the animation's own while it plays and restore the
  game's afterwards. FLIC carries palette changes as chunks, so this updates
  mid-playback.
* Pace on the header's frame duration against the real clock, so a slow machine
  drops behind rather than playing in slow motion.
* Any keypress skips the current animation; the player should never be trapped
  in 78 seconds of video.

### 3. Where they play

* **`SEQONE` then `SEQTHREE` at startup**, before the advisory page and the
  attract loop, and suppressed by `--nowait` exactly as `PG13()` is. Once per
  run, not once per attract cycle: they are the opening, not part of the loop.
* **`SEQFOUR` on final victory**, on the `EndTitle` path in `GameLoop()`, before
  the victory page and the high-score entry.

Direct calls rather than a new mapinfo intermission action. The intermission
system would be the general answer, but the startup pair has to run *outside*
the attract loop it would live in, and inventing a general mechanism with one
caller and a special case is more machinery than reproducing two fixed cues.

### 4. When the files are absent

Everything behaves exactly as it does today. This is optional content that most
installations will not have, the startup log says whether it was found — like
the CD soundtrack — and no code path requires it.

### 5. Tests

* A **synthetic FLIC** built by the test itself exercises the decoder without
  the commercial disc: known chunk types, known pixels, checked frame by frame.
  That makes decoder coverage data-free, so it runs in CI.
* A **runtime gate** that the game still starts, and reaches the title, both
  with and without a `video/` directory present.
* Playback is entirely outside the tic loop, so the determinism checksum must
  not move.
