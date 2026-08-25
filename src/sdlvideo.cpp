
// HEADER FILES ------------------------------------------------------------

#include "wl_def.h"
#include "c_cvars.h"

#include "templates.h"
//#include "i_system.h"
//#include "i_video.h"
#include "v_video.h"
#include "v_pfx.h"
//#include "stats.h"
#include "v_palette.h"
#include "sdlvideo.h"
#include "r_xbrz.h"
//#include "r_swrenderer.h"
#include "thingdef/thingdef.h"
#include "wl_main.h"
#include "r_capture.h"
#include "version.h"

#include <SDL.h>

#ifdef ECWOLF_RENDERER_OPENGL
#include "render/opengl/r_glworld.h"
#else
// Software-only build: the GL present path compiles out entirely.
static inline bool R_GLLiveWantPresent() { return false; }
static inline void R_GLLivePresent(const unsigned char *, int, int, int, int, int) {}
static inline void R_GLLiveSetContextActive(bool) {}
static inline void R_GLProfileEndFrame() {}
#endif

IVideo *Video = NULL;

extern float screenGamma;

DFrameBuffer *I_SetMode (int &width, int &height, DFrameBuffer *old)
{
	bool fs = false;
	switch (Video->GetDisplayType ())
	{
	case DISPLAY_WindowOnly:
		fs = false;
		break;
	case DISPLAY_FullscreenOnly:
		fs = true;
		break;
	case DISPLAY_Both:
		fs = vid_fullscreen;
		break;
	}
	DFrameBuffer *res = Video->CreateFrameBuffer (width, height, fs, old);

	/* Right now, CreateFrameBuffer cannot return NULL
	if (res == NULL)
	{
		I_FatalError ("Mode %dx%d is unavailable\n", width, height);
	}
	*/
	return res;
}

bool I_CheckResolution (int width, int height, int bits)
{
	int twidth, theight;

	Video->StartModeIterator (bits, screen ? screen->IsFullscreen() : vid_fullscreen);
	while (Video->NextMode (&twidth, &theight, NULL))
	{
		if (width == twidth && height == theight)
			return true;
	}
	return false;
}

void I_ClosestResolution (int *width, int *height, int bits)
{
	int twidth, theight;
	int cwidth = 0, cheight = 0;
	int iteration;
	DWORD closest = 0xFFFFFFFFu;

	for (iteration = 0; iteration < 2; iteration++)
	{
		Video->StartModeIterator (bits, screen ? screen->IsFullscreen() : vid_fullscreen);
		while (Video->NextMode (&twidth, &theight, NULL))
		{
			if (twidth == *width && theight == *height)
				return;

			if (iteration == 0 && (twidth < *width || theight < *height))
				continue;

			DWORD dist = (twidth - *width) * (twidth - *width)
				+ (theight - *height) * (theight - *height);

			if (dist < closest)
			{
				closest = dist;
				cwidth = twidth;
				cheight = theight;
			}
		}
		if (closest != 0xFFFFFFFFu)
		{
			*width = cwidth;
			*height = cheight;
			return;
		}
	}
}

//
// V_SetResolution
//
bool V_DoModeSetup (int width, int height, int bits)
{
	DFrameBuffer *buff = I_SetMode (width, height, screen);
	int cx1, cx2;

	if (buff == NULL)
	{
		return false;
	}

	screen = buff;
	GC::WriteBarrier(screen);
	screen->SetGamma (screenGamma);

	// Load fonts now so they can be packed into textures straight away,
	// if D3DFB is being used for the display.
	//FFont::StaticPreloadFonts();

	V_CalcCleanFacs(320, 200, width, height, &CleanXfac, &CleanYfac, &cx1, &cx2);

	CleanWidth = width / CleanXfac;
	CleanHeight = height / CleanYfac;
	assert(CleanWidth >= 320);
	assert(CleanHeight >= 200);

	if (width < 800 || width >= 960)
	{
		if (cx1 < cx2)
		{
			// Special case in which we don't need to scale down.
			CleanXfac_1 = 
			CleanYfac_1 = cx1;
		}
		else
		{
			CleanXfac_1 = MAX(CleanXfac - 1, 1);
			CleanYfac_1 = MAX(CleanYfac - 1, 1);
			// On larger screens this is not enough so make sure it's at most 3/4 of the screen's width
			while (CleanXfac_1 * 320 > screen->GetWidth()*3/4 && CleanXfac_1 > 2)
			{
				CleanXfac_1--;
				CleanYfac_1--;
			}
		}
		CleanWidth_1 = width / CleanXfac_1;
		CleanHeight_1 = height / CleanYfac_1;
	}
	else // if the width is between 800 and 960 the ratio between the screensize and CleanXFac-1 becomes too large.
	{
		CleanXfac_1 = CleanXfac;
		CleanYfac_1 = CleanYfac;
		CleanWidth_1 = CleanWidth;
		CleanHeight_1 = CleanHeight;
	}


	DisplayWidth = width;
	DisplayHeight = height;
	DisplayBits = bits;

	//R_OldBlend = ~0;
	//Renderer->OnModeSet();
	
	//M_RefreshModesList ();

	return true;
}

