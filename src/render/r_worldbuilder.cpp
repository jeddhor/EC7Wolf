// ===========================================================================
//
// r_worldbuilder.cpp - backend-neutral static world geometry (Phase 5).
//
// ===========================================================================

#include "render/r_worldbuilder.h"
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
		const FTextureID &tex, int kind, int side, float shade)
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
		mesh.surfaces.Push(surf);
	}
}

namespace WorldBuilder
{

void Build(GameMap *gm, WorldMesh &out)
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
			// Solid wall cell: emit each face that borders open space.
			for(int side = 0; side < 4; ++side)
			{
				MapSpot adj = spot->GetAdjacent((MapTile::Side)side);
				if(adj != NULL && adj->tile != NULL)
					continue;	// neighbor is solid: face hidden

				FTextureID tex = spot->texture[side];
				const float sh = SideShade(side);

				switch(side)
				{
					case MapTile::East:	// +X face at x+1
						PushQuad(out,
							fx+1, fy,   0,  fx+1, fy+1, 0,
							fx+1, fy+1, 1,  fx+1, fy,   1,
							tex, WSURF_Wall, side, sh);
						break;
					case MapTile::West:	// -X face at x
						PushQuad(out,
							fx, fy+1, 0,  fx, fy,   0,
							fx, fy,   1,  fx, fy+1, 1,
							tex, WSURF_Wall, side, sh);
						break;
					case MapTile::North:	// +Y face at y+1
						PushQuad(out,
							fx+1, fy+1, 0,  fx, fy+1, 0,
							fx,   fy+1, 1,  fx+1, fy+1, 1,
							tex, WSURF_Wall, side, sh);
						break;
					case MapTile::South:	// -Y face at y
						PushQuad(out,
							fx, fy, 0,  fx+1, fy, 0,
							fx+1, fy, 1,  fx, fy, 1,
							tex, WSURF_Wall, side, sh);
						break;
				}
				++out.wallFaces;
			}
		}
		else if(spot->sector != NULL)
		{
			// Open cell: floor and/or ceiling.
			FTextureID floorTex = spot->sector->texture[MapSector::Floor];
			FTextureID ceilTex  = spot->sector->texture[MapSector::Ceiling];

			if(floorTex.isValid())
			{
				// Floor at z=0, wound so it faces up (+Z).
				PushQuad(out,
					fx,   fy,   0,  fx+1, fy,   0,
					fx+1, fy+1, 0,  fx,   fy+1, 0,
					floorTex, WSURF_Floor, -1, 0.85f);
				++out.floorTiles;
			}
			if(ceilTex.isValid())
			{
				// Ceiling at z=1, wound so it faces down (-Z).
				PushQuad(out,
					fx,   fy+1, 1,  fx+1, fy+1, 1,
					fx+1, fy,   1,  fx,   fy,   1,
					ceilTex, WSURF_Ceiling, -1, 0.6f);
				++out.ceilingTiles;
			}
		}
	}
}

} // namespace WorldBuilder
