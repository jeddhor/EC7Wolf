/*
** v_ttf.cpp
**
** TrueType text rendering onto the 8-bit indexed canvas. See v_ttf.h for why
** this exists rather than another baked bitmap font.
*/

#include "v_ttf.h"

#include "w_wad.h"
#include "v_video.h"
#include "v_palette.h"
#include "colormatcher.h"
#include "tarray.h"
#include "templates.h"

// stb_truetype carries an explicit warning that it does no range checking and
// must not be pointed at untrusted font files. Everything it parses here comes
// out of our own pk3, never from user-supplied data.
#define STB_TRUETYPE_IMPLEMENTATION
#define STBTT_STATIC
#include "stb_truetype.h"

namespace
{
	struct Glyph
	{
		TArray<BYTE>	cover;		// 8-bit coverage, w*h
		int				w, h;
		int				xoff, yoff;	// offset from pen position to bitmap corner
		int				advance;	// pen advance in whole pixels
		bool			valid;

		Glyph() : w(0), h(0), xoff(0), yoff(0), advance(0), valid(false) {}
	};

	// One rasterised size of one face. Glyphs are cached on first use; the menu
	// only ever touches printable ASCII, so the table stays small.
	struct SizedFace
	{
		int		pixelHeight;
		int		ascent;
		float	scale;
		Glyph	glyphs[128 - 32];
	};

	// Resolving antialiasing means blending the text color over whatever is
	// already on the canvas and finding the nearest palette entry -- far too
	// slow to do per pixel, since ColorMatcher::Pick searches the palette.
	// Instead, for each text color, precompute [coverage bucket][destination
	// index] -> index once. 17 buckets keeps the table small while staying
	// visually indistinguishable from full 256-level blending.
	const int kBuckets = 17;

	struct BlendTable
	{
		int		r, g, b;
		BYTE	map[kBuckets][256];
	};
}

class FTTFont
{
public:
	FTTFont() : ok(false) {}

	bool Load(const char *lumpname)
	{
		const int lump = Wads.CheckNumForFullName(lumpname);
		if(lump < 0)
			return false;
		const int len = Wads.LumpLength(lump);
		if(len <= 0)
			return false;
		data.Resize(len);
		Wads.ReadLump(lump, &data[0]);
		if(stbtt_InitFont(&info, &data[0],
			stbtt_GetFontOffsetForIndex(&data[0], 0)) == 0)
			return false;
		ok = true;
		return true;
	}

	bool IsOk() const { return ok; }

	SizedFace *GetSize(int pixelHeight)
	{
		if(pixelHeight < 4)
			pixelHeight = 4;
		for(unsigned int i = 0;i < sizes.Size();++i)
		{
			if(sizes[i]->pixelHeight == pixelHeight)
				return sizes[i];
		}

		SizedFace *sf = new SizedFace;
		sf->pixelHeight = pixelHeight;
		sf->scale = stbtt_ScaleForPixelHeight(&info, (float)pixelHeight);
		int asc, desc, gap;
		stbtt_GetFontVMetrics(&info, &asc, &desc, &gap);
		sf->ascent = (int)(asc * sf->scale + 0.5f);
		sizes.Push(sf);
		return sf;
	}

	Glyph *GetGlyph(SizedFace *sf, int ch)
	{
		if(ch < 32 || ch > 126)
			return NULL;
		Glyph *g = &sf->glyphs[ch - 32];
		if(g->valid)
			return g;

		int adv, lsb;
		stbtt_GetCodepointHMetrics(&info, ch, &adv, &lsb);
		g->advance = (int)(adv * sf->scale + 0.5f);

		int x0, y0, x1, y1;
		stbtt_GetCodepointBitmapBox(&info, ch, sf->scale, sf->scale,
			&x0, &y0, &x1, &y1);
		g->w = x1 - x0;
		g->h = y1 - y0;
		g->xoff = x0;
		g->yoff = y0;
		if(g->w > 0 && g->h > 0)
		{
			g->cover.Resize(g->w * g->h);
			stbtt_MakeCodepointBitmap(&info, &g->cover[0], g->w, g->h, g->w,
				sf->scale, sf->scale, ch);
		}
		g->valid = true;
		return g;
	}

	int Kern(int a, int b, float scale) const
	{
		return (int)(stbtt_GetCodepointKernAdvance(&info, a, b) * scale + 0.5f);
	}

	void Flush()
	{
		for(unsigned int i = 0;i < sizes.Size();++i)
			delete sizes[i];
		sizes.Clear();
	}

	~FTTFont() { Flush(); }

private:
	TArray<BYTE>		data;	// must outlive `info`, which points into it
	stbtt_fontinfo		info;
	TArray<SizedFace *>	sizes;
	bool				ok;
};

