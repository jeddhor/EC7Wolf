// ===========================================================================
//
// r_dynamicwalls.cpp - renderer-owned dynamic-wall snapshots + interpolation.
//
// Renderer redesign Phase 7. See r_dynamicwalls.h for the model. Doors are
// keyed by their (stable) map cell; pushwalls are keyed by their thinker so the
// stored world position stays continuous as the wall transfers between cells.
//
// ===========================================================================

#include "render/r_dynamicwalls.h"
#include "wl_def.h"
#include "id_ca.h"
#include "gamemap.h"
#include "thinker.h"
#include "c_cvars.h"

namespace
{
	// MapTile::Side -> unit step in the world builder's tile space. This MUST match
	// GameMap::GetAdjacent (gamemap.cpp), which is the engine's definition of where
	// a side points: South is +Y and North is -Y. Getting the Y pair backwards makes
	// a pushwall on the N/S axis animate toward the player instead of away, then snap
	// to the right cell when the thinker finishes and the map data takes over (the
	// E/W axis is unaffected, which is why only some secret walls looked wrong).
	void SideDelta(int side, int &dx, int &dy)
	{
		switch(side)
		{
			case MapTile::East:  dx =  1; dy =  0; break;
			case MapTile::North: dx =  0; dy = -1; break;
			case MapTile::West:  dx = -1; dy =  0; break;
			default:             dx =  0; dy =  1; break;	// South
		}
	}

	// A door's slide amount lives on the axis it opens along: a vertical door
	// (offsetVertical) opens East/West -> slideAmount[East]; a horizontal door
	// opens North/South -> slideAmount[North]. The opposite-side entry mirrors it.
	unsigned int LiveDoorAmount(MapSpot spot)
	{
		const int axis = spot->tile->offsetVertical ? MapTile::East : MapTile::North;
		return spot->slideAmount[axis];
	}

	// World-space base (min) corner of a moving pushwall block, in tile units:
	// its origin cell shifted by pushAmount/64 of a tile toward pushDirection.
	void PushBase(MapSpot spot, float &x, float &y)
	{
		int dx, dy;
		SideDelta(spot->pushDirection, dx, dy);
		const float f = (float)spot->pushAmount / 64.0f;
		x = (float)spot->GetX() + dx * f;
		y = (float)spot->GetY() + dy * f;
	}

	struct DoorSnap
	{
		unsigned int prevAmt, curAmt;
		int          style;
		bool         valid;
		DoorSnap() : prevAmt(0), curAmt(0), style(0), valid(false) {}
	};

	struct PushSnap
	{
		float      prevX, prevY, curX, curY;
		int        dir;
		FTextureID tex[4];
		bool       valid;
		PushSnap() : prevX(0), prevY(0), curX(0), curY(0), dir(0), valid(false) {}
	};

	TMap<MapSpot, DoorSnap>  g_doors;
	TMap<Thinker *, PushSnap> g_pushes;

	inline float LerpF(float a, float b, float alpha)
	{
		return a + (b - a) * alpha;
	}
}

