# Phase 6 — Indexed palette + colormap shader fidelity

The "looks like ECWolf" phase. Phase 5 drew the static world geometry with a
debug pseudo-colour shader; Phase 6 replaces that with real fidelity by resolving
every world pixel exactly the way the software renderer does — through the 8-bit
indexed palette and distance colormap — still rendered offscreen and verified
headlessly against software screenshots. The live game window is unchanged.

## What landed

* **Real indexed textures.** Each surface's `FTexture` is uploaded once as an
  `R8UI` *index* texture (physical palette indices, transposed from ECWolf's
  column-major `GetPixels()` into row-major). Textures are cached per
  `FTextureID` so shared art uploads a single time.
* **Palette + colormap textures.** A 256×1 `RGB8` palette texture from
  `GPalette.BaseColors` (the same buffer the software screenshot is written with,
  so parity is exact) and a 256×`NUMCOLORMAPS` `R8UI` colormap texture uploaded
  directly from `NormalLight.Maps`.
* **Shader pipeline** `index → colormap[shadeRow] → palette`, all integer/nearest
  fetches — palette indices are never linearly filtered.
* **Shade rows mirror the software renderer per surface type:**
  * *Walls* use the perpendicular forward distance (view-space `-z`), fed through
    ECWolf's exact wall formula (`heightnumerator`, `r_depthvisibility`,
    `LIGHT2SHADE`, `GETPALOOKUP`, `MINZ`) — the same quantity `wallheight`
    encodes in the raycaster.
  * *Floors/ceilings* use the Corridor 7 screen-space VGA band pattern
    (`c7PlaneShades`: `firstShade + band` from the horizon, with the four-pixel
    alternation dither), or the generic distance-row plane formula for non-C7.
* **Corridor 7 colour rules, wall-only** (matching `ShadeWallColor`): the
  208–239 colour-cycle by `TimeCount`, and full-bright reserved indices
  (`Remap[15]`, `Remap[254]`, `Remap[208..239]`) that ignore distance shading.
  Planes deliberately apply neither, matching `R_DrawPlane`.
* **Explicit opacity.** Corridor 7's see-through wall art (grates/fences) carries
  a per-column `GetColumnOpacity()` buffer; it is uploaded as an `R8UI` opacity
  texture and transparent texels are `discard`ed. Transparency is *explicit* —
  never inferred from index 0/255 — exactly like the software `postopacity` test.
* **4×4 Bayer dither** on the wall shade row (by pixel coord) to smooth the 64
  discrete colormap bands; toggleable via the `uDither` uniform.
* **Palette effects stay in the palette texture.** Visor / electric / damage /
  pickup shifts only ever re-upload the 256-entry palette; world pixels never
  change. The offscreen capture reads the live `BaseColors`, so any active shift
  is reflected for free.
* **Shade-row debug mode** (exit-gate requirement): a second render pass writes
  `<out>.shaderow.ppm`, visualizing the per-pixel shade row as greyscale.

## Verification (headless, Xvfb + Mesa)

`tools/test_gl_world.sh` renders the software screenshot and the GL offscreen
render of the same view. On Corridor 7 MAP01:

```
GL world: mesh walls=1422 floors=1195 ceilings=1195 verts=22872
GL world: uploaded 45 unique index textures (6 with opacity).
GL world: rendered 640x380, 96.4% covered.
```

Side-by-side against software, the GL render now reproduces the real wall art,
the gray wall panels, the dark see-through grate side walls (transparent texels
discarded rather than drawn as magenta key), the dithered floor/ceiling
gradients, and the full-bright hazard stripes / lamp indices. MAP03 and MAP12
render the same way (blue banded walls, yellow/black hazard bank, drip walls).

## Scope / what is deliberately deferred

* **Exact C7 plane VGA banding.** The plane shade is a faithful reconstruction of
  `c7PlaneShades` (`firstShade`, band stepping, 4-px alternation) but omits the
  per-colour duplicate-run compression the software renderer walks in
  `NormalLight.Maps`; C7 planes therefore read slightly brighter than software.
  Exact plane parity is a Phase 11 (parity/hardening) item.
* **Exact framing/aspect** against the raycaster is still refined in Phase 11.
* Dynamic walls (Phase 7), masked mid-wall geometry / decorations (Phase 8) and
  sprites (Phase 9) are not in the static mesh. Making GL the live game window is
  the Phase 10 window-ownership refactor.

## Exit gate — met (offscreen level)

Static-world GL screenshots closely match the software renderer — real indexed
textures resolved through the palette and distance colormap, C7 colour-cycle,
full-bright, and see-through opacity all reproduced — with a debug shader mode
that outputs the shade row. Determinism gate remains green (Phase 6 touches only
the offscreen GL path; the simulation is untouched, run-to-run stable, and
interpolation on/off is identical).
