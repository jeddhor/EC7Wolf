# Phase 4 — OpenGL device, context, presentation + indexed-palette pipeline

Brings up the OpenGL backend's foundation: an SDL GL 3.3 core context, a GLSL
compile/link helper, presentation/readback, and — most importantly — the
**indexed-texture → colormap → palette** GPU pipeline that is the fidelity core
of the whole hardware renderer. Verified headlessly.

The game stays fully playable on the software renderer throughout: selecting
`opengl` before world rendering exists falls back cleanly to software.

## What landed

* Build: `ECWOLF_RENDERER_OPENGL` defaults ON and links OpenGL + **libepoxy**
  (lazy GL loader, no init call). If the dependency is missing the backend is
  disabled with a warning rather than failing the build.
* `render/opengl/r_glshader.{h,cpp}` — compile/link a program with full log
  reporting.
* `render/opengl/r_gldevice.{h,cpp}` — `GLDevice`: SDL GL window+context (core
  profile, optional hidden window for headless), vsync, viewport/clear/present,
  resize, fullscreen toggle, capability logging, and RGB framebuffer readback
  (flipped top-down) for screenshots.
* `render/opengl/r_glpalette.{h,cpp}` — `GLIndexedPipeline`: R8UI index
  textures, a 256×1 RGB palette texture, a 256×N R8UI colormap texture, the
  palette-lookup shader, and an attributeless fullscreen-triangle draw. Nearest
  filtering only; palette indices are never linearly filtered. The fragment
  shader resolves `index -> colormap[shadeRow] -> palette RGB`.
* `render/opengl/r_glrenderer.{h,cpp}` — `OpenGLRenderer` backend (defers to
  software until Phase 5) and `R_GLRunSelfTest()`.
* `--gltest [out.ppm]` main-entry hook (runs before the game window, headless
  safe) and `tools/test_gl_selftest.sh`.

## Self-test (the verification)

`R_GLRunSelfTest` creates a hidden GL context, uploads a synthetic 256-entry
palette and a 256-wide index image (column *x* holds index *x*), renders it
through the palette shader into an offscreen FBO, reads it back, and asserts
every column's resolved RGB equals `palette[x]` exactly (±1). Result on the CI
environment (Xvfb + Mesa llvmpipe, OpenGL 4.5 core):

```
GL: version '4.5 (Core Profile) Mesa ...' renderer 'llvmpipe' glsl '4.50'
GL self-test: PASS - indexed-palette lookup exact for all 256 indices.
```

This proves the exact-index GPU pipeline works end to end — the single biggest
technical risk of the hardware renderer (palette fidelity) — before any world
geometry exists.

## Why the backend defers to software for now

Making GL the *live* game window requires refactoring SDL window ownership out
of `SDLFB` and porting the 2D/HUD system, which is scoped to Phases 5/10. Until
then `OpenGLRenderer::Init()` reports readiness and returns false so the
selector falls back to software — exercised and verified:

```
OpenGL backend: device + indexed-palette pipeline ready; world rendering pending (Phase 5+). Deferring to software.
Renderer: OpenGL renderer failed to initialize; falling back to software.
Renderer: using software renderer.
```

## Exit gate — met

OpenGL initializes (3.3 core requested, 4.5 obtained), renders, reads back a
screenshot, resolves the indexed-palette test image exactly, and falls back
cleanly to software. Resize/fullscreen/vsync are implemented on `GLDevice`
(exercised once world presentation is wired). Determinism gate remains green.
