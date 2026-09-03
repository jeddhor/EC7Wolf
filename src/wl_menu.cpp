////////////////////////////////////////////////////////////////////
//
// WL_MENU.C
// by John Romero (C) 1992 Id Software, Inc.
//
////////////////////////////////////////////////////////////////////

#include "m_classes.h"
#include "m_random.h"
#include "wl_def.h"
#include "g_session.h"
#include "wl_menu.h"
#include "wl_iwad.h"
#include "c7_cdaudio.h"
#include "c7_upscale.h"
#include "id_ca.h"
#include "id_sd.h"
#include "id_in.h"
#include "id_vl.h"
#include "id_vh.h"
#include "id_us.h"
#include "language.h"
#include "w_wad.h"
#include "c_cvars.h"
#include "g_mapinfo.h"
#include "v_video.h"
#include "wl_agent.h"
#include "wl_inter.h"
#include "wl_draw.h"
#include "wl_game.h"
#include "wl_net.h"
#include "net_watchdog.h"
#include "c7_menu.h"
#include "wl_play.h"
#include "wl_text.h"
#include "v_palette.h"
#include "colormatcher.h"
#include "v_font.h"
#include "templates.h"
#include "thingdef/thingdef.h"
#include "wl_loadsave.h"
#include "am_map.h"
#include "r_artscale.h"

#include <climits>

static int	lastgamemusicoffset;
static FName playerClass = NAME_None;
EpisodeInfo	*episode = 0;
int BORDCOLOR, BORD2COLOR, BORD3COLOR, BKGDCOLOR, STRIPE, STRIPEBG,
	MENUWIN_BACKGROUND, MENUWIN_TOPBORDER, MENUWIN_BOTBORDER,
	MENUWINHGLT_BACKGROUND, MENUWINHGLT_TOPBORDER, MENUWINHGLT_BOTBORDER;
static MenuItem	*readThis;
// Android version reads this elsewhere so non-static.
bool menusAreFaded = true;

EMenuStyle MenuStyle = MENUSTYLE_Wolf;

MENU_LISTENER(EnterControlBase);
MENU_LISTENER(JoinNetGame);

// --- Multiplayer setup ------------------------------------------------------
//
// Corridor 7's CD release shipped network play and this port has never offered
// it. The engine underneath has always had it; only the way in was missing.
// See docs/multiplayer.md.
//
// Internet only: the original also spoke IPX and modem, which solve a 1994
// problem that no machine running this still has.
static TextInputMenuItem *mpAddressItem = NULL;
static TextInputMenuItem *mpPortItem = NULL;
static MultipleChoiceMenuItem *mpRoleItem = NULL;
static MultipleChoiceMenuItem *mpPlayersItem = NULL;
static MultipleChoiceMenuItem *mpModeItem = NULL;
static MultipleChoiceMenuItem *mpDelayItem = NULL;
static MenuItem *mpStartItem = NULL;

// Tics of input delay behind each "connection" choice. Zero exchanges the tic
// about to run and waits for everyone, which is right on a LAN and unusable
// across the internet; the rest give the round trip that many tics to complete
// in. Measured at an 80ms round trip: 8.6 tics a second at zero against 21.4
// at eight.
static const int mpDelayTics[] = { 0, 6, 10, 16 };
static MultipleChoiceMenuItem *mpArenaItem = NULL;
static MultipleChoiceMenuItem *mpFragsItem = NULL;
static MultipleChoiceMenuItem *mpClassItem = NULL;
// Kept in the same order as the characters option list, and in the order
// MAPINFO lists the player classes -- which is also the order that decides
// which side you are on in team play.
static const char* const mpClassNames[] = { "C7Player", "C7AlienPlayer" };
// Kept in the same order as the fraglimits option list.
static const int mpFragLimits[] = { 0, 10, 20, 30, 50 };
// Eight arenas, and not the contiguous run the compendium describes: the maps
// it puts at 58 and 59 are empty boxes, and the eighth real arena is at 60.
// See the note above the network levels in mapinfo/corridor7.txt.
static const char* const mpArenaMaps[] = {
	"MAP51", "MAP52", "MAP53", "MAP54", "MAP55", "MAP56", "MAP57", "MAP60"
};

MENU_LISTENER(MultiplayerRoleChanged);
MENU_LISTENER(StartMultiplayer);

Menu mainMenu(MENU_X, MENU_Y, MENU_W, 24);
Menu optionsMenu(80, 80, 190, 28);
Menu soundBase(24, 45, 284, 24);
Menu controlBase(CTL_X, CTL_Y, CTL_W, 56, EnterControlBase);
Menu displayMenu(20, 75, 285, 56);
Menu automapMenu(40, 55, 260, 56);
Menu mouseSensitivity(20, 50, 300, 24);
Menu joySensitivity(20, 30, 300, 24);
Menu playerClasses(NM_X, NM_Y, NM_W, 24);
Menu episodes(NE_X+4, NE_Y-1, NE_W+7, 83);
Menu skills(NM_X, NM_Y, NM_W, 24);
Menu multiplayerMenu(NM_X, NM_Y, NM_W + 60, 100);
Menu controls(15, 70, 310, 24);
Menu resolutionMenu(90, 25, 150, 24);
Menu advancedGraphics(20, 60, 285, 56);

MENU_LISTENER(PlayDemosOrReturnToGame)
{
	Menu::closeMenus();
	if (!ingame)
		StartCPMusic(gameinfo.TitleMusic);
	return true;
}
MENU_LISTENER(ViewScoresOrEndGame)
{
	if (ingame)
	{
		if(CP_EndGame(0))
			Menu::closeMenus();
	}
	else
	{
		if (gameinfo.TrackHighScores == true && Session::TracksHighScores())
		{
			MenuFadeOut();

			StartCPMusic(gameinfo.ScoresMusic);

			DrawHighScores();
			VW_UpdateScreen();
			MenuFadeIn();

			IN_Ack(ACK_Local);

			StartCPMusic(gameinfo.MenuMusic);
			MenuFadeOut();
			mainMenu.draw();
			MenuFadeIn ();
		}
	}
	return true;
}
// Corridor 7's main menu splits ECWolf's dual-purpose entries: HIGH SCORES
// always shows the table and ABORT CURRENT MISSION always ends the game.
MENU_LISTENER(C7ViewHighScores)
{
	if (gameinfo.TrackHighScores == true && Session::TracksHighScores())
	{
		MenuFadeOut();

		StartCPMusic(gameinfo.ScoresMusic);

		DrawHighScores();
		VW_UpdateScreen();
		MenuFadeIn();

		IN_Ack(ACK_Local);

		StartCPMusic(gameinfo.MenuMusic);
		MenuFadeOut();
		mainMenu.draw();
		MenuFadeIn ();
	}
	return true;
}
// Starting a new mission throws away the one in progress, so the released game
// asks first -- the port went straight to the rank screen and the running game
// was gone. Wired as the switcher's activate listener, which cancels the switch
// when it returns false.
MENU_LISTENER(C7ConfirmNewMission)
{
	if(!ingame)
		return true;
	if(Confirm(language["STR_C7NEWGAME"]))
		return true;
	mainMenu.draw();
	return false;
}

MENU_LISTENER(C7AbortMission)
{
	if (ingame)
	{
		if(CP_EndGame(0))
			Menu::closeMenus();
	}
	return true;
}
// Corridor 7 does not just cut to DOS: it holds a full-screen sign-off page
// (C7G0013) for a moment, then fades that out and exits. Stretched to fill the
// window at any resolution rather than sitting native-size in a corner.
static void Corridor7ExitScreen()
{
	FTexture *page = TexMan(TexMan.CheckForTexture("C7G0013", FTexture::TEX_Any));
	if(page == NULL)
		return;

	// Upscaled like the menu splash: this is 320x200 art shown across the whole
	// window, so it is magnified more than anything else the game draws.
	page = R_UpscaledArt(page);

	VW_FadeOut();
	screen->Lock(true);
	// Sized in real pixels rather than through the 320x200 virtual space, since
	// the upscaled page is no longer 320x200 and would be drawn several times
	// too large if its own dimensions were read as virtual units.
	screen->DrawTexture(page, 0, 0,
		DTA_DestWidth, SCREENWIDTH, DTA_DestHeight, SCREENHEIGHT,
		DTA_TopOffset, 0, DTA_LeftOffset, 0, TAG_DONE);
	screen->Unlock();
	VW_UpdateScreen();
	VW_FadeIn();

	// Long enough to read, and interruptible so a keypress does not feel stuck.
	IN_ClearKeysDown();
	IN_UserInput(TICRATE*2, ACK_Local);

	VW_FadeOut();
}

MENU_LISTENER(QuitGame)
{
	FString endString = gameinfo.QuitMessages[M_Random()%gameinfo.QuitMessages.Size()];
	if(endString[0] == '$')
		endString = language[endString.Mid(1)];

	if(Confirm(endString))
	{
		VW_UpdateScreen();
		SD_MusicOff();
		SD_StopSound();
		if(!menusAreFaded)
			MenuFadeOut();
		else
			VW_FadeOut();
		if(IWad::CheckGameFilter("Corridor7"))
			Corridor7ExitScreen();
		Quit();
	}

	// special case
	if(which != -1)
		mainMenu.draw();
	return false;
}
MENU_LISTENER(SetSoundEffects)
{
	SDMode modes[3] = { sdm_Off, sdm_PC, sdm_AdLib };
	if(SoundMode != modes[which])
	{
		SD_WaitSoundDone();
		SD_SetSoundMode(modes[which]);
	}
	return true;
}
MENU_LISTENER(SetDigitalSound)
{
	if(DigiMode != (which == 0 ? sds_Off : sds_SoundBlaster))
		SD_SetDigiDevice(which == 0 ? sds_Off : sds_SoundBlaster);
	return true;
}
MENU_LISTENER(SetMusic)
{
	if(MusicMode != (SMMode)which)
	{
		SD_SetMusicMode((SMMode)which);
		if(which != smm_Off)
			StartCPMusic(gameinfo.MenuMusic);
	}
	return true;
}
// Corridor 7 with a ripped soundtrack installed: None / AdLib / CD Audio.
//
// Switching has to silence whichever device was playing, or a ten-minute CD
// track carries on underneath the AdLib song that just started -- the two share
// one output, but not one code path.
MENU_LISTENER(SetMusicC7)
{
	const bool wantCD = (which == 2);

	if(which == 0)
	{
		C7CD::Stop();
		SD_SetMusicMode(smm_Off);
		return true;
	}

	snd_cdmusic = wantCD;
	if(MusicMode == smm_Off)
		SD_SetMusicMode(smm_AdLib);

	if(wantCD)
	{
		SD_MusicOff();			// stop the AdLib song
		C7CD::StartLevelTrack();	// and put the disc on straight away
	}
	else
	{
		C7CD::Stop();
		StartCPMusic(gameinfo.MenuMusic);
	}
	return true;
}

