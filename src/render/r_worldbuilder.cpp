// ===========================================================================
//
// r_worldbuilder.cpp - backend-neutral static world geometry (Phase 5).
//
// ===========================================================================

#include "render/r_worldbuilder.h"
#include "render/r_dynamicwalls.h"
#include "wl_def.h"
#include "gamemap.h"
#include "id_ca.h"

namespace
{
	// Per-side base shade so adjacent faces read distinctly and lighting has a
	// starting point before colormaps land in Phase 6. Matches the classic
	// Wolfenstein convention that N/S faces are darker than E/W faces.
	float SideShade(int side)
	{
		switch(side)
		{
			case MapTile::North:
			case MapTile::South: return 0.7f;
			default:             return 1.0f;	// East / West
		}
	}

	void PushQuad(WorldMesh &mesh,
		float ax, float ay, float az,
		float bx, float by, float bz,
		float cx, float cy, float cz,
		float dx, float dy, float dz,
		const FTextureID &tex, int kind, int side, float shade,
		int slideStyle = 0, unsigned int slideAmount = 0)
	{
		const unsigned int first = mesh.vertices.Size();
		const float texKey = (float)(tex.isValid() ? tex.GetIndex() : 0);

		// Two triangles: a,b,c and a,c,d. UVs map the quad corners to [0,1].
		WorldVertex v[6];
		const float px[6] = { ax, bx, cx, ax, cx, dx };
		const float py[6] = { ay, by, cy, ay, cy, dy };
		const float pz[6] = { az, bz, cz, az, cz, dz };
		const float uu[6] = { 0,  1,  1,  0,  1,  0 };
		const float vv[6] = { 1,  1,  0,  1,  0,  0 };
		for(int i = 0; i < 6; ++i)
		{
			v[i].x = px[i]; v[i].y = py[i]; v[i].z = pz[i];
			v[i].u = uu[i]; v[i].v = vv[i];
			v[i].texKey = texKey;
			v[i].shade = shade;
			mesh.vertices.Push(v[i]);
		}

		WorldSurface surf;
		surf.firstVertex = first;
		surf.vertexCount = 6;
		surf.texture = tex;
		surf.kind = kind;
		surf.side = side;
		surf.slideStyle = slideStyle;
		surf.slideAmount = slideAmount;
		mesh.surfaces.Push(surf);
	}

	// Floor and/or ceiling for one open (or door / vacated-pushwall) cell.
	void PushFloorCeiling(WorldMesh &out, MapSpot spot, float fx, float fy)
	{
		if(spot->sector == NULL)
			return;
		FTextureID floorTex = spot->sector->texture[MapSector::Floor];
		FTextureID ceilTex  = spot->sector->texture[MapSector::Ceiling];
		if(floorTex.isValid())
		{
			PushQuad(out,
				fx,   fy,   0,  fx+1, fy,   0,
				fx+1, fy+1, 0,  fx,   fy+1, 0,
				floorTex, WSURF_Floor, -1, 0.85f);
			++out.floorTiles;
		}
		if(ceilTex.isValid())
		{
			PushQuad(out,
				fx,   fy+1, 1,  fx+1, fy+1, 1,
				fx+1, fy,   1,  fx,   fy,   1,
				ceilTex, WSURF_Ceiling, -1, 0.6f);
			++out.ceilingTiles;
		}
	}

	// One solid wall face of a 1x1 cell whose base (min) corner is at (bx,by).
	// The base is a float so a moving pushwall block can sit at a fractional
	// position; static walls pass integer tile coordinates.
	void PushWallFace(WorldMesh &out, int side, float bx, float by,
		const FTextureID &tex)
	{
		const float sh = SideShade(side);
		switch(side)
		{
			case MapTile::East:	// +X face at x+1
				PushQuad(out,
					bx+1, by,   0,  bx+1, by+1, 0,
					bx+1, by+1, 1,  bx+1, by,   1,
					tex, WSURF_Wall, side, sh);
				break;
			case MapTile::West:	// -X face at x
				PushQuad(out,
					bx, by+1, 0,  bx, by,   0,
					bx, by,   1,  bx, by+1, 1,
					tex, WSURF_Wall, side, sh);
				break;
			case MapTile::North:	// +Y face at y+1
				PushQuad(out,
					bx+1, by+1, 0,  bx, by+1, 0,
					bx,   by+1, 1,  bx+1, by+1, 1,
					tex, WSURF_Wall, side, sh);
				break;
			case MapTile::South:	// -Y face at y
				PushQuad(out,
					bx, by, 0,  bx+1, by, 0,
					bx+1, by, 1,  bx, by, 1,
					tex, WSURF_Wall, side, sh);
				break;
		}
		++out.wallFaces;
	}
}

