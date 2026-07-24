# Phase 10 — View model, HUD, and the 2D compositor

Phases 5–9 built the GL 3D world: opaque walls, doors, pushwalls, floors,
ceilings, see-through masked panes, and actor sprites — all verified offscreen
against the software renderer. Everything so far has been *3D*. Phase 10 begins
the other half of a frame: the 2D layer the software engine draws on top of the
world — the first-person **weapon**, the **HUD / status bar**, **menus**,
**text**, the **automap**, and screen **transitions** — and composites it with
the GPU world into one complete playable frame.

Phase 10 landed in two slices. The first built the **backend-neutral 2D
compositor** and verified a full composited frame offscreen against the software
screenshot. The second (below, "Live present") flips the game window itself over
to GL when `vid_renderer` selects OpenGL, so a Corridor 7 level is *played* on
the GPU — world, weapon, HUD, menus, and transitions — without ever blitting the
software framebuffer to the screen. The software renderer remains the untouched
default and fallback, and the determinism gate stays green throughout.

## The model: 3D world + transparent-keyed 2D overlay

In ECWolf every 2D element is drawn as *final palette indices* into a single
8-bit framebuffer, on top of the 3D view. A GPU frame reproduces that layering
without re-implementing any of the 2D code:

1. The **GL 3D world** is rendered into a colour texture the exact size of the
   3D view sub-rectangle (`viewwidth × viewheight`). It reuses the Phase 5–9
   world renderer verbatim — same meshes, same indexed/colormap/palette shader,
   same interpolated camera — so the world pixels are identical to the world
   capture. Keeping it view-sized means the screen-space plane-band / horizon
   math needs no repositioning.

2. The engine's **8-bit 2D layer** (weapon, HUD, menus, text) is uploaded as an
   *indexed overlay*: an `R8UI` index texture plus an `R8UI` opacity texture.
   Everything **outside** the 3D view rectangle — the status bar, full-screen
   menus, letterboxing — is opaque 2D. **Inside** the view rectangle only the
   pixels a 2D pass drew over the world (the player weapon) are opaque; the rest
   is transparent so the GPU world shows through.

3. The **compositor** (a screen-space quad in `kScreenFrag`) blits the world
   texture into the view sub-rectangle, then draws the overlay over the whole
   frame, resolving each opaque overlay texel through the palette and
   `discard`ing transparent ones so the world behind shows through. Walls, HUD,
   and weapon end up in one frame with correct occlusion.

## Recovering the weapon silhouette (two-background coverage)

The overlay's hard part is deciding which view-region texels are "weapon" (keep,
opaque) and which are "world" (drop, transparent). A single reserved key is
fragile — a 2D element may legitimately paint that index. Instead the weapon is
detected by **background independence**: `DrawPlayerWeapon` is re-run over two
different backgrounds (`0x00` and `0xFF`) into scratch buffers, and a texel is
opaque iff it comes out **identical** both times. The weapon overwrites
deterministically, so its texels always match across the two backgrounds while
untouched background texels always differ — collision-proof, whatever indices
the weapon art uses. This mirrors exactly what the live path will do (clear the
view to a key, draw the weapon over it), but reconstructs it non-destructively
inside the capture.

## Shading

The world texture is already fully shaded by the Phase 6 pipeline
(index → colormap[shadeRow] → palette). The 2D overlay is **not** distance-shaded
— 2D graphics are drawn at full brightness as final indices — so the compositor
resolves overlay texels straight through the 256-entry palette texture, the same
`GPalette.BaseColors` the software screenshot is written with. Palette effects
(damage flash, visor, fades) already live entirely in that palette, so they
apply to the composited frame for free.

## Verification (headless, Xvfb + Mesa)

`tools/test_gl_frame.sh` captures the software screenshot and the GL composite of
the same Corridor 7 MAP01 frame and asserts:

```
PASS: GL composite frame rendered (640x480, view 640x380 at 0,0).
PASS: player weapon composited over the GL 3D view (13113 opaque texels).
PASS: 2D HUD band below the view is pixel-exact vs software (640x100 at y=380).
```

* **HUD pixel-exact.** The status-bar band below the 3D view is an *exact* match
  (AE = 0) to the software frame — both resolve the same 8-bit overlay through
  the palette. This also proves the compositor's vertical orientation: a flip
  would scatter the band entirely.
