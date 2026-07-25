// WL_DRAW.C

#include "wl_def.h"
#include "id_sd.h"
#include "id_in.h"
#include "id_vl.h"
#include "id_vh.h"
#include "id_us.h"
#include "textures/textures.h"
#include "c_cvars.h"
#include "r_sprites.h"
#include "r_data/colormaps.h"
#include "v_video.h"
#include "wl_cloudsky.h"
#include "wl_atmos.h"
#include "wl_shade.h"
#include "actor.h"
#include "id_ca.h"
#include "gamemap.h"
#include "g_mapinfo.h"
#include "lumpremap.h"
#include "wl_agent.h"
#include "wl_draw.h"
#include "wl_game.h"
#include "wl_iwad.h"
#include "wl_net.h"
#include "wl_play.h"
#include "wl_state.h"
#include "a_inventory.h"
#include "thingdef/thingdef.h"

/*
=============================================================================

							LOCAL CONSTANTS

=============================================================================
*/

#define MINDIST         (0x4000l)

#define mapheight (map->GetHeader().height)
#define mapwidth (map->GetHeader().width)
#define maparea (mapheight*mapwidth)

/*
=============================================================================

							GLOBAL VARIABLES

=============================================================================
*/

void DrawFloorAndCeiling(byte *vbuf, unsigned vbufPitch, int min_wallheight);
void DrawParallax(byte *vbuf, unsigned vbufPitch);

const RatioInformation AspectCorrection[] =
{
	/* UNC		*/  {960,  600, 0x10000, 0,                    48,         false},
	/* 16:9		*/  {1280, 450, 0x15555, 0,                    48*3/4,     true},
	/* 16:10	*/  {1152, 500, 0x13333, 0,                    48*5/6,     true},
	/* 17:10	*/  {1224, 471, 0x14666, 0,                    48*40/51,   true},
	/* 4:3 		*/  {960,  600, 0x10000, 0,                    48,         false},
	/* 5:4		*/  {960,  640, 0x10000, (fixed) 6.5*FRACUNIT, 48*15/16,   false},
	/* 64:27	*/  {1720, 346, 0x1C71C, 0,                    48*173/300, true},
	/* 32:9		*/  {2560, 600, 0x2AAAB, 0,					   48*3/8,     true}
};

/*static*/ byte *vbuf = NULL;
unsigned vbufPitch = 0;

int32_t	lasttimecount;
int32_t	frameon;
bool	fpscounter;
int		r_extralight;

int fps_frames=0, fps_time=0, fps=0;

TUniquePtr<int[]> wallheight;
int min_wallheight;

//
// math tables
//
TUniquePtr<short[]> pixelangle;
fixed finetangent[FINEANGLES/2 + ANG180];
fixed finesine[FINEANGLES+FINEANGLES/4];
fixed *finecosine = finesine+ANG90;

//
// refresh variables
//
fixed   viewx,viewy;                    // the focal point
angle_t viewangle;
fixed   viewsin,viewcos;
int viewshift = 0;
fixed viewz = 32;

fixed gLevelVisibility = VISIBILITY_DEFAULT;
fixed gLevelMaxLightVis = MAXLIGHTVIS_DEFAULT;
int gLevelLight = LIGHTLEVEL_DEFAULT;

void    TransformActor (AActor *ob);
void    BuildTables (void);
void    ClearScreen (void);
unsigned int CalcRotate (AActor *ob);
void    DrawScaleds (void);
void    CalcTics (void);
void    ThreeDRefresh (void);



//
// wall optimization variables
//
int     lastside;               // true for vertical
int32_t    lastintercept;
MapSpot lasttilehit;
int     lasttexture;

//
// ray tracing variables
//
short    focaltx,focalty,viewtx,viewty;
longword xpartialup,xpartialdown,ypartialup,ypartialdown;

short   midangle;
short   angle;

MapTile::Side hitdir;
MapSpot tilehit;
int     pixx;

short   xtile,ytile;
short   xtilestep,ytilestep;
int32_t    xintercept,yintercept;
word    xstep,ystep;
int     texdelta;
int		texheight;

#define TEXTUREBASE 0x4000000
fixed	texxscale = FRACUNIT;
fixed	texyscale = FRACUNIT;


/*
============================================================================

						3 - D  DEFINITIONS

============================================================================
*/

/*
========================
=
= TransformActor
=
= Takes paramaters:
=   gx,gy               : globalx/globaly of point
=
= globals:
=   viewx,viewy         : point of view
=   viewcos,viewsin     : sin/cos of viewangle
=   scale               : conversion from global value to screen value
=
= sets:
=   screenx,transx,transy,screenheight: projected edge location and size
=
========================
*/


//
// transform actor
//
void TransformActor (AActor *ob)
{
	fixed gx,gy,gxt,gyt,nx,ny;

//
// translate point to view centered coordinates
//
	gx = ob->x-viewx;
	gy = ob->y-viewy;

//
// calculate newx
//
	gxt = FixedMul(gx,viewcos);
	gyt = FixedMul(gy,viewsin);
	// Wolf4SDL used 0x2000 for statics and 0x4000 for moving actors, but since
	// we no longer tell the difference, use the smaller fudging value since
	// the larger one will just look ugly in general.
	nx = gxt-gyt-0x2000;

//
// calculate newy
//
	gxt = FixedMul(gx,viewsin);
	gyt = FixedMul(gy,viewcos);
	ny = gyt+gxt;

//
// calculate perspective ratio
//
	ob->transx = nx;
	ob->transy = ny;

	if (nx<MINDIST)                 // too close, don't overflow the divide
	{
		ob->viewheight = 0;
		return;
	}

	ob->viewx = (word)(centerx + ny*scale/nx);

//
// calculate height (heightnumerator/(nx>>8))
//
	ob->viewheight = (word)((heightnumerator<<8)/nx);
}

//==========================================================================

/*
====================
=
= CalcHeight
=
= Calculates the height of xintercept,yintercept from viewx,viewy
=
====================
*/

int CalcHeight()
{
	fixed z = FixedMul(xintercept - viewx, viewcos)
		- FixedMul(yintercept - viewy, viewsin);
	if(z < MINDIST) z = MINDIST;
	int height = (heightnumerator << 8) / z;
	if(height < min_wallheight) min_wallheight = height;
	return height;
}

//==========================================================================

/*
===================
=
= ScalePost
=
===================
*/

const byte *postsource;
const byte *postopacity;
int postx;

static inline BYTE Corridor7CycleColor(BYTE color)
{
	if(!IWad::CheckGameFilter("Corridor7"))
		return color;

	// The DOS game independently rotates all four eight-color ramps from
	// 208..239. Besides the red and blue force-field bands, 224..239 drive
	// the blinking and travelling lights embedded in many wall textures.
	if(color >= 208 && color <= 239)
	{
		const int base = color & ~7;
		const int phase = (gamestate.TimeCount >> 3) & 7;
		return base + ((color-base-phase) & 7);
	}
	return color;
}

static inline BYTE ShadeWallColor(BYTE color, const BYTE *shades)
{
	color = Corridor7CycleColor(color);
	if(IWad::CheckGameFilter("Corridor7"))
	{
		// Corridor 7 reserves indices 15 and 254 for lamps embedded in wall
		// graphics. Index 39 is the ordinary white used throughout structural
		// artwork and must remain distance-shaded. It also uses the four
		// rotating 208..239 ramps for illuminated animated pixels. The DOS
		// renderer leaves both groups at source brightness while shading the
		// rest of the wall by distance. Do this per texel so a lit panel keeps
		// its shaded housing, and so the behavior is independent of viewport
		// resolution and scaling.
		if(color == GPalette.Remap[15] || color == GPalette.Remap[254] ||
			(color >= GPalette.Remap[208] && color <= GPalette.Remap[239]))
			return NormalLight.Maps[color];
	}
	return shades[color];
}

