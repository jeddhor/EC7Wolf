// Corridor 7's own distance shading for walls and sprites (GitHub #57).
//
// CORR7CD.EXE builds one compiled scaler per column height (SetupScaling,
// 1e37:0061). Every texel a scaler writes goes through a five-instruction
// subroutine with the column's shade amount in CH:
//
//     mov  bx,ax                 ; texel index (AH = 0)
//     and  cl,ss:[bx+2a1e]       ; shade & mask[texel]
//     sub  al,cl                 ; texel - shade
//     mov  cl,ch
//     mov  bl,ss:[bx+2b1e]       ; floor[texel], BH = 0
//     sub  bx,ax                 ; floor - (texel - shade)
//     and  al,bh                 ; kept only if that went negative
//
// so a texel is moved SHADE palette entries down its ramp, and becomes index 0
// (black) once it reaches or passes the ramp's first entry. The tables, read
// from a running game's data segment, are:
//
//   mask[i]  = 255 for 16..207 (the eight 24-entry colour ramps), 0 elsewhere:
//              the EGA block, the four rotating lamp ramps 208..239 and the
//              static lamps 240..255 are never shaded;
//   floor[i] = the first index of i's ramp, 16 + 24*n, and 0 outside them.
//
// The shade amount is looked up in the table at DS:c0a2, which 2f28:042b fills
// as 16 at index 0 and then one less every five entries down to 0 at 76. The
// index is the column's projected height plus two adjustments:
//
//   walls   (ScalePost, 0f11c):  (wallheight >> 3) + c1ac*2 + brightness
//   sprites (ScaleShape, 10cec): (height     >> 1) + c1ac*2 + brightness
//
// c1ac is 4 while the muzzle flash is lit (2163:1e42 and the other gun
// routines), so the flash adds eight. The brightness is DS:8b5c, 0 to 10,
// raised and lowered by the = and - keys (Keyboard[] at DS:8b6d) and kept in
// CONFIG.DAT; a game with no configuration starts at 0. The first-person
// weapon (SimpleScaleShape, 1e37:0a7c) draws at shade 0.
//
// Heights are the original's: heightnumerator / (nx >> 8) with Wolfenstein's
// projection for a 320-wide view (focal length 0x5700, MINDIST 0x5800), which
// gives a heightnumerator of 223232 -- the 72.37 degree view the port already
// reproduces. A wall a tile away is 872 high, so it is unshaded inside about
// 1.4 tiles, at shade 5 at two tiles, 11 at five and 14 at ten. Sprites use a
// quarter of the divisor and stay unshaded out to about five tiles.

#include "c7_shade.h"
#include "c_cvars.h"
#include "g_mapinfo.h"
#include "gamemap.h"
#include "id_ca.h"
#include "textures/textures.h"
#include "v_palette.h"
#include "wl_iwad.h"
#include "wl_main.h"

namespace C7Shade
{
	static BYTE tables[ROWS][256];
	static bool built = false;
	static int frameBonus = 0;

	static const int64_t NATIVE_HEIGHTNUMERATOR = 223232;

	bool Active()
	{
		return c7_lighting == 1 && IWad::CheckGameFilter("Corridor7");
	}

	static int NativeMask(int i) { return i >= 16 && i <= 207 ? 255 : 0; }
	static int NativeFloor(int i) { return i >= 16 && i <= 207 ? 16 + (i-16)/24*24 : 0; }

	// The scaler's subroutine, on the original's palette indices.
	static int NativeTexel(int texel, int shade)
	{
		const int lowered = (texel - (shade & NativeMask(texel))) & 0xFF;
		return NativeFloor(texel) - lowered >= 0 ? 0 : lowered;
	}

	void BuildTables()
	{
		// Textures are loaded through GPalette.Remap, which is the identity
		// except that index 0 moves onto a duplicate of its colour. A physical
		// index therefore names the original index it equals, and an original
		// index going out is sent through Remap the same way.
		for(int s = 0;s < ROWS;++s)
		{
			for(int i = 0;i < 256;++i)
				tables[s][i] = GPalette.Remap[NativeTexel(i, s)];
		}
		built = true;
	}

	const BYTE *Row(int shade)
	{
		if(!built)
			BuildTables();
		return tables[clamp(shade, 0, (int)MAX_SHADE)];
	}

	void SetFrameBonus(int bonus) { frameBonus = bonus; }
	int FrameBonus() { return frameBonus; }

