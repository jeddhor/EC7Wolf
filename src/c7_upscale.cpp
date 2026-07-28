/*
** c7_upscale.cpp
**
** Optional neural-network upscales of the Corridor 7 art. See c7_upscale.h.
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

#include "c7_upscale.h"

#include "c_cvars.h"
#include "filesys.h"
#include "m_classes.h"
#include "tarray.h"
#include "textures/textures.h"
#include "w_wad.h"
#include "wl_def.h"
#include "wl_iwad.h"
#include "zstring.h"

#include "render/opengl/r_glworld.h"

namespace
{
	const char *const kPackName = "c7_assets_upscaled.pk3";
	const char *const kInfoLump = "c7upscal.txt";
	const char *const kListLump = "c7upscal.lst";

	// One texture the pack took over. Both copies stay allocated for the run:
	// the pack is a switchable layer, and the game still needs the original art
	// underneath it. Two copies of the wall and sprite pages is a few tens of
	// megabytes, which is the price of switching without a restart.
	struct Swap
	{
		FTextureID	id;
		FTexture	*original;
		FTexture	*upscaled;
	};

	FString		gPackPath;
	int			gWadnum = -1;
	bool		gValid = false;
	FString		gProblem;
	unsigned int gExpected = 0;
	TArray<Swap> gSwaps;

	// Whether the upscaled copies are the ones currently installed in the
	// texture manager. Starts true because the replacements are applied as the
	// texture manager loads the pack; ApplyPreference() undoes them if the
	// player has the option switched off.
	bool		gApplied = true;

	// Set by --no-upscale before the wad list is built.
	bool		gDisabled = false;

	// Splits a manifest lump into non-empty, non-comment lines.
	void ReadLines(int lump, TArray<FString> &out)
	{
		FString text = Wads.ReadLump(lump).GetString();
		// A lump read into an FString carries its NUL terminator as a character,
		// so the text is one longer than it looks and ends in a line that is not
		// empty but has nothing in it.
		text.Truncate((long)strlen(text.GetChars()));
		text.Substitute("\r", "");
		long start = 0;
		while(start <= (long)text.Len())
		{
			long end = text.IndexOf('\n', start);
			if(end < 0)
				end = (long)text.Len();
			FString line = text.Mid(start, end-start);
			// Not on an empty string: FString::StripLeftRight() walks backwards
			// from Len()-1, which for a blank line is (size_t)-1.
			if(!line.IsEmpty())
				line.StripLeftRight();
			if(!line.IsEmpty() && line.Compare("//", 2) != 0)
				out.Push(line);
			start = end+1;
		}
	}

	// The integer following `key ` on the first line that starts with it, or -1.
	int ManifestValue(const TArray<FString> &lines, const char *key)
	{
		const size_t keylen = strlen(key);
		for(unsigned int i = 0;i < lines.Size();++i)
		{
			if(lines[i].Len() > keylen && lines[i][keylen] == ' ' &&
				lines[i].Compare(key, (int)keylen) == 0)
				return atoi(lines[i].Mid((long)keylen+1).GetChars());
		}
		return -1;
	}
}

namespace C7Upscale
{

void Disable()
{
	gDisabled = true;
}

FString FindPack(const FString &gameDataDir, const FString &progDir)
{
	if(gDisabled || !IWad::CheckGameFilter("Corridor7"))
		return FString();

	// Beside the game data first: that is where the build script writes it, and
	// where a player with several games installed would keep a pack that only
	// makes sense for one of them.
	FString candidate = gameDataDir + kPackName;
	if(File(candidate).exists())
	{
		gPackPath = candidate;
		return candidate;
	}

	candidate = progDir + FString(PATH_SEPARATOR) + kPackName;
	if(File(candidate).exists())
	{
		gPackPath = candidate;
		return candidate;
	}

	return FString();
}

void Init()
{
	if(gPackPath.IsEmpty())
		return;

	// Find the pack among the open wads by name rather than by path: the path
	// has been through separator normalisation since FindPack() handed it over.
	for(int i = Wads.GetNumWads()-1;i >= 0;--i)
	{
		FString name = Wads.GetWadFullName(i);
		const long slash = name.LastIndexOfAny("/\\");
		if(slash >= 0)
			name = name.Mid(slash+1);
		if(name.CompareNoCase(kPackName) == 0)
		{
			gWadnum = i;
			break;
		}
	}
	if(gWadnum < 0)
	{
		gProblem = "the pack could not be opened";
		Printf("Upscale: %s was found but %s.\n", kPackName, gProblem.GetChars());
		return;
	}

	const int infoLump = Wads.CheckNumForFullName(kInfoLump, gWadnum);
	const int listLump = Wads.CheckNumForFullName(kListLump, gWadnum);
	if(infoLump < 0 || listLump < 0)
	{
		// Either someone else's hires pk3 under our name, or a pack built by a
		// script older than the manifest. Both want the same answer from the
		// player, so say what to do about it rather than what is missing.
		gProblem = "it has no manifest; rebuild it with make_c7_upscaled_pk3.py";
		Printf("Upscale: %s cannot be used -- %s.\n", kPackName, gProblem.GetChars());
		return;
	}

	TArray<FString> info, wanted;
	ReadLines(infoLump, info);
	ReadLines(listLump, wanted);

	const int declared = ManifestValue(info, "lumps");
	if(declared < 0 || (unsigned int)declared != wanted.Size())
	{
		gProblem.Format("its manifest is inconsistent (%d declared, %u listed)",
			declared, wanted.Size());
		Printf("Upscale: %s cannot be used -- %s.\n", kPackName, gProblem.GetChars());
		return;
	}

	// All or nothing. A pack whose build was interrupted, or whose upscaler
	// dropped images partway through, still produces a loadable pk3 -- it is
	// just missing lumps, and the result would be a level where some walls are
	// sharp and their neighbours are not. Checking every promised name against
	// what actually arrived is the only way to catch that before it is on screen.
	TArray<FString> missing;
	for(unsigned int i = 0;i < wanted.Size();++i)
	{
		const int lump = Wads.CheckNumForName(wanted[i], ns_hires, gWadnum, true);
		if(lump < 0)
		{
			if(missing.Size() < 8)
				missing.Push(wanted[i]);
			else
				missing[7] = "...";
		}
	}
	if(missing.Size() > 0)
	{
		FString names;
		for(unsigned int i = 0;i < missing.Size();++i)
			names += (i ? ", " : "") + missing[i];
		gProblem.Format("%u of its %u images are missing", missing.Size(),
			wanted.Size());
		Printf("Upscale: %s is incomplete -- %s (%s).\n", kPackName,
			gProblem.GetChars(), names.GetChars());
		Printf("Upscale: rebuild it with make_c7_upscaled_pk3.py; the stock art will be used.\n");
		return;
	}

	gValid = true;
	gExpected = wanted.Size();
	Printf("Upscale: %s carries %u images", kPackName, wanted.Size());
	const int scale = ManifestValue(info, "scale");
	if(scale > 1)
		Printf(" at %dx", scale);
	Printf(".\n");
}

bool Present() { return !gPackPath.IsEmpty(); }
bool Valid() { return gValid; }
bool Enabled() { return gValid && gApplied; }

int WantedFilter(int current)
{
	if(Enabled() && current <= 0)
		return 2;	// Smooth: samples the pixel's footprint in texture space
	return current;
}

bool IsPackWad(int wadnum)
{
	return gWadnum >= 0 && wadnum == gWadnum;
}

bool OwnsWad(int wadnum)
{
	return gValid && wadnum == gWadnum;
}

void NoteSwap(FTextureID id, FTexture *original, FTexture *upscaled)
{
	Swap swap = { id, original, upscaled };
	gSwaps.Push(swap);
}

void SetEnabled(bool enabled)
{
	if(!gValid)
		enabled = false;
	if(enabled == gApplied)
		return;

	for(unsigned int i = 0;i < gSwaps.Size();++i)
	{
		// free=false, so this is a swap rather than a replacement: the texture
		// being displaced keeps its pixels and gets its id back on the way in.
		TexMan.ReplaceTexture(gSwaps[i].id,
			enabled ? gSwaps[i].upscaled : gSwaps[i].original, false);
	}
	gApplied = enabled;
	vid_upscaled_assets = enabled;

	// Everything downstream that holds pixels rather than texture ids is now
	// looking at art that is no longer installed.
	R_GLLiveInvalidateTextures();
	Menu::forgetCachedArt();

	if(gSwaps.Size() > 0)
		Printf("Upscale: %s art for %u textures.\n",
			enabled ? "upscaled" : "original", gSwaps.Size());
}

void ApplyPreference()
{
	if(!gValid)
	{
		// The pack was rejected, so nothing was ever swapped in. Keep the config
		// value the player chose: they may fix the pack and restart.
		gApplied = false;
		return;
	}
	// gApplied is true here: the texture manager applied the pack as it loaded.
	SetEnabled(vid_upscaled_assets);

	// The menu couples these when the player switches the pack on; a config that
	// already had it on has never been through that, so apply the same rule here
	// rather than starting the game in the combination the menu will not let them
	// select.
	const int filter = WantedFilter(vid_glfilter);
	if(filter != vid_glfilter)
	{
		vid_glfilter = filter;
		Printf("Upscale: texture filtering raised to Smooth; nearest sampling of a "
			"four-times pack is what makes it crawl.\n");
	}
	Printf("Upscale: %u of the game's textures have an upscaled copy; using the %s art.\n",
		gSwaps.Size(), gApplied ? "upscaled" : "original");

	// Every name in the manifest was checked for at startup, so a shortfall here
	// means a lump that is present but replaces nothing -- a name the game does
	// not use. Harmless, but it means the pack was built against different data.
	if(gExpected > gSwaps.Size())
		Printf("Upscale: %u of its images do not match anything the game draws.\n",
			gExpected - gSwaps.Size());
}

}