void ScalePost()
{
	if(postsource == NULL)
		return;

	int ywcount, yoffs, yw, yd, yendoffs;
	byte col;

	const int shade = LIGHT2SHADE(gLevelLight + r_extralight);
	const int tz = FixedMul(r_depthvisibility<<8, wallheight[postx]);
	BYTE *curshades = &NormalLight.Maps[GETPALOOKUP(MAX(tz, MINZ), shade)<<8];

	ywcount = yd = wallheight[postx];
	if(yd <= 0)
		yd = 100;

	// Calculate starting and ending offsets
	{
		// ywcount can be large enough to cause an overflow if we don't reduce
		// fixed point precision here
		const int topoffset = ywcount*((viewz + fixed(map->GetPlane(0).depth<<FRACBITS))>>8)/(32<<(FRACBITS-5));
		const int botoffset = ywcount*(viewz>>8)/(32<<(FRACBITS-5));

		yoffs = (viewheight / 2 - topoffset - viewshift) * vbufPitch;
		if(yoffs < 0) yoffs = 0;
		yoffs += postx;

		yendoffs = viewheight / 2 - botoffset - 1 - viewshift;
		yw=(texyscale>>2)-1;
	}

	while(yendoffs >= viewheight)
	{
		ywcount -= texyscale;
		while(ywcount <= 0)
		{
			ywcount += yd;
			yw--;
		}
		yendoffs--;
	}
	if(yw < 0)
		yw = (texyscale>>2) - ((-yw) % (texyscale>>2));

	col = ShadeWallColor(postsource[yw], curshades);
	bool opaque = postopacity == NULL || postopacity[yw] != 0;
	yendoffs = yendoffs * vbufPitch + postx;
	while(yoffs <= yendoffs)
	{
		if(opaque)
			vbuf[yendoffs] = col;
		ywcount -= texyscale;
		if(ywcount <= 0)
		{
			do
			{
				ywcount += yd;
				yw--;
			}
			while(ywcount <= 0);
			if(yw < 0) yw = (texyscale>>2)-1;
			col = ShadeWallColor(postsource[yw], curshades);
			opaque = postopacity == NULL || postopacity[yw] != 0;
		}
		yendoffs -= vbufPitch;
	}
}

void GlobalScalePost(byte *vidbuf, unsigned pitch)
{
	vbuf = vidbuf;
	vbufPitch = pitch;
	postopacity = NULL;
	ScalePost();
}

static void DetermineHitDir(bool vertical)
{
	if(vertical)
	{
		if(xtilestep==-1 && (xintercept>>16)<=xtile)
			hitdir = MapTile::East;
		else
			hitdir = MapTile::West;
	}
	else
	{
		if(ytilestep==-1 && (yintercept>>16)<=ytile)
			hitdir = MapTile::South;
		else
			hitdir = MapTile::North;
	}
}

static int SlideTextureOffset(unsigned int style, int intercept, int amount)
{
	if(!amount)
		return 0;

	switch(style)
	{
		default:
			return -amount;
		case SLIDE_Split:
			if(intercept < FRACUNIT/2)
				return amount/2;
			return -amount/2;
		case SLIDE_Invert:
			return amount;
	}
}

// Corridor 7 uses plane-1 values 86..88 to opt individual wall cells into
// four-page animations. The released maps deliberately reuse the same base
// wall IDs without a marker, so these cannot be ordinary global ANIMDEFS.
static FTexture *GetWallTexture(MapSpot spot, MapTile::Side side)
{
	FTextureID texture = spot->texture[side];
	if(spot->corridor7WallMarker >= 1 && spot->corridor7WallMarker <= 3 &&
		spot->corridor7WallID > 0 && spot->corridor7WallID <= 253)
	{
		static bool cached[253] = { false };
		static FTextureID animation[253][4];
		const unsigned int base = spot->corridor7WallID-1;
		if(!cached[base])
		{
			for(unsigned int i = 0;i < 4;++i)
			{
				FString textureName;
				textureName.Format("C7W%04u", base+i);
				animation[base][i] = TexMan.CheckForTexture(textureName,
					FTexture::TEX_Wall);
			}
			cached[base] = true;
		}
		const unsigned int frame =
			((gamestate.TimeCount/5)+(spot->corridor7WallMarker-1))&3;
		const FTextureID animated = animation[base][frame];
		if(animated.isValid())
			texture = animated;
	}
	return TexMan(texture);
}

// --- Corridor 7 force-field door helpers (kept in sync with r_worldbuilder.cpp) ---

// 106 = active barrier, 107 = its permanently-open aperture. Both render as a single
// centre pane on a track and, unlike normal doors, carry no offset flag.
static bool IsForceFieldDoor(MapSpot spot)
{
	return spot && spot->tile &&
		(spot->corridor7WallMarker == 106 || spot->corridor7WallMarker == 107);
}

// A force-field door's axis is not stored, so derive it from open-neighbour
// topology (the pane blocks the passage, so it sits perpendicular to the open run).
static bool ForceFieldDoorHorizontal(MapSpot spot)
{
	const MapSpot n = spot->GetAdjacent(MapTile::North);
	const MapSpot s = spot->GetAdjacent(MapTile::South);
	const MapSpot w = spot->GetAdjacent(MapTile::West);
	const MapSpot e = spot->GetAdjacent(MapTile::East);
	const int openNS = (!n || !n->tile) + (!s || !s->tile);
	const int openWE = (!w || !w->tile) + (!e || !e->tile);
	return openNS > openWE;
}

// The Corridor 7 door track/jamb graphic (C7W0254), used on the jamb sides of every
// normal door tile in xlat/corridor7.txt. Force-field door tiles carry the force-
// field art on all four sides, so their jamb faces must substitute this fixed track.
static FTexture *C7DoorTrackTexture()
{
	static FTextureID id = TexMan.CheckForTexture("C7W0254", FTexture::TEX_Wall);
	return id.isValid() ? TexMan(id) : NULL;
}

/*
====================
=
= HitVertWall
=
= tilehit bit 7 is 0, because it's not a door tile
= if bit 6 is 1 and the adjacent tile is a door tile, use door side pic
=
====================
*/

void HitVertWall (void)
{
	if(!tilehit)
		return;

	int texture;

	DetermineHitDir(true);

	tilehit->amFlags |= AM_Visible;
	texture = (yintercept+texdelta+SlideTextureOffset(tilehit->slideStyle, (word)yintercept, tilehit->slideAmount[hitdir]))&(FRACUNIT-1);
	if (xtilestep == -1 && !tilehit->tile->offsetVertical)
	{
		texture = (FRACUNIT - texture)&(FRACUNIT-1);
		xintercept += TILEGLOBAL;
	}

	if(lastside==1 && lastintercept==xtile && lasttilehit==tilehit && !(lasttilehit->tile->offsetVertical))
	{
		texture -= texture%texxscale;

		ScalePost();
		wallheight[pixx] = CalcHeight();
		if(postsource)
			postsource+=(texture-lasttexture)*texheight/texxscale;
		if(postopacity)
			postopacity+=(texture-lasttexture)*texheight/texxscale;
		postx=pixx;
		lasttexture=texture;
		return;
	}

	if(lastside!=-1) ScalePost();

	lastside=1;
	lastintercept=xtile;
	lasttilehit=tilehit;
	wallheight[pixx] = CalcHeight();
	postx = pixx;
	FTexture *source = NULL;

	MapSpot adj = tilehit->GetAdjacent(hitdir);
	const bool adjForceField = IsForceFieldDoor(adj) && ForceFieldDoorHorizontal(adj);
	if (adj && adj->tile && adj->tile->offsetHorizontal && !adj->tile->offsetVertical) // check for adjacent doors
		source = GetWallTexture(adj, hitdir);
	else if (adjForceField) // force-field door jamb: fixed track texture, not its art
		source = C7DoorTrackTexture();
	else
		source = GetWallTexture(tilehit, hitdir);

	if(source)
	{
		texheight = source->GetHeight();
		texxscale = TEXTUREBASE/source->xScale;
		texyscale = source->yScale>>(FRACBITS-8);
		texture -= texture%texxscale;

		const unsigned int column = texture/texxscale;
		postsource = source->GetColumn(column, NULL);
		postopacity = source->GetColumnOpacity(column);
	}
	else
	{
		postsource = NULL;
		postopacity = NULL;
	}

	lasttexture=texture;
}


