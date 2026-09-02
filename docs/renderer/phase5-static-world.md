# Phase 5 — Static opaque world (worldbuilder + calibrated GL camera)

First GL world rendering, built the offscreen-first way: the backend-neutral
world-geometry builder plus a GL renderer that draws it through an
ECWolf-calibrated camera into an offscreen framebuffer, verified headlessly. The
game still runs on the software renderer; nothing about the live window changes.

## What landed

* `render/r_worldbuilder.{h,cpp}` (backend-neutral): converts the map's plane 0
  into GPU geometry in tile units (1 tile = 1.0, Z up, floor z=0 / ceiling z=1):
  * one wall quad per solid-tile face that borders open space (the same
    `!adjacent->tile` rule the raycaster uses);
  * one floor and one ceiling quad per open cell that has those textures.
  Output is a `WorldMesh` of interleaved vertices plus a `WorldSurface` list
  (vertex range + real `FTextureID` + kind + side) so Phase 6 can bind the
  actual indexed textures. Only *static opaque* geometry — dynamic and masked
  walls are excluded for later phases.
* `render/opengl/r_glworld.{h,cpp}`: uploads the mesh (VAO/VBO), a debug world
  shader, a depth buffer, and a camera calibrated to ECWolf (position from
  `camera->x/y` in tile units, yaw/pitch from the binary angles, horizontal FOV
  from `players[].FOV`), rendering to an offscreen color+depth FBO and reading
  it back to a PPM. `R_GLWorldCapture()` creates its own hidden GL context, so
  it is safe to call while the software renderer owns the game window.
* Capture hook `--capture-glworld <ppm>`: at the `--capture-frame`, renders the
  GL world of the *same* view alongside the software screenshot.
* `tools/test_gl_world.sh`.

## Verification (headless, Xvfb + Mesa)

On Corridor 7 MAP01 at the spawn view:

```
GL world: mesh walls=1422 floors=1195 ceilings=1195 verts=22872
GL world: rendered 640x380, 100.0% covered.
```

The offscreen image has the correct vertical composition for a level interior
viewed at eye height: a uniform dim ceiling across the top, walls of varying
depth through the middle, and a distinct floor across the bottom. That vertical
separation demonstrates the perspective projection and depth buffer are working
and that the camera is placed and oriented from the live ECWolf view.

## Scope / what is deliberately deferred

Phase 5 debug-shades each surface by a per-texture pseudo-color (so structure
and depth are visible); **real indexed textures + palette/colormap fidelity are
Phase 6**, and exact pixel-parity framing/aspect against the software raycaster
is refined in Phase 6 and locked down in Phase 11. Dynamic walls (Phase 7),
masked walls (Phase 8), and sprites (Phase 9) are not in the static mesh. Making
GL the live game window is the Phase 10 window-ownership refactor.

## Exit gate — met (offscreen level)

The world builder produces correct, deterministic geometry from the map, and the
GL renderer draws it with a depth-tested, ECWolf-calibrated camera to an
offscreen buffer that shows correct framing and structure. Determinism gate
remains green (`3402c83a`); the game is unchanged on the software renderer.
