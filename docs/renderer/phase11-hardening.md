# Phase 11 — Parity, hardening, and optimization

Phase 10 made the GPU own a complete playable frame (world + weapon + HUD +
menus + transitions), presented live to the game window. Phase 11 is about
trusting that renderer: measuring it against the software reference across many
scenes, instrumenting it so misuse and leaks are caught early, and then
optimizing. This is a multi-part phase; this document covers the **parity &
hardening** slice. Optimization (batching, static-mesh caching, culling,
precaching), interactive robustness (alt-tab / fullscreen / resolution / device
recreation), the default-renderer flip, and Android GLES follow.

## GL debug output (`vid_gldebug` / `--gl-debug`)

Opt-in GL diagnostics for the live renderer, off by default and free when off:

* A **`GL_KHR_debug` callback** is installed on the live game-window context the
  first time the live path renders. Driver diagnostics (errors, undefined
  behaviour, performance warnings) are routed into the game console, tagged by
  severity; verbose `NOTIFICATION`-level chatter is filtered out. Synchronous
  mode is enabled so a message points at the offending call.
* Where `KHR_debug` is unavailable, the path degrades to **`glGetError` drains**
  after each live stage (`EnsureLiveResources`, `RenderLiveWorld`,
  `R_GLLivePresent`), which log any accumulated error code.

Enable it via the config setting **`Vid_GLDebug`** or the **`--gl-debug`**
command-line flag (the flag is read before the GL context is created). Both are
inert under the software renderer.

## Resource-leak ledger

The live module keeps a small ledger (`GLLedger`) of the GL objects it itself
allocates — textures, framebuffers, renderbuffers, and shader programs — bumped
at each create site and decremented at each matching free. It covers the
persistent resources (world FBO/texture/depth, palette, colormap, the two shader
programs) and the per-present overlay textures (created and freed inside one
`R_GLLivePresent`). The per-map index/opacity **texture caches** are created by
the shared mesh uploader, so they are excluded from the ledger and audited
separately by their map sizes.

At shutdown (`R_GLLiveShutdown`, run before the GL context is destroyed) the path
frees everything and prints the balance:

```
GL live: 0 leaked GL objects (balanced; 104 cache textures freed).
```

A nonzero balance — or a non-empty cache after teardown — prints a `WARNING`
line instead, so a create-without-free anywhere in the frame loop surfaces
immediately. This makes leaks a checkable invariant rather than something only a
long soak would reveal.

## Golden-scene parity report (`tools/test_gl_parity.sh`)

Generalises the single-scene `test_gl_frame.sh` into an automated
screenshot-difference report over a set of golden Corridor 7 scenes. For each
map it renders — in one process, at the same gameplay frame — the software
screenshot **and** the GL composite (`--capture-glframe`), then measures:

* **HUD band exactness.** The 2D status bar below the 3D view must be a
  pixel-exact (AE = 0) match; both resolve the same 8-bit overlay through the
  palette, so any difference is a compositor/orientation regression. *Hard gate.*
* **Weapon overlay.** Opaque weapon texels composited over the view (> 0).
  *Hard gate.*
* **View-region RMSE.** Normalized RMSE of the 3D view rectangle (GL world vs
  software raycaster), plus a full-frame RMSE, both recorded per scene.
* A per-scene **diff image** (`MAP*.diff.png`) and a Markdown **`parity-report.md`**
  are written for human review.

### The view-RMSE baseline (a real, documented parity gap)

View RMSE currently sits around **0.30–0.42** across the golden scenes. This is
**not** dither noise: Corridor 7's software renderer draws a distinctive
*textured* ordered-dither gradient across floors and ceilings — an effect added
specifically to reproduce Corridor 7's look, absent from stock Wolfenstein 3D —
and the GL floor/ceiling shader does not yet reproduce it. The world region
therefore legitimately differs there (visible as flat floor/ceiling fills under
GL versus the software gradient), consistently in both the offscreen composite
and the live present.

Because that gap is known and would only *lower* RMSE once closed, the parity
gate's ceiling (`GL_PARITY_MAX_VIEW_RMSE`, default **0.55**) is set well above the
baseline: it guards against gross regressions (broken shader, wrong palette,
black world) while tolerating the documented floor/ceiling gap. Porting the C7
floor/ceiling textured shading to GL is the top remaining world-fidelity item;
tighten the ceiling once it lands.

## Hardening test (`tools/test_gl_hardening.sh`)

Runs the live OpenGL renderer over a sweep of maps with `--gl-debug`, repeating
the renderer init → per-map cache build → teardown lifecycle, and asserts on
every run that it went live, the debug path ran, **no** GL errors or
HIGH-severity debug messages were emitted, and shutdown reported a **balanced**
GL object ledger. A per-map leak, or a cache not invalidated on map change, shows
up as a nonzero balance.

## Verification status

* Determinism gate green — `checksum=400c5d59`, unchanged (software path
  untouched; the new cvar defaults off and never affects the simulation).
* `test_gl_world`, `test_gl_frame`, `test_gl_live` — all green.
* `test_gl_parity` — 6/6 golden scenes within tolerance; HUD pixel-exact and
  weapon composited on every scene; view RMSE recorded (0.29–0.42 baseline).
* `test_gl_hardening` — live GL, clean debug, balanced ledger across the map
  sweep.

## Deferred (remaining Phase 11 work)

* **C7 floor/ceiling textured shading in GL** — close the documented view-RMSE
  gap (the largest remaining world-fidelity item).
* **Optimization** — profile CPU scene construction vs GPU; batch by pipeline and
  texture; cache static (non-animated) geometry rather than rebuilding the mesh
  each frame; frustum/portal culling to retire the raycaster-for-visibility pass;
  texture precaching via the existing hit-list.
* **Interactive robustness** — window resize, fullscreen toggle, alt-tab / context
  loss, resolution changes, HiDPI drawable scaling, vsync/perf. (The present path
  already parametrises the drawable size; the event paths are not yet exercised.)
* **Default-renderer flip** — make OpenGL the default on supported desktops with
  software still selectable (the Phase 11 exit gate).
* **Android GLES 3** — validated as a separate platform milestone after desktop.