/*
====================
=
= HitHorizWall
=
= tilehit bit 7 is 0, because it's not a door tile
= if bit 6 is 1 and the adjacent tile is a door tile, use door side pic
=
====================
*/

void HitHorizWall (void)
{
	if(!tilehit)
		return;

	int texture;

	DetermineHitDir(false);

	tilehit->amFlags |= AM_Visible;
	texture = (xintercept+texdelta+SlideTextureOffset(tilehit->slideStyle, (word)xintercept, tilehit->slideAmount[hitdir]))&(FRACUNIT-1);
	if(!tilehit->tile->offsetHorizontal)
	{
		if (ytilestep == -1)
			yintercept += TILEGLOBAL;
		else
			texture = (FRACUNIT - texture)&(FRACUNIT-1);
	}

	if(lastside==0 && lastintercept==ytile && lasttilehit==tilehit && !(lasttilehit->tile->offsetHorizontal))
	{
		texture -= texture%texxscale;

		ScalePost();
		wallheight[pixx] = CalcHeight();
		if(postsource)
			postsource+=(texture-lasttexture)*texheight/texxscale;
		if(postopacity)
			postopacity+=(texture-lasttexture)*texheight/texxscale;
		postx=pixx;
		lasttexture=texture;
		return;
	}

	if(lastside!=-1) ScalePost();

	lastside=0;
	lastintercept=ytile;
	lasttilehit=tilehit;
	wallheight[pixx] = CalcHeight();
	postx = pixx;
	FTexture *source = NULL;

	MapSpot adj = tilehit->GetAdjacent(hitdir);
	const bool adjForceField = IsForceFieldDoor(adj) && !ForceFieldDoorHorizontal(adj);
	if (adj && adj->tile && adj->tile->offsetVertical && !adj->tile->offsetHorizontal) // check for adjacent doors
		source = GetWallTexture(adj, hitdir);
	else if (adjForceField) // force-field door jamb: fixed track texture, not its art
		source = C7DoorTrackTexture();
	else
		source = GetWallTexture(tilehit, hitdir);

	if(source)
	{
		texheight = source->GetHeight();
		texxscale = TEXTUREBASE/source->xScale;
		texyscale = source->yScale>>(FRACBITS-8);
		texture -= texture%texxscale;

		const unsigned int column = texture/texxscale;
		postsource = source->GetColumn(column, NULL);
		postopacity = source->GetColumnOpacity(column);
	}
	else
	{
		postsource = NULL;
		postopacity = NULL;
	}

	lasttexture=texture;
}

//==========================================================================

#define HitHorizBorder HitHorizWall
#define HitVertBorder HitVertWall

//==========================================================================

/*
=====================
=
= CalcRotate
=
=====================
*/

unsigned int CalcRotate (AActor *ob)
{
	angle_t angle, viewangle;

	// this isn't exactly correct, as it should vary by a trig value,
	// but it is close enough with only eight rotations

	viewangle = players[ConsolePlayer].camera->angle + (centerx - ob->viewx)/8;

	angle = viewangle - ob->angle;

	angle+= ANGLE_180 + ANGLE_45/2;

	return angle/ANGLE_45;
}

/*
=====================
=
= DrawScaleds
=
= Draws all objects that are visable
=
=====================
*/

#define MAXVISABLE 512

enum VisObjectType
{
	VIS_Actor,
	VIS_MaskedWall
};

typedef struct
{
	VisObjectType type;
	AActor *actor;
	MapSpot spot;
	MapTile::Side side;
	int first;
	int last;
	int viewheight;
	//short      viewx,
	//		viewheight,
	//		shapenum;
	//short      flags;          // this must be changed to uint32_t, when you
							// you need more than 16-flags for drawing
} visobj_t;

visobj_t vislist[MAXVISABLE];
visobj_t *visptr,*visstep,*farthest;
static TArray<int> maskedWallDepth;

struct MaskedWallHit
{
	MapSpot spot;
	MapTile::Side side;
	int first;
	int last;

	MaskedWallHit(MapSpot spot, MapTile::Side side, int column)
		: spot(spot), side(side), first(column), last(column) {}
};

static TArray<MaskedWallHit> maskedWallHits;

// Corridor 7 force-field doors (map marker 106) are a single see-through pane on
// the cell-centre plane -- the barrier just switches off in place, it never slides.
// The map format encodes only the tile, not the axis, so (like autoOrient doors)
// pick it from open-neighbour topology: the pane blocks the passage, so it is
// perpendicular to whichever axis the open floor runs along. Returned as an axis
// selector so the masked-plane code can centre it without the tile carrying an
// offset flag (which would reclassify it as a door and change collision).
enum { MASKPLANE_EDGES = 0, MASKPLANE_CENTRE_X, MASKPLANE_CENTRE_Y };

static int MaskedPlaneAxis(MapSpot spot)
{
	if(spot->tile->offsetVertical)
		return MASKPLANE_CENTRE_X;
	if(spot->tile->offsetHorizontal)
		return MASKPLANE_CENTRE_Y;
	if(IsForceFieldDoor(spot))
		// Passage along N/S -> pane spans X, centred in Y (MASKPLANE_CENTRE_Y).
		return ForceFieldDoorHorizontal(spot) ? MASKPLANE_CENTRE_Y : MASKPLANE_CENTRE_X;
	return MASKPLANE_EDGES;
}

static bool IsMaskedWallPassSide(MapSpot spot, MapTile::Side side)
{
	if(!(spot->maskedWallType || spot->tile->renderMasked))
		return false;
	const int axis = MaskedPlaneAxis(spot);
	if(axis == MASKPLANE_CENTRE_X && side != MapTile::West && side != MapTile::East)
		return false;
	if(axis == MASKPLANE_CENTRE_Y && side != MapTile::North && side != MapTile::South)
		return false;

	// Rendering must continue through a masked tile even when another wall tile
	// touches the side the ray entered. Otherwise a line of adjacent glass panes
	// stops at its second tile, and that tile's transparent texels expose the
	// previous framebuffer instead of freshly traced scenery.
	if(IWad::CheckGameFilter("Corridor7"))
		return true;

	MapSpot adjacent = spot->GetAdjacent(side);
	return !adjacent || !adjacent->tile;
}

static bool IsConnectedMaskedWall(MapSpot spot, MapTile::Side direction)
{
	MapSpot other = spot->GetAdjacent(direction);
	if(!other || !other->tile ||
		!(other->maskedWallType || other->tile->renderMasked))
	{
		return false;
	}

	// Corridor 7 puts unrelated masked artwork next to one another in a few
	// places. Only merge faces that came from the same wall definition and map
	// marker, otherwise a real exposed edge could disappear.
	if(spot->corridor7WallID || other->corridor7WallID)
	{
		return spot->corridor7WallID == other->corridor7WallID &&
			spot->corridor7WallMarker == other->corridor7WallMarker;
	}
	return true;
}

static bool IsMaskedWallRenderSide(MapSpot spot, MapTile::Side side)
{
	if(!IsMaskedWallPassSide(spot, side))
		return false;

	const bool horizontalRun = IsConnectedMaskedWall(spot, MapTile::East) ||
		IsConnectedMaskedWall(spot, MapTile::West);
	const bool verticalRun = IsConnectedMaskedWall(spot, MapTile::North) ||
		IsConnectedMaskedWall(spot, MapTile::South);

	// A row of panes is one continuous plane. Its internal east/west tile
	// boundaries are not surfaces; drawing them edge-on creates the periodic
	// floor-to-ceiling black lines seen down glass-lined corridors.
	if(horizontalRun && !verticalRun &&
		(side == MapTile::East || side == MapTile::West))
	{
		return false;
	}
	if(verticalRun && !horizontalRun &&
		(side == MapTile::North || side == MapTile::South))
	{
		return false;
	}
	return true;
}

static void RecordMaskedWallHit(MapSpot spot, MapTile::Side side, int column)
{
	// Rays are traced from left to right, but each ray can cross several panes.
	// Extend the most recent run for this exact surface instead of turning the
	// tile-wide visibility bit into a full, guessed wall face.
	for(int i = maskedWallHits.Size()-1;i >= 0;--i)
	{
		MaskedWallHit &hit = maskedWallHits[i];
		if(hit.spot != spot || hit.side != side)
			continue;
		if(column <= hit.last+1)
		{
			hit.last = MAX(hit.last, column);
			return;
		}
		break;
	}
	maskedWallHits.Push(MaskedWallHit(spot, side, column));
}

