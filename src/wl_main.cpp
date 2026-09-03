// WL_MAIN.C

#ifdef _WIN32
//	#include <io.h>
#else
	#include <unistd.h>
#endif

#include "wl_def.h"
#include "g_session.h"
#include "wl_menu.h"
#include "id_ca.h"
#include "id_sd.h"
#include "id_vl.h"
#include "id_vh.h"
#include "id_us.h"
#include "wl_atmos.h"
#include "m_classes.h"
#include "m_random.h"
#include "config.h"
#include "w_wad.h"
#include "language.h"
#include "textures/textures.h"
#include "c_cvars.h"
#include "thingdef/thingdef.h"
#include "v_font.h"
#include "v_palette.h"
#include "v_video.h"
#include "r_data/colormaps.h"
#include "wl_agent.h"
#include "doomerrors.h"
#include "lumpremap.h"
#include "scanner.h"
#include "g_shared/a_keys.h"
#include "g_mapinfo.h"
#include "wl_draw.h"
#include "wl_inter.h"
#include "wl_iwad.h"
#include "render/r_visibility.h"
#include "c7_cdaudio.h"
#include "c7_flic.h"
#include "c7_upscale.h"
#include "wl_play.h"
#include "c7_editorlink.h"
#include "r_capture.h"
#include "render/r_renderer.h"
#ifdef ECWOLF_RENDERER_OPENGL
#include "render/opengl/r_glrenderer.h"
#endif
#include "wl_game.h"
#include "wl_loadsave.h"
#include "wl_net.h"
#include "net_watchdog.h"
#include "dobject.h"
#include "colormatcher.h"
#include "version.h"
#include "r_2d/r_main.h"
#include "filesys.h"
#include "g_conversation.h"
#include "g_intermission.h"

#include <clocale>

/*
=============================================================================

							WOLFENSTEIN 3-D

						An Id Software production

							by John Carmack

=============================================================================
*/

/*
=============================================================================

							LOCAL CONSTANTS

=============================================================================
*/


#define FOCALLENGTH     (0x5700l)               // in global coordinates

#define VIEWWIDTH       256                     // size of view window
#define VIEWHEIGHT      144

/*
=============================================================================

							GLOBAL VARIABLES

=============================================================================
*/

//
// proejection variables
//
fixed    focallength;
fixed    focallengthy;
fixed    r_depthvisibility;
unsigned screenofs;
int      viewscreenx, viewscreeny;
int      viewwidth;
int      viewheight;
int      statusbarx;
int      statusbary1, statusbary2;
short    centerx;
short    centerxwide;
fixed    scale;
fixed    pspritexscale;
fixed    pspriteyscale;
fixed    yaspect;
int32_t  heightnumerator;

bool	startgame;
bool	loadedgame;
int		mousexadjustment;
int     mouseyadjustment;
int		panxadjustment;
int     panyadjustment;

//
// Command line parameter variables
//
bool param_nowait = false;
int     param_difficulty = 1;           // default is "normal"
const char* param_tedlevel = NULL;            // default is not to start a level
const char* param_playerclass = NULL;         // default is the first class in MAPINFO
int     param_joystickindex = 0;

int     param_joystickhat = -1;
int     param_samplerate = 44100;
int     param_audiobuffer = 2048 / (44100 / param_samplerate);

//===========================================================================

/*
=====================
=
= NewGame
=
= Set up new game to start from the beginning
=
=====================
*/

void NewGame (int difficulty, FString map, bool displayBriefing, FName playerClass)
{
	// void cast can be removed when we move to C++11
	memset ((void*)&gamestate,0,sizeof(gamestate));

	FName playerClassNames[MAXPLAYERS];
	playerClassNames[ConsolePlayer] = playerClass != NAME_None ? playerClass : gameinfo.PlayerClasses[0];

	Net::NewGame(difficulty, map, playerClassNames);

	gamestate.difficulty = &SkillInfo::GetSkill(difficulty);
	strncpy(gamestate.mapname, map, 8);
	gamestate.mapname[8] = 0;
	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		gamestate.playerClass[i] = ClassDef::FindClass(playerClassNames[i]);

	levelInfo = &LevelInfo::Find(map);

	if(displayBriefing)
		EnterText(levelInfo->Cluster);

	// Clear LevelRatios
	LevelRatios.killratio = LevelRatios.secretsratio = LevelRatios.treasureratio =
		LevelRatios.numLevels = LevelRatios.time = 0;

	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		players[i].state = player_t::PST_ENTER;

	Dialog::ClearConversations();

	startgame = true;
}

//===========================================================================

/*
==========================
=
= ShutdownId
=
= Shuts down all ID_?? managers
=
==========================
*/

static void ShutdownId (void)
{
	SD_Shutdown ();
	IN_Shutdown ();
}


//===========================================================================

/*
==================
=
= BuildTables
=
= Calculates:
=
= scale                 projection constant
= sintable/costable     overlapping fractional tables
=
==================
*/

const double radtoint = (double)(FINEANGLES/2/PI);

void BuildTables (void)
{
	//
	// calculate fine tangents
	//

	int i;
	for(i=0;i<FINEANGLES/8;i++)
	{
		double tang=tan((i+0.5)/radtoint);
		finetangent[i + FINEANGLES/2] = finetangent[i]=(fixed)(tang*FRACUNIT);
		finetangent[FINEANGLES/4-1-i]=(fixed)((1/tang)*FRACUNIT);
		finetangent[FINEANGLES/4+i]=-finetangent[FINEANGLES/4-1-i];
		finetangent[FINEANGLES/2-1-i]=-finetangent[i];
	}
	memcpy(finetangent + FINEANGLES/2, finetangent, sizeof(fixed)*ANG180);

	//
	// costable overlays sintable with a quarter phase shift
	// ANGLES is assumed to be divisable by four
	//

	float angle = 0;
	float anglestep = (float)(PI/2/ANG90);
	for(i=0; i<FINEANGLES; i++)
	{
		finesine[i]=fixed(FRACUNIT*sin(angle));
		angle+=anglestep;
	}
	memcpy(&finesine[FINEANGLES], finesine, FINEANGLES*sizeof(fixed)/4);

#if defined(USE_STARSKY) || defined(USE_RAIN) || defined(USE_SNOW)
	Init3DPoints();
#endif
}

//===========================================================================

void CalcVisibility(fixed vis)
{
	r_depthvisibility = FixedDiv(FixedMul((160*FRACUNIT),vis),focallengthy<<16);
}