MENU_LISTENER(EnterControlBase)
{
	controlBase[2]->setEnabled(mouseenabled);
	controlBase[3]->setEnabled(mouseenabled);
	controlBase[4]->setEnabled(mouseenabled);
	controlBase[5]->setEnabled(IN_JoyPresent());
	controlBase[6]->setEnabled(IN_JoyPresent() && joystickenabled);
	controlBase.draw();

	IN_AdjustMouse();

	return true;
}

MENU_LISTENER(SetPlayerClassAndSwitch)
{
	playerClass = gameinfo.PlayerClasses[which];

	return true;
}
MENU_LISTENER(SetPlayerClassAndJoin)
{
	SetPlayerClassAndSwitch(which);
	return JoinNetGame(which);
}
MENU_LISTENER(SetEpisodeAndSwitchToSkill)
{
	EpisodeInfo &ep = EpisodeInfo::GetEpisode(which);

	if(!GameMap::CheckMapExists(ep.StartMap))
	{
		SD_PlaySound("player/usefail");
		Message("Please select \"Read This!\"\n"
				"from the Options menu to\n"
				"find out how to order this\n" "episode from Apogee.");
		IN_ClearKeysDown();
		IN_Ack(ACK_Local);
		episodes.draw();
		return false;
	}

	if(ingame)
	{
		if(!Confirm(language["CURGAME"]))
		{
			episodes.draw();
			return false;
		}
	}

	episode = &ep;
	return true;
}
MENU_LISTENER(StartNewGame)
{
	const SkillInfo &si = SkillInfo::GetSkill(which);
	if(si.MustConfirm.IsNotEmpty())
	{
		if(!Confirm(si.MustConfirm))
			return false;
	}

	if(episode == NULL)
		episode = &EpisodeInfo::GetEpisode(0);

	Menu::closeMenus();
	NewGame(which, episode->StartMap, true, playerClass);

	//
	// CHANGE "READ THIS!" TO NORMAL COLOR
	//
	if(readThis)
		readThis->setHighlighted(false);

	return true;
}
MENU_LISTENER(JoinNetGame)
{
	Menu::closeMenus();
	NewGame(0, "", true);

	//
	// CHANGE "READ THIS!" TO NORMAL COLOR
	//
	if(readThis)
		readThis->setHighlighted(false);

	return true;
}
// Only a client needs somewhere to connect to; only a host decides how many
// are playing. Showing both to both is how a setup screen ends up asking a
// question that has no answer.
MENU_LISTENER(MultiplayerRoleChanged)
{
	const bool joining = (mpRoleItem != NULL && mpRoleItem->getCurrentOption() == 1);
	if(mpAddressItem)
		mpAddressItem->setEnabled(joining);
	if(mpPlayersItem)
		mpPlayersItem->setEnabled(!joining);
	if(mpModeItem)
		mpModeItem->setEnabled(!joining);
	if(mpArenaItem)
		mpArenaItem->setEnabled(!joining);
	if(mpFragsItem)
		mpFragsItem->setEnabled(!joining);
	return true;
}

// Net::Init reports progress through this while it waits for the other
// players.
//
// It used to hand the string to Message(), the bitmap window the engine has
// always used for "press Y to quit". That box is the wrong instrument for this
// in three separate ways: it is set in the 320x200 bitmap font while every
// other screen the player has just been looking at is not, it sizes itself to
// its text and then clips whatever exceeds 310 virtual pixels -- so the line
// explaining what to check ran off the edge -- and it only repaints when
// something calls it, which made the spinner move in whatever steps the socket
// poll happened to take. A player who has just come from the setup screen
// deserves the screen they came from.
static bool MultiplayerStatus(const Net::InitStatus &status)
{
	const bool hosting = (status.phase == Net::InitStatus::PHASE_Hosting);

	FString detail;
	if(hosting)
		detail.Format("Listening on %s", status.detail.GetChars());
	else
		detail.Format("Connecting to %s", status.detail.GetChars());

	// Said only once it has been long enough to be worth saying. Before that it
	// is ordinary waiting and an explanation would be noise.
	const char *note = NULL;
	if(status.seconds >= 10)
	{
		note = hosting
			? "Nobody has connected yet. If the other players are not on this "
			  "network, your router must forward UDP on this port to this "
			  "machine."
			: "No answer yet. Check the address, and that the host has "
			  "forwarded this port to their machine.";
	}

	C7WaitingRow rows[MAXPLAYERS];
	int rowCount = 0;
	for(unsigned int i = 0;i < status.peers.Size() && rowCount < MAXPLAYERS;++i)
	{
		rows[rowCount].label = status.peers[i].name.GetChars();
		rows[rowCount].value = status.peers[i].state.GetChars();
		++rowCount;
	}

	if(!C7Menu_DrawWaiting(hosting ? "Hosting" : "Joining", detail, note,
		status.seconds, rows, rowCount))
	{
		// Every other game keeps the box it has always had.
		Message(detail.GetChars());
	}

	// Waiting is the one screen in the game with no way out of its own: the
	// loop below belongs to the network code, so nothing was reading the
	// keyboard and Escape did nothing. On a phone that is worse, because there
	// is no keyboard to press and the back button reaches the same nothing.
	// Read events here, where the wait is actually being drawn.
	IN_ProcessEvents();
	if(LastScan == sc_Escape || Keyboard[sc_Escape])
	{
		LastScan = sc_None;
		return false;
	}
	return true;
}

MENU_LISTENER(StartMultiplayer)
{
	const bool joining = (mpRoleItem != NULL && mpRoleItem->getCurrentOption() == 1);

	// Only a player joining has an address to read, and a host's is empty by
	// definition -- so this used to run over an empty string on the way to
	// hosting as well as on the way to a mistyped join.
	FString address = mpAddressItem ? mpAddressItem->getValue() : "";
	address.StripLeftRight();
	if(joining && address.IsEmpty())
	{
		Confirm("Enter the address of the machine hosting the game.");
		return false;
	}

	int port = mpPortItem ? atoi(mpPortItem->getValue()) : NET_DEFAULT_PORT;
	if(port <= 0 || port > 65535)
		port = NET_DEFAULT_PORT;

	Net::InitVars.ticDelay = (byte)mpDelayTics[mpDelayItem ? mpDelayItem->getCurrentOption() : 0];

	// The address the player typed is kept whole, port and all: Net::StartJoin
	// reads "host:port" itself, and it is the destination rather than the
	// local bind that --port sets.
	static FString joinTarget;
	if(joining)
	{
		joinTarget = address;
		if(joinTarget.IndexOf(':') == -1)
			joinTarget.AppendFormat(":%d", port);

		Net::InitVars.mode = Net::MODE_Client;
		Net::InitVars.joinAddress = joinTarget.GetChars();
		Net::InitVars.numPlayers = 1;   // the host's sync says how many really

		// A client binds any free local port. InitVars.port is the socket it
		// opens, not the one it talks to -- the destination is in the address
		// above -- and binding the host's port would stop two players sharing
		// a machine, or sitting behind one router.
		Net::InitVars.port = 0;
	}
	else
	{
		Net::InitVars.port = (uint16_t)port;
		Net::InitVars.mode = Net::MODE_Host;
		Net::InitVars.numPlayers = (byte)(2 + (mpPlayersItem ? mpPlayersItem->getCurrentOption() : 0));
		switch(mpModeItem ? mpModeItem->getCurrentOption() : 0)
		{
			default: Net::InitVars.gameMode = Net::GM_Battle; break;
			case 1:  Net::InitVars.gameMode = Net::GM_TeamBattle; break;
			case 2:  Net::InitVars.gameMode = Net::GM_Cooperative; break;
		}
		Net::InitVars.fragLimit =
			(byte)mpFragLimits[mpFragsItem ? mpFragsItem->getCurrentOption() : 0];
	}

	// Connecting blocks until everyone is present, drawing through the same
	// callback the startup path uses -- unless the player gives up, in which
	// case they land back on the setup screen with what they typed still in
	// it, rather than in a game nobody joined.
	if(!Net::Init(MultiplayerStatus))
		return false;

	// From here on a stall is a netgame stall, and worth being able to see.
	NetWatch_Start();

	// One map for everybody, and it is the host's. Net::NewGame exchanges the
	// name and keeps the arbiter's, so a client deliberately names nothing
	// rather than guessing at an arena it would only be overruled about.
	FString arena;
	if(!joining)
	{
		const int pick = mpArenaItem ? mpArenaItem->getCurrentOption() : 0;
		arena = mpArenaMaps[pick];
	}

	const FName character =
		mpClassNames[mpClassItem ? mpClassItem->getCurrentOption() : 0];

	Menu::closeMenus();
	// No briefing: an arena has no story to open with, and the text screen
	// would be one player reading while the rest of the game waits.
	NewGame(gd_medium, arena, false, character);

	if(readThis)
		readThis->setHighlighted(false);

	return true;
}
MENU_LISTENER(ReadThis)
{
	MenuFadeOut();
	StartCPMusic(gameinfo.FinaleMusic);
	HelpScreens();
	StartCPMusic(gameinfo.MenuMusic);
	mainMenu.draw();
	MenuFadeIn();
	return true;
}
MENU_LISTENER(ToggleFullscreen)
{
	VL_SetFullscreen(vid_fullscreen);
	displayMenu.draw();

	IN_AdjustMouse();

	return true;
}
MENU_LISTENER(ToggleVsync)
{
	screen->SetVSync(vid_vsync);
	return true;
}
static const int kMaxFPSValues[] = { 0, 60, 75, 120, 144, 165, 240 };
static const float kFOVValues[] = { 60.0f, 72.0f, 90.0f, 100.0f, 110.0f, 120.0f };
static const float kGammaValues[] = { 0.75f, 1.0f, 1.25f, 1.5f, 1.75f, 2.0f };