static void GetMaskedWallEndpoints(MapSpot spot, MapTile::Side side,
	fixed &worldx1, fixed &worldy1, fixed &worldx2, fixed &worldy2)
{
	const fixed left = spot->GetX() << TILESHIFT;
	const fixed top = spot->GetY() << TILESHIFT;
	const fixed right = left + TILEGLOBAL;
	const fixed bottom = top + TILEGLOBAL;
	// A centred pane (offset door or C7 force-field door) collapses front and back
	// to the cell-centre plane; a plain masked wall keeps them at the tile edges.
	const int axis = MaskedPlaneAxis(spot);
	const fixed verticalPlane = axis == MASKPLANE_CENTRE_X ? left+TILEGLOBAL/2 : left;
	const fixed verticalBackPlane = axis == MASKPLANE_CENTRE_X ? left+TILEGLOBAL/2 : right;
	const fixed horizontalPlane = axis == MASKPLANE_CENTRE_Y ? top+TILEGLOBAL/2 : top;
	const fixed horizontalBackPlane = axis == MASKPLANE_CENTRE_Y ? top+TILEGLOBAL/2 : bottom;

	switch(side)
	{
		case MapTile::West:
			worldx1 = worldx2 = verticalPlane;
			worldy1 = top;
			worldy2 = bottom;
			break;
		case MapTile::East:
			worldx1 = worldx2 = verticalBackPlane;
			worldy1 = bottom;
			worldy2 = top;
			break;
		case MapTile::North:
			worldy1 = worldy2 = horizontalPlane;
			worldx1 = right;
			worldx2 = left;
			break;
		default:
			worldy1 = worldy2 = horizontalBackPlane;
			worldx1 = left;
			worldx2 = right;
			break;
	}
}

static void TransformMaskedWallPoint(fixed worldx, fixed worldy, fixed &nx, fixed &ny)
{
	const fixed gx = worldx-viewx;
	const fixed gy = worldy-viewy;
	nx = FixedMul(gx, viewcos)-FixedMul(gy, viewsin);
	ny = FixedMul(gy, viewcos)+FixedMul(gx, viewsin);
}

static bool ClipMaskedWall(fixed &nx1, fixed &ny1, fixed &u1,
	fixed &nx2, fixed &ny2, fixed &u2)
{
	if(nx1 < MINDIST && nx2 < MINDIST)
		return false;

	if(nx1 < MINDIST)
	{
		const fixed fraction = FixedDiv(MINDIST-nx1, nx2-nx1);
		ny1 += FixedMul(ny2-ny1, fraction);
		u1 += FixedMul(u2-u1, fraction);
		nx1 = MINDIST;
	}
	else if(nx2 < MINDIST)
	{
		const fixed fraction = FixedDiv(MINDIST-nx2, nx1-nx2);
		ny2 += FixedMul(ny1-ny2, fraction);
		u2 += FixedMul(u1-u2, fraction);
		nx2 = MINDIST;
	}
	return true;
}

static int MaskedWallHeight(MapSpot spot, MapTile::Side side)
{
	fixed worldx1, worldy1, worldx2, worldy2;
	fixed nx1, ny1, nx2, ny2;
	GetMaskedWallEndpoints(spot, side, worldx1, worldy1, worldx2, worldy2);
	TransformMaskedWallPoint(worldx1, worldy1, nx1, ny1);
	TransformMaskedWallPoint(worldx2, worldy2, nx2, ny2);
	const fixed depth = (nx1+nx2)/2;
	return depth < MINDIST ? 0 : (heightnumerator<<8)/depth;
}

static void ScaleMaskedWallPost(const BYTE *source, const BYTE *opacity,
	int screenx, int height, int textureHeight, int textureYScale)
{
	if(height <= 0 || wallheight[screenx] > height)
		return;

	const int textureSpan = MAX(1, textureHeight*textureYScale/256);
	int ywcount = height;
	int yd = height;
	if(yd <= 0)
		yd = 100;

	const int topoffset = ywcount*((viewz + fixed(map->GetPlane(0).depth<<FRACBITS))>>8)/(32<<(FRACBITS-5));
	const int botoffset = ywcount*(viewz>>8)/(32<<(FRACBITS-5));
	int yoffs = (viewheight/2-topoffset-viewshift)*vbufPitch;
	if(yoffs < 0)
		yoffs = 0;
	yoffs += screenx;

	int yend = viewheight/2-botoffset-1-viewshift;
	int yw = textureSpan-1;
	while(yend >= viewheight)
	{
		ywcount -= textureYScale;
		while(ywcount <= 0)
		{
			ywcount += yd;
			--yw;
		}
		--yend;
	}
	yw %= textureSpan;
	if(yw < 0)
		yw += textureSpan;

	const int shade = LIGHT2SHADE(gLevelLight+r_extralight);
	const int tz = FixedMul(r_depthvisibility<<8, height);
	BYTE *curshades = &NormalLight.Maps[GETPALOOKUP(MAX(tz, MINZ), shade)<<8];
	const BYTE maskColor = GPalette.Remap[255];
	int yendoffs = yend*vbufPitch+screenx;
	while(yoffs <= yendoffs)
	{
		const bool opaque = opacity ? opacity[yw] != 0 : source[yw] != maskColor;
		const unsigned int depthIndex = yend*viewwidth+screenx;
		if(opaque && height >= maskedWallDepth[depthIndex])
		{
			vbuf[yendoffs] = ShadeWallColor(source[yw], curshades);
			maskedWallDepth[depthIndex] = height;
		}
		ywcount -= textureYScale;
		if(ywcount <= 0)
		{
			do
			{
				ywcount += yd;
				--yw;
			}
			while(ywcount <= 0);
			if(yw < 0)
				yw = textureSpan-1;
		}
		yendoffs -= vbufPitch;
		--yend;
	}
}

static void DrawMaskedWall(MapSpot spot, MapTile::Side side,
	int hitFirst, int hitLast)
{
	FTexture *texture = GetWallTexture(spot, side);
	if(!texture)
		return;

	fixed worldx1, worldy1, worldx2, worldy2;
	fixed nx1, ny1, nx2, ny2;
	fixed u1 = 0;
	fixed u2 = texture->GetWidth()<<FRACBITS;
	GetMaskedWallEndpoints(spot, side, worldx1, worldy1, worldx2, worldy2);
	TransformMaskedWallPoint(worldx1, worldy1, nx1, ny1);
	TransformMaskedWallPoint(worldx2, worldy2, nx2, ny2);
	if(!ClipMaskedWall(nx1, ny1, u1, nx2, ny2, u2))
		return;

	int screenx1 = centerx + int((int64_t(ny1)*scale)/nx1);
	int screenx2 = centerx + int((int64_t(ny2)*scale)/nx2);
	if(screenx1 == screenx2)
		return;
	if(screenx1 > screenx2)
	{
		swapvalues(screenx1, screenx2);
		swapvalues(nx1, nx2);
		swapvalues(u1, u2);
	}

	const int first = MAX(MAX(screenx1, hitFirst), 0);
	const int last = MIN(MIN(screenx2, hitLast), viewwidth-1);
	if(first > last)
		return;
	const int range = screenx2-screenx1;
	const int textureWidth = texture->GetWidth();
	const int textureHeight = texture->GetHeight();
	const int textureYScale = texture->yScale>>(FRACBITS-8);
	const bool slidingPlane =
		(spot->tile->offsetVertical && (side == MapTile::West || side == MapTile::East)) ||
		(spot->tile->offsetHorizontal && (side == MapTile::North || side == MapTile::South));
	for(int screenx = first;screenx <= last;++screenx)
	{
		const double fraction = double(screenx-screenx1)/range;
		const double inverseDepth = (1.0-fraction)/nx1+fraction/nx2;
		if(inverseDepth <= 0)
			continue;
		const fixed depth = fixed(1.0/inverseDepth);
		const double perspectiveU =
			(((1.0-fraction)*u1/nx1)+(fraction*u2/nx2))/inverseDepth;
		int column;
		if(slidingPlane)
		{
			const unsigned int intercept = MAX(0, MIN<int>(FRACUNIT-1,
				int(perspectiveU/textureWidth)));
			const unsigned int amount = spot->slideAmount[side];
			if(CheckSlidePass(spot->slideStyle, intercept, amount))
				continue;
			const int shifted = (intercept+SlideTextureOffset(spot->slideStyle,
				intercept, amount))&(FRACUNIT-1);
			column = int((int64_t(shifted)*textureWidth)>>FRACBITS);
		}
		else
		{
			column = MAX(0, MIN<int>(textureWidth-1,
				int(perspectiveU)>>FRACBITS));
		}
		const int height = (heightnumerator<<8)/depth;
		ScaleMaskedWallPost(texture->GetMaskedColumn(column),
			texture->GetColumnOpacity(column), screenx, height, textureHeight,
			textureYScale);
	}
}

