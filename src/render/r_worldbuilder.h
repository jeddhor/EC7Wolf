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
	WSURF_Wall,
	WSURF_DoorLeaf,		// sliding door leaf: wall-shaded + shader slide (Phase 7)
	WSURF_Masked,		// colour-keyed masked wall: wall-shaded + alpha test (Phase 8)
	WSURF_Sprite		// billboard actor sprite: distance-shaded, index-0 keyed (Phase 9)
};

// A run of vertices sharing a texture/kind, so the backend can bind the real
// indexed texture per surface in Phase 6.
struct WorldSurface
{
	unsigned int firstVertex;
	unsigned int vertexCount;
	FTextureID   texture;
	int          kind;			// WorldSurfaceKind
	int          side;			// MapTile::Side for walls, -1 otherwise
	// Door-leaf slide state (WSURF_DoorLeaf only): the shader reproduces the
	// software CheckSlidePass()/SlideTextureOffset() along the quad's U axis.
	int          slideStyle;	// SLIDE_Normal / SLIDE_Split / SLIDE_Invert
	unsigned int slideAmount;	// 0 = closed .. 0xffff = fully open
	// Sprite state (WSURF_Sprite only): full-bright ignores distance shade.
	int          fullbright;	// 1 = FL_BRIGHT / frame->fullbright

	WorldSurface() : firstVertex(0), vertexCount(0), kind(0), side(-1),
		slideStyle(0), slideAmount(0), fullbright(0) {}
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
	// Build static opaque geometry for the given map's plane 0 into out. Cells
	// reported by IsDynamicCell are skipped (door/pushwall cells still emit their
	// floor and ceiling so the doorway/vacated cell is not a hole).
	void BuildStatic(GameMap *gm, WorldMesh &out);

	// Build the dynamic geometry (door leaves + moving pushwalls) at the given
	// interpolation alpha. Door slide amounts and pushwall world positions are
	// blended between the previous and current simulation tics via DynamicWalls.
	void BuildDynamic(GameMap *gm, WorldMesh &out, float alpha);

	// Build the masked (colour-keyed, see-through) wall geometry: glass, grates,
	// fences, force fields, and opened animated-wall apertures. Faces are emitted
	// at the tile boundaries (like a solid wall) but only on sides that survive
	// the connected-glass merge, and are alpha-tested by the backend. Rebuilt each
	// frame because force-field art animates with the game clock.
	//
	// camX/camY are the camera position in tile units. The raycaster's DDA records
	// a masked-wall hit only for the cell a ray ENTERS, so it draws just the face
	// nearest the viewer; emitting a cell's far face too makes a see-through pane
	// read as a doubled box. camX/camY drive a CPU back-face cull that reproduces
	// the entry-face behaviour (done on the CPU so it is independent of the world-
	// mirror in the projection, which flips GL winding).
	void BuildMasked(GameMap *gm, WorldMesh &out, float camX, float camY);

	// Build billboard geometry for every visible actor sprite. Reproduces the
	// software DrawScaleds() visibility test, TransformActor(), and the frame /
	// rotation / mirror / visor selection, then emits one camera-facing quad per
	// sprite (world-oriented along actor->angle for FL_BILLBOARD actors). Actor
	// positions are read at their current (already interpolated by the caller)
	// transform. The quads are index-0 alpha-tested and distance-shaded by the
	// backend, sharing the world depth buffer so walls and masked panes occlude
	// them correctly. Must run after the software view globals for this frame are
	// current (viewx/viewy/viewsin/viewcos/scale/centerx and spot->visible).
	void BuildSprites(GameMap *gm, WorldMesh &out);
}

#endif
