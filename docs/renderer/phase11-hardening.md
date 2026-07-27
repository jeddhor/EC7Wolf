# Phase 11 — Parity, hardening, and optimization

Phase 10 made the GPU own a complete playable frame (world + weapon + HUD +
menus + transitions), presented live to the game window. Phase 11 is about
trusting that renderer: measuring it against the software reference across many
scenes, instrumenting it so misuse and leaks are caught early, and then
optimizing. This is a multi-part phase; this document covers the **parity &
hardening** slice, and records the **cutover** at the end.

**Phase 11 is closed.** OpenGL is the default renderer; the software renderer
remains complete and selectable. See [Cutover](#cutover-opengl-becomes-the-default)
below for what was accepted and what deliberately was not.

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

### The view-RMSE baseline

View RMSE sits at **0.044–0.077** across the golden scenes.

It did not start there. The original baseline was 0.30–0.42, and that was
attributed to Corridor 7's textured ordered-dither floor/ceiling gradient not
being ported to the GL shader. That reading was wrong: the real cause was a
plane-shade bug (the raw colormap row was used where the visible palette step
was needed), and fixing it with a C7 plane LUT dropped RMSE by roughly a factor
of five. What remains at 0.04–0.08 is edge and sampling difference between a
rasteriser and a scan-line raycaster.

The parity gate's ceiling (`GL_PARITY_MAX_VIEW_RMSE`, default **0.55**) is
therefore now very loose relative to the measurement. It is left where it is on
purpose: it exists to catch gross regressions (broken shader, wrong palette,
black world), and a ceiling tightened to just above the current numbers would
fail on ordinary sampling drift rather than on anything a player could see.

## Hardening test (`tools/test_gl_hardening.sh`)

Runs the live OpenGL renderer over a sweep of maps with `--gl-debug`, repeating
the renderer init → per-map cache build → teardown lifecycle, and asserts on
every run that it went live, the debug path ran, **no** GL errors or
HIGH-severity debug messages were emitted, and shutdown reported a **balanced**
GL object ledger. A per-map leak, or a cache not invalidated on map change, shows
up as a nonzero balance.

## Cutover: OpenGL becomes the default

`vid_renderer` now defaults to `"opengl"`. The exit gate for Phase 11 was *"GL
becomes default on supported desktop; software stays selectable and fully
functional"*, and both halves are enforced rather than assumed.

### Choosing the renderer before the window exists

The decision cannot be deferred. SDLFB reads `vid_renderer` to decide whether to
create a GL-capable window, and a GL-presenting window deliberately carries **no
`SDL_Renderer`** — the software present path has nothing to draw into. Failing
over *after* the window is up would leave the software fallback presenting into
a window that cannot accept it.

So `CheckRendererAvailable()` runs in `InitGame()` immediately before the first
`VL_SetVGAPlaneMode()`, and where OpenGL is requested it calls
`R_GLProbeAvailable()`: a hidden 32×32 GL 3.3 core window, created and destroyed,
cached for the run. If that fails, `vid_renderer` is demoted to `"software"` for
this run only. A build compiled without `ECWOLF_RENDERER_OPENGL` takes the same
path.

"For this run only" needs machinery, because `WriteConfig` used to save whatever
`vid_renderer` held: one launch on a broken driver would have written `software`
into the config and thrown away a choice the player never changed. So the
requested value is kept separately in **`vid_renderer_requested`**, which is what
the config is written from. The demotion moves `vid_renderer` alone; the menu
moves both. A machine that later gains a working driver gets GL back with no
intervention, and a test run pinned with `--vid-renderer` no longer rewrites the
player's setting on exit either.

A probe rather than a capability string because a driver can advertise OpenGL
and still refuse a core profile; the only trustworthy question is whether a
context can actually be created.

`R_InitRendererBackend()`'s existing software fallback is still there behind it,
so there are two independent ways to end up on software and no way to end up
with neither.

### On upstream's PHILOSOPHY.md

Upstream ECWolf states that it *"will always default to 8-bit paletted software
ray casting"*. This fork departs from the "software" half of that deliberately —
it is the stated exit gate of the renderer redesign — and keeps the rest: the GL
path is an **indexed** pipeline that uploads 8-bit index textures and resolves
the palette and colormap in the shader, not a truecolor renderer. Corridor 7's
palette effects (night vision, infrared, electric, damage flashes) are still
256-entry palette rewrites, now uploaded as a palette texture. Anyone who wants
the raycaster still has it, unchanged, one menu item away.

### The trap the cutover exposed: gates that assumed the old default

Flipping the default silently broke `test_gl_parity`, and it kept reporting
**PASS** while doing so.

The parity run never pinned a renderer, because it never had to: the default was
software, so `--capture-file` captured a genuine software frame to compare the
offscreen GL composite against. Once the default became OpenGL, the GPU owned
the world and the framebuffer `--capture-file` reads held only the 2D overlay —
the reference came out **94.9% black** in the view region. View RMSE went from
0.044–0.077 to 0.345–0.459, which is *still under* the 0.55 ceiling, so the gate
went on passing while comparing the renderer against a blank image.

Two things made this findable rather than shipped: the numbers were recorded
before the flip, so the jump stood out; and `glframe.ppm` was **byte-identical**
across the two runs, which localised the change to the reference half rather
than to the renderer. Had the ceiling been tightened to just above the baseline
— as the old version of this document suggested doing — it would instead have
failed loudly, which is an argument for tight gates.

`test_gl_parity`, `test_gl_frame` and `test_gl_world` now pass
`--vid-renderer software` explicitly, so their reference halves mean what they
say regardless of what the default is. The Corridor 7 2D gates (automap,
floorplan, keys) were already pinned, and are unaffected in any case because the
2D overlay *is* still drawn into that framebuffer under GL.

The general lesson, worth applying to any future default change: a test that
depends on a default is a test that stops testing when the default moves, and it
does not necessarily tell you.

### Accepted at cutover

* `test_gl_selftest` — indexed-palette pipeline verified on the GPU.
* `test_gl_frame`, `test_gl_world`, `test_gl_live` — composite frame, static
  world/masked/sprite geometry, and live presentation to the game window; HUD
  band pixel-exact against software in both the offscreen and live paths.
* `test_gl_parity` — 6/6 golden scenes, HUD AE = 0 and weapon composited on
  every one, view RMSE 0.044–0.077.
* `test_gl_modeswitch` — shrink, grow, repeat, and visor mode changes; context
  teardown and rebuild with a balanced object ledger each time.
* `test_gl_hardening` — MAP01/20/40 live with `--gl-debug`: no GL errors, no
  HIGH-severity messages, balanced ledger.
* `test_glxbrz_parity` — the GL xBRZ shader against the CPU scaler.
* The Corridor 7 gates (determinism `ae626557`, smoke, AI, automap, keys per
  floor, CD audio) re-run on the **new default**, and the determinism gate re-run
  under both renderers to confirm the simulation does not depend on which one is
  drawing.

### Deliberately not done

* **Optimization.** The scene is rebuilt per frame; there is no batching, static
  mesh caching, culling, or precaching. Phase 11 lists these as profile-driven
  and *"only now consider"*, and nothing in the acceptance runs pointed at a
  frame-rate problem worth trading complexity for. Retiring the raycaster's
  visibility pass belongs with this work, not before it.
* **Alt-tab / context loss.** Video mode changes tear down and rebuild the
  context and are covered by `test_gl_modeswitch`; a compositor yanking the
  context out from under a running game is the same code path but is not
  exercised by a test.
* **HiDPI drawable scaling** beyond what the present path already parametrises.
* **Android GLES 3** — a separate platform milestone, as planned.

## Verification status

* Determinism gate green — `checksum=ae626557`, unchanged by the cutover and
  identical under software and OpenGL. (The checksum moved from `400c5d59` for an
  unrelated and legitimate reason: the aliens' patrol routes were restored.)
* `test_gl_world`, `test_gl_frame`, `test_gl_live`, `test_gl_modeswitch` — green.
* `test_gl_parity` — 6/6 golden scenes; HUD pixel-exact and weapon composited on
  every scene; view RMSE 0.044–0.077.
* `test_gl_hardening` — live GL, clean debug, balanced ledger across the map
  sweep.
* **Android GLES 3** — validated as a separate platform milestone after desktop.
