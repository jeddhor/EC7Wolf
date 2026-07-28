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

* **Alt-tab / context loss.** Video mode changes tear down and rebuild the
  context and are covered by `test_gl_modeswitch`; a compositor yanking the
  context out from under a running game is the same code path but is not
  exercised by a test.
* **HiDPI drawable scaling** beyond what the present path already parametrises.
* **Android GLES 3** — a separate platform milestone, as planned.

## Optimization

Done after the cutover, and profile-driven as the plan requires — which turned
out to matter, because the plan's own headline item was worth almost nothing and
two costs it did not emphasise dominated the frame.

### Measuring first (`vid_glprofile` / `--gl-profile`)

Splits a live frame into the stages that could plausibly dominate and prints a
breakdown every 100 frames. The GPU bucket is *submission* time — the driver may
return before the work is done — so it reads as "what the draw calls cost this
thread", not GPU milliseconds. Numbers below are 640×400 on a Radeon RX 580.
(The headless test environment is llvmpipe and is useless for this: it puts
rasterisation on the CPU.)

| stage | before | after |
| --- | --- | --- |
| visibility (software raycast) | 4.06 ms | 0.21 |
| draw submission | 3.85 | **0.00** |
| weapon | 2.90 | 2.50 |
| static build | 0.41 | 0.43 |
| upload | 0.08 | 0.12 |
| present | 1.11 | 0.79 |
| **MAP01 total** | **12.48 ms** | **4.13 ms** |

MAP20 14.91 → 3.81 ms; MAP40 14.90 → 1.39 ms.

### What actually cost the frame

**Draw submission (31–50%).** The world arrived as one surface per wall face,
floor tile and ceiling tile — 3878 of them on MAP01 — and each got its own
`glDrawArrays` with its own uniform updates. Surfaces are now sorted by draw
state and merged into runs, which collapses that to a few dozen draws and takes
submission to zero. Safe only because this pass has **no blending**: every
transparent texel is a shader `discard` and depth testing decides the rest, so
the image does not depend on draw order. A blended surface type would break that
assumption, and `MeshDraw` is where it would have to be handled.

**The retained raycaster (28–33%).** The software wall pass is still run under
GL for its side effects — it stamps cell visibility for the automap and the
sprite cull, collects masked-wall hits, and sets `viewz`. Its *pixels*, though,
were being texture-mapped column by column and then thrown away: the GL path
clears the whole view region on the very next statement.
`WallRefreshVisibilityOnly()` skips `ScalePost` and nothing else, so the
traversal — and therefore the visibility set — is bit-for-bit identical. This is
**not** the "retire the raycaster" item; the traversal still runs, and portal
traversal is still what would be needed to remove it.

**The weapon, drawn twice (23%).** The second draw builds the coverage mask the
compositor needs. Coverage is a silhouette, so it depends only on which sprite is
drawn and where — and every input to that is a function of the simulation tic
(`BobWeapon` derives its offsets from `gamestate.TimeCount`, as does the
Corridor 7 walk-cycle pose). Frames run several times per tic, so the mask is now
rebuilt only when its key changes. The remaining ~2.5 ms is the one mandatory CPU
draw of the weapon into the 8-bit frame; removing that means moving the view
model onto the GPU, which is a Phase 10-shaped change, not an optimization.

**Static geometry (3% + 1%).** The plan's headline optimization, and the profile
says it was never the problem. It is cached anyway, but by **comparing content**
rather than by guessing when to invalidate: the mesh is still built each frame
and `memcmp`'d against the last upload. A pushwall settling into its final cell
silently rewrites the static world, and a missed invalidation would leave a wall
standing where the player just walked; a content compare can only ever fail
towards rebuilding. That removed the upload (0.38 → 0.12 ms) and left the build.

### Measured, and deliberately not done

* **Frustum culling.** Draw submission is now 0.00 ms and the GPU is not the
  bottleneck at these resolutions, so culling has nothing left to win — and it
  would actively cost: the visible set changes every frame, so a culled static
  mesh would differ every frame and defeat the content-compared cache above.
* **Texture precaching.** `BuildStatic` spans the whole map, not just what is
  visible, so every wall texture is already uploaded during the first frame on a
  level. Upload sits at 0.09–0.12 ms. There is no hitch left for a precache pass
  to remove.

Both are in the plan's optimization list. Neither survives contact with the
measurements, and doing them anyway would trade real complexity for nothing.

## Hardware renderer options

Two settings the software raycaster cannot offer, both under **Advanced
Graphics → Hardware Renderer**, both **off by default** so every parity gate goes
on measuring the untouched renderer.

### Texture Filter — Sharp / Bilinear / Smooth (`Vid_GLFilter`)

The constraint that shapes all of this: **a palette index is a name, not a
colour.** The world texture is `R8UI`, which the hardware can only sample
nearest, and averaging indices would be meaningless anyway — index 5 and index
200 average to 102, an unrelated entry. So filtering cannot happen at the
sampler. Each tap is resolved the whole way — colour cycle, full-bright rules,
colormap row, palette — and only the resulting RGB is mixed.

The same taps produce **coverage**: a transparent tap contributes no colour and
lowers the weight instead, and that fraction is written to alpha.

