/*
** g_traversal.cpp
**
** See g_traversal.h. This is the geometry TryMove used to hold inline; TryMove
** now calls it and adds the three things only a real move may do.
*/

#include "g_traversal.h"
#include "lnspec.h"
#include "actor.h"
#include "wl_def.h"
#include "wl_agent.h"
#include "gamemap.h"
#include "id_ca.h"
#include "thingdef/thingdef.h"
#include "wl_iwad.h"

namespace Traversal {

bool CheckPositionAt(const Body &body, fixed x, fixed y, const Hooks *hooks)
{
	if(map == NULL)
		return false;

	const fixed radius = body.radius;

	// Off the edge is not a place a body can be. noclip lets a player leave
	// the walls but not the map, and a navigator has no business routing
	// through either.
	if(x - radius < 0 || y - radius < 0 ||
		x + radius >= (((int32_t)map->GetHeader().width)<<TILESHIFT) ||
		y + radius >= (((int32_t)map->GetHeader().height)<<TILESHIFT))
		return false;

	const int xl = (x - radius)>>TILESHIFT;
	const int yl = (y - radius)>>TILESHIFT;
	const int xh = (x + radius)>>TILESHIFT;
	const int yh = (y + radius)>>TILESHIFT;

	//
	// solid walls
	//
	for(int ty = yl;ty <= yh;++ty)
	{
		for(int tx = xl;tx <= xh;++tx)
		{
			const bool checkLines[4] =
			{
				(x + radius) > ((tx+1)<<TILESHIFT),
				(y - radius) < (ty<<TILESHIFT),
				(x - radius) < (tx<<TILESHIFT),
				(y + radius) > ((ty+1)<<TILESHIFT)
			};
			MapSpot spot = map->GetSpot(tx, ty, 0);
			if(!spot->tile)
				continue;

			// Pushwall backs: a wall part way through its travel blocks up to
			// where it has got to.
			if(spot->pushAmount != 0)
			{
				switch(spot->pushDirection)
				{
					case MapTile::North:
						if(y - radius <= static_cast<fixed>((ty<<TILESHIFT)+((63-spot->pushAmount)<<10)))
							return false;
						break;
					case MapTile::West:
						if(x - radius <= static_cast<fixed>((tx<<TILESHIFT)+((63-spot->pushAmount)<<10)))
							return false;
						break;
					case MapTile::East:
						if(x + radius >= static_cast<fixed>((tx<<TILESHIFT)+(spot->pushAmount<<10)))
							return false;
						break;
					case MapTile::South:
						if(y + radius >= static_cast<fixed>((ty<<TILESHIFT)+(spot->pushAmount<<10)))
							return false;
						break;
				}
				continue;
			}

			for(unsigned short i = 0;i < 4;++i)
			{
				if(spot->sideSolid[i] && spot->slideAmount[i] != 0xffff && checkLines[i])
				{
					// A door this body is planning to open, on a face that
					// actually opens. Nothing is written; the question is
					// simply asked of the state that will exist.
					if(body.openDoor == spot && (body.openDoorSides & (1<<i)))
						continue;

					// Whatever the caller wants to do about being blocked --
					// Corridor 7 zaps a player leaning on wall IDs 6 and 14 --
					// happens through the hook, not here. A question has no
					// business damaging anybody.
					if(hooks != NULL && hooks->onWallBlocked != NULL)
						hooks->onWallBlocked(hooks->context, spot);
					return false;
				}
			}
		}
	}

	//
	// actors
	//
	bool blocked = false;
	for(AActor::Iterator iter = AActor::GetIterator().Next();iter;)
	{
		// Awkward on purpose: an overlap hook can destroy the actor, so the
		// iterator advances before anything is called.
		AActor *check = iter;
		iter.Next();

		if(check == body.ignore)
			continue;

		// Players clip through each other in this game.
		if(check->player && body.isPlayer)
			continue;

		const fixed r = check->radius + radius;
		if(check->flags & FL_SOLID)
		{
			if(abs(x - check->x) > r || abs(y - check->y) > r)
				continue;
			// Not an early return: the caller's overlap hook still wants to
			// hear about everything else it is standing in, which is how
			// TryMove has always behaved.
			blocked = true;
		}
		else
		{
			if(abs(x - check->x) <= r && abs(y - check->y) <= r)
			{
				if(hooks != NULL && hooks->onOverlap != NULL)
					hooks->onOverlap(hooks->context, check);
			}
		}
	}

	return !blocked;
}

bool CanOccupyTile(const Body &body, unsigned int tileX, unsigned int tileY)
{
	if(map == NULL)
		return false;
	// A tile with a wall in it is not somewhere to stand, and the side checks
	// alone will not say so: they ask whether the body crosses one of the
	// tile's edges, and a body sitting in the middle of a wall tile crosses
	// none of them. Movement never reaches that state because a pawn cannot
	// get inside a wall in the first place; a query asked about every cell in
	// the map reaches it four thousand times.
	MapSpot spot = map->GetSpot(tileX, tileY, 0);
	if(spot == NULL || spot->sector == NULL)
		return false;
	if(spot->tile != NULL)
		return false;

	const fixed x = (fixed)((tileX<<TILESHIFT) + (1<<(TILESHIFT-1)));
	const fixed y = (fixed)((tileY<<TILESHIFT) + (1<<(TILESHIFT-1)));
	return CheckPositionAt(body, x, y, NULL);
}

bool CanStepBetweenTiles(const Body &body, unsigned int fromX, unsigned int fromY,
	unsigned int toX, unsigned int toY)
{
	if(!CanOccupyTile(body, fromX, fromY) || !CanOccupyTile(body, toX, toY))
		return false;

	const fixed halfTile = (fixed)(1<<(TILESHIFT-1));
	const fixed ax = (fixed)((fromX<<TILESHIFT)) + halfTile;
	const fixed ay = (fixed)((fromY<<TILESHIFT)) + halfTile;
	const fixed bx = (fixed)((toX<<TILESHIFT)) + halfTile;
	const fixed by = (fixed)((toY<<TILESHIFT)) + halfTile;

	// Sampled along the line, because standing in both ends says nothing about
	// the middle: a body of radius 22 in a 64-unit tile fits in two rooms and
	// not in the doorway between them. Eight samples puts one every eight
	// units over a single tile step, which is a third of the body's width.
	const unsigned int Samples = 8;
	for(unsigned int i = 1;i < Samples;++i)
	{
		const fixed x = ax + (fixed)(((int64_t)(bx - ax)*i)/Samples);
		const fixed y = ay + (fixed)(((int64_t)(by - ay)*i)/Samples);
		if(!CheckPositionAt(body, x, y, NULL))
			return false;
	}
	return true;
}

bool ContactDamageWallAt(unsigned int tileX, unsigned int tileY)
{
	if(map == NULL)
		return false;
	MapSpot spot = map->GetSpot(tileX, tileY, 0);
	if(spot == NULL || spot->tile == NULL)
		return false;
	// The same two IDs the movement path zaps on, read the same way, so the
	// planner and the damage cannot disagree about which walls are live.
	return spot->corridor7WallID == 6 || spot->corridor7WallID == 14;
}

TransporterInfo TransporterAt(unsigned int tileX, unsigned int tileY)
{
	enum { TELEPORT_NoStop = 1 };

	TransporterInfo info;
	if(map == NULL)
		return info;

	MapSpot spot = map->GetSpot(tileX, tileY, 0);
	if(spot == NULL)
		return info;

	for(unsigned int i = 0;i < spot->triggers.Size();++i)
	{
		const MapTrigger &trig = spot->triggers[i];
		// Crossed, not used: these are floor cells a player walks over. A
		// transporter that had to be operated would be a different protocol.
		if(trig.action != Specials::Teleport_Relative || !trig.playerCross)
			continue;

		MapSpot dest = NULL;
		while((dest = map->GetSpotByTag(trig.arg[0], dest)))
		{
			info.destX.Push((uint16_t)dest->GetX());
			info.destY.Push((uint16_t)dest->GetY());
		}
		if(info.destX.Size() == 0)
			continue;			// a tag nothing answers to

		info.exists = true;
		info.freezes = (trig.arg[2] & TELEPORT_NoStop) == 0;
		break;
	}

	return info;
}

DoorInfo DoorAt(unsigned int tileX, unsigned int tileY)
{
	DoorInfo info;
	if(map == NULL)
		return info;

	MapSpot spot = map->GetSpot(tileX, tileY, 0);
	if(spot == NULL || spot->tile == NULL)
		return info;

	for(unsigned int i = 0;i < spot->triggers.Size();++i)
	{
		const MapTrigger &trig = spot->triggers[i];
		if(trig.action != Specials::Door_Open || !trig.playerUse)
			continue;
		// A trigger with a tag operates doors somewhere else: that is a
		// switch, and a switch is a different edge type with a different
		// protocol. Only a door that opens itself is a door here.
		if(trig.arg[0] != 0)
			continue;

		info.exists = true;
		// Whatever key the trigger demands, recorded and not acted on. Which
		// keys a bot is carrying changes during a match; the graph does not.
		info.lock = trig.arg[3];

		// EVDoor slides sides `direction` and `direction+2` together, and
		// Side is East, North, West, South -- so bit 0 of arg[4] picks the
		// axis, and the two faces that open are the ones on it.
		const int axis = trig.arg[4] & 1;
		info.passable[axis] = true;
		info.passable[axis + 2] = true;
		break;
	}

	return info;
}

// Fill in the open-door rule for whichever of these cells has a door in it.
// Returns false when a cell has a door this body must not plan through.
static bool PlanningBody(const Body &in, Body &out, unsigned int tileX,
	unsigned int tileY)
{
	out = in;
	const DoorInfo info = DoorAt(tileX, tileY);
	if(!info.exists)
		return true;

	out.openDoor = map->GetSpot(tileX, tileY, 0);
	out.openDoorSides = 0;
	for(unsigned int i = 0;i < 4;++i)
	{
		if(info.passable[i])
			out.openDoorSides |= (BYTE)(1<<i);
	}
	return out.openDoorSides != 0;
}

bool CanOccupyTileOrDoor(const Body &body, unsigned int tileX, unsigned int tileY)
{
	if(map == NULL)
		return false;
	MapSpot spot = map->GetSpot(tileX, tileY, 0);
	if(spot == NULL || spot->sector == NULL)
		return false;

	// The wall rejection in CanOccupyTile is what refuses a door cell, and it
	// refuses it for the right reason: a closed door is a wall. Ask the same
	// question of the open state instead.
	if(spot->tile != NULL)
	{
		// An ordinary wall, and it stays a wall. Without this the centre of
		// every solid cell answers yes -- a body of radius 22 in a 64-unit
		// tile reaches none of that tile's own faces, so there is nothing for
		// the position check to collide with. That mistake turns a 64 by 64
		// arena into 4096 standable cells, which is exactly what it did.
		if(!Traversal::DoorAt(tileX, tileY).exists)
			return false;

		Body planning;
		if(!PlanningBody(body, planning, tileX, tileY))
			return false;

		const fixed x = (fixed)((tileX<<TILESHIFT) + (1<<(TILESHIFT-1)));
		const fixed y = (fixed)((tileY<<TILESHIFT) + (1<<(TILESHIFT-1)));
		return CheckPositionAt(planning, x, y, NULL);
	}

	return CanOccupyTile(body, tileX, tileY);
}

bool CanStepBetweenTilesOrDoor(const Body &body, unsigned int fromX, unsigned int fromY,
	unsigned int toX, unsigned int toY)
{
	if(!CanOccupyTileOrDoor(body, fromX, fromY) ||
		!CanOccupyTileOrDoor(body, toX, toY))
		return false;

	// At most one end of a step is a door: two doors side by side share a
	// face, and a body crossing between them is crossing two boundaries at
	// once, which the follower's one-door-at-a-time protocol cannot drive.
	Body planning = body;
	const bool fromDoor = DoorAt(fromX, fromY).exists;
	const bool toDoor = DoorAt(toX, toY).exists;
	if(fromDoor && toDoor)
		return false;
	if(fromDoor && !PlanningBody(body, planning, fromX, fromY))
		return false;
	if(toDoor && !PlanningBody(body, planning, toX, toY))
		return false;

	const fixed halfTile = (fixed)(1<<(TILESHIFT-1));
	const fixed ax = (fixed)((fromX<<TILESHIFT)) + halfTile;
	const fixed ay = (fixed)((fromY<<TILESHIFT)) + halfTile;
	const fixed bx = (fixed)((toX<<TILESHIFT)) + halfTile;
	const fixed by = (fixed)((toY<<TILESHIFT)) + halfTile;

	const unsigned int Samples = 8;
	for(unsigned int i = 1;i < Samples;++i)
	{
		const fixed x = ax + (fixed)(((int64_t)(bx - ax)*i)/Samples);
		const fixed y = ay + (fixed)(((int64_t)(by - ay)*i)/Samples);
		if(!CheckPositionAt(planning, x, y, NULL))
			return false;
	}
	return true;
}

Body PlayerBody(const ClassDef *playerClass, const AActor *ignore)
{
	Body body;
	body.isPlayer = true;
	body.ignore = ignore;
	// A body with no width fits everywhere, including inside a wall, so a
	// missing class is a failure to answer rather than an answer of zero.
	// C7Player is 22 units in a 64-unit tile and that is the number the whole
	// question turns on.
	if(playerClass != NULL && playerClass->GetDefault() != NULL)
		body.radius = playerClass->GetDefault()->radius;
	return body;
}

}