bool IVideo::SetResolution (int width, int height, int bits)
{
	int oldwidth, oldheight;
	int oldbits;

	if (screen)
	{
		oldwidth = SCREENWIDTH;
		oldheight = SCREENHEIGHT;
		oldbits = DisplayBits;
	}
	else
	{ // Harmless if screen wasn't allocated
		oldwidth = width;
		oldheight = height;
		oldbits = bits;
	}

	// The mode list is a list of things a display can show, and it is only the
	// window that has to be one of them. A render-scaled frame is a framebuffer
	// size -- any size is valid, and snapping it to the nearest listed mode would
	// silently change its shape: 1280x800 at 1/3 is 426x266, whose nearest entry
	// is 480x270, which would then be stretched to a 16:10 window.
	if ((unsigned)width == windowWidth && (unsigned)height == windowHeight)
	{
		I_ClosestResolution (&width, &height, bits);
		if (!I_CheckResolution (width, height, bits))
		{ // Try specified resolution
			if (!I_CheckResolution (oldwidth, oldheight, oldbits))
			{ // Try previous resolution (if any)
				return false;
			}
			else
			{
				width = oldwidth;
				height = oldheight;
				bits = oldbits;
			}
		}
	}
	return V_DoModeSetup (width, height, bits);
}

void IVideo::DumpAdapters ()
{
	Printf("Multi-monitor support unavailable.\n");
}

void I_ShutdownGraphics ()
{
	if (screen)
	{
		DFrameBuffer *s = screen;
		screen = NULL;
		s->ObjectFlags |= OF_YesReallyDelete;
		delete s;
	}
	if (Video)
		delete Video, Video = NULL;

	SDL_QuitSubSystem (SDL_INIT_VIDEO);
}

void I_InitGraphics ()
{
	if(Video)
		return;

	if (SDL_InitSubSystem (SDL_INIT_VIDEO) < 0)
	{
		I_FatalError ("Could not initialize SDL video:\n%s\n", SDL_GetError());
		return;
	}

#ifdef __ANDROID__
	extern void Android_InitGraphics();
	Android_InitGraphics();
#endif

	Video = new SDLVideo (0);
	if (Video == NULL)
		I_FatalError ("Failed to initialize display");

//	Video->SetWindowedScale (vid_winscale);
}

// MACROS ------------------------------------------------------------------

// TYPES -------------------------------------------------------------------

class SDLFB : public DFrameBuffer
{
	DECLARE_CLASS(SDLFB, DFrameBuffer)
public:
#if SDL_VERSION_ATLEAST(2,0,0)
	SDLFB (int width, int height, bool fullscreen, SDL_Window *oldwin);
#else
	SDLFB (int width, int height, bool fullscreen);
#endif
	~SDLFB ();

	bool Lock (bool buffer);
	void Unlock ();
	bool Relock ();
	void ForceBuffering (bool force);
	bool IsValid ();
	void Update ();
	PalEntry *GetPalette ();
	void GetFlashedPalette (PalEntry pal[256]);
	void UpdatePalette ();
	bool SetGamma (float gamma);
	bool SetFlash (PalEntry rgb, int amount);
	void GetFlash (PalEntry &rgb, int &amount);
	void SetFullscreen (bool fullscreen);
	int GetPageCount ();
	bool IsFullscreen ();

	void PaletteChanged () { }
	int QueryNewPalette () { return 0; }
	bool Is8BitMode() { return true; }

	friend class SDLVideo;

	virtual void SetVSync (bool vsync);
	virtual void ScaleCoordsFromWindow(SWORD &x, SWORD &y);

private:
	PalEntry SourcePalette[256];
	BYTE GammaTable[3][256];
	PalEntry Flash;
	int FlashAmount;
	float Gamma;
	bool UpdatePending;

#if SDL_VERSION_ATLEAST(2,0,0)
	SDL_Window *Screen;
	SDL_Renderer *Renderer;
	union
	{
		SDL_Texture *Texture;
		SDL_Surface *Surface;
	};
	SDL_GLContext GLContext;	// non-NULL when presenting through the GL backend
	bool UsingGL;
	SDL_Texture *XBRZTexture;	// upscaled frame; separate from the Texture union
	int XBRZFactor;				// factor XBRZTexture was sized for; 0 = none
	// The window this framebuffer asked for, which is not Width/Height once
	// vid_renderscale has the game drawing smaller than it displays.
	int WinWidth, WinHeight;
#else
	SDL_Surface *Screen;
#endif

	bool UsingRenderer;
	bool NeedPalUpdate;
	bool NeedGammaUpdate;
	bool NotPaletted;

	void UpdateColors ();
	void GetPresentPalette (PalEntry pal[256]);
	void ResetSDLRenderer ();
#if SDL_VERSION_ATLEAST(2,0,0)
	bool PresentXBRZ ();
	void DestroyXBRZTexture ();
#endif

	SDLFB () {}
};
IMPLEMENT_INTERNAL_CLASS(SDLFB)

struct MiniModeInfo
{
	WORD Width, Height;
};

// PUBLIC FUNCTION PROTOTYPES ----------------------------------------------

// PRIVATE FUNCTION PROTOTYPES ---------------------------------------------

// EXTERNAL DATA DECLARATIONS ----------------------------------------------

extern IVideo *Video;
//extern SDL_Surface *cursorSurface;
//extern SDL_Rect cursorBlit;
//extern bool GUICapture;

#define vid_maxfps 70
#define cl_capfps false
//EXTERN_CVAR (Float, Gamma)
//EXTERN_CVAR (Int, vid_maxfps)
//EXTERN_CVAR (Bool, cl_capfps)

// PUBLIC DATA DEFINITIONS -------------------------------------------------

extern unsigned screenBits;
#define vid_displaybits screenBits

#if 0
CVAR (Int, vid_adapter, 0, CVAR_ARCHIVE|CVAR_GLOBALCONFIG)

CVAR (Int, vid_displaybits, 32, CVAR_ARCHIVE|CVAR_GLOBALCONFIG)

CVAR (Bool, vid_forcesurface, false, CVAR_ARCHIVE|CVAR_GLOBALCONFIG)

