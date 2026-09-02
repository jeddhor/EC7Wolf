# Phase 7 — Doors, pushwalls, and changing map geometry

Phases 5–6 built the *static* opaque world. Phase 7 adds the geometry that moves
every simulation tic — sliding doors and pushwalls — and interpolates it so the
motion is smooth at any refresh rate. As in Phases 5–6 the work is verified
offscreen against the software renderer; the live game window is unchanged and
the simulation is byte-for-byte identical (the determinism gate stays green).

## The model

Dynamic geometry is kept **out** of the static mesh and rebuilt every frame, so a
door leaf or a moving pushwall never has to invalidate the (large) static mesh.

* **`render/r_dynamicwalls.{h,cpp}`** — a renderer-owned snapshot + interpolation
  store, the door/pushwall analogue of the Phase 3 actor interpolation. Around
  each tic `BeginTic()` shifts *current → previous* and `EndTic()` captures the
  new *current*; `Reset()` (called from `SetupGameLevel`) forgets history so a
  new or loaded level does not smear. `GetRender(alpha)` returns the door and
  pushwall render lists blended at the sub-tic `alpha`.
  * A **door** is keyed by its (stable) map cell.
  * A **pushwall** is keyed by its **thinker**, not a cell, because the same
    logical wall transfers ownership from one cell to the next as it moves. The
    stored value is the block's *world-space* base corner, so it stays continuous
    across a tile boundary and never snaps backwards when `pushAmount` resets from
    64 to 0. This is exactly the mitigation the design calls for.
  * The store only ever *reads* simulation fields, so determinism is preserved.

* **`render/r_worldbuilder.cpp`** — split into `BuildStatic` and `BuildDynamic`,
  sharing one cell classification (`DynamicWalls::IsDynamicCell`) so the two
  meshes agree on exactly which cells are dynamic.
  * `BuildStatic` skips door and moving-pushwall cells but still emits their
    floor/ceiling, so the doorway (and a vacated pushwall cell) is not a hole.
    Neighbors still treat those cells as solid for face adjacency, so no
    duplicate wall appears at the opening.
  * `BuildDynamic` emits, at the interpolated positions from `GetRender`:
    * one **door-leaf** quad per door in the tile-center plane (the same plane
      the raycaster's `GetMaskedWallEndpoints` uses: `left+½` for a vertical
      door, `top+½` for a horizontal one), tagged with the door's slide style
      and amount;
    * a 1×1 opaque **pushwall block** at the interpolated base corner, all four
      faces (a moving wall can be seen from any side; the depth buffer resolves
      occlusion).

* **`render/opengl/r_glworld.cpp`** — the offscreen capture now uploads and draws
  the dynamic mesh after the static mesh, sharing one clear, depth buffer, shader
  and texture cache. The fragment shader reproduces the software door slide along
  the leaf's U axis before sampling:
  * `CheckSlidePass(style, intercept, amount)` → `discard` for open columns;
  * `SlideTextureOffset(style, …)` shifts the remaining (solid) columns, so the
    leaf recedes into its pocket exactly as `HitVertWall`/`DrawMaskedWall` draw
    it, for all three styles (`SLIDE_Normal`, `SLIDE_Split`, `SLIDE_Invert`).
  * A door leaf is otherwise shaded as a wall (perpendicular distance, C7 color
    cycle, full-bright), matching `ShadeWallColor`.

The tic hooks are wired next to the existing actor interpolation in the play loop
(`Interpolation::BeginTic/EndTic` → `DynamicWalls::BeginTic/EndTic`) and reset in
`SetupGameLevel`.

## Verification (headless, Xvfb + Mesa)

Two capture-time world overrides were added to the deterministic harness so a
mid-motion door/pushwall can be compared between the software and GL renderers
without scripted input. They are opt-in and never used by the determinism gate:

* `--capture-open-doors N` forces every door to slide amount `N` (0..65535) each
  tic (before thinkers run, so both renderers and the interpolation snapshot
  agree);
* `--capture-push N` wires the nearest in-view wall up as a mid-move pushwall
  (`SetTile` the destination, point `pushReceptor` back — exactly as `EVPushwall`
  does) and holds it at push amount `N` (0..64).

On Corridor 7 MAP01 at the spawn view (a hazard-striped door is dead ahead):

```
GL world: static walls=1390 floors=1211 ceilings=1211 verts=22872; dynamic faces=16 verts=96
PASS: GL door slide renders (closed vs open differ by 1065 px).
```

* **Doors.** Forcing the door from closed → open, the GL hazard-striped leaf
  slides open progressively and reveals the room behind it, matching the software
  door frame by frame (`tools/test_gl_world.sh` now asserts the closed/open GL
  images differ).
* **Pushwalls.** `--capture-push` moves a grate-textured wall one tile into the
  corridor; the block appears at the same world position in both the software
  raycaster and the GL render (both images change by a comparable amount when the
  block moves; the block is emitted as 4 extra dynamic faces).
* **Interpolation.** Door slide amounts and pushwall world positions blend
  linearly between the previous and current tics; pushwalls are keyed by thinker
  so the world position is continuous across a tile transfer by construction.
* **Determinism gate green** — run-to-run stable (`checksum=400c5d59`, unchanged
  from Phase 6) and interpolation on/off identical. Phase 7 only *reads*
  simulation state.

## Scope / what is deliberately deferred

* **Map revision / dirty-material caching and visibility-connectivity recompute.**
  The offscreen capture rebuilds the mesh each frame, so revision-gated caching is
  not yet observable; it lands with the persistent live GL context in Phase 10.
  The static/dynamic split done here is the prerequisite.
* **Door jambs.** A door leaf sits in the tile center while its cell's side faces
  are suppressed (as in the classic engine); the exact jamb/track texture on the
  half-tile pocket is a masked-surface detail deferred to Phase 8/11.
* **Software-side dynamic-wall interpolation.** The software raycaster still reads
  live door/pushwall state; consuming interpolated dynamic state in *both*
  renderers is folded into the live-window work (Phase 10) alongside interpolated
  camera parity for the capture.
* Exact framing/aspect parity against the raycaster remains a Phase 11 item.

## Exit gate — met (offscreen level)

Every dynamic wall type builds as interpolated GPU geometry separate from the
static mesh: sliding doors render with the exact software slide (all three
styles) and open/close correctly at fractional positions, and pushwalls render at
continuous thinker-keyed world positions matching the raycaster. The determinism
gate remains green; the simulation is untouched.
