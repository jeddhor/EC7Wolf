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
			const unsigned int firstShade = MIN<unsigned int>(NUMCOLORMAPS-1,
				MAX(0, 5-static_cast<int>(extraLight/16)));

			for(unsigned int color = 0;color < 256;++color)
			{
				unsigned int shadeIndex = firstShade;
				byte shadeColor = NormalLight.Maps[(shadeIndex<<8)+color];
				for(unsigned int step = 0;step < litBand;++step)
				{
					for(unsigned int darker = shadeIndex+1;
						darker < NUMCOLORMAPS;++darker)
					{
						const byte candidate = NormalLight.Maps[(darker<<8)+color];
						if(candidate != shadeColor)
						{
							shadeIndex = darker;
							shadeColor = candidate;
							break;
						}
					}
				}
				c7PlaneShades[color] = shadeColor;
				c7NextPlaneShades[color] = shadeColor;
				for(unsigned int darker = shadeIndex+1;
					darker < NUMCOLORMAPS;++darker)
				{
					const byte candidate = NormalLight.Maps[(darker<<8)+color];
					if(candidate != shadeColor)
					{
						c7NextPlaneShades[color] = candidate;
						break;
					}
				}
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