/*
====================
=
= CalcProjection
=
= Uses focallength
=
====================
*/

void CalcProjection (int32_t focal)
{
	int     i;
	int    intang;
	int     halfview;
	double  facedist;

	const fixed projectionFOV = static_cast<fixed>((players[ConsolePlayer].FOV / 90.0f)*AspectCorrection[r_ratio].viewGlobal);

	// 0xFD17 is a magic number to convert the player's radius 0x5800 to FOCALLENGTH (0x5700)
	focallength = FixedMul(focal, 0xFD17);
	facedist = 2*FOCALLENGTH+0x100; // Used to be MINDIST (0x5800) which was 0x100 then the FOCALLENGTH (0x5700)
	halfview = viewwidth/2;                                 // half view in pixels
	focallengthy = centerx*yaspect/finetangent[FINEANGLES/2+(ANGLE_45>>ANGLETOFINESHIFT)];

	//
	// calculate scale value for vertical height calculations
	// and sprite x calculations
	//
	scale = (fixed) (viewwidth*facedist/projectionFOV);

	//
	// divide heightnumerator by a posts distance to get the posts height for
	// the heightbuffer.  The pixel height is height>>2
	//
	heightnumerator = FixedMul(((TILEGLOBAL*scale)>>6), yaspect);

	//
	// calculate the angle offset from view angle of each pixel's ray
	//

	for (i=0;i<=halfview;i++)
	{
		// start 1/2 pixel over, so viewangle bisects two middle pixels
		double tang = (((double)i+0.5)*projectionFOV)/viewwidth/facedist;
		double angle = atan(tang);
		intang = (int) (angle*radtoint);
		pixelangle[halfview-i] = intang;
		pixelangle[halfview-1+i] = -intang;
	}
}

//===========================================================================

Menu musicMenu(CTL_X, CTL_Y-6, 280, 32);
static TArray<FString> songList;

MENU_LISTENER(ChangeMusic)
{
	StartCPMusic(songList[which]);
	for(unsigned int i = 0;i < songList.Size();++i)
		musicMenu[i]->setHighlighted(i == (unsigned)which);
	musicMenu.draw();
	return true;
}

void DoJukebox(void)
{
	IN_ClearKeysDown();
	if (!AdLibPresent && !SoundBlasterPresent)
		return;

	VW_FadeOut ();

	ClearMScreen ();
	musicMenu.setHeadText(language["ROBSJUKEBOX"], true);
	for(unsigned int i = 0;i < (unsigned)Wads.GetNumLumps();++i)
	{
		if(Wads.GetLumpNamespace(i) != ns_music)
			continue;

		FString langString;
		langString.Format("MUS_%s", Wads.GetLumpFullName(i));
		const char* trackName = language[langString];
		if(trackName == langString.GetChars())
			musicMenu.addItem(new MenuItem(Wads.GetLumpFullName(i), ChangeMusic));
		else
			musicMenu.addItem(new MenuItem(language[langString], ChangeMusic));
		songList.Push(Wads.GetLumpFullName(i));

	}
	musicMenu.show();
	return;
}

/*
==========================
=
= InitGame
=
= Load a few things right away
=
==========================
*/

static void CollectGC()
{
	GC::FullGC();
	GC::DelSoftRootHead();
}

// The waiting screen for a game started from the command line.
//
// DrawStartupConsole cannot serve: for Corridor 7 it draws the signon splash
// and returns before printing anything, which was a deliberate decision -- the
// splash is the game's own opening and ECWolf's initialization chatter has no
// business over it. That is right for the eight lines of startup and wrong for
// the one screen where the game is waiting on somebody else, which without a
// word on it is indistinguishable from a hang.
static bool DrawNetworkStatus(const Net::InitStatus &status)
{
	FString statusStr;
	if(!status.failure.IsEmpty())
	{
		statusStr = status.failure;
	}
	else
	{
		if(status.phase == Net::InitStatus::PHASE_Hosting)
			statusStr.Format("Listening on %s", status.detail.GetChars());
		else
			statusStr.Format("Connecting to %s", status.detail.GetChars());
		statusStr.AppendFormat("   %u:%02u", status.seconds/60, status.seconds%60);
		for(unsigned int i = 0;i < status.peers.Size();++i)
		{
			statusStr.AppendFormat("\n%s: %s",
				status.peers[i].name.GetChars(), status.peers[i].state.GetChars());
		}
	}

	const bool hasSignon = !gameinfo.SignonLump.IsEmpty();
	if(hasSignon)
		CA_CacheScreen(TexMan(gameinfo.SignonLump));
	else
		screen->Clear(0, 0, SCREENWIDTH, SCREENHEIGHT, GPalette.BlackIndex, 0);

	// Low on the splash, where Corridor 7's own artwork is darkest.
	PrintY = 200 - 8 - ConFont->GetHeight()*3;
	PrintX = WindowX = 12;
	WindowW = 296;
	WindowH = ConFont->GetHeight()*3;
	US_Print(ConFont, statusStr, CR_WHITE);

	VH_UpdateScreen();

	// This used to return false and it did not matter, because the connect
	// loops threw the answer away. It is the cancel signal now, so returning
	// false here would abandon every --host and --join before the first
	// packet. Escape is the only thing that gives up.
	IN_ProcessEvents();
	if(LastScan == sc_Escape || Keyboard[sc_Escape])
	{
		LastScan = sc_None;
		return false;
	}
	return true;
}

