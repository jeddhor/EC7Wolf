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

They carry no audio; see [The audio](#the-audio) below for where the sound
actually comes from.

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

* **`SEQONE` then `SEQTHREE` in the attract loop**, suppressed by `--nowait`
  exactly as `PG13()` is. They were placed *before* the loop first, on the
  assumption that an opening is an opening — the DMA trace then showed the DOS
  game beginning the whole sequence again at t=87.5, so they belong inside the
  cycle. Measurement beat the assumption; see [The audio](#the-audio).
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

## The audio

The animations have **no audio of their own**. FLIC has no such chunk, and the
three files contain only `COLOR256`, `BRUN`, `SS2`, `COPY` and a `PSTAMP`
thumbnail; their prefix chunks hold nothing but the authoring paths
(`H:\LAB\JOE\C7-INTRO.FLC`, `H:\LAB\CARLOS\FLICS\END.FLC`). No disc track is
the length of a cinematic either — the audio tracks are 6, 8, 183, 348, 381 and
636 seconds, against cinematics of 6.4, 43 and 78.

The executable plays **digitized sounds from `AUDIOMUS.CO7` at fixed frame
numbers**, out of a compare chain at file offset `0x026FDB`:

```
3D 3C 00     CMP  AX, 60          ; the running frame counter
74 2A        JZ   +0x2A
6A 2E        PUSH 46              ; sound index
9A 08 16 ..  CALL far 1AE4:1608   ; play it
```

Established two independent ways, which is the only reason the numbers below are
here rather than guessed:

1. **Read out of that chain**, following each `JZ` to the `PUSH` it selects.
2. **Measured**, by running the released game under the instrumented DOSBox-X
   build that logs Sound Blaster DMA payloads, and matching every payload
   against `AUDIOMUS` with `tools/python/match_corridor7_dma.py` — the same
   workflow that settled the menu sounds.

The two agree to within 0.17 s across the whole opening. (The DMA timestamps are
CPU cycles; at the trace's `cycles=20000` that is 20,000,000 per second, and the
calibration came out at 19,997,349.)

### SEQONE — the Capstone logo

| Frame | Sound | Which |
| --- | --- | --- |
| 1 | 46 | `c7/apparition` |
| 36 | 27 | `c7/monster/morph/class8` |
| 55 | 10 | `doors/open` |
| 60 | 1 | `c7/teleport` |

Every one of those is an **ordinary in-game effect**. The logo is scored out of
the apparition shriek, a monster morph, a door and a teleport — which is why a
player recognises the first one as "the sound the floating skull makes". That
observation is what started this investigation, and it turned out to be exactly
right.

### SEQTHREE — the opening cinematic

| Frame | Sound | Which |
| --- | --- | --- |
| 1 | 87 | `c7/cinematic/line1` |
| 120 | 88 | `c7/cinematic/line2` |
| 340 | 89 | `c7/cinematic/line3` |
| 500 | 90 | `c7/cinematic/line4` |

Sounds 87–90 are the astronauts' dialogue: 7.5 s, 12.5 s, 8.2 s and 10.2 s,
against everything else in the bank being under 3.2 s. They are also the **only
digitized sounds in the game that nothing else ever plays** — they exist for this
cinematic and nothing but this cinematic, which is why nothing referenced them
until now. They are digitized-only in `SNDINFO`: there is no AdLib or
PC-speaker rendition of speech to fall back to.

### SEQFOUR — not yet

The ending's script is dispatched by a binary search over the frame counter plus
a `JMP CS:[BX+...]` jump table, rather than the flat compare chain the other two
use, and it has not been read out reliably. The sounds it reaches are visible in
the same code region — 50, 78 (ten times), 62, 12, 34, 25 and 93 among them —
but the frames they belong to are not, and the ending cannot be reached under
DOSBox without playing the game to the end. It plays silent until that is
settled. Better silent than wrong.

## They are part of the attract loop

The DMA trace shows the whole sequence beginning again 87.5 seconds in — logo at
t=0, the cinematic's last line at t=48.2, then the title and credit pages, then
the logo again. So the cinematics belong **inside** the attract cycle, not before
it, which is where they are now.

Two more traps, both found by playing it rather than by reading it:

**Restore the palette on a black screen, never on a picture.** The animation's
last image is still in the framebuffer when playback ends, and those 256 indices
mean something only under the animation's own palette. Handing the game's
palette back first showed that image in the wrong colours for one present --
a psychedelic flash at the end of every cinematic. Playback now fades to black
while the palette still matches its pixels, and swaps on black.

**A cue can outlive its animation.** The last line of dialogue is 10.2 s and
starts 7.5 s before the final frame, so in the released game it finishes over
whatever comes next; cutting it at the last frame would be a deviation, not a
fix. But a *skip* means "move on", so that stops the sound with the picture.
Separately, the attract loop's route into the control panel never silenced
digitized audio -- the in-game route always has -- because until now nothing in
the attract loop made a sound. A line of dialogue followed the player into the
menu.

One trap worth recording: `PG13()` and the attract loop's faders leave the screen
blended to black, and anything presented while that is true is invisible. Moving
the cinematics into the loop put them behind that blend — they ran correctly,
onto a black screen. `C7Flic_Play` now clears the fade before playing and
restores it afterwards, because the next thing the loop does is fade the title
page in.