// Returns the index of the option matching the live value, so a menu opens
// showing what is actually set rather than always showing the first choice.
template<typename T, int N>
static int NearestOption(const T (&values)[N], T current)
{
	int best = 0;
	double bestDist = -1;
	for(int i = 0;i < N;++i)
	{
		const double dist = fabs((double)values[i] - (double)current);
		if(bestDist < 0 || dist < bestDist)
		{
			bestDist = dist;
			best = i;
		}
	}
	return best;
}

MENU_LISTENER(SetRenderer)
{
	// Read once before the first video mode is set, so this cannot take effect
	// until the game is next started. Saying so beats silently doing nothing.
	// Both, so the choice survives into the config even on a machine whose
	// startup demoted vid_renderer for want of a GL context.
	vid_renderer = vid_renderer_requested = which == 0 ? "opengl" : "software";
	return true;
}

// Kept in the same order as glMSAAOptions.
static const int kGLMSAAValues[] = { 0, 2, 4, 8 };

MENU_LISTENER(SetGLFilter)
{
	// Read by the world shader each frame, so this takes effect immediately.
	vid_glfilter = which;
	return true;
}

MENU_LISTENER(SetGLMSAA)
{
	// The world framebuffer is rebuilt when the sample count changes, which
	// EnsureWorldFbo notices on the next frame.
	vid_glmsaa = kGLMSAAValues[which];
	return true;
}

MENU_LISTENER(SetMaxFPS)
{
	vid_maxfps = kMaxFPSValues[which];
	return true;
}

// Kept in the same order as xbrzOptions below: Off, Auto, then the fixed
// factors, which are the values vid_xbrz itself stores.
static const int kXBRZValues[] = { 0, 1, 2, 3, 4, 5, 6 };

// The two scaling options turn each other off, so each has to be able to move
// the other's row. Both are NULL outside the Corridor 7 menu, which does not
// build them.
static MultipleChoiceMenuItem *xbrzItem = NULL;
static MultipleChoiceMenuItem *upscaleItem = NULL;
static MultipleChoiceMenuItem *glFilterItem = NULL;

MENU_LISTENER(SetXBRZ)
{
	// Takes effect on the next presented frame; the upscaled texture is
	// reallocated by the present path when the factor it was built for changes.
	vid_xbrz = kXBRZValues[which];

	// Running an edge filter over art a neural network already enlarged four
	// times has nothing left to find -- the staircases it looks for are gone --
	// and it costs a full frame of work per frame to say so.
	if(vid_xbrz != 0 && C7Upscale::Enabled())
	{
		C7Upscale::SetEnabled(false);
		if(upscaleItem)
			upscaleItem->setCurrentOption(0);
	}
	return true;
}

MENU_LISTENER(SetUpscaledAssets)
{
	C7Upscale::SetEnabled(which != 0);
	vid_upscaled_assets = C7Upscale::Enabled();

	if(vid_upscaled_assets && vid_xbrz != 0)
	{
		vid_xbrz = 0;
		if(xbrzItem)
			xbrzItem->setCurrentOption(0);
	}

	// Nearest sampling and a four-times pack are a bad pair, and the pack is the
	// half that just changed. See C7Upscale::WantedFilter().
	const int filter = C7Upscale::WantedFilter(vid_glfilter);
	if(filter != vid_glfilter)
	{
		vid_glfilter = filter;
		if(glFilterItem)
			glFilterItem->setCurrentOption(filter);
	}
	return true;
}

// Kept in the same order as renderScaleOptions below.
static const int kRenderScaleValues[] = { 1, 2, 3, 4 };

MENU_LISTENER(SetRenderScale)
{
	if(vid_renderscale == kRenderScaleValues[which])
		return true;
	vid_renderscale = kRenderScaleValues[which];

	// A different render size is a different framebuffer, so this goes through
	// the same mode set the resolution menu does rather than taking effect at
	// present time the way xBRZ can.
	MenuFadeOut();
	VL_UpdateRenderSize();
	VH_Startup();	// fizzlefade tables are sized to the frame
	VL_SetVGAPlaneMode();
	MenuFadeIn();
	return true;
}

MENU_LISTENER(SetFOV)
{
	localDesiredFOV = kFOVValues[which];
	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		players[i].SetFOV(localDesiredFOV);
	return true;
}

MENU_LISTENER(SetGamma)
{
	screenGamma = kGammaValues[which];
	screen->SetGamma(screenGamma);
	return true;
}

MENU_LISTENER(SetAspectRatio)
{
	vid_aspect = static_cast<Aspect>(which);
	r_ratio = static_cast<Aspect>(CheckRatio(screenWidth, screenHeight));
	NewViewSize(viewsize);
	displayMenu.draw();
	return true;
}

// Dummy screen sizes to pass when windowed
MENU_LISTENER(EnterResolutionSelection);
MENU_LISTENER(SetResolution)
{
	MenuFadeOut();

	{
		int width, height;
		bool lb;
		Video->StartModeIterator(DisplayBits, vid_fullscreen);
		for(int i = 0;i <= which;++i)
			Video->NextMode(&width, &height, &lb);
		windowWidth = width;
		windowHeight = height;
		VL_UpdateRenderSize();

		if(vid_fullscreen)
		{
			fullScreenWidth = windowWidth;
			fullScreenHeight = windowHeight;
		}
		else
		{
			windowedScreenWidth = windowWidth;
			windowedScreenHeight = windowHeight;
		}
	}

	r_ratio = static_cast<Aspect>(CheckRatio(windowWidth, windowHeight));
	VH_Startup(); // Recalculate fizzlefade stuff.
	VL_SetVGAPlaneMode();
	EnterResolutionSelection(which);
	resolutionMenu.draw();
	MenuFadeIn();
	return true;
}
MENU_LISTENER(EnterResolutionSelection)
{
	int selected = 0;
	resolutionMenu.clear();
	FString resolution;

	{
		int width, height;
		bool lb;
		Video->StartModeIterator(DisplayBits, vid_fullscreen);
		while(Video->NextMode(&width, &height, &lb))
		{
			resolution.Format("%dx%d", width, height);
			MenuItem *item = new MenuItem(resolution, SetResolution);
			resolutionMenu.addItem(item);

			// The list is a list of window sizes, so it highlights against the
			// window, not against SCREENWIDTH -- which is the render size and
			// smaller than any entry once vid_renderscale is above 1.
			if((unsigned)width == windowWidth && (unsigned)height == windowHeight)
			{
				selected = resolutionMenu.countItems()-1;
				item->setHighlighted(true);
			}
		}
	}

	resolutionMenu.setCurrentPosition(selected);
	return true;
}

MENU_LISTENER(ChangeAutomapFlag)
{
	AM_UpdateFlags();
	return true;
}
MENU_LISTENER(ChangeAMOverlay)
{
	am_overlay = which;
	AM_UpdateFlags();
	return true;
}
MENU_LISTENER(ChangeAMRotate)
{
	am_rotate = which;
	AM_UpdateFlags();
	return true;
}
MENU_LISTENER(AdjustViewSize)
{
	NewViewSize(viewsize);
	return true;
}

// Adds an item with an explicit row label. Multiple-choice and slider items
// keep their current value in the text a label/value skin would otherwise use,
// so they have to be told what to call themselves.
static MenuItem *AddLabeled(Menu &menu, MenuItem *item, const char *label)
{
	item->setLabel(label);
	menu.addItem(item);
	return item;
}

// The multiplayer setup screen: who you are, where they are, and how forgiving
// the connection needs to be.
static void BuildMultiplayerMenu()
{
	static const char* roles[] = { "Host a game", "Join a game" };
	static const char* players[] = { "2", "3", "4", "5", "6", "7", "8" };
	static const char* modes[] = { "Battle", "Team battle", "Cooperative" };
	// Named for what a player can judge rather than for tics, which mean
	// nothing to anyone who has not read the netcode.
	static const char* connections[] = { "Same building", "Good", "Average",
	                                     "Poor" };

	multiplayerMenu.setHeadText("Multiplayer", true);

	// setLabel, not setText: a multiple-choice item puts its current value in
	// the text, so a row labeled with setText renames itself to its own value
	// the first time it is changed -- "Host a game    Host a game".
	static const char* arenas[] = { "Level 1", "Level 2", "Level 3", "Level 4",
	                                "Level 5", "Level 6", "Level 7", "Level 8" };
	static const char* fraglimits[] = { "None", "10", "20", "30", "50" };
	static const char* characters[] = { "Marine", "Eitak warrior" };

	mpRoleItem = new MultipleChoiceMenuItem(MultiplayerRoleChanged, roles, 2, 1);
	AddLabeled(multiplayerMenu, mpRoleItem, "Role");

	// Never disabled alongside the host-only rows: your character is yours
	// whether you are hosting or joining, and in team play it is also which
	// side you are on.
	mpClassItem = new MultipleChoiceMenuItem(NULL, characters, 2, 0);
	AddLabeled(multiplayerMenu, mpClassItem, "Character");

	mpAddressItem = new TextInputMenuItem("", 39, NULL, NULL, true);
	AddLabeled(multiplayerMenu, mpAddressItem, "Server address");

	mpPortItem = new TextInputMenuItem("5029", 5, NULL, NULL, true);
	AddLabeled(multiplayerMenu, mpPortItem, "Port");

	mpPlayersItem = new MultipleChoiceMenuItem(NULL, players, 7, 0);
	AddLabeled(multiplayerMenu, mpPlayersItem, "Players");

	mpModeItem = new MultipleChoiceMenuItem(NULL, modes, 3, 0);
	AddLabeled(multiplayerMenu, mpModeItem, "Game");

	mpFragsItem = new MultipleChoiceMenuItem(NULL, fraglimits, 5, 2);
	AddLabeled(multiplayerMenu, mpFragsItem, "Frag limit");

	mpArenaItem = new MultipleChoiceMenuItem(NULL, arenas, 8, 0);
	AddLabeled(multiplayerMenu, mpArenaItem, "Arena");

	mpDelayItem = new MultipleChoiceMenuItem(NULL, connections, 4, 2);
	AddLabeled(multiplayerMenu, mpDelayItem, "Connection");

	multiplayerMenu.addItem(new LabelMenuItem(""));

	mpStartItem = new MenuItem("Start", StartMultiplayer);
	multiplayerMenu.addItem(mpStartItem);

	// Open on the server address: joining is the default role, and the address
	// is the one row a joining player must fill in. Counted rather than named,
	// so it moves when the rows above it do -- Role, Character, then this.
	multiplayerMenu.setCurrentPosition(2);
	MultiplayerRoleChanged(0);
}

