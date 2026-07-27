/*
** c7_automap.cpp
**
** Corridor 7's inset map panel.
**
** Measured from the released game under DOSBox-X, at native 320x200 with the
** capture mapped back through the palette embedded in CORR7CD.EXE
** (tools/dosbox/capture_corridor7_automap.sh). Everything below that cites a
** number was read off those captures rather than guessed:
**
**   * The panel is 64x64 at the top-right of the view, screen (256,0)..(319,63)
**     in 320x200 space. One pixel border of palette index 32, interior filled
**     with index 48.
**   * The map is drawn one pixel per tile at a FIXED position: panel interior
**     pixel (i,j) is always map tile (i+1,j+1), so the 62x62 interior holds the
**     64x64 map minus its solid border ring. This was confirmed by the
**     alignment staying put across frames while the player moved.
**   * Within the painted region, grey (32) means the tile is solid and the
**     background (48) means it is floor. Correlating every grey pixel against
**     the raw MAPTEMP.CO7 plane-0 codes matched 100%, over both walls and
**     doors, so this is "has a tile" rather than any door/wall distinction.
**   * Only a 23x24 tile window around the player is painted; the rest of the
**     map stays background. This is not fog of war -- exploring did not grow
**     the painted region, and rows that had been painted stopped being painted
**     once the player moved away, which a reveal can never do.
**   * The player is index 63 at their own tile, with a second pixel of index 60
**     one tile BEHIND them (opposite their facing). At spawn, facing east from
**     (7,31), that trailing pixel sat at (6,31).
**
** One detail is measured only as a bound. The window's vertical origin is
** exactly player_y-12 (two independent samples, and a two-tile walk moved the
** painted band by exactly two rows). Horizontally every sample sat against the
** left clamp, which only proves the offset is at least 14; walking from x=7 to
** x=15 never scrolled it. kWindowOffsetX below is that lower bound, so it
** reproduces every frame captured. Confirming it needs a level wide enough to
** walk far from the left edge, which the debug warp would give us once
** capture_corridor7_planes.sh works headlessly.
*/

#include "actor.h"
#include "c7_automap.h"
#include "gamemap.h"
#include "g_shared/a_inventory.h"
#include "id_ca.h"
#include "r_data/colormaps.h"
#include "thingdef/thingdef.h"
#include "v_video.h"
#include "wl_agent.h"
#include "wl_game.h"
#include "wl_def.h"
#include "wl_draw.h"
#include "wl_iwad.h"
#include "wl_play.h"

// Panel placement in the original's 320x200 screen.
static const int kPanelX = 256;
static const int kPanelY = 0;
static const int kPanelSize = 64;

// Palette indices, straight from the captures.
static const int kBorderColor = 32;
static const int kFloorColor = 48;
static const int kWallColor = 32;
static const int kPlayerColor = 63;
static const int kPlayerTailColor = 60;
// Seen once on a wandering alien. It sits in the 224-231 ramp, one of the four
// the palette animation rotates, so it blinks without any work here.
static const int kMonsterColor = 226;

// Painted window around the player, in tiles.
static const int kWindowWidth = 23;
static const int kWindowHeight = 24;
static const int kWindowOffsetX = 14;
static const int kWindowOffsetY = 12;

static bool c7MapActive = false;

bool C7Map_Active()
{
	return c7MapActive;
}

void C7Map_Toggle()
{
	c7MapActive = !c7MapActive;
}

void C7Map_LevelReset()
{
	c7MapActive = false;
}

// Real-screen rectangle of the whole panel, so individual tile pixels can be
// derived from it by interpolation. Deriving them this way rather than scaling
// each pixel on its own keeps the panel gapless and seamless at any resolution.
static void PanelRect(int &x, int &y, int &w, int &h)
{
	x = kPanelX;
	y = kPanelY;
	w = kPanelSize;
	h = kPanelSize;
	screen->VirtualToRealCoordsInt(x, y, w, h, 320, 200, true, true);
}