* **Weapon over world.** The player weapon composites opaque texels over the GL
  world (occluding it, occluded by nothing), at the same screen position and with
  the same pixels as software; only the transparent gaps differ, showing the GPU
  world instead of the software world behind them.
* **World region** differs from software only by the known GL-vs-software
  rasterization delta (dither / sub-pixel), exactly as in the Phase 5–9 world
  capture.
* **Determinism gate green** — `checksum=400c5d59`, unchanged from Phases 6–9;
  the compositor touches only render-scratch state.

## Live present (GPU-owned game window)

When `vid_renderer` selects OpenGL, the window itself becomes the compositor's
target:

* **SDLFB creates a GL-capable window** (`SDL_WINDOW_OPENGL` + a 3.3 core
  context) and, instead of streaming the 8-bit `MemBuffer` through an
  `SDL_Renderer`, routes `Update()` to `R_GLLivePresent` and `SDL_GL_SwapWindow`.
  This is hard-gated: with the default `vid_renderer = software` nothing in the
  SDL video path changes, so the reference experience is byte-for-byte identical.
  A failed context creation falls back to the software present cleanly.
* **`OpenGLRenderer::RenderScene`** runs a *reduced* software frame each gameplay
  tic: it calls `WallRefresh` **only for its side effects** — the raycaster stamps
  each ray-touched cell `visible` (which GL sprite culling and the automap read)
  and sets `viewz`/`viewshift` for the plane-height uniforms — then discards the
  wall pixels by clearing the 3D view region to the compositor key and redrawing
  the weapon over it. It then renders the GL world into a persistent FBO. Index
  textures are cached across frames (rebuilt only on level change); only the
  meshes and the 2D overlay are rebuilt per frame.
* **Present** uploads `MemBuffer` as the overlay and composites exactly as the
  offscreen path, keying the view region on `GPalette.Remap[0]`. Because the 2D
  layer is drawn over that key *after* `RenderScene`, the live path composites
  **everything** drawn over the world — the weapon, notification banners, floating
  messages — automatically, so it is strictly more complete than the offscreen
  reconstruction. Non-gameplay frames (menus, intermissions, loading, fades) have
  no world and present as pure opaque 2D.

Verified by `tools/test_gl_live.sh`: it plays a level on the GPU headlessly
(Xvfb creates a real GL window), captures the on-window presented frame, and
checks it against a software reference run — the OpenGL renderer goes live and
the 2D HUD band is pixel-exact (AE = 0) against software. The determinism gate is
unaffected (it runs the default software path).

## Scope / what is deliberately deferred

* **GPU visibility.** The live path still runs the CPU raycaster (`WallRefresh`)
  purely to stamp cell visibility for sprite culling and the automap, discarding
  its wall pixels. Replacing it with a GPU-side frustum/portal visibility pass —
  so the raycaster is not run at all under GL — is Phase 11's culling work.
* **Single-key overlay transparency (live).** The live present keys the view
  region on one index (`GPalette.Remap[0]`) rather than the offscreen path's
  collision-proof two-background test, so a 2D element that paints exactly that
  index inside the view region would read as transparent (a rare, single-pixel
  artifact confined to the view). The offscreen composite remains collision-proof.
* **Static-mesh caching.** Index textures already persist across frames, but the
  world *mesh* is rebuilt every frame. Caching the static (non-animated) geometry
  is a Phase 10/11 optimization.
* **Interactive hardening** — window resize, fullscreen toggle, alt-tab / context
  loss, resolution changes, HiDPI drawable scaling, and vsync/perf profiling —
  is Phase 11 per the redesign. The live path is functional and headless-verified;
  these robustness paths are not yet exercised.
* **The offscreen harness** (`R_GLFrameCapture`) reconstructs only the weapon as
  2D-over-world (banners/messages go through the `screen` DCanvas, not the `vbuf`
  path). The live path has no such boundary — it composites all of them.

## Exit gate — met

A complete Corridor 7 level can be played, paused, saved, loaded, exited, and
navigated through menus with the OpenGL renderer selected, presented entirely by
the GPU compositor — the world on the GPU, the weapon / HUD / menus / text / and
transitions composited over it — without ever blitting the software framebuffer
to the screen. The HUD is pixel-exact against the software reference and the
world matches within the known rasterization delta. The software renderer remains
the default and a clean fallback, the simulation is untouched, and the
determinism gate stays green. Remaining items (GPU visibility, static-mesh
caching, interactive/robustness hardening) are Phase 11.