void CreateMenus()
{
	// HACK: Determine menu style by IWAD
	if(IWad::CheckGameFilter("Blake"))
		MenuStyle = MENUSTYLE_Blake;
	else if(IWad::CheckGameFilter("Corridor7"))
		MenuStyle = MENUSTYLE_Corridor7;

	// Extract the palette
	BORDCOLOR = ColorMatcher.Pick(RPART(gameinfo.MenuColors[0]), GPART(gameinfo.MenuColors[0]), BPART(gameinfo.MenuColors[0]));
	BORD2COLOR = ColorMatcher.Pick(RPART(gameinfo.MenuColors[1]), GPART(gameinfo.MenuColors[1]), BPART(gameinfo.MenuColors[1]));
	BORD3COLOR = ColorMatcher.Pick(RPART(gameinfo.MenuColors[2]), GPART(gameinfo.MenuColors[2]), BPART(gameinfo.MenuColors[2]));
	BKGDCOLOR = ColorMatcher.Pick(RPART(gameinfo.MenuColors[3]), GPART(gameinfo.MenuColors[3]), BPART(gameinfo.MenuColors[3]));
	STRIPE = ColorMatcher.Pick(RPART(gameinfo.MenuColors[4]), GPART(gameinfo.MenuColors[4]), BPART(gameinfo.MenuColors[4]));
	STRIPEBG = ColorMatcher.Pick(RPART(gameinfo.MenuColors[5]), GPART(gameinfo.MenuColors[5]), BPART(gameinfo.MenuColors[5]));
	MENUWIN_BACKGROUND = ColorMatcher.Pick(RPART(gameinfo.MenuWindowColors[0]), GPART(gameinfo.MenuWindowColors[0]), BPART(gameinfo.MenuWindowColors[0])),
	MENUWIN_TOPBORDER = ColorMatcher.Pick(RPART(gameinfo.MenuWindowColors[1]), GPART(gameinfo.MenuWindowColors[1]), BPART(gameinfo.MenuWindowColors[1])),
	MENUWIN_BOTBORDER = ColorMatcher.Pick(RPART(gameinfo.MenuWindowColors[2]), GPART(gameinfo.MenuWindowColors[2]), BPART(gameinfo.MenuWindowColors[2])),
	MENUWINHGLT_BACKGROUND = ColorMatcher.Pick(RPART(gameinfo.MenuWindowColors[3]), GPART(gameinfo.MenuWindowColors[3]), BPART(gameinfo.MenuWindowColors[3])),
	MENUWINHGLT_TOPBORDER = ColorMatcher.Pick(RPART(gameinfo.MenuWindowColors[4]), GPART(gameinfo.MenuWindowColors[4]), BPART(gameinfo.MenuWindowColors[4])),
	MENUWINHGLT_BOTBORDER = ColorMatcher.Pick(RPART(gameinfo.MenuWindowColors[5]), GPART(gameinfo.MenuWindowColors[5]), BPART(gameinfo.MenuWindowColors[5]));

	// Actually initialize the menus
	GameSave::InitMenus();

	// Keep menus legible for games whose data does not provide the Wolf3D
	// picture headings. setHeadPicture replaces this text when it finds one.
	mainMenu.setHeadText("Main Menu", true);
	mainMenu.setHeadPicture("M_OPTION");

	const bool useEpisodeMenu = EpisodeInfo::GetNumEpisodes() > 1;
	if(MenuStyle == MENUSTYLE_Corridor7)
	{
		// The released game shipped this screen as one picture with its labels
		// painted in. The new shell draws the labels itself, so the picture is
		// gone and the items carry real text again.
		//
		// Nomenclature is the original's: it says Mission and Building, never
		// Game and Quit, and the difficulty ladder is a rank.
		mainMenu.setEscapeSound("");

		// No character menu here, even though there are now two characters.
		// The campaign is the Marine's: the manual sends a special-forces
		// Marine down to restore contact, and no briefing, line of dialogue or
		// ending accommodates anybody else. The second class exists for
		// multiplayer, which is where 9.5 puts the choice and where the setup
		// screen offers it -- so New Mission still goes straight to the rank
		// ladder rather than asking single player a question it has no use for.
		if(!Net::IsArbiter())
			mainMenu.addItem(new MenuItem("New Mission", JoinNetGame));
		else if(useEpisodeMenu)
			mainMenu.addItem(new MenuSwitcherMenuItem("New Mission", episodes, C7ConfirmNewMission));
		else
			mainMenu.addItem(new MenuSwitcherMenuItem("New Mission", skills, C7ConfirmNewMission));

		// The released game stores and retrieves missions; it never says save
		// or load. The items themselves are the engine's own.
		MenuItem *store = GameSave::GetSaveMenuItem();
		MenuItem *retrieve = GameSave::GetLoadMenuItem();
		store->setText("Store Mission");
		retrieve->setText("Retrieve Mission");
		mainMenu.addItem(store);
		mainMenu.addItem(retrieve);
		mainMenu.addItem(new MenuSwitcherMenuItem("Options", optionsMenu));
		mainMenu.addItem(new MenuItem("Resume Current Mission", PlayDemosOrReturnToGame));
		mainMenu.addItem(new MenuItem("Abort Current Mission", C7AbortMission));
		mainMenu.addItem(new MenuItem("High Scores", C7ViewHighScores));
		mainMenu.addItem(new MenuItem("Exit Building", QuitGame));
	}
	else
	{
	if(gameinfo.PlayerClasses.Size() > 1)
		mainMenu.addItem(new MenuSwitcherMenuItem(language["STR_NG"], playerClasses));
	else if(!Net::IsArbiter())
		mainMenu.addItem(new MenuItem(language["STR_NG"], JoinNetGame));
	else if(useEpisodeMenu)
		mainMenu.addItem(new MenuSwitcherMenuItem(language["STR_NG"], episodes));
	else
		mainMenu.addItem(new MenuSwitcherMenuItem(language["STR_NG"], skills));

	mainMenu.addItem(new MenuSwitcherMenuItem(language["STR_OPTIONS"], optionsMenu));
	mainMenu.addItem(GameSave::GetLoadMenuItem());
	mainMenu.addItem(GameSave::GetSaveMenuItem());
	readThis = new MenuItem(language["STR_RT"], ReadThis);
	readThis->setVisible(gameinfo.DrawReadThis);
	readThis->setHighlighted(true);
	mainMenu.addItem(readThis);
	mainMenu.addItem(new MenuItem(language["STR_VS"], ViewScoresOrEndGame));
	mainMenu.addItem(new MenuItem(language["STR_BD"], PlayDemosOrReturnToGame));
	mainMenu.addItem(new MenuItem(language["STR_QT"], QuitGame));
	}

	playerClasses.setHeadText(language["STR_PLAYERCLASS"]);
	for(unsigned int i = 0;i < gameinfo.PlayerClasses.Size();++i)
	{
		const ClassDef *cls = ClassDef::FindClass(gameinfo.PlayerClasses[i]);
		const char* displayName = cls->Meta.GetMetaString(APMETA_DisplayName);
		if(!displayName)
			I_FatalError("Player class %s has no display name.", cls->GetName().GetChars());
		if(Net::IsArbiter())
			playerClasses.addItem(new MenuSwitcherMenuItem(displayName, useEpisodeMenu ? episodes : skills, SetPlayerClassAndSwitch));
		else
			playerClasses.addItem(new MenuItem(displayName, SetPlayerClassAndJoin));
	}

	episodes.setHeadText(language["STR_WHICHEPISODE"]);
	for(unsigned int i = 0;i < EpisodeInfo::GetNumEpisodes();++i)
	{
		EpisodeInfo &episode = EpisodeInfo::GetEpisode(i);
		MenuItem *tmp = new MenuSwitcherMenuItem(episode.EpisodeName, skills, SetEpisodeAndSwitchToSkill);
		if(!episode.EpisodePicture.IsEmpty())
			tmp->setPicture(episode.EpisodePicture);
		if(!GameMap::CheckMapExists(episode.StartMap))
			tmp->setHighlighted(2);
		episodes.addItem(tmp);
	}

	skills.setHeadText(language[IWad::CheckGameFilter("Corridor7")
		? "STR_C7RANK" : "STR_HOWTOUGH"]);
	skills.setHeadPicture("M_HOWTGH", true);
	for(unsigned int i = 0;i < SkillInfo::GetNumSkills();++i)
	{
		SkillInfo &skill = SkillInfo::GetSkill(i);
		MenuItem *tmp = new MenuItem(skill.Name, StartNewGame);
		if(!skill.SkillPicture.IsEmpty())
			tmp->setPicture(skill.SkillPicture, NM_X + 185, NM_Y + 7);
		skills.addItem(tmp);
	}
	skills.setCurrentPosition(2);

	// Multiplayer sits under the difficulty ladder, behind a section heading
	// so the two are plainly different kinds of choice: the rows above pick
	// how hard a single-player mission is, and this one does not start a
	// mission at all.
	//
	// LabelMenuItem is drawn by the Corridor 7 shell as small dim capitals
	// over a hairline, which is exactly the separation wanted, and by the
	// stock menu as a heading -- so this reads correctly in both.
	if(IWad::CheckGameFilter("Corridor7"))
	{
		skills.addItem(new LabelMenuItem("Network"));
		skills.addItem(new MenuSwitcherMenuItem("Multiplayer", multiplayerMenu));
	}

	BuildMultiplayerMenu();

	optionsMenu.setHeadText(language["STR_OPTIONS"], true);
	optionsMenu.setHeadPicture("M_OPTION");
	if(MenuStyle == MENUSTYLE_Corridor7)
	{
		// Four categories under one Options screen, so the main menu stays
		// short. The submenus themselves are the engine's existing ones -- only
		// the grouping and the titles change.
		optionsMenu.addItem(new MenuSwitcherMenuItem("Automap", automapMenu));
		optionsMenu.addItem(new MenuSwitcherMenuItem("Graphics", displayMenu));
		optionsMenu.addItem(new MenuSwitcherMenuItem("Audio", soundBase));
		optionsMenu.addItem(new MenuSwitcherMenuItem("Controls", controlBase));

	}
	else
	{
	optionsMenu.addItem(new MenuSwitcherMenuItem(language["STR_CL"], controlBase));
	optionsMenu.addItem(new MenuSwitcherMenuItem(language["STR_SD"], soundBase));
	optionsMenu.addItem(new MenuSwitcherMenuItem(language["STR_DISPLAY"], displayMenu));
	optionsMenu.addItem(new MenuSwitcherMenuItem(language["STR_AMOPTIONS"], automapMenu));
	}

	// Collect options and defaults
	const char* soundEffectsOptions[] = {language["STR_NONE"], language["STR_PC"], language["STR_ALSB"] };
	const char* digitizedOptions[] = {language["STR_NONE"], language["STR_SB"] };
	const char* musicOptions[] = { language["STR_NONE"], language["STR_ALSB"], language["STR_MIDI"] };
	if(!AdLibPresent && !SoundBlasterPresent)
	{
		soundEffectsOptions[2] = NULL;
		musicOptions[1] = NULL;
	}
	if(!SoundBlasterPresent)
		digitizedOptions[1] = NULL;
	int soundEffectsMode = 0;
	int digitizedMode = 0;
	int musicMode = 0;
	switch(SoundMode)
	{
		default: soundEffectsMode = 0; break;
		case sdm_PC: soundEffectsMode = 1; break;
		case sdm_AdLib: soundEffectsMode = 2; break;
	}
	switch(DigiMode)
	{
		default: digitizedMode = 0; break;
		case sds_SoundBlaster: digitizedMode = 1; break;
	}
	switch(MusicMode)
	{
		default: musicMode = 0; break;
		case smm_AdLib: musicMode = 1; break;
		case smm_Midi: musicMode = 2; break;
	}
	soundBase.setHeadText(language["STR_SOUNDCONFIG"]);
	AddLabeled(soundBase, new LabelMenuItem(language["STR_DIGITALDEVICE"]), "Digital Sound");
	AddLabeled(soundBase, new MultipleChoiceMenuItem(SetDigitalSound, digitizedOptions, 2, digitizedMode), "Device");
	AddLabeled(soundBase, new SliderMenuItem(SoundVolume, 150, MAX_VOLUME, language["STR_SOFT"], language["STR_LOUD"]), "Volume");
	AddLabeled(soundBase, new LabelMenuItem(language["STR_ADLIBDEVICE"]), "Sound Effects");
	AddLabeled(soundBase, new MultipleChoiceMenuItem(SetSoundEffects, soundEffectsOptions, 3, soundEffectsMode), "Device");
	AddLabeled(soundBase, new SliderMenuItem(AdlibVolume, 150, MAX_VOLUME, language["STR_SOFT"], language["STR_LOUD"], SD_UpdatePCSpeakerVolume), "Volume");
	AddLabeled(soundBase, new LabelMenuItem(language["STR_MUSICDEVICE"]), "Music");
	if(C7CD::Present())
	{
		// The disc's soundtrack is a device like any other once it is installed,
		// so it belongs here rather than being an invisible override. It stays
		// the default when present -- that is what the CD release did -- but the
		// player can drop back to the AdLib score without deleting the rip.
		static const char *c7MusicOptions[] = { "None", "AdLib/SB", "CD Audio" };
		AddLabeled(soundBase, new MultipleChoiceMenuItem(SetMusicC7,
			c7MusicOptions, 3,
			MusicMode == smm_Off ? 0 : (snd_cdmusic ? 2 : 1)), "Device");
	}
	else
		AddLabeled(soundBase, new MultipleChoiceMenuItem(SetMusic, musicOptions, 3, musicMode), "Device");
	AddLabeled(soundBase, new SliderMenuItem(MusicVolume, 150, MAX_VOLUME, language["STR_SOFT"], language["STR_LOUD"], SD_UpdateMusicVolume), "Volume");

	controlBase.setHeadText(language["STR_CL"], true);
	controlBase.setHeadPicture("M_CONTRL");
	controlBase.addItem(new BooleanMenuItem(language["STR_ALWAYSRUN"], alwaysrun, EnterControlBase));
	controlBase.addItem(new BooleanMenuItem(language["STR_MOUSEEN"], mouseenabled, EnterControlBase));
	controlBase.addItem(new BooleanMenuItem(language["STR_WINDOWEDMOUSE"], forcegrabmouse, EnterControlBase));
	controlBase.addItem(new BooleanMenuItem(language["STR_MOUSEMOVE"], mousemovesforward, EnterControlBase));
	controlBase.addItem(new MenuSwitcherMenuItem(language["STR_SENS"], mouseSensitivity));
	controlBase.addItem(new BooleanMenuItem(language["STR_JOYEN"], joystickenabled, EnterControlBase));
	controlBase.addItem(new MenuSwitcherMenuItem(language["STR_JOYSENS"], joySensitivity));
	controlBase.addItem(new MenuSwitcherMenuItem(language["STR_CUSTOM"], controls));
	controlBase.addItem(new BooleanMenuItem(language["STR_ESCQUIT"], quitonescape));

	joySensitivity.setHeadText(language["STR_JOYSENS"]);
	for(int i = 0;i < JoyNumAxes;++i)
	{
		FString label;
		if(i < 4)
		{
			static const char AxisNames[4] = { 'X', 'Y', 'Z', 'R' };
			label.Format("%c Axis", AxisNames[i]);
		}
		else
			label.Format("Axis %d", i+1);

		joySensitivity.addItem(new LabelMenuItem(label));
		joySensitivity.addItem(new SliderMenuItem(JoySensitivity[i].sensitivity, 164, 30, language["STR_SLOW"], language["STR_FAST"]));
		joySensitivity.addItem(new SliderMenuItem(JoySensitivity[i].deadzone, 150, 20, language["STR_SMALL"], language["STR_LARGE"]));
	}

	const char* aspectOptions[] = {"Aspect: Auto", "Aspect: 16:9", "Aspect: 16:10", "Aspect: 17:10", "Aspect: 4:3", "Aspect: 5:4", "Aspect: 21:9", "Aspect: 32:9"};
	displayMenu.setHeadText(language["STR_DISPLAY"]);
	if(MenuStyle == MENUSTYLE_Corridor7)
	{
		// Built in its own order rather than appended to the generic list: the
		// settings below were never exposed by a menu before, and tacking them
		// on the end put them under the Screen Size heading, which has nothing
		// to do with them. Only Corridor 7 is reordered, so no other game's
		// menu shifts underneath it.
		static const char *rendererOptions[] = { "OpenGL", "Software" };
		static const char *maxFPSOptions[] = { "Unlimited", "60", "75", "120", "144", "165", "240" };
		static const char *fovOptions[] = { "60", "72", "90", "100", "110", "120" };
		static const char *gammaOptions[] = { "0.75", "1.00", "1.25", "1.50", "1.75", "2.00" };

		AddLabeled(displayMenu, new MultipleChoiceMenuItem(SetRenderer, rendererOptions, 2,
			vid_renderer.CompareNoCase("opengl") == 0 ? 0 : 1), "Renderer");
#ifndef __ANDROID__
		AddLabeled(displayMenu, new BooleanMenuItem(language["STR_FULLSCREEN"], vid_fullscreen, ToggleFullscreen), "Fullscreen");
#endif
		displayMenu.addItem(new MenuSwitcherMenuItem("Screen Resolution", resolutionMenu, EnterResolutionSelection));
		AddLabeled(displayMenu, new MultipleChoiceMenuItem(SetAspectRatio, aspectOptions, 8, vid_aspect), "Aspect Ratio");
#if SDL_VERSION_ATLEAST(2,0,0)
		AddLabeled(displayMenu, new BooleanMenuItem(language["STR_VSYNC"], vid_vsync, ToggleVsync), "Vertical Sync");
#endif
		AddLabeled(displayMenu, new MultipleChoiceMenuItem(SetMaxFPS, maxFPSOptions, 7,
			NearestOption(kMaxFPSValues, vid_maxfps)), "Frame Rate Limit");
		AddLabeled(displayMenu, new MultipleChoiceMenuItem(SetFOV, fovOptions, 6,
			NearestOption(kFOVValues, localDesiredFOV)), "Field of View");
		AddLabeled(displayMenu, new MultipleChoiceMenuItem(SetGamma, gammaOptions, 6,
			NearestOption(kGammaValues, screenGamma)), "Brightness");
		AddLabeled(displayMenu, new SliderMenuItem(viewsize, 110, 21, language["STR_SMALL"], language["STR_LARGE"], AdjustViewSize), "View Size");
		displayMenu.addItem(new MenuSwitcherMenuItem("Advanced Graphics", advancedGraphics));

		static const char *xbrzOptions[] = { "Off", "Auto", "2x", "3x", "4x", "5x", "6x" };
		static const char *renderScaleOptions[] = { "Native", "1/2", "1/3", "1/4" };
		// "Sharp" rather than "Off" because nearest is a deliberate look here,
		// not the absence of a feature -- it is what the game shipped as.
		static const char *glFilterOptions[] = { "Sharp", "Bilinear", "Smooth" };
		static const char *glMSAAOptions[] = { "Off", "2x", "4x", "8x" };

		static const char *upscaleOptions[] = { "Off", "On" };
		// Disabled rows, so the option is visible and says why it cannot be
		// used rather than vanishing and leaving the player wondering whether
		// the game noticed their pack at all.
		static const char *upscaleMissing[] = { "Not Installed" };
		static const char *upscaleBroken[] = { "Pack Incomplete" };

		advancedGraphics.setHeadText("Advanced Graphics");
		advancedGraphics.addItem(new LabelMenuItem("Image Scaling"));

		// First, because it replaces the art the rest of this section filters:
		// it is a different and better answer to the same question, and turning
		// it on makes the row below it moot.
		if(C7Upscale::Valid())
		{
			upscaleItem = new MultipleChoiceMenuItem(SetUpscaledAssets,
				upscaleOptions, 2, C7Upscale::Enabled() ? 1 : 0);
			AddLabeled(advancedGraphics, upscaleItem, "Upscaled Assets");
		}
		else
		{
			MenuItem *unavailable = AddLabeled(advancedGraphics,
				new MultipleChoiceMenuItem(NULL,
					C7Upscale::Present() ? upscaleBroken : upscaleMissing, 1, 0),
				"Upscaled Assets");
			unavailable->setEnabled(false);
		}

		// Sits above xBRZ because it is what gives xBRZ anything to do: the
		// filter enlarges the frame to fit the window, so at Native -- where the
		// frame already is the window -- there is nothing to enlarge into and it
		// costs a frame of work to hand back the picture unchanged.
		AddLabeled(advancedGraphics, new MultipleChoiceMenuItem(SetRenderScale,
			renderScaleOptions, 4,
			NearestOption(kRenderScaleValues, vid_renderscale)), "Render Resolution");
		// Both renderers filter now: the software path on the CPU at scanout, the
		// OpenGL path as a shader over the composited frame (render/opengl/
		// r_glxbrz.cpp). The setting means the same thing to each and picks the
		// same factor for a given window, so it is not qualified by renderer.
		xbrzItem = new MultipleChoiceMenuItem(SetXBRZ, xbrzOptions, 7,
			NearestOption(kXBRZValues, vid_xbrz));
		AddLabeled(advancedGraphics, xbrzItem, "xBRZ Smoothing");

		// OpenGL only: both of these live in the world shader and the world
		// framebuffer, neither of which the software raycaster has.
		advancedGraphics.addItem(new LabelMenuItem("Hardware Renderer"));
		glFilterItem = new MultipleChoiceMenuItem(SetGLFilter,
			glFilterOptions, 3, clamp(vid_glfilter, 0, 2));
		AddLabeled(advancedGraphics, glFilterItem, "Texture Filter");
		AddLabeled(advancedGraphics, new MultipleChoiceMenuItem(SetGLMSAA,
			glMSAAOptions, 4, NearestOption(kGLMSAAValues, vid_glmsaa)),
			"Antialiasing");

		advancedGraphics.addItem(new LabelMenuItem("Motion"));
		AddLabeled(advancedGraphics, new BooleanMenuItem("Motion Interpolation", r_interpolate), "Motion Interpolation");
		AddLabeled(advancedGraphics, new BooleanMenuItem("Camera", r_interpolate_camera), "Camera");
		AddLabeled(advancedGraphics, new BooleanMenuItem("Actors", r_interpolate_actors), "Actors");
		AddLabeled(advancedGraphics, new BooleanMenuItem("Doors & Pushwalls", r_interpolate_dynamicwalls), "Doors & Pushwalls");
		advancedGraphics.addItem(new LabelMenuItem("Diagnostics"));
		AddLabeled(advancedGraphics, new BooleanMenuItem("GL Debug Output", vid_gldebug), "GL Debug Output");
	}
	else
	{
#ifndef __ANDROID__
	displayMenu.addItem(new BooleanMenuItem(language["STR_FULLSCREEN"], vid_fullscreen, ToggleFullscreen));
#endif
#if SDL_VERSION_ATLEAST(2,0,0)
	displayMenu.addItem(new BooleanMenuItem(language["STR_VSYNC"], vid_vsync, ToggleVsync));
#endif
	AddLabeled(displayMenu, new MultipleChoiceMenuItem(SetAspectRatio, aspectOptions, 8, vid_aspect), "Aspect Ratio");
	displayMenu.addItem(new MenuSwitcherMenuItem(language["STR_SELECTRES"], resolutionMenu, EnterResolutionSelection));
	displayMenu.addItem(new LabelMenuItem(language["STR_SCREENSIZE"]));
	AddLabeled(displayMenu, new SliderMenuItem(viewsize, 110, 21, language["STR_SMALL"], language["STR_LARGE"], AdjustViewSize), "View Size");
	}


	resolutionMenu.setHeadText(language["STR_SELECTRES"]);

	mouseSensitivity.setHeadText(language["STR_MOUSEADJ"]);
	mouseSensitivity.addItem(new LabelMenuItem(language["STR_MOUSEXADJ"]));
	mouseSensitivity.addItem(new SliderMenuItem(mousexadjustment, 173, 20, language["STR_SLOW"], language["STR_FAST"]));
	mouseSensitivity.addItem(new LabelMenuItem(language["STR_MOUSEYADJ"]));
	mouseSensitivity.addItem(new SliderMenuItem(mouseyadjustment, 173, 20, language["STR_SLOW"], language["STR_FAST"]));

	mouseSensitivity.addItem(new LabelMenuItem(language["STR_PANXADJ"]));
	mouseSensitivity.addItem(new SliderMenuItem(panxadjustment, 173, 20, language["STR_SLOW"], language["STR_FAST"]));
	mouseSensitivity.addItem(new LabelMenuItem(language["STR_PANYADJ"]));
	mouseSensitivity.addItem(new SliderMenuItem(panyadjustment, 173, 20, language["STR_SLOW"], language["STR_FAST"]));


	controls.setHeadText(language["STR_CUSTOM"], true);
	controls.setHeadPicture("M_CUSTOM");
	controls.showControlHeaders(true);
	for(int i = 0;controlScheme[i].button != bt_nobutton;i++)
	{
		controls.addItem(new ControlMenuItem(controlScheme[i]));
	}

	const char* rotateOptions[] = { language["STR_AMROTATEOFF"], language["STR_AMROTATEON"], language["STR_AMROTATEOVERLAY"] };
	const char* overlayOptions[] = { language["STR_AMOVERLAYOFF"], language["STR_AMOVERLAYON"], language["STR_AMOVERLAYBOTH"] };
	automapMenu.setHeadText(language["STR_AMOPTIONS"]);

	if(MenuStyle == MENUSTYLE_Corridor7)
	{
		// Applied last on purpose: every menu above sets its own generic title,
		// so anything assigned earlier is overwritten before it is ever drawn.
		optionsMenu.setHeadText("Options");
		// "Automap", not "Gameplay": every item on this menu is an automap
		// setting, and calling it Gameplay promised options that were never
		// there. They apply to the full-viewport automap (bound to F1), not to
		// Corridor 7's own inset floor-plan panel, which is drawn by
		// c7_automap.cpp and reads none of these.
		automapMenu.setHeadText("Automap");
		displayMenu.setHeadText("Graphics");
		soundBase.setHeadText("Audio");
		controlBase.setHeadText("Controls");
		controls.setHeadText("Controls");
		resolutionMenu.setHeadText("Resolution");
		mouseSensitivity.setHeadText("Mouse Sensitivity");
		joySensitivity.setHeadText("Joystick Sensitivity");
		skills.setHeadText("Choose Your Rank");
		episodes.setHeadText("Choose Your Mission");
	}
	AddLabeled(automapMenu, new MultipleChoiceMenuItem(ChangeAMOverlay, overlayOptions, 3, am_overlay), "Map Overlay");
	AddLabeled(automapMenu, new MultipleChoiceMenuItem(ChangeAMRotate, rotateOptions, 3, am_rotate), "Rotate Map");
	automapMenu.addItem(new BooleanMenuItem(language["STR_AMTEXTURES"], am_drawtexturedwalls, ChangeAutomapFlag));
	automapMenu.addItem(new BooleanMenuItem(language["STR_AMFLOORS"], am_drawfloors, ChangeAutomapFlag));
	automapMenu.addItem(new BooleanMenuItem(language["STR_AMTEXTUREDOVERLAY"], am_overlaytextured, ChangeAutomapFlag));
	automapMenu.addItem(new BooleanMenuItem(language["STR_AMRATIOS"], am_showratios, ChangeAutomapFlag));
	automapMenu.addItem(new BooleanMenuItem(language["STR_AMPAUSE"], am_pause, ChangeAutomapFlag));
}