static bool DrawStartupConsole(FString statusStr)
{
	// Window for printing text to the screen is (12,76), (308, 182)
	const int textWindowTop = 76 + 2*ConFont->GetHeight();
	const int textWindowHeight = 182-textWindowTop;

	const bool hasSignon = !gameinfo.SignonLump.IsEmpty();
	if(hasSignon)
		CA_CacheScreen(TexMan(gameinfo.SignonLump));
	else
		screen->Clear(0, 0, SCREENWIDTH, SCREENHEIGHT, GPalette.BlackIndex, 0);

	// Corridor 7's signon lump is its intended opening splash. Keep it clean
	// instead of drawing ECWolf's generic initialization text over the image.
	if(hasSignon && IWad::CheckGameFilter("Corridor7"))
	{
		VH_UpdateScreen();
		return false;
	}

	word width, height;

	static const char* const engineVersion = GAMENAME " " DOTVERSIONSTR_NOREV;
	VW_MeasurePropString(ConFont, engineVersion, width, height);
	px = 160-width/2;
	py = 76;
	VWB_DrawPropString(ConFont, engineVersion, CR_GRAY);

	FString engineMode;
	switch(Net::InitVars.mode)
	{
	case Net::MODE_SinglePlayer:
		engineMode = "Single player";
		break;
	case Net::MODE_Host:
		engineMode.Format("Hosting %d players", Net::InitVars.numPlayers);
		break;
	case Net::MODE_Client:
		engineMode = "Joining multiplayer";
		break;
	}
	VW_MeasurePropString(ConFont, engineMode, width, height);
	px = 160-width/2;
	py += ConFont->GetHeight();
	VWB_DrawPropString(ConFont, engineMode, CR_GRAY);

	VW_MeasurePropString(ConFont, statusStr, width, height);
	px = 160-width/2;
	py = textWindowTop + (textWindowHeight-height)/2;
	VWB_DrawPropString(ConFont, statusStr, CR_GRAY);

	VH_UpdateScreen();

	return hasSignon;
}

void I_ShutdownGraphics();

//
// Demote vid_renderer to software if the requested hardware renderer cannot be
// had on this machine. Only the setting used for this run is changed; the
// config keeps whatever the player chose.
//
static void CheckRendererAvailable()
{
	FString requested = vid_renderer;
	requested.ToLower();
	if(requested.Compare("opengl") != 0 && requested.Compare("gl") != 0)
		return;

#ifdef ECWOLF_RENDERER_OPENGL
	if(R_GLProbeAvailable())
		return;

	Printf("Renderer: no OpenGL 3.3 core context available on this display; "
		"using the software renderer.\n");
#else
	Printf("Renderer: this build has no OpenGL support; "
		"using the software renderer.\n");
#endif

	vid_renderer = "software";
}

static void InitGame()
{
	// initialize SDL
	{
		SDL_version ver;
#if SDL_VERSION_ATLEAST(2,0,0)
		SDL_GetVersion(&ver);
#else
		ver = *SDL_Linked_Version();
#endif
		printf("SDL_Init: Using SDL %d.%d.%d\n", ver.major, ver.minor, ver.patch);
	}

#if SDL_VERSION_ATLEAST(2,0,0)
	if(SDL_Init(0) < 0)
#else
	if(SDL_Init(SDL_INIT_VIDEO) < 0)
#endif
	{
		I_FatalError("Unable to init SDL: %s", SDL_GetError());
	}

	//
	// Mapinfo
	//

	V_InitFontColors();
	G_ParseMapInfo(true);

	//
	// Init texture manager
	//

	TexMan.Init();
	// The upscale pack is applied as the texture manager loads it; this puts the
	// textures back if the player has the option switched off.
	C7Upscale::ApplyPreference();
	printf("VL_ReadPalette: Setting up the Palette...\n");
	VL_ReadPalette(gameinfo.GamePalette);
	atterm(R_DeinitColormaps);
	GenerateLookupTables();

	//
	// Fonts
	//
	V_InitFonts();
	atterm(V_ClearFonts);

//
// load in and lock down some basic chunks
//

	BuildTables ();          // trig tables

	// OpenGL is the default renderer, so the machine has to be asked whether it
	// can actually provide one before the window is built. SDLFB reads
	// vid_renderer to decide whether to make the window GL-capable and to leave
	// out the SDL_Renderer the software path presents through, and that
	// decision cannot be revisited once the window exists. Demoting the setting
	// here keeps the two agreeing, and leaves the player's own choice intact in
	// the config -- a machine that gains a working driver gets GL back.
	CheckRendererAvailable();

	// Setup a temporary window so if we have to terminate we don't do extra mode sets
	VL_SetVGAPlaneMode (true);
	DrawStartupConsole("Initializing game engine");

//
// Load Actors
//

	ClassDef::LoadActors();
	atterm(CollectGC);

	// I_ShutdownGraphics needs to be run before the class definitions are unloaded.
	atterm (I_ShutdownGraphics);

	// Parse non-gameinfo sections in MAPINFO
	G_ParseMapInfo(false);

//
// Fonts
//
	VH_Startup ();
	IN_Startup ();
	SD_Startup ();

//
// Load Keys
//

	P_InitKeyMessages();
	atterm(P_DeinitKeyMessages);

//
// Finish with setting up through the config file.
//
	FinalReadConfig();

//
// Load the status bar
//
	CreateStatusBar();

//
// Load Noah's Ark quiz
//
	Dialog::LoadGlobalModule("NOAHQUIZ");

//
// Net game?
//
	// Giving up here leaves the mode back at single-player, so the game still
	// starts -- just not as a netgame. Better than a splash screen with no way
	// off it.
	if(!Net::Init(DrawNetworkStatus))
	{
		// Which is more use than "abandoned" on its own, and this is the one
		// place that knows the netgame is over before a level exists to say it
		// on.
		if(Net::Abandoned())
		{
			Printf("%s\n", Net::AbandonedReason());
			Net::ClearAbandoned();
		}
		Printf("Network game abandoned; starting single-player.\n");
	}
	NetWatch_Start();

//
// initialize the menusalcProjection
	printf("CreateMenus: Preparing the menu system...\n");
	CreateMenus();

//
// Finish signon screen
//
	VL_SetVGAPlaneMode();
	if(DrawStartupConsole("Initialization complete"))
	{
		if (!param_nowait)
			IN_UserInput(70*4, ACK_Any);
	}
	else // Delay for a moment to allow the user to enter the jukebox if desired
		IN_UserInput(16, ACK_Any);

//
// HOLDING DOWN 'M' KEY?
//
	IN_ProcessEvents();

	if (Keyboard[sc_M])
		DoJukebox();

//
// Select and initialize the renderer backend (software fallback guaranteed).
// atterm ordering is LIFO, so this runs before I_ShutdownGraphics at exit.
//
	R_InitRendererBackend();
	atterm(R_ShutdownRendererBackend);

#ifdef NOTYET
	vdisp = (byte *) (0xa0000+PAGE1START);
	vbuf = (byte *) (0xa0000+PAGE2START);
#endif
}

//===========================================================================

/*
==========================
=
= SetViewSize
=
==========================
*/

