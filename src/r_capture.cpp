// ===========================================================================
//
// r_capture.cpp - deterministic capture & determinism-checksum harness.
//
// Renderer-redesign Phase 0.  See r_capture.h for the rationale.  Nothing in
// this file runs unless a --capture-* switch is present on the command line.
//
// ===========================================================================

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <math.h>

#include "r_capture.h"
#include "wl_def.h"
#include "g_session.h"
#include "g_command.h"
#include "wl_play.h"
#include "actor.h"
#include "wl_agent.h"
#include "wl_game.h"
#include "m_random.h"
#include "m_crc32.h"
#include "m_png.h"
#include "v_video.h"
#include "c7_automap.h"
#include "r_xbrz.h"
#include "v_palette.h"
#include "files.h"
#include "c_cvars.h"
#include "id_ca.h"
#include "id_vl.h"
#include "id_vh.h"
#include "gamemap.h"
#include "wl_net.h"
#include "thingdef/thingdef.h"
#include "a_inventory.h"
#ifdef ECWOLF_RENDERER_OPENGL
#include "render/opengl/r_glworld.h"
#include "render/opengl/r_glxbrz.h"
#endif

namespace Capture
{

namespace
{
	bool     g_armed          = false;

	bool     g_haveSeed       = false;
	DWORD    g_seed           = 0;

	FString  g_checksumPath;
	TArray<FString> g_tapes;
	FString  g_commandTracePath;
	FILE    *g_checksumFile   = NULL;

	int      g_captureFrame   = -1;      // 1-based rendered frame to shoot
	FString  g_captureFile;

	FString  g_glWorldPath;              // Phase 5 GL world offscreen capture
	FString  g_glFramePath;              // Phase 10 full-frame composite capture
	FString  g_glPresentPath;            // Phase 10 live GL-presented frame
	FString  g_glXBRZPath;               // Phase 11 GL-vs-CPU xBRZ parity pair

	int      g_maxFrames      = -1;      // quit after this many rendered frames
	int      g_maxTics        = -1;      // quit after this many simulation tics

	bool     g_haveOpenDoors  = false;   // --capture-open-doors world override
	int      g_openDoors      = 0;       // forced slide amount 0..65535

	bool     g_havePush       = false;   // --capture-push world override
	int      g_pushAmount     = 0;       // forced push amount 0..64
	MapSpot  g_pushOrigin      = NULL;   // synthetic pushwall origin (chosen once)

	bool     g_haveBlend      = false;   // --capture-blend full-screen flash override
	int      g_blendR = 0, g_blendG = 0, g_blendB = 0, g_blendA = 0;

	// --capture-duel A B: stand players A and B face to face on the map's own
	// floor and park everyone else out of the way, every tic.
	//
	// --capture-warp cannot be used for this. It pins players[ConsolePlayer],
	// which is a different player on each machine, so two instances would pin
	// two different pawns and the simulations would part company immediately.
	// Everything here is computed from map data and applied to every player
	// identically, which is the only shape a world override may take in a
	// netgame.
	// A and B face each other; the optional C stands at A's shoulder facing the
	// same way, which is how a fight with two players on one side of it gets
	// scripted -- and the only way to see team kills actually add up.
	int      g_duelA = -1, g_duelB = -1, g_duelC = -1;
	bool     g_duelFound      = false;
	fixed    g_duelX[MAXPLAYERS], g_duelY[MAXPLAYERS];
	angle_t  g_duelAngle[MAXPLAYERS];

	// --capture-fire [FROMTIC]: hold the attack button down from a given tic.
	// Injected into the local player's command before it is sent, so it reaches
	// everyone else the way a real trigger pull would rather than being applied
	// behind the network's back.
	long     g_fireFrom       = -1;

	// --capture-ammo: top every player's ammo up each tic.
	//
	// A scripted fight otherwise ends when the magazines do, at about two
	// kills, which is too short to watch a rule that only shows up over a run
	// of them. Applied to every player alike, so it stays deterministic --
	// unlike --capture-give, which hands an item to players[ConsolePlayer] and
	// so hands it to a different player on each machine.
	bool     g_topUpAmmo      = false;

	// One press: held from `from` for `tics` tics, or forever when tics < 0.
	struct PressWindow
	{
		long from;
		long tics;
	};
	bool InWindow(const TArray<PressWindow> &windows)
	{
		const long now = (long)gamestate.TimeCount;
		for(unsigned int i = 0; i < windows.Size(); ++i)
		{
			if(now >= windows[i].from &&
				(windows[i].tics < 0 || now < windows[i].from + windows[i].tics))
				return true;
		}
		return false;
	}

	// --capture-forward [FROMTIC [TICS]]: walk forward over a window. Negative
	// controly is forward (wl_agent.cpp thrusts by -controly), and RUNMOVE is
	// the running magnitude, which is what forwardmove[1] scales -- so this
	// measures the speed a player actually moves at rather than the value in
	// their definition.
	//
	// --capture-use TIC [TICS]: hold the use key over a window. Nothing else in
	// the harness can press it, so anything the player operates by hand -- an
	// elevator, a dispenser, an access terminal, a door -- was untestable
	// headlessly until this existed. A use that never lets go keeps re-opening
	// the door it just opened, so anything about what happens *after* a door is
	// open needs the key released again.
	//
	// Both may be given more than once, and each occurrence is another window.
	// A player who walks into a doorway, stops, and then closes the door on
	// themselves needs three separate presses to reproduce, which one window
	// each could not express.
	TArray<PressWindow> g_forwardWindows;
	TArray<PressWindow> g_useWindows;

	// --capture-place TIC X Y [ANGLE]: put the player at one exact spot, once.
	// Unlike --capture-warp, which pins them there every tic, this is a single
	// assignment, so the tics after it are ordinary play. Reaching a particular
	// sub-tile position by steering is a matter of luck at 35 tics a second;
	// stating it is not.
	long     g_placeTic       = -1;
	double   g_placeX         = 0.0, g_placeY = 0.0, g_placeAngle = -1.0;
	bool     g_placeDone      = false;

	// --capture-trace [FROMTIC]: print the player's position every tic. A tile
	// coordinate is too coarse to tell "stopped by a wall" from "cannot move at
	// all", and that difference is the whole question when something reports
	// being stuck.
	long     g_traceFrom      = -1;

	// --capture-scoreboard: hold the scoreboard key down.
	bool     g_holdScoreboard = false;

	// --capture-tally PATH: photograph the end-of-match page when it appears.
	//
	// That page is up for a few seconds somewhere in the middle of a match,
	// at a moment decided by when somebody happens to reach the frag limit.
	// No frame number finds it and no key sequence leads to it, so the page
	// says when it is ready rather than the harness guessing.
	FString  g_tallyPath;

	bool     g_haveWarp       = false;   // --capture-warp: pin player to a tile+angle
	// --capture-snapshot PATH TIC: the editor's Snapshot. Renders the frame at
	// a given SIMULATION TIC, writes it, prints a result line and exits.
	//
	// Anchored to a tic rather than a frame because a frame number is not a
	// property of the game: the tic-per-frame ratio moves with how fast the
	// machine draws, so "frame 30" is a different moment on a busy box than on
	// an idle one. The editor caches what comes back and must be able to say
	// what it is a picture of.
	FString  g_snapshotPath;
	long     g_snapshotTic    = -1;
	bool     g_snapshotDone   = false;