CUSTOM_CVAR (Float, rgamma, 1.f, CVAR_ARCHIVE|CVAR_GLOBALCONFIG)
{
	if (screen != NULL)
	{
		screen->SetGamma (Gamma);
	}
}
CUSTOM_CVAR (Float, ggamma, 1.f, CVAR_ARCHIVE|CVAR_GLOBALCONFIG)
{
	if (screen != NULL)
	{
		screen->SetGamma (Gamma);
	}
}
CUSTOM_CVAR (Float, bgamma, 1.f, CVAR_ARCHIVE|CVAR_GLOBALCONFIG)
{
	if (screen != NULL)
	{
		screen->SetGamma (Gamma);
	}
}
#else
#define vid_adapter 0
#define rgamma 1.f
#define ggamma 1.f
#define bgamma 1.f
#define vid_forcesurface 0
#endif

// PRIVATE DATA DEFINITIONS ------------------------------------------------

// Dummy screen sizes to pass when windowed
static MiniModeInfo WinModes[] =
{
	{ 320, 200 },
	{ 320, 240 },
	{ 400, 225 },	// 16:9
	{ 400, 300 },
	{ 480, 270 },	// 16:9
	{ 480, 360 },
	{ 512, 288 },	// 16:9
	{ 512, 384 },
	{ 640, 270 },   // 64:27 (~21:9)
	{ 640, 360 },	// 16:9
	{ 640, 400 },
	{ 640, 480 },
	{ 720, 480 },	// 16:10
	{ 720, 540 },
	{ 800, 450 },	// 16:9
	{ 800, 480 },
	{ 800, 500 },	// 16:10
	{ 800, 600 },
	{ 848, 480 },	// 16:9
	{ 960, 600 },	// 16:10
	{ 960, 720 },
	{ 1024, 288 },  // 32:9
	{ 1024, 576 },	// 16:9
	{ 1024, 600 },	// 17:10
	{ 1024, 640 },	// 16:10
	{ 1024, 768 },
	{ 1088, 612 },	// 16:9
	{ 1152, 648 },	// 16:9
	{ 1152, 720 },	// 16:10
	{ 1152, 864 },
	{ 1280, 360 },  // 32:9
	{ 1280, 540 },  // 64:27 (~21:9)
	{ 1280, 720 },	// 16:9
	{ 1280, 854 },
	{ 1280, 800 },	// 16:10
	{ 1280, 960 },
	{ 1280, 1024 },	// 5:4
	{ 1360, 768 },	// 16:9
	{ 1366, 768 },
	{ 1400, 787 },	// 16:9
	{ 1400, 875 },	// 16:10
	{ 1400, 1050 },
	{ 1440, 900 },
	{ 1440, 960 },
	{ 1440, 1080 },
	{ 1600, 900 },	// 16:9
	{ 1600, 1000 },	// 16:10
	{ 1600, 1200 },
	{ 1680, 1050 },	// 16:10
	{ 1720, 720 },  // 43:18 (~21:9)
	{ 1920, 540 },  // 32:9
	{ 1920, 1080 },
	{ 1920, 1200 },
	{ 2048, 864 }, // 64:27 (~21:9)
	{ 2048, 1536 },
	{ 2240, 1400 }, // 16:10
	{ 2304, 1440 }, // 16:10
	{ 2560, 720 },  // 32:9
	{ 2560, 1080 }, // 64:27 (~21:9)
	{ 2560, 1440 },
	{ 2560, 1600 },
	{ 2560, 2048 },
	{ 2880, 1800 },
	{ 3072, 1920 }, // 16:10
	{ 3200, 1800 },
	{ 3440, 1440 }, // 43:18 (~21:9)
	{ 3840, 1080 }, // 32:9
	{ 3840, 2160 },
	{ 3840, 2400 },
	{ 4096, 2160 },
	{ 4096, 2304 }, // 16:9
	{ 4480, 2520 }, // 16:9
	{ 5120, 1440 }, // 32:9
	{ 5120, 2880 }
};

//static cycle_t BlitCycles;
//static cycle_t SDLFlipCycles;

// CODE --------------------------------------------------------------------

void ScaleWithAspect (int &w, int &h, int Width, int Height)
{
	int resRatio = CheckRatio (Width, Height);
	int screenRatio;
	CheckRatio (w, h, &screenRatio);
	if (resRatio == screenRatio)
		return;

	double yratio;
	switch(resRatio)
	{
		case ASPECT_NONE: yratio = 4./3.; break;
		case ASPECT_16_9: yratio = 16./9.; break;
		case ASPECT_16_10: yratio = 16./10.; break;
		case ASPECT_17_10: yratio = 17./10.; break;
		case ASPECT_5_4: yratio = 5./4.; break;
		case ASPECT_4_3: yratio = 4./3.; break;
		case ASPECT_64_27: yratio = 64./27.; break;
		case ASPECT_32_9: yratio = 32./9.; break;
		default: return;
	}
	double y = w/yratio;
	if (y > h)
		w = (int)(h*yratio);
	else
		h = (int)(y);
}

SDLVideo::SDLVideo (int parm)
{
	IteratorBits = 0;
	IteratorFS = false;
}

SDLVideo::~SDLVideo ()
{
}

void SDLVideo::StartModeIterator (int bits, bool fs)
{
	IteratorMode = 0;
	IteratorBits = bits;
	IteratorFS = fs;
}

bool SDLVideo::NextMode (int *width, int *height, bool *letterbox)
{
	if (IteratorBits != 8)
		return false;

#if !SDL_VERSION_ATLEAST(2,0,0)
	if (!IteratorFS)
	{
#endif
		if ((unsigned)IteratorMode < sizeof(WinModes)/sizeof(WinModes[0]))
		{
			*width = WinModes[IteratorMode].Width;
			*height = WinModes[IteratorMode].Height;
			++IteratorMode;
			return true;
		}
#if !SDL_VERSION_ATLEAST(2,0,0)
	}
	else
	{
		SDL_Rect **modes = SDL_ListModes (NULL, SDL_FULLSCREEN|SDL_HWSURFACE);
		if (modes != NULL && modes[IteratorMode] != NULL)
		{
			*width = modes[IteratorMode]->w;
			*height = modes[IteratorMode]->h;
			++IteratorMode;
			return true;
		}
	}
#endif
	return false;
}

