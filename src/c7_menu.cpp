/*
** c7_menu.cpp
**
** The Corridor 7 menu shell. See c7_menu.h for why this is a skin rather than a
** menu hierarchy.
**
** Layout is expressed as fractions of the real screen rather than in the
** engine's 320x200 virtual space. Text is rasterised by v_ttf at the exact
** pixel size the current resolution wants, so the menu stays crisp at 4K; the
** virtual space would have quantised it to 320x200 and thrown that away.
*/

#include "c7_menu.h"

#include "wl_def.h"
#include "wl_iwad.h"
#include "m_classes.h"
#include "r_xbrz.h"
#include "tarray.h"
#include "v_palette.h"
#include "v_video.h"
#include "colormatcher.h"
#include "v_ttf.h"
#include "textures/textures.h"
#include "w_wad.h"
#include "zstring.h"

namespace
{
	// Design reference, matching the approved mock-ups. Everything below is a
	// fraction of the real screen derived from these, so the proportions hold at
	// any aspect ratio instead of only at 16:10.
	const double kDesignW = 1280.0, kDesignH = 800.0;
	const double kLabelX  = 786.0 / kDesignW;	// label column left edge
	const double kValueX  = 1215.0 / kDesignW;	// value column right edge
	const double kFadeIn  = 0.38;	// art fully opaque left of here
	const double kFadeOut = 0.66;	// fully black right of here

	// Accent colours land on palette entries the game already uses: the status
	// bar's amber readouts and its greys.
	const int kAmberR = 255, kAmberG = 190, kAmberB = 40;
	const int kAmberDimR = 150, kAmberDimG = 108, kAmberDimB = 20;
	const int kWhiteR = 222, kWhiteG = 222, kWhiteB = 222;
	const int kGreyR = 150, kGreyG = 150, kGreyB = 150;
	const int kDimR = 96, kDimG = 96, kDimB = 96;

	FTTFont *g_regular = NULL;
	FTTFont *g_bold = NULL;
	bool     g_fontsTried = false;

	int Scaled(double designPx)
	{
		const int px = (int)(designPx * SCREENHEIGHT / kDesignH + 0.5);
		return px < 1 ? 1 : px;
	}

	bool LoadFonts()
	{
		if(!g_fontsTried)
		{
			g_fontsTried = true;
			g_regular = V_GetTTFont("fonts/c7menu.ttf");
			g_bold = V_GetTTFont("fonts/c7menub.ttf");
		}
		return g_regular != NULL && g_bold != NULL;
	}

	// An 8-bit texture built at runtime rather than loaded from a lump.
	//
	// Unload() is deliberately a no-op. The base class contract is that the
	// pixels can be dropped and regenerated from the source lump on the next
	// GetPixels(), and there is no source lump here -- the pixels are the only
	// copy, so freeing them would hand out dangling memory. They are released in
	// the destructor instead.
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
	// the handful of colours the menu chrome picks but ruinous for a megapixel of
	// upscaled art -- xBRZ blends its inputs, so nearly every pixel is a new
	// colour needing its own search. Quantising the key to 5 bits per channel
	// bounds the work at 32768 searches no matter how large the image, and costs
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
				// would punch a hole in the art. Remap[0] is the palette's own
				// duplicate of colour 0, which is the same colour and opaque.
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

	// Rebuilds the splash art at `factor` times its authored size.
	//
	// The result has to land back in the 256-colour palette, because every 2D
	// surface in this engine is 8-bit -- so most of xBRZ's blending is quantised
	// away again. What survives is the part that matters: the reshaped edges. A
	// blended colour is lost to the nearest palette entry, but a diagonal that
	// was a staircase and is now a slope is still a slope afterwards, because
	// that is geometry rather than colour.
	FTexture *BuildUpscaledBackdrop(FTexture *src, int factor)
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

		// The splash is dithered through its shadows, and the upscaler would read
		// each dither cell as a feature to enlarge; resolve them first.
		R_XBRZDeDither(&rgb[0], sw, sh);

