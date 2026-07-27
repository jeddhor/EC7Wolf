/*
** c7_cdaudio.h
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

#ifndef __C7_CDAUDIO_H__
#define __C7_CDAUDIO_H__

namespace C7CD
{
	// Looks for the ripped soundtrack next to the player's game data. Safe to
	// call for any game; it does nothing unless this is Corridor 7.
	void Init();

	// True when a usable soundtrack was found on disk. Fixed for the run; this
	// is what decides whether the Audio menu offers CD Audio at all.
	bool Present();

	// True when the CD soundtrack is the music device in use. While it is, the
	// AdLib songs are not played at all, which is exactly what the CD release
	// does -- its song-start routine returns immediately when a disc is in the
	// drive. Unlike the disc, this can be turned off without removing the
	// files: it also requires snd_cdmusic and a music device that is not Off.
	bool Available();

	// Called where the AdLib path would start a floor's song.
	void StartLevelTrack();

	// Silence the streamed track. Used when switching the music device away
	// from CD audio, where otherwise a ten-minute track would keep playing
	// underneath the AdLib song that just started.
	void Stop();
}

#endif
