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

#endif
