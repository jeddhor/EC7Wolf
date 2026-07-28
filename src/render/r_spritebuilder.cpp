// ===========================================================================
//
// r_spritebuilder.cpp - backend-neutral actor-sprite billboards (Phase 9).
//
// DrawScaleds() in the software renderer walks the actor list, tests each
// actor's visibility, transforms it, selects a rotation frame, and scan-line
// scales it into the framebuffer with the Corridor 7 colour-cycle, full-bright,
// visor-visibility rules baked into the inner loop.
//
// The GPU renderer needs the same *selection* (which actors, which frame /
// rotation / mirror, which material state) but expresses the *scaling* as a
// camera-facing billboard quad the backend rasterises with the world depth
// buffer. This file reproduces the selection and emits the geometry; the shared
// index/opacity/palette shader (r_glworld.cpp) does the shading. The scan-line
// scaler is untouched, and nothing here writes simulation state, so the
// determinism gate is unaffected.
//
// Sprites are read at each actor's *current* transform, which the caller has
// already replaced with the interpolated value for this frame (Phase 3), so
// billboards move smoothly and stay consistent with the interpolated camera.
//
// ===========================================================================

#include <math.h>

#include "render/r_worldbuilder.h"
#include "wl_def.h"
#include "wl_draw.h"
#include "wl_main.h"
#include "wl_game.h"
#include "wl_play.h"
#include "wl_agent.h"
#include "actor.h"
#include "id_ca.h"
#include "gamemap.h"
#include "r_sprites.h"
#include "textures/textures.h"

// Provided by wl_draw.cpp; not exposed in a header. TransformActor populates
// actor->viewx / viewheight / transx / transy from the current view globals, and
// CalcRotate reads actor->viewx to choose the eight-way rotation frame.
void TransformActor(AActor *ob);
unsigned int CalcRotate(AActor *ob);

namespace
{
	// One sprite texel maps to 1/64 of a tile: a 64px-tall sprite drawn at unit
	// scale is exactly one tile high, matching the software scaler (whose sprite
	// screen height equals the full-tile wall height for a 64px sprite). See the
	// derivation in docs/renderer/phase9-sprites.md.
	const float kTexelsPerTile = 64.0f;

	// Push one billboard quad (two triangles a,b,c / a,c,d) with the sprite's
	// material state. UVs match PushQuad in r_worldbuilder.cpp (v=0 is the top
	// texture row); flipU mirrors the sprite horizontally for its rotation.
	void PushSpriteQuad(WorldMesh &out,
		const float p[4][3], bool flipU, const FTextureID &tex,
		bool fullbright)
	{
		const unsigned int first = out.vertices.Size();
		const float texKey = (float)(tex.isValid() ? tex.GetIndex() : 0);

		// Corner order a,b,c,a,c,d with a=bottom-left, b=bottom-right,
		// c=top-right, d=top-left.
		const int idx[6] = { 0, 1, 2, 0, 2, 3 };
		const float uu[6] = { 0, 1, 1, 0, 1, 0 };
		const float vv[6] = { 1, 1, 0, 1, 0, 0 };
		for(int i = 0; i < 6; ++i)
		{
			WorldVertex v;
			v.x = p[idx[i]][0];
			v.y = p[idx[i]][1];
			v.z = p[idx[i]][2];
			v.u = flipU ? 1.0f - uu[i] : uu[i];
			v.v = vv[i];
			v.texKey = texKey;
			v.shade = 1.0f;
			out.vertices.Push(v);
		}

		WorldSurface surf;
		surf.firstVertex = first;
		surf.vertexCount = 6;
		surf.texture = tex;
		surf.kind = WSURF_Sprite;
		surf.side = -1;
		surf.fullbright = fullbright ? 1 : 0;
		out.surfaces.Push(surf);
		++out.wallFaces;
	}

	// The nine-cell visibility test from DrawScaleds: an actor is drawn if its own
	// cell is visible, or any of the eight surrounding *open* cells is visible.
	bool ActorVisible(AActor *obj)
	{
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

		if(spot->visible)
			return true;
		for(int i = 0; i < 8; ++i)
			if(spots[i] && spots[i]->visible && !spots[i]->tile)
				return true;
		return false;
	}
}