static void SetViewSize (unsigned int screenWidth, unsigned int screenHeight)
{
	statusbarx = 0;
	if(AspectCorrection[r_ratio].isWide)
		statusbarx = screenWidth*(48-AspectCorrection[r_ratio].multiplier)/(48*2);

	if(StatusBar)
	{
		statusbary1 = StatusBar->GetHeight(true);
		statusbary2 = 200 - StatusBar->GetHeight(false);
	}
	else
	{
		statusbary1 = 0;
		statusbary2 = 200;
	}

	statusbary1 = statusbary1*screenHeight/200;
	if(AspectCorrection[r_ratio].tallscreen)
		statusbary2 = ((statusbary2 - 100)*screenHeight*3)/AspectCorrection[r_ratio].baseHeight + screenHeight/2
			+ (screenHeight - screenHeight*AspectCorrection[r_ratio].multiplier/48)/2;
	else
		statusbary2 = statusbary2*screenHeight/200;

	unsigned int width;
	unsigned int height;
	if(viewsize == 21)
	{
		width = screenWidth;
		height = screenHeight;
	}
	else if(viewsize == 20)
	{
		width = screenWidth;
		height = statusbary2-statusbary1;
	}
	else
	{
		width = screenWidth - (20-viewsize)*16*screenWidth/320;
		height = (statusbary2-statusbary1+1) - (20-viewsize)*8*screenHeight/200;
	}

	// Some code assumes these are even.
	viewwidth = width&~1;
	viewheight = height&~1;
	centerx = viewwidth/2-1;
	centerxwide = AspectCorrection[r_ratio].isWide ? CorrectWidthFactor(centerx) : centerx;
	if((unsigned) viewheight == screenHeight)
		viewscreenx = viewscreeny = screenofs = 0;
	else
	{
		viewscreenx = (screenWidth-viewwidth) / 2;
		viewscreeny = (statusbary2+statusbary1-viewheight)/2;
		screenofs = viewscreeny*SCREENPITCH+viewscreenx;
	}

	int virtheight = screenHeight;
	int virtwidth = screenWidth;
	if(AspectCorrection[r_ratio].isWide)
		virtwidth = CorrectWidthFactor(virtwidth);
	else
		virtheight = CorrectWidthFactor(virtheight);
	yaspect = FixedMul((320<<FRACBITS)/200,(virtheight<<FRACBITS)/virtwidth);

	pspritexscale = (centerxwide<<FRACBITS)/160;
	pspriteyscale = FixedMul(pspritexscale, yaspect);

	//
	// calculate trace angles and projection constants
	//
	if(players[ConsolePlayer].mo)
		CalcProjection(players[ConsolePlayer].mo->radius);
	else
		CalcProjection (FOCALLENGTH);
}

void NewViewSize (int width, unsigned int scrWidth, unsigned int scrHeight)
{
	if(width < 4 || width > 21)
		return;

	viewsize = width;
	SetViewSize(scrWidth, scrHeight);
}



//===========================================================================

/*
==========================
=
= Quit
=
==========================
*/

void Quit ()
{
	EditorLink::SessionResult("quit");
	throw CNoRunExit();
}

void I_FatalError (const char *format, ...)
{
	va_list vlist;
	va_start(vlist, format);
	FString error;
	error.VFormat(format, vlist);
	va_end(vlist);

	// Told to the editor before it is thrown: the parent needs to know WHY the
	// process is about to end, and an exit code cannot say.
	EditorLink::Fatal(error.GetChars());
	EditorLink::SessionResult("fatal");
	throw CFatalError(error);
}

void I_Error(const char* format, ...)
{
	va_list vlist;
	va_start(vlist, format);
	FString error;
	error.VFormat(format, vlist);
	va_end(vlist);

	throw CRecoverableError(error);
}

//==========================================================================

static bool DebugNetwork = false;

void NetDPrintf(const char* format, ...)
{
	if(!DebugNetwork)
		return;

	va_list vlist;
	va_start(vlist, format);
	vprintf(format, vlist);
	va_end(vlist);
}

//==========================================================================

/*
==================
=
= PG13
=
==================
*/

static void PG13 (void)
{
	VW_FadeOut ();

	if(gameinfo.AdvisoryPic.IsEmpty())
		return;

	BYTE color = ColorMatcher.Pick(RPART(gameinfo.AdvisoryColor), GPART(gameinfo.AdvisoryColor), BPART(gameinfo.AdvisoryColor));

	VWB_Clear(color, 0, 0, screenWidth, screenHeight);
	FTexture *tex = TexMan(gameinfo.AdvisoryPic);
	if(tex->GetScaledWidth() == 320)
		VWB_DrawGraphic(tex, 0, 100-tex->GetScaledHeight()/2);
	else
		VWB_DrawGraphic(tex, 304-tex->GetScaledWidth(), 174-tex->GetScaledHeight());
	VW_UpdateScreen ();

	VW_FadeIn ();
	IN_UserInput (TICRATE * 7, ACK_Any);

	VW_FadeOut ();
}

//===========================================================================

////////////////////////////////////////////////////////
//
// NON-SHAREWARE NOTICE
//
////////////////////////////////////////////////////////
static void NonShareware (void)
{
	if(strlen(language["REGNOTICE_TITLE"]) == 0)
		return;

	VW_FadeOut ();

	ClearMScreen ();
	DrawStripes (10);

	PrintX = 110;
	PrintY = 15;

	pa = MENU_TOP;
	US_Print (BigFont, language["REGNOTICE_TITLE"], gameinfo.FontColors[GameInfo::MENU_HIGHLIGHTSELECTION]);
	pa = MENU_CENTER;

	WindowX = PrintX = 40;
	PrintY = 60;
	US_Print (BigFont, language["REGNOTICE_MESSAGE"], gameinfo.FontColors[GameInfo::MENU_SELECTION]);

	VW_UpdateScreen ();
	VW_FadeIn ();
	IN_Ack (ACK_Any);
}

//===========================================================================


/*
=====================
=
= DemoLoop
=
=====================
*/

