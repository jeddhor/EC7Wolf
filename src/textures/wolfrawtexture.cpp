/*
** wolfrawtexture.cpp
** Wolfenstein "raw" support.
** So I copy/pasted the shape support and changed things up...
**
**---------------------------------------------------------------------------
** Copyright 2011 Braden Obrzut
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
#include "m_swap.h"
#include "templates.h"
#include "v_palette.h"
#include "textures.h"

//==========================================================================
//
// A texture that is a Wolfenstein "raw"
//
//==========================================================================

class FWolfRawTexture : public FTexture
{
public:
	FWolfRawTexture (int lumpnum, FileReader &file);
	~FWolfRawTexture ();

	const BYTE *GetColumn (unsigned int column, const Span **spans_out);
	const BYTE *GetPixels ();
	void Unload ();

protected:
	BYTE *Pixels;
	Span **Spans;
	bool Mac;

	virtual void MakeTexture ();
};

//==========================================================================
//
// Checks if the lump is a Wolfenstein "raw"
//
//==========================================================================

static bool CheckIfWolfRaw(FileReader &file)
{
	if(file.GetLength() < 5) return false;
	
	WORD header[2];
	file.Seek(0, SEEK_SET);
	file.Read(header, 4);

	WORD Width = LittleShort(header[0]);
	WORD Height = LittleShort(header[1]);
	if(file.GetLength() == Width*Height+4) // Raw page
		return true;

	Width = BigShort(header[0]);
	Height = BigShort(header[1]);
	if(file.GetLength() == Width*Height+4) // Mac raw
		return true;
	return false;
}

//==========================================================================
//
//
//
//==========================================================================

FTexture *WolfRawTexture_TryCreate(FileReader &file, int lumpnum)
{
	if(!CheckIfWolfRaw(file))
		return NULL;
	return new FWolfRawTexture(lumpnum, file);
}

//==========================================================================
//
//
//
//==========================================================================

FWolfRawTexture::FWolfRawTexture(int lumpnum, FileReader &file)
: FTexture(NULL, lumpnum), Pixels(0), Spans(0)
{
	WORD header[2];
	file.Seek(0, SEEK_SET);
	file.Read(header, 4);
	Width = LittleShort(header[0]);
	Height = LittleShort(header[1]);
	if(file.GetLength() != Width*Height+4)
	{
		Mac = true;
		Width = BigShort(header[0]);
		Height = BigShort(header[1]);
	}
	else
		Mac = false;
	LeftOffset = 0;
	TopOffset = 0;
	CalcBitSize ();
}

//==========================================================================
//
//
//
//==========================================================================

FWolfRawTexture::~FWolfRawTexture ()
{
	Unload ();
	if (Spans != NULL)
	{
		FreeSpans (Spans);
		Spans = NULL;
	}
}

//==========================================================================
//
//
//
//==========================================================================

void FWolfRawTexture::Unload ()
{
	if(Pixels != NULL)
	{
		delete[] Pixels;
		Pixels = NULL;
	}
}

//==========================================================================
//
//
//
//==========================================================================

const BYTE *FWolfRawTexture::GetPixels ()
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

const BYTE *FWolfRawTexture::GetColumn (unsigned int column, const Span **spans_out)
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
		if (Spans == NULL)
		{
			Spans = CreateSpans(Pixels);
		}
		*spans_out = Spans[column];
	}
	return Pixels + column*Height;
}


//==========================================================================
//
//
//
//==========================================================================

void FWolfRawTexture::MakeTexture ()
{
	FMemLump lump = Wads.ReadLump (SourceLump);
	const BYTE* data = ((const BYTE*)lump.GetMem())+4;
	const bool corridor7LoadingPlate = Wads.CheckLumpName(SourceLump, "C7G0073");
	// C7G0073 is authored against the menu/loading DAC layout, while the rest
	// of play uses C7PAL. This index translation was recovered by matching the
	// released DOS plate pixel-for-pixel and keeps the asset palette-native.
	static const BYTE corridor7LoadingRemap[256] =
	{
		  0,   1,   2,   3,   4,   5,   6,   7,   8,   9,  10,  11,  12,  13,  14,  15,
		 16,  17,  18,  19,  20,  21,  22,  23,  24,  25,  26,  27,  28,  29,  30,  31,
		 32,  33,  34,  35,  36,  37,  38,  39,  40,  41,  42,  43,  44,  45,  46,  47,
		 34,   7,  31,  31,  31,  32,  32,  30,   7,  33,  33,  33, 157,  28,  29,  29,
		 31,  31, 155,  25,  32,  33,  30,  32,  30, 154,  31,  31,  33, 157, 152, 157,
		 32,  33,  82,  32, 144, 144, 147,  30,  19,  27,  31,  32, 139, 139, 155,  23,
		 29,  27,  32,  27,  28,  31,  24,  31,  32,  30,  30,  33,  33,  34,  18, 140,
		 29,  32,  31,  32, 144, 147,  30, 139, 152, 146,  30, 154, 154, 138, 140, 141,
		142, 142, 156, 144,  32,   8, 139, 146, 139, 143, 154, 152, 152, 154, 142, 154,
		144, 145,  20,  30,  31,  32,  30,  28,  30, 138, 153, 138, 140, 154, 154, 143,
		144, 150,  21,  30,  26,   8,  29,  30,  31,  32, 140, 140, 172, 153, 142, 152,
		 30, 139, 152, 141, 142, 152, 154,  29,  29,  33, 138, 141, 142, 140, 152, 143,
		144,  31,  26,  32, 148, 197, 146, 143, 145, 143, 150, 141,  30, 148, 140, 143,
		144, 143, 143, 145, 141, 150, 144,   8, 141, 141, 142,  65, 142, 138,  16, 140,
		189,  19,  20,  28, 190, 193, 192, 190, 198,  24, 188, 196, 200, 189, 187, 189,
		188, 192, 197,  27, 188, 192, 193,  19,  22,  23,  24,  26,  34,  28,  29, 255
	};

	Pixels = new BYTE[Width*Height];
	memset(Pixels, 0, Width*Height);

	if(Mac)
	{
		for(unsigned int y = 0;y < Height;++y)
		{
			BYTE *dest = Pixels+y;
			for(unsigned int x = 0;x < Width;++x)
			{
				const BYTE source = *data++;
				*dest = GPalette.Remap[corridor7LoadingPlate ?
					corridor7LoadingRemap[source] : source];
				dest += Height;
			}
		}
	}
	else
	{
		for(unsigned int x = 0;x < Width;++x)
		{
			for(unsigned int y = 0;y < Height;++y)
			{
				const BYTE source = data[y*(Width>>2)+(x>>2) + (x&3)*(Width>>2)*Height];
				Pixels[x*Height+y] = GPalette.Remap[corridor7LoadingPlate ?
					corridor7LoadingRemap[source] : source];
			}
		}
	}
}
