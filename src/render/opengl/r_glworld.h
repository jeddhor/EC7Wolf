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

#endif
