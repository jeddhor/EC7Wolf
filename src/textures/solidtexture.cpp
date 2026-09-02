/*
** solidtexture.cpp
** Creates a texture that consist of a solid color.
**
**---------------------------------------------------------------------------
** Copyright 2012 Braden Obrzut
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
#include "v_palette.h"
#include "v_video.h"
#include "textures.h"

//==========================================================================
//
// Solid color 64x64 texture
//
//==========================================================================

class FSolidTexture : public FTexture
{
public:
	FSolidTexture(DWORD color, int paletteIndex = -1);
	~FSolidTexture();

	const BYTE *GetColumn(unsigned int column, const Span **spans_out);
	const BYTE *GetPixels();
	void Unload();

protected:
	BYTE* Pixels;
	Span **Spans;
	const DWORD color;
	// >= 0 pins the texel to an exact palette entry instead of color matching.
	const int paletteIndex;

	virtual void MakeTexture();
};

//==========================================================================
//
// SolidTexture_TryCreate
// Convert a 6 character string of hex characters into a solid color texture
//
//==========================================================================

FTexture *SolidTexture_TryCreate(const char* color)
{
	DWORD texColor = 0;
	int i = 5;
	do
	{
		int digit;
		char cdigit = *color++;
		// Switch to uppercase for valid range
		if(cdigit >= 'a' && cdigit <= 'f')
			cdigit += 'A'-'a';
		// Check range and convert to integer
		if(cdigit >= '0' && cdigit <= '9')
			digit = cdigit - '0';
		else if(cdigit >= 'A' && cdigit <= 'F')
			digit = cdigit - 'A' + 0xA;
		else
			return NULL;

		texColor |= digit<<(4*i);
		--i;
	}
	while(*color != '\0');

	return new FSolidTexture(texColor);
}

//==========================================================================
//
// SolidTexture_CreateIndexed
//
// Solid texture pinned to an exact palette entry. Color matching cannot
// express this: a palette may hold the same RGB at several indices, and which
// one you get matters when something walks the palette by index rather than
// reading the color. Corridor 7's plane shading does exactly that -- it steps
// one index darker per band and stops at the bottom of the color's own
// 16-aligned ramp -- and its palette repeats (170,0,0) at 4, 76 and 244, so an
// "#AA0000" flat resolved to 4 and faded out through the grays instead of the
// reds.
//
//==========================================================================

FTexture *SolidTexture_CreateIndexed(int paletteIndex)
{
	const PalEntry &pe = GPalette.BaseColors[paletteIndex & 0xFF];
	return new FSolidTexture(MAKERGB(pe.r, pe.g, pe.b), paletteIndex & 0xFF);
}

//==========================================================================
//
//
//
//==========================================================================

FSolidTexture::FSolidTexture(DWORD color, int paletteIndex) : FTexture(NULL, -1),
	Pixels(NULL), Spans(NULL), color(color), paletteIndex(paletteIndex)
{
	Width = 64;
	Height = 64;
	LeftOffset = 0;
	TopOffset = 0;
	CalcBitSize();
}

//==========================================================================
//
//
//
//==========================================================================

FSolidTexture::~FSolidTexture ()
{
	Unload();
	if(Spans)
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

void FSolidTexture::Unload ()
{
	if(Pixels)
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

const BYTE *FSolidTexture::GetPixels()
{
	if(!Pixels)
		MakeTexture();
	return Pixels;
}

//==========================================================================
//
//
//
//==========================================================================

const BYTE *FSolidTexture::GetColumn(unsigned int column, const Span **spans_out)
{
	if (!Pixels)
		MakeTexture();

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

void FSolidTexture::MakeTexture()
{
	Pixels = new BYTE[Width*Height];

	memset(Pixels, paletteIndex >= 0
		? (BYTE)paletteIndex
		: RGB32k[RPART(color)>>3][GPART(color)>>3][BPART(color)>>3], Width*Height);
}