namespace WorldBuilder
{

void BuildSprites(GameMap *gm, WorldMesh &out)
{
	out.Clear();
	if(gm == NULL || players[ConsolePlayer].camera == NULL)
		return;

	// Screen-right in world XY. ECWolf's forward is (viewcos, -viewsin), so the
	// right-handed basis vector forward x up(+Z) is (-viewsin, -viewcos) -- but that
	// axis lands on screen-LEFT once the projection's negated clip X (which matches
	// GL's handedness to Corridor 7's X-east / Y-south world) is applied. A billboard
	// has to span the axis that actually increases screen x, so use its negation;
	// texture column 0 then falls on the sprite's left edge exactly as ScaleSprite
	// draws it (actx = xcenter - leftOffset, columns increasing rightward).
	// FL_BILLBOARD sprites below are unaffected: they span a real world direction
	// (finesine, finecosine) that already matches Scale3DSprite.
	float screenRx = FIXED2FLOAT(viewsin);
	float screenRy = FIXED2FLOAT(viewcos);
	{
		const float l = sqrtf(screenRx*screenRx + screenRy*screenRy);
		if(l > 0.0f) { screenRx /= l; screenRy /= l; }
	}

	for(AActor::Iterator iter = AActor::GetIterator(); iter.Next();)
	{
		AActor *obj = iter;
		if(obj->sprite == SPR_NONE)
			continue;
		if(!ActorVisible(obj))
			continue;

		TransformActor(obj);
		if(!obj->viewheight ||
			(gamestate.victoryflag && obj == players[ConsolePlayer].mo))
			continue;	// too close / far, or the winning player's own body

		SpriteRenderInfo info;
		if(!R_GetSpriteRenderInfo(obj, info))
			continue;	// no frame, null texture, or visor-gated out

		FTexture *tex = info.tex;
		const float scaleXf = FIXED2FLOAT(obj->scaleX);
		const float scaleYf = FIXED2FLOAT(obj->scaleY);
		const float worldW = (float)tex->GetScaledWidthDouble()*scaleXf/kTexelsPerTile;
		const float worldH = (float)tex->GetScaledHeightDouble()*scaleYf/kTexelsPerTile;
		if(worldW <= 0.0f || worldH <= 0.0f)
			continue;

		// Anchor the billboard by the texture's offsets, exactly as the software
		// scaler does (ScaleSprite in r_sprites.cpp): the actor origin sits leftOff
		// texels from the sprite's left edge and topOff texels below its top edge.
		// Horizontally that spans [-leftOff, worldW-leftOff] about the origin;
		// vertically the top edge is topOff above the origin and the bottom is worldH
		// below the top. The top-offset is what places ceiling / hanging props high:
		// their topOff is a full tile while the graphic itself is short, so anchoring
		// the base at z=0 (the old model) dropped every such prop onto the floor.
		//
		// The origin's own height above the floor comes from obj->z: the software
		// scaler adds (obj->z<<6) to viewz, and a full wall (floor..ceiling) spans
		// map-plane depth tiles = (depth<<FRACBITS) fixed Z mapped to GL z in [0,1].
		const float leftOff = (float)tex->GetScaledLeftOffsetDouble()*scaleXf/kTexelsPerTile;
		const float topOff = (float)tex->GetScaledTopOffsetDouble()*scaleYf/kTexelsPerTile;
		const float aL = -leftOff;
		const float aR = worldW - leftOff;
		const float invWallZ = 1.0f / (float)(gm->GetPlane(0).depth << FRACBITS);
		const float zOrigin = (float)obj->z * 64.0f * invWallZ;
		const float zT = zOrigin + topOff;
		const float zB = zT - worldH;

		const float cx = (float)obj->x / (float)TILEGLOBAL;
		const float cy = (float)obj->y / (float)TILEGLOBAL;

		// Right axis: screen-facing by default; world-oriented along the actor's
		// facing for FL_BILLBOARD sprites (flat panels placed in the world, e.g.
		// the laser barrier rods). Scale3DSprite spans (finesine, finecosine).
		float rx = screenRx, ry = screenRy;
		if(info.worldAligned)
		{
			rx = FIXED2FLOAT(finesine[obj->angle>>ANGLETOFINESHIFT]);
			ry = FIXED2FLOAT(finecosine[obj->angle>>ANGLETOFINESHIFT]);
			const float l = sqrtf(rx*rx + ry*ry);
			if(l > 0.0f) { rx /= l; ry /= l; }
		}

		float p[4][3];
		// a bottom-left, b bottom-right, c top-right, d top-left
		p[0][0] = cx + aL*rx; p[0][1] = cy + aL*ry; p[0][2] = zB;
		p[1][0] = cx + aR*rx; p[1][1] = cy + aR*ry; p[1][2] = zB;
		p[2][0] = cx + aR*rx; p[2][1] = cy + aR*ry; p[2][2] = zT;
		p[3][0] = cx + aL*rx; p[3][1] = cy + aL*ry; p[3][2] = zT;

		PushSpriteQuad(out, p, info.flip, tex->GetID(), info.fullbright);
	}
}

} // namespace WorldBuilder
