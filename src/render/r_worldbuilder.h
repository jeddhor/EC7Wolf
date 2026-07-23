#ifndef __R_WORLDBUILDER_H__
#define __R_WORLDBUILDER_H__

#include "tarray.h"
#include "textures/textures.h"

class GameMap;

// ===========================================================================
//
// RenderWorldBuilder - backend-neutral static world geometry (Phase 5).
//
// Converts the tile map's plane 0 into conventional GPU geometry: one quad per
// floor/ceiling of each open cell and one quad per solid-tile face that borders
// open space. Coordinates are in tile units (1 tile = 1.0) with Z up: floor at
// z=0, ceiling at z=1. This is independent of any graphics API; the OpenGL
// backend (and later Vulkan) uploads the result.
//
// Only static opaque geometry is produced here. Dynamic walls (doors,
// pushwalls) and masked walls are handled in later phases and are intentionally
// excluded so they can be interpolated / alpha-tested separately.
//
// ===========================================================================

struct WorldVertex
{
	float x, y, z;		// tile-unit world position
	float u, v;			// texture coordinates
	float texKey;		// texture index (debug shading in Phase 5; real bind in 6)
	float shade;		// per-face base shade (0..1), refined by colormaps later
};

enum WorldSurfaceKind
{
	WSURF_Floor,
	WSURF_Ceiling,
	WSURF_Wall
};

// A run of vertices sharing a texture/kind, so the backend can bind the real
// indexed texture per surface in Phase 6.
struct WorldSurface
{
	unsigned int firstVertex;
	unsigned int vertexCount;
	FTextureID   texture;
	int          kind;		// WorldSurfaceKind
	int          side;		// MapTile::Side for walls, -1 otherwise
};

struct WorldMesh
{
	TArray<WorldVertex>  vertices;
	TArray<WorldSurface> surfaces;

	// Summary counts (used by tests / diagnostics).
	unsigned int wallFaces;
	unsigned int floorTiles;
	unsigned int ceilingTiles;

	WorldMesh() : wallFaces(0), floorTiles(0), ceilingTiles(0) {}
	void Clear()
	{
		vertices.Clear();
		surfaces.Clear();
		wallFaces = floorTiles = ceilingTiles = 0;
	}
};

namespace WorldBuilder
{
	// Build static opaque geometry for the given map's plane 0 into out.
	void Build(GameMap *gm, WorldMesh &out);
}

#endif
