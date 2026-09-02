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

	// Nearest palette entry for a 24-bit color, cached by RGB555.
	//
	// The exact matcher is a linear scan of all 256 entries, which is nothing for
	// the handful of colors a menu picks but ruinous across a megapixel of
	// upscaled art -- xBRZ blends its inputs, so nearly every pixel is a new
	// color needing its own search. Quantising the key to 5 bits per channel
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
				// duplicate of color 0 -- the same color, but opaque.
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

	// Composed tiled pages, kept so the tiling is done once rather than per
	// frame. These are the *source* handed to R_UpscaledArt, which caches the
	// upscale of them separately.
	struct TiledEntry
	{
		FTexture *tile;
		FTexture *page;
		int w, h;
	};
	TArray<TiledEntry> TiledCache;

	// Rebuilds `src` at `factor` times its authored size.
	//
	// The result has to land back in the 256-color palette, because every 2D
	// surface in this engine is 8-bit -- so most of xBRZ's blending is quantised
	// away again. What survives is the part that matters: the reshaped edges. A
	// blended color is lost to the nearest palette entry, but a diagonal that
	// was a staircase and is now a slope is still a slope afterward, because
	// that is geometry rather than color.
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

FTexture *R_UpscaledTiledPage(FTexture *tile, int w, int h)
{
	if(tile == NULL || w <= 0 || h <= 0)
		return tile;

	const int tw = tile->GetWidth();
	const int th = tile->GetHeight();
	if(tw <= 0 || th <= 0)
		return tile;

	// `w` and `h` are the page in the 320x200 space the caller lays out in, but
	// the tile is copied by its real texels -- and a hires replacement has four
	// times as many of those per virtual pixel. Composing at the tile's own
	// density keeps the pattern repeating the number of times the layout asks
	// for; composing at 320x200 would show a quarter of the tiles at four times
	// the size.
	const int sw = tile->GetScaledWidth(), sh = tile->GetScaledHeight();
	const bool tileIsHires = sw > 0 && sh > 0 && (tw > sw || th > sh);
	if(sw > 0 && sh > 0)
	{
		w = (int)(((int64_t)w * tw) / sw);
		h = (int)(((int64_t)h * th) / sh);
	}

	// Keyed on the tile and the page size, not on the screen: the composed page
	// is resolution-independent, and R_UpscaledArt below does its own rebuild
	// when the window changes.
	for(unsigned int i = 0;i < TiledCache.Size();++i)
	{
		if(TiledCache[i].tile == tile && TiledCache[i].w == w &&
			TiledCache[i].h == h)
			return tileIsHires ? TiledCache[i].page
				: R_UpscaledArt(TiledCache[i].page);
	}

	const BYTE *const src = tile->GetPixels();
	if(src == NULL)
		return tile;

	// Column-major, as every FTexture's pixels are.
	BYTE *const pixels = new BYTE[(size_t)w * h];
	for(int x = 0; x < w; ++x)
	{
		const BYTE *const col = src + (size_t)(x % tw) * th;
		BYTE *const dst = pixels + (size_t)x * h;
		for(int y = 0; y < h; ++y)
			dst[y] = col[y % th];
	}

	FTexture *const page = new FUpscaledTexture(w, h, pixels);
	TiledEntry entry = { tile, page, w, h };
	TiledCache.Push(entry);

	// A page composed from an already-upscaled tile is not run through the
	// filter again: it is at the pack's resolution, not the game's, and xBRZ has
	// nothing left to find in art a network has already enlarged.
	FTexture *const scaled = tileIsHires ? page : R_UpscaledArt(page);
	// Once per tile per page size, so this is a handful of lines a run rather
	// than noise -- and it is the only way to tell from a log whether a backdrop
	// was actually enlarged or quietly handed back at its authored size.
	Printf("Art: tiled %dx%d backdrop from a %dx%d tile -> %dx%d.\n",
		w, h, tw, th, scaled->GetWidth(), scaled->GetHeight());
	return scaled;
}

FTexture *R_UpscaledArt(FTexture *src)
{
	if(src == NULL)
		return src;

	// Art that is already a hires replacement is handed straight back. The two
	// upscalers are alternatives, not a pipeline: xBRZ looks for the staircases
	// that point sampling leaves behind, and there are none in a page a network
	// has already redrawn four times the size.
	if(src->GetWidth() > src->GetScaledWidth() ||
		src->GetHeight() > src->GetScaledHeight())
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
