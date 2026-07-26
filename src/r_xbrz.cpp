/*
** r_xbrz.cpp
**
** Engine-side wrapper around the vendored xBRZ upscaler (deps/xbrz).
**
** xBRZ is a "scale by rules" filter: it looks at each 5x5 neighbourhood of the
** source and decides whether a step in the pixels is a genuine hard edge or a
** diagonal that was forced into a staircase by the low resolution, then draws
** the latter as a smooth slope. On art authored at 320x200 that recovers the
** curves the original artists were drawing around, which plain point sampling
** cannot do and bilinear filtering only blurs.
**
** The filter works in RGB, so it can only run once the frame has left index
** space -- which is exactly why it lives here at presentation time rather than
** on the textures. Corridor 7 animates its palette constantly (the visor modes
** recolour the whole screen, indices 208-239 cycle, and 15/254 are reserved for
** the lamps), so a texture cached as RGB would freeze whatever palette happened
** to be current when it was built. Filtering the finished frame keeps every one
** of those effects intact for free: they have already been resolved into the
** pixels by the time this code sees them.
*/

#include <stdint.h>
#include <math.h>
#include <thread>
#include <vector>

#include "c_cvars.h"
#include "r_xbrz.h"
#include "tarray.h"
#include "templates.h"
#include "v_palette.h"
#include "zdoomsupport.h"

#include "xbrz.h"

const int XBRZ_MAX_FACTOR = xbrz::SCALE_FACTOR_MAX;

// Ceiling on the upscaled frame, in pixels. A factor is stepped down until it
// fits rather than refused outright, so an ambitious setting on a small machine
// degrades to a lower factor instead of silently turning the feature off. 64
// megapixels is roughly 6x a 1440p frame -- far past anything sensible, so this
// only ever catches a pathological combination of resolution and factor.
static const int64_t kMaxScaledPixels = 64ll * 1024 * 1024;

// Rows per work item. xBRZ reads two rows either side of a slice, so tiny
// slices repeat that overlap often enough to lose what the thread gained;
// upstream suggests at least 8-16.
static const int kSliceRows = 16;

static TArray<uint32_t> ScratchSrc;
static TArray<uint32_t> ScratchDst;

int R_XBRZAutoFactor(int srcW, int srcH, int dstW, int dstH)
{
	if(srcW <= 0 || srcH <= 0 || dstW <= 0 || dstH <= 0)
		return 1;

	// Match the scaled frame to the window by area rather than by width or
	// height alone, so a letterboxed or pillarboxed window picks the factor that
	// fits the axis actually doing the constraining.
	const double area = ((double)dstW * dstH) / ((double)srcW * srcH);
	int factor = (int)(sqrt(area) + 0.5);
	return clamp(factor, 1, XBRZ_MAX_FACTOR);
}

int R_XBRZFactor(int srcW, int srcH, int dstW, int dstH)
{
	if(vid_xbrz <= 0 || srcW <= 0 || srcH <= 0)
		return 0;

	int factor = vid_xbrz == 1
		? R_XBRZAutoFactor(srcW, srcH, dstW, dstH)
		: clamp((int)vid_xbrz, 2, XBRZ_MAX_FACTOR);

	while(factor > 1 &&
		(int64_t)srcW * factor * (int64_t)srcH * factor > kMaxScaledPixels)
		--factor;

	// 1x is what the filter degrades to when there is no room to grow into;
	// running it at that point would cost a full frame of work to produce the
	// frame we already have.
	return factor > 1 ? factor : 0;
}

// Runs xbrz::scale over [0,srcHeight) split into row slices across the hardware
// threads. Slices are half-open and non-overlapping, which is the condition
// upstream requires for this to be safe; each thread reads two rows outside its
// own slice but writes only within it.
static void ScaleThreaded(int factor, const uint32_t *src, uint32_t *dst,
	int srcW, int srcH, xbrz::ColorFormat fmt)
{
	static unsigned int hwThreads = 0;
	if(hwThreads == 0)
	{
		hwThreads = std::thread::hardware_concurrency();
		if(hwThreads == 0)
			hwThreads = 1;
	}

	const int slices = (srcH + kSliceRows - 1) / kSliceRows;
	const int threads = MIN((int)hwThreads, slices);
	if(threads <= 1)
	{
		xbrz::scale((size_t)factor, src, dst, srcW, srcH, fmt);
		return;
	}

	// Contiguous bands rather than round-robin slices: a band is one call into
	// xbrz::scale, so the per-slice edge overhead is paid once per thread
	// instead of once per 16 rows.
	std::vector<std::thread> pool;
	pool.reserve((size_t)threads - 1);
	for(int t = 1; t < threads; ++t)
	{
		const int first = (int)((int64_t)srcH * t / threads);
		const int last = (int)((int64_t)srcH * (t+1) / threads);
		if(first >= last)
			continue;
		pool.push_back(std::thread([=]() {
			xbrz::scale((size_t)factor, src, dst, srcW, srcH, fmt,
				xbrz::ScalerCfg(), first, last);
		}));
	}
	// The calling thread takes the first band rather than idling on the join.
	xbrz::scale((size_t)factor, src, dst, srcW, srcH, fmt, xbrz::ScalerCfg(),
		0, (int)((int64_t)srcH / threads));
	for(size_t i = 0; i < pool.size(); ++i)
		pool[i].join();
}

const uint32_t *R_XBRZScaleIndexed(const BYTE *src, int srcPitch, int srcW, int srcH,
	const PalEntry *pal, int factor)
{
	if(src == NULL || pal == NULL || srcW <= 0 || srcH <= 0 ||
		factor < 2 || factor > XBRZ_MAX_FACTOR)
		return NULL;

	// xbrz::ColorFormat::RGB ignores the top 8 bits, and SDL's ARGB8888 wants
	// them set, so the frame is built opaque once here and stays valid for both.
	uint32_t lut[256];
	for(int i = 0; i < 256; ++i)
		lut[i] = 0xFF000000u | ((uint32_t)pal[i].r << 16) |
			((uint32_t)pal[i].g << 8) | (uint32_t)pal[i].b;

	ScratchSrc.Resize((unsigned)(srcW * srcH));
	uint32_t *const rgb = &ScratchSrc[0];
	for(int y = 0; y < srcH; ++y)
	{
		const BYTE *const row = src + (size_t)y * srcPitch;
		uint32_t *const out = rgb + (size_t)y * srcW;
		for(int x = 0; x < srcW; ++x)
			out[x] = lut[row[x]];
	}

	ScratchDst.Resize((unsigned)(srcW * factor * srcH * factor));
	uint32_t *const dst = &ScratchDst[0];
	ScaleThreaded(factor, rgb, dst, srcW, srcH, xbrz::ColorFormat::RGB);
	return dst;
}

void R_XBRZScaleARGB(const uint32_t *src, int srcW, int srcH, int factor,
	uint32_t *dst, bool hasAlpha)
{
	if(src == NULL || dst == NULL || srcW <= 0 || srcH <= 0 ||
		factor < 2 || factor > XBRZ_MAX_FACTOR)
		return;
	ScaleThreaded(factor, src, dst, srcW, srcH,
		hasAlpha ? xbrz::ColorFormat::ARGB : xbrz::ColorFormat::RGB);
}

void R_XBRZFreeScratch()
{
	ScratchSrc.Clear();
	ScratchSrc.ShrinkToFit();
	ScratchDst.Clear();
	ScratchDst.ShrinkToFit();
}