static void AddMaskedWall(const MaskedWallHit &hit)
{
	if(visptr >= &vislist[MAXVISABLE-1] ||
		!IsMaskedWallPassSide(hit.spot, hit.side))
		return;
	const int height = MaskedWallHeight(hit.spot, hit.side);
	if(height <= 0)
		return;
	visptr->type = VIS_MaskedWall;
	visptr->actor = NULL;
	visptr->spot = hit.spot;
	visptr->side = hit.side;
	visptr->first = hit.first;
	visptr->last = hit.last;
	visptr->viewheight = height;
	++visptr;
}

void DrawScaleds (void)
{
	int      i,least,numvisable,height;

	visptr = &vislist[0];
	if(maskedWallHits.Size() > 0)
	{
		const unsigned int maskedWallPixels = viewwidth*viewheight;
		maskedWallDepth.Resize(maskedWallPixels);
		memset(&maskedWallDepth[0], 0,
			maskedWallPixels*sizeof(maskedWallDepth[0]));
		for(unsigned int i = 0;i < maskedWallHits.Size();++i)
			AddMaskedWall(maskedWallHits[i]);
	}

//
// place active objects
//
	for(AActor::Iterator iter = AActor::GetIterator();iter.Next();)
	{
		AActor *obj = iter;

		if (obj->sprite == SPR_NONE)
			continue;

		MapSpot spot = map->GetSpot(obj->tilex, obj->tiley, 0);
		MapSpot spots[8];
		spots[0] = spot->GetAdjacent(MapTile::East);
		spots[1] = spots[0] ? spots[0]->GetAdjacent(MapTile::North) : NULL;
		spots[2] = spot->GetAdjacent(MapTile::North);
		spots[3] = spots[2] ? spots[2]->GetAdjacent(MapTile::West) : NULL;
		spots[4] = spot->GetAdjacent(MapTile::West);
		spots[5] = spots[4] ? spots[4]->GetAdjacent(MapTile::South) : NULL;
		spots[6] = spot->GetAdjacent(MapTile::South);
		spots[7] = spots[6] ? spots[6]->GetAdjacent(MapTile::East) : NULL;

		//
		// could be in any of the nine surrounding tiles
		//
		if (spot->visible
			|| ( spots[0] && (spots[0]->visible && !spots[0]->tile) )
			|| ( spots[1] && (spots[1]->visible && !spots[1]->tile) )
			|| ( spots[2] && (spots[2]->visible && !spots[2]->tile) )
			|| ( spots[3] && (spots[3]->visible && !spots[3]->tile) )
			|| ( spots[4] && (spots[4]->visible && !spots[4]->tile) )
			|| ( spots[5] && (spots[5]->visible && !spots[5]->tile) )
			|| ( spots[6] && (spots[6]->visible && !spots[6]->tile) )
			|| ( spots[7] && (spots[7]->visible && !spots[7]->tile) ) )
		{
			TransformActor (obj);
			if (!obj->viewheight || (gamestate.victoryflag && obj == players[ConsolePlayer].mo))
				continue;                                               // too close or far away

			visptr->type = VIS_Actor;
			visptr->actor = obj;
			visptr->spot = NULL;
			visptr->viewheight = obj->viewheight;

			if (visptr < &vislist[MAXVISABLE-1])    // don't let it overflow
				visptr++;
		}
	}

//
// draw from back to front
//
	numvisable = (int) (visptr-&vislist[0]);

	if (!numvisable)
		return;                                                                 // no visable objects

	for (i = 0; i<numvisable; i++)
	{
		least = 0x7fffffff;
		for (visstep=&vislist[0] ; visstep<visptr ; visstep++)
		{
			height = visstep->viewheight;
			if (height < least)
			{
				least = height;
				farthest = visstep;
			}
		}
		//
		// draw farthest
		//
		if(farthest->type == VIS_MaskedWall)
			DrawMaskedWall(farthest->spot, farthest->side,
				farthest->first, farthest->last);
		else if(farthest->actor->flags & FL_BILLBOARD)
			Scale3DSprite(farthest->actor, farthest->actor->state, farthest->viewheight);
		else
			ScaleSprite(farthest->actor, farthest->actor->viewx, farthest->actor->state, farthest->viewheight);

		farthest->viewheight = 0x7fffffff;
	}
}

//==========================================================================

/*
==============
=
= DrawPlayerWeapon
=
= Draw the player's hands
=
==============
*/

void DrawPlayerWeapon (void)
{
	static const int corridor7Bases[] = { 746, 786, 754, 762, 770, 778, 794, 802 };
	static const int corridor7X[16] =
		{ 0, 1, 2, 3, 4, 3, 2, 1, 0, -1, -2, -3, -4, -3, -2, -1 };
	static int corridor7Phase[MAXPLAYERS] = { 0 };
	static int corridor7LastTime[MAXPLAYERS] = { 0 };

	for(unsigned int i = 0;i < player_t::NUM_PSPRITES;++i)
	{
		if(!players[ConsolePlayer].psprite[i].frame)
			return;

		fixed xoffset, yoffset;
		players[ConsolePlayer].BobWeapon(&xoffset, &yoffset);

		const Frame *frame = players[ConsolePlayer].psprite[i].frame;
		unsigned int spriteOverride = SPR_NONE;
		if(IWad::CheckGameFilter("Corridor7"))
		{
			bool readyFrame = false;
			int readyBase = 0;
			for(unsigned int weapon = 0;
				weapon < sizeof(corridor7Bases)/sizeof(corridor7Bases[0]);++weapon)
			{
				char readyName[5];
				mysnprintf(readyName, sizeof(readyName), "C%03d",
					corridor7Bases[weapon]+7);
				if(frame->spriteInf == R_GetSprite(readyName))
				{
					readyFrame = true;
					readyBase = corridor7Bases[weapon];
					break;
				}
			}
			if(readyFrame)
			{
				if(corridor7LastTime[ConsolePlayer] != gamestate.TimeCount)
				{
					TicCmd_t &cmd = control[ConsolePlayer];
					if(cmd.controly == 0)
						corridor7Phase[ConsolePlayer] = 0;
					else
					{
						const bool running =
							(!alwaysrun && cmd.buttonstate[bt_run]) ||
							(alwaysrun && !cmd.buttonstate[bt_run]);
						corridor7Phase[ConsolePlayer] =
							(corridor7Phase[ConsolePlayer]+(running ? 2 : 1))&15;
					}
					corridor7LastTime[ConsolePlayer] = gamestate.TimeCount;
				}
				const int phase = corridor7Phase[ConsolePlayer]&15;
				// Each eight-page weapon family has four firing pages, one moving
				// pose at base+4, two unused transition pages, and its stationary
				// pose at base+7. Alternate only the two actual movement poses;
				// indexing through base+5/base+6 makes the gun visibly stutter.
				xoffset += corridor7X[phase]<<FRACBITS;
				char poseName[5];
				mysnprintf(poseName, sizeof(poseName), "C%03d",
					readyBase+((phase&4) ? 4 : 7));
				spriteOverride = R_GetSprite(poseName);
			}
		}

		R_DrawPlayerSprite(players[ConsolePlayer].ReadyWeapon, frame,
			players[ConsolePlayer].psprite[i].sx+xoffset,
			players[ConsolePlayer].psprite[i].sy+yoffset, spriteOverride);
	}
}