static void DemoLoop()
{
//
// check for launch from ted
//
	if (param_tedlevel)
	{
		param_nowait = true;
		NewGame(param_difficulty,param_tedlevel,false,
			param_playerclass ? FName(param_playerclass) : NAME_None);
	}


//
// main game cycle
//

	if (!param_nowait && (IWad::GetGame().Flags & IWad::REGISTERED))
		NonShareware();

	if (!param_nowait)
		PG13 ();

	IntermissionInfo *demoLoop = IntermissionInfo::Find("DemoLoop");
	bool gotoMenu = false;
	while (1)
	{
		// The CD release opens with the Capstone logo and the story cinematic,
		// and they are part of the attract cycle rather than a one-off opening.
		// Timed under an instrumented DOSBox-X: the logo's first sound fires at
		// t=0, the cinematic's last at t=48.2, and the whole sequence begins
		// again at t=87.5 -- with the title and credit pages in between, which
		// is where the gap goes. Suppressed by --nowait like the advisory page.
		if (!param_nowait)
		{
			C7Flic_Play("SEQONE");
			C7Flic_Play("SEQTHREE");
		}

		// After the cinematics, not before them. The title theme is a
		// minute and six seconds of music for the title and credit pages;
		// starting it here used to mean it played under the Capstone logo
		// and the story cinematic, over their own dialogue, from the moment
		// the game opened.
		StartCPMusic(gameinfo.TitleMusic);

		while(!param_nowait && ShowIntermission(demoLoop, true))
		{
		}

		if(!param_tedlevel)
		{
			gotoMenu = false;

			// Silence anything still sounding before the menu opens. The
			// in-game route into the control panel has always done this
			// (wl_play.cpp); the attract loop never did, because nothing in it
			// made a noise. The cinematics do -- a line of dialogue outlasts
			// the animation that started it -- and it followed the player into
			// the menu.
			SD_StopDigitized();

			if (Keyboard[sc_Tab])
				RecordDemo ();
			else
				US_ControlPanel (0);
		}

		if (param_tedlevel || startgame || loadedgame)
		{
			param_tedlevel = NULL;
			if(GameLoop ())
				gotoMenu = true;

			// The floor's song does not follow the player out of the game.
			// StopMusic deliberately leaves the disc alone -- it has to, or
			// opening the control panel would restart the soundtrack every
			// time -- so leaving the game is the one place that has to say so
			// outright. Without this the level's track played on underneath
			// the menu, and then underneath the next game's.
			C7CD::Stop();
		}
	}
}


//===========================================================================

// CheckRatio -- From ZDoom
//
// Tries to guess the physical dimensions of the screen based on the
// screen's pixel dimensions.
int CheckRatio (int width, int height, int *trueratio)
{
	int fakeratio = -1;
	Aspect ratio;

	if (vid_aspect != ASPECT_NONE)
	{
		// [SP] User wants to force aspect ratio; let them.
		fakeratio = vid_aspect;
	}
	/*if (vid_nowidescreen)
	{
		if (!vid_tft)
		{
			fakeratio = 0;
		}
		else
		{
			fakeratio = (height * 5/4 == width) ? 4 : 0;
		}
	}*/
	if (abs (height * 32/9 - width) < 5)
	{
		ratio = ASPECT_32_9;
	}
	else if (abs (height * 64/27 - width) < 5 || abs (height * 43/18 - width) < 5)
	{
		ratio = ASPECT_64_27;
	}
	else if (abs (height * 16/9 - width) < 10) // If the size is approximately 16:9, consider it so.
	{
		ratio = ASPECT_16_9;
	}
	// Consider 17:10 as well.
	else if (abs (height * 17/10 - width) < 10)
	{
		ratio = ASPECT_17_10;
	}
	// 16:10 has more variance in the pixel dimensions. Grr.
	else if (abs (height * 16/10 - width) < 60)
	{
		// 320x200 and 640x400 are always 4:3, not 16:10
		if ((width == 320 && height == 200) || (width == 640 && height == 400))
		{
			ratio = ASPECT_NONE;
		}
		else
		{
			ratio = ASPECT_16_10;
		}
	}
	// Unless vid_tft is set, 1280x1024 is 4:3, not 5:4.
	else if (height * 5/4 == width)// && vid_tft)
	{
		ratio = ASPECT_5_4;
	}
	// Assume anything else is 4:3.
	else
	{
		ratio = ASPECT_4_3;
	}

	if (trueratio != NULL)
	{
		*trueratio = ratio;
	}
	return (fakeratio >= 0) ? fakeratio : ratio;
}

#define IFARG(str) if(!strcmp(arg, (str)))

