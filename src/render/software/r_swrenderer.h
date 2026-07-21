#ifndef __R_SWRENDERER_H__
#define __R_SWRENDERER_H__

#include "render/r_renderer.h"

// Reference software renderer. Wraps the historical CPU raycaster path and is
// always available. Returns a heap-allocated backend owned by the caller.
IRenderer *R_CreateSoftwareRenderer();

#endif
