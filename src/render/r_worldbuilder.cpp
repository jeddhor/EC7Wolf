// ===========================================================================
//
// r_worldbuilder.cpp - backend-neutral static world geometry (Phase 5).
//
// ===========================================================================

#include "render/r_worldbuilder.h"
#include "render/r_dynamicwalls.h"
#include "wl_def.h"
#include "wl_game.h"
#include "wl_iwad.h"
#include "gamemap.h"
#include "id_ca.h"
#include "textures/textures.h"

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

	// One wall face of a 1x1 cell whose base (min) corner is at (bx,by). The base
	// is a float so a moving pushwall block can sit at a fractional position;
	// static walls pass integer tile coordinates. kind is WSURF_Wall for solid
	// walls or WSURF_Masked for colour-keyed (alpha-tested) walls -- the geometry
	// is identical; only the backend's transparency handling differs.
	//
	// The corner ORDER fixes the U direction (PushQuad puts u=0 on a/d, u=1 on b/c),
	// so it has to match the raycaster or that face's texture reads mirrored --
	// lettering runs backwards while the level layout still looks right. Both
	// software paths agree on the convention: HitVertWall / HitHorizWall for solid
	// walls (they invert the intercept on the East and North faces) and
	// GetMaskedWallEndpoints for masked ones. Per face:
	//     East  -> U runs -Y (north)    West  -> U runs +Y (south)
	//     North -> U runs -X (west)     South -> U runs +X (east)
	// Offset door leaves are the documented exception -- the raycaster skips the
	// inversion for them (the !offsetVertical / !offsetHorizontal guards), so their
	// quads are built separately in BuildDynamic and must not be "corrected" here.
	void PushWallFace(WorldMesh &out, int side, float bx, float by,
		const FTextureID &tex, int kind = WSURF_Wall)
	{
		const float sh = SideShade(side);
		switch(side)
		{
			case MapTile::East:	// +X face at x+1, U runs -Y (north)
				PushQuad(out,
					bx+1, by+1, 0,  bx+1, by,   0,
					bx+1, by,   1,  bx+1, by+1, 1,
					tex, kind, side, sh);
				break;
			case MapTile::West:	// -X face at x, U runs +Y (south)
				PushQuad(out,
					bx, by,   0,  bx, by+1, 0,
					bx, by+1, 1,  bx, by,   1,
					tex, kind, side, sh);
				break;
			case MapTile::North:	// -Y face at y (GetAdjacent(North) == y-1)
				PushQuad(out,
					bx+1, by, 0,  bx, by, 0,
					bx,   by, 1,  bx+1, by, 1,
					tex, kind, side, sh);
				break;
			case MapTile::South:	// +Y face at y+1 (GetAdjacent(South) == y+1)
				PushQuad(out,
					bx, by+1, 0,  bx+1, by+1, 0,
					bx+1, by+1, 1,  bx, by+1, 1,
					tex, kind, side, sh);
				break;
		}
		++out.wallFaces;
	}

	// Resolve the texture actually drawn for a wall side this frame. Mirrors
	// wl_draw.cpp's GetWallTexture: Corridor 7 force-field / animated walls
	// (corridor7WallMarker 1..3) cycle through four "C7Wnnnn" frames selected by
	// the game clock, so the barrier shimmers. Reading spot->texture[side]
	// directly would freeze that animation, so every wall path resolves through
	// here. Rebuilt each frame; a Phase 10 concern for static-mesh caching.
	FTextureID ResolveWallTexture(MapSpot spot, int side)
	{
		FTextureID texture = spot->texture[side];
		if(spot->corridor7WallMarker >= 1 && spot->corridor7WallMarker <= 3 &&
			spot->corridor7WallID > 0 && spot->corridor7WallID <= 253)
		{
			const unsigned int base = spot->corridor7WallID-1;
			const unsigned int frame =
				((gamestate.TimeCount/5)+(spot->corridor7WallMarker-1))&3;
			FString name;
			name.Format("C7W%04u", base+frame);
			const FTextureID animated =
				TexMan.CheckForTexture(name, FTexture::TEX_Wall);
			if(animated.isValid())
				texture = animated;
		}
		return texture;
	}

	// --- masked (colour-keyed) wall classification, mirroring wl_draw.cpp ---

	bool MaskedRaw(MapSpot s)
	{
		return s && s->tile && (s->maskedWallType || s->tile->renderMasked);
	}

	// A solid, opaque tile that fully occludes the neighbouring face. Doors,
	// pushwalls, and masked walls do NOT occlude (they are see-through or move
	// away), so a wall bordering them must still emit its face.
	bool IsSolidOccluder(MapSpot s)
	{
		return s && s->tile && !DynamicWalls::IsDynamicCell(s) &&
			!DynamicWalls::IsMaskedWallCell(s);
	}

	// Which sides of a masked tile are eligible surfaces (before connected-glass
	// merging). Offset (door) tiles are already excluded upstream.
	bool MaskedPassSide(MapSpot spot, int side)
	{
		if(!MaskedRaw(spot))
			return false;
		if(spot->tile->offsetVertical &&
			side != MapTile::West && side != MapTile::East)
			return false;
		if(spot->tile->offsetHorizontal &&
			side != MapTile::North && side != MapTile::South)
			return false;
		// In Corridor 7 a masked tile passes on every side so a fresh face is
		// drawn even where another masked pane abuts it; the connected-glass
		// merge below removes the internal boundaries.
		if(IWad::CheckGameFilter("Corridor7"))
			return true;
		MapSpot adj = spot->GetAdjacent((MapTile::Side)side);
		return !adj || !adj->tile;
	}

	// Two masked tiles form one continuous plane when they share the same map
	// marker (the same wall KIND). Their individual artwork page (corridor7WallID)
	// may differ: an observation-glass wall is built from varied panels (earth,
	// globe, monitors...) that must still merge into one plane, otherwise each
	// differing panel is an isolated cell that draws its perpendicular faces too
	// -- an extra pane of glass seen edge-on through the wall. Different markers
	// (e.g. a force-field door) stay separate. Outside C7 (no marker) adjacency is
	// enough.
	bool ConnectedMasked(MapSpot spot, int dir)
	{
		MapSpot other = spot->GetAdjacent((MapTile::Side)dir);
		if(!MaskedRaw(other))
			return false;
		return spot->corridor7WallMarker == other->corridor7WallMarker;
	}

	// The internal tile boundaries of a run of panes are not surfaces; drawing
	// them edge-on produces the periodic floor-to-ceiling lines seen down
	// glass-lined corridors, so they are culled here (matches the raycaster).
	bool MaskedRenderSide(MapSpot spot, int side)
	{
		if(!MaskedPassSide(spot, side))
			return false;
		const bool horizontalRun = ConnectedMasked(spot, MapTile::East) ||
			ConnectedMasked(spot, MapTile::West);
		const bool verticalRun = ConnectedMasked(spot, MapTile::North) ||
			ConnectedMasked(spot, MapTile::South);
		if(horizontalRun && !verticalRun &&
			(side == MapTile::East || side == MapTile::West))
			return false;
		if(verticalRun && !horizontalRun &&
			(side == MapTile::North || side == MapTile::South))
			return false;
		return true;
	}

	// --- Corridor 7 force-field door helpers (kept in sync with wl_draw.cpp) ---

	// 106 = active barrier, 107 = its permanently-open aperture. Both render as a
	// single centre pane on a track and carry no offset flag.
	bool IsForceFieldDoor(MapSpot spot)
	{
		return spot && spot->tile &&
			(spot->corridor7WallMarker == 106 || spot->corridor7WallMarker == 107);
	}

	// The axis is not stored, so derive it from open-neighbour topology (the pane
	// blocks the passage, so it sits perpendicular to whichever way the floor runs).
	bool ForceFieldDoorHorizontal(MapSpot spot)
	{
		const MapSpot n = spot->GetAdjacent(MapTile::North);
		const MapSpot s = spot->GetAdjacent(MapTile::South);
		const MapSpot ww = spot->GetAdjacent(MapTile::West);
		const MapSpot e = spot->GetAdjacent(MapTile::East);
		const int openNS = (!n || !n->tile) + (!s || !s->tile);
		const int openWE = (!ww || !ww->tile) + (!e || !e->tile);
		return openNS > openWE;	// passage N/S -> pane spans X, centred in Y
	}

	// C7's door track/jamb graphic (C7W0254), used on the jamb sides of every normal
	// door tile. Force-field door tiles carry the force-field art on all four sides,
	// so their jamb faces must substitute this fixed track instead.
	FTextureID C7DoorTrackTexture()
	{
		static FTextureID id = TexMan.CheckForTexture("C7W0254", FTexture::TEX_Wall);
		return id;
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
			// Doors, moving pushwalls, and masked (see-through) walls are built
			// by BuildDynamic / BuildMasked. Keep them out of the static mesh but
			// still emit the cell's floor/ceiling so the doorway (or vacated
			// pushwall cell) is not a hole. A masked full tile has no sector, so
			// PushFloorCeiling is a no-op there.
			if(DynamicWalls::IsDynamicCell(spot) ||
				DynamicWalls::IsMaskedWallCell(spot))
			{
				PushFloorCeiling(out, spot, fx, fy);
				continue;
			}

			// Solid wall cell: emit each face not fully occluded by its neighbour.
			// Only an opaque solid neighbour hides a face; doors, pushwalls, and
			// masked panes are see-through or move away, so the face behind them
			// (e.g. a doorjamb, or a wall seen through glass) is still drawn.
			for(int side = 0; side < 4; ++side)
			{
				MapSpot adj = spot->GetAdjacent((MapTile::Side)side);
				if(IsSolidOccluder(adj))
					continue;	// neighbor is opaque solid: face hidden

				// Doorjamb texture, mirroring wl_draw.cpp HitVertWall /
				// HitHorizWall: when the neighbour across this face is a door of
				// the perpendicular orientation, the jamb shows the door track
				// texture, not the frame tile's own wall texture. A normal door
				// carries the track (C7W0254) on its own jamb sides; a force-field
				// door carries force-field art on all sides, so it substitutes the
				// fixed track texture instead.
				MapSpot texSpot = spot;
				bool forceFieldJamb = false;
				if(adj && adj->tile)
				{
					const bool ns = (side == MapTile::North ||
						side == MapTile::South);
					const bool doorV = (adj->tile->offsetVertical &&
							!adj->tile->offsetHorizontal) ||
						(IsForceFieldDoor(adj) && !ForceFieldDoorHorizontal(adj));
					const bool doorH = (adj->tile->offsetHorizontal &&
							!adj->tile->offsetVertical) ||
						(IsForceFieldDoor(adj) && ForceFieldDoorHorizontal(adj));
					if((ns && doorV) || (!ns && doorH))
					{
						if(IsForceFieldDoor(adj))
							forceFieldJamb = true;
						else
							texSpot = adj;
					}
				}
				PushWallFace(out, side, fx, fy, forceFieldJamb ?
					C7DoorTrackTexture() : ResolveWallTexture(texSpot, side));
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
			const FTextureID tex = ResolveWallTexture(d.spot, MapTile::East);
			PushQuad(out,
				fx+0.5f, fy,   0,  fx+0.5f, fy+1, 0,
				fx+0.5f, fy+1, 1,  fx+0.5f, fy,   1,
				tex, WSURF_DoorLeaf, MapTile::East, 1.0f, d.style, amt);
			++out.wallFaces;
		}
		else
		{
			// Opens North/South: plane at y+0.5, U runs along X.
			const FTextureID tex = ResolveWallTexture(d.spot, MapTile::North);
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

// True when the camera lies on the outward side of this cell's `side` face, i.e.
// the face is nearest the viewer. Matches the raycaster, whose DDA only records a
// masked hit for the cell it enters (never the far side), so only the near face is
// ever drawn. bx/by are the cell's min corner in tile units.
bool MaskedFaceTowardCamera(int side, int bx, int by, float camX, float camY)
{
	switch(side)
	{
		case MapTile::East:  return camX > (float)(bx + 1);	// +X edge
		case MapTile::West:  return camX < (float)bx;		// -X edge
		case MapTile::North: return camY < (float)by;		// -Y edge
		default:             return camY > (float)(by + 1);	// South, +Y edge
	}
}

void BuildMasked(GameMap *gm, WorldMesh &out, float camX, float camY)
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
		if(!DynamicWalls::IsMaskedWallCell(spot))
			continue;

		const float fx = (float)x;
		const float fy = (float)y;

		// Force-field door: a single centre pane on a track (mirrors the software
		// GetMaskedWallEndpoints centre plane), not the four edge faces of a box.
		// 106 = active barrier, 107 = its permanently-open aperture (post animate).
		if(spot->corridor7WallMarker == 106 || spot->corridor7WallMarker == 107)
		{
			// A centre pane collapses its two opposite faces onto one plane, and
			// those faces carry OPPOSITE U directions (GetMaskedWallEndpoints), so
			// the raycaster mirrors the artwork depending on which side the ray
			// arrives from -- that is how the door's handle swaps sides as you walk
			// around it. Emitting one fixed winding pins the handle to one side and
			// reads as flipped from the other, so orient U by the camera's side.
			if(ForceFieldDoorHorizontal(spot))
			{
				// Plane at y+0.5: from the south the ray hits the South face (U +X),
				// from the north the North face (U -X).
				const bool south = camY > fy+0.5f;
				const float x1 = south ? fx   : fx+1;
				const float x2 = south ? fx+1 : fx;
				PushQuad(out, x1, fy+0.5f, 0, x2, fy+0.5f, 0,
					x2, fy+0.5f, 1, x1, fy+0.5f, 1,
					ResolveWallTexture(spot, MapTile::North), WSURF_Masked,
					MapTile::North, 1.0f);
			}
			else
			{
				// Plane at x+0.5: from the east the ray hits the East face (U -Y),
				// from the west the West face (U +Y).
				const bool east = camX > fx+0.5f;
				const float y1 = east ? fy+1 : fy;
				const float y2 = east ? fy   : fy+1;
				PushQuad(out, fx+0.5f, y1, 0, fx+0.5f, y2, 0,
					fx+0.5f, y2, 1, fx+0.5f, y1, 1,
					ResolveWallTexture(spot, MapTile::East), WSURF_Masked,
					MapTile::East, 1.0f);
			}
			++out.wallFaces;
			continue;
		}

		// A masked tile is a see-through box: emit its boundary faces exactly like
		// a solid wall (the same planes GetMaskedWallEndpoints uses for a
		// non-offset masked wall), but only on sides that survive the
		// connected-glass merge, and tagged WSURF_Masked so the backend alpha-
		// tests the colour key. The texture resolves the force-field animation.
		for(int side = 0; side < 4; ++side)
		{
			if(!MaskedRenderSide(spot, side))
				continue;
			// The raycaster draws only the masked face a ray reaches: never one
			// backed by a solid wall (no hit is ever recorded there), and only the
			// near side of a see-through cell (the DDA records the entered cell,
			// not the far boundary). Emitting the others wraps the texture onto the
			// sides of a solid opening or shows the far pane through the near one,
			// so a force-field/grate reads as a doubled box. Cull both here.
			if(IsSolidOccluder(spot->GetAdjacent((MapTile::Side)side)))
				continue;
			if(!MaskedFaceTowardCamera(side, (int)x, (int)y, camX, camY))
				continue;
			PushWallFace(out, side, fx, fy, ResolveWallTexture(spot, side),
				WSURF_Masked);
		}
	}
}

} // namespace WorldBuilder
