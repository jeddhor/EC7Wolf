// MiSTer hybrid core support, see mister.h

#include "mister.h"
#include "wl_def.h"
#include "c_cvars.h"
#include "id_vl.h"
#include "id_vh.h"
#include "wl_main.h"
#include "wl_play.h"
#include "wl_iwad.h"
#include "tarray.h"
#include "zstring.h"

#include <mister_hybrid.h>
#include <string.h>

#define EXIT_TO_MENU 0
#define EXIT_RESTART 42 // danik_hybrid_launch.sh starts the game again
#define EXIT_RELOADED 43 // the same, after the core has settled

static const char* const TITLE = "Corridor 7";

// The player came through the game list: quitting a game goes back to it
static bool PickedFromList = false;

void MiSTer_Resolution(unsigned &width, unsigned &height)
{
	// 320x200, 640x200, 320x240, 640x240 (OSD status bits 32-33, as in the
	// ECWolf core). 320x200 as well when there is no core to ask; 200 lines
	// when the core is an older one without the mode
	static const int modes[4] = { MH_MODE_320x200, MH_MODE_640x200, MH_MODE_320x240, MH_MODE_640x240 };
	int mode = MH_Open() ? modes[MH_OSD_GAME_BITS(MH_OSDStatus(), 32, 2)] : MH_MODE_320x200;
	if(!MH_ModeAvailable(mode))
		mode = MH_ModeWidth(mode) == 640 ? MH_MODE_640x200 : MH_MODE_320x200;
	width = MH_ModeWidth(mode);
	height = MH_ModeHeight(mode);
}

bool MiSTer_UpdateResolution()
{
	unsigned width, height;
	MiSTer_Resolution(width, height);
	if(width == windowWidth && height == windowHeight)
		return false;

	// EC7Wolf draws at windowWidth/Height divided by vid_renderscale
	// (VL_UpdateRenderSize); the core scans out the window's size
	windowWidth = fullScreenWidth = windowedScreenWidth = width;
	windowHeight = fullScreenHeight = windowedScreenHeight = height;
	VL_UpdateRenderSize();
	r_ratio = static_cast<Aspect>(CheckRatio(windowWidth, windowHeight));
	VH_Startup(); // Recalculate fizzlefade stuff.
	VL_SetVGAPlaneMode();
	return true;
}

// The games with a menu entry of their own (package/games.txt): ECWolf's
// game (iwadinfo.txt, Autoname) as the core's set name ECWolf_<id>.
struct MiSTerGame
{
	const char *autoname;
	const char *id;
	const char *name;
	const char *shareware_of;
	const char *pattern; // its files, for a game that was not found
	const char *missing;
};
static const MiSTerGame Games[] =
{
	{ "Corridor7.CD", "CORR7", "Corridor 7: Alien Invasion", NULL, "*.CO7",
		"Corridor 7 was not found. Copy the files of the CD version (*.CO7) "
		"to %s/." },
};
#define NO_GAME "No game data found. Copy the files of Corridor 7 (*.CO7) to %s/."

// A file ECWolf found in the game's folder ("./VSWAP.CO7"): its name there,
// else NULL
static const char *InGameFolder(const FString &path)
{
	const char *p = path.GetChars();
	return strncmp(p, "./", 2) == 0 && p[2] != 0 && strchr(p + 2, '/') == NULL ? p + 2 : NULL;
}

int MiSTer_PickIWad(WadStuff *wads, const char *const *autonames, int numwads)
{
	// The games ECWolf found, each with its files, which MH_PickGame() looks
	// for again for the lines under the game's logo ("Checking Game Data...",
	// "Game Data OK"); one found outside the game's folder with none to look
	// for. Then the games of a menu entry ECWolf did not find, with their
	// message. A game found twice has the menu entry the first time only.
	TArray<mh_game> games;
	TArray<int> wad;
	TArray<FString> ids;
	TArray<const char*> files;
	TArray<unsigned> filesAt;
	static const char *const none[] = { NULL };
	bool seen[countof(Games)] = {};
	for(int i = 0;i < numwads;++i)
	{
		ids.Push(autonames[i]);
		unsigned j = 0;
		while(j < wads[i].Path.Size() && InGameFolder(wads[i].Path[j]))
			++j;
		if(j == 0 || j < wads[i].Path.Size())
		{
			filesAt.Push(~0u);
			continue;
		}
		filesAt.Push(files.Size());
		for(j = 0;j < wads[i].Path.Size();++j)
			files.Push(InGameFolder(wads[i].Path[j]));
		files.Push(NULL);
	}
	for(int i = 0;i < numwads;++i)
	{
		mh_game game = { ids[i].GetChars(), wads[i].Name.GetChars(),
			filesAt[i] != ~0u ? &files[filesAt[i]] : none, NULL, NULL };
		for(unsigned g = 0;g < countof(Games);++g)
		{
			if(strcmp(autonames[i], Games[g].autoname) == 0 && !seen[g])
			{
				seen[g] = true;
				game.id = Games[g].id;
				game.name = Games[g].name;
				game.shareware_of = Games[g].shareware_of;
			}
		}
		games.Push(game);
		wad.Push(i);
	}
	static const char *patterns[countof(Games)][2];
	for(unsigned g = 0;g < countof(Games);++g)
	{
		if(seen[g] || Games[g].pattern == NULL)
			continue;
		patterns[g][0] = Games[g].pattern;
		patterns[g][1] = NULL;
		mh_game game = { Games[g].id, Games[g].name, patterns[g], NULL, Games[g].missing };
		games.Push(game);
		wad.Push(-1);
	}

	int listed = 0;
	int pick = MH_PickGame(games.Size() ? &games[0] : NULL, games.Size(), NULL, NO_GAME, &listed);
	if(pick < 0)
		return -1;
	if(wad[pick] < 0)
	{
		// some of its files are there, not all of them
		FString text;
		text.Format(games[pick].missing, MH_GamePath());
		MiSTer_ShowError(text);
		return -1;
	}
	// the game's logo and "Loading <name>..." came with the pick (host
	// version 17)
	PickedFromList = listed != 0;
	return wad[pick];
}

void MiSTer_ShowError(const char *message)
{
	if(MH_Open())
		MH_UI_Message(TITLE, message, MH_UI_WAIT|MH_UI_ERROR);
}

int MiSTer_ExitCode()
{
	// The player loaded the core again while the game ran
	if(MH_CoreReloaded())
		return EXIT_RELOADED;
	// Not if we are quitting because another core was loaded
	if(PickedFromList && MH_Open())
		return EXIT_RESTART;
	return EXIT_TO_MENU;
}
