#include "textures/textures.h"
#include "c_cvars.h"
#include "id_ca.h"
#include "gamemap.h"
#include "wl_def.h"
#include "wl_draw.h"
#include "wl_main.h"
#include "wl_shade.h"
#include "wl_iwad.h"
#include "r_data/colormaps.h"
#include "v_palette.h"

#include <climits>

extern int viewshift;
extern fixed viewz;

static void R_DrawPlane(byte *vbuf, unsigned vbufPitch, int min_wallheight, int halfheight, fixed planeheight)
{
	fixed dist;                                // distance to row projection
	fixed tex_step;                            // global step per one screen pixel
	fixed gu, gv, du, dv;                      // global texture coordinates
	const byte *tex = NULL;
	int texwidth = 0, texheight = 0;
	fixed texxscale = 0, texyscale = 0;
	FTextureID lasttex;
	byte *tex_offset;
	bool useOptimized = false;
	bool isMasked = false;
	const bool corridor7 = IWad::CheckGameFilter("Corridor7");

	if(planeheight == 0) // Eye level
		return;

	const fixed heightFactor = abs(planeheight)>>8;
	int y0 = ((min_wallheight*heightFactor)>>FRACBITS) - abs(viewshift);
	if(y0 > halfheight)
		return; // view obscured by walls
	if(y0 <= 0) y0 = 1; // don't let division by zero

	lasttex.SetInvalid();

	const unsigned int mapwidth = map->GetHeader().width;
	const unsigned int mapheight = map->GetHeader().height;

	fixed planenumerator = FixedMul(heightnumerator, planeheight);
	const bool floor = planenumerator < 0;
	int tex_offsetPitch;
	if(floor)
	{
		tex_offset = vbuf + (signed)vbufPitch * (halfheight + y0);
		tex_offsetPitch = vbufPitch-viewwidth;
		planenumerator *= -1;
	}
	else
	{
		tex_offset = vbuf + (signed)vbufPitch * (halfheight - y0 - 1);
		tex_offsetPitch = -viewwidth-vbufPitch;
	}

	// Break viewx/viewy apart so we can use the fractional part for texel selection without overflowing.
	const int viewxTile = viewx>>FRACBITS;
	const int viewxFrac = (viewx&(FRACUNIT-1))<<8; // 8.24
	const int viewyTile = viewy>>FRACBITS;
	const int viewyFrac = (viewy&(FRACUNIT-1))<<8; // 8.24

	unsigned int oldmapx = INT_MAX, oldmapy = INT_MAX;
	const byte* curshades = NormalLight.Maps;
	byte c7PlaneShades[256];
	byte c7NextPlaneShades[256];
	// draw horizontal lines
	for(int y = y0;floor ? y+halfheight < viewheight : y < halfheight; ++y, tex_offset += tex_offsetPitch)
	{
		if(floor ? (y+halfheight < 0) : (y < halfheight - viewheight))
		{
			tex_offset += viewwidth;
			continue;
		}

		// Shift in some extra bits so that we don't get spectacular round off.
		dist = (planenumerator / (y + 1))<<8;
		gu =  viewxFrac + FixedMul(dist, viewcos);
		gv = -viewyFrac + FixedMul(dist, viewsin);
		tex_step = dist / scale;
		du =  FixedMul(tex_step, viewsin);
		dv = -FixedMul(tex_step, viewcos);
		gu -= (viewwidth >> 1) * du;
		gv -= (viewwidth >> 1) * dv; // starting point (leftmost)

		// Corridor 7's untextured planes use a screen-space VGA pattern rather
		// than Wolf's distance formula. Native 320x200 captures show that the
		// renderer advances one visible palette step every three rows from the
		// near edge toward the horizon. Each three-row band alternates adjacent
		// steps in four-pixel groups; the middle row and successive bands reverse
		// the groups. Measuring from each plane's near edge mirrors the pattern
		// onto the floor. Reconstruct it in virtual
		// 320x160 viewport coordinates so it scales cleanly at any resolution.
		if(corridor7)
		{
			const unsigned int virtualEdgeRow = MIN<unsigned int>(79,
				(static_cast<uint64_t>(MAX(0, halfheight-1-y))*80)/MAX(1, halfheight));
			const unsigned int band = virtualEdgeRow/3;
			const unsigned int extraLight = MAX(0, r_extralight);
			const unsigned int litBand = band > extraLight/8 ? band-extraLight/8 : 0;

			// Corridor 7 does not shade its planes through a colormap at all: it
			// walks the PALETTE, one index darker per band, and stops at the bottom
			// of the colour's own ramp. Read straight off the released game,
			// MAP23's green ceiling from the screen edge inward:
			//
			//   122 121 122 120 121 120 119 120 118 119 118 117 ...
			//
			// which is band N alternating with band N+1 while N counts down by one
			// index per band. The ramps are neither uniformly sized nor aligned
			// (grey 16-39, red 64-79, green 112-127, purple 184-207), so each
			// colour's floor comes from V_GetC7RampFloors, which derives them from
			// the palette by descending while luminance does not rise.
			//
			// This replaces a walk of NormalLight.Maps looking for the next
			// visually distinct row. That walk could not match the original on any
			// saturated colour: Corridor 7's palette holds three overlapping red
			// ramps, so the colour matcher legitimately hops between them
			// (71 -> 241, 73 -> 242) and the step sequence came out erratic.
			const BYTE *const rampFloor = V_GetC7RampFloors();
			for(unsigned int color = 0;color < 256;++color)
			{
				const unsigned int base = rampFloor[color];
				const unsigned int lit = color >= base + litBand
					? color - litBand : base;
				c7PlaneShades[color] = static_cast<byte>(lit);
				c7NextPlaneShades[color] =
					static_cast<byte>(lit > base ? lit-1 : base);
			}
			curshades = c7PlaneShades;
		}
		else
		{
			const int shade = LIGHT2SHADE(gLevelLight + r_extralight);
			const int tz = FixedMul(FixedDiv(r_depthvisibility, abs(planeheight)),
				abs(((halfheight)<<16) - ((halfheight-y)<<16)));
			curshades = &NormalLight.Maps[GETPALOOKUP(tz, shade)<<8];
		}

		for(unsigned int x = 0;x < (unsigned)viewwidth; ++x, ++tex_offset)
		{
			const unsigned int virtualX = corridor7 ?
				MIN<unsigned int>(319, (static_cast<uint64_t>(x)*320)/MAX(1, viewwidth)) : 0;
			const unsigned int virtualEdgeRow = corridor7 ? MIN<unsigned int>(79,
				(static_cast<uint64_t>(MAX(0, halfheight-1-y))*80)/MAX(1, halfheight)) : 0;
			const unsigned int band = virtualEdgeRow/3;
			const bool c7UseNextShade = corridor7 &&
				((((virtualX>>2)&1) ^ (virtualEdgeRow%3 == 1) ^
				  (band&1)) == 0);
			if(((wallheight[x]*heightFactor)>>FRACBITS) <= y)
			{
				unsigned int curx = viewxTile + (gu >> (TILESHIFT+8));
				unsigned int cury = viewyTile + (-(gv >> (TILESHIFT+8)) - 1);

				if(curx != oldmapx || cury != oldmapy)
				{
					oldmapx = curx;
					oldmapy = cury;
					const MapSpot spot = map->GetSpot(oldmapx%mapwidth, oldmapy%mapheight, 0);

					FTextureID curtex = spot->sector ? spot->sector->texture[floor ? MapSector::Floor : MapSector::Ceiling] : FNullTextureID();

					if (curtex != lasttex)
					{
						lasttex = curtex;
						if(curtex.isValid())
						{
							FTexture * const texture = TexMan(curtex);
							tex = texture->GetPixels();
							texwidth = texture->GetWidth();
							texheight = texture->GetHeight();
							texxscale = texture->xScale>>10;
							texyscale = -texture->yScale>>10;

							useOptimized = texwidth == 64 && texheight == 64 && texxscale == FRACUNIT>>10 && texyscale == -FRACUNIT>>10;
							isMasked = texture->bMasked;
						}
						else
							tex = NULL;
					}
				}

				if(tex)
				{
					unsigned texoffs;
					if(useOptimized)
					{
						const int u = (gu>>18) & 63;
						const int v = (-gv>>18) & 63;
						texoffs = (u * 64) + v;
					}
					else
					{
						const int u = (FixedMul((viewxTile<<16)+(gu>>8)-512, texxscale)) & (texwidth-1);
						const int v = (FixedMul((viewyTile<<16)-(gv>>8)+512, texyscale)) & (texheight-1);
						texoffs = (u * texheight) + v;
					}

					if(isMasked)
					{
						if(const byte c = tex[texoffs])
							*tex_offset = c7UseNextShade ? c7NextPlaneShades[c] : curshades[c];
					}
					else
					{
						const byte c = tex[texoffs];
						*tex_offset = c7UseNextShade ? c7NextPlaneShades[c] : curshades[c];
					}
				}
			}
			gu += du;
			gv += dv;
		}
	}
}

// Textured Floor and Ceiling by DarkOne
// With multi-textured floors and ceilings stored in lower and upper bytes of
// according tile in third mapplane, respectively.
void DrawFloorAndCeiling(byte *vbuf, unsigned vbufPitch, int min_wallheight)
{
	const int halfheight = (viewheight >> 1) - viewshift;

	R_DrawPlane(vbuf, vbufPitch, min_wallheight, halfheight, viewz);
	R_DrawPlane(vbuf, vbufPitch, min_wallheight, halfheight, viewz+(map->GetPlane(0).depth<<FRACBITS));
}
