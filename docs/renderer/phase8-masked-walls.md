# Phase 8 — Masked walls and special Corridor 7 surfaces

Phases 5–7 built the opaque static world plus the moving geometry (doors,
pushwalls). Phase 8 adds the *see-through* geometry: glass, grates, fences,
force fields, and the opened apertures left by Corridor 7's animated walls.
These are colour-keyed surfaces — the texture reserves an index as transparent —
so they must be alpha-tested, and the geometry rendered *behind* them must show
through. As before the work is verified offscreen against the software renderer;
the simulation is untouched and the determinism gate stays green.

## The problem Phase 8 fixes

A masked-wall cell is still a `tile` (it has walls), so the Phase 5 static
builder was emitting it as an **opaque** wall. In game that turns every
chain-link fence and glass pane into a solid block. Phase 8 routes those cells
into a dedicated alpha-tested mesh instead, and — just as importantly — fixes the
neighbour-occlusion test so the geometry seen *through* a masked pane is actually
built.

## The model

* **Classification (`DynamicWalls::IsMaskedWallCell`)** — a cell is masked when
  `maskedWallType` (derived at load time from index-255 art) or the tile's
  `renderMasked` flag is set, and it is *not* a door. Doors are masked too, but
  they already render as sliding leaves in the Phase 7 dynamic mesh, so they are
  excluded here to avoid drawing them twice.

* **`WorldBuilder::BuildStatic` — two fixes:**
  * Masked cells are pulled out of the opaque mesh (their floor/ceiling is still
    emitted; a masked full tile has no sector, so that is a no-op).
  * Occlusion now hides a wall face only when the neighbour is an **opaque solid**
    tile (`IsSolidOccluder`). Doors, pushwalls, and masked panes no longer hide
    the face behind them, so a wall seen through glass — or a doorjamb beside a
    door — is built instead of being culled. (This also lands the door-jamb faces
    deferred from Phase 7.)

* **`WorldBuilder::BuildMasked`** — emits, for each masked cell, the same four
  tile-boundary faces a solid wall would (the planes the raycaster's
  `GetMaskedWallEndpoints` uses for a non-offset masked wall), tagged
  `WSURF_Masked`. Two refinements mirror `wl_draw.cpp` exactly:
  * **Connected glass.** `MaskedRenderSide` culls the internal tile boundaries of
    a run of panes (matching `IsConnectedMaskedWall`/`IsMaskedWallRenderSide`), so
    a glass-lined corridor is one continuous plane instead of showing the
    periodic floor-to-ceiling seams that edge-on internal faces would draw.
  * **Force-field / animated-wall texture.** `ResolveWallTexture` reproduces
    `GetWallTexture`: a Corridor 7 wall with `corridor7WallMarker` 1..3 cycles
    through four `C7Wnnnn` frames selected by the game clock. The builder reads
    this (not the frozen `spot->texture`) for **every** wall path — static,
    masked, and door leaf — so force fields shimmer. Because the frame depends on
    the clock, the mesh is rebuilt each frame; keeping animated cells out of a
    future cached static mesh is a Phase 10 note.

* **`render/opengl/r_glworld.cpp`** — the masked mesh is uploaded (sharing the
  index/opacity/palette caches) and drawn after the static and dynamic meshes in
  the same clear and depth buffer. Because every masked fragment either writes
  depth (opaque texel) or is discarded (transparent texel), draw order does not
  affect correctness. The fragment shader gains the masked transparency test,
  mirroring the software `ScaleMaskedWallPost` post-opacity check:
  * an explicit per-column **opacity buffer** wins when the texture provides one
    (the C7 grate/fence `FFlatTexture`s — 6 of them on MAP01);
  * otherwise a masked wall (and, now, a door leaf) is keyed on the **index-255
    remap colour** (`GPalette.Remap[255]`), the transparency key used throughout
    Corridor 7.
  A small negative polygon offset biases the masked pass toward the viewer so a
  pane mounted flush on a solid wall does not z-fight the coplanar wall behind it.

## Verification (headless, Xvfb + Mesa)

Corridor 7 MAP01 spawns facing a corridor lined with chain-link fences and
diamond-grate panels — a dense masked-wall scene.

```
GL world: static walls=1388 floors=1245 ceilings=1245 verts=23268; dynamic faces=16 verts=96 (alpha=…); masked faces=84 verts=504
GL world: uploaded 45 unique index textures (6 with opacity).
PASS: GL static world rendered (walls=1388, dynamic-faces=16, coverage=99.3%).
PASS: GL masked walls built (84 faces, 6 textures with opacity masks).
PASS: GL door slide renders (closed vs open differ by 1065 px).
```

* **Transparency.** The GL render shows the chain-link fences as see-through: the
  floor and the wall panels behind the diamond mesh are visible through the
  transparent texels, matching the software frame. Before Phase 8 the same cells
  rendered as solid blocks.
* **Both alpha paths exercised.** 6 masked textures upload explicit opacity masks;
  the remaining masked faces alpha-test on the index-255 colour key.
* **Depth interactions.** Masked panes share the opaque depth buffer; opaque
  texels occlude and are occluded correctly, and transparent texels reveal freshly
  rendered geometry rather than stale framebuffer contents (the discard never
  writes colour or depth).
* **`tools/test_gl_world.sh`** asserts the masked mesh is non-empty and that at
  least one opacity mask uploaded, in addition to the existing wall/door checks.
* **Determinism gate green** — `checksum=400c5d59`, unchanged from Phases 6–7;
  interpolation on/off identical. Phase 8 only *reads* simulation state.

## Scope / what is deliberately deferred

* **Translucent (blended) surfaces.** Corridor 7's masked walls are binary
  alpha (opaque-or-keyed), matching `ShadeWallColor`, so no alpha blending is
  needed. Any genuinely translucent effect would need a sorted blended pass and
  is out of scope here.
* **Pixel-exact software/GL parity** over the masked test matrix (framing,
  aspect, sub-pixel column selection) remains a Phase 11 item; Phase 8 verifies
  the geometry, transparency behaviour, and material classification.
* **Static-mesh caching.** Animated-wall cells change texture with the clock, so
  they must stay out of any revision-cached static mesh; that caching lands with
  the persistent live context in Phase 10.
* **Visor-dependent sprite visibility and the laser-barrier sprite dissolve** are
  sprite/actor effects and belong to Phase 9.

## Exit gate — met (offscreen level)

Masked walls build as a separate alpha-tested mesh, render see-through with the
correct transparency key (explicit opacity mask or index-255), reveal the
geometry behind them, merge into continuous planes across connected panes, and
animate their force-field art with the game clock. Ordinary walls, door leaves,
and masked walls share one depth buffer with correct occlusion. The determinism
gate remains green; the simulation is untouched.