	//: Kept as given so the camera can be checked against the map that
	//: actually loaded, and reported back in the snapshot result.
	double   g_warpTileX      = 0.0, g_warpTileY = 0.0, g_warpDegrees = 0.0;
	bool     g_warpChecked    = false;

	// A number, all of it, and finite. strtod alone accepts "1.5rubbish" and
	// "nan"; neither is a camera position.
	bool ParseFinite(const char *text, double &out)
	{
		if(text == NULL || *text == '\0')
			return false;
		char *end = NULL;
		errno = 0;
		const double value = strtod(text, &end);
		if(end == text || *end != '\0' || errno == ERANGE)
			return false;
		// NaN is the only value not equal to itself; the comparison also
		// rejects the infinities without needing <cmath> here.
		if(value != value || value > 1.0e9 || value < -1.0e9)
			return false;
		out = value;
		return true;
	}
	fixed    g_warpX = 0, g_warpY = 0;
	angle_t  g_warpAngle = 0;

	// --capture-extralight VALUE [FROMFRAME]: pin the player's extralight from a
	// given rendered frame onward. Repeatable, so the visor can be switched on or
	// off part way through a run (20 = C7 visor mode 2, 12 = muzzle flash, 0 = off).
	struct ExtraLightStep { int value, frame; };
	TArray<ExtraLightStep> g_extraLights;
	bool     g_haveExtraLight = false;
	int      g_extraLight     = 0;

	// --capture-xbrz FACTOR: also write the screenshot upscaled through xBRZ, to
	// PATH with a "-xbrzN" suffix. The upscaler runs at presentation time, past
	// the point a normal capture is taken, so this is the only way to see its
	// output headlessly; it deliberately calls the same entry point the present
	// path does, with the same flashed palette, rather than a test-only copy.
	int      g_xbrzFactor     = 0;

	// --capture-actors PATH: trace every monster's position and state each tic.
	// Enemy behavior is otherwise invisible to the test harness -- a screenshot
	// says nothing about whether an alien patrolled, backed off, or stood still
	// for 500 tics -- so the AI work is measured from this rather than by eye.
	FString  g_actorPath;
	// --capture-players PATH: trace each player's pawn each tic. Deliberately
	// a second file rather than more rows in the actor trace, whose readers
	// take every row to be one monster and the population to be stable.
	FString  g_playerPath;
	FILE    *g_playerFile     = NULL;
	FILE    *g_actorFile      = NULL;

	// --capture-give CLASS: hand the player an inventory item once, at the first
	// tic. A powerup is the only way to reach some render states, and picking one
	// up off the floor needs a Touch -- which a warp does not produce -- so the
	// Invulnerability Sphere's strobe cannot be photographed any other way.
	FString  g_giveClass;
	bool     g_giveDone       = false;

	bool     g_c7Map          = false;   // --capture-c7map: raise the C7 inset panel
	bool     g_c7FloorPlan    = false;   // --capture-floorplan: as if the plan were picked up
	// --capture-exitlevel: complete the level at this tic, taking the same path
	// the elevator does (lnspec.cpp sets ex_completed), so a level transition can
	// be exercised headlessly. The debug "quit level" key cannot be driven under
	// Corridor 7 because its Tab modifier is the floor map.
	long     g_exitLevelTic   = -1;
	bool     g_exitLevelDone  = false;
	// --capture-verbs: report the state each of Corridor 7's verbs acts on,
	// whenever it changes. This is an observation, not an override: it exists so
	// a test that presses buttons -- a touchscreen, a gamepad -- can assert that
	// the press reached the simulation, which a screenshot cannot do on a screen
	// where the textures animate on their own.
	bool     g_verbs          = false;
	bool     g_haveVisorMode  = false;   // --capture-visormode: force the C7 visor
	int      g_visorMode      = 0;       // 0 off, 1 night vision, 2 infrared, 3 shock

	// --capture-vidmode: queued mid-run video mode changes. Repeatable, so a run
	// can switch more than once (tearing down a context that was itself built
	// after an earlier teardown).
	struct VidModeChange { int w, h, frame; };
	TArray<VidModeChange> g_vidModes;

	// Running state.
	uint64_t g_ticCount       = 0;
	uint64_t g_frameCount     = 0;
	DWORD    g_worldChecksum  = 0;       // folds every tic's state
	bool     g_finalized      = false;
	// Set by a capture that produced its artifact outside the gameplay loop; the
	// next presented frame ends the run. See Capture::NoteArtifactComplete().
	bool     g_artifactComplete = false;

	inline DWORD Fold(DWORD crc, const void *p, unsigned int len)
	{
		return AddCRC32(crc, reinterpret_cast<const BYTE *>(p), len);
	}

	// Build a checksum over exactly the deterministic simulation state that a
	// correct interpolation/renderer change must leave untouched: every actor's
	// world transform plus the shared RNG and clock.  Render-only fields are
	// deliberately excluded.
	DWORD ChecksumThisTic()
	{
		DWORD crc = 0;

		crc = Fold(crc, &gamestate.TimeCount, sizeof(gamestate.TimeCount));

		const DWORD rng = FRandom::StaticSumSeeds();
		crc = Fold(crc, &rng, sizeof(rng));

		for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
		{
			// Pointer identity is not stable across runs; transform is.
			crc = Fold(crc, &iter->x,      sizeof(iter->x));
			crc = Fold(crc, &iter->y,      sizeof(iter->y));
			crc = Fold(crc, &iter->z,      sizeof(iter->z));
			crc = Fold(crc, &iter->angle,  sizeof(iter->angle));
			crc = Fold(crc, &iter->pitch,  sizeof(iter->pitch));
			crc = Fold(crc, &iter->health, sizeof(iter->health));
			crc = Fold(crc, &iter->flags,  sizeof(iter->flags));
		}

		return crc;
	}

	// One line per living monster per tic. Deliberately records dir and the
	// pathing flag alongside the tile: "did it move" is not the same question as
	// "is it patrolling", and a patrol that has run into a wall shows up here as
	// dir == nodir with FL_PATHING still set.
	void TracePlayers()
	{
		if(g_playerFile == NULL)
			return;

		for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		{
			if(players[i].mo == NULL)
				continue;
			// The sprite and frame letter matter for the one thing about a
			// player that only the other machines can see: whether the walk
			// cycle is running. Standing in front of another player and
			// squinting is a poor instrument -- the sprite is thirty pixels
			// tall at any sensible distance -- and this says MARN A or MARN C
			// outright.
			char sprite[5] = "----";
			char frameLetter = '-';
			if(players[i].mo->state != NULL)
			{
				memcpy(sprite, players[i].mo->state->sprite, 4);
				sprite[4] = '\0';
				frameLetter = (char)('A' + players[i].mo->state->frame);
			}
			fprintf(g_playerFile, "%lu %u %d %d %u %d %d %u %d %s %d %d %s %c\n",
				(unsigned long)g_ticCount, i,
				players[i].mo->tilex, players[i].mo->tiley,
				(unsigned)(players[i].mo->angle/ANGLE_1),
				players[i].health,
				(int)players[i].frags,
				(unsigned)Net::PlayerTeam(i),
				Net::TeamFrags(Net::PlayerTeam(i)),
				players[i].mo->GetClass()->GetName().GetChars(),
				players[i].mo->x, players[i].mo->y,
				sprite, frameLetter);
		}
	}