		const int bw = sw*factor, bh = sh*factor;
		TArray<uint32_t> big((unsigned)(bw*bh));
		big.Resize((unsigned)(bw*bh));
		R_XBRZScaleARGB(&rgb[0], sw, sh, factor, &big[0], /*hasAlpha=*/false);

		PaletteCache cache;
		BYTE *const out = new BYTE[(size_t)bw*bh];
		for(int y = 0;y < bh;++y)
		{
			for(int x = 0;x < bw;++x)
			{
				const uint32_t c = big[y*bw + x];
				out[x*bh + y] = cache.Match((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF);
			}
		}
		return new FUpscaledTexture(bw, bh, out);
	}

	// The splash art.
	//
	// Preferred source is the game's own VGA chunk 6, upscaled here at startup:
	// that is the screen the original shows behind its menu, minus the logo,
	// which is why the menu draws the wordmark itself. Deriving it at runtime is
	// the point -- the art is commercial, so shipping a pre-upscaled copy would
	// mean shipping the art, whereas reading it out of the player's own data
	// files ships nothing.
	//
	// C7MENUBG still wins if it exists, so anyone who prefers a different
	// upscaler can drop one in an archive beside the data files and keep it.
	FTexture *Backdrop()
	{
		static FTexture *cached = NULL;
		static int cachedFactor = -1;
		static bool overrideChecked = false;
		static FTexture *override = NULL;

		if(!overrideChecked)
		{
			overrideChecked = true;
			const FTextureID id = TexMan.CheckForTexture("C7MENUBG", FTexture::TEX_Any);
			if(id.isValid())
				override = TexMan(id);
		}
		if(override != NULL)
			return override;

		const FTextureID srcId = TexMan.CheckForTexture("C7G0006", FTexture::TEX_Any);
		if(!srcId.isValid())
			return NULL;
		FTexture *const src = TexMan(srcId);
		if(src == NULL)
			return NULL;

		// Sized to the screen it will be stretched onto, so the upscale does the
		// enlarging rather than the blitter. Rebuilt only when that lands on a
		// different factor, which in practice means a resolution change.
		const int factor = R_XBRZAutoFactor(src->GetWidth(), src->GetHeight(),
			SCREENWIDTH, SCREENHEIGHT);
		if(factor < 2)
			return src;	// nothing to gain; the window is no bigger than the art

		if(cached == NULL || cachedFactor != factor)
		{
			FTexture *const built = BuildUpscaledBackdrop(src, factor);
			if(built == NULL)
				return src;
			delete cached;
			cached = built;
			cachedFactor = factor;
		}
		return cached;
	}

	// Paints the art across the screen, then fades it into black to the right in
	// vertical strips. Strips rather than a per-pixel composite: Dim() already
	// blends through the palette correctly, and 96 of them is smooth enough that
	// the banding is below the palette's own quantisation.
	void DrawBackdrop()
	{
		FTexture *art = Backdrop();
		if(art)
		{
			screen->DrawTexture(art, 0, 0,
				DTA_DestWidth, SCREENWIDTH,
				DTA_DestHeight, SCREENHEIGHT,
				TAG_DONE);
		}
		else
			screen->Clear(0, 0, SCREENWIDTH, SCREENHEIGHT, 0, 0);

		const int strips = 96;
		const int x0 = (int)(kFadeIn * SCREENWIDTH);
		const int x1 = (int)(kFadeOut * SCREENWIDTH);
		const int span = x1 - x0;
		if(span > 0)
		{
			for(int i = 0;i < strips;++i)
			{
				const int sx = x0 + span * i / strips;
				const int sw = (x0 + span * (i + 1) / strips) - sx;
				if(sw <= 0)
					continue;
				// Smoothstep, so neither end of the fade shows a seam.
				const double t = (i + 0.5) / strips;
				const double a = t * t * (3.0 - 2.0 * t);
				screen->Dim(0, (float)a, sx, 0, sw, SCREENHEIGHT);
			}
		}
		if(x1 < SCREENWIDTH)
			screen->Clear(x1, 0, SCREENWIDTH, SCREENHEIGHT, 0, 0);
	}

