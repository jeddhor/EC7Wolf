# Phase 0 — Deterministic baseline & test harness

This is the first phase of the renderer redesign (OpenGL renderer + motion
interpolation). It changes **no** runtime behavior in normal play; it adds an
opt-in capture/checksum harness plus the documentation and gates that every
later phase is measured against.

## What landed

* `src/r_capture.{h,cpp}` — a deterministic capture & checksum harness, fully
  no-op unless a `--capture-*` switch is present.
* Hooks: `Capture::ParseArgs` + `Capture::OverrideRNGSeed` in `wl_main.cpp`;
  `Capture::PerTic` + `Capture::PostFrame` in the `PlayLoop` in `wl_play.cpp`.
* `tools/test_corridor7_determinism.sh` — the determinism gate.
* This document, including the golden scene matrix and the framebuffer-coupling
  audit that Phases 10–11 must retire.

## Command-line switches

| Switch | Effect |
| --- | --- |
| `--capture-rngseed N` | Pin the RNG seed so the simulation is reproducible. |
| `--capture-checksum PATH` | Write a per-tic + summary checksum log to PATH. |
| `--capture-frame N` | Write a screenshot after rendered frame N (1-based). |
| `--capture-file PATH` | Destination PNG for `--capture-frame` (default `capture.png`). |
| `--capture-maxframes N` | Finalize and quit after N rendered frames. |
| `--capture-maxtics N` | Finalize and quit after N simulation tics (pacing-independent). |

The checksum folds only **deterministic simulation state** — `gamestate.TimeCount`,
`FRandom::StaticSumSeeds()`, and every actor's `x/y/z/angle/pitch/health/flags`.
Render-only state is deliberately excluded, so a correct interpolation or
renderer change must leave the checksum unchanged.

### Determinism gate

```
tools/test_corridor7_determinism.sh BUILD_DIR DATA_DIR [MAP] [SEED] [TICS]
```

Runs the harness twice with a pinned seed and a fixed **tic** budget (frame
count is not deterministic under the current wall-clock pacing, so the run is
bounded by tics), then asserts the two checksum logs are byte-identical. The
checksum log intentionally omits the rendered-frame count for this reason.

**Recorded golden checksum** (regenerate if a deliberate gameplay change lands):

| Map | Seed | Tics | Checksum |
| --- | ---: | ---: | --- |
| MAP01 | 12345 | 400 | `3402c83a` |

This is the gate later phases must keep green. Fixed-step timing (Phase 3) will
additionally make the *frame* count reproducible, at which point golden
screenshots at a given `--capture-frame` become byte-stable too.

### Golden screenshot example

```
cd DATA_DIR
ec7wolf --data CO7 --nowait --tedlevel MAP01 --skill 2 \
        --capture-rngseed 1 --capture-frame 60 \
        --capture-file map01_f60.png --capture-maxframes 120
```

Produces a 640×480 8-bit-colormap PNG and quits.

## Golden scene matrix

Scenes the parity harness must cover (from the redesign doc §9). Basic Wolf3D
cases validate the generic path; the Corridor 7 rows are the ones a naive port
breaks and must be captured with the C7 game filter active (the 3D view is
re-cleared each frame for masked/glass correctness — see the audit below).

Generic:
- Basic corridor (walls only).
- Doors at 0 / 25 / 50 / 75 / 100 %.
- Pushwall on both sides of a cell crossing.
- Floor + ceiling textures.
- Rotating and full-bright sprites.
- Masked walls; multiple masked walls at different depths.
- Widescreen and high-FOV views.

Corridor 7:
- Glass panes (transparent, reveal geometry behind).
- Force fields (palette-cycled, animated).
- Night and infrared visor modes.
- Laser barriers (animated dissolve).
- Palette cycling and electric-shock palette rewrite.
- Damage and pickup palette flashes.
- Fizzle fade.

## Framebuffer-coupling audit

The current renderer writes into a locked 8-bit CPU buffer. These are the direct
couplings the hardware 2D/HUD work (Phases 10–11) must route through the
accelerated `DFrameBuffer`/`FNativeTexture` seams instead of raw buffer writes.

Direct 3D-view lock (`VL_LockSurface`):
- `src/id_vl.cpp` — implementation of the lock/unlock primitive.
- `src/wl_draw.cpp` — `ThreeDRefresh` locks the surface for the whole 3D frame,
  and (Corridor 7) memsets the view to the remapped background colour before
  rendering so masked/glass texels never reveal stale pixels.

Framebuffer `GetBuffer()` (2D / canvas paths):
- `src/id_vh.cpp`, `src/v_video.cpp`, `src/v_draw.cpp`, `src/id_vl.cpp`,
  `src/r_2d/r_main.cpp`, `src/textures/canvastexture.cpp`.

(The `GetBuffer()` calls under `src/resourcefiles/` are lump-data accessors, not
framebuffer access, and are unrelated.)

Fizzle fades and screenshots also read/manipulate the CPU framebuffer directly
and will each need a GPU implementation or an explicitly isolated fallback.

## Exit gate — met

* The software renderer produces byte-repeatable screenshots at a chosen frame.
* The simulation produces a stable per-tic checksum; the determinism gate passes
  (`3402c83a` for the recorded MAP01 run).
* The harness is opt-in and leaves normal play unaffected.