static const char* CheckParameters(int argc, char *argv[], TArray<FString> &files)
{
	const char* extension = NULL;
	bool hasError = false, showHelp = false;
	bool sampleRateGiven = false, audioBufferGiven = false;
	int defaultSampleRate = param_samplerate;

	fullscreen = vid_fullscreen;

	for(int i = 1; i < argc; i++)
	{
		char *arg = argv[i];
		IFARG("--baby")
			param_difficulty = 0;
		else IFARG("--easy")
			param_difficulty = 1;
		else IFARG("--normal")
			param_difficulty = 2;
		else IFARG("--hard")
			param_difficulty = 3;
		else IFARG("--skill")
		{
			if(++i >= argc)
			{
				printf("The skill option is missing an argument!\n");
				hasError = true;
			}
			else
				// Guarded: without the else this read argv[argc] when --skill
				// was the last token on the line, which is one past the end.
				param_difficulty = atoi(argv[i])-1; // 1-based indexing
		}
		else IFARG("--nowait")
			param_nowait = true;
		else IFARG("--tedlevel")
		{
			if(++i >= argc)
			{
				printf("The tedlevel option is missing the level argument!\n");
				hasError = true;
			}
			else param_tedlevel = argv[i];
		}
		else IFARG("--fullscreen")
			fullscreen = true;
		else IFARG("--res")
		{
			if(i + 2 >= argc)
			{
				printf("The res option needs the width and/or the height argument!\n");
				hasError = true;
			}
			else
			{
				// --res names the window, as the video mode always has;
				// vid_renderscale then decides what is drawn inside it.
				windowWidth = atoi(argv[++i]);
				windowHeight = atoi(argv[++i]);
				if(windowWidth < 320)
					printf("Screen width must be at least 320!\n"), hasError = true;
				if(windowHeight < 200)
					printf("Screen height must be at least 200!\n"), hasError = true;
				VL_UpdateRenderSize();
			}
		}
		else IFARG("--aspect")
		{
			const char* ratio = argv[++i];
			if(strcmp(ratio, "4:3") == 0)
				vid_aspect = ASPECT_4_3;
			else if(strcmp(ratio, "16:10") == 0)
				vid_aspect = ASPECT_16_10;
			else if(strcmp(ratio, "17:10") == 0)
				vid_aspect = ASPECT_17_10;
			else if(strcmp(ratio, "16:9") == 0)
				vid_aspect = ASPECT_16_9;
			else if(strcmp(ratio, "5:4") == 0)
				vid_aspect = ASPECT_5_4;
			else if(strcmp(ratio, "21:9") == 0)
				vid_aspect = ASPECT_64_27;
			else
			{
				printf("Unknown aspect ratio %s!\n", ratio);
				hasError = true;
			}
		}
		else IFARG("--bits")
		{
			if(++i >= argc)
			{
				printf("The bits option is missing the color depth argument!\n");
				hasError = true;
			}
			else
			{
				screenBits = atoi(argv[i]);
				switch(screenBits)
				{
					case 8:
					case 16:
					case 24:
					case 32:
						break;

					default:
						printf("Screen color depth must be 8, 16, 24, or 32!\n");
						hasError = true;
						break;
				}
			}
		}
		else IFARG("--noadaptive")
			noadaptive = true;
		else IFARG("--extravbls")
		{
			if(++i >= argc)
			{
				printf("The extravbls option is missing the vbls argument!\n");
				hasError = true;
			}
			else
			{
				extravbls = atoi(argv[i]);
				if((signed)extravbls < 0)
				{
					printf("Extravbls must be positive!\n");
					hasError = true;
				}
			}
		}
		else IFARG("--joystick")
		{
			if(++i >= argc)
			{
				printf("The joystick option is missing the index argument!\n");
				hasError = true;
			}
			else param_joystickindex = atoi(argv[i]);   // index is checked in InitGame
		}
		else IFARG("--joystickhat")
		{
			if(++i >= argc)
			{
				printf("The joystickhat option is missing the index argument!\n");
				hasError = true;
			}
			else param_joystickhat = atoi(argv[i]);
		}
		else IFARG("--samplerate")
		{
			if(++i >= argc)
			{
				printf("The samplerate option is missing the rate argument!\n");
				hasError = true;
			}
			else param_samplerate = atoi(argv[i]);
			sampleRateGiven = true;
		}
		else IFARG("--audiobuffer")
		{
			if(++i >= argc)
			{
				printf("The audiobuffer option is missing the size argument!\n");
				hasError = true;
			}
			else param_audiobuffer = atoi(argv[i]);
			audioBufferGiven = true;
		}
		else IFARG("--help")
			showHelp = true;
		else IFARG("--data")
			if(++i >= argc)
			{
				printf("Expected main data extension!\n");
				hasError = true;
			}
			else
				extension = argv[i];
		else IFARG("--file")
		{
			if(++i < argc)
				files.Push(argv[i]);
		}
		else IFARG("--config")
		{
			// The config code will handle this itself, so ignore it here.
			++i;
		}
		else IFARG("--console") {} // Windows always create console parameter
		else IFARG("--savedir")
		{
			if(++i < argc)
				FileSys::SetDirectoryPath(FileSys::DIR_Saves, argv[i]);
		}
		else IFARG("--port")
		{
			if(++i < argc)
				Net::InitVars.port = atoi(argv[i]);
		}
		else IFARG("--netwatchdog")
		{
			// Says, every couple of seconds, which loop the game is in while
			// the playsim is not advancing. For chasing a netgame that stops.
			netwatchdog = true;
		}
		else IFARG("--net-delay")
		{
			// Tics of input delay; see docs/multiplayer.md. The setup menu
			// will set this once it exists, and it is here now so the gates
			// can measure it.
			if(++i < argc)
			{
				int delay = atoi(argv[i]);
				if(delay < 0) delay = 0;
				if(delay > 32) delay = 32;
				Net::InitVars.ticDelay = (byte)delay;
			}
		}
		else IFARG("--host")
		{
			if(++i < argc)
			{
				Net::InitVars.mode = Net::MODE_Host;
				Net::InitVars.numPlayers = atoi(argv[i]);
			}
		}
		else IFARG("--join")
		{
			if(++i < argc)
			{
				Net::InitVars.mode = Net::MODE_Client;
				Net::InitVars.joinAddress = argv[i];
			}
		}
		else IFARG("--playerclass")
		{
			if(i + 1 < argc)
				param_playerclass = argv[++i];
		}
		else IFARG("--battle")
		{
			Net::InitVars.gameMode = Net::GM_Battle;
		}
		else IFARG("--teams")
		{
			Net::InitVars.gameMode = Net::GM_TeamBattle;
		}
		else IFARG("--fraglimit")
		{
			if(i + 1 < argc)
			{
				const int limit = atoi(argv[++i]);
				Net::InitVars.fragLimit = (byte)(limit < 0 ? 0 : (limit > 255 ? 255 : limit));
			}
		}
		else IFARG("--debugnet")
		{
			DebugNetwork = true;
		}
		else IFARG("--foreignsave")
		{
			GameSave::param_foreginsave = true;
		}
		else IFARG("--vid-renderer")
		{
			// Read much earlier, before the first video mode is set, because
			// SDLFB needs to know whether to make a GL-capable window. That
			// scan only peeks; this is where the option and its value are
			// consumed, and without it both of them were handed to the wad
			// loader.
			++i;
		}
		else IFARG("--no-upscale") { /* also read early; peeked, not consumed */ }
		// The rest of the early scans, for the same reason. Each is a loop of
		// its own further up that reads argv without claiming anything, and
		// every one of them printed "Could not stat --gl-debug" on any run
		// that used it.
		else IFARG("--gl-debug") {}
		else IFARG("--gl-profile") {}
		else IFARG("--vis-diff") {}
		else IFARG("--gltest") { if(i + 1 < argc && argv[i+1][0] != '-') ++i; }
		else IFARG("--flictest") { ++i; }
		else IFARG("--netvectors") { ++i; }
		else IFARG("--sessiontest") {}
		else IFARG("--editor-capabilities") {}
		else if(EditorLink::ArgClaimed(i))
		{
			// --editor-protocol / --editor-session, read before anything is
			// initialized. Same rule as the capture options: the parser that
			// understood them records what it took, and this asks.
		}
		else if(Capture::ArgClaimed(i))
		{
			// The capture harness parsed this token, and its values, before we
			// got here -- Capture::ParseArgs runs first and records what it
			// took. This used to be a hand-written copy of that option list
			// kept purely so the harness's arguments were not misread as data
			// files, and it had drifted: fifteen of the thirty-three options
			// were missing, so each of them and its value reached the wad
			// loader and printed "Could not stat --capture-trace". Asking the
			// parser cannot drift, because there is only one parser.
		}
		else
			files.Push(argv[i]);
	}
	if(hasError || showHelp)
	{
		if(hasError) printf("\n");
		printf(
			"%s\n"
			"http://maniacsvault.net/ecwolf/\n"
			"Based on Wolf4SDL v1.7\n"
			"Ported by Chaos-Software (http://www.chaos-software.de.vu)\n"
			"Original Wolfenstein 3D by id Software\n\n"
			"Usage: " BINNAME " [options]\n"
			"Options:\n"
			" --help                 This help page\n"
#ifdef _WIN32
			" --console              Display a console window\n"
#endif
			" --config <file>        Use an explicit location for the config file\n"
			" --savedir <dir>        Use an explicit location for save games\n"
			" --file <file>          Loads an extra data file\n"
			" --data <extension>     Selects the given game data set skipping the dialog\n"
			" --tedlevel <level>     Starts the game in the given level\n"
			" --skill <#>            Sets the difficulty for tedlevel\n"
			" --baby                 Sets the difficulty to baby for tedlevel\n"
			" --easy                 Sets the difficulty to easy for tedlevel\n"
			" --normal               Sets the difficulty to normal for tedlevel\n"
			" --hard                 Sets the difficulty to hard for tedlevel\n"
			" --nowait               Skips intro screens\n"
			" --fullscreen           Starts the game in fullscreen mode\n"
			" --res <width> <height> Sets the screen resolution\n"
			" --aspect <aspect>      Sets the aspect ratio.\n"
			" --noadaptive           Disables adaptive tics.\n"
			" --bits <b>             Sets the screen color depth\n"
			"                        (use this when you have palette/fading problems\n"
			"                        allowed: 8, 16, 24, 32, default: \"best\" depth)\n"
			" --extravbls <vbls>     Sets a delay after each frame, which may help to\n"
			"                        reduce flickering (unit is currently 8 ms, default: 0)\n"
			" --joystick <index>     Use the index-th joystick if available\n"
			"                        (-1 to disable joystick, default: 0)\n"
			" --joystickhat <index>  Enables movement with the given coolie hat\n"
			" --samplerate <rate>    Sets the sound sample rate (given in Hz, default: %i)\n"
			" --audiobuffer <size>   Sets the size of the audio buffer (-> sound latency)\n"
			"                        (given in bytes, default: 2048 / (44100 / samplerate))\n"
			" --host <number>        Sets up a network game with the given number of players.\n"
			" --net-delay <tics>     Input delay for network play (0-32)\n"
			" --netwatchdog          Report which loop a stalled netgame is in\n"
			" --join <address>       Joins a network game coordinated by the given host.\n"
			" --port <number>        Port number to use for network communications.\n"
			" --battle               Player vs. player battle\n"
			" --debugnet             Enable network debugging messages.\n"
			" --foreignsave          Disable save game validity checking.\n"
			, GetGameCaption(), defaultSampleRate
		);
		Quit();
	}

	r_ratio = static_cast<Aspect>(CheckRatio(windowWidth, windowHeight));

	if(sampleRateGiven && !audioBufferGiven)
		param_audiobuffer = 2048 / (44100 / param_samplerate);

#ifdef __ANDROID__
	param_audiobuffer = (2048*2) / (44100 / param_samplerate);
#endif

	return extension;
}