namespace
{
	TArray<FTTFont *>	g_fonts;
	TArray<FString>		g_fontNames;
	TArray<BlendTable *> g_blends;

	BlendTable *GetBlend(int r, int g, int b)
	{
		for(unsigned int i = 0;i < g_blends.Size();++i)
		{
			if(g_blends[i]->r == r && g_blends[i]->g == g && g_blends[i]->b == b)
				return g_blends[i];
		}

		BlendTable *bt = new BlendTable;
		bt->r = r; bt->g = g; bt->b = b;
		for(int bucket = 0;bucket < kBuckets;++bucket)
		{
			const int a = bucket * 255 / (kBuckets - 1);
			for(int dst = 0;dst < 256;++dst)
			{
				const PalEntry &d = GPalette.BaseColors[dst];
				const int nr = (r * a + d.r * (255 - a)) / 255;
				const int ng = (g * a + d.g * (255 - a)) / 255;
				const int nb = (b * a + d.b * (255 - a)) / 255;
				bt->map[bucket][dst] = ColorMatcher.Pick(nr, ng, nb);
			}
		}
		g_blends.Push(bt);
		return bt;
	}
}

FTTFont *V_GetTTFont(const char *lumpname)
{
	for(unsigned int i = 0;i < g_fontNames.Size();++i)
	{
		if(g_fontNames[i].CompareNoCase(lumpname) == 0)
			return g_fonts[i];
	}

	FTTFont *font = new FTTFont;
	if(!font->Load(lumpname))
	{
		delete font;
		font = NULL;
	}
	// Cache the failure too, so a missing face is not re-read every frame.
	g_fontNames.Push(lumpname);
	g_fonts.Push(font);
	return font;
}

int V_TTAscent(FTTFont *font, int pixelHeight)
{
	if(font == NULL || !font->IsOk())
		return 0;
	return font->GetSize(pixelHeight)->ascent;
}

int V_TTTextWidth(FTTFont *font, int pixelHeight, const char *text)
{
	if(font == NULL || !font->IsOk() || text == NULL)
		return 0;

	SizedFace *sf = font->GetSize(pixelHeight);
	int width = 0;
	for(const char *p = text;*p;++p)
	{
		Glyph *g = font->GetGlyph(sf, (unsigned char)*p);
		if(g == NULL)
			continue;
		width += g->advance;
		if(p[1])
			width += font->Kern((unsigned char)p[0], (unsigned char)p[1], sf->scale);
	}
	return width;
}

void V_TTDrawText(FTTFont *font, int pixelHeight, int x, int y,
	const char *text, int r, int g, int b)
{
	if(font == NULL || !font->IsOk() || text == NULL || screen == NULL)
		return;

	SizedFace *sf = font->GetSize(pixelHeight);
	BlendTable *blend = GetBlend(r, g, b);

	BYTE *const buffer = screen->GetBuffer();
	if(buffer == NULL)
		return;
	const int pitch = screen->GetPitch();
	const int cw = screen->GetWidth();
	const int ch = screen->GetHeight();

	// Callers position by the top edge; the rasteriser works from the baseline.
	const int baseline = y + sf->ascent;

	int pen = x;
	for(const char *p = text;*p;++p)
	{
		Glyph *gl = font->GetGlyph(sf, (unsigned char)*p);
		if(gl == NULL)
			continue;

		if(gl->w > 0 && gl->h > 0)
		{
			const int gx = pen + gl->xoff;
			const int gy = baseline + gl->yoff;
			for(int row = 0;row < gl->h;++row)
			{
				const int dy = gy + row;
				if(dy < 0 || dy >= ch)
					continue;
				const BYTE *src = &gl->cover[row * gl->w];
				BYTE *dst = buffer + dy * pitch;
				for(int col = 0;col < gl->w;++col)
				{
					const int a = src[col];
					if(a == 0)
						continue;
					const int dx = gx + col;
					if(dx < 0 || dx >= cw)
						continue;
					const int bucket = (a * (kBuckets - 1) + 127) / 255;
					dst[dx] = blend->map[bucket][dst[dx]];
				}
			}
		}

		pen += gl->advance;
		if(p[1])
			pen += font->Kern((unsigned char)p[0], (unsigned char)p[1], sf->scale);
	}
}

void V_TTFlushCache()
{
	for(unsigned int i = 0;i < g_fonts.Size();++i)
	{
		if(g_fonts[i])
			g_fonts[i]->Flush();
	}
	for(unsigned int i = 0;i < g_blends.Size();++i)
		delete g_blends[i];
	g_blends.Clear();
}
