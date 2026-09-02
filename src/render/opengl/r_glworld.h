#ifndef __R_GLWORLD_H__
#define __R_GLWORLD_H__

// GL static-world renderer + offscreen capture (renderer redesign Phase 5).
//
// Builds the static opaque world mesh from the live map, renders it through a
// camera calibrated to ECWolf's view (position/angle/pitch/FOV) into an
// offscreen framebuffer, and (optionally) writes the result as a PPM. This is
// the verifiable, non-invasive bring-up of GL world rendering before the live
// window ownership refactor.
//
// Returns true on success. Safe to call while the software renderer owns the
// game window: it creates its own hidden GL context for the offscreen render.
bool R_GLWorldCapture(const char *outPath);

// Full-frame composite capture (renderer redesign Phase 10). Renders the GL 3D
// world into the view sub-rectangle and composites the engine's live 8-bit 2D
// layer (player weapon, HUD/status bar, menus, text) over it as an indexed
// overlay -- the view region transparent except where the weapon (or any 2D
// drawn over the world) is opaque -- producing a complete playable frame the
// size of the software screenshot. Writes the result as a PPM. Like
// R_GLWorldCapture it owns its own hidden GL context and does not disturb the
// software renderer that owns the game window.
bool R_GLFrameCapture(const char *outPath);

// --- Phase 10 live present (GPU-owned game window) ---------------------------
//
// These drive the live GL renderer that composites directly to the game window
// created (GL-capable) by SDLFB when vid_renderer selects OpenGL. They run on
// that window's context, which SDLFB makes current before calling Present.

// True when the config/CLI selects the OpenGL renderer. Read by SDLFB to decide
// whether to create a GL-capable window and present through GL.
bool R_GLLiveWantPresent();

// Per-frame GL timing report (vid_glprofile). Call once per presented frame,
// after the swap. No-op unless profiling is on.
void R_GLProfileEndFrame();

// Reduced software frame + GL world render for one gameplay frame. Called from
// OpenGLRenderer::RenderScene (inside the interpolation Apply/Restore that wraps
// the software path too).
void R_GLLiveRenderScene();

// Draw 2D that lands over the 3D view after the world pass (Corridor 7's
// top-message / power-chamber overlay) and record which texels it painted, so
// the compositor keeps them opaque even when they are drawn in the key color
// (e.g. the top message's black drop shadow). `draw` is invoked more than once
// and must be a pure drawing function. Reached from game code through
// IRenderer::DrawViewOverlay; the software backend just calls `draw`.
void R_GLLiveDrawViewOverlay(void (*draw)());

// Composite the last rendered world (if any) and the engine's 8-bit 2D layer
// into the default framebuffer. Called from SDLFB::Update with the context
// current; the caller swaps buffers afterward. drawableW/H are the window's GL
// drawable size (pass <= 0 to use fw/fh).
void R_GLLivePresent(const unsigned char *mem, int pitch, int fw, int fh,
	int drawableW, int drawableH);

// Free all live GL resources (called from OpenGLRenderer::Shutdown).
void R_GLLiveShutdown();

// Drop every uploaded index/opacity texture and the cached static geometry that
// points at them. The world caches art by texture id and holds the upload for
// the run, so anything that changes what an id resolves to -- switching the
// upscaled asset pack on or off -- has to say so here or the old pixels stay on
// screen until the next map. Safe to call when the backend is not live.
void R_GLLiveInvalidateTextures();

// SDLFB reports whether it created a GL context on the game window; the OpenGL
// backend goes live only when this is true (else it falls back to software).
void R_GLLiveSetContextActive(bool active);
bool R_GLLiveContextActive();

// Headless verification: while armed with a path, every present keeps a copy of
// the composited frame; R_GLLiveWriteCapture() writes the latest to that path.
// The capture harness arms once and writes at its chosen gameplay frame.
void R_GLLiveArmCapture(const char *path, int frame);
void R_GLLiveWriteCapture();

#endif
