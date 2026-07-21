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
#include "v_palette.h"
#include "files.h"

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

	int      g_maxFrames      = -1;      // quit after this many rendered frames
	int      g_maxTics        = -1;      // quit after this many simulation tics

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

		FILE *file = fopen(path, "wb");
		if(file != NULL)
		{
			M_CreatePNG(file, buffer, GPalette.BaseColors, color_type,
				SCREENWIDTH, SCREENHEIGHT, pitch);
			M_FinishPNG(file);
			fclose(file);
			Printf("Capture: wrote screenshot '%s' at frame %lu\n",
				path, (unsigned long)g_frameCount);
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
		WriteScreenshot(g_captureFile.GetChars());

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