////////////////////////////////////////////////////////////////////
//
// Wolfenstein Control Panel!  Ta Da!
//
////////////////////////////////////////////////////////////////////
void US_ControlPanel (ScanCode scancode)
{
	int which;
	bool idEasterEgg = Wads.CheckNumForName("IDGUYPAL") != -1;

	if (!Net::IsArbiter())
	{
		// Disable functions that should only be available to arbiter
		switch(scancode)
		{
			case sc_F2:
			case sc_F3:
			case sc_F7:
			case sc_F8:
			case sc_F9:
				return;
			default:
				break;
		}
	}

	if (!Session::AllowsSaving())
	{
		// At this time we don't support saves in multiplayer
		switch(scancode)
		{
			case sc_F2:
			case sc_F3:
			case sc_F8:
			case sc_F9:
				return;
			default:
				break;
		}
	}

	if (ingame)
	{
		if (CP_CheckQuick (scancode))
			return;
		lastgamemusicoffset = StartCPMusic (gameinfo.MenuMusic);

		Net::BlockPlaysim();

		VW_FadeOut();
	}
	else
		StartCPMusic (gameinfo.MenuMusic);
	SetupControlPanel ();

	//
	// F-KEYS FROM WITHIN GAME
	//
	Menu::closeMenus(false);
	switch (scancode)
	{
		case sc_F1:
			HelpScreens ();
			goto finishup;

		case sc_F2:
			GameSave::GetSaveMenu().show();
			goto finishup;

		case sc_F3:
			GameSave::GetLoadMenu().show();
			goto finishup;

		case sc_F4:
			soundBase.show();
			goto finishup;

		case sc_F5:
			displayMenu.show();
			goto finishup;

		case sc_F6:
			controlBase.show ();
			goto finishup;

		finishup:
			CleanupControlPanel ();
			return;

		default:
			break;
	}

	if(MenuStyle == MENUSTYLE_Corridor7)
	{
		// Named rather than numbered: this block used to index the old
		// picture-painted layout by hand, and silently enabled the wrong rows
		// the moment the menu was reordered.
		enum
		{
			C7MENU_NEW = 0, C7MENU_STORE, C7MENU_RETRIEVE, C7MENU_OPTIONS,
			C7MENU_RESUME, C7MENU_ABORT, C7MENU_HIGHSCORES, C7MENU_EXIT
		};

		if(ingame)
		{
			// Require an explicit end game rather than stranding other players.
			mainMenu[C7MENU_NEW]->setEnabled(Session::CanLeaveSessionUnilaterally());
			mainMenu[C7MENU_STORE]->setEnabled(Session::AllowsSaving() && players[ConsolePlayer].state != player_t::PST_DEAD);
			mainMenu[C7MENU_RESUME]->setEnabled(true);
			mainMenu[C7MENU_ABORT]->setEnabled(Net::IsArbiter());
		}
		else
		{
			mainMenu[C7MENU_NEW]->setEnabled(true);
			mainMenu[C7MENU_STORE]->setEnabled(false);
			mainMenu[C7MENU_RESUME]->setEnabled(false);
			mainMenu[C7MENU_ABORT]->setEnabled(false);
		}
		mainMenu[C7MENU_OPTIONS]->setEnabled(true);
		mainMenu[C7MENU_HIGHSCORES]->setEnabled(gameinfo.TrackHighScores == true && Session::TracksHighScores());
		mainMenu[C7MENU_EXIT]->setEnabled(true);
	}
	else if(ingame)
	{
		mainMenu[0]->setEnabled(Session::CanLeaveSessionUnilaterally()); // explicit end game rather than stranding others
		mainMenu[mainMenu.countItems()-3]->setText(language["STR_EG"]);
		mainMenu[mainMenu.countItems()-3]->setEnabled(Net::IsArbiter());
		mainMenu[mainMenu.countItems()-2]->setText(language["STR_BG"]);
		mainMenu[mainMenu.countItems()-2]->setEnabled(true);
		mainMenu[mainMenu.countItems()-2]->setHighlighted(true);
		mainMenu[3]->setEnabled(Session::AllowsSaving() && players[ConsolePlayer].state != player_t::PST_DEAD);
	}
	else
	{
		mainMenu[0]->setEnabled(true);
		if (gameinfo.TrackHighScores == true && Session::TracksHighScores())
		{
			mainMenu[mainMenu.countItems()-3]->setText(language["STR_VS"]);
			mainMenu[mainMenu.countItems()-3]->setEnabled(true);
		}
		else
		{
			mainMenu[mainMenu.countItems()-3]->setText(language["STR_EG"]);
			mainMenu[mainMenu.countItems()-3]->setEnabled(false);
		}
		mainMenu[mainMenu.countItems()-2]->setText(language["STR_BD"]);
		mainMenu[mainMenu.countItems()-2]->setEnabled(Session::CanLeaveSessionUnilaterally());
		mainMenu[mainMenu.countItems()-2]->setHighlighted(false);
		mainMenu[3]->setEnabled(false);
	}
	mainMenu.validateCurPos();
	mainMenu.draw();
	MenuFadeIn ();
	Menu::closeMenus(false);

	//
	// MAIN MENU LOOP
	//
	do
	{
		which = mainMenu.handle();

		if(idEasterEgg)
		{
			IN_ProcessEvents();

			//
			// EASTER EGG FOR SPEAR OF DESTINY!
			//
			if (Keyboard[sc_I] && Keyboard[sc_D])
			{
				MenuFadeOut ();
				StartCPMusic ("XJAZNAZI");
				VL_ReadPalette("IDGUYPAL");

				CA_CacheScreen(TexMan("IDGUYS"));

				VW_UpdateScreen ();

				VW_FadeIn();

				while (Keyboard[sc_I] || Keyboard[sc_D])
					IN_WaitAndProcessEvents();
				IN_ClearKeysDown ();
				IN_Ack (ACK_Local);

				VW_FadeOut ();
				VL_ReadPalette(gameinfo.GamePalette);

				mainMenu.draw();
				StartCPMusic (gameinfo.MenuMusic);
				MenuFadeIn ();
			}
		}

		switch (which)
		{
			case -1:
				if(!ingame || quitonescape)
					QuitGame(0);
				else
					PlayDemosOrReturnToGame(0);
				break;
			default:
				break;
		}

		//
		// "EXIT OPTIONS" OR "NEW GAME" EXITS
		//
	}
	while (!Menu::areMenusClosed());

	//
	// DEALLOCATE EVERYTHING
	//
	CleanupControlPanel ();

	// RETURN/START GAME EXECUTION
}