//==========================================================================

void AsmRefresh()
{
	static word xspot[2],yspot[2];
	int32_t xstep=0,ystep=0;
	longword xpartial=0,ypartial=0;
	MapSpot focalspot = map->GetSpot(focaltx, focalty, 0);
	bool playerInPushwallBackTile = focalspot->pushAmount != 0;

	for(pixx=0;pixx<viewwidth;pixx++)
	{
		short angl=midangle+pixelangle[pixx];
		if(angl<0) angl+=FINEANGLES;
		if(angl>=ANG360) angl-=FINEANGLES;
		if(angl<ANG90)
		{
			xtilestep=1;
			ytilestep=-1;
			xstep=finetangent[ANG90-1-angl];
			ystep=-finetangent[angl];
			xpartial=xpartialup;
			ypartial=ypartialdown;
		}
		else if(angl<ANG180)
		{
			xtilestep=-1;
			ytilestep=-1;
			xstep=-finetangent[angl-ANG90];
			ystep=-finetangent[ANG180-1-angl];
			xpartial=xpartialdown;
			ypartial=ypartialdown;
		}
		else if(angl<ANG270)
		{
			xtilestep=-1;
			ytilestep=1;
			xstep=-finetangent[ANG270-1-angl];
			ystep=finetangent[angl-ANG180];
			xpartial=xpartialdown;
			ypartial=ypartialup;
		}
		else if(angl<ANG360)
		{
			xtilestep=1;
			ytilestep=1;
			xstep=finetangent[angl-ANG270];
			ystep=finetangent[ANG360-1-angl];
			xpartial=xpartialup;
			ypartial=ypartialup;
		}
		yintercept=FixedMul(ystep,xpartial)+viewy;
		xtile=focaltx+xtilestep;
		xspot[0]=xtile;
		xspot[1]=yintercept>>16;
		xintercept=FixedMul(xstep,ypartial)+viewx;
		ytile=focalty+ytilestep;
		yspot[0]=xintercept>>16;
		yspot[1]=ytile;
		texdelta=0;

		// Special treatment when player is in back tile of pushwall
		if(playerInPushwallBackTile)
		{
			if(focalspot->pushReceptor)
				focalspot = focalspot->pushReceptor;

			if((focalspot->pushDirection == MapTile::East && xtilestep == 1) ||
				(focalspot->pushDirection == MapTile::West && xtilestep == -1))
			{
				int32_t yintbuf = yintercept - ytilestep*(abs(ystep * signed(64 - focalspot->pushAmount)) >> 6);
				if((yintbuf >> 16) == focalty)   // ray hits pushwall back?
				{
					if(focalspot->pushDirection == MapTile::East)
						xintercept = (focaltx << TILESHIFT) + (focalspot->pushAmount << 10);
					else
						xintercept = (focaltx << TILESHIFT) - TILEGLOBAL + ((64 - focalspot->pushAmount) << 10);
					yintercept = yintbuf;
					ytile = (short) (yintercept >> TILESHIFT);
					tilehit = focalspot;
					HitVertWall();
					continue;
				}
			}
			else if((focalspot->pushDirection == MapTile::South && ytilestep == 1) ||
				(focalspot->pushDirection == MapTile::North && ytilestep == -1))
			{
				int32_t xintbuf = xintercept - xtilestep*(abs(xstep * signed(64 - focalspot->pushAmount)) >> 6);
				if((xintbuf >> 16) == focaltx)   // ray hits pushwall back?
				{
					xintercept = xintbuf;
					if(focalspot->pushDirection == MapTile::South)
						yintercept = (focalty << TILESHIFT) + (focalspot->pushAmount << 10);
					else
						yintercept = (focalty << TILESHIFT) - TILEGLOBAL + ((64 - focalspot->pushAmount) << 10);
					xtile = (short) (xintercept >> TILESHIFT);
					tilehit = focalspot;
					HitHorizWall();
					continue;
				}
			}
		}

		do
		{
			if(ytilestep==-1 && (yintercept>>16)<=ytile) goto horizentry;
			if(ytilestep==1 && (yintercept>>16)>=ytile) goto horizentry;
vertentry:

			if((uint32_t)yintercept>mapheight*65536-1 || (word)xtile>=mapwidth)
			{
				if(xtile<0) xintercept=0, xtile=0;
				else if((unsigned)xtile>=mapwidth) xintercept=mapwidth<<TILESHIFT, xtile=mapwidth-1;
				else xtile=(short) (xintercept >> TILESHIFT);
				if(yintercept<0) yintercept=0, ytile=0;
				else if((unsigned)yintercept>=(mapheight<<TILESHIFT)) yintercept=mapheight<<TILESHIFT, ytile=mapheight-1;
				yspot[0]=0xffff;
				tilehit=0;
				HitHorizBorder();
				break;
			}
			if(xspot[0]>=mapwidth || xspot[1]>=mapheight) break;
			tilehit=map->GetSpot(xspot[0], xspot[1], 0);
			if(tilehit && tilehit->tile)
			{
				DetermineHitDir(true);
				if(IsMaskedWallPassSide(tilehit, hitdir))
				{
					if(IsMaskedWallRenderSide(tilehit, hitdir))
						RecordMaskedWallHit(tilehit, hitdir, pixx);
					goto passvert;
				}
				if(tilehit->tile->offsetVertical)
				{
					int32_t yintbuf=yintercept+(ystep>>1);
					if((yintbuf>>16)!=(yintercept>>16))
						goto passvert;
					if(CheckSlidePass(tilehit->slideStyle, (word)yintbuf, tilehit->slideAmount[hitdir]))
						goto passvert;
					yintercept=yintbuf;
					xintercept=(xtile<<TILESHIFT)|0x8000;
					ytile = (short) (yintercept >> TILESHIFT);
					HitVertWall();
				}
				else
				{
					bool isPushwall = tilehit->pushAmount != 0 || tilehit->pushReceptor;
					if(tilehit->pushReceptor)
						tilehit = tilehit->pushReceptor;

					if(isPushwall)
					{
						if(tilehit->pushDirection==MapTile::West || tilehit->pushDirection==MapTile::East)
						{
							int32_t yintbuf;
							int pwallposnorm;
							int pwallposinv;
							if(tilehit->pushDirection==MapTile::West)
							{
								pwallposnorm = 64-tilehit->pushAmount;
								pwallposinv = tilehit->pushAmount;
							}
							else
							{
								pwallposnorm = tilehit->pushAmount;
								pwallposinv = 64-tilehit->pushAmount;
							}
							if((tilehit->pushDirection==MapTile::East && xtile==(signed)tilehit->GetX() && ((uint32_t)yintercept>>16)==tilehit->GetY())
								|| (tilehit->pushDirection==MapTile::West && !(xtile==(signed)tilehit->GetX() && ((uint32_t)yintercept>>16)==tilehit->GetY())))
							{
								yintbuf=yintercept+((ystep*pwallposnorm)>>6);
								if((yintbuf>>16)!=(yintercept>>16))
									goto passvert;

								xintercept=(xtile<<TILESHIFT)+TILEGLOBAL-(pwallposinv<<10);
								yintercept=yintbuf;
								ytile = (short) (yintercept >> TILESHIFT);
								HitVertWall();
							}
							else
							{
								yintbuf=yintercept+((ystep*pwallposinv)>>6);
								if((yintbuf>>16)!=(yintercept>>16))
									goto passvert;

								xintercept=(xtile<<TILESHIFT)-(pwallposinv<<10);
								yintercept=yintbuf;
								ytile = (short) (yintercept >> TILESHIFT);
								HitVertWall();
							}
						}
						else
						{
							int pwallposi = tilehit->pushAmount;
							if(tilehit->pushDirection==MapTile::North) pwallposi = 64-tilehit->pushAmount;
							if((tilehit->pushDirection==MapTile::South && (word)yintercept<(pwallposi<<10))
								|| (tilehit->pushDirection==MapTile::North && (word)yintercept>(pwallposi<<10)))
							{
								if(((uint32_t)yintercept>>16)==tilehit->GetY() && xtile==(signed)tilehit->GetX())
								{
									if((tilehit->pushDirection==MapTile::South && (int32_t)((word)yintercept)+ystep<(pwallposi<<10))
										|| (tilehit->pushDirection==MapTile::North && (int32_t)((word)yintercept)+ystep>(pwallposi<<10)))
										goto passvert;

									if(tilehit->pushDirection==MapTile::South)
									{
										yintercept=(yintercept&0xffff0000)+(pwallposi<<10);
										xintercept=xintercept-((xstep*(64-pwallposi))>>6);
									}
									else
									{
										yintercept=(yintercept&0xffff0000)-TILEGLOBAL+(pwallposi<<10);
										xintercept=xintercept-((xstep*pwallposi)>>6);
									}
									xtile = (short) (xintercept >> TILESHIFT);
									HitHorizWall();
								}
								else
								{
									texdelta = -(pwallposi<<10);
									xintercept=xtile<<TILESHIFT;
									ytile = (short) (yintercept >> TILESHIFT);
									HitVertWall();
								}
							}
							else
							{
								if(((uint32_t)yintercept>>16)==tilehit->GetY() && xtile==(signed)tilehit->GetX())
								{
									texdelta = -(pwallposi<<10);
									xintercept=xtile<<TILESHIFT;
									ytile = (short) (yintercept >> TILESHIFT);
									HitVertWall();
								}
								else
								{
									if((tilehit->pushDirection==MapTile::South && (int32_t)((word)yintercept)+ystep>(pwallposi<<10))
										|| (tilehit->pushDirection==MapTile::North && (int32_t)((word)yintercept)+ystep<(pwallposi<<10)))
										goto passvert;

									if(tilehit->pushDirection==MapTile::South)
									{
										yintercept=(yintercept&0xffff0000)-TILEGLOBAL+(pwallposi<<10);
										xintercept=xintercept-((xstep*pwallposi)>>6);
									}
									else
									{
										yintercept=(yintercept&0xffff0000)+(pwallposi<<10);
										xintercept=xintercept-((xstep*(64-pwallposi))>>6);
									}
									xtile = (short) (xintercept >> TILESHIFT);
									HitHorizWall();
								}
							}
						}
					}
					else
					{
						xintercept=xtile<<TILESHIFT;
						ytile = (short) (yintercept >> TILESHIFT);
						HitVertWall();
					}
				}
				break;
			}
passvert:
			tilehit->visible=true;
			tilehit->amFlags |= AM_Visible;
			xtile+=xtilestep;
			yintercept+=ystep;
			xspot[0]=xtile;
			xspot[1]=yintercept>>16;
		}
		while(1);
		continue;

		do
		{
			if(xtilestep==-1 && (xintercept>>16)<=xtile) goto vertentry;
			if(xtilestep==1 && (xintercept>>16)>=xtile) goto vertentry;
horizentry:

			if((uint32_t)xintercept>mapwidth*65536-1 || (word)ytile>=mapheight)
			{
				if(ytile<0) yintercept=0, ytile=0;
				else if((unsigned)ytile>=mapheight) yintercept=mapheight<<TILESHIFT, ytile=mapheight-1;
				else ytile=(short) (yintercept >> TILESHIFT);
				if(xintercept<0) xintercept=0, xtile=0;
				else if((unsigned)xintercept>=(mapwidth<<TILESHIFT)) xintercept=mapwidth<<TILESHIFT, xtile=mapwidth-1;
				xspot[0]=0xffff;
				tilehit=0;
				HitVertBorder();
				break;
			}
			if(yspot[0]>=mapwidth || yspot[1]>=mapheight) break;
			tilehit=map->GetSpot(yspot[0], yspot[1], 0);
			if(tilehit && tilehit->tile)
			{
				DetermineHitDir(false);
				if(IsMaskedWallPassSide(tilehit, hitdir))
				{
					if(IsMaskedWallRenderSide(tilehit, hitdir))
						RecordMaskedWallHit(tilehit, hitdir, pixx);
					goto passhoriz;
				}
				if(tilehit->tile->offsetHorizontal)
				{
					int32_t xintbuf=xintercept+(xstep>>1);
					if((xintbuf>>16)!=(xintercept>>16))
						goto passhoriz;
					if(CheckSlidePass(tilehit->slideStyle, (word)xintbuf, tilehit->slideAmount[hitdir]))
						goto passhoriz;
					xintercept=xintbuf;
					yintercept=(ytile<<TILESHIFT)+0x8000;
					xtile = (short) (xintercept >> TILESHIFT);
					HitHorizWall();
				}
				else
				{
					bool isPushwall = tilehit->pushAmount != 0 || tilehit->pushReceptor;
					if(tilehit->pushReceptor)
						tilehit = tilehit->pushReceptor;

					if(isPushwall)
					{
						if(tilehit->pushDirection==MapTile::North || tilehit->pushDirection==MapTile::South)
						{
							int32_t xintbuf;
							int pwallposnorm;
							int pwallposinv;
							if(tilehit->pushDirection==MapTile::North)
							{
								pwallposnorm = 64-tilehit->pushAmount;
								pwallposinv = tilehit->pushAmount;
							}
							else
							{
								pwallposnorm = tilehit->pushAmount;
								pwallposinv = 64-tilehit->pushAmount;
							}
							if((tilehit->pushDirection == MapTile::South && ytile==(signed)tilehit->GetY() && ((uint32_t)xintercept>>16)==tilehit->GetX())
								|| (tilehit->pushDirection == MapTile::North && !(ytile==(signed)tilehit->GetY() && ((uint32_t)xintercept>>16)==tilehit->GetX())))
							{
								xintbuf=xintercept+((xstep*pwallposnorm)>>6);
								if((xintbuf>>16)!=(xintercept>>16))
									goto passhoriz;

								yintercept=(ytile<<TILESHIFT)+TILEGLOBAL-(pwallposinv<<10);
								xintercept=xintbuf;
								xtile = (short) (xintercept >> TILESHIFT);
								HitHorizWall();
							}
							else
							{
								xintbuf=xintercept+((xstep*pwallposinv)>>6);
								if((xintbuf>>16)!=(xintercept>>16))
									goto passhoriz;

								yintercept=(ytile<<TILESHIFT)-(pwallposinv<<10);
								xintercept=xintbuf;
								xtile = (short) (xintercept >> TILESHIFT);
								HitHorizWall();
							}
						}
						else
						{
							int pwallposi = tilehit->pushAmount;
							if(tilehit->pushDirection==MapTile::West) pwallposi = 64-tilehit->pushAmount;
							if((tilehit->pushDirection==MapTile::East && (word)xintercept<(pwallposi<<10))
								|| (tilehit->pushDirection==MapTile::West && (word)xintercept>(pwallposi<<10)))
							{
								if(((uint32_t)xintercept>>16)==tilehit->GetX() && ytile==(signed)tilehit->GetY())
								{
									if((tilehit->pushDirection==MapTile::East && (int32_t)((word)xintercept)+xstep<(pwallposi<<10))
										|| (tilehit->pushDirection==MapTile::West && (int32_t)((word)xintercept)+xstep>(pwallposi<<10)))
										goto passhoriz;

									if(tilehit->pushDirection==MapTile::East)
									{
										xintercept=(xintercept&0xffff0000)+(pwallposi<<10);
										yintercept=yintercept-((ystep*(64-pwallposi))>>6);
									}
									else
									{
										xintercept=(xintercept&0xffff0000)-TILEGLOBAL+(pwallposi<<10);
										yintercept=yintercept-((ystep*pwallposi)>>6);
									}
									ytile = (short) (yintercept >> TILESHIFT);
									HitVertWall();
								}
								else
								{
									texdelta = -(pwallposi<<10);
									yintercept=ytile<<TILESHIFT;
									xtile = (short) (xintercept >> TILESHIFT);
									HitHorizWall();
								}
							}
							else
							{
								if(((uint32_t)xintercept>>16)==tilehit->GetX() && ytile==(signed)tilehit->GetY())
								{
									texdelta = -(pwallposi<<10);
									yintercept=ytile<<TILESHIFT;
									xtile = (short) (xintercept >> TILESHIFT);
									HitHorizWall();
								}
								else
								{
									if((tilehit->pushDirection==MapTile::East && (int32_t)((word)xintercept)+xstep>(pwallposi<<10))
										|| (tilehit->pushDirection==MapTile::West && (int32_t)((word)xintercept)+xstep<(pwallposi<<10)))
										goto passhoriz;

									if(tilehit->pushDirection==MapTile::East)
									{
										xintercept=(xintercept&0xffff0000)-TILEGLOBAL+(pwallposi<<10);
										yintercept=yintercept-((ystep*pwallposi)>>6);
									}
									else
									{
										xintercept=(xintercept&0xffff0000)+(pwallposi<<10);
										yintercept=yintercept-((ystep*(64-pwallposi))>>6);
									}
									ytile = (short) (yintercept >> TILESHIFT);
									HitVertWall();
								}
							}
						}
					}
					else
					{
						yintercept=ytile<<TILESHIFT;
						xtile = (short) (xintercept >> TILESHIFT);
						HitHorizWall();
					}
				}
				break;
			}
passhoriz:
			tilehit->visible=true;
			tilehit->amFlags |= AM_Visible;
			ytile+=ytilestep;
			xintercept+=xstep;
			yspot[0]=xintercept>>16;
			yspot[1]=ytile;
		}
		while(1);
	}
}

