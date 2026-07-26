/*
** v_ttf.h
**
** TrueType text rendering onto the 8-bit indexed canvas.
**
** ECWolf's own fonts are bitmap lumps, which are fixed-size: a menu drawn with
** them either snaps to a baked size ladder or gets scaled and goes soft. The
** Corridor 7 menu has to look right from 640x400 to 4K, so it rasterises a
** bundled TrueType face at the exact pixel size the current resolution wants.
**
** The face is bundled rather than taken from the host: a system font cannot be
** relied on to exist, and the menu must look identical on every platform.
*/

#ifndef __V_TTF_H__
#define __V_TTF_H__

#include "zstring.h"

class FTTFont;

// Loads (and caches) a bundled face by its full lump name, e.g.
// "fonts/c7menu.ttf". Returns NULL if the lump is missing or unparsable, so
// callers must be able to fall back to the engine's bitmap fonts.
FTTFont *V_GetTTFont(const char *lumpname);

// Width in real pixels of `text` rendered at `pixelHeight`. Uses the same
// advance and kerning the renderer will apply, so it can be used for right
// alignment without drifting.
int V_TTTextWidth(FTTFont *font, int pixelHeight, const char *text);

// Ascent above the baseline, in real pixels, at this size. Callers position by
// the text's top edge, so this is what converts a top to a baseline.
int V_TTAscent(FTTFont *font, int pixelHeight);

// Draws `text` with its top-left at (x, y) in real screen pixels, into the
// currently locked 8-bit canvas. Antialiasing is resolved against whatever is
// already in the framebuffer, so text over the splash art blends correctly
// rather than fringing against an assumed background.
void V_TTDrawText(FTTFont *font, int pixelHeight, int x, int y,
	const char *text, int r, int g, int b);

// Drops every cached glyph and blend table. Called when the palette changes,
// since the blend tables are palette-dependent.
void V_TTFlushCache();

#endif
