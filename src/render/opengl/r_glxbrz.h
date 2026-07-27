#ifndef __R_GLXBRZ_H__
#define __R_GLXBRZ_H__

// xBRZ image scaling for the OpenGL present path (renderer redesign Phase 11).
//
// The software path filters the finished 8-bit frame on the CPU, in
// SDLFB::PresentXBRZ. Under GL there is no such frame to reach for: the
// compositor resolves the 8-bit 2D layer and the rendered world straight into
// the window, and pulling that back to system memory to run the CPU filter
// would stall the pipeline once per frame to do work the GPU is far better at.
//
// So the filter is a shader instead, and the compositor is redirected into an
// offscreen buffer at the game's own resolution to give it something to read.
// The pass structure mirrors the CPU implementation exactly (deps/xbrz):
// preprocessing decides, per source pixel, which of its four corners want
// blending, and the scaling pass acts on that decision. Splitting them the same
// way is not just fidelity -- preprocessing is the expensive half, and running
// it per source pixel rather than per output pixel is where the shader wins its
// cost back at the higher factors.
//
// Everything here runs on the game window's context, which SDLFB has made
// current before calling R_GLLivePresent.

// Redirect compositing into the offscreen buffer, sized fw x fh (the 8-bit
// frame), and leave it bound with the viewport set. Returns the scale factor in
// force, or 0 when scaling is off, has no room to work in, or could not
// allocate -- in which case nothing was bound and the caller composites to the
// window as usual. Every nonzero return must be paired with R_GLXBRZEnd.
int R_GLXBRZBegin(int fw, int fh, int drawableW, int drawableH);

// Scale the composited frame into the window. Restores the default framebuffer
// whether or not the scaling passes ran, so it is also the correct way to bail
// out of a present that gave up after R_GLXBRZBegin succeeded.
void R_GLXBRZEnd(int drawableW, int drawableH);

// Free every GL object this module owns. The owning context must be current.
void R_GLXBRZShutdown();

// Headless verification: with a path armed, the next 2D-only present writes the
// shader's output and the CPU filter's output for the same frame, as
// PATH-gl.png and PATH-cpu.png. Restricted to frames with no rendered world
// because that is the only case where the two paths are fed identical pixels --
// GL and software do not render the 3D view to the last level, so comparing a
// gameplay frame would measure that difference instead of this one.
void R_GLXBRZArmParityCapture(const char *path);
void R_GLXBRZWriteParity(const unsigned char *mem, int pitch, int fw, int fh,
	bool haveWorld);

#endif