namespace WorldBuilder
{

void BuildStatic(GameMap *gm, WorldMesh &out)
{
	out.Clear();
	if(gm == NULL || gm->NumPlanes() == 0)
		return;

	const GameMap::Header &header = gm->GetHeader();
	const unsigned int w = header.width;
	const unsigned int h = header.height;

	for(unsigned int y = 0; y < h; ++y)
	for(unsigned int x = 0; x < w; ++x)
	{
		MapSpot spot = gm->GetSpot(x, y, 0);
		const float fx = (float)x;
		const float fy = (float)y;

		if(spot->tile != NULL)
		{
			// Doors and moving pushwalls are rebuilt every frame by
			// BuildDynamic; keep them out of the static mesh but still emit the
			// cell's floor/ceiling so the doorway (or vacated pushwall cell) is
			// not a hole. Neighbours still treat these cells as solid for
			// adjacency, so no duplicate faces appear at the opening.
			if(DynamicWalls::IsDynamicCell(spot))
			{
				PushFloorCeiling(out, spot, fx, fy);
				continue;
			}

			// Solid wall cell: emit each face that borders open space.
			for(int side = 0; side < 4; ++side)
			{
				MapSpot adj = spot->GetAdjacent((MapTile::Side)side);
				if(adj != NULL && adj->tile != NULL)
					continue;	// neighbor is solid: face hidden

				PushWallFace(out, side, fx, fy, spot->texture[side]);
			}
		}
		else if(spot->sector != NULL)
		{
			// Open cell: floor and/or ceiling.
			PushFloorCeiling(out, spot, fx, fy);
		}
	}
}

void BuildDynamic(GameMap *gm, WorldMesh &out, float alpha)
{
	out.Clear();
	if(gm == NULL || gm->NumPlanes() == 0)
		return;

	TArray<DynamicWalls::DoorRender> doors;
	TArray<DynamicWalls::PushRender> pushes;
	DynamicWalls::GetRender(alpha, doors, pushes);

	// Door leaves: a single quad in the tile-centre plane. The shader reproduces
	// the software CheckSlidePass()/SlideTextureOffset() slide along the quad's
	// U axis (the axis the door opens along), so the leaf recedes into its pocket
	// exactly as the raycaster draws it.
	for(unsigned int i = 0; i < doors.Size(); ++i)
	{
		const DynamicWalls::DoorRender &d = doors[i];
		const float fx = (float)d.spot->GetX();
		const float fy = (float)d.spot->GetY();
		const unsigned int amt = (unsigned int)(d.amount + 0.5f);

		if(d.spot->tile->offsetVertical)
		{
			// Opens East/West: plane at x+0.5, U runs along Y.
			const FTextureID tex = d.spot->texture[MapTile::East];
			PushQuad(out,
				fx+0.5f, fy,   0,  fx+0.5f, fy+1, 0,
				fx+0.5f, fy+1, 1,  fx+0.5f, fy,   1,
				tex, WSURF_DoorLeaf, MapTile::East, 1.0f, d.style, amt);
			++out.wallFaces;
		}
		else
		{
			// Opens North/South: plane at y+0.5, U runs along X.
			const FTextureID tex = d.spot->texture[MapTile::North];
			PushQuad(out,
				fx,   fy+0.5f, 0,  fx+1, fy+0.5f, 0,
				fx+1, fy+0.5f, 1,  fx,   fy+0.5f, 1,
				tex, WSURF_DoorLeaf, MapTile::North, 1.0f, d.style, amt);
			++out.wallFaces;
		}
	}

	// Pushwall blocks: an opaque 1x1 block at the interpolated base corner. All
	// four faces are emitted (a moving wall can be seen from any side); the depth
	// buffer resolves occlusion.
	for(unsigned int i = 0; i < pushes.Size(); ++i)
	{
		const DynamicWalls::PushRender &p = pushes[i];
		for(int side = 0; side < 4; ++side)
			PushWallFace(out, side, p.x, p.y, p.tex[side]);
	}
}

} // namespace WorldBuilder
