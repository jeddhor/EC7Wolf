// ID_VL.H

#ifndef __ID_VL_H__
#define __ID_VL_H__

//===========================================================================

// Beyond a quarter there is nothing left to render: a 640x400 window would be
// drawing at 160x100, well under the floor VL_UpdateRenderSize enforces.
#define VL_MAX_RENDERSCALE 4

extern  bool	fullscreen;
// screenWidth/screenHeight are the size the game renders at -- the framebuffer,
// what SCREENWIDTH ends up as, and what every piece of layout code measures
// against. windowWidth/windowHeight are the size that reaches the display. They
// are equal unless vid_renderscale asks for a smaller frame, in which case the
// present path stretches one to the other (see VL_UpdateRenderSize).
extern  unsigned screenWidth, screenHeight, screenBits, curPitch;
extern  unsigned windowWidth, windowHeight;
// The video mode the user picked, which is a window size, not a render size.
extern  unsigned fullScreenWidth, fullScreenHeight;
extern  unsigned windowedScreenWidth, windowedScreenHeight;
extern  unsigned scaleFactorX, scaleFactorY;
extern	float	screenGamma;

extern	bool  screenfaded;

//===========================================================================

//
// VGA hardware routines
//

#define VL_WaitVBL(a) SDL_Delay((SDL_GetTicks() - TICS2MS(GetTimeCount())) + TICS2MS((a)-1))

void VL_ToggleFullscreen();
void VL_SetFullscreen(bool isFull);

// Recomputes screenWidth/Height from windowWidth/Height and vid_renderscale.
// Call after changing either the video mode or the scale, before setting the
// mode. Returns true if the render size moved.
bool VL_UpdateRenderSize();

void VL_ReadPalette(const char* lump);

void VL_SetVGAPlaneMode (bool forSignon=false);
void VL_SetTextMode (void);

class FFader
{
public:
	virtual ~FFader() {}

	// Performs a fade step and returns true if fade is complete
	virtual bool Update()=0;
};

class FBlendFader : public FFader
{
	fixed start, end;
	int red, green, blue;
	int32_t fadems;
	int32_t startms;
	fixed aStep;

public:
	FBlendFader(int start, int end, int red, int green, int blue, int steps);

	bool Update();

	int R() const { return red; }
	int G() const { return green; }
	int B() const { return blue; }
};

void VL_FadeOut     (int start, int end, int red, int green, int blue, int steps);
void VL_FadeIn      (int start, int end, int steps);
void VL_FadeClear   ();

byte *VL_LockSurface();
void VL_UnlockSurface();

#define VL_ClearScreen(color) VWB_Clear(color, 0, 0, SCREENWIDTH, SCREENHEIGHT)

#endif