DFrameBuffer *SDLVideo::CreateFrameBuffer (int width, int height, bool fullscreen, DFrameBuffer *old)
{
	static int retry = 0;
	static int owidth, oheight;
	
	PalEntry flashColor;
	int flashAmount;

#if SDL_VERSION_ATLEAST(2,0,0)
	SDL_Window *oldwin = NULL;
#endif

#if __ANDROID__
	// Always fullscreen in Android
	fullscreen = true;
#endif

	if (old != NULL)
	{ // Reuse the old framebuffer if its attributes are the same
		SDLFB *fb = static_cast<SDLFB *> (old);
		// The window is part of "the same attributes": changing vid_renderscale
		// and the video mode together can leave the render size untouched while
		// the window has to resize, and reusing the framebuffer then would keep
		// the old window forever.
		if (fb->Width == width &&
			fb->Height == height &&
			fb->WinWidth == MAX<int>((int)windowWidth, width) &&
			fb->WinHeight == MAX<int>((int)windowHeight, height))
		{
#if SDL_VERSION_ATLEAST(2,0,0)
			bool fsnow = (SDL_GetWindowFlags (fb->Screen) & SDL_WINDOW_FULLSCREEN_DESKTOP) != 0;
	
			if (fsnow != fullscreen)
			{
				fb->SetFullscreen (fullscreen);
			}
			return old;
#else
			bool fsnow = (fb->Screen->flags & SDL_FULLSCREEN) != 0;
	
			if (fsnow == fullscreen)
				return old;
			if (fsnow != fullscreen)
			{
				if(SDL_WM_ToggleFullScreen (fb->Screen))
					return old;
			}
#endif
		}

#if SDL_VERSION_ATLEAST(2,0,0)
		oldwin = fb->Screen;
		fb->Screen = NULL;
#endif

		old->GetFlash (flashColor, flashAmount);
		old->ObjectFlags |= OF_YesReallyDelete;
		if (screen == old) screen = NULL;
		delete old;
	}
	else
	{
		flashColor = 0;
		flashAmount = 0;
	}

#if SDL_VERSION_ATLEAST(2,0,0)
	SDLFB *fb = new SDLFB (width, height, fullscreen, oldwin);
#else
	SDLFB *fb = new SDLFB (width, height, fullscreen);
#endif
	
	// If we could not create the framebuffer, try again with slightly
	// different parameters in this order:
	// 1. Try with the closest size
	// 2. Try in the opposite screen mode with the original size
	// 3. Try in the opposite screen mode with the closest size
	// This is a somewhat confusing mass of recursion here.

	while (fb == NULL || !fb->IsValid ())
	{
		if (fb != NULL)
		{
			delete fb;
		}

		switch (retry)
		{
		case 0:
			owidth = width;
			oheight = height;
		case 2:
			// Try a different resolution. Hopefully that will work.
			I_ClosestResolution (&width, &height, 8);
			break;

		case 1:
			// Try changing fullscreen mode. Maybe that will work.
			width = owidth;
			height = oheight;
			fullscreen = !fullscreen;
			break;

		default:
			// I give up!
			I_FatalError ("Could not create new screen (%d x %d)", owidth, oheight);
		}

		++retry;
		fb = static_cast<SDLFB *>(CreateFrameBuffer (width, height, fullscreen, NULL));
	}
	retry = 0;

	fb->SetFlash (flashColor, flashAmount);

	return fb;
}

void SDLVideo::SetWindowedScale (float scale)
{
}

// FrameBuffer implementation -----------------------------------------------

#if SDL_VERSION_ATLEAST(2,0,0)
SDLFB::SDLFB (int width, int height, bool fullscreen, SDL_Window *oldwin)
#else
SDLFB::SDLFB (int width, int height, bool fullscreen)
#endif
	: DFrameBuffer (width, height)
{
	int i;
	
	NeedPalUpdate = false;
	NeedGammaUpdate = false;
	UpdatePending = false;
	NotPaletted = false;
	FlashAmount = 0;
	// Only ever assigned in ResetSDLRenderer, which the GL path skips entirely,
	// so without this it stays uninitialized for the whole life of a GL
	// framebuffer.
	UsingRenderer = false;

#if SDL_VERSION_ATLEAST(2,0,0)
	Renderer = NULL;
	Texture = NULL;
	GLContext = NULL;
	XBRZTexture = NULL;
	XBRZFactor = 0;
	// The window takes the video mode; width/height above are the render size,
	// which vid_renderscale may have divided down. Equal in the ordinary case.
	//
	// Except on the surface path, which blits the frame into the window at 1:1
	// and has nothing that could stretch it -- there the window is pinned back
	// to the frame, so the setting is merely inert rather than drawing the game
	// into a corner of an oversized window.
	WinWidth = MAX<int>(vid_forcesurface ? width : (int)windowWidth, width);
	WinHeight = MAX<int>(vid_forcesurface ? height : (int)windowHeight, height);
	// The OpenGL backend presents by compositing on the game window itself, so
	// the window must be GL-capable and must not also drive an SDL_Renderer.
	UsingGL = R_GLLiveWantPresent();

#ifdef __ANDROID__
	// A phone has one window and it is the screen. There is no windowed mode to
	// fall back to, and asking for an arbitrary 640x480 window is how this
	// arrived at "Could not create new screen (640 x 480)" -- the retry ladder
	// above tries a different resolution, then toggles fullscreen, then gives
	// up, and none of that helps when the request was never going to be
	// honoured in the first place.
	fullscreen = true;
	{
		SDL_DisplayMode dm;
		if (SDL_GetCurrentDisplayMode(0, &dm) == 0 && dm.w > 0 && dm.h > 0)
		{
			WinWidth = dm.w;
			WinHeight = dm.h;
		}
	}
#endif

	Uint32 winflags = (fullscreen ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0);
	if (UsingGL)
	{
		// The second place in the tree that asks for a GL context, and it has
		// to agree with GLDevice::Create about what it is asking for. Requesting
		// a desktop core profile here on Android makes SDL_CreateWindow itself
		// fail, before any of the renderer's own code runs -- so the backend
		// looks absent when it is merely unreachable.
#ifdef __ANDROID__
		SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
		SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
		SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,
			SDL_GL_CONTEXT_PROFILE_ES);
#else
		SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
		SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
		SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,
			SDL_GL_CONTEXT_PROFILE_CORE);
