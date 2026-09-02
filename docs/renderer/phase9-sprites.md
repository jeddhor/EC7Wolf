# Phase 9 — Sprites and world effects

Phases 5–8 built the world: opaque walls, doors, pushwalls, floors, ceilings,
and see-through masked panes. Phase 9 adds the actors — every billboard the
software renderer draws in `DrawScaleds()`: posts, pickups, mines, projectiles,
enemies, bosses, and Corridor 7's infrared laser barrier. As before the work is
verified offscreen against the software renderer, the scan-line scaler is left
untouched, and the determinism gate stays green.

## The split: selection vs. scaling

The software renderer fuses two jobs in one inner loop: it *selects* what to draw
(which actors are visible, which rotation frame, mirror, material state) and it
*scales* the chosen texture column-by-column into the framebuffer. The GPU
renderer keeps the selection identical and replaces the scaling with a
camera-facing billboard quad that the existing indexed shader rasterises against
the world depth buffer.

* **`R_GetSpriteRenderInfo` (r_sprites.cpp)** reproduces the selection half of
  `ScaleSprite`/`Scale3DSprite` without drawing: the frame's `Sprite`, the eight-
  way rotation via `CalcRotate`, the mirror bit, full-bright (`FL_BRIGHT` or
  `frame->fullbright`), world-orientation (`FL_BILLBOARD`), and the Corridor 7
  visor gate (`C7VisorCanSeeActor`). It returns
  false when the actor must not be drawn this instant. It lives in r_sprites.cpp
  because the sprite tables (`loadedSprites`/`spriteFrames`) are file-static
  there.

* **`WorldBuilder::BuildSprites` (r_spritebuilder.cpp)** walks the actor list with
  the same nine-cell visibility test as `DrawScaleds`, runs `TransformActor` (to
  populate `viewx`, which `CalcRotate` reads), calls the selector, and emits one
  billboard quad per surviving sprite tagged `WSURF_Sprite`.

## Billboard geometry

One sprite texel maps to 1/64 of a tile, so a 64px-tall sprite at unit scale is
exactly one tile high. This follows from the software scaler: a sprite's on-screen
height is `GetScaledHeightDouble()*dyScale`, `dyScale = (height/256)*scaleY`, and
the full-tile wall height at the same distance is `height/256*(planeDepth)` with
the Corridor 7 plane depth of 64 — so a 64px sprite and a one-tile wall project to
the same pixel height. The quad is therefore:

* **Width / height** = `GetScaledWidthDouble()*scaleX/64` and
  `GetScaledHeightDouble()*scaleY/64` tiles.
* **Horizontal axis** — screen-facing by default: the world-space screen-right
  vector `(-viewsin, -viewcos)` (forward `(viewcos,-viewsin)` × up `+Z`), so the
  billboard stays parallel to the view plane and upright. For `FL_BILLBOARD`
  actors the axis is the actor's facing `(finesine, finecosine)` — a flat panel
  placed in the world, matching `Scale3DSprite` (the laser-barrier rods).
* **Horizontal anchor** at the texture's scaled left offset; **vertical** with the
  sprite standing on the floor (z = 0 … worldH).
* **Mirror** bakes into the quad's U coordinates.

## Shading (shared indexed shader, r_glworld.cpp)

Sprites reuse the wall shade path (`uSurfKind = 2`): the fragment's perpendicular
view-space distance drives the same `GETPALOOKUP` shade row the software sprite
loop computes from `FixedMul(r_depthvisibility<<8, height)`. On top of that:

* **Transparency** keys on **raw index 0** (`if(src[y]) …` in the scaler), *not*
  the index-255 mask color walls use. An explicit opacity buffer still wins when
  a sprite texture provides one.
* **Color-cycle** — Corridor 7 rotates indices 208–239; sprites share the wall
  cycle block, matching `C7CycleSpriteColor`.
* **Full-bright** — `FL_BRIGHT`/`frame->fullbright` forces shade row 0 (ignore
  distance), matching `colormap = NormalLight.Maps`. The wall-only reserved-index
  full-bright rule (indices 15/254) is suppressed for sprites.
