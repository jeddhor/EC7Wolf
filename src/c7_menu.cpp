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

#include <math.h>
#include <SDL.h>

#include "c7_menu.h"

#include "wl_def.h"
#include "id_in.h"
#include "id_us.h"
#include "wl_iwad.h"
#include "m_classes.h"
#include "id_vh.h"
#include "r_artscale.h"
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

	// The splash art.
	//
	// Preferred source is the game's own VGA chunk 6, upscaled at first use:
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
		return R_UpscaledArt(TexMan(srcId));
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

bool C7Menu_FadeColumn(const Menu *menu, bool out)
{
	if(menu == NULL || screen == NULL || !C7Menu_Active() || !LoadFonts())
		return false;

	// Left edge of the fade. The rows all start at kLabelX and the selection
	// chevron hangs a little to their left, so this starts left of both and runs
	// to the right edge. It reaches slightly into the art's own fade to black,
	// which is what keeps the boundary invisible: there is nothing at full
	// strength anywhere near it.
	const int x0 = (int)((kLabelX - 0.05) * SCREENWIDTH);
	const int w = SCREENWIDTH - x0;
	if(x0 < 0 || w <= 0)
		return false;

	// Same span as the palette fade this replaces, so the menu keeps the pacing
	// it has always had and only the area being faded changes.
	const int steps = 10;
	for(int i = 0;i <= steps;++i)
	{
		const double t = (double)i / steps;
		const float alpha = (float)(out ? t : 1.0 - t);
		if(!C7Menu_Draw(menu))
			return false;	// mid-fade is an awkward place to fail, but a half
							// drawn column beats leaving the screen mid-dim
		if(alpha > 0.0f)
			screen->Dim(0, alpha, x0, 0, w, SCREENHEIGHT);
		VW_UpdateScreen();
		SDL_Delay(TICS2MS(1));
	}
	return true;
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


// Editing a text field inside this shell.
//
// TextInputMenuItem::activate draws its own editor with US_LineInput, at the
// stock menu's coordinates and in the bitmap font. Those coordinates mean
// nothing here -- the row it belongs to is somewhere else entirely and in a
// different typeface -- so the field appeared as a blue strip across the
// bottom of the screen while the row it was editing sat untouched further up.
//
// Rather than work out where the row is and draw a second editor there, this
// puts the text being typed into the item as its value and asks the shell to
// draw the menu. The value column already right-aligns it in the right place,
// in the right font, on the right row, because that is what it does for every
// other item.
bool C7Menu_DrawWaiting(const char *heading, const char *detail,
	const char *note, unsigned int seconds,
	const C7WaitingRow *rows, int rowCount)
{
	if(!C7Menu_Active() || !LoadFonts() || screen == NULL)
		return false;

	const int labelX = (int)(kLabelX * SCREENWIDTH);
	const int valueX = (int)(kValueX * SCREENWIDTH);
	const int ruleW = valueX - labelX;

	DrawBackdrop();

	// The heading sits exactly where a menu's does, so that arriving here from
	// the setup screen does not move the eye.
	const int hy = Scaled(96);
	FString head(heading ? heading : "");
	head.ToUpper();
	V_TTDrawText(g_bold, Scaled(30), labelX, hy, head, kWhiteR, kWhiteG, kWhiteB);
	DrawRule(labelX, hy + Scaled(42), ruleW, Scaled(2));

	int y = Scaled(196);

	if(detail && *detail)
	{
		V_TTDrawText(g_regular, Scaled(23), labelX, y, detail,
			kGreyR, kGreyG, kGreyB);
		y += Scaled(46);
	}

	// An indeterminate bar: there is no total to measure against, so it sweeps
	// rather than fills. A segment a fifth of the width slides across a dim
	// track and eases at each end, which reads as activity without pretending
	// to be progress.
	{
		const int barH = Scaled(6);
		const int trackY = y;
		screen->Clear(labelX, trackY, labelX + ruleW, trackY + barH,
			ColorMatcher.Pick(38, 34, 26), 0);

		const int segW = ruleW / 5;
		const double period = 2200.0;
		double phase = fmod((double)SDL_GetTicks(), period) / period;
		// Triangle wave, then smoothstepped, so it slows at the turns instead
		// of snapping back to the left.
		double sweep = phase < 0.5 ? phase*2.0 : (1.0 - phase)*2.0;
		sweep = sweep * sweep * (3.0 - 2.0 * sweep);
		const int segX = labelX + (int)(sweep * (ruleW - segW));
		screen->Clear(segX, trackY, segX + segW, trackY + barH,
			ColorMatcher.Pick(kAmberR, kAmberG, kAmberB), 0);

		y += barH + Scaled(34);
	}

	// Elapsed time, right-aligned in the value column like any other value.
	{
		FString elapsed;
		elapsed.Format("%u:%02u", seconds/60, seconds%60);
		const int w = V_TTTextWidth(g_regular, Scaled(21), elapsed);
		V_TTDrawText(g_regular, Scaled(21), valueX - w, Scaled(196),
			elapsed, kAmberDimR, kAmberDimG, kAmberDimB);
	}

	for(int i = 0;i < rowCount;++i)
	{
		if(rows[i].label == NULL)
			continue;
		V_TTDrawText(g_regular, Scaled(21), labelX, y, rows[i].label,
			kWhiteR, kWhiteG, kWhiteB);
		if(rows[i].value)
		{
			const int w = V_TTTextWidth(g_regular, Scaled(21), rows[i].value);
			V_TTDrawText(g_regular, Scaled(21), valueX - w, y, rows[i].value,
				kGreyR, kGreyG, kGreyB);
		}
		y += Scaled(32);
	}

	// The note is wrapped to the column rather than clipped at it. The box this
	// replaced cut whatever would not fit, which turned the one line explaining
	// what to check into half a line explaining nothing.
	if(note && *note)
	{
		y += Scaled(18);
		const int size = Scaled(18);
		FString word, line;
		const char *p = note;
		for(;;)
		{
			if(*p && *p != ' ' && *p != '\n')
			{
				word += *p++;
				continue;
			}

			FString candidate = line.IsEmpty() ? word : line + " " + word;
			if(!line.IsEmpty() && V_TTTextWidth(g_regular, size, candidate) > ruleW)
			{
				V_TTDrawText(g_regular, size, labelX, y, line, kDimR, kDimG, kDimB);
				y += Scaled(24);
				line = word;
			}
			else
				line = candidate;
			word = "";

			if(*p == '\n')
			{
				V_TTDrawText(g_regular, size, labelX, y, line, kDimR, kDimG, kDimB);
				y += Scaled(24);
				line = "";
			}
			if(!*p)
				break;
			++p;
		}
		if(!line.IsEmpty())
			V_TTDrawText(g_regular, size, labelX, y, line, kDimR, kDimG, kDimB);
	}

	VW_UpdateScreen();
	return true;
}

bool C7Menu_LineInput(const Menu *menu, MenuItem *item, FString &text,
	unsigned int maxLength, void (*setValue)(MenuItem *, const FString &))
{
	const FString original = text;
	FString edited = text;
	bool done = false, accepted = false;
	unsigned int blink = 0;

	LastASCII = key_None;
	LastScan = sc_None;

	while(!done)
	{
		IN_ProcessEvents();

		const ScanCode scan = LastScan;
		const char typed = LastASCII;
		LastScan = sc_None;
		LastASCII = key_None;

		switch(scan)
		{
			case sc_Return:
				accepted = done = true;
				break;
			case sc_Escape:
				done = true;
				break;
			case sc_BackSpace:
				if(edited.Len() > 0)
					edited.Truncate(edited.Len() - 1);
				break;
			default:
				// Anything printable. An address is ASCII, and refusing the
				// rest here is cheaper than validating it later.
				if(typed >= ' ' && typed < 127 && edited.Len() < maxLength)
					edited += typed;
				break;
		}

		// A caret that blinks, so it is obvious the field is being edited and
		// not merely selected.
		FString shown = edited;
		if(((++blink >> 4) & 1) == 0)
			shown += "_";
		setValue(item, shown);

		C7Menu_Draw(menu);
		VW_UpdateScreen();
		SDL_Delay(10);
	}

	setValue(item, accepted ? edited : original);
	if(accepted)
		text = edited;
	return accepted;
}
