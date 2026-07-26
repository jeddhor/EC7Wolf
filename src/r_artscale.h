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

#endif