////////////////////////////////////////////////////////////////////
//
// CHECK QUICK-KEYS & QUIT (WHILE IN A GAME)
//
////////////////////////////////////////////////////////////////////
int CP_CheckQuick (ScanCode scancode)
{
	switch (scancode)
	{
		// Check to see if we have anything to open
		case sc_F1:
			if(Wads.CheckNumForName("HELPART", ns_global) == -1)
				return 1;
			break;

		// Disable save if dead
		case sc_F2:
			if(players[ConsolePlayer].state == player_t::PST_DEAD)
				return 1;
			break;

		//
		// END GAME
		//
		case sc_F7:
			WindowH = 160;
			CP_EndGame(0);

			DrawPlayScreen();
			WindowH = 200;
			return 1;

		//
		// QUICKSAVE
		//
		case sc_F8:
			if(players[ConsolePlayer].state != player_t::PST_DEAD)
				GameSave::QuickLoadOrSave(false);
			return 1;

		//
		// QUICKLOAD
		//
		case sc_F9:
			GameSave::QuickLoadOrSave(true);
			return 1;

		//
		// QUIT
		//
		case sc_F10:
			WindowX = WindowY = 0;
			WindowW = 320;
			WindowH = 160;
			QuitGame(-1);

			DrawPlayScreen ();
			WindowH = 200;
			return 1;
	}

	return 0;
}


