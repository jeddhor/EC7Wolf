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
#include <string.h>
#include <math.h>

#include "r_capture.h"
#include "wl_def.h"
#include "wl_play.h"
#include "actor.h"
#include "wl_agent.h"
#include "wl_game.h"
#include "m_random.h"
#include "m_crc32.h"
#include "m_png.h"
#include "v_video.h"
#include "c7_automap.h"
#include "v_palette.h"
#include "files.h"
#include "c_cvars.h"
#include "id_ca.h"
#include "id_vl.h"
#include "id_vh.h"
#include "gamemap.h"
#ifdef ECWOLF_RENDERER_OPENGL
#include "render/opengl/r_glworld.h"
#endif

namespace Capture
{

namespace
{
	bool     g_armed          = false;

	bool     g_haveSeed       = false;
	DWORD    g_seed           = 0;

	FString  g_checksumPath;
	FILE    *g_checksumFile   = NULL;

	int      g_captureFrame   = -1;      // 1-based rendered frame to shoot
	FString  g_captureFile;

	FString  g_glWorldPath;              // Phase 5 GL world offscreen capture
	FString  g_glFramePath;              // Phase 10 full-frame composite capture
	FString  g_glPresentPath;            // Phase 10 live GL-presented frame

	int      g_maxFrames      = -1;      // quit after this many rendered frames
	int      g_maxTics        = -1;      // quit after this many simulation tics

	bool     g_haveOpenDoors  = false;   // --capture-open-doors world override
	int      g_openDoors      = 0;       // forced slide amount 0..65535

	bool     g_havePush       = false;   // --capture-push world override
	int      g_pushAmount     = 0;       // forced push amount 0..64
	MapSpot  g_pushOrigin      = NULL;   // synthetic pushwall origin (chosen once)

	bool     g_haveBlend      = false;   // --capture-blend full-screen flash override
	int      g_blendR = 0, g_blendG = 0, g_blendB = 0, g_blendA = 0;

	bool     g_haveWarp       = false;   // --capture-warp: pin player to a tile+angle
	fixed    g_warpX = 0, g_warpY = 0;
	angle_t  g_warpAngle = 0;

	// --capture-extralight VALUE [FROMFRAME]: pin the player's extralight from a
	// given rendered frame onward. Repeatable, so the visor can be switched on or
	// off part way through a run (20 = C7 visor mode 2, 12 = muzzle flash, 0 = off).
	struct ExtraLightStep { int value, frame; };
	TArray<ExtraLightStep> g_extraLights;
	bool     g_haveExtraLight = false;
	int      g_extraLight     = 0;

	bool     g_c7Map          = false;   // --capture-c7map: raise the C7 inset panel
	// --capture-exitlevel: complete the level at this tic, taking the same path
	// the elevator does (lnspec.cpp sets ex_completed), so a level transition can
	// be exercised headlessly. The debug "quit level" key cannot be driven under
	// Corridor 7 because its Tab modifier is the floor map.
	long     g_exitLevelTic   = -1;
	bool     g_exitLevelDone  = false;
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
		// colours. They are the same in ordinary play, but Corridor 7 rewrites the
		// DAC for the visor modes (V_SetCorridor7PaletteMode) and V_ForceBlend
		// adds a full-screen flash on top -- and a screenshot that ignores both
		// shows a grey scene where the game is displaying green or red, which
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
			if(players[ConsolePlayer].mo)
			{
				ptx = players[ConsolePlayer].mo->tilex;
				pty = players[ConsolePlayer].mo->tiley;
			}
			Printf("Capture: wrote screenshot '%s' at frame %lu tic %lu map %s player (%d,%d)\n",
				path, (unsigned long)g_frameCount,
				(unsigned long)gamestate.TimeCount,
				gamestate.mapname, ptx, pty);
		}
		else
			Printf("Capture: FAILED to open screenshot '%s'\n", path);

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

		Printf("Capture: summary tics=%lu frames=%lu checksum=%08x\n",
			(unsigned long)g_ticCount,
			(unsigned long)g_frameCount,
			(unsigned int)g_worldChecksum);
	}
}

void ParseArgs(int argc, char **argv)
{
	for(int i = 1; i < argc; ++i)
	{
		const char *arg = argv[i];
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
		else if(strcmp(arg, "--capture-warp") == 0 && i + 3 < argc)
		{
			const double tx = atof(argv[++i]);
			const double ty = atof(argv[++i]);
			const double deg = atof(argv[++i]);
			g_warpX = (fixed)((tx + 0.5) * (double)TILEGLOBAL);
			g_warpY = (fixed)((ty + 0.5) * (double)TILEGLOBAL);
			double a = deg / 360.0; a -= (double)(long)a; if(a < 0) a += 1.0;
			g_warpAngle = (angle_t)(a * 4294967296.0);
			g_haveWarp = true;
			g_armed = true;
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
		else if(strcmp(arg, "--capture-c7map") == 0)
		{
			g_c7Map = true;
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

#ifdef ECWOLF_RENDERER_OPENGL
	// Arm the live GL present capture (it keeps the latest presented frame; we
	// write it at the chosen gameplay frame in PostFrame).
	if(!g_glPresentPath.IsEmpty())
		R_GLLiveArmCapture(g_glPresentPath.GetChars(), g_captureFrame);
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
	// open neighbour, and wire it up as a mid-move pushwall exactly the way
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
				const double score = fwd / dist;	// near + centred wins
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

void PreTic()
{
	if(!g_armed || map == NULL)
		return;

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
	if(g_haveWarp)
	{
		AActor *pmo = players[ConsolePlayer].mo;
		if(pmo)
		{
			pmo->x = g_warpX;
			pmo->y = g_warpY;
			pmo->angle = g_warpAngle;
			pmo->pitch = 0;
		}
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
	if(g_haveVisorMode)
		V_SetCorridor7PaletteMode(g_visorMode, 0);

	// Raise Corridor 7's inset map panel. It is a toggle held in c7_automap.cpp
	// rather than a palette or view setting, so forcing it each frame is what
	// makes it reachable without scripted input.
	if(g_c7Map && !C7Map_Active())
		C7Map_Toggle();

	if(!g_haveBlend)
		return;

	// Force the full-screen flash after UpdatePaletteShifts has run for this
	// frame (so gameplay does not clobber it) and before the scene is rendered.
	// Both renderers read this through the framebuffer's flash: the software
	// scanout blends it into the palette, and the GL path uploads
	// GetFlashedPalette() to its palette texture.
	V_ForceBlend(g_blendR, g_blendG, g_blendB, g_blendA);
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

	// A tic-based quit keeps the determinism gate reproducible under the
	// current wall-clock frame pacing, where the tic-per-frame ratio varies.
	if(g_maxTics > 0 && g_ticCount >= (uint64_t)g_maxTics)
	{
		Finalize();
		Quit();
	}
}

void PostFrame()
{
	if(!g_armed)
		return;

	++g_frameCount;

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
		screenWidth = windowedScreenWidth = g_vidModes[i].w;
		screenHeight = windowedScreenHeight = g_vidModes[i].h;
		r_ratio = static_cast<Aspect>(CheckRatio(screenWidth, screenHeight));
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
