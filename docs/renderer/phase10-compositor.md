# Phase 10 — View model, HUD, and the 2D compositor

Phases 5–9 built the GL 3D world: opaque walls, doors, pushwalls, floors,
ceilings, see-through masked panes, and actor sprites — all verified offscreen
against the software renderer. Everything so far has been *3D*. Phase 10 begins
the other half of a frame: the 2D layer the software engine draws on top of the
world — the first-person **weapon**, the **HUD / status bar**, **menus**,
**text**, the **automap**, and screen **transitions** — and composites it with
the GPU world into one complete playable frame.

This first Phase 10 slice lands the **backend-neutral 2D compositor** and
verifies a full composited frame offscreen against the software screenshot. It
does not yet flip the live SDL window over to GL presentation (that is the
closing Phase 10 slice); the software renderer still owns the game window, and
this slice is exercised through the capture harness, so the playable build is
unchanged and the determinism gate stays green.

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

## Scope / what is deliberately deferred

* **Live SDL-window ownership.** This slice composites and verifies offscreen
  through the capture harness; the software renderer still owns and presents the
  game window. Routing `screen->Update()` through a persistent GL context — so a
  level is *played* on the GPU without the software framebuffer — is the closing
  Phase 10 slice, together with persistent per-frame GL resources and static-mesh
  caching of non-animated cells.
* **2D drawn over the view other than the weapon.** Notification banners,
  floating messages, and the overhead automap are drawn through the `screen`
  DCanvas rather than the `vbuf` path the weapon uses, so the offscreen harness —
  which re-runs only the weapon — does not reconstruct them. The live path draws
  them over the transparent-keyed view like any other 2D, so they composite
  naturally there; this is a capture-harness reconstruction boundary, not a
  compositor limitation (the weapon proves arbitrary opaque 2D-over-world works).
* **Fizzle / fade transitions** are palette- and framebuffer-level effects that
  join the live-present slice, where the composited frame is the surface they
  operate on.

## Exit-gate progress

The 2D compositor — the core of "a playable frame without the software
framebuffer" — is in place and verified: the GPU world, the first-person weapon,
and the HUD composite into one correct, correctly-oriented frame the size of the
software screenshot, with the HUD pixel-exact. The remaining Phase 10 exit-gate
work is the live-window present swap so a complete level is *played* through this
compositor; the simulation is untouched and the determinism gate remains green.