/*
====================
=
= WallRefresh
=
====================
*/

void WallRefresh (void)
{
	xpartialdown = viewx&(TILEGLOBAL-1);
	xpartialup = TILEGLOBAL-xpartialdown;
	ypartialdown = viewy&(TILEGLOBAL-1);
	ypartialup = TILEGLOBAL-ypartialdown;

	min_wallheight = viewheight;
	lastside = -1;                  // the first pixel is on a new wall
	maskedWallHits.Clear();
	viewshift = FixedMul(focallengthy, finetangent[(ANGLE_180+players[ConsolePlayer].camera->pitch)>>ANGLETOFINESHIFT]);

	
	angle_t bobangle = ((gamestate.TimeCount<<13)/(20*TICRATE/35)) & FINEMASK;
	const fixed playerMovebob = players[ConsolePlayer].mo->GetClass()->Meta.GetMetaFixed(APMETA_MoveBob);
	fixed curbob = gamestate.victoryflag ? 0 : FixedMul(FixedMul(players[ConsolePlayer].bob, playerMovebob)>>1, finesine[bobangle]);

	viewz = curbob - players[ConsolePlayer].mo->viewheight;

	AsmRefresh();
	ScalePost ();                   // no more optimization on last post
}

void CalcViewVariables()
{
	viewangle = players[ConsolePlayer].camera->angle;
	midangle = viewangle>>ANGLETOFINESHIFT;
	viewsin = finesine[viewangle>>ANGLETOFINESHIFT];
	viewcos = finecosine[viewangle>>ANGLETOFINESHIFT];
	viewx = players[ConsolePlayer].camera->x - FixedMul(focallength,viewcos);
	viewy = players[ConsolePlayer].camera->y + FixedMul(focallength,viewsin);

	focaltx = (short)(viewx>>TILESHIFT);
	focalty = (short)(viewy>>TILESHIFT);

	viewtx = (short)(players[ConsolePlayer].camera->x >> TILESHIFT);
	viewty = (short)(players[ConsolePlayer].camera->y >> TILESHIFT);

	if(players[ConsolePlayer].camera->player)
		r_extralight = players[ConsolePlayer].camera->player->extralight << 3;
	else
		r_extralight = 0;
}