#endif
		SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
		SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);
		winflags |= SDL_WINDOW_OPENGL;
	}

	if (oldwin)
	{
		// In some cases (Mac OS X fullscreen) SDL2 doesn't like having multiple windows which
		// appears to inevitably happen while compositor animations are running. So lets try
		// to reuse the existing window.
		Screen = oldwin;
		SDL_SetWindowSize (Screen, WinWidth, WinHeight);
		SetFullscreen (fullscreen);
	}
	else
	{
		Screen = SDL_CreateWindow (GetGameCaption(),
			SDL_WINDOWPOS_UNDEFINED_DISPLAY(vid_adapter), SDL_WINDOWPOS_UNDEFINED_DISPLAY(vid_adapter),
			WinWidth, WinHeight, winflags);

		if (Screen == NULL)
			return;
	}

#ifdef _WIN32
	extern void ForceSDLFocus(SDL_Window *win);
	ForceSDLFocus(Screen);
#endif

	if (UsingGL)
	{
		GLContext = SDL_GL_CreateContext(Screen);
		if (GLContext != NULL)
		{
			SDL_GL_MakeCurrent(Screen, GLContext);
			SDL_GL_SetSwapInterval(vid_vsync ? 1 : 0);
			R_GLLiveSetContextActive(true);
		}
		else
		{
			Printf("GL: window context creation failed (%s); "
				"using software presentation.\n", SDL_GetError());
			UsingGL = false;
			R_GLLiveSetContextActive(false);
		}
	}

	if (!UsingGL)
		ResetSDLRenderer ();

#ifdef __ANDROID__
	extern void PostSDLCreateRenderer(SDL_Window *);
	PostSDLCreateRenderer(Screen);
#endif

	for (i = 0; i < 256; i++)
	{
		GammaTable[0][i] = GammaTable[1][i] = GammaTable[2][i] = i;
	}
#else
	SDL_WM_SetCaption(GetGameCaption(), NULL);

	if(vid_displaybits == static_cast<unsigned>(-1))
	{
		const SDL_VideoInfo *vidInfo = SDL_GetVideoInfo();
		screenBits = vidInfo->vfmt->BitsPerPixel;
	}

	Screen = SDL_SetVideoMode (width, height, vid_displaybits,
		SDL_HWSURFACE|SDL_HWPALETTE|SDL_DOUBLEBUF|SDL_ANYFORMAT|
		(fullscreen ? SDL_FULLSCREEN : 0));

	if (Screen == NULL)
		return;

	for (i = 0; i < 256; i++)
	{
		GammaTable[0][i] = GammaTable[1][i] = GammaTable[2][i] = i;
	}
	if (Screen->format->palette == NULL)
	{
		NotPaletted = true;
		GPfx.SetFormat (Screen->format->BitsPerPixel,
			Screen->format->Rmask,
			Screen->format->Gmask,
			Screen->format->Bmask);
	}
#endif

	memcpy (SourcePalette, GPalette.BaseColors, sizeof(PalEntry)*256);
#if SDL_VERSION_ATLEAST(2,0,0)
	// The GL present path uploads the palette to a texture each frame (there is
	// no SDL_Surface/renderer palette to program), so skip UpdateColors here.
	if (!UsingGL)
#endif
		UpdateColors ();

#ifdef __APPLE__
	SetVSync (vid_vsync);
#endif
}

SDLFB::~SDLFB ()
{
#if SDL_VERSION_ATLEAST(2,0,0)
	if (GLContext)
	{
		R_GLLiveSetContextActive(false);
		SDL_GL_DeleteContext (GLContext);
		GLContext = NULL;
	}

	if (Renderer)
	{
		DestroyXBRZTexture ();
		if (Texture)
			SDL_DestroyTexture (Texture);
		SDL_DestroyRenderer (Renderer);
	}

	if(Screen)
	{
		SDL_DestroyWindow (Screen);
	}
#endif

	// The scratch buffers are sized for this framebuffer's resolution; a mode
	// change builds a new SDLFB, so do not carry the old one's memory into it.
	R_XBRZFreeScratch ();
}

bool SDLFB::IsValid ()
{
	return DFrameBuffer::IsValid() && Screen != NULL;
}

int SDLFB::GetPageCount ()
{
	return 1;
}

bool SDLFB::Lock (bool buffered)
{
	return DSimpleCanvas::Lock ();
}

bool SDLFB::Relock ()
{
	return DSimpleCanvas::Lock ();
}

void SDLFB::Unlock ()
{
	if (UpdatePending && LockCount == 1)
	{
		Update ();
	}
	else if (--LockCount <= 0)
	{
		Buffer = NULL;
		LockCount = 0;
	}
}

