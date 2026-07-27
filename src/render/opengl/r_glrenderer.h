#ifndef __R_GLRENDERER_H__
#define __R_GLRENDERER_H__

#include "render/r_renderer.h"

// OpenGL renderer backend (renderer redesign Phase 4+). Create the backend for
// the renderer selector. World rendering is filled in from Phase 5 onward; for
// now Init() reports status and defers gameplay to the software renderer.
IRenderer *R_CreateOpenGLRenderer();

// Headless-capable self-test of the GL device + indexed-palette pipeline.
// Creates a hidden GL context, renders a known index image through the palette
// shader into an offscreen buffer, and verifies the resolved RGB matches the
// palette exactly. Writes a PPM to outPath when non-NULL. Returns true on pass.
bool R_GLRunSelfTest(const char *outPath);

// Can this machine give out a GL 3.3 core context at all? Answered by creating
// and destroying a hidden window, cached for the rest of the run. Must be asked
// before the game's window is created -- see the definition for why.
bool R_GLProbeAvailable();

#endif
