/*
** r_artscale.cpp
**
** Runtime upscaling of the game's own art, for the full-screen pages.
**
** These pages -- the menu splash, the sign-off screen -- are 320x200 art
** stretched to fill the window, which is the most visible point-sampling in the
** game: a modern display magnifies them four times or more. Running them through
** xBRZ at load time recovers the curves the artists were drawing around.
**
** Doing it here rather than shipping upscaled copies is also what keeps the
** commercial art out of this repository. The source is the player's own data
** files; nothing derived from them is distributed.
*/

#include <stdint.h>
#include <string.h>

#include "colormatcher.h"
#include "r_artscale.h"
#include "r_xbrz.h"
#include "tarray.h"
#include "textures/textures.h"
#include "v_palette.h"
#include "v_video.h"
#include "wl_def.h"

namespace
{
	// An 8-bit texture built at runtime rather than loaded from a lump.
	//
	// Unload() is deliberately a no-op. The base class contract is that pixels
	// can be dropped and rebuilt from the source lump on the next GetPixels(),
	// and there is no source lump here -- these pixels are the only copy, so
	// freeing them would hand out dangling memory. The destructor releases them.
	class FUpscaledTexture : public FTexture
	{
	public:
		// Takes ownership of `pixels`, which must be column-major, as every
		// FTexture's GetPixels() is.
		FUpscaledTexture(int w, int h, BYTE *pixels)
			: FTexture(NULL, -1), Pixels(pixels), Spans(NULL)
		{
			Width = (WORD)w;
			Height = (WORD)h;
			LeftOffset = 0;
			TopOffset = 0;
			CalcBitSize();
		}

		~FUpscaledTexture()
		{
			if(Spans)
				FreeSpans(Spans);
			delete[] Pixels;
		}

		void Unload() {}
		const BYTE *GetPixels() { return Pixels; }

		const BYTE *GetColumn(unsigned int column, const Span **spans_out)
		{
			if(column >= (unsigned)Width)
				column = (WidthMask + 1 == Width) ? (column & WidthMask) : (column % Width);
			if(spans_out != NULL)
			{
				if(Spans == NULL)
					Spans = CreateSpans(Pixels);
				*spans_out = Spans[column];
			}
			return Pixels + column*Height;
		}

	private:
		BYTE *Pixels;
		Span **Spans;
	};

	// Nearest palette entry for a 24-bit colour, cached by RGB555.
	//
	// The exact matcher is a linear scan of all 256 entries, which is nothing for
	// the handful of colours a menu picks but ruinous across a megapixel of
	// upscaled art -- xBRZ blends its inputs, so nearly every pixel is a new
	// colour needing its own search. Quantising the key to 5 bits per channel
	// bounds the work at 32768 searches however large the image, and costs
	// nothing visible: the palette's own entries are further apart than the
	// rounding this introduces.
	class PaletteCache
	{
	public:
		PaletteCache() { memset(Known, 0, sizeof(Known)); }

		BYTE Match(int r, int g, int b)
		{
			const unsigned key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
			if(!Known[key])
			{
				BYTE c = ColorMatcher.Pick(r, g, b);
				// Index 0 is the transparent key, so a pixel that matched it
				// would punch a hole in the page. Remap[0] is the palette's own
				// duplicate of colour 0 -- the same colour, but opaque.
				if(c == 0)
					c = GPalette.Remap[0];
				Entry[key] = c;
				Known[key] = 1;
			}
			return Entry[key];
		}

	private:
		BYTE Entry[32768];
		BYTE Known[32768];
	};

	struct CacheEntry
	{
		FTexture *src;
		FTexture *scaled;
		int factor;
	};
	TArray<CacheEntry> Cache;

	// Rebuilds `src` at `factor` times its authored size.
	//
	// The result has to land back in the 256-colour palette, because every 2D
	// surface in this engine is 8-bit -- so most of xBRZ's blending is quantised
	// away again. What survives is the part that matters: the reshaped edges. A
	// blended colour is lost to the nearest palette entry, but a diagonal that
	// was a staircase and is now a slope is still a slope afterwards, because
	// that is geometry rather than colour.
	FTexture *BuildUpscaled(FTexture *src, int factor)
	{
		const int sw = src->GetWidth(), sh = src->GetHeight();
		if(sw <= 0 || sh <= 0 || factor < 2)
			return NULL;
		const BYTE *const srcPixels = src->GetPixels();
		if(srcPixels == NULL)
			return NULL;

		// Column-major indices in, row-major opaque ARGB out, which is what the
		// upscaler wants.
		TArray<uint32_t> rgb((unsigned)(sw*sh));
		rgb.Resize((unsigned)(sw*sh));
		for(int x = 0;x < sw;++x)
		{
			for(int y = 0;y < sh;++y)
			{
				const PalEntry &pe = GPalette.BaseColors[srcPixels[x*sh + y]];
				rgb[y*sw + x] = 0xFF000000u | ((uint32_t)pe.r << 16) |
					((uint32_t)pe.g << 8) | (uint32_t)pe.b;
			}
		}

		// This art is dithered, and the upscaler would read each dither cell as
		// a feature worth enlarging; resolve them first.
		R_XBRZDeDither(&rgb[0], sw, sh);

		const int bw = sw*factor, bh = sh*factor;
		TArray<uint32_t> big((unsigned)(bw*bh));
		big.Resize((unsigned)(bw*bh));
		R_XBRZScaleARGB(&rgb[0], sw, sh, factor, &big[0], /*hasAlpha=*/false);

		PaletteCache pal;
		BYTE *const out = new BYTE[(size_t)bw*bh];
		for(int y = 0;y < bh;++y)
		{
			for(int x = 0;x < bw;++x)
			{
				const uint32_t c = big[y*bw + x];
				out[x*bh + y] = pal.Match((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF);
			}
		}
		return new FUpscaledTexture(bw, bh, out);
	}
}

FTexture *R_UpscaledArt(FTexture *src)
{
	if(src == NULL)
		return src;

	// Sized to the screen it will be stretched onto, so the upscale does the
	// enlarging rather than the blitter.
	const int factor = R_XBRZAutoFactor(src->GetWidth(), src->GetHeight(),
		SCREENWIDTH, SCREENHEIGHT);
	if(factor < 2)
		return src;	// nothing to gain; the window is no bigger than the art

	for(unsigned int i = 0;i < Cache.Size();++i)
	{
		if(Cache[i].src != src)
			continue;
		if(Cache[i].factor == factor)
			return Cache[i].scaled;
		// Same page, different screen: rebuild in place rather than accumulating
		// a copy per resolution the player has visited.
		FTexture *const rebuilt = BuildUpscaled(src, factor);
		if(rebuilt == NULL)
			return src;
		delete Cache[i].scaled;
		Cache[i].scaled = rebuilt;
		Cache[i].factor = factor;
		return rebuilt;
	}

	FTexture *const built = BuildUpscaled(src, factor);
	if(built == NULL)
		return src;
	CacheEntry entry = { src, built, factor };
	Cache.Push(entry);
	return built;
}
