#ifndef __R_DYNAMICWALLS_H__
#define __R_DYNAMICWALLS_H__

#include "tarray.h"
#include "textures/textures.h"
#include "gamemap.h"

class Thinker;

// ===========================================================================
//
// Renderer-owned dynamic-wall snapshots + interpolation (renderer redesign
// Phase 7).
//
// Doors and pushwalls change geometry every simulation tic. Like the actor
// interpolation added in Phase 3, we snapshot the previous and current
// simulation states and blend between them by the fractional accumulator alpha
// so the motion is smooth at any refresh rate. The blended values are used for
// rendering ONLY; the authoritative simulation fields (slideAmount, pushAmount,
// pushReceptor, ...) are never modified here, so determinism is preserved.
//
// A pushwall is keyed by its *thinker* rather than a map cell, because the same
// logical wall transfers ownership from one cell to the next as it moves. The
// stored world position is therefore continuous across a tile boundary and the
// wall does not snap backwards when pushAmount resets from 64 to 0.
//
// ===========================================================================

namespace DynamicWalls
{
	// Cell classification (shared with the world builder so the static mesh and
	// the dynamic mesh agree on exactly which cells are dynamic).
	bool IsDoorCell(MapSpot spot);
	bool IsPushwallCell(MapSpot spot);		// origin or receptor while in motion
	bool IsPushwallOrigin(MapSpot spot);	// thinker-bearing cell (emit identity)
	inline bool IsDynamicCell(MapSpot spot)
	{
		return IsDoorCell(spot) || IsPushwallCell(spot);
	}

	// One door leaf to render. amount is the interpolated slide (0 = closed ..
	// 0xffff = fully open); style selects CheckSlidePass()/SlideTextureOffset().
	struct DoorRender
	{
		MapSpot spot;
		int     style;
		float   amount;
	};

	// One moving pushwall block to render. (x,y) is the interpolated base (min)
	// corner in tile units; tex[] holds the four side textures.
	struct PushRender
	{
		float      x, y;
		int        dir;			// MapTile::Side of travel
		FTextureID tex[4];
	};

	// Snapshot lifecycle, called around each simulation tic and on level start.
	void BeginTic();	// shift current snapshot into previous
	void EndTic();		// capture the post-tic state as current
	void Reset();		// forget all history (level start / load / teleport)

	// Produce the door + pushwall render lists interpolated at the given alpha.
	void GetRender(float alpha, TArray<DoorRender> &doors,
		TArray<PushRender> &pushes);
}

#endif