void SDLFB::Update ()
{
	if (LockCount != 1)
	{
		if (LockCount > 0)
		{
			UpdatePending = true;
			--LockCount;
		}
		return;
	}

	DrawRateStuff ();

#if SDL_VERSION_ATLEAST(2,0,0)
	if (UsingGL)
	{
		// GL present: the OpenGL backend already rendered the world for this frame
		// (OpenGLRenderer::RenderScene); composite it with the 8-bit 2D layer in
		// MemBuffer and swap. The palette (incl. any blend baked into BaseColors)
		// is uploaded inside Present, so the SDL palette/gamma path is bypassed.
		Buffer = NULL;
		LockCount = 0;
		UpdatePending = false;
		NeedGammaUpdate = false;
		NeedPalUpdate = false;

		int dw = Width, dh = Height;
		SDL_GL_GetDrawableSize (Screen, &dw, &dh);
		R_GLLivePresent (MemBuffer, Pitch, Width, Height, dw, dh);
#ifdef __ANDROID__
		// The touch overlay, on top of the finished frame and before the swap.
		// It used to be hooked into the SDL_Renderer path below, which the GL
		// cutover stopped using -- so from Phase 11 until now the controls were
		// never initialised and never drawn, on a platform that has no keyboard.
		{
			extern void frameControls();
			frameControls();
		}
#endif
		SDL_GL_SwapWindow (Screen);
		R_GLProfileEndFrame ();
		// After the swap, where unwinding is safe: a capture whose artifact is
		// produced outside the gameplay loop ends its run here.
		Capture::PostPresent ();
		return;
	}
#endif

	if (NeedGammaUpdate)
	{
		bool Windowed = false;
		NeedGammaUpdate = false;
		CalcGamma ((Windowed || rgamma == 0.f) ? Gamma : (Gamma * rgamma), GammaTable[0]);
		CalcGamma ((Windowed || ggamma == 0.f) ? Gamma : (Gamma * ggamma), GammaTable[1]);
		CalcGamma ((Windowed || bgamma == 0.f) ? Gamma : (Gamma * bgamma), GammaTable[2]);
		NeedPalUpdate = true;
	}

	if (NeedPalUpdate)
	{
		NeedPalUpdate = false;
		UpdateColors ();
	}

#if 0
#ifndef __APPLE__
	if(vid_maxfps && !cl_capfps)
	{
		SEMAPHORE_WAIT(FPSLimitSemaphore)
	}
#endif
#endif

	Buffer = NULL;
	LockCount = 0;
	UpdatePending = false;

	//BlitCycles.Reset();
	//SDLFlipCycles.Reset();
	//BlitCycles.Clock();

#if SDL_VERSION_ATLEAST(2,0,0)
	// Image scaling, when it is on and the frame can be filtered. Anything that
	// stops it -- the setting being off, no room to scale into, a texture that
	// would not allocate -- reports false and falls through to the plain path
	// below, so a frame is never lost to it.
	if (PresentXBRZ ())
		return;

	void *pixels;
	int pitch;
	if (UsingRenderer)
	{
		if (SDL_LockTexture (Texture, NULL, &pixels, &pitch))
			return;
	}
	else
	{
		if (SDL_LockSurface (Surface))
			return;

		pixels = Surface->pixels;
		pitch = Surface->pitch;
	}

	if (NotPaletted)
	{
		GPfx.Convert (MemBuffer, Pitch,
			pixels, pitch, Width, Height,
			FRACUNIT, FRACUNIT, 0, 0);
	}
	else
	{
		if (pitch == Pitch)
		{
			memcpy (pixels, MemBuffer, Width*Height);
		}
		else
		{
			for (int y = 0; y < Height; ++y)
			{
				memcpy ((BYTE *)pixels+y*pitch, MemBuffer+y*Pitch, Width);
			}
		}
	}

	if (UsingRenderer)
	{
		SDL_UnlockTexture (Texture);

		//SDLFlipCycles.Clock();
		SDL_RenderClear(Renderer);
		SDL_RenderCopy(Renderer, Texture, NULL, NULL);

#ifdef __ANDROID__
		// Hack control overlay in
		extern void frameControls();
		frameControls();
#endif

		SDL_RenderPresent(Renderer);
		//SDLFlipCycles.Unclock();
	}
	else
	{
		SDL_UnlockSurface (Surface);

		//SDLFlipCycles.Clock();
		SDL_UpdateWindowSurface (Screen);
		//SDLFlipCycles.Unclock();
	}

#else
	if (SDL_LockSurface (Screen) == -1)
		return;

	if (NotPaletted)
	{
		GPfx.Convert (MemBuffer, Pitch,
			Screen->pixels, Screen->pitch, Width, Height,
			FRACUNIT, FRACUNIT, 0, 0);
	}
	else
	{
		if (Screen->pitch == Pitch)
		{
			memcpy (Screen->pixels, MemBuffer, Width*Height);
		}
		else
		{
			for (int y = 0; y < Height; ++y)
			{
				memcpy ((BYTE *)Screen->pixels+y*Screen->pitch, MemBuffer+y*Pitch, Width);
			}
		}
	}
	
	SDL_UnlockSurface (Screen);

#if 0
	if (cursorSurface != NULL && GUICapture)
	{
		// SDL requires us to draw a surface to get true color cursors.
		SDL_BlitSurface(cursorSurface, NULL, Screen, &cursorBlit);
	}
#endif

	//SDLFlipCycles.Clock();
	SDL_Flip (Screen);
	//SDLFlipCycles.Unclock();
#endif

	//BlitCycles.Unclock();
}