* **Sharp** — one tap. Bit-identical to the renderer without the feature.
* **Bilinear** — four taps, weighted by the fractional sample position.
* **Smooth** — four bilinear samples on a rotated grid across the pixel's
  footprint in texture space, taken from `dFdx`/`dFdy`.

**There is no trilinear or anisotropic option, and that is not an omission.**
Both need a mip chain. A mip chain of palette indices is meaningless for the
reason above, and a mip chain of *resolved colour* would have to be rebuilt every
time Corridor 7 rewrites the palette — which it does for night vision, infrared,
electric, damage and pickup flashes. **Smooth** is what those settings are for:
it samples the actual pixel footprint, narrows with distance the same way, and
needs no precomputation that a palette change could invalidate.

### Antialiasing — Off / 2x / 4x / 8x (`Vid_GLMSAA`)

The world renders into a multisampled framebuffer and is resolved into the
texture the compositor samples, so nothing downstream knows MSAA is on. The
sample count is clamped to `GL_MAX_SAMPLES`, and an incomplete framebuffer falls
back to no antialiasing rather than rendering nothing.

MSAA alone cannot smooth a **sprite or masked-wall silhouette**, because those
edges come from a shader `discard` and a discarded fragment kills every sample.
With filtering also on, the coverage fraction described above is fed to
`GL_SAMPLE_ALPHA_TO_COVERAGE`, which turns it into a sample mask — so cutout
edges get antialiased too. Coverage rather than blending on purpose: **blending
would make the pass order-dependent and break the state-sorted draw batching**
that the optimization work depends on.

### Cost and caveats

Smooth + 4× MSAA measured 4.01 ms/frame on MAP01 against 4.13 ms with both off —
inside the noise, because the frame is CPU-bound on the weapon draw and the GPU
has the headroom. On weaker hardware the extra taps are real work; that is what
the three levels are for.

MSAA applies to the **live** renderer only. The offscreen `--capture-glframe`
path used by the parity gate does not multisample, which is why turning it on
cannot move those numbers.

`tools/test_gl_filtering.sh` asserts the parts that could silently rot: that
Sharp is untouched, that bilinear introduces colours outside the on-screen
palette set (proving taps are resolved *before* mixing rather than after), that a
256-entry palette rewrite still reaches the screen with filtering on, and that
MSAA changes edges and only edges.

## Upscaled assets (`Vid_UpscaledAssets`)

Both renderers, so it sits under **Advanced Graphics → Image Scaling** rather
than under Hardware Renderer. `tools/make_c7_upscaled_pk3.py` builds
`c7_assets_upscaled.pk3` from the player's own data files; the engine finds it
beside them (or beside the executable), validates it, and installs it over the
stock art. See `docs/corridor7.md` for the player-facing side.

Three things about the implementation are worth knowing before touching it.

**Both copies stay in memory, and the switch is a pointer swap.** The pack
arrives through ZDoom's `hires/` namespace, whose normal behaviour is
`ReplaceTexture(id, newtex, /*free=*/true)` — the original is deleted. For this
pack the free is suppressed and the pair recorded, so `C7Upscale::SetEnabled()`
can swap `Textures[i].Texture` back and forth. Nothing else has to know: every
consumer in the engine reaches art through an `FTextureID`, so the id keeps
resolving and only what it resolves to changes.

The exceptions are the places that cached the resolved `FTexture *` instead, and
they are what makes the switch look broken rather than fail loudly:

* the GL world caches uploads per texture id for the run —
  `R_GLLiveInvalidateTextures()` forgets the map so the next frame re-uploads;
* `Menu::cursor` was looked up once and kept — `Menu::forgetCachedArt()`;
* `DrawPlayBorderSides` held a `static FTexture *const[8]` — now looked up per
  draw, which is eight lookups on the frames that draw a border.

**A hires wall has to carry its own transparency.** Corridor 7 keys wall
transparency on palette index 255, and `FFlatTexture` builds an opacity plane
from it; both renderers ask for transparency *explicitly* rather than inferring
it from an index, which is exactly what makes the replacement possible. But
`FPNGTexture` had no `GetColumnOpacity` at all, so 50 of the 256 wall pages —
grates, force-field frames — would have come back solid. It now builds an
opacity plane from the PNG's alpha channel, and the build script writes those
pages as RGBA. The paletted pixels cannot answer the question themselves: a
transparent PNG texel becomes index 0, which is also an ordinary black.

**Validation is all-or-nothing on purpose.** An upscaler that dies partway
through still writes a loadable pk3, and a level where some walls are sharp and
their neighbours are not is worse than one where none are. The pack carries
`c7upscal.lst`, the manifest of what the build *intended* to write, and every
name in it must resolve as a hires lump in that same file. A pack that fails is
skipped entirely — `AddHiresTextures` is not called for it — rather than partly
applied.

`tools/test_corridor7_upscale.sh` builds a pack with `fake_upscaler.py` (a
nearest-neighbour stand-in, so the test needs no GPU and takes seconds) and
checks the four states: absent, complete, switched off, incomplete. The case
that would rot silently is *switched off*: it is the only one where a texture has
to be put back, and it asserts the frame is **byte-identical** to having no pack
installed at all.

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