	void TraceActors()
	{
		if(g_actorFile == NULL)
			return;

		for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
		{
			if(!(iter->flags & FL_ISMONSTER) || iter->health <= 0)
				continue;
			fprintf(g_actorFile, "%lu %s %d %d %d %d %d %d\n",
				(unsigned long)g_ticCount,
				iter->GetClass()->GetName().GetChars(),
				iter->tilex, iter->tiley,
				(int)iter->dir,
				(iter->flags & FL_PATHING) ? 1 : 0,
				(iter->flags & FL_ATTACKMODE) ? 1 : 0,
				iter->health);
		}
	}

	// Companion to the screenshot below: the same frame, run through the same
	// upscaler the present path uses. Written as a separate file so the plain
	// screenshot keeps its exact former contents and every existing test that
	// diffs it is unaffected.
	void WriteXBRZ(const char *path, const BYTE *buffer, int pitch,
		ESSType color_type, const PalEntry *shotPal)
	{
		if(g_xbrzFactor < 2 || buffer == NULL)
			return;
		if(color_type != SS_PAL)
		{
			// The upscaler is fed the indexed frame on purpose: that is what the
			// present path has, and expanding it here through the flashed palette
			// is the step being tested.
			Printf("Capture: --capture-xbrz needs an 8-bit screenshot buffer.\n");
			return;
		}

		const uint32_t *const scaled = R_XBRZScaleIndexed(buffer, pitch,
			SCREENWIDTH, SCREENHEIGHT, shotPal, g_xbrzFactor);
		if(scaled == NULL)
		{
			Printf("Capture: xBRZ %dx refused the frame.\n", g_xbrzFactor);
			return;
		}

		const int w = SCREENWIDTH * g_xbrzFactor, h = SCREENHEIGHT * g_xbrzFactor;
		FString outPath;
		const char *const dot = strrchr(path, '.');
		if(dot != NULL)
			outPath.Format("%.*s-xbrz%d%s", (int)(dot - path), path, g_xbrzFactor, dot);
		else
			outPath.Format("%s-xbrz%d", path, g_xbrzFactor);

		FILE *file = fopen(outPath.GetChars(), "wb");
		if(file == NULL)
		{
			Printf("Capture: FAILED to open '%s'\n", outPath.GetChars());
			return;
		}
		// 0xAARRGGBB in memory is B,G,R,A on a little-endian host, which is what
		// SS_BGRA means to the PNG writer.
		M_CreatePNG(file, (const BYTE *)scaled, NULL, SS_BGRA, w, h,
			w * (int)sizeof(uint32_t));
		M_FinishPNG(file);
		fclose(file);
		Printf("Capture: wrote xBRZ %dx screenshot '%s' (%dx%d).\n",
			g_xbrzFactor, outPath.GetChars(), w, h);
	}

	void WriteScreenshot(const char *path)
	{
		if(screen == NULL)
			return;

		const BYTE *buffer;
		int pitch;
		ESSType color_type;
		screen->GetScreenshotBuffer(buffer, pitch, color_type);
		if(buffer == NULL)
		{
			screen->ReleaseScreenshotBuffer();
			return;
		}

		// Resolve through the framebuffer's CURRENT palette, not GPalette's base
		// colors. They are the same in ordinary play, but Corridor 7 rewrites the
		// DAC for the visor modes (V_SetCorridor7PaletteMode) and V_ForceBlend
		// adds a full-screen flash on top -- and a screenshot that ignores both
		// shows a gray scene where the game is displaying green or red, which
		// makes the visor impossible to compare against the original.
		PalEntry shotPal[256];
		screen->GetFlashedPalette(shotPal);

		FILE *file = fopen(path, "wb");
		if(file != NULL)
		{
			M_CreatePNG(file, buffer, shotPal, color_type,
				SCREENWIDTH, SCREENHEIGHT, pitch);
			M_FinishPNG(file);
			fclose(file);
			// The tic is reported alongside the frame because they are not 1:1:
			// frame pacing is decoupled from the 70Hz simulation, so the tic a
			// given frame lands on varies between runs. Anything measuring an
			// animation rate has to bin by tic, not by frame.
			// Player tile is logged too: "spawned in a wall" bugs are about
			// where the pawn ended up, and a screenshot alone cannot say which
			// tile that is.
			int ptx = -1, pty = -1;
			// Access cards too. They are per-floor, so whether they survive a
			// level transition is a gameplay rule worth asserting, and the
			// status bar cannot answer it from pixels alone -- the cheat that
			// grants them also changes health, ammo and armour, so a screenshot
			// diff of the bar cannot isolate the cards.
			char cards[3] = { '-', '-', '\0' };
			if(players[ConsolePlayer].mo)
			{
				AActor *const pmo = players[ConsolePlayer].mo;
				ptx = pmo->tilex;
				pty = pmo->tiley;
				if(pmo->FindInventory(ClassDef::FindClass("C7Static001")))
					cards[0] = 'R';
				if(pmo->FindInventory(ClassDef::FindClass("C7Static002")))
					cards[1] = 'B';
			}
			Printf("Capture: wrote screenshot '%s' at frame %lu tic %lu map %s player (%d,%d) cards %s\n",
				path, (unsigned long)g_frameCount,
				(unsigned long)gamestate.TimeCount,
				gamestate.mapname, ptx, pty, cards);
		}
		else
			Printf("Capture: FAILED to open screenshot '%s'\n", path);

		WriteXBRZ(path, buffer, pitch, color_type, shotPal);

		screen->ReleaseScreenshotBuffer();
	}

	void Finalize()
	{
		if(g_finalized)
			return;
		g_finalized = true;

		if(g_checksumFile != NULL)
		{
			// The checksum log is a determinism artifact, so it must contain
			// only deterministic content. The rendered-frame count depends on
			// wall-clock pacing and is deliberately omitted here (it is still
			// printed to stdout below for humans).
			fprintf(g_checksumFile,
				"summary tics=%lu checksum=%08x\n",
				(unsigned long)g_ticCount,
				(unsigned int)g_worldChecksum);
			fclose(g_checksumFile);
			g_checksumFile = NULL;
		}

		if(g_playerFile != NULL)
		{
			fclose(g_playerFile);
			g_playerFile = NULL;
		}

		if(g_actorFile != NULL)
		{
			fclose(g_actorFile);
			g_actorFile = NULL;
		}

		Printf("Capture: summary tics=%lu frames=%lu checksum=%08x\n",
			(unsigned long)g_ticCount,
			(unsigned long)g_frameCount,
			(unsigned int)g_worldChecksum);

		// The command digest is separate from the world checksum on purpose:
		// "the machines disagree about what was pressed" and "the machines
		// disagree about what happened" are different failures, and a single
		// number cannot tell you which one you have.
		Command::CloseTrace();
		const Command::Violations &bad = Command::GetViolations();
		Printf("Capture: commands digest=%08x clamped=%u stripped=%u missing=%u\n",
			(unsigned int)Command::Digest(),
			bad.clampedAxes, bad.strippedButtons, bad.missingCommands);
	}