#ifndef _WIN32
// I_MakeRNGSeed is from ZDoom
#include <time.h>

// Return a random seed, preferably one with lots of entropy.
unsigned int I_MakeRNGSeed()
{
	unsigned int seed;
	int file;

	// Try reading from /dev/urandom first, then /dev/random, then
	// if all else fails, use a crappy seed from time().
	seed = time(NULL);
	file = open("/dev/urandom", O_RDONLY);
	if (file < 0)
	{
		file = open("/dev/random", O_RDONLY);
	}
	if (file >= 0)
	{
		read(file, &seed, sizeof(seed));
		close(file);
	}
	return seed;
}
#else
unsigned int I_MakeRNGSeed();
#endif

/*
==========================
=
= main
=
==========================
*/

static void ScannerMessageHandler(Scanner::MessageLevel level, const char *error, va_list list)
{
	FString errorMessage;
	errorMessage.VFormat(error, list);

	if(level == Scanner::ERROR)
		throw CRecoverableError(errorMessage);
	else
		Printf("%s", errorMessage.GetChars());
}

// Basically from ZDoom
// We are definting an atterm function so that we can control the exit behavior.
static const unsigned int MAX_TERMS = 32;
static void (*TermFuncs[MAX_TERMS])(void);
static unsigned int NumTerms;
void atterm(void (*func)(void))
{
	for(unsigned int i = 0;i < NumTerms;++i)
	{
		if(TermFuncs[i] == func)
			return;
	}

	if(NumTerms < MAX_TERMS)
		TermFuncs[NumTerms++] = func;
	else
		fprintf(stderr, "Failed to register atterm function!\n");
}

static void CallTerminateFunctions()
{
	ShutdownId();
	WriteConfig();

	while(NumTerms > 0)
		TermFuncs[--NumTerms]();

	SDL_Quit();
}

#ifdef _WIN32
void I_AcknowledgeError();
#endif

