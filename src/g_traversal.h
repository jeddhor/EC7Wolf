/*
** g_traversal.h
**
** "Would a body of this size fit here?", asked without moving anything.
**
** A navigator has to know whether a step is possible before taking it, and the
** only honest answer comes from the code that decides whether a step actually
** succeeds. Asking a different piece of code produces a graph that disagrees
** with the game: a route through a gap the player cannot fit through, or a
** wall the planner believes in and the pawn walks past.
**
** So the geometry in TryMove lives here, and TryMove is what it always was
** minus the geometry: it calls this, then does the things only a real move may
** do -- zap a player leaning on an electric wall, zap one standing in a laser,
** and let whatever it overlapped Touch it.
**
** The query passes no hooks and therefore does none of that. It cannot: there
** is nowhere for a side effect to happen. That is the difference between this
** and the tempting alternative of running TryMove on a disposable actor and
** hoping nothing it touches minds.
**
** See docs/multiplayer-bots-and-server.md, section 12.3.
*/

#ifndef __G_TRAVERSAL_H__
#define __G_TRAVERSAL_H__

#include "wl_def.h"
#include "gamemap.h"

class AActor;

namespace Traversal {

// What is being fitted, rather than which actor is being moved. A navigator
// asks about a body that may not exist yet -- the graph is built before any
// bot has a pawn -- so the query takes dimensions and rules, not a pointer.
struct Body
{
	fixed radius = 0;
	// Players pass through one another in this game, so who is asking changes
	// which actors block.
	bool isPlayer = false;
	// Excluded from the actor test: whatever is being moved cannot block
	// itself.
	const AActor *ignore = NULL;
};

// Called while the position is being checked, by the caller that is allowed to
// have side effects. The query supplies neither.
struct Hooks
{
	// A wall side blocked the body. Corridor 7 zaps a player leaning on an
	// electric wall here, every time contact is remade.
	void (*onWallBlocked)(void *context, MapSpot spot) = NULL;
	// A non-solid actor overlapped. Called during iteration rather than after
	// it, because Touch can destroy the actor and a list gathered first would
	// be a list of dangling pointers by the time it was walked.
	void (*onOverlap)(void *context, AActor *other) = NULL;
	void *context = NULL;
};

// Does the body fit at this position?
//
// The same dimensions and boundary rules the player's own movement uses,
// because it is the same code. Passing hooks makes it a move; passing none
// makes it a question.
bool CheckPositionAt(const Body &body, fixed x, fixed y, const Hooks *hooks);

// Can the body stand in the middle of this tile? The question a graph builder
// asks about a cell, and the one a follower asks before committing to one.
bool CanOccupyTile(const Body &body, unsigned int tileX, unsigned int tileY);

// Can the body get from one tile centre to the next, adjacent one?
//
// Sampled along the way rather than only at the ends: a body with a radius can
// be able to stand in both tiles and unable to pass between them, which is
// most of what makes a doorway a doorway.
bool CanStepBetweenTiles(const Body &body, unsigned int fromX, unsigned int fromY,
	unsigned int toX, unsigned int toY);

// The body an ordinary player of this class has. Used by the graph, which is
// built before anyone has spawned.
Body PlayerBody(const class ClassDef *playerClass, const AActor *ignore = NULL);

}

#endif
