/*
** c7_automap.cpp
**
** Corridor 7's inset map panel.
**
** Native 320x200 panel and retail executable verification, November 2026:
** 64x64 at (256,0), one pixel per tile. Without a floor plan the wall
** bitmap is sampled in a 24x24 window, x aligned down to eight tiles.
** Geometry is independent of the live door/zone graph. A floor plan also
** reveals stationary/disguised aliens. Marker ramps are explicitly cycled
** because the port does not rotate the hardware DAC used by the DOS game.
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
static const int kMonsterColor = 224;
static const int kMineColor = 208;
static const int kWindowWidth = 24;
static const int kWindowHeight = 24;
static const int kWindowOffsetX = 12;
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

	// Border, then the interior. The interior is the background color that
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

	// The floor plan drops the sampling window and reveals every living alien.
	const bool fullmap = gamestate.fullmap ||
		player->FindInventory(ClassDef::FindClass("C7FloorPlan")) != NULL;

	int firstDrawX = 1, lastDrawX = lastX, firstDrawY = 1, lastDrawY = lastY;
	if(!fullmap)
	{
		firstDrawX = clamp(playerTX - kWindowOffsetX, 0, MAX(0, int(mapwidth) - kWindowWidth)) & ~7;
		firstDrawY = clamp(playerTY - kWindowOffsetY, 0, MAX(0, int(mapheight) - kWindowHeight));
		lastDrawX = MIN(lastX, firstDrawX + kWindowWidth - 1);
		lastDrawY = MIN(lastY, firstDrawY + kWindowHeight - 1);
		firstDrawX = MAX(1, firstDrawX);
		firstDrawY = MAX(1, firstDrawY);
	}

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
				solid = spot->tile != NULL || spot->corridor7MapSolidFloor;
				// Doors read as floor, not wall: the original paints the four
				// doors on level 1 in the background color even though they
				// are tiles. Same test the ECWolf automap uses.
				if(spot->tile && (spot->tile->offsetHorizontal || spot->tile->offsetVertical))
					solid = false;
				if(spot->corridor7WallMarker == 107)
					solid = false;
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

	// Native markers use animated red/yellow ramps. HUD Clear() does not
	// pass through the world renderer's palette-cycle shader.
	const int phase = (gamestate.TimeCount >> C7_RAMP_CYCLE_SHIFT) & 7;
	const ClassDef *mineClass = ClassDef::FindClass("C7ProximityMine");
	for(AActor::Iterator iter = AActor::GetIterator();iter.Next();)
	{
		AActor *const actor = iter;
		const bool mine = mineClass && actor->IsKindOf(mineClass);
		if(actor == player || (!(actor->flags & FL_ISMONSTER) && !mine) || actor->health <= 0)
			continue;
		if(!mine && !fullmap && actor->dir == nodir)
			continue;
		const int tx = actor->tilex, ty = actor->tiley;
		if(tx < firstDrawX || tx > lastDrawX || ty < firstDrawY || ty > lastDrawY)
			continue;
		FillPanelRun(px, py, pw, ph, tx, tx, ty, GPalette.Remap[(mine ? kMineColor : kMonsterColor) + phase]);
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
