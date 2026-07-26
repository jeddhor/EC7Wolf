#ifndef __R_INTERPOLATION_H__
#define __R_INTERPOLATION_H__

#include "wl_def.h"

class AActor;

// ===========================================================================
//
// Renderer-independent motion interpolation (renderer redesign Phase 3).
//
// The simulation runs at a fixed 70 Hz. To display smooth motion at higher
// refresh rates, the renderer draws actors (including the camera, which is an
// actor) at an interpolated position between the two most recent simulation
// states, using the fractional accumulator "alpha" in [0,1).
//
// The interpolated transform is applied to actors ONLY for the duration of a
// rendered frame and then restored, so the simulation never observes an
// interpolated value. Determinism is therefore preserved exactly: a recorded
// run produces the same per-tic checksum with interpolation on or off.
//
// ===========================================================================

// Shortest-arc angle interpolation. Interpolating 359deg -> 1deg travels
// through 0deg, not backwards through 358deg.
angle_t R_LerpAngle(angle_t from, angle_t to, float alpha);

namespace Interpolation
{
	// Called immediately before a simulation tic runs: shift every actor's
	// current render transform into its previous slot.
	void BeginTic();

	// Called immediately after a simulation tic runs: capture every actor's
	// post-tic transform as its current render transform. Actors whose history
	// is still invalid (freshly spawned or just teleported) get previous set
	// equal to current so they render statically.
	void EndTic();

	// Substitute interpolated transforms into all actors for a render at the
	// given alpha, then Restore() puts the authoritative simulation state back.
	// Apply()/Restore() are a no-op when interpolation is disabled.
	void Apply(float alpha);
	void Restore();

	// Forgets every actor's motion history. A level change gives actors new
	// authoritative positions from outside the tic loop, and Restore() would
	// otherwise write the previous level's snapshot back over them.
	void Reset();
}

#endif