////////////////////////////////////////////////////////////////////
//
// END THE CURRENT GAME
//
////////////////////////////////////////////////////////////////////
int CP_EndGame (int)
{
	int res;
	res = Confirm (language[MenuStyle == MENUSTYLE_Corridor7
		? "STR_C7ENDGAME" : "ENDGAMESTR"]);
	if (!ingame)
		mainMenu.draw();
	if(!res) return 0;

	Net::EndGame();
	return 1;
}

////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////
//
// SUPPORT ROUTINES
//
////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////
//
// Clear Menu screens to dark red
//
////////////////////////////////////////////////////////////////////
void ClearMScreen (void)
{
	static FTextureID backdropID = TexMan.CheckForTexture("BACKDROP", FTexture::TEX_Any);
	if(!backdropID.isValid())
		VWB_Clear (BORDCOLOR, 0, 0, screenWidth, screenHeight);
	else
		CA_CacheScreen(TexMan(backdropID), true);
}


////////////////////////////////////////////////////////////////////
//
// Draw a window for a menu
//
////////////////////////////////////////////////////////////////////
void DrawWindow (int x, int y, int w, int h, int wcolor, int color1, int color2)
{
	int wx = x, wy = y, ww = w, wh = h;
	MenuToRealCoords(wx, wy, ww, wh, MENU_CENTER);

	VWB_Clear (wcolor, wx, wy, wx+ww, wy+wh);
	DrawOutline (x, y, w, h, color1, color2);
}

void DrawOutline (int x, int y, int w, int h, int color1, int color2)
{
	MenuToRealCoords(x, y, w, h, MENU_CENTER);

	VWB_Clear(color2, x-scaleFactorX, y, x+w+scaleFactorX, y+scaleFactorY);
	VWB_Clear(color2, x-scaleFactorX, y, x, y+h);
	VWB_Clear(color1, x-scaleFactorX, y+h, x+w+scaleFactorX, y+h+scaleFactorY);
	VWB_Clear(color1, x+w, y, x+w+scaleFactorX, y+h);
}

////////////////////////////////////////////////////////////////////
//
// Setup Control Panel stuff - graphics, etc.
//
////////////////////////////////////////////////////////////////////
void SetupControlPanel (void)
{
	// The menu is not seen through the visor. Corridor 7's night and infrared
	// modes are a whole-DAC rewrite, not a tint over the 3D view, so anything
	// drawn while one is active comes out green or red -- including the menu,
	// which UpdatePaletteShifts had no chance to undo because the play loop is
	// not running. Reset here rather than on the way in: US_ControlPanel has
	// already faded the view out, so the change happens on a black screen. The
	// visor comes back by itself, since PlayFrame updates the palette from the
	// player's C7VisorMode before it renders or fades back in.
	//
	// FinishPaletteShifts also drops a damage or pickup flash that was still
	// decaying, which is the same argument: it is a moment of the game, not a
	// property of the menu.
	FinishPaletteShifts();

	WindowH = 200;
	if(screenHeight % 200 != 0)
		VL_ClearScreen(0);

	//
	// CENTER MOUSE
	//
	if(IN_IsInputGrabbed())
		IN_CenterMouse();
}

////////////////////////////////////////////////////////////////////
//
// Clean up all the Control Panel stuff
//
////////////////////////////////////////////////////////////////////
void CleanupControlPanel (void)
{
	VWB_Clear(ColorMatcher.Pick(RPART(gameinfo.MenuFadeColor), GPART(gameinfo.MenuFadeColor), BPART(gameinfo.MenuFadeColor)),
		0, 0, screenWidth, screenHeight);
}

////////////////////////////////////////////////////////////////////
//
// DELAY FOR AN AMOUNT OF TICS OR UNTIL CONTROLS ARE INACTIVE
//
////////////////////////////////////////////////////////////////////
void TicDelay (int count)
{
	ControlInfo ci;

	int32_t startTime = GetTimeCount ();
	do
	{
		SDL_Delay(5);
		ReadAnyControl (&ci);
	}
	while ((int32_t) GetTimeCount () - startTime < count && ci.dir != dir_None);
}

////////////////////////////////////////////////////////////////////
//
// WAIT FOR CTRLKEY-UP OR BUTTON-UP
//
////////////////////////////////////////////////////////////////////
void WaitKeyUp (void)
{
	ControlInfo ci;
	while (ReadAnyControl (&ci), ci.button0 |
		ci.button1 |
		ci.button2 | ci.button3 | Keyboard[sc_Space] | Keyboard[sc_Enter] | Keyboard[sc_Escape])
	{
		IN_WaitAndProcessEvents();
	}
}


