# Phase 1 — C++17 build modernization + renderer selection plumbing

Pure build/config change. No runtime behavior changes; the simulation checksum
is unchanged (`3402c83a` for the MAP01 gate).

## What landed

* `src/CMakeLists.txt`: engine `CXX_STANDARD` raised from 98 to 17 with
  `CXX_STANDARD_REQUIRED ON` (compiles as `-std=gnu++17`).
* Top-level `CMakeLists.txt`: renderer-backend options
  `ECWOLF_RENDERER_SOFTWARE` (ON, and required to stay ON — it is the reference
  path), `ECWOLF_RENDERER_OPENGL` (OFF until Phase 4), `ECWOLF_RENDERER_VULKAN`
  (OFF). Each maps to an `ECWOLF_RENDERER_*=1` compile definition on the engine
  target.
* `vid_renderer` config setting (`"software" | "opengl" | "vulkan"`), declared in
  `c_cvars.h`, defined/loaded/saved in `c_cvars.cpp` following the existing
  `Vid_*` config-global pattern, persisted as `Vid_Renderer` in the config file.
  It is data-only for now; the Phase 2 renderer seam consumes it.

## Pre-flight compatibility scan

Before flipping the standard, the tree was scanned for constructs C++17 *removes*
(not merely deprecates):

* `register` storage class — none (only a log string and a comment matched).
* Non-empty dynamic exception specifications `throw(T)` — none. The `throw()`
  specs in `dobject.h` are all empty, which stays legal in C++17 (removed only
  in C++20).
* `std::auto_ptr`, `unary_function`/`binary_function`, `bind1st`/`bind2nd`,
  `mem_fun`, `ptr_fun` — none.

The build has no `-Werror`, so deprecation warnings do not break it.

## Exit gate — met

* Full engine builds cleanly at C++17 (gcc 15.2).
* Corridor 7 starts, enters MAP01, and runs; determinism gate passes with an
  unchanged checksum.
* Only the software renderer exists and is selected.
