# Phase 3 — Fixed-step timing + motion interpolation

Decouples frame pacing from the 70 Hz simulation and interpolates actor and
camera transforms between simulation tics, on the software renderer. This is the
highest-value slice before any GPU work: it proves the game/render boundary and
delivers smoother motion with no new backend.

Interpolation is **renderer-independent** and proven here on the software
renderer, exactly as the redesign requires, so the OpenGL backend inherits it.

## Timing

`wl_play.cpp` gains a decoupled frame-pacing path (`CalcTicsInterpolated`)
selected by `g_interpFrameTiming`, which the gameplay `PlayLoop` enables from
`r_interpolate` and disables on exit (intermission/animation loops keep the
legacy blocking `CalcTics`). It:

* measures elapsed time with `SDL_GetPerformanceCounter` (sub-millisecond),
* accumulates whole 70 Hz tics (0..`MAXTICS`, surplus dropped to avoid spiral),
* exposes the residual as `R_GetInterpolationAlpha()` in [0,1),
* honors `vid_maxfps` (0 = unlimited) by folding the cap wait into the elapsed
  measurement.

Crucially the loop now renders **every** frame, including frames where zero
simulation tics are due — those are pure interpolation frames.

## Interpolation

`render/r_interpolation.{h,cpp}` plus non-serialized history on `AActor`
(`renderPrev*`, `renderCur*`, `renderInterpValid`):

* `BeginTic()` (before each tic) shifts current -> previous for all actors.
* `EndTic()` (after each tic) captures the post-tic transform as current; an
  actor whose history is still invalid (fresh spawn / post-teleport) gets
  previous = current so it renders statically instead of smearing.
* `Apply(alpha)` / `Restore()` bracket the render: the renderer reads
  interpolated `x/y/z/angle/pitch` (the camera is an actor, so
  `CalcViewVariables` interpolates for free), then the authoritative simulation
  state is restored. `renderCur*` is the verbatim post-tic value, so Restore is
  exact.
* `R_LerpAngle` uses shortest-arc binary-angle interpolation (359deg -> 1deg
  travels through 0deg). Unit-verified.

Reset cases handled: spawn (`AActor::Init` sets `renderInterpValid = false`) and
teleport (`AActor::Teleport` invalidates). Pauses render statically because
previous == current while no tics run.

Cadence-sensitive per-frame work (`UpdatePaletteShifts`, `StatusBar->Tick`) is
gated on `tics > 0`, reproducing the original per-tic-batch rate so damage/bonus
fades and HUD animation do not speed up at high refresh rates.

## New settings

`r_interpolate` (master, default on), `r_interpolate_camera`,
`r_interpolate_actors`, `r_interpolate_dynamicwalls` (consumed in Phase 7),
`r_latelatch_mouse` (default off; full late-latch is a later refinement), and
`vid_maxfps`. All persist to the config.

## Determinism — the hard gate

Interpolated transforms are render-only, restored before the next tic, and never
observed by the checksum (which is folded at `EndTic`, before substitution).
`tools/test_corridor7_determinism.sh` now asserts two properties, both passing:

* **Run-to-run determinism**: identical runs -> identical checksum
  (`3402c83a`, MAP01 seed 12345, 400 tics).
* **Interpolation invariant**: an interpolation-OFF run produces the *identical*
  checksum as interpolation-ON. Interpolation does not change the simulation.

## Known scope boundaries (per the redesign)

Not interpolated here (intentionally): weapon/view bob, sprite animation frames,
palette modes, and dynamic-wall (door/pushwall) positions — the last lands in
Phase 7 via `r_interpolate_dynamicwalls`. Full mouse-look late-latch is deferred.
In the headless Xvfb test environment the software renderer is slower than
70 Hz, so the visible >70 Hz benefit is not observable there, but the decoupling
and determinism are.

## Exit gate — met

Simulation stays 70 Hz and bit-identical (interpolation on or off); frame pacing
is decoupled and frame-limited; camera and actors interpolate; teleports, loads,
and pauses reset cleanly (no smear).
