/*
** flattexture.cpp
** Texture class for standard Doom flats
**
**---------------------------------------------------------------------------
** Copyright 2004-2006 Randy Heit
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
**---------------------------------------------------------------------------
**
**
*/

#include "wl_def.h"
#include "files.h"
#include "w_wad.h"
#include "v_palette.h"
#include "textures.h"
#include "wl_iwad.h"

//==========================================================================
//
// A texture defined between F_START and F_END markers
//
//==========================================================================

class FFlatTexture : public FTexture
{
public:
	FFlatTexture (int lumpnum);
	~FFlatTexture ();

	const BYTE *GetColumn (unsigned int column, const Span **spans_out);
	const BYTE *GetMaskedColumn (unsigned int column);
	const BYTE *GetColumnOpacity (unsigned int column);
	const BYTE *GetPixels ();
	void Unload ();

protected:
	BYTE *Pixels;
	BYTE *MaskedPixels;
	BYTE *Opacity;
	Span DummySpans[2];


	void MakeTexture ();

	friend class FTexture;
};



//==========================================================================
//
// Since there is no way to detect the validity of a flat
// they can't be used anywhere else but between F_START and F_END
//
//==========================================================================

FTexture *FlatTexture_TryCreate(FileReader & file, int lumpnum)
{
	return new FFlatTexture(lumpnum);
}

//==========================================================================
//
//
//
//==========================================================================

FFlatTexture::FFlatTexture (int lumpnum)
: FTexture(NULL, lumpnum), Pixels(0), MaskedPixels(0), Opacity(0)
{
	// Size the texture from the lump length recorded in the resource
	// directory. Corridor 7 GFXTILES wall pages are square raw bitmaps with
	// no embedded width/height header; every released page is 4096 bytes
	// (64x64), so the VSWAP length is the authoritative stride source.
	const int area = Wads.LumpLength (lumpnum);
	int bits = 6;
	for(int candidate = 3;candidate <= 8;++candidate)
	{
		if((1 << candidate)*(1 << candidate) == area)
		{
			bits = candidate;
			break;
		}
	}

	bMasked = false;
	WidthBits = HeightBits = bits;
	Width = Height = 1 << bits;
	WidthMask = (1 << bits) - 1;
	DummySpans[0].TopOffset = 0;
	DummySpans[0].Length = Height;
	DummySpans[1].TopOffset = 0;
	DummySpans[1].Length = 0;

	if(Wads.GetLumpFlags(lumpnum) & LUMPF_DOUBLERESFLAT)
		yScale = xScale = 2*FRACUNIT;
}

//==========================================================================
//
//
//
//==========================================================================

FFlatTexture::~FFlatTexture ()
{
	Unload ();
}

//==========================================================================
//
//
//
//==========================================================================

void FFlatTexture::Unload ()
{
	if (Pixels != NULL)
	{
		delete[] Pixels;
		Pixels = NULL;
	}
	if (Opacity != NULL)
	{
		delete[] Opacity;
		Opacity = NULL;
	}
	if (MaskedPixels != NULL)
	{
		delete[] MaskedPixels;
		MaskedPixels = NULL;
	}
}

//==========================================================================
//
//
//
//==========================================================================

const BYTE *FFlatTexture::GetColumn (unsigned int column, const Span **spans_out)
{
	if (Pixels == NULL)
	{
		MakeTexture ();
	}
	if ((unsigned)column >= (unsigned)Width)
	{
		if (WidthMask + 1 == Width)
		{
			column &= WidthMask;
		}
		else
		{
			column %= Width;
		}
	}
	if (spans_out != NULL)
	{
		*spans_out = DummySpans;
	}
	return Pixels + column*Height;
}

//==========================================================================
//
//
//
//==========================================================================

const BYTE *FFlatTexture::GetColumnOpacity (unsigned int column)
{
	if (Pixels == NULL)
		MakeTexture ();
	if (Opacity == NULL)
		return NULL;
	if ((unsigned)column >= (unsigned)Width)
	{
		if (WidthMask + 1 == Width)
			column &= WidthMask;
		else
			column %= Width;
	}
	return Opacity + column*Height;
}

//==========================================================================
//
//
//
//==========================================================================

const BYTE *FFlatTexture::GetMaskedColumn (unsigned int column)
{
	if (Pixels == NULL)
		MakeTexture ();
	if (MaskedPixels == NULL)
		return GetColumn(column, NULL);
	if ((unsigned)column >= (unsigned)Width)
	{
		if (WidthMask + 1 == Width)
			column &= WidthMask;
		else
			column %= Width;
	}
	return MaskedPixels + column*Height;
}

//==========================================================================
//
//
//
//==========================================================================

const BYTE *FFlatTexture::GetPixels ()
{
	if (Pixels == NULL)
	{
		MakeTexture ();
	}
	return Pixels;
}

//==========================================================================
//
//
//
//==========================================================================

void FFlatTexture::MakeTexture ()
{
	FWadLump lump = Wads.OpenLumpNum (SourceLump);
	Pixels = new BYTE[Width*Height];
	long numread = lump.Read (Pixels, Width*Height);
	if (numread < Width*Height)
	{
		memset (Pixels + numread, 0xBB, Width*Height - numread);
	}
	if(IWad::CheckGameFilter("Corridor7"))
	{
		// Corridor 7 uses source index 255 as the DOS transparent key. ECWolf's
		// masked/compositor paths treat index 0 as transparent, so remap 255 to
		// 0 before palette injection. Opaque art may still use index 0 as black,
		// so keep a separate opacity plane and leave the opaque Pixels buffer on
		// the original indices (255 remains the magenta palette entry there).
		for(int i = 0;i < Width*Height;++i)
		{
			if(Pixels[i] == 255)
			{
				bMasked = true;
				break;
			}
		}
		if(bMasked)
		{
			Opacity = new BYTE[Width*Height];
			MaskedPixels = new BYTE[Width*Height];
			for(int i = 0;i < Width*Height;++i)
			{
				const BYTE source = Pixels[i];
				Opacity[i] = source == 255 ? 0 : 1;
				MaskedPixels[i] = source == 255 ? 0 : source;
			}
		}
	}
	if(!(Wads.GetLumpFlags(SourceLump) & LUMPF_DONTFLIPFLAT))
	{
		FlipSquareBlockRemap (Pixels, Width, Height, GPalette.Remap);
		if(MaskedPixels)
			FlipSquareBlockRemap (MaskedPixels, Width, Height, GPalette.Remap);
		if(Opacity)
		{
			BYTE identity[256];
			for(unsigned int i = 0;i < 256;++i)
				identity[i] = i;
			FlipSquareBlockRemap (Opacity, Width, Height, identity);
		}
	}
	else
	{
		for(int i = 0;i < Width*Height;i++)
		{
			Pixels[i] = GPalette.Remap[Pixels[i]];
			if(MaskedPixels)
				MaskedPixels[i] = GPalette.Remap[MaskedPixels[i]];
		}
	}
}