* **Laser barrier** — no shader case at all, and deliberately so. Corridor 7's
  infrared barrier statics are painted entirely in the 232-239 ramp, so the
  color-cycle and full-bright rules above *are* the effect: the rotation walks
  the infrared red sweep along artwork whose indices already climb the ramp. An
  earlier revision special-cased them here (a hashed dissolve painting
  `ColorMatcher.Pick(0xFF,0xFF,0xFF)`); it was removed, along with the
  `WorldSurface::laser` / `uSpriteLaser` plumbing that carried it. See
  [corridor7.md](../corridor7.md#the-infrared-laser-barrier).

## Depth and draw order

Sprites are drawn last, sharing the world depth buffer. Because each fragment
either writes depth (opaque texel) or is discarded (transparent/unlit), draw order
never affects correctness: walls and masked panes occlude sprites, nearer sprites
occlude farther ones, and a sprite behind glass shows through the pane's discarded
texels (the pane wrote no depth there). No sorted blended pass is needed — like
the masked walls, Corridor 7 sprites are binary alpha.

## Interpolation

Actor sprites and the camera are read at their **interpolated** sub-tic transform,
matching the software frame: the capture applies `Interpolation::Apply(alpha)`,
refreshes the view basis (`CalcViewVariables`) so the billboard builder is
consistent with the interpolated camera, builds the sprites, captures the camera
transform, then restores authoritative simulation state. Animation *frames* are
never blended — only positions/angles interpolate — so motion is smooth without
ghosting. `Apply`/`Restore` are no-ops when interpolation is disabled, and they
touch only render-scratch transforms, so the determinism gate is unaffected.

## Verification (headless, Xvfb + Mesa)

Corridor 7 MAP01 spawns facing the two white gate posts (C010 statics) flanked by
further statics:

```
GL world: static walls=1388 … masked faces=84 verts=504; sprite faces=6 verts=36
PASS: GL static world rendered (walls=1388, dynamic-faces=16, coverage=99.3%).
PASS: GL masked walls built (84 faces, 6 textures with opacity masks).
PASS: GL actor sprites built (6 billboard faces).
PASS: GL door slide renders (closed vs open differ by 1065 px).
```

* **Placement / depth.** The two posts render at the correct screen positions and
  scale, standing on the floor in front of the back wall — matching the software
  frame (whose gun and HUD are Phase 10 overlays, absent from the world capture).
* **Both transparency families.** Sprite silhouettes alpha-test on index 0;
  masked walls still key on index 255 — the two paths coexist in one shader.
* **`tools/test_gl_world.sh`** now asserts MAP01 builds a non-empty sprite mesh,
  alongside the wall / masked / door checks.
* **Determinism gate green** — `checksum=400c5d59`, unchanged from Phases 6–8;
  interpolation on/off identical.

## Scope / what is deliberately deferred

* **Pixel-exact vertical placement.** Hanging/floating `z` offsets and the exact
  top-offset anchoring are approximated (feet on floor); pixel-exact sprite
  framing joins the software/GL parity matrix in Phase 11.
* **Rotation scenes** are verified by faithful code reuse (`CalcRotate` and the
  mirror bit are the same logic as the software path); the stationary capture demo
  has no enemy walking through a rotation in frame, so that is re-checked live once
  the GL backend owns the window in Phase 10. (The infrared barrier is now covered
  directly, in both renderers, by `tools/test_corridor7_laserbarrier.sh`.)
* **Blended/translucent sprites.** None in Corridor 7 (binary alpha), so no sorted
  pass; a genuinely translucent effect would need one and is out of scope.
* **Static-mesh caching** still excludes animated/actor geometry (a Phase 10 note).

## Exit gate — met (offscreen level)

Actor sprites build as depth-tested billboards with correct frame/rotation/mirror
selection, scale and offsets, screen-facing or world-oriented orientation,
index-0 transparency, Corridor 7 color-cycle, full-bright and visor gating —
which is what lights the infrared laser barrier — occluding and occluded by walls and masked panes
in one shared depth buffer, at interpolated positions without frame blending. The
determinism gate remains green; the simulation is untouched.
