// ===========================================================================
//
// r_interpolation.cpp - renderer-independent motion interpolation.
//
// Renderer redesign Phase 3. See r_interpolation.h for the model. The core
// technique is temporary substitution: for the duration of a rendered frame,
// each actor's authoritative transform is replaced with an interpolated value,
// the scene is drawn, and the authoritative state is restored. Because the
// post-tic ("current") transform is captured verbatim and the substitution is
// undone before the next tic, the simulation never observes an interpolated
// value and determinism is preserved exactly.
//
// ===========================================================================

#include "render/r_interpolation.h"
#include "actor.h"
#include "wl_agent.h"
#include "wl_play.h"
#include "c_cvars.h"

angle_t R_LerpAngle(angle_t from, angle_t to, float alpha)
{
	// angle_t is a binary angle that wraps modulo 2^32, so the signed
	// difference automatically takes the shortest arc (-180deg..+180deg).
	const int32_t delta = static_cast<int32_t>(to - from);
	return from + static_cast<angle_t>(static_cast<int32_t>(delta * alpha));
}

namespace
{
	inline fixed LerpFixed(fixed from, fixed to, float alpha)
	{
		// Use double to avoid overflow when from/to differ by a large amount.
		return from + static_cast<fixed>(
			static_cast<double>(to - from) * static_cast<double>(alpha));
	}

	inline AActor *CameraActor()
	{
		return players[ConsolePlayer].camera;
	}
}

namespace Interpolation
{

void BeginTic()
{
	if(!r_interpolate)
		return;

	for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
	{
		AActor *a = iter;
		a->renderPrevX     = a->renderCurX;
		a->renderPrevY     = a->renderCurY;
		a->renderPrevZ     = a->renderCurZ;
		a->renderPrevAngle = a->renderCurAngle;
		a->renderPrevPitch = a->renderCurPitch;
	}
}

void EndTic()
{
	if(!r_interpolate)
		return;

	for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
	{
		AActor *a = iter;
		a->renderCurX     = a->x;
		a->renderCurY     = a->y;
		a->renderCurZ     = a->z;
		a->renderCurAngle = a->angle;
		a->renderCurPitch = a->pitch;

		if(!a->renderInterpValid)
		{
			// First capture (fresh spawn or post-teleport): render statically.
			a->renderPrevX     = a->renderCurX;
			a->renderPrevY     = a->renderCurY;
			a->renderPrevZ     = a->renderCurZ;
			a->renderPrevAngle = a->renderCurAngle;
			a->renderPrevPitch = a->renderCurPitch;
			a->renderInterpValid = true;
		}
	}
}

void Apply(float alpha)
{
	if(!r_interpolate)
		return;

	const AActor *camera = CameraActor();

	for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
	{
		AActor *a = iter;
		if(!a->renderInterpValid)
			continue;

		const bool isCamera = (a == camera);
		if(isCamera ? !r_interpolate_camera : !r_interpolate_actors)
			continue;

		a->x     = LerpFixed(a->renderPrevX, a->renderCurX, alpha);
		a->y     = LerpFixed(a->renderPrevY, a->renderCurY, alpha);
		a->z     = LerpFixed(a->renderPrevZ, a->renderCurZ, alpha);
		a->angle = R_LerpAngle(a->renderPrevAngle, a->renderCurAngle, alpha);
		a->pitch = R_LerpAngle(a->renderPrevPitch, a->renderCurPitch, alpha);
	}
}

void Restore()
{
	if(!r_interpolate)
		return;

	for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
	{
		AActor *a = iter;
		if(!a->renderInterpValid)
			continue;

		// renderCur* is the authoritative post-tic state captured in EndTic and
		// unchanged since, so this restores the exact simulation values.
		a->x     = a->renderCurX;
		a->y     = a->renderCurY;
		a->z     = a->renderCurZ;
		a->angle = a->renderCurAngle;
		a->pitch = a->renderCurPitch;
	}
}

} // namespace Interpolation