////////////////////////////////////////////////////////////////////
//
// READ KEYBOARD, JOYSTICK AND MOUSE FOR INPUT
//
////////////////////////////////////////////////////////////////////

// Store relative mouse movement until menu changes.
static int menumousex, menumousey;

void ReadAnyControl (ControlInfo * ci)
{
	int mouseactive = 0;

	IN_ReadControl (0, ci);

	if (mouseenabled && IN_IsInputGrabbed())
	{
		int mousex, mousey, buttons;
		buttons = SDL_GetRelativeMouseState(&mousex, &mousey);
		menumousex += mousex;
		menumousey += mousey;

		int middlePressed = buttons & SDL_BUTTON(SDL_BUTTON_MIDDLE);
		int rightPressed = buttons & SDL_BUTTON(SDL_BUTTON_RIGHT);
		buttons &= ~(SDL_BUTTON(SDL_BUTTON_MIDDLE) | SDL_BUTTON(SDL_BUTTON_RIGHT));
		if(middlePressed) buttons |= 1 << 2;
		if(rightPressed) buttons |= 1 << 1;

		if(menumousey < -SENSITIVE)
		{
			ci->dir = dir_North;
			mouseactive = 1;
		}
		else if(menumousey > SENSITIVE)
		{
			ci->dir = dir_South;
			mouseactive = 1;
		}

		if(menumousex < -SENSITIVE)
		{
			ci->dir = dir_West;
			mouseactive = 1;
		}
		else if(menumousex > SENSITIVE)
		{
			ci->dir = dir_East;
			mouseactive = 1;
		}

		if(mouseactive)
			menumousex = menumousey = 0;

		if (buttons)
		{
			ci->button0 = !!(buttons & 1);
			ci->button1 = !!(buttons & 2);
			ci->button2 = !!(buttons & 4);
			ci->button3 = false;
			mouseactive = 1;
		}
	}

	if (joystickenabled && !mouseactive)
	{
		int jx, jy, jb;

		IN_GetJoyDelta (&jx, &jy);
		if (jy < -SENSITIVE)
			ci->dir = dir_North;
		else if (jy > SENSITIVE)
			ci->dir = dir_South;

		if (jx < -SENSITIVE)
			ci->dir = dir_West;
		else if (jx > SENSITIVE)
			ci->dir = dir_East;

		jb = IN_JoyButtons ();
		if (jb)
		{
			ci->button0 = !!(jb & 1);
			ci->button1 = !!(jb & 2);
			ci->button2 = !!(jb & 4);
			ci->button3 = !!(jb & 8);
		}
	}
}

#ifdef __ANDROID__
extern  bool inConfirm;
#endif
////////////////////////////////////////////////////////////////////
//
// DRAW DIALOG AND CONFIRM YES OR NO TO QUESTION
//
////////////////////////////////////////////////////////////////////
bool Confirm (const char *string)
{
	bool xit = false;
	int x, y, tick = 0, lastBlinkTime;
	const char* whichsnd[2] = { "menu/escape", "menu/activate" };
	ControlInfo ci;

#ifdef __ANDROID__
	inConfirm = true;
#endif

	Message (string);
	// Corridor 7 announces the dialog itself and stays silent on the answer.
	if(MenuStyle == MENUSTYLE_Corridor7)
		SD_PlaySound ("c7/menu/prompt");
	IN_ClearKeysDown ();
	WaitKeyUp ();

	//
	// BLINK CURSOR
	//
	x = PrintX;
	y = PrintY;
	lastBlinkTime = GetTimeCount();

	do
	{
		ReadAnyControl(&ci);

		if (GetTimeCount() - lastBlinkTime >= 10)
		{
			switch (tick)
			{
				case 0:
				{
					double dx = x;
					double dy = y;
					double dw = 8;
					double dh = 13;
					MenuToRealCoords(dx, dy, dw, dh, MENU_CENTER);
					VWB_Clear(MENUWIN_BACKGROUND, (int)dx, (int)dy, (int)(dx+dw), (int)(dy+dh));
					break;
				}
				case 1:
					PrintX = x;
					PrintY = y;
					US_Print (BigFont, "_", gameinfo.FontColors[GameInfo::MESSAGEFONT]);
			}
			VW_UpdateScreen ();
			tick ^= 1;
			lastBlinkTime = GetTimeCount();
		}
		else SDL_Delay(5);

	}
	while (!Keyboard[sc_Y] && !Keyboard[sc_S] && !Keyboard[sc_N] && !Keyboard[sc_Escape] && !Keyboard[sc_Return] && !ci.button0 && !ci.button1);

	if (Keyboard[sc_S] || Keyboard[sc_Y] || Keyboard[sc_Return] || ci.button0)
	{
		xit = true;
		if(MenuStyle != MENUSTYLE_Corridor7)
			ShootSnd ();
	}

	IN_ClearKeysDown ();
	WaitKeyUp ();

	if(MenuStyle != MENUSTYLE_Corridor7)
		SD_PlaySound (whichsnd[xit]);

#ifdef __ANDROID__
	inConfirm = false;
#endif

	return xit;
}

////////////////////////////////////////////////////////////////////
//
// PRINT A MESSAGE IN A WINDOW
//
////////////////////////////////////////////////////////////////////
void Message (const char *string)
{
	static const int
		MESSAGE_BG = ColorMatcher.Pick(RPART(gameinfo.MessageColors[0]), GPART(gameinfo.MessageColors[0]), BPART(gameinfo.MessageColors[0])),
		TOPBRDR = ColorMatcher.Pick(RPART(gameinfo.MessageColors[1]), GPART(gameinfo.MessageColors[1]), BPART(gameinfo.MessageColors[1])),
		BOTBRDR = ColorMatcher.Pick(RPART(gameinfo.MessageColors[2]), GPART(gameinfo.MessageColors[2]), BPART(gameinfo.MessageColors[2]));

	word width, height;

	FString measureString;
	measureString.Format("%s_", string);
	VW_MeasurePropString(BigFont, measureString, width, height);
	width = MIN<int>(width, 320 - 10);
	height = MIN<int>(height, 200 - 10);

	PrintY = (WindowH / 2) - height / 2;
	PrintX = WindowX = 160 - width / 2;

	DrawWindow (WindowX - 5, PrintY - 5, width + 10, height + 10, MESSAGE_BG);
	DrawOutline (WindowX - 5, PrintY - 5, width + 10, height + 10, BOTBRDR, TOPBRDR);
	US_Print (BigFont, string, gameinfo.FontColors[GameInfo::MESSAGEFONT]);
	VW_UpdateScreen ();
}

////////////////////////////////////////////////////////////////////
//
// THIS MAY BE FIXED A LITTLE LATER...
//
////////////////////////////////////////////////////////////////////

int StartCPMusic (const char* song)
{
	int lastoffs;

	// With a disc in the drive the CD release plays no title, menu,
	// intermission or high-score song at all: its song-start routine
	// (19f8:2769) returns immediately. Whatever the disc is playing carries on
	// over the menus, which is the whole point of a soundtrack that runs for
	// ten minutes at a stretch.
	if(C7CD::Available())
		return 0;

	//lastmusic = song;
	lastoffs = SD_MusicOff ();

	SD_StartMusic(song);
	return lastoffs;
}

///////////////////////////////////////////////////////////////////////////
//
// CHECK FOR PAUSE KEY (FOR MUSIC ONLY)
//
///////////////////////////////////////////////////////////////////////////
void CheckPause (void)
{
	static int SoundStatus = 1;
	static int pauseofs = 0;
	if (LastScan == sc_Pause)
	{
		// The disc is left running, as it was on real hardware -- MSCDEX had no
		// idea the game was paused.
		switch (C7CD::Available() ? -1 : SoundStatus)
		{
			case 0:
				SD_ContinueMusic(gameinfo.MenuMusic, pauseofs);
				break;
			case 1:
				pauseofs = SD_MusicOff();
				break;
		}

		SoundStatus ^= 1;
		VW_WaitVBL (3);
		IN_ClearKeysDown ();
	}
}

///////////////////////////////////////////////////////////////////////////
//
// DRAW SCREEN TITLE STRIPES
//
///////////////////////////////////////////////////////////////////////////
void DrawStripes (int y)
{
	static unsigned int calcStripes = INT_MAX;
	static unsigned int sy, sh;
	static unsigned int ly, lh;
	if(calcStripes != scaleFactorY)
	{
		unsigned int dummyx = 0, dummyw = 320;
		sy = y;
		sh = 24;
		ly = y+22;
		lh = 1;
		calcStripes = scaleFactorY;

		MenuToRealCoords(dummyx, sy, dummyw, sh, MENU_TOP);
		MenuToRealCoords(dummyx, ly, dummyw, lh, MENU_TOP);
	}

	VWB_Clear(STRIPEBG, 0, sy, screenWidth, sy+sh);
	VWB_Clear(STRIPE, 0, ly, screenWidth, ly+lh);
}

void ShootSnd (void)
{
	SD_PlaySound ("menu/activate");
}

void MenuFadeOut()
{
	assert(!menusAreFaded);
	menusAreFaded = true;

	VL_FadeOut(0, 255,
		RPART(gameinfo.MenuFadeColor), GPART(gameinfo.MenuFadeColor), BPART(gameinfo.MenuFadeColor),
		10);
}

void MenuFadeIn()
{
	assert(menusAreFaded);
	menusAreFaded = false;

	VL_FadeIn(0, 255, 10);
}

void ShowMenu(Menu &menu)
{
	// Clear out any residual mouse movement.
	menumousex = menumousey = 0;

	VW_FadeOut ();
	if(screenHeight % 200 != 0)
		VL_ClearScreen(0);

	lastgamemusicoffset = StartCPMusic (gameinfo.MenuMusic);
	Menu::closeMenus(false);
	menu.show();

	CleanupControlPanel();
	IN_ClearKeysDown ();
	VW_FadeOut();
	if(viewsize != 21)
		DrawPlayScreen ();

	if (!startgame && !loadedgame)
		ContinueMusic (lastgamemusicoffset);

	if (loadedgame)
		playstate = ex_abort;

	ResetTimeCount();

	if (MousePresent && IN_IsInputGrabbed())
		IN_CenterMouse();     // Clear accumulated mouse movement
}