int WL_Main (int argc, char *argv[])
{
	try
	{
		// Stop the C library from screwing around with its functions according
		// to the system locale.
		setlocale(LC_ALL, "C");

		FileSys::SetupPaths(argc, argv);

		Capture::ParseArgs(argc, argv); // deterministic capture/checksum harness

		// Standalone FLIC decode. Runs before any game data is opened and
		// exits, so it needs neither a Corridor 7 installation nor a window.
		// Answers with no game data present, because the editor asks what this
		// build supports before it knows whether the data it has is usable.
		{
			int probeExit = 0;
			if(EditorLink::RunCapabilityProbe(argc, argv, probeExit))
				return probeExit;
		}
		EditorLink::ParseArgs(argc, argv);

		for(int fi = 1; fi + 1 < argc; ++fi)
		{
			if(strcmp(argv[fi], "--flictest") == 0)
				return C7Flic_SelfTest(argv[fi + 1]);
		}

		// The packet layout this build actually speaks. Data-free and
		// windowless, like --flictest, because the gate that reads it runs
		// before anything is loaded.
		for(int ni = 1; ni + 1 < argc; ++ni)
		{
			if(strcmp(argv[ni], "--netvectors") == 0)
				return Net::WriteProtocolVectors(argv[ni + 1]);
		}

		// The session model, checked against sessions this build cannot yet
		// play: an authority that owns no player, a slot 0 owned by somebody
		// who is not the authority. Also data-free -- it touches no player
		// array, which is most of what it is proving.
		for(int si = 1; si < argc; ++si)
		{
			if(strcmp(argv[si], "--sessiontest") == 0)
				return Session::SelfTest();
		}

#ifdef ECWOLF_RENDERER_OPENGL
		// Standalone GL device + indexed-palette pipeline self-test. Runs before
		// the game window is created and exits, so it is headless-safe.
		for(int gi = 1; gi < argc; ++gi)
		{
			if(strcmp(argv[gi], "--gltest") == 0)
			{
				const char *out = (gi + 1 < argc) ? argv[gi + 1] : NULL;
				const bool ok = R_GLRunSelfTest(out);
				SDL_Quit();
				return ok ? 0 : 1;
			}
		}
#endif

		// Find the program directory.
		FString progdir(FileSys::GetDirectoryPath(FileSys::DIR_Program));

		Scanner::SetMessageHandler(ScannerMessageHandler);

		printf("ReadConfig: Reading the Configuration.\n");
		config.LocateConfigFile(argc, argv);
		ReadConfig();

		// Command-line renderer override (used by the headless GL tests; the
		// config's Vid_Renderer is the normal path). Must run before the first
		// video mode is set so SDLFB can create a GL-capable window. Only
		// vid_renderer is set, not vid_renderer_requested, so a test run pinned
		// to one renderer does not rewrite the player's config on exit.
		for(int i = 1; i < argc - 1; ++i)
		{
			if(strcmp(argv[i], "--vid-renderer") == 0)
			{
				vid_renderer = argv[i + 1];
				Printf("Renderer: command-line override -> %s\n",
					vid_renderer.GetChars());
				break;
			}
		}
		// Ignore any upscaled asset pack sitting beside the game data. The
		// regression gates run from the player's own data directory, so a pack
		// installed there would silently change the art every one of them
		// measures -- and it would override the texture filter that the
		// filtering gate exists to vary.
		for(int i = 1; i < argc; ++i)
		{
			if(strcmp(argv[i], "--no-upscale") == 0)
			{
				// Deliberately does not touch vid_upscaled_assets: that is what
				// gets written back on exit, and a test run must not turn the
				// player's pack off for them. With no pack loaded the setting
				// has nothing to act on anyway.
				C7Upscale::Disable();
				break;
			}
		}
		// GL debug output / error checking (KHR_debug). Off by default; opt in via
		// the config's Vid_GLDebug or this flag. Must be set before the GL context
		// is created so the debug context hint can be requested.
		for(int i = 1; i < argc; ++i)
		{
			if(strcmp(argv[i], "--gl-debug") == 0)
			{
				vid_gldebug = true;
				Printf("Renderer: GL debug output enabled (command line).\n");
				break;
			}
		}
		// Per-frame GL timing breakdown. Separate from --gl-debug: that one
		// enables synchronous driver diagnostics, which would distort exactly
		// the numbers this reports.
		for(int i = 1; i < argc; ++i)
		{
			if(strcmp(argv[i], "--gl-profile") == 0)
			{
				vid_glprofile = true;
				Printf("Renderer: GL frame profiling enabled (command line).\n");
				break;
			}
		}
		// Run both cell-visibility traversals each frame and tally the
		// difference. Costs a full extra raycast per frame, so it is a
		// measurement mode, not something to leave on.
		for(int i = 1; i < argc; ++i)
		{
			if(strcmp(argv[i], "--vis-diff") == 0)
			{
				r_visdiff = true;
				Printf("Renderer: portal/raycaster visibility comparison enabled.\n");
				break;
			}
		}

		{
			TArray<FString> wadfiles, files;

			Printf("IWad: Selecting base game data.\n");
			const char* extension = CheckParameters(argc, argv, wadfiles);
			EditorLink::DataSelected(extension ? extension : "-",
				progdir.GetChars());
			IWad::SelectGame(files, extension, MAIN_PK3, progdir);

			for(unsigned int i = 0;i < wadfiles.Size();++i)
				files.Push(wadfiles[i]);

			// Normalize path separators as ZDoom code expects
			for(unsigned int i = 0;i < files.Size();++i)
				files[i].ReplaceChars('\\', '/');

			printf("W_Init: Init WADfiles.\n");
			// Every file that reached the loader reports itself from inside
			// AddFile, success or failure -- "did it load MY map" is the
			// question a playtest most needs answered, and only the loader
			// knows the answer.
			Wads.InitMultipleFiles(files);
			LumpRemapper::RemapAll();
			language.SetupStrings();
		}

		// Reports whether the player's ripped CD soundtrack was found, before
		// anything can ask to play music.
		C7CD::Init();

		// Checks the upscaled asset pack, before the texture manager consumes
		// it in InitGame() below.
		C7Upscale::Init();

		// Reports whether the CD cinematics were extracted, on the same footing
		// as the soundtrack above: both are content that only exists if the
		// player has been pointed at their disc.
		C7Flic_Init();

		R_InitRenderer();

		printf("InitGame: Setting up the game...\n");
		rngseed = I_MakeRNGSeed(); // May change after initializing a net game
		Capture::OverrideRNGSeed(rngseed); // deterministic capture runs pin the seed
		InitGame();

		FRandom::StaticClearRandom();

		printf("DemoLoop: Starting the game loop...\n");
		DemoLoop();

		I_FatalError("Demo loop exited???");
	}
	catch(CNoRunExit) // Normal exit from deep code
	{
		// Every ordinary exit converges here, so this is where the editor is
		// told the session is over. Quit() says so too and says it earlier; a
		// second one is harmless and the parent takes the first, whereas a
		// session that ends with no closing event at all leaves it waiting.
		EditorLink::SessionResult("exit");
		CallTerminateFunctions();
		return 0;
	}
	catch(CDoomError &error)
	{
		// A CRecoverableError that reached here killed the process -- "Could
		// not find map MAP99!" is one, and it never passes through
		// I_FatalError. Without this the stream simply stopped, which is the
		// one thing a parent cannot tell apart from a hang.
		EditorLink::Fatal(error.GetMessage());
		EditorLink::SessionResult("error");
		CallTerminateFunctions();

#ifdef __ANDROID__
		Printf("%s\n", error.GetMessage());
#else
		fprintf(stderr, "%s\n", error.GetMessage());
#endif

#ifdef _WIN32
		I_AcknowledgeError();
#endif

		return 1;
	}
	return 1;
}