namespace DynamicWalls
{

bool IsDoorCell(MapSpot spot)
{
	return spot && spot->tile &&
		(spot->tile->offsetVertical || spot->tile->offsetHorizontal);
}

bool IsPushwallCell(MapSpot spot)
{
	// A see-through masked wall is never a moving block. C7 force-field doors carry
	// a C7AnimatedWall thinker while deactivating; without this guard the thinker
	// test below would also class them as a pushwall, so BuildDynamic would draw the
	// full 4-face block on top of the masked center pane for the ~0.5s transition.
	if(!spot || !spot->tile || IsDoorCell(spot) || IsMaskedWallCell(spot))
		return false;
	// A wall in motion: the origin carries a thinker and/or a nonzero push
	// amount; the destination carries a pushReceptor back to the origin.
	return spot->thinker != NULL || spot->pushAmount != 0 ||
		spot->pushReceptor != NULL;
}

bool IsMaskedWallCell(MapSpot spot)
{
	// Color-keyed / see-through tiles (maskedWallType is derived from index-255
	// art; renderMasked is an explicit map flag). Doors slide as leaves in the
	// dynamic mesh, so they are excluded here even though they too are masked.
	if(!spot || !spot->tile || IsDoorCell(spot))
		return false;
	return spot->maskedWallType != 0 || spot->tile->renderMasked;
}

bool IsPushwallOrigin(MapSpot spot)
{
	// The thinker always rides the current origin cell, even across transfers.
	// A nonzero pushAmount also marks the origin (used by the capture-time
	// synthetic pushwall, which has no thinker); the destination cell is
	// identified by pushReceptor instead and is never treated as an origin.
	return spot && spot->tile && !IsDoorCell(spot) && !IsMaskedWallCell(spot) &&
		spot->pushReceptor == NULL &&
		(spot->thinker != NULL || spot->pushAmount != 0);
}

void Reset()
{
	g_doors.Clear();
	g_pushes.Clear();
}

void BeginTic()
{
	if(!r_interpolate || !r_interpolate_dynamicwalls)
		return;

	{
		TMapIterator<MapSpot, DoorSnap> it(g_doors);
		TMap<MapSpot, DoorSnap>::Pair *p;
		while(it.NextPair(p))
			p->Value.prevAmt = p->Value.curAmt;
	}
	{
		TMapIterator<Thinker *, PushSnap> it(g_pushes);
		TMap<Thinker *, PushSnap>::Pair *p;
		while(it.NextPair(p))
		{
			p->Value.prevX = p->Value.curX;
			p->Value.prevY = p->Value.curY;
		}
	}
}

void EndTic()
{
	if(!r_interpolate || !r_interpolate_dynamicwalls || map == NULL)
		return;

	const GameMap::Header &hdr = map->GetHeader();
	for(unsigned int y = 0; y < hdr.height; ++y)
	for(unsigned int x = 0; x < hdr.width; ++x)
	{
		MapSpot spot = map->GetSpot(x, y, 0);

		if(IsDoorCell(spot))
		{
			DoorSnap &s = g_doors[spot];
			const unsigned int amt = LiveDoorAmount(spot);
			s.style = spot->slideStyle;
			s.curAmt = amt;
			if(!s.valid)			// first sighting: render statically this tic
			{
				s.prevAmt = amt;
				s.valid = true;
			}
		}
		else if(IsPushwallOrigin(spot))
		{
			Thinker *id = spot->thinker;
			PushSnap &s = g_pushes[id];
			float bx, by;
			PushBase(spot, bx, by);
			s.curX = bx;
			s.curY = by;
			s.dir = spot->pushDirection;
			for(int i = 0; i < 4; ++i)
				s.tex[i] = spot->texture[i];
			if(!s.valid)
			{
				s.prevX = bx;
				s.prevY = by;
				s.valid = true;
			}
		}
	}
}

void GetRender(float alpha, TArray<DoorRender> &doors, TArray<PushRender> &pushes)
{
	doors.Clear();
	pushes.Clear();
	if(map == NULL)
		return;

	const bool interp = r_interpolate && r_interpolate_dynamicwalls;
	const GameMap::Header &hdr = map->GetHeader();
	for(unsigned int y = 0; y < hdr.height; ++y)
	for(unsigned int x = 0; x < hdr.width; ++x)
	{
		MapSpot spot = map->GetSpot(x, y, 0);

		if(IsDoorCell(spot))
		{
			DoorRender d;
			d.spot = spot;
			d.style = spot->slideStyle;
			DoorSnap *s = interp ? g_doors.CheckKey(spot) : NULL;
			if(s && s->valid)
				d.amount = LerpF((float)s->prevAmt, (float)s->curAmt, alpha);
			else
				d.amount = (float)LiveDoorAmount(spot);
			doors.Push(d);
		}
		else if(IsPushwallOrigin(spot))
		{
			PushRender pr;
			pr.dir = spot->pushDirection;
			for(int i = 0; i < 4; ++i)
				pr.tex[i] = spot->texture[i];

			Thinker *id = spot->thinker;
			PushSnap *s = interp ? g_pushes.CheckKey(id) : NULL;
			if(s && s->valid)
			{
				pr.x = LerpF(s->prevX, s->curX, alpha);
				pr.y = LerpF(s->prevY, s->curY, alpha);
			}
			else
				PushBase(spot, pr.x, pr.y);
			pushes.Push(pr);
		}
	}
}

} // namespace DynamicWalls