	// Set for every argv index this harness consumed -- see ClaimArg in the
	// header for why CheckParameters needs to know.
	TArray<bool> g_claimed;
}

void ClaimArg(int index)
{
	if(index < 0)
		return;
	while((int)g_claimed.Size() <= index)
		g_claimed.Push(false);
	g_claimed[index] = true;
}

bool ArgClaimed(int index)
{
	return index >= 0 && index < (int)g_claimed.Size() && g_claimed[index];
}

void ParseArgs(int argc, char **argv)
{
	for(int i = 1; i < argc; ++i)
	{
		const char *arg = argv[i];
		// Where this option started. Every branch below advances i over the
		// values it takes, so claiming first..i afterward records the option
		// and its values without a second table saying how many that is.
		const int first = i;
		bool unmatched = false;
		if(strcmp(arg, "--capture-rngseed") == 0 && i + 1 < argc)
		{
			g_seed = (DWORD)strtoul(argv[++i], NULL, 0);
			g_haveSeed = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-checksum") == 0 && i + 1 < argc)
		{
			g_checksumPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-players") == 0 && i + 1 < argc)
		{
			g_playerPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-actors") == 0 && i + 1 < argc)
		{
			g_actorPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-frame") == 0 && i + 1 < argc)
		{
			g_captureFrame = atoi(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-file") == 0 && i + 1 < argc)
		{
			g_captureFile = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-xbrz") == 0 && i + 1 < argc)
		{
			g_xbrzFactor = atoi(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-maxframes") == 0 && i + 1 < argc)
		{
			g_maxFrames = atoi(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-maxtics") == 0 && i + 1 < argc)
		{
			g_maxTics = atoi(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-glworld") == 0 && i + 1 < argc)
		{
			g_glWorldPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-glframe") == 0 && i + 1 < argc)
		{
			g_glFramePath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-glpresent") == 0 && i + 1 < argc)
		{
			g_glPresentPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-glxbrz") == 0 && i + 1 < argc)
		{
			g_glXBRZPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-open-doors") == 0 && i + 1 < argc)
		{
			g_openDoors = atoi(argv[++i]);
			if(g_openDoors < 0)     g_openDoors = 0;
			if(g_openDoors > 0xffff) g_openDoors = 0xffff;
			g_haveOpenDoors = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-push") == 0 && i + 1 < argc)
		{
			g_pushAmount = atoi(argv[++i]);
			if(g_pushAmount < 0)  g_pushAmount = 0;
			if(g_pushAmount > 64) g_pushAmount = 64;
			g_havePush = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-duel") == 0 && i + 2 < argc)
		{
			g_duelA = atoi(argv[++i]);
			g_duelB = atoi(argv[++i]);
			if(i + 1 < argc && argv[i+1][0] >= '0' && argv[i+1][0] <= '9')
				g_duelC = atoi(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-tape") == 0 && i + 1 < argc)
		{
			g_tapes.Push(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-commands") == 0 && i + 1 < argc)
		{
			g_commandTracePath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-tally") == 0 && i + 1 < argc)
		{
			g_tallyPath = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-scoreboard") == 0)
		{
			g_holdScoreboard = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-place") == 0 && i + 3 < argc)
		{
			g_placeTic = atol(argv[++i]);
			g_placeX = atof(argv[++i]);
			g_placeY = atof(argv[++i]);
			if(i + 1 < argc && argv[i+1][0] >= '0' && argv[i+1][0] <= '9')
				g_placeAngle = atof(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-snapshot") == 0 && i + 2 < argc)
		{
			g_snapshotPath = argv[++i];
			g_snapshotTic = atol(argv[++i]);
			if(g_snapshotTic < 0)
				g_snapshotTic = 0;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-trace") == 0)
		{
			g_traceFrom = (i + 1 < argc && argv[i+1][0] >= '0' && argv[i+1][0] <= '9')
				? atol(argv[++i]) : 0;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-forward") == 0 || strcmp(arg, "--capture-use") == 0)
		{
			PressWindow window = { 0, -1 };
			if(i + 1 < argc && argv[i+1][0] >= '0' && argv[i+1][0] <= '9')
			{
				window.from = atol(argv[++i]);
				if(i + 1 < argc && argv[i+1][0] >= '0' && argv[i+1][0] <= '9')
					window.tics = atol(argv[++i]);
			}
			if(strcmp(arg, "--capture-forward") == 0)
				g_forwardWindows.Push(window);
			else
				g_useWindows.Push(window);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-ammo") == 0)
		{
			g_topUpAmmo = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-fire") == 0)
		{
			g_fireFrom = (i + 1 < argc && argv[i+1][0] != '-') ? atol(argv[++i]) : 0;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-warp") == 0 && i + 3 < argc)
		{
			// Strictly parsed. atof() answers 0 for "banana" and happily
			// returns a NaN for "nan", and a camera at NaN moved the player to
			// a coordinate no arithmetic recovers from -- silently, because
			// there was nothing to notice it. A snapshot of the wrong place is
			// worse than no snapshot, so anything that is not a plain finite
			// number is refused here and the warp stays disarmed.
			// All three tokens are taken first and judged afterward. Doing
			// it inside a && chain short-circuits on the first bad one, which
			// leaves the other two unconsumed -- and an unconsumed token in
			// this engine is a filename, so "--capture-warp banana 31 90"
			// asked the wad loader for files called 31 and 90.
			const char *ax = argv[++i];
			const char *ay = argv[++i];
			const char *ad = argv[++i];
			double tx = 0, ty = 0, deg = 0;
			const bool ok = ParseFinite(ax, tx) && ParseFinite(ay, ty)
				&& ParseFinite(ad, deg);
			if(!ok)
			{
				printf("Capture: --capture-warp needs three finite numbers "
					"(tile x, tile y, degrees); ignoring it.\n");
			}
			else
			{
				g_warpTileX = tx;
				g_warpTileY = ty;
				g_warpX = (fixed)((tx + 0.5) * (double)TILEGLOBAL);
				g_warpY = (fixed)((ty + 0.5) * (double)TILEGLOBAL);
				double a = deg / 360.0; a -= (double)(long)a; if(a < 0) a += 1.0;
				g_warpAngle = (angle_t)(a * 4294967296.0);
				g_warpDegrees = deg;
				g_haveWarp = true;
				g_armed = true;
			}
		}
		else if(strcmp(arg, "--capture-extralight") == 0 && i + 1 < argc)
		{
			ExtraLightStep el;
			el.value = atoi(argv[++i]);
			el.frame = (i + 1 < argc && argv[i+1][0] != '-') ? atoi(argv[++i]) : 0;
			g_extraLights.Push(el);
			if(el.frame <= 0)
				g_extraLight = el.value;	// active from the first frame
			g_haveExtraLight = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-give") == 0 && i + 1 < argc)
		{
			g_giveClass = argv[++i];
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-c7map") == 0)
		{
			g_c7Map = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-verbs") == 0)
		{
			g_verbs = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-floorplan") == 0)
		{
			g_c7FloorPlan = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-exitlevel") == 0 && i + 1 < argc)
		{
			g_exitLevelTic = atol(argv[++i]);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-visormode") == 0 && i + 1 < argc)
		{
			g_visorMode = atoi(argv[++i]);
			g_haveVisorMode = true;
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-vidmode") == 0 && i + 3 < argc)
		{
			VidModeChange vm;
			vm.w = atoi(argv[++i]);
			vm.h = atoi(argv[++i]);
			vm.frame = atoi(argv[++i]);
			if(vm.w > 0 && vm.h > 0 && vm.frame > 0)
				g_vidModes.Push(vm);
			g_armed = true;
		}
		else if(strcmp(arg, "--capture-blend") == 0 && i + 4 < argc)
		{
			g_blendR = atoi(argv[++i]) & 0xFF;
			g_blendG = atoi(argv[++i]) & 0xFF;
			g_blendB = atoi(argv[++i]) & 0xFF;
			g_blendA = atoi(argv[++i]);
			if(g_blendA < 0)   g_blendA = 0;
			if(g_blendA > 256) g_blendA = 256;
			g_haveBlend = true;
			g_armed = true;
		}
		else
			unmatched = true;

		if(strncmp(arg, "--capture-", 10) == 0)
		{
			// Claimed whether or not a branch above recognized it. An option in
			// this namespace that nothing matched is either a typo or one given
			// without the value it needs, and saying so is better than silently
			// ignoring it -- and far better than what used to happen, which was
			// handing it to the wad loader to fail to stat.
			if(unmatched)
				printf("Capture: unrecognised option '%s' (or its value is "
					"missing); ignored.\n", arg);
			for(int taken = first; taken <= i; ++taken)
				ClaimArg(taken);
		}
	}

	if(g_captureFile.IsEmpty())
		g_captureFile = "capture.png";

	if(g_armed && !g_checksumPath.IsEmpty())
	{
		g_checksumFile = fopen(g_checksumPath.GetChars(), "w");
		if(g_checksumFile == NULL)
			Printf("Capture: FAILED to open checksum log '%s'\n",
				g_checksumPath.GetChars());
	}

	if(g_armed && !g_playerPath.IsEmpty())
	{
		g_playerFile = fopen(g_playerPath.GetChars(), "w");
		if(g_playerFile == NULL)
			Printf("Capture: FAILED to open player trace '%s'\n",
				g_playerPath.GetChars());
		else
			fprintf(g_playerFile, "# tic player tilex tiley angle health frags team teamfrags class x y\n");
	}

	if(g_armed && !g_actorPath.IsEmpty())
	{
		g_actorFile = fopen(g_actorPath.GetChars(), "w");
		if(g_actorFile == NULL)
			Printf("Capture: FAILED to open actor trace '%s'\n",
				g_actorPath.GetChars());
		else
			fprintf(g_actorFile, "# tic class tilex tiley dir pathing attack health\n");
	}

#ifdef ECWOLF_RENDERER_OPENGL
	// Arm the live GL present capture (it keeps the latest presented frame; we
	// write it at the chosen gameplay frame in PostFrame).
	if(!g_glPresentPath.IsEmpty())
		R_GLLiveArmCapture(g_glPresentPath.GetChars(), g_captureFrame);
	// The xBRZ parity pair is written by the first 2D-only present after this,
	// which is the title or menu page the game opens on -- deliberately not tied
	// to --capture-frame, since frames are only counted once a level is running
	// and the comparison is only meaningful before one is.
	if(!g_glXBRZPath.IsEmpty())
		R_GLXBRZArmParityCapture(g_glXBRZPath.GetChars());
#endif
}

bool Active()
{
	return g_armed;
}

bool OverrideRNGSeed(DWORD &seed)
{
	if(!g_haveSeed)
		return false;
	seed = g_seed;
	Printf("Capture: forcing RNG seed 0x%08x\n", (unsigned int)g_seed);
	return true;
}

	// Choose (once) the solid, non-door wall cell nearest the player that has an
	// open neighbor, and wire it up as a mid-move pushwall exactly the way
	// EVPushwall does (SetTile the destination, point pushReceptor back). The
	// raycaster and the GL dynamic builder both read this state, so the same
	// moving block appears in each renderer. Test-only; never in the gate.
	void SetupSyntheticPushwall()
	{
		AActor *pmo = players[ConsolePlayer].mo;
		if(pmo == NULL)
			return;
		const double pxf = (double)pmo->x / (double)TILEGLOBAL;
		const double pyf = (double)pmo->y / (double)TILEGLOBAL;
		// ECWolf forward vector convention: (cos a, -sin a).
		const double a = (double)pmo->angle / 4294967296.0 * 2.0 * 3.14159265358979;
		const double fdx = cos(a), fdy = -sin(a);

		// Prefer the nearest eligible wall that is in front of the player so the
		// moving block lands in the captured view.
		const GameMap::Header &hdr = map->GetHeader();
		MapSpot best = NULL;
		int bestDir = 0;
		double bestScore = -1.0;
		for(unsigned int y = 0; y < hdr.height; ++y)
		for(unsigned int x = 0; x < hdr.width; ++x)
		{
			MapSpot s = map->GetSpot(x, y, 0);
			if(!s->tile || s->tile->offsetVertical || s->tile->offsetHorizontal)
				continue;
			for(int dir = 0; dir < 4; ++dir)
			{
				MapSpot n = s->GetAdjacent((MapTile::Side)dir);
				if(n == NULL || n->tile != NULL || n->sector == NULL)
					continue;
				const double cx = (double)x + 0.5 - pxf;
				const double cy = (double)y + 0.5 - pyf;
				const double dist = sqrt(cx*cx + cy*cy);
				if(dist < 0.5 || dist > 12.0)
					break;
				const double fwd = (cx*fdx + cy*fdy) / dist;	// cos(angle off view)
				if(fwd < 0.6)			// keep it well inside the forward cone
					break;
				const double score = fwd / dist;	// near + centered wins
				if(score > bestScore)
				{
					bestScore = score;
					best = s;
					bestDir = dir;
				}
				break;
			}
		}
		if(best == NULL)
			return;

		MapSpot moveTo = best->GetAdjacent((MapTile::Side)bestDir);
		best->pushDirection = (MapTile::Side)bestDir;
		moveTo->SetTile(best->tile);
		moveTo->pushReceptor = best;
		moveTo->pushDirection = (MapTile::Side)bestDir;
		for(int i = 0; i < 4; ++i)
			moveTo->texture[i] = best->texture[i];
		g_pushOrigin = best;
	}
}

namespace Capture
{

	// Choose where the duel happens, once per level, from the map itself.
	//
	// Every machine runs this over the same map and in the same order, so every
	// machine gets the same answer without a byte crossing the wire. Tiles are
	// not hardcoded because the arenas do not share a layout and a tile that is
	// floor in one is solid in the next.
	void FindDuelSpots()
	{
		g_duelFound = true;
		for(unsigned int i = 0;i < MAXPLAYERS;++i)
		{
			g_duelX[i] = g_duelY[i] = 0;
			g_duelAngle[i] = 0;
		}
		if(map == NULL)
			return;

		const GameMap::Header &hdr = map->GetHeader();

		TArray<unsigned int> open;
		for(unsigned int y = 0;y < hdr.height;++y)
		{
			for(unsigned int x = 0;x < hdr.width;++x)
			{
				MapSpot spot = map->GetSpot(x, y, 0);
				if(spot->tile == NULL && spot->sector != NULL)
					open.Push(y*hdr.width + x);
			}
		}
		if(open.Size() == 0)
			return;

		// The fight goes in the middle, where an arena is most likely to have
		// room on both sides; the parked players go to the first open cells in
		// scan order, which is the opposite corner of the map from it.
		const unsigned int cx = hdr.width/2, cy = hdr.height/2;
		unsigned int anchor = open[0];
		unsigned int best = 0xFFFFFFFF;
		for(unsigned int i = 0;i < open.Size();++i)
		{
			const unsigned int x = open[i]%hdr.width, y = open[i]/hdr.width;
			const unsigned int dx = x > cx ? x-cx : cx-x;
			const unsigned int dy = y > cy ? y-cy : cy-y;
			const unsigned int d = dx*dx + dy*dy;
			if(d < best) { best = d; anchor = open[i]; }
		}

		const unsigned int ax = anchor%hdr.width, ay = anchor/hdr.width;

		// The opponent stands a few tiles away in whichever direction has open
		// floor. Three tiles is inside every weapon's reach and far enough that
		// the two are not standing in the same cell.
		static const int dirs[4][2] = { {1,0}, {-1,0}, {0,1}, {0,-1} };
		int bx = -1, by = -1, faceDir = 0;
		for(unsigned int gap = 3;gap >= 2 && bx < 0;--gap)
		{
			for(unsigned int d = 0;d < 4;++d)
			{
				const int tx = (int)ax + dirs[d][0]*(int)gap;
				const int ty = (int)ay + dirs[d][1]*(int)gap;
				if(tx < 0 || ty < 0 || (unsigned)tx >= hdr.width || (unsigned)ty >= hdr.height)
					continue;
				MapSpot spot = map->GetSpot(tx, ty, 0);
				if(spot->tile != NULL || spot->sector == NULL)
					continue;
				bx = tx; by = ty; faceDir = d;
				break;
			}
		}
		if(bx < 0)
			return;

		// Angles increase anticlockwise from east, which is how the rest of the
		// engine reads them.
		static const angle_t facing[4] = { 0, ANGLE_180, ANGLE_270, ANGLE_90 };

		if(g_duelA >= 0 && g_duelA < MAXPLAYERS)
		{
			g_duelX[g_duelA] = (ax<<FRACBITS) + (FRACUNIT/2);
			g_duelY[g_duelA] = (ay<<FRACBITS) + (FRACUNIT/2);
			g_duelAngle[g_duelA] = facing[faceDir];
		}
		if(g_duelB >= 0 && g_duelB < MAXPLAYERS)
		{
			g_duelX[g_duelB] = ((unsigned)bx<<FRACBITS) + (FRACUNIT/2);
			g_duelY[g_duelB] = ((unsigned)by<<FRACBITS) + (FRACUNIT/2);
			g_duelAngle[g_duelB] = facing[faceDir] + ANGLE_180;
		}

		// One tile behind A, facing the same way. Auto-aim skips a team-mate, so
		// C shoots past A at B rather than at the back of A's head.
		if(g_duelC >= 0 && g_duelC < MAXPLAYERS)
		{
			const int tx = (int)ax - dirs[faceDir][0];
			const int ty = (int)ay - dirs[faceDir][1];
			if(tx >= 0 && ty >= 0 && (unsigned)tx < hdr.width && (unsigned)ty < hdr.height)
			{
				MapSpot spot = map->GetSpot(tx, ty, 0);
				if(spot->tile == NULL && spot->sector != NULL)
				{
					g_duelX[g_duelC] = ((unsigned)tx<<FRACBITS) + (FRACUNIT/2);
					g_duelY[g_duelC] = ((unsigned)ty<<FRACBITS) + (FRACUNIT/2);
					g_duelAngle[g_duelC] = facing[faceDir];
				}
			}
		}

		unsigned int park = 0;
		for(unsigned int i = 0;i < MAXPLAYERS;++i)
		{
			if((int)i == g_duelA || (int)i == g_duelB || (int)i == g_duelC)
				continue;
			// Spread the bystanders out so they cannot shoot each other either;
			// this gate is about the two in the middle.
			while(park < open.Size())
			{
				const unsigned int x = open[park]%hdr.width, y = open[park]/hdr.width;
				const unsigned int dx = x > ax ? x-ax : ax-x;
				const unsigned int dy = y > ay ? y-ay : ay-y;
				if(dx + dy > 16)
					break;
				++park;
			}
			if(park >= open.Size())
				break;
			g_duelX[i] = ((open[park]%hdr.width)<<FRACBITS) + (FRACUNIT/2);
			g_duelY[i] = ((open[park]/hdr.width)<<FRACBITS) + (FRACUNIT/2);
			g_duelAngle[i] = ANGLE_90;
			park += 4;
		}
	}

// Hold the trigger for the local player.
//
// Deliberately injected into the command before it is exchanged rather than
// applied to the pawn directly: the point of the gate this exists for is that
// two machines agree about a fight, and a shot that never traveled over the
// wire would prove nothing about that.
void SetupScriptedSlots(FName (&playerClassNames)[MAXPLAYERS])
{
	if(!g_commandTracePath.IsEmpty())
		Command::OpenTrace(g_commandTracePath.GetChars());

	for(unsigned int i = 0;i < g_tapes.Size();++i)
	{
		FString error;
		Command::Producer *producer =
			Command::MakeScriptedProducer(g_tapes[i].GetChars(), error);
		if(producer == NULL)
		{
			// Fatal rather than skipped: a gate that quietly ran with one
			// fewer player than it asked for would still pass, and would be
			// testing something nobody chose.
			I_FatalError("%s", error.GetChars());
		}

		const unsigned int slot = Session::AddAuthoritySlot(0, 0x5eed0000u + i);
		if(slot >= Session::MAX_PLAYER_SLOTS)
		{
			delete producer;
			I_FatalError("No room for command tape '%s': %u slots already",
				g_tapes[i].GetChars(), Session::ActiveSlotCount());
		}

		Command::SetProducer(slot, producer);
		// The same character as the player, so the tape is an ordinary
		// opponent rather than something with different rules.
		playerClassNames[slot] = playerClassNames[0];
		Printf("Capture: slot %u is driven by command tape '%s'.\n",
			slot, g_tapes[i].GetChars());
	}
}

void InjectControls(TicCmd_t &cmd)
{
	if(g_holdScoreboard)
		cmd.buttonstate[bt_scoreboard] = true;

	if(InWindow(g_forwardWindows))
	{
		cmd.controly = -RUNMOVE;
		cmd.buttonstate[bt_run] = true;
	}

	if(InWindow(g_useWindows))
		cmd.buttonstate[bt_use] = true;

	if(g_fireFrom < 0 || (long)gamestate.TimeCount < g_fireFrom)
		return;
	cmd.buttonstate[bt_attack] = true;
}

void PreTic()
{
	if(!g_armed || map == NULL)
		return;

	if(!g_giveClass.IsEmpty() && !g_giveDone && players[ConsolePlayer].mo)
	{
		g_giveDone = true;
		const ClassDef *cls = ClassDef::FindClass(g_giveClass);
		if(cls == NULL)
			Printf("Capture: no such class '%s' to give.\n", g_giveClass.GetChars());
		else
		{
			players[ConsolePlayer].mo->GiveInventory(cls, 0, true);
			Printf("Capture: gave the player %s.\n", g_giveClass.GetChars());
		}
	}

	if(g_exitLevelTic >= 0 && !g_exitLevelDone &&
		(long)gamestate.TimeCount >= g_exitLevelTic)
	{
		g_exitLevelDone = true;
		Printf("Capture: completing level at tic %lu\n",
			(unsigned long)gamestate.TimeCount);
		playstate = ex_completed;
	}

	// Force every door cell to a fixed slide amount each tic. Applied before the
	// thinkers run so DynamicWalls::EndTic snapshots it and both renderers agree;
	// this is a rendering test override and is never used by the determinism gate.
	if(g_haveOpenDoors)
	{
		const GameMap::Header &hdr = map->GetHeader();
		for(unsigned int y = 0; y < hdr.height; ++y)
		for(unsigned int x = 0; x < hdr.width; ++x)
		{
			MapSpot spot = map->GetSpot(x, y, 0);
			if(spot->tile &&
				(spot->tile->offsetVertical || spot->tile->offsetHorizontal))
			{
				spot->slideAmount[0] = spot->slideAmount[1] =
					spot->slideAmount[2] = spot->slideAmount[3] =
					(unsigned int)g_openDoors;
			}
		}
	}

	if(g_havePush)
	{
		if(g_pushOrigin == NULL)
			SetupSyntheticPushwall();
		if(g_pushOrigin != NULL)
			g_pushOrigin->pushAmount = (unsigned int)g_pushAmount;
	}

	// Pin the player to a fixed tile + facing so a specific viewpoint can be
	// reproduced for renderer comparison, independent of the deterministic bot.
	// Applied every tic; both renderers are pinned identically, so software vs
	// GL comparisons at any frame stay valid.
	// Every player, from a table every machine computed the same way.
	if(g_duelA >= 0)
	{
		if(!g_duelFound)
			FindDuelSpots();
		for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		{
			if(players[i].mo == NULL || g_duelX[i] == 0)
				continue;
			// The dead are left where they fell. A corpse turns toward the
			// angle it died facing, and only once it has arrived does the
			// player become eligible to respawn -- so pinning the angle of a
			// dead player holds them dead for ever. It cost a long detour:
			// the fight simply stopped after the first kill, which reads much
			// more like a weapon or a network fault than like a test fixture
			// standing on the death animation's foot.
			if(players[i].health <= 0)
				continue;
			players[i].mo->x = g_duelX[i];
			players[i].mo->y = g_duelY[i];
			players[i].mo->angle = g_duelAngle[i];
			players[i].mo->pitch = 0;
		}
	}

	if(g_topUpAmmo)
	{
		for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
		{
			if(players[i].mo == NULL)
				continue;
			for(AInventory *inv = players[i].mo->inventory;inv != NULL;inv = inv->inventory)
			{
				if(inv->IsKindOf(NATIVE_CLASS(Ammo)))
					inv->amount = inv->maxamount;
			}
		}
	}

	if(g_haveWarp)
	{
		// Checked against the map that actually loaded, once, before the player
		// is moved anywhere. A tile outside the map, or one with a wall in it,
		// is a camera that produces a picture of the inside of a wall or of
		// nothing -- and the editor would cache that as this map's snapshot.
		if(!g_warpChecked)
		{
			g_warpChecked = true;
			const int tx = (int)g_warpTileX, ty = (int)g_warpTileY;
			const int w = (int)map->GetHeader().width;
			const int h = (int)map->GetHeader().height;
			if(g_warpTileX < 0 || g_warpTileY < 0 || tx >= w || ty >= h)
			{
				printf("Capture: camera tile (%g, %g) is outside this %dx%d map; "
					"not moving the player.\n", g_warpTileX, g_warpTileY, w, h);
				g_haveWarp = false;
			}
			else if(map->GetSpot(tx, ty, 0)->tile != NULL)
			{
				printf("Capture: camera tile (%d, %d) is inside a wall; "
					"not moving the player.\n", tx, ty);
				g_haveWarp = false;
			}
			else
			{
				printf("Capture: camera at tile (%g, %g) facing %g degrees.\n",
					g_warpTileX, g_warpTileY, g_warpDegrees);
			}
		}

		AActor *pmo = players[ConsolePlayer].mo;
		if(g_haveWarp && pmo)
		{
			pmo->x = g_warpX;
			pmo->y = g_warpY;
			pmo->angle = g_warpAngle;
			pmo->pitch = 0;
		}
	}

	if(g_placeTic >= 0 && !g_placeDone && (long)gamestate.TimeCount >= g_placeTic &&
		players[ConsolePlayer].mo)
	{
		g_placeDone = true;
		AActor *pmo = players[ConsolePlayer].mo;
		pmo->x = FLOAT2FIXED(g_placeX);
		pmo->y = FLOAT2FIXED(g_placeY);
		if(g_placeAngle >= 0.0)
			pmo->angle = (angle_t)(g_placeAngle * ANGLE_1);
		Printf("Capture: placed the player at %.4f, %.4f\n", g_placeX, g_placeY);
	}

	if(g_traceFrom >= 0 && (long)gamestate.TimeCount >= g_traceFrom &&
		players[ConsolePlayer].mo)
	{
		const AActor *pmo = players[ConsolePlayer].mo;
		Printf("Capture: trace tic=%u x=%.4f y=%.4f tile=(%u,%u)\n",
			gamestate.TimeCount, FIXED2FLOAT(pmo->x), FIXED2FLOAT(pmo->y),
			pmo->tilex, pmo->tiley);
	}
}

void ApplyPaletteOverride()
{
	// Pin the player's extralight, which is what the Corridor 7 visor drives
	// (a_playerpawn.cpp sets 20 in visor mode 2, 12 during a muzzle flash). It
	// brightens the plane shading: wl_floorceiling.cpp subtracts extraLight/8 from
	// the band and lowers firstShade by extraLight/16, and the GL shader mirrors
	// that. Forcing it lets visor-lit planes be compared between renderers without
	// scripted input -- notably across a video mode change, where the GL side has
	// to rebuild its plane shade table for the new context.
	//
	// Applied here rather than in PreTic because the player pawn's Tick assigns
	// extralight from the visor inventory every tic, which would overwrite it.
	// This runs after the tics and before the scene is rendered, so it is the
	// value both renderers actually see.
	if(g_haveExtraLight)
	{
		if(players[ConsolePlayer].mo && players[ConsolePlayer].mo->player)
			players[ConsolePlayer].mo->player->extralight = (short)g_extraLight;
	}

	// Force a Corridor 7 visor palette. Applied here, after UpdatePaletteShifts
	// has set the mode from the player's C7VisorMode inventory, so it wins for
	// the frame about to be rendered. Both renderers read the result through the
	// framebuffer palette, so this compares the visor between them -- and against
	// the original -- without scripted input.
	//
	// The C7VisorMode token is set to match. The palette is not the whole visor:
	// r_sprites.cpp gates the laser-barrier statics on that token, so forcing the
	// palette alone gives an infrared view with the one thing infrared exists to
	// reveal still hidden. Mode 0/1/2 here is token 1/2/3 (UpdatePaletteShifts
	// maps it the other way).
	if(g_haveVisorMode)
	{
		if(players[ConsolePlayer].mo)
		{
			AInventory *mode = players[ConsolePlayer].mo->FindInventory(
				ClassDef::FindClass("C7VisorMode"));
			if(mode)
				mode->amount = g_visorMode + 1;
		}
		V_SetCorridor7PaletteMode(g_visorMode, 0);
	}

	// Raise Corridor 7's inset map panel. It is a toggle held in c7_automap.cpp
	// rather than a palette or view setting, so forcing it each frame is what
	// makes it reachable without scripted input.
	if(g_c7Map && !C7Map_Active())
		C7Map_Toggle();

	// Stand in for having picked up the floor plan. Only the revealed state is
	// forced, not the inventory token, so this stays a render-side override
	// like the rest of this function -- the panel reads either one. The pickup
	// itself needs the equipment cheat held down for two seconds, which is
	// input-timing dependent and cannot be part of a deterministic capture.
	if(g_c7FloorPlan)
		gamestate.fullmap = true;

	if(!g_haveBlend)
		return;

	// Force the full-screen flash after UpdatePaletteShifts has run for this
	// frame (so gameplay does not clobber it) and before the scene is rendered.
	// Both renderers read this through the framebuffer's flash: the software
	// scanout blends it into the palette, and the GL path uploads
	// GetFlashedPalette() to its palette texture.
	V_ForceBlend(g_blendR, g_blendG, g_blendB, g_blendA);
}

// Printed only when something moves, so a run of any length stays readable and
// the absence of a line is itself the assertion that nothing happened.
static void TraceVerbs()
{
	if(!g_verbs)
		return;

	player_t &player = players[ConsolePlayer];
	AActor *pawn = player.mo;

	int visor = 0, mines = 0, ammo = 0, health = 0;
	if(pawn)
	{
		if(AInventory *mode = pawn->FindInventory(ClassDef::FindClass("C7VisorMode")))
			visor = mode->amount;
		if(AInventory *m = pawn->FindInventory(ClassDef::FindClass("C7Mines")))
			mines = m->amount;
		health = player.health;
	}
	if(player.ReadyWeapon && player.ReadyWeapon->ammo[AWeapon::PrimaryFire])
		ammo = player.ReadyWeapon->ammo[AWeapon::PrimaryFire]->amount;

	const int map = C7Map_Active() ? 1 : 0;
	const int angle = pawn ? (int)(pawn->angle >> 24) : 0;
	const int x = pawn ? (int)(pawn->x >> 10) : 0;
	const int y = pawn ? (int)(pawn->y >> 10) : 0;

	static bool first = true;
	static int lastVisor, lastMines, lastAmmo, lastHealth, lastMap, lastAngle, lastX, lastY;
	if(first || visor != lastVisor || mines != lastMines || ammo != lastAmmo ||
		health != lastHealth || map != lastMap || angle != lastAngle ||
		x != lastX || y != lastY)
	{
		Printf("verbs tic=%lu visor=%d mines=%d map=%d ammo=%d health=%d x=%d y=%d angle=%d\n",
			(unsigned long)g_ticCount, visor, mines, map, ammo, health, x, y, angle);
		first = false;
		lastVisor = visor; lastMines = mines; lastAmmo = ammo; lastHealth = health;
		lastMap = map; lastAngle = angle; lastX = x; lastY = y;
	}
}

void PerTic()
{
	if(!g_armed)
		return;

	++g_ticCount;
	const DWORD ticCrc = ChecksumThisTic();
	g_worldChecksum = Fold(g_worldChecksum, &ticCrc, sizeof(ticCrc));

	if(g_checksumFile != NULL)
		fprintf(g_checksumFile, "tic %lu %08x\n",
			(unsigned long)g_ticCount, (unsigned int)ticCrc);

	TraceActors();
	TracePlayers();
	TraceVerbs();

	// A tic-based quit keeps the determinism gate reproducible under the
	// current wall-clock frame pacing, where the tic-per-frame ratio varies.
	if(g_maxTics > 0 && g_ticCount >= (uint64_t)g_maxTics)
	{
		Finalize();
		Quit();
	}
}

void WriteTallyShot()
{
	if(!g_armed || g_tallyPath.IsEmpty())
		return;
	WriteScreenshot(g_tallyPath.GetChars());
}

void NoteArtifactComplete()
{
	g_artifactComplete = true;
}

void PostPresent()
{
	if(!g_armed || !g_artifactComplete)
		return;

	// Cleared first: Quit() unwinds by throwing, and a handler that presented
	// another frame on the way out would otherwise re-enter this.
	g_artifactComplete = false;
	Finalize();
	Quit();
}

void PostFrame()
{
	if(!g_armed)
		return;

	++g_frameCount;

	// The editor's Snapshot: first frame drawn at or after the chosen tic.
	// One line of result, then out -- the editor is waiting on the process, and
	// a snapshot run that carried on playing would be a window nobody asked for.
	if(!g_snapshotDone && !g_snapshotPath.IsEmpty() && map != NULL
		&& (long)g_ticCount >= g_snapshotTic)
	{
		g_snapshotDone = true;
		WriteScreenshot(g_snapshotPath.GetChars());
#ifdef ECWOLF_RENDERER_OPENGL
		// The same GL captures the frame-anchored shot does. Not because a
		// snapshot needs them, but because a caller that asked for one asked
		// for it on purpose -- and the GL world capture prints how many
		// textures carried an opacity plane, which is the only way the upscale
		// gate can see that masked walls kept their transparency. Leaving them
		// out silently removed a check's evidence rather than its subject.
		if(!g_glWorldPath.IsEmpty())
			R_GLWorldCapture(g_glWorldPath.GetChars());
		if(!g_glFramePath.IsEmpty())
			R_GLFrameCapture(g_glFramePath.GetChars());
		if(!g_glPresentPath.IsEmpty())
			R_GLLiveWriteCapture();
#endif
		printf("Capture: snapshot '%s' tic=%lu frame=%lu map=%s camera=%g,%g,%g\n",
			g_snapshotPath.GetChars(), (unsigned long)g_ticCount,
			(unsigned long)g_frameCount, gamestate.mapname,
			g_warpTileX, g_warpTileY, g_warpDegrees);
		fflush(stdout);
		Finalize();
		Quit();
	}

	if(g_captureFrame > 0 && (uint64_t)g_captureFrame == g_frameCount)
	{
		WriteScreenshot(g_captureFile.GetChars());
#ifdef ECWOLF_RENDERER_OPENGL
		// Render the same view with the GL static-world renderer for parity
		// comparison against the software screenshot just taken.
		if(!g_glWorldPath.IsEmpty())
			R_GLWorldCapture(g_glWorldPath.GetChars());
		// Composite the full playable frame in GL (3D world + the engine's 8-bit
		// 2D overlay) for parity against the same software screenshot.
		if(!g_glFramePath.IsEmpty())
			R_GLFrameCapture(g_glFramePath.GetChars());
		// When the GL backend is live, write the actual on-window presented frame.
		if(!g_glPresentPath.IsEmpty())
			R_GLLiveWriteCapture();
#endif
	}

	// Change the video mode mid-run, the way the Display menu's resolution picker
	// does (MENU_LISTENER(SetResolution) in wl_menu.cpp). Toggling fullscreen
	// takes the same path -- VL_SetFullscreen just swaps in the fullscreen or
	// windowed size before calling VL_SetVGAPlaneMode -- so this exercises both
	// reported cases, and in particular the framebuffer/GL-context recreation
	// that follows. Applied after frame N is captured, so a capture at a later
	// frame shows what the renderer produces once the mode has changed.
	// Scheduled extralight (visor) changes take effect from their frame onward.
	for(unsigned int i = 0; i < g_extraLights.Size(); ++i)
	{
		if(g_extraLights[i].frame > 0 &&
			(uint64_t)g_extraLights[i].frame == g_frameCount)
		{
			g_extraLight = g_extraLights[i].value;
			Printf("Capture: extralight -> %d at frame %d.\n",
				g_extraLight, g_extraLights[i].frame);
		}
	}

	for(unsigned int i = 0; i < g_vidModes.Size(); ++i)
	{
		if((uint64_t)g_vidModes[i].frame != g_frameCount)
			continue;
		Printf("Capture: switching video mode to %dx%d at frame %d.\n",
			g_vidModes[i].w, g_vidModes[i].h, g_vidModes[i].frame);
		windowWidth = windowedScreenWidth = g_vidModes[i].w;
		windowHeight = windowedScreenHeight = g_vidModes[i].h;
		VL_UpdateRenderSize();
		r_ratio = static_cast<Aspect>(CheckRatio(windowWidth, windowHeight));
		VH_Startup();	// recalculate fizzlefade tables for the new size
		VL_SetVGAPlaneMode();
	}

	const bool hitFrameLimit =
		(g_maxFrames > 0 && g_frameCount >= (uint64_t)g_maxFrames);
	const bool doneCapturing =
		(g_captureFrame > 0 && g_frameCount >= (uint64_t)g_captureFrame &&
		 g_maxFrames <= 0);

	if(hitFrameLimit || doneCapturing)
	{
		Finalize();
		Quit();
	}
}

} // namespace Capture
