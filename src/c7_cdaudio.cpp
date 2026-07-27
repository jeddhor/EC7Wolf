/*
** c7_cdaudio.cpp
**
** Redbook soundtrack playback for the Corridor 7 CD release.
**
**---------------------------------------------------------------------------
** Copyright 2026 EC7Wolf contributors
** All rights reserved.
**
** Redistribution and use in source and binary forms, with or without
** modification, are permitted provided that the following conditions
** are met:
**
** 1. Redistributions of source code must retain the above copyright
**    notice, this list of conditions and the following disclaimer.
** 2. Redistributions in binary form must reproduce the above copyright
**    notice, this list of conditions and the following disclaimer in the
**    documentation and/or other materials provided with the distribution.
** 3. The name of the author may not be used to endorse or promote products
**    derived from this software without specific prior written permission.
**
** THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
** IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
** OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
** IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
** INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
** NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
** DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
** THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
** (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
** THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
**
*/

/*
** How the CD release actually used the disc
** =========================================
**
** Read out of CORR7CD.EXE rather than guessed at. Three routines matter:
**
**   18b8:09cf  the floor's StartMusic. Its first act is:
**
**                  if(cd_present && !cd_playing)
**                  {
**                      ax = cd_track; cd_track++;
**                      CDPlay(ax);
**                      return;                 // the AdLib song is never loaded
**                  }
**                  ... otherwise index the 36-entry song schedule at 4557:0bd0
**
**   19f8:2769  "play song N", whose whole body is wrapped in
**              `if(cd_present == 0)`. With a disc in the drive the title, menu,
**              intermission and high-score songs simply do not play.
**
**   2ae4:1979  CDPlay(n), which looks n up in a five-entry table of
**              (start address, length) pairs at 4557:24e2 and hands the pair to
**              MSCDEX. Entry 0 is zeroed; the four real entries are, decoded as
**              Redbook minute:second:frame and frame counts:
**
**                  1   03:47:54  47706 frames  636.08 s
**                  2   14:23:60  26518 frames  353.57 s
**                  3   20:23:28  13755 frames  183.40 s
**                  4   23:32:58  28624 frames  381.65 s
**
**              Matched against the disc's table of contents those are physical
**              audio tracks 3, 5, 7 and 9 -- the four pieces of music. The
**              even-numbered tracks between them are six to eight seconds long
**              and are lead-ins; the durations above agree with the ripped
**              tracks to the frame, except entry 2, whose start address is the
**              beginning of the six-second track 4 rather than of track 5. That
**              six seconds is inaudible (peak -30 dBFS) and is not reproduced
**              here.
**
** So the disc's soundtrack is not a per-floor assignment at all: it is a
** four-song playlist that advances by one whenever a floor begins and the
** previous song has already run out. A ten-minute track therefore plays across
** several floors, and when it ends the floor stays quiet until the next one
** starts. That is reproduced exactly.
**
** The one deliberate difference: the original's counter increments without
** limit, so a long enough game walks off the end of that five-entry table and
** reads whatever follows it on the stack. This wraps back to the first song
** instead, which is what the disc's own "advance track" debug key does
** (2ae4:1931 resets the counter when it passes 4).
*/

#include "wl_def.h"
#include "c7_cdaudio.h"
#include "filesys.h"
#include "id_sd.h"
#include "wl_iwad.h"
#include "c_cvars.h"
#include "zstring.h"

namespace
{
	// Physical CD track numbers, in the order the disc plays them.
	const int TrackNumbers[] = { 3, 5, 7, 9 };
	const unsigned NumTracks = countof(TrackNumbers);

	FString TrackPaths[NumTracks];  // empty where the file is missing
	unsigned NextTrack = 0;
	unsigned Found = 0;
	bool Initialized = false;

	void FindTracks()
	{
		// Beside the player's own game files, never inside the pk3: this is
		// commercial audio ripped from a disc they own.
		const FString dirName = IWad::GetGameDataDirectory() + "cdaudio";
		File dir(dirName);
		if(!dir.exists() || !dir.isDirectory())
		{
			Printf("CD audio: no %s directory; using the AdLib soundtrack.\n",
				dirName.GetChars());
			return;
		}

		for(unsigned i = 0; i < NumTracks; ++i)
		{
			FString name;
			name.Format("track%02d.ogg", TrackNumbers[i]);

			// getInsensitiveFile is a no-op on case-insensitive filesystems and
			// matches the directory listing on the rest, so TRACK03.OGG works
			// as well as track03.ogg.
			File track(dir, dir.getInsensitiveFile(name, false));
			if(!track.exists() || !track.isFile())
				continue;

			TrackPaths[i] = track.getPath();
			++Found;
		}

		if(Found == 0)
		{
			Printf("CD audio: %s holds none of track03/05/07/09.ogg; "
				"using the AdLib soundtrack.\n", dirName.GetChars());
			return;
		}

		Printf("CD audio: %u of %u soundtrack files found in %s.\n",
			Found, NumTracks, dirName.GetChars());
	}

	void EnsureInitialized()
	{
		if(Initialized)
			return;
		Initialized = true;

		if(!IWad::CheckGameFilter("Corridor7"))
			return;

		FindTracks();
	}
}

namespace C7CD
{

void Init()
{
	EnsureInitialized();
}

bool Present()
{
	EnsureInitialized();
	return Found != 0;
}

bool Available()
{
	// snd_cdmusic is the player's choice in the Audio menu; MusicMode is the
	// master music switch. Either one turning this off has to hand the floor's
	// music back to the AdLib path rather than leaving it silent, which is why
	// every caller asks this rather than Present().
	return Present() && snd_cdmusic && MusicMode != smm_Off;
}

void Stop()
{
	if(!Present())
		return;
	SD_MusicOff();
}

void StartLevelTrack()
{
	if(!Available())
		return;

	// The disc's rule: a song that is still running is left alone, and the
	// playlist only moves on once one has finished. This is what makes the
	// soundtrack span floors instead of restarting at every elevator.
	if(SD_MusicFilePlaying())
		return;

	for(unsigned i = 0; i < NumTracks; ++i)
	{
		const unsigned index = (NextTrack + i) % NumTracks;
		if(TrackPaths[index].IsEmpty())
			continue;

		NextTrack = (index + 1) % NumTracks;
		SD_StartMusicFile(TrackPaths[index]);
		Printf("CD audio: playing track %02d.\n", TrackNumbers[index]);
		return;
	}
}

}
