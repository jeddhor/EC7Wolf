/*
** c7_upscale.h
**
** Optional neural-network upscales of the Corridor 7 art.
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
**
** tools/make_c7_upscaled_pk3.py runs the player's own GFXTILES and VGAGRAPH
** through Real-ESRGAN and writes c7_assets_upscaled.pk3 -- every wall, sprite
** and picture at four times its authored size, in the pk3's hires/ namespace.
** Everything in it derives from the commercial release, so it is never
** distributed and never lives in the source tree: it sits beside the player's
** own data files, and this looks for it there.
**
** The pack is a replacement layer rather than a replacement: the original art
** is still loaded, still needed, and still what the game falls back to. Both
** copies stay in memory so the player can switch between them from the menu
** without restarting, which is also the only way to compare them honestly.
*/

#ifndef __C7_UPSCALE_H__
#define __C7_UPSCALE_H__

#include "zstring.h"

class FTexture;
class FTextureID;

namespace C7Upscale
{
	// The upscaled asset pack, if one is installed. Looks beside the player's
	// game data first and beside the executable second -- they are usually the
	// same directory, and the build script writes the pack into the former.
	// Returns an empty string when there is none. Called while the wad list is
	// still being assembled, so the pack's lumps exist by the time Init() runs.
	FString FindPack(const FString &gameDataDir, const FString &progDir);

	// Reads the pack's manifest and checks that every lump it promises really
	// arrived, then reports what it found. Must run after the wads are open and
	// before the texture manager starts, since that is what consumes the pack.
	void Init();

	// A pack file was found on disk. True even when it turned out to be broken,
	// which is the difference that lets the menu say "invalid" rather than
	// silently offering nothing.
	bool Present();

	// The pack passed its manifest check and can be switched on.
	bool Valid();

	// True for the wad the pack was loaded as, valid or not. A rejected pack's
	// hires lumps are skipped rather than partly applied.
	bool IsPackWad(int wadnum);

	// True while the pack owns this wad, which is how the texture manager knows
	// to keep the original texture alive instead of freeing it. Any other hires
	// wad the player loads keeps the stock ZDoom behaviour of replacing outright.
	bool OwnsWad(int wadnum);

	// Records one texture the pack replaced, so it can be put back.
	void NoteSwap(FTextureID id, FTexture *original, FTexture *upscaled);

	// Puts the textures into the state the config asks for. Called once after
	// the texture manager has finished, since the replacements are applied as a
	// side effect of loading and may need undoing.
	void ApplyPreference();

	// Whether the upscaled art is the art currently in use. SetEnabled() swaps
	// every recorded texture and drops the caches that were built from them, so
	// it takes effect on the next frame.
	bool Enabled();
	void SetEnabled(bool enabled);
}

#endif