	int ShadeForIndex(int index)
	{
		index = clamp(index, 0, 255);
		if(index == 0)
			return MAX_SHADE;
		return MAX(0, 15 - (index-1)/5);
	}

	static int NativeHeight(int portHeight)
	{
		if(heightnumerator <= 0 || portHeight <= 0)
			return 0;
		return (int)((int64_t)portHeight*NATIVE_HEIGHTNUMERATOR/heightnumerator);
	}

	int WallShade(int portHeight)
	{
		return ShadeForIndex((NativeHeight(portHeight)>>3) + frameBonus);
	}

	int SpriteShade(int portHeight)
	{
		return ShadeForIndex((NativeHeight(portHeight)>>1) + frameBonus);
	}

	// The floor and ceiling (1cb7:0a17, the first thing ThreeDRefresh draws).
	// Each row is a run of words, so its even four-pixel groups take the low
	// byte and its odd ones the high byte, and the two bytes swap every row:
	//
	//   ceiling, from the top:  start (C, C-1); after every third row both
	//                           drop by one while the new high byte is above
	//                           the limit.
	//   floor, from the horizon: start (F, F+1); the same three-row rule, but
	//                           only once 46 rows have counted past the first
	//                           two, and rising while below the limit.
	//
	// So the ceiling darkens toward the horizon from its first row, and the
	// floor holds its darkest pair for 48 rows below the horizon before it
	// starts to brighten. The four bytes are set per floor in 18b8:1177..11a3:
	// 38/18 and 184/200 (gray over purple) everywhere but MAP20 to MAP29, where
	// a jump table gives red (76/66, 66/76) or green (122/114, 114/122).
	static BYTE planePattern[2][PLANE_ROWS][2];
	static int planeFlat[2];
	static const LevelInfo *planeLevel = NULL;
	static int planeValues[4] = {-1, -1, -1, -1};

	static int FlatColor(FTextureID id)
	{
		if(!id.isValid())
			return -1;
		FTexture *const tex = TexMan(id);
		const BYTE *const pixels = tex ? tex->GetPixels() : NULL;
		return pixels ? pixels[0] : -1;
	}

	static void BuildPlanePattern(const int v[4])
	{
		// v: ceiling start, ceiling limit, floor start, floor limit.
		int hi = v[0], lo = v[0]-1, run = 0;
		for(int row = 0;row < PLANE_ROWS;++row)
		{
			planePattern[1][row][0] = GPalette.Remap[lo & 0xFF];
			planePattern[1][row][1] = GPalette.Remap[hi & 0xFF];
			++run;
			const int swap = hi; hi = lo; lo = swap;
			if((signed char)v[1] < (signed char)hi && run > 2)
			{
				run = 0;
				--hi; --lo;
			}
		}

		hi = v[2]; lo = v[2]+1; run = 0;
		int counted = 0;
		for(int row = 0;row < PLANE_ROWS;++row)
		{
			// Stored by distance from the near edge: the bottom of the view.
			BYTE *const out = planePattern[0][PLANE_ROWS-1-row];
			out[0] = GPalette.Remap[lo & 0xFF];
			out[1] = GPalette.Remap[hi & 0xFF];
			++run;
			const int swap = hi; hi = lo; lo = swap;
			if(run > 2 && ++counted > 45 && (signed char)hi < (signed char)v[3])
			{
				run = 0;
				++hi; ++lo;
			}
		}
	}

	const BYTE (*PlanePattern(bool ceiling, int &flatColor))[2]
	{
		if(!Active() || levelInfo == NULL || levelInfo->C7Planes[0] < 0 ||
			levelInfo->C7PlanesFlats[0] != levelInfo->DefaultTexture[0] ||
			levelInfo->C7PlanesFlats[1] != levelInfo->DefaultTexture[1])
			return NULL;

		if(planeLevel != levelInfo || memcmp(planeValues, levelInfo->C7Planes, sizeof(planeValues)) != 0)
		{
			planeLevel = levelInfo;
			memcpy(planeValues, levelInfo->C7Planes, sizeof(planeValues));
			BuildPlanePattern(planeValues);
			planeFlat[0] = FlatColor(levelInfo->DefaultTexture[MapSector::Floor]);
			planeFlat[1] = FlatColor(levelInfo->DefaultTexture[MapSector::Ceiling]);
		}
		flatColor = planeFlat[ceiling ? 1 : 0];
		if(flatColor < 0)
			return NULL;
		return planePattern[ceiling ? 1 : 0];
	}
}
