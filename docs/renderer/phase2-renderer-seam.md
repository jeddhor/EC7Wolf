# Phase 2 — Renderer seam (IRenderer + SoftwareRenderer)

Introduces the backend-neutral renderer boundary. Game code no longer calls the
software renderer directly; it calls through `IRenderer`. The software backend
is a thin pass-through, so `vid_renderer software` is behaviorally identical to
the pre-seam engine.

## What landed

* `src/render/r_renderer.{h,cpp}`
  * `IRenderer` interface: `Init` / `Shutdown` / `RenderScene` / `Type` / `Name`.
  * Global `IRenderer *Renderer`.
  * `R_InitRendererBackend()` resolves the `vid_renderer` config value against
    the compiled-in `ECWOLF_RENDERER_*` backends and **always** falls back to
    software — when the requested backend is not compiled in, or when its
    `Init()` fails. `R_ShutdownRendererBackend()` tears it down.
* `src/render/software/r_swrenderer.{h,cpp}`
  * `SoftwareRenderer` whose `RenderScene()` calls the unchanged
    `ThreeDRefresh()`. All existing software render functions are untouched.
* Wiring
  * `wl_main.cpp` `InitGame`: `R_InitRendererBackend()` then
    `atterm(R_ShutdownRendererBackend)` (LIFO, so it runs before
    `I_ShutdownGraphics`).
  * `wl_play.cpp` `R_RenderView`: the single `ThreeDRefresh()` call site now
    calls `Renderer->RenderScene()`.
* `src/CMakeLists.txt`: the two new sources added to the engine.

## Design note

Phase 2 deliberately wraps the *entire* legacy 3D path in one `RenderScene()`
call rather than decomposing it into the design doc's finer
`BeginFrame`/`RenderWorld`/`RenderViewModel`/`Begin2D`/`EndFrame` methods. That
decomposition is where the OpenGL backend needs seams (Phases 4+), and doing it
now would risk behavior changes for no present benefit. The interface grows as
the hardware backend requires it.

## Verification

* Builds cleanly at C++17.
* Log shows `Renderer: using software renderer.` — the seam is live.
* Determinism gate passes with an unchanged checksum (`3402c83a`), proving the
  simulation is untouched by the indirection.
* The 3D view still renders (640×480 golden screenshot produced).

Byte-exact golden-screenshot parity is intentionally deferred to Phase 3:
`RenderScene()` is the same `ThreeDRefresh()` function, so identical input
yields identical output, but the current wall-clock loop maps a given rendered
frame number to a non-deterministic simulation tic. Once the fixed-step loop
lands, `--capture-frame N` becomes byte-stable and screenshot diffs become a
usable gate.

## Exit gate — met

`vid_renderer software` is visually and behaviorally unchanged; rendering is
routed through `IRenderer`; a failed/absent hardware backend falls back to
software.
