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
	byte c7DarkerShades[256];
	unsigned int c7ShadeFraction = 0;
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

		// Corridor 7's untextured planes use a much steeper VGA shade ramp
		// than its walls. Preserve the bright near ceiling/floor while reaching
		// the darkest ramp entries before the horizon, as in the DOS renderer.
		if(corridor7)
		{
			const int shade = LIGHT2SHADE(118 + r_extralight);
			const int cutoff = (halfheight*19)/80;
			const int range = MAX(1, halfheight-1-cutoff);
			const int maxVisibility =
				((NUMCOLORMAPS-1)-(4*LIGHTVISIBILITY_FACTOR))*FRACUNIT;
			const int distance = MAX(0, y-cutoff);
			const fixed linearVisibility =
				fixed((int64_t(distance)*maxVisibility)/range);
			const int curveStrength = floor ? 40 : 24;
			const fixed curve = fixed((int64_t(curveStrength)*FRACUNIT*distance*
				MAX(0, range-distance))/(range*range));
			const fixed visibility = MAX<fixed>(0, linearVisibility-curve);
			// The DOS VGA renderer ordered-dithers between adjacent shade rows.
			// Keeping the fractional lookup prevents broad flat bands on modern
			// high-resolution viewports while retaining the original palette.
			const fixed limitedVisibility = MIN<fixed>(gLevelMaxLightVis, visibility);
			const fixed lookup = MAX<fixed>(0, shade-limitedVisibility);
			const unsigned int shadeIndex = MIN<unsigned int>(
				lookup >> FRACBITS, NUMCOLORMAPS-1);
			c7ShadeFraction = shadeIndex < NUMCOLORMAPS-1 ?
				(static_cast<unsigned int>(lookup) & (FRACUNIT-1)) : 0;
			curshades = &NormalLight.Maps[shadeIndex<<8];
			for(unsigned int color = 0;color < 256;++color)
			{
				c7DarkerShades[color] = curshades[color];
				for(unsigned int darker = shadeIndex+1;
					darker < NUMCOLORMAPS;++darker)
				{
					const byte candidate = NormalLight.Maps[(darker<<8)+color];
					if(candidate != curshades[color])
					{
						c7DarkerShades[color] = candidate;
						break;
					}
				}
			}
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
						{
							static const BYTE bayer4[16] =
								{ 0, 8, 2, 10, 12, 4, 14, 6,
								  3, 11, 1, 9, 15, 7, 13, 5 };
							const bool darker = corridor7 &&
								c7ShadeFraction > (static_cast<unsigned int>(
								bayer4[((y&3)<<2)|(x&3)]) << 12);
							*tex_offset = darker ? c7DarkerShades[c] : curshades[c];
						}
					}
					else
					{
						static const BYTE bayer4[16] =
							{ 0, 8, 2, 10, 12, 4, 14, 6,
							  3, 11, 1, 9, 15, 7, 13, 5 };
						const byte c = tex[texoffs];
						const bool darker = corridor7 &&
							c7ShadeFraction > (static_cast<unsigned int>(
							bayer4[((y&3)<<2)|(x&3)]) << 12);
						*tex_offset = darker ? c7DarkerShades[c] : curshades[c];
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
