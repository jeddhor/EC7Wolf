/*
** r_xbrz.h
**
** Engine-side wrapper around the vendored xBRZ upscaler (deps/xbrz).
*/

#ifndef __R_XBRZ_H__
#define __R_XBRZ_H__

#include <stdint.h>

#include "wl_def.h"

struct PalEntry;

// Widest factor xBRZ itself supports. vid_xbrz is clamped to this.
extern const int XBRZ_MAX_FACTOR;

// Factor to actually use for a srcW x srcH frame shown in a dstW x dstH window,
// honouring vid_xbrz: 0 means "do not scale" and is returned both when the
// setting is off and when the chosen factor would not fit the pixel budget.
// vid_xbrz == 1 asks for the automatic factor; see R_XBRZAutoFactor.
int R_XBRZFactor(int srcW, int srcH, int dstW, int dstH);

// The factor that best fills a dstW x dstH window from a srcW x srcH frame.
// 1 means the window is not big enough for upscaling to buy anything.
int R_XBRZAutoFactor(int srcW, int srcH, int dstW, int dstH);

// Expand an 8-bit indexed frame through `pal` and upscale it. Returns
// (srcW*factor) x (srcH*factor) pixels in 0xAARRGGBB order, owned by this
// module and valid only until the next call. NULL if the arguments are unusable.
const uint32_t *R_XBRZScaleIndexed(const BYTE *src, int srcPitch, int srcW, int srcH,
	const PalEntry *pal, int factor);

// Upscale a caller-owned 0xAARRGGBB image into caller-owned storage, which must
// hold (srcW*factor) x (srcH*factor) pixels. `hasAlpha` picks the ARGB rule set,
// which reads the alpha channel rather than assuming the image is opaque.
void R_XBRZScaleARGB(const uint32_t *src, int srcW, int srcH, int factor,
	uint32_t *dst, bool hasAlpha);

// Drop the scratch buffers. Called at shutdown and on a video mode change, so a
// full-screen frame's worth of scratch is not held for a mode that no longer
// exists.
void R_XBRZFreeScratch();

#endif
