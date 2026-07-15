/*
** file_gamemaps.cpp
**
**---------------------------------------------------------------------------
** Copyright 2011 Braden Obrzut
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

#include "filesys.h"
#include "doomerrors.h"
#include "wl_def.h"
#include "resourcefile.h"
#include "tmemory.h"
#include "w_wad.h"
#include "m_swap.h"
#include "zstring.h"
#include "wolfmapcommon.h"

struct FMapLump;

static bool ValidateTed5RLEW(FileReader *reader, DWORD offset, WORD length, DWORD expandedBytes)
{
	if(length < 2 || (length & 1) || expandedBytes > 0xFFFF || (expandedBytes & 1))
		return false;

	TUniquePtr<BYTE[]> input(new BYTE[length]);
	reader->Seek(offset, SEEK_SET);
	if(reader->Read(input.Get(), length) != length || ReadLittleShort(input.Get()) != expandedBytes)
		return false;

	DWORD in = 2;
	DWORD out = 0;
	while(out < expandedBytes)
	{
		if(in+2 > length)
			return false;
		const WORD value = ReadLittleShort(input.Get()+in);
		if(value == 0xABCD)
		{
			if(in+6 > length)
				return false;
			const DWORD runBytes = static_cast<DWORD>(ReadLittleShort(input.Get()+in+2))*2;
			if(runBytes > expandedBytes-out)
				return false;
			out += runBytes;
			in += 6;
		}
		else
		{
			out += 2;
			in += 2;
		}
	}
	return out == expandedBytes && in == length;
}

class FGamemaps : public FResourceFile
{
	public:
		FGamemaps(const char* filename, FileReader *file);
		~FGamemaps();

		FResourceLump *GetLump(int lump);
		bool Open(bool quiet);

	private:
		FMapLump* Lumps;

		TUniquePtr<FileReader> mapheadReader;
		// Gamemaps = Carmack+RLEW, Maptemp = RLEW
		bool carmacked;
		// Corridor 7's TED5 file stores map headers and planes together.
		bool containedTed5;
};

FGamemaps::FGamemaps(const char* filename, FileReader *file) : FResourceFile(filename, file), Lumps(NULL), mapheadReader(NULL), containedTed5(false)
{
	FString path(filename);
	int lastSlash = path.LastIndexOfAny("/\\:");
	int lastDot = path.LastIndexOf('.');
	FString extension = path.Mid(lastDot+1);

	carmacked = path.Mid(lastSlash+1, 7).CompareNoCase("maptemp") != 0;
	if(!carmacked && Reader->GetLength() >= 12)
	{
		char signature[12];
		Reader->Seek(0, SEEK_SET);
		if(Reader->Read(signature, sizeof(signature)) == sizeof(signature) &&
			memcmp(signature, "TED5v1.0.\0\0\0", sizeof(signature)) == 0)
			containedTed5 = true;
	}

	path = path.Left(lastSlash+1);
	if(containedTed5)
		return;

	FString mapheadFile = FString("maphead.") + extension;
	if(Wads.CheckIfWadLoaded(path.Left(lastSlash)) == -1)
	{
		File directory(path.Len() > 0 ? path : ".");
		mapheadFile = path + directory.getInsensitiveFile(mapheadFile, true);

		mapheadReader = new FileReader();
		if(!mapheadReader->Open(mapheadFile))
			mapheadReader.Reset();
	}
	else // Embedded vanilla data?
	{
		FLumpReader *lreader = reinterpret_cast<FLumpReader *>(file);

		for(DWORD i = 0; i < lreader->LumpOwner()->LumpCount(); ++i)
		{
			FResourceLump *lump = lreader->LumpOwner()->GetLump(i);
			if(lump->FullName.CompareNoCase(mapheadFile) == 0)
			{
				mapheadReader = lump->NewReader();
				break;
			}
		}
	}

	if(!mapheadReader)
	{
		FString error;
		error.Format("Could not open gamemaps since %s is missing.", mapheadFile.GetChars());
		throw CRecoverableError(error);
	}
}

FGamemaps::~FGamemaps()
{
	if(Lumps != NULL)
		delete[] Lumps;
}

FResourceLump *FGamemaps::GetLump(int lump)
{
	return &Lumps[lump];
}

bool FGamemaps::Open(bool quiet)
{
	if(containedTed5)
	{
		struct Ted5MapHeader
		{
			DWORD PlaneOffset[PLANES];
			WORD PlaneLength[PLANES];
			WORD Width;
			WORD Height;
			char Name[16];
		};
		static const unsigned int MAX_TED5_MAPS = 100;
		static const unsigned int MAX_MAP_DIMENSION = 181;
		Ted5MapHeader headers[MAX_TED5_MAPS];
		const long fileLength = Reader->GetLength();
		if(fileLength <= 0 || static_cast<unsigned long>(fileLength) > 0xFFFFFFFFUL)
			return false;
		long offset = 0;
		unsigned int mapCount = 0;

		while(offset < fileLength)
		{
			BYTE raw[42];
			unsigned int fields;
			if(fileLength-offset == 4)
			{
				Reader->Seek(offset, SEEK_SET);
				if(Reader->Read(raw, 4) == 4 && memcmp(raw, "!ID!", 4) == 0)
				{
					offset += 4;
					break;
				}
			}
			if(mapCount >= MAX_TED5_MAPS)
			{
				if(!quiet) Printf(" (TED5 archive exceeds %u maps)", MAX_TED5_MAPS);
				return false;
			}

			if(mapCount == 0)
			{
				BYTE first[46];
				Reader->Seek(0, SEEK_SET);
				if(Reader->Read(first, sizeof(first)) != sizeof(first))
					return false;
				headers[0].PlaneOffset[0] = sizeof(first);
				headers[0].PlaneOffset[1] = ReadLittleLong(&first[12]);
				headers[0].PlaneOffset[2] = ReadLittleLong(&first[16]);
				for(unsigned int plane = 0; plane < PLANES; ++plane)
					headers[0].PlaneLength[plane] = ReadLittleShort(&first[20+plane*2]);
				headers[0].Width = ReadLittleShort(&first[26]);
				headers[0].Height = ReadLittleShort(&first[28]);
				memcpy(headers[0].Name, &first[30], sizeof(headers[0].Name));
			}
			else
			{
				Reader->Seek(offset, SEEK_SET);
				if(fileLength-offset < static_cast<long>(sizeof(raw)) ||
					Reader->Read(raw, sizeof(raw)) != sizeof(raw) || memcmp(raw, "!ID!", 4) != 0)
				{
					if(!quiet) Printf(" (invalid TED5 map marker at 0x%lx)", offset);
					return false;
				}
				fields = 4;
				for(unsigned int plane = 0; plane < PLANES; ++plane)
				{
					headers[mapCount].PlaneOffset[plane] = ReadLittleLong(&raw[fields+plane*4]);
					headers[mapCount].PlaneLength[plane] = ReadLittleShort(&raw[fields+12+plane*2]);
				}
				headers[mapCount].Width = ReadLittleShort(&raw[fields+18]);
				headers[mapCount].Height = ReadLittleShort(&raw[fields+20]);
				memcpy(headers[mapCount].Name, &raw[fields+22], sizeof(headers[mapCount].Name));
			}

			Ted5MapHeader &header = headers[mapCount];
			const DWORD minimumPlaneOffset = static_cast<DWORD>(offset + (mapCount == 0 ? 46 : sizeof(raw)));
			if(header.Width == 0 || header.Height == 0 ||
				header.Width > MAX_MAP_DIMENSION || header.Height > MAX_MAP_DIMENSION)
			{
				if(!quiet) Printf(" (invalid TED5 map %u dimensions %ux%u)", mapCount+1, header.Width, header.Height);
				return false;
			}
			DWORD previousEnd = 0;
			const DWORD expandedBytes = static_cast<DWORD>(header.Width)*header.Height*2;
			for(unsigned int plane = 0; plane < PLANES; ++plane)
			{
				const DWORD start = header.PlaneOffset[plane];
				const DWORD end = start + header.PlaneLength[plane];
				if(end < start || end > static_cast<DWORD>(fileLength) ||
					(plane == 0 && start < minimumPlaneOffset) || (plane && start < previousEnd))
				{
					if(!quiet) Printf(" (invalid TED5 map %u plane %u range)", mapCount+1, plane);
					return false;
				}
				if(!ValidateTed5RLEW(Reader, start, header.PlaneLength[plane], expandedBytes))
				{
					if(!quiet) Printf(" (invalid TED5 map %u plane %u RLEW stream)", mapCount+1, plane);
					return false;
				}
				previousEnd = end;
			}
			offset = header.PlaneOffset[PLANES-1] + header.PlaneLength[PLANES-1];
			++mapCount;
		}
		if(offset != fileLength || mapCount == 0)
		{
			if(!quiet) Printf(" (trailing or missing TED5 data at 0x%lx)", offset);
			return false;
		}

		static const unsigned int NUM_MAP_LUMPS = 2;
		NumLumps = mapCount*NUM_MAP_LUMPS;
		Lumps = new FMapLump[NumLumps];
		for(unsigned int i = 0; i < mapCount; ++i)
		{
			FMapLump &markerLump = Lumps[i*NUM_MAP_LUMPS];
			char lumpname[14];
			mysnprintf(lumpname, 14, "MAP%02d", i+1);
			markerLump.Owner = this;
			markerLump.LumpNameSetup(lumpname);
			markerLump.Namespace = ns_global;
			markerLump.LumpSize = 0;

			FMapLump &dataLump = Lumps[i*NUM_MAP_LUMPS+1];
			dataLump.Owner = this;
			dataLump.LumpNameSetup("PLANES");
			dataLump.Namespace = ns_global;
			dataLump.rlewTag = 0xABCD;
			dataLump.carmackCompressed = false;
			for(unsigned int plane = 0; plane < PLANES; ++plane)
			{
				dataLump.Header.PlaneOffset[plane] = headers[i].PlaneOffset[plane];
				dataLump.Header.PlaneLength[plane] = headers[i].PlaneLength[plane];
			}
			dataLump.Header.Width = headers[i].Width;
			dataLump.Header.Height = headers[i].Height;
			memset(dataLump.Header.Name, 0, sizeof(dataLump.Header.Name));
			memcpy(dataLump.Header.Name, headers[i].Name, sizeof(headers[i].Name));
			dataLump.LumpSize += headers[i].Width*headers[i].Height*PLANES*2;
		}
		if(!quiet) Printf(", %d lumps (self-contained TED5)\n", NumLumps);
		return true;
	}

	WORD rlewTag;

	// Read the map head.
	// First two bytes is the tag for the run length encoding
	// Followed by offsets in the gamemaps file, we'll count until we
	// hit a 0 offset.
	unsigned int NumPossibleMaps = (mapheadReader->GetLength()-2)/4;
	mapheadReader->Seek(0, SEEK_SET);
	DWORD* offsets = new DWORD[NumPossibleMaps];
	mapheadReader->Read(&rlewTag, 2);
	rlewTag = LittleShort(rlewTag);
	mapheadReader->Read(offsets, NumPossibleMaps*4);
	for(NumLumps = 0;NumLumps < NumPossibleMaps;++NumLumps)
	{
		offsets[NumLumps] = LittleLong(offsets[NumLumps]);
		if(offsets[NumLumps] == 0 || offsets[NumLumps] == 0xFFFFFFFFu)
			break;
	}

	// We allocate 2 lumps per map so...
	static const unsigned int NUM_MAP_LUMPS = 2;
	NumLumps *= NUM_MAP_LUMPS;

	Lumps = new FMapLump[NumLumps];
	for(unsigned int i = 0;i < NumLumps/NUM_MAP_LUMPS;++i)
	{
		// Map marker
		FMapLump &markerLump = Lumps[i*NUM_MAP_LUMPS];
		// Hey we don't need to use a temporary name here!
		// First map is MAP01 and so forth.
		char lumpname[14];
		mysnprintf(lumpname, 14, "MAP%02d", i+1);
		markerLump.Owner = this;
		markerLump.LumpNameSetup(lumpname);
		markerLump.Namespace = ns_global;
		markerLump.LumpSize = 0;

		// Make the data lump
		FMapLump &dataLump = Lumps[i*NUM_MAP_LUMPS+1];
		dataLump.rlewTag = rlewTag;
		dataLump.carmackCompressed = carmacked;
		BYTE header[PLANES*6+20];
		Reader->Seek(offsets[i], SEEK_SET);
		Reader->Read(&header, PLANES*6+20);

		dataLump.Owner = this;
		dataLump.LumpNameSetup("PLANES");
		dataLump.Namespace = ns_global;
		for(unsigned int j = 0;j < PLANES;j++)
		{
			dataLump.Header.PlaneOffset[j] = ReadLittleLong(&header[4*j]);
			dataLump.Header.PlaneLength[j] = ReadLittleShort(&header[PLANES*4+2*j]);
		}
		dataLump.Header.Width = ReadLittleShort(&header[PLANES*6]);
		dataLump.Header.Height = ReadLittleShort(&header[PLANES*6+2]);
		memcpy(dataLump.Header.Name, &header[PLANES*6+4], 16);
		dataLump.LumpSize += dataLump.Header.Width*dataLump.Header.Height*PLANES*2;
	}
	delete[] offsets;
	if(!quiet) Printf(", %d lumps\n", NumLumps);
	return true;
}

FResourceFile *CheckGamemaps(const char *filename, FileReader *file, bool quiet)
{
	FString fname(filename);
	int lastSlash = fname.LastIndexOfAny("/\\:");
	if(lastSlash != -1)
		fname = fname.Mid(lastSlash+1, 8);
	else
		fname = fname.Left(8);

	// File must be gamemaps.something or maptemp.something
	if(fname.Len() == 8 && (fname.CompareNoCase("gamemaps") == 0 || fname.Left(7).CompareNoCase("maptemp") == 0))
	{
		FResourceFile *rf = new FGamemaps(filename, file);
		if(rf->Open(quiet)) return rf;
		rf->Reader = NULL; // to avoid destruction of reader
		delete rf;
	}
	return NULL;
}