// Fills panel-local pixels [i0,i1] on row j. Local coordinates run 0..63 over
// the whole panel, border included.
static void FillPanelRun(int px, int py, int pw, int ph, int i0, int i1, int j, int color)
{
	const int x0 = px + (i0*pw)/kPanelSize;
	const int x1 = px + ((i1+1)*pw)/kPanelSize;
	const int y0 = py + (j*ph)/kPanelSize;
	const int y1 = py + ((j+1)*ph)/kPanelSize;
	if(x1 <= x0 || y1 <= y0)
		return;
	screen->Clear(x0, y0, x1, y1, color, 0);
}

void C7Map_Draw()
{
	if(!c7MapActive || map == NULL || players[ConsolePlayer].mo == NULL)
		return;

	int px, py, pw, ph;
	PanelRect(px, py, pw, ph);
	if(pw <= 0 || ph <= 0)
		return;

	// Border, then the interior. The interior is the background colour that
	// unpainted tiles keep, so floor tiles need no work later.
	for(int j = 0;j < kPanelSize;++j)
	{
		if(j == 0 || j == kPanelSize-1)
			FillPanelRun(px, py, pw, ph, 0, kPanelSize-1, j, kBorderColor);
		else
		{
			FillPanelRun(px, py, pw, ph, 0, 0, j, kBorderColor);
			FillPanelRun(px, py, pw, ph, 1, kPanelSize-2, j, kFloorColor);
			FillPanelRun(px, py, pw, ph, kPanelSize-1, kPanelSize-1, j, kBorderColor);
		}
	}

	const unsigned int mapwidth = map->GetHeader().width;
	const unsigned int mapheight = map->GetHeader().height;
	if(mapwidth < 3 || mapheight < 3)
		return;

	// Tile (tx,ty) lands on panel-local pixel (tx,ty): interior pixel (i,j)
	// holds tile (i+1,j+1), and the interior starts one pixel in.
	const int lastX = int(mapwidth) - 2;
	const int lastY = int(mapheight) - 2;

	AActor *const player = players[ConsolePlayer].mo;
	const int playerTX = player->tilex;
	const int playerTY = player->tiley;

	// The floor plan reveals the whole level at once, so it simply drops the
	// window rather than widening it -- and it drops the reachability gate
	// below with it. A blueprint shows the floor's geometry, not where you can
	// currently walk; leaving the gate on made the plan look like it kept
	// expiring, because the gate is live (see below) and re-greyed everything
	// past a door the moment that door swung shut.
	const bool fullmap = gamestate.fullmap ||
		player->FindInventory(ClassDef::FindClass("C7FloorPlan")) != NULL;

	int firstDrawX = 1, lastDrawX = lastX, firstDrawY = 1, lastDrawY = lastY;
	if(!fullmap)
	{
		firstDrawX = clamp(playerTX - kWindowOffsetX, 1, MAX(1, lastX - kWindowWidth + 1));
		firstDrawY = clamp(playerTY - kWindowOffsetY, 1, MAX(1, lastY - kWindowHeight + 1));
		lastDrawX = MIN(lastX, firstDrawX + kWindowWidth - 1);
		lastDrawY = MIN(lastY, firstDrawY + kWindowHeight - 1);
	}

	// Floor only counts as floor if the player could currently walk to it: the
	// original paints grey for any area not linked to the one the player stands
	// in, so a room behind a shut door reads as solid until the door opens. That
	// is Wolf3D's zone graph, which Corridor 7 inherited and which ECWolf still
	// maintains for sound propagation. Without this, level 1's sealed side rooms
	// showed as open floor where the original showed wall.
	//
	// Note this is a live query, not a record of what has been seen: CheckLink
	// reads zoneLinks, which counts doors that are open right now. Reachability
	// therefore shrinks again whenever a door closes, which is why the floor
	// plan has to bypass it rather than merely widen the window.
	const GameMap::Zone *playerZone = map->GetSpot(playerTX, playerTY, 0)->zone;
	if(!fullmap && playerZone == NULL)
	{
		// Standing in a doorway puts the player on a door tile, and a door
		// belongs to no zone -- it is the link between two of them. CheckLink
		// answers false for a NULL zone, so every tile on the map read as
		// unreachable and the panel filled solid. Borrow a zone from a
		// neighbouring tile: the player can only be inside a door that is open,
		// and an open door links the zones on either side, so whichever of the
		// two is found first gives the same reachability set.
		static const int kAdjX[4] = { -1, 1, 0, 0 };
		static const int kAdjY[4] = { 0, 0, -1, 1 };
		for(int i = 0;i < 4 && playerZone == NULL;++i)
		{
			const int ax = playerTX + kAdjX[i];
			const int ay = playerTY + kAdjY[i];
			if(ax < 0 || ay < 0 || ax >= int(mapwidth) || ay >= int(mapheight))
				continue;
			playerZone = map->GetSpot(ax, ay, 0)->zone;
		}
	}
	TMap<const GameMap::Zone *, bool> zoneReachable;

	// Solid tiles as one run per stretch, so a row costs a handful of fills
	// instead of one per tile.
	for(int ty = firstDrawY;ty <= lastDrawY;++ty)
	{
		int runStart = -1;
		for(int tx = firstDrawX;tx <= lastDrawX+1;++tx)
		{
			bool solid = false;
			if(tx <= lastDrawX)
			{
				const MapSpot spot = map->GetSpot(tx, ty, 0);
				solid = spot->tile != NULL;
				// Doors read as floor, not wall: the original paints the four
				// doors on level 1 in the background colour even though they
				// are tiles. Same test the ECWolf automap uses.
				if(solid && (spot->tile->offsetHorizontal || spot->tile->offsetVertical))
					solid = false;
				else if(!solid && !fullmap)
				{
					const GameMap::Zone *const zone = spot->zone;
					if(zone == NULL)
						solid = true;
					else if(zone != playerZone)
					{
						bool *cached = zoneReachable.CheckKey(zone);
						if(cached == NULL)
						{
							const bool linked = map->CheckLink(playerZone, zone, true);
							zoneReachable[zone] = linked;
							solid = !linked;
						}
						else
							solid = !*cached;
					}
				}
			}
			if(solid && runStart < 0)
				runStart = tx;
			else if(!solid && runStart >= 0)
			{
				FillPanelRun(px, py, pw, ph, runStart, tx-1, ty, kWallColor);
				runStart = -1;
			}
		}
	}

	// Aliens. Without the floor plan only the ones already inside the painted
	// window show, which is what "monsters close to you" amounts to.
	//
	// The panel is a motion detector, not an X-ray. It paints aliens that are
	// moving, which is why the guide tells the player to read dot speed as a
	// rough species classifier, and why it warns that motionless actors and
	// still-disguised Bandors may not show up at all. Painting every living
	// alien gives away the two things the game deliberately hides: an ambush
	// waiting around a corner, and the filing cabinet that is about to unfold
	// into one.
	//
	// dir is the existing state that already answers this, so nothing new has
	// to be stored or saved: map setup leaves a standing actor at nodir and
	// only gives a direction to one placed on patrol, and an actor that wakes
	// gets a direction from SelectChaseDir on its first A_Chase.
	for(AActor::Iterator iter = AActor::GetIterator();iter.Next();)
	{
		AActor *const actor = iter;
		if(actor == player || !(actor->flags & FL_ISMONSTER) || actor->health <= 0)
			continue;
		if(actor->dir == nodir)
			continue;
		const int tx = actor->tilex, ty = actor->tiley;
		if(tx < firstDrawX || tx > lastDrawX || ty < firstDrawY || ty > lastDrawY)
			continue;
		FillPanelRun(px, py, pw, ph, tx, tx, ty, kMonsterColor);
	}

	// Player last so nothing can paint over it, with the trailing pixel one
	// tile opposite the way they are facing.
	static const int kTailX[8] = { -1, -1,  0,  1,  1,  1,  0, -1 };
	static const int kTailY[8] = {  0,  1,  1,  1,  0, -1, -1, -1 };
	const unsigned int octant = ((player->angle + ANGLE_45/2) / ANGLE_45) & 7;
	const int tailX = playerTX + kTailX[octant];
	const int tailY = playerTY + kTailY[octant];
	if(tailX >= firstDrawX && tailX <= lastDrawX && tailY >= firstDrawY && tailY <= lastDrawY)
		FillPanelRun(px, py, pw, ph, tailX, tailX, tailY, kPlayerTailColor);
	if(playerTX >= firstDrawX && playerTX <= lastDrawX &&
		playerTY >= firstDrawY && playerTY <= lastDrawY)
		FillPanelRun(px, py, pw, ph, playerTX, playerTX, playerTY, kPlayerColor);
}
