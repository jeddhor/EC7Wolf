// ID_VL.C

#include <string.h>
#include "c_cvars.h"
#include "colormatcher.h"
#include "wl_def.h"
#include "id_in.h"
#include "id_vl.h"
#include "id_vh.h"
#include "w_wad.h"
#include "r_2d/r_main.h"
#include "r_data/colormaps.h"
#include "v_font.h"
#include "v_video.h"
#include "v_palette.h"
#include "wl_draw.h"
#include "wl_game.h"
#include "wl_main.h"
#include "wl_play.h"


// Uncomment the following line, if you get destination out of bounds
// assertion errors and want to ignore them during debugging
//#define IGNORE_BAD_DEST

#ifdef IGNORE_BAD_DEST
#undef assert
#define assert(x) if(!(x)) return
#define assert_ret(x) if(!(x)) return 0
#else
#define assert_ret(x) assert(x)
#endif

bool fullscreen = true;
unsigned screenWidth = 640;
unsigned screenHeight = 480;
unsigned windowWidth = 640;
unsigned windowHeight = 480;
unsigned fullScreenWidth = 640;
unsigned fullScreenHeight = 480;
unsigned windowedScreenWidth = 640;
unsigned windowedScreenHeight = 480;
unsigned screenBits = static_cast<unsigned> (-1);      // use "best" color depth according to libSDL
float screenGamma = 1.0f;

unsigned curPitch;

unsigned scaleFactorX, scaleFactorY;

bool	 screenfaded;

//===========================================================================

void VL_ToggleFullscreen()
{
	VL_SetFullscreen(!fullscreen);
}

// Splits the video mode into the size that reaches the display and the smaller
// size the game actually draws. Rendering below the display is what gives a
// filter like xBRZ something to work with: at 1:1 it enlarges the frame and the
// window immediately throws the enlargement away.
//
// The floor is the original's own 320x200. Below that the 2D layout code stops
// having room for a status bar, and V_DoModeSetup asserts on it outright.
bool VL_UpdateRenderSize()
{
	const unsigned scale = clamp(vid_renderscale, 1, VL_MAX_RENDERSCALE);
	const unsigned w = MAX<unsigned>(windowWidth / scale, 320);
	const unsigned h = MAX<unsigned>(windowHeight / scale, 200);

	const bool changed = (w != screenWidth || h != screenHeight);
	screenWidth = w;
	screenHeight = h;
	return changed;
}

void VL_SetFullscreen(bool isFull)
{
	vid_fullscreen = fullscreen = isFull;

	if (fullscreen)
	{
		windowWidth = fullScreenWidth;
		windowHeight = fullScreenHeight;
	}
	else
	{
		windowWidth = windowedScreenWidth;
		windowHeight = windowedScreenHeight;
	}
	VL_UpdateRenderSize();

	// Recalculate the aspect ratio, because this can change from fullscreen to
	// windowed now. It is taken from the window rather than the render size: the
	// aspect the player sees is the window's, and a scale that does not divide
	// evenly would otherwise nudge the ratio for no reason.
	r_ratio = static_cast<Aspect>(CheckRatio(windowWidth, windowHeight));
	VL_SetVGAPlaneMode();
	if(playstate)
	{
		DrawPlayScreen();
	}
	IN_AdjustMouse();
}

//===========================================================================

void VL_ReadPalette(const char* lump)
{
	InitPalette(lump);
	R_InitColormaps();
	TexMan.InvalidatePalette();
	V_RetranslateFonts();
}

/*
=======================
=
= VL_SetVGAPlaneMode
=
=======================
*/

void I_InitGraphics ();
void	VL_SetVGAPlaneMode (bool forSignon)
{
	if(!forSignon)
		screen->Unlock();

	I_InitGraphics();
	Video->SetResolution(screenWidth, screenHeight, 8);
	screen->Lock(true);
	R_SetupBuffer ();
	screen->Unlock();

	scaleFactorX = CleanXfac;
	scaleFactorY = CleanYfac;

	pixelangle = new short[SCREENWIDTH];
	wallheight = new int[SCREENWIDTH];

	NewViewSize(viewsize);

	screen->Lock(false);
}

/*
=============================================================================

						PALETTE OPS

		To avoid snow, do a WaitVBL BEFORE calling these

=============================================================================
*/

FBlendFader::FBlendFader(int start, int end, int red, int green, int blue, int steps)
: start(start<<FRACBITS), end(end<<FRACBITS), red(red), green(green),
  blue(blue), fadems(TICS2MS(steps)), startms(SDL_GetTicks()),
  aStep((this->end-this->start)/fadems)
{
}

bool FBlendFader::Update()
{
	int32_t curtime;
	if((curtime = SDL_GetTicks() - startms) < fadems)
	{
		V_SetBlend(red, green, blue, (start+curtime*aStep)>>FRACBITS);
		return false;
	}
	else
	{
		V_SetBlend(red, green, blue, end>>FRACBITS);
		return true;
	}
}

/*
=================
=
= VL_FadeOut
=
= Fades the current palette to the given color in the given number of steps
=
=================
*/

static FBlendFader fade(0, 0, 0, 0, 0, 1);
void VL_Fade (int start, int end, int red, int green, int blue, int steps)
{
	fade = FBlendFader(start, end, red, green, blue, steps);

	while(!fade.Update())
		VH_UpdateScreen();
	VH_UpdateScreen();

	screenfaded = end != 0;

	// Clear out any input at this point that may be stored up. This solves
	// issues such as starting facing the wrong angle in super 3d noah's ark.
	IN_ProcessEvents();
}

void VL_FadeOut (int start, int end, int red, int green, int blue, int steps)
{
	VL_Fade(start, end, red, green, blue, steps);
}


/*
=================
=
= VL_FadeIn
=
=================
*/

void VL_FadeIn (int start, int end, int steps)
{
	if(screenfaded)
		VL_Fade(end, start, fade.R(), fade.G(), fade.B(), steps);
}

/*
=================
=
= VL_FadeIn
= Match fade color and remove palette blend
=
=================
*/

void VL_FadeClear ()
{
	VWB_Clear(ColorMatcher.Pick(fade.R(), fade.G(), fade.B()), 0, 0, screenWidth, screenHeight);
	V_SetBlend(0, 0, 0, 0);
	VH_UpdateScreen();
}

/*
=============================================================================

							PIXEL OPS

=============================================================================
*/

byte *VL_LockSurface()
{
	screen->Lock(false);
	return (byte *) screen->GetBuffer();
}

void VL_UnlockSurface()
{
	screen->Unlock();
}