	void DrawRule(int x, int y, int w, int h)
	{
		screen->Clear(x, y, x + w, y + h,
			ColorMatcher.Pick(kAmberDimR, kAmberDimG, kAmberDimB), 0);
	}

	// The selection marker: a filled chevron rather than a highlight bar, so the
	// art behind the column stays readable.
	void DrawCursor(int x, int y, int size)
	{
		const BYTE c = ColorMatcher.Pick(kAmberR, kAmberG, kAmberB);
		for(int i = 0;i < size;++i)
		{
			const int half = size / 2;
			const int rows = (i <= half) ? i : (size - 1 - i);
			if(rows < 0)
				continue;
			screen->Clear(x, y + i, x + rows + 1, y + i + 1, c, 0);
		}
	}
}

bool C7Menu_Active()
{
	return IWad::CheckGameFilter("Corridor7");
}

void C7Menu_Invalidate()
{
	V_TTFlushCache();
}

bool C7Menu_Draw(const Menu *menu)
{
	if(menu == NULL || !LoadFonts() || screen == NULL)
		return false;

	const int labelX = (int)(kLabelX * SCREENWIDTH);
	const int valueX = (int)(kValueX * SCREENWIDTH);
	const int ruleW = valueX - labelX;

	DrawBackdrop();

	int y;
	const bool isMain = (menu == &mainMenu);
	if(isMain)
	{
		// The splash art ships without the logo, so the menu side carries it.
		const int titleSize = Scaled(54);
		const int ty = Scaled(96);
		const int wordW = V_TTTextWidth(g_bold, titleSize, "CORRIDOR ");
		V_TTDrawText(g_bold, titleSize, labelX, ty, "CORRIDOR",
			kWhiteR, kWhiteG, kWhiteB);
		V_TTDrawText(g_bold, titleSize, labelX + wordW, ty, "7",
			kAmberR, kAmberG, kAmberB);
		V_TTDrawText(g_regular, Scaled(13), labelX + Scaled(3), ty + Scaled(62),
			"A L I E N   I N V A S I O N", kDimR, kDimG, kDimB);
		DrawRule(labelX, ty + Scaled(88), ruleW, Scaled(2));
		y = Scaled(244);
	}
	else
	{
		const int hy = Scaled(96);
		FString head = menu->getHeadText();
		head.ToUpper();
		V_TTDrawText(g_bold, Scaled(30), labelX, hy, head,
			kWhiteR, kWhiteG, kWhiteB);
		DrawRule(labelX, hy + Scaled(42), ruleW, Scaled(2));
		y = Scaled(196);
	}

	// Rows. Item heights are authored for the 320x200 skin and mean nothing
	// here, so the shell paces them itself.
	const int rowStep = isMain ? Scaled(52) : Scaled(42);
	const int textSize = isMain ? Scaled(26) : Scaled(23);
	const int valueSize = isMain ? Scaled(24) : Scaled(21);
	const int count = menu->getNumItems();
	const int cur = menu->getCurrentPosition();

	// Scrolling. The engine keeps its own itemOffset, but it is computed from
	// 320x200 item heights that mean nothing here, and it is only ever advanced
	// by drawMenu(), which the skin replaces -- so a long list (the resolution
	// picker) never scrolled and the selection walked off the bottom.
	//
	// Both of handle()'s navigation branches move curPos identically whether or
	// not they touch itemOffset, so the skin can derive its own window and leave
	// the engine's alone. Deriving it from curPos each frame rather than storing
	// it means the selection is always on screen by construction.
	const int listBottom = SCREENHEIGHT - Scaled(96);
	int rowsVisible = (listBottom - y) / rowStep;
	if(rowsVisible < 1)
		rowsVisible = 1;
	int first = 0;
	if(cur >= rowsVisible)
		first = cur - rowsVisible + 1;
	if(first > count - rowsVisible)
		first = count - rowsVisible;
	if(first < 0)
		first = 0;
	const int listTop = y;

	for(int i = first;i < count;++i)
	{
		MenuItem *item = menu->getIndex(i);
		if(item == NULL || !item->isVisible())
			continue;
		if(y + rowStep > listBottom)
			break;

		// A section label titles the rows under it rather than being one of
		// them, so it is set in small dim capitals over a hairline instead of
		// being drawn as an ordinary row.
		if(item->isSectionLabel())
		{
			FString head = item->getLabel();
			head.ToUpper();
			const int sy = y + Scaled(12);
			V_TTDrawText(g_bold, Scaled(13), labelX, sy, head,
				kAmberDimR, kAmberDimG, kAmberDimB);
			const int hw = V_TTTextWidth(g_bold, Scaled(13), head);
			screen->Clear(labelX + hw + Scaled(10), sy + Scaled(7),
				labelX + ruleW, sy + Scaled(7) + 1,
				ColorMatcher.Pick(52, 44, 30), 0);
			y += rowStep;
			continue;
		}

		const bool active = (i == cur);
		const bool usable = item->isEnabled();
		int r = kWhiteR, g = kWhiteG, b = kWhiteB;
		if(active)      { r = kAmberR; g = kAmberG; b = kAmberB; }
		else if(!usable){ r = kDimR;   g = kDimG;   b = kDimB;   }

		if(active)
		{
			const int cs = Scaled(18);
			DrawCursor(labelX - Scaled(26), y + Scaled(6), cs);
			screen->Clear(labelX, y + rowStep - Scaled(12),
				labelX + ruleW, y + rowStep - Scaled(12) + 1,
				ColorMatcher.Pick(70, 50, 8), 0);
		}

		V_TTDrawText(active ? g_bold : g_regular, textSize, labelX, y,
			item->getLabel(), r, g, b);

		const FString value = isMain ? FString() : item->getValueText();
		if(value.IsNotEmpty())
		{
			const int vw = V_TTTextWidth(g_regular, valueSize, value);
			const int vr = active ? kAmberR : (usable ? kGreyR : kDimR);
			const int vg = active ? kAmberG : (usable ? kGreyG : kDimG);
			const int vb = active ? kAmberB : (usable ? kGreyB : kDimB);
			V_TTDrawText(g_regular, valueSize, valueX - vw, y + Scaled(1),
				value, vr, vg, vb);
		}

		y += rowStep;
	}

	// Tell the player the list continues. Without this a scrolled list is
	// indistinguishable from a complete one.
	if(count > rowsVisible)
	{
		const BYTE tip = ColorMatcher.Pick(kAmberDimR, kAmberDimG, kAmberDimB);
		const int tw = Scaled(10), th = Scaled(6);
		const int tx = valueX - tw;
		if(first > 0)
		{
			for(int r = 0;r < th;++r)
				screen->Clear(tx + (tw * r) / (2 * th), listTop - Scaled(18) + (th - 1 - r),
					tx + tw - (tw * r) / (2 * th), listTop - Scaled(18) + (th - r), tip, 0);
		}
		if(first + rowsVisible < count)
		{
			for(int r = 0;r < th;++r)
				screen->Clear(tx + (tw * r) / (2 * th), listBottom + Scaled(6) + r,
					tx + tw - (tw * r) / (2 * th), listBottom + Scaled(6) + r + 1, tip, 0);
		}

		FString pos;
		pos.Format("%d / %d", cur + 1, count);
		V_TTDrawText(g_regular, Scaled(13), labelX, listBottom + Scaled(6),
			pos, kDimR, kDimG, kDimB);
	}

	// Footer key hints. Arrows are drawn as triangles: the bundled face is an
	// ASCII subset and cannot be assumed to carry arrow codepoints.
	const int fy = SCREENHEIGHT - Scaled(54);
	screen->Clear(labelX, fy - Scaled(14), valueX + Scaled(17),
		fy - Scaled(14) + 1, ColorMatcher.Pick(48, 48, 48), 0);
	V_TTDrawText(g_regular, Scaled(15), labelX, fy,
		"ENTER  Select      ESC  Back", kDimR, kDimG, kDimB);

	return true;
}
