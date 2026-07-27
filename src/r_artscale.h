/*
** r_artscale.h
**
** Runtime upscaling of the game's own art, for the full-screen pages.
*/

#ifndef __R_ARTSCALE_H__
#define __R_ARTSCALE_H__

class FTexture;

// An upscaled copy of `src`, sized for the current screen and cached, so a page
// that is drawn every frame pays for this once. Returns `src` itself when there
// is nothing to gain -- a screen no larger than the art, or a source that cannot
// be read -- so callers can use the result unconditionally.
//
// Only sensible for full-screen pages, which are stretched to fill the window
// and so are the art most obviously enlarged. Callers must size the draw in real
// pixels (DTA_DestWidth/DTA_DestHeight) rather than in the 320x200 virtual space,
// since the returned texture is no longer 320x200.
// A page whose cached copy was built for a different screen is rebuilt in place
// on the next call, so a resolution change costs one rebuild rather than leaving
// the wrong size on screen or accumulating a copy per resolution visited.
FTexture *R_UpscaledArt(FTexture *src);

// An upscaled `w` x `h` page built by tiling `tile` across it.
//
// A repeating backdrop cannot be upscaled one tile at a time: xBRZ treats the
// edges of what it is handed as edges of the image, so every seam in the middle
// of the pattern would be filtered as though the pattern stopped there, leaving
// a grid of them across the screen. Tiling first and upscaling the finished page
// makes those seams interior pixels like any other, and the only edges the
// filter sees are the edges of the screen.
//
// Cached per (tile, size), and drawn like any other upscaled page: size the draw
// in real pixels, since the result is no longer w x h.
FTexture *R_UpscaledTiledPage(FTexture *tile, int w, int h);

#endif