static TUniquePtr<FFader> fizzlein;
void ThreeDStartFadeIn()
{
	// For multiplayer disable fade in since players need to be back in the
	// action immediately after respawning.
	if(Net::InitVars.mode != Net::MODE_SinglePlayer)
		return;

	switch(gameinfo.DeathTransition)
	{
		case GameInfo::TRANSITION_Fizzle:
		{
			FFizzleFader *fader = new FFizzleFader(0, 0, screenWidth, screenHeight, 20, true);
			fader->CaptureFrame();
			fizzlein.Reset(fader);
			break;
		}
		case GameInfo::TRANSITION_Fade:
			fizzlein.Reset(new FBlendFader(255, 0, 0, 0, 0, 24));
			break;
	}
}

//==========================================================================

void R_RenderView()
{
	CalcViewVariables();

//
// follow the walls from there to the right, drawing as we go
//
#if 0 // USE_STARSKY
	if(GetFeatureFlags() & FF_STARSKY)
		DrawStarSky(vbuf, vbufPitch);
#endif

	WallRefresh ();

	DrawParallax(vbuf, vbufPitch);
#if 0 // USE_CLOUDSKY
	if(GetFeatureFlags() & FF_CLOUDSKY)
		DrawClouds(vbuf, vbufPitch, min_wallheight);
#endif
	DrawFloorAndCeiling(vbuf, vbufPitch, min_wallheight);

//
// draw all the scaled images
//
	DrawScaleds();                  // draw scaled stuff

#if 0 // USE_RAIN
	if(GetFeatureFlags() & FF_RAIN)
		DrawRain(vbuf, vbufPitch);
#endif
#if 0 // USE_SNOW
	if(GetFeatureFlags() & FF_SNOW)
		DrawSnow(vbuf, vbufPitch);
#endif

	DrawPlayerWeapon ();    // draw player's hands

	if((control[ConsolePlayer].buttonstate[bt_showstatusbar] || control[ConsolePlayer].buttonheld[bt_showstatusbar]) && viewsize == 21)
	{
		ingame = false;
		StatusBar->DrawStatusBar();
		ingame = true;
	}

	// Always mark the current spot as visible in the automap
	map->GetSpot(players[ConsolePlayer].mo->tilex, players[ConsolePlayer].mo->tiley, 0)->amFlags |= AM_Visible;
}

/*
========================
=
= ThreeDRefresh
=
========================
*/



void    ThreeDRefresh (void)
{
	// Ensure we have a valid camera
	if(players[ConsolePlayer].camera == NULL)
		players[ConsolePlayer].camera = players[ConsolePlayer].mo;

//
// clear out the traced array
//
	map->ClearVisibility();

	vbuf = VL_LockSurface();
	if(vbuf == NULL) return;

	vbuf += screenofs;
	vbufPitch = SCREENPITCH;
	if(IWad::CheckGameFilter("Corridor7"))
	{
		// Masked walls intentionally leave keyed pixels untouched. Start every
		// 3D frame from a known background so the loading plate (or an earlier
		// camera view) can never survive through glass on the first frame.
		for(int y = 0;y < viewheight;++y)
			memset(vbuf+y*vbufPitch, GPalette.Remap[0], viewwidth);
	}

	R_RenderView();

	VL_UnlockSurface();
	vbuf = NULL;

	if(player_t *player = players[ConsolePlayer].camera->player)
	{
		if(player->ScreenFader)
			player->ScreenFader->Update();
	}

//
// show screen and time last cycle
//
	if (fizzlein)
	{
		while(!fizzlein->Update())
			VH_UpdateScreen();
		VH_UpdateScreen();
		fizzlein.Reset();

		// don't make a big tic count
		ResetTimeCount();
	}
	else if (fpscounter)
	{
		FString fpsDisplay;
		fpsDisplay.Format("%2u fps", fps);

		word x = 0;
		word y = 0;
		word width, height;
		VW_MeasurePropString(ConFont, fpsDisplay, width, height);
		MenuToRealCoords(x, y, width, height, MENU_TOP);
		VWB_Clear(GPalette.BlackIndex, x, y, x+width+1, y+height+1);
		px = 0;
		py = 0;
		pa = MENU_TOP;
		VWB_DrawPropString(ConFont, fpsDisplay, CR_WHITE);
		pa = MENU_CENTER;
	}

	if (fpscounter)
	{
		fps_frames++;
		fps_time+=tics;

		if(fps_time>35)
		{
			fps_time-=35;
			fps=fps_frames<<1;
			fps_frames=0;
		}
	}
}