// The palette a frame is actually shown through: the source palette after gamma
// and after any full-screen flash (damage, pickups, the visor tints) has been
// blended in. Factored out of UpdateColors because the xBRZ path needs the same
// colours but resolves them itself rather than through GPfx.
void SDLFB::GetPresentPalette (PalEntry pal[256])
{
	for (int i = 0; i < 256; ++i)
	{
		pal[i].r = GammaTable[0][SourcePalette[i].r];
		pal[i].g = GammaTable[1][SourcePalette[i].g];
		pal[i].b = GammaTable[2][SourcePalette[i].b];
	}
	if (FlashAmount)
	{
		DoBlending (pal, pal,
			256, GammaTable[0][Flash.r], GammaTable[1][Flash.g], GammaTable[2][Flash.b],
			FlashAmount);
	}
}

void SDLFB::UpdateColors ()
{
	if (NotPaletted)
	{
		PalEntry palette[256];

		GetPresentPalette (palette);
		GPfx.SetPalette (palette);
	}
	else
	{
		SDL_Color colors[256];
		
		for (int i = 0; i < 256; ++i)
		{
			colors[i].r = GammaTable[0][SourcePalette[i].r];
			colors[i].g = GammaTable[1][SourcePalette[i].g];
			colors[i].b = GammaTable[2][SourcePalette[i].b];
		}
		if (FlashAmount)
		{
			DoBlending ((PalEntry *)colors, (PalEntry *)colors,
				256, GammaTable[2][Flash.b], GammaTable[1][Flash.g], GammaTable[0][Flash.r],
				FlashAmount);
		}
#if SDL_VERSION_ATLEAST(2,0,0)
		SDL_SetPaletteColors (Surface->format->palette, colors, 0, 256);
#else
		SDL_SetPalette (Screen, SDL_LOGPAL|SDL_PHYSPAL, colors, 0, 256);
#endif
	}
}

PalEntry *SDLFB::GetPalette ()
{
	return SourcePalette;
}

void SDLFB::UpdatePalette ()
{
	NeedPalUpdate = true;
}

bool SDLFB::SetGamma (float gamma)
{
	Gamma = gamma;
	NeedGammaUpdate = true;
	return true;
}

bool SDLFB::SetFlash (PalEntry rgb, int amount)
{
	Flash = rgb;
	FlashAmount = amount;
	NeedPalUpdate = true;
	return true;
}

void SDLFB::GetFlash (PalEntry &rgb, int &amount)
{
	rgb = Flash;
	amount = FlashAmount;
}

// Q: Should I gamma adjust the returned palette?
void SDLFB::GetFlashedPalette (PalEntry pal[256])
{
	memcpy (pal, SourcePalette, 256*sizeof(PalEntry));
	if (FlashAmount)
	{
		DoBlending (pal, pal, 256, Flash.r, Flash.g, Flash.b, FlashAmount);
	}
}

void SDLFB::SetFullscreen (bool fullscreen)
{
#ifdef __ANDROID__
	fullscreen = true;
#endif

#if SDL_VERSION_ATLEAST(2,0,0)
	if (IsFullscreen() == fullscreen)
		return;

	SDL_SetWindowFullscreen (Screen, fullscreen ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0);
	if (!fullscreen)
	{
		// Restore proper window size
		SDL_SetWindowSize (Screen, Width, Height);
	}

	if (!UsingGL)
		ResetSDLRenderer ();
#endif
}

bool SDLFB::IsFullscreen ()
{
#if SDL_VERSION_ATLEAST(2,0,0)
	return (SDL_GetWindowFlags (Screen) & SDL_WINDOW_FULLSCREEN_DESKTOP) != 0;
#else
	return (Screen->flags & SDL_FULLSCREEN) != 0;
#endif
}

void SDLFB::ResetSDLRenderer ()
{
#if SDL_VERSION_ATLEAST(2,0,0)
	// The GL present path owns the window's context and never uses an
	// SDL_Renderer; leave it untouched.
	if (UsingGL)
		return;

	if (Renderer)
	{
		DestroyXBRZTexture ();
		if (Texture)
			SDL_DestroyTexture (Texture);
		SDL_DestroyRenderer (Renderer);
	}

	UsingRenderer = !vid_forcesurface;
	if (UsingRenderer)
	{
		Renderer = SDL_CreateRenderer (Screen, -1,SDL_RENDERER_ACCELERATED|SDL_RENDERER_TARGETTEXTURE|
										(vid_vsync ? SDL_RENDERER_PRESENTVSYNC : 0));
		if (!Renderer)
			return;

		SDL_SetRenderDrawColor(Renderer, 0, 0, 0, 255);

		Uint32 fmt;
		switch(vid_displaybits)
		{
			default: fmt = SDL_PIXELFORMAT_ARGB8888; break;
			case 30: fmt = SDL_PIXELFORMAT_ARGB2101010; break;
			case 24: fmt = SDL_PIXELFORMAT_RGB888; break;
			case 16: fmt = SDL_PIXELFORMAT_RGB565; break;
			case 15: fmt = SDL_PIXELFORMAT_ARGB1555; break;
		}
		Texture = SDL_CreateTexture (Renderer, fmt, SDL_TEXTUREACCESS_STREAMING, Width, Height);

		{
			NotPaletted = true;

			Uint32 format;
			SDL_QueryTexture(Texture, &format, NULL, NULL, NULL);

			Uint32 Rmask, Gmask, Bmask, Amask;
			int bpp;
			SDL_PixelFormatEnumToMasks(format, &bpp, &Rmask, &Gmask, &Bmask, &Amask);
			GPfx.SetFormat (bpp, Rmask, Gmask, Bmask);
		}
	}
	else
	{
		Surface = SDL_GetWindowSurface (Screen);

		if (Surface->format->palette == NULL)
		{
			NotPaletted = true;
			GPfx.SetFormat (Surface->format->BitsPerPixel, Surface->format->Rmask, Surface->format->Gmask, Surface->format->Bmask);
		}
		else
			NotPaletted = false;
	}

	// In fullscreen, set logical size according to animorphic ratio.
	// Windowed modes are rendered to fill the window (usually 1:1)
	//
	// A render-scaled window falls under "fill the window" too: SDL_RenderCopy
	// stretches the frame over the whole output on its own, and the frame is the
	// window divided down so the two are the same shape by construction. Running
	// it through ScaleWithAspect instead would letterbox -- 640x400 is classed as
	// a 4:3 mode -- and the picture would move when the render scale changed.
	if (IsFullscreen ())
	{
		int w, h;
		SDL_GetWindowSize (Screen, &w, &h);
		ScaleWithAspect (w, h, Width, Height);
		SDL_RenderSetLogicalSize (Renderer, w, h);
	}
#endif
}

#if SDL_VERSION_ATLEAST(2,0,0)
void SDLFB::DestroyXBRZTexture ()
{
	if (XBRZTexture)
	{
		SDL_DestroyTexture (XBRZTexture);
		XBRZTexture = NULL;
	}
	XBRZFactor = 0;
}

// Present the frame through xBRZ instead of uploading it at 1:1. Returns false
// if scaling is not being done, in which case the caller presents normally.
bool SDLFB::PresentXBRZ ()
{
	if (!UsingRenderer || Renderer == NULL || Texture == NULL)
		return false;

	// Measure against the renderer's output rather than the window: on a HiDPI
	// display those differ, and it is the output that the frame is stretched to.
	int outW = Width, outH = Height;
	SDL_GetRendererOutputSize (Renderer, &outW, &outH);

	const int factor = R_XBRZFactor (Width, Height, outW, outH);
	if (factor < 2)
	{
		DestroyXBRZTexture ();
		return false;
	}

	PalEntry pal[256];
	GetPresentPalette (pal);
	const uint32_t *const scaled =
		R_XBRZScaleIndexed (MemBuffer, Pitch, Width, Height, pal, factor);
	if (scaled == NULL)
	{
		DestroyXBRZTexture ();
		return false;
	}

	const int tw = Width * factor, th = Height * factor;
	if (XBRZTexture == NULL || XBRZFactor != factor)
	{
		DestroyXBRZTexture ();

		// The upscaled frame is larger than the window as often as not (6x from
		// 640x400 overshoots any display), and it is rarely an exact multiple of
		// it either way, so the final fit to the window is filtered. Point
		// sampling here would put the staircase edges back that xBRZ just spent
		// a frame's work removing. The hint is read when the texture is created,
		// so it is set around this call and restored straight after rather than
		// changed globally -- the unscaled path still wants point sampling.
		char prev[8];
		const char *const cur = SDL_GetHint (SDL_HINT_RENDER_SCALE_QUALITY);
		snprintf (prev, sizeof prev, "%s", cur ? cur : "0");
		SDL_SetHint (SDL_HINT_RENDER_SCALE_QUALITY, "1");
		XBRZTexture = SDL_CreateTexture (Renderer, SDL_PIXELFORMAT_ARGB8888,
			SDL_TEXTUREACCESS_STREAMING, tw, th);
		SDL_SetHint (SDL_HINT_RENDER_SCALE_QUALITY, prev);

		if (XBRZTexture == NULL)
			return false;
		XBRZFactor = factor;
	}

	void *pixels;
	int pitch;
	if (SDL_LockTexture (XBRZTexture, NULL, &pixels, &pitch))
		return false;
	if (pitch == tw*(int)sizeof(uint32_t))
	{
		memcpy (pixels, scaled, (size_t)tw*th*sizeof(uint32_t));
	}
	else
	{
		for (int y = 0; y < th; ++y)
		{
			memcpy ((BYTE *)pixels + (size_t)y*pitch, scaled + (size_t)y*tw,
				(size_t)tw*sizeof(uint32_t));
		}
	}
	SDL_UnlockTexture (XBRZTexture);

	SDL_RenderClear (Renderer);
	SDL_RenderCopy (Renderer, XBRZTexture, NULL, NULL);
	SDL_RenderPresent (Renderer);
	return true;
}
#endif

void SDLFB::SetVSync (bool vsync)
{
#if SDL_VERSION_ATLEAST(2,0,0)
	if (UsingGL)
	{
		SDL_GL_MakeCurrent (Screen, GLContext);
		SDL_GL_SetSwapInterval (vsync ? 1 : 0);
		return;
	}
	ResetSDLRenderer ();
#endif
}

void SDLFB::ScaleCoordsFromWindow(SWORD &x, SWORD &y)
{
#if SDL_VERSION_ATLEAST(2,0,0)
	int w, h;
	SDL_GetWindowSize (Screen, &w, &h);

	// Detect if we're doing scaling in the Window and adjust the mouse
	// coordinates accordingly. This could be more efficent, but I
	// don't think performance is an issue in the menus.
	if(IsFullscreen())
	{
		int realw = w, realh = h;
		ScaleWithAspect (realw, realh, SCREENWIDTH, SCREENHEIGHT);
		if (realw != SCREENWIDTH || realh != SCREENHEIGHT)
		{
			double xratio = (double)SCREENWIDTH/realw;
			double yratio = (double)SCREENHEIGHT/realh;
			if (realw < w)
			{
				x = (SWORD)((x - (w - realw)/2)*xratio);
				y = (SWORD)(y*yratio);
			}
			else
			{
				y = (SWORD)((y - (h - realh)/2)*yratio);
				x = (SWORD)(x*xratio);
			}
		}
	}
	else
	{
		x = (SWORD)(x*Width/w);
		y = (SWORD)(y*Height/h);
	}
#endif
}

#if 0
ADD_STAT (blit)
{
	FString out;
	out.Format ("blit=%04.1f ms  flip=%04.1f ms",
		BlitCycles.Time() * 1e-3, SDLFlipCycles.TimeMS());
	return out;
}
#endif
