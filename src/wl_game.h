#ifndef __WL_GAME_H__
#define __WL_GAME_H__

#include "id_sd.h"
#include "textures/textures.h"

/*
=============================================================================

						WL_GAME DEFINITIONS

=============================================================================
*/

//---------------
//
// gamestate structure
//
//---------------

extern struct gametype
{
	char		mapname[9];
	const class SkillInfo *difficulty;
	const class ClassDef *playerClass[MAXPLAYERS];

	FTextureID  faceframe;

	short       secretcount,treasurecount,killcount,
				secrettotal,treasuretotal,killtotal;
	int32_t     TimeCount;
	bool        victoryflag;            // set during victory animations
	bool		fullmap;
	BYTE shotgunMinimum; // 0, 50 or 100; fixed by the authority for this game.
	// Corridor 7 Intruder Alert reach: 0 classic (the alarm is a noise heard
	// through open doors, as in DOS), 1 map-wide (heard everywhere). Fixed by
	// the authority for this game, like the shotgun rule.
	BYTE c7IntruderAlert;
	// Alien weapon pickups: 0 classic (capacity goes back to 100, even from
	// above it, as in DOS), 1 keep (a capacity above 100 is left alone; GitHub
	// #40). Fixed by the authority for this game.
	BYTE c7KeepAlienCapacity;
	// Original map errors: 0 classic (the DOS map data as shipped), 1 fixed
	// (known errors in it corrected; GitHub #51). Fixed by the authority.
	BYTE c7MapFixes;
} gamestate;

extern  char            demoname[13];

void    SetupGameLevel (void);
bool    GameLoop (void);
void    DrawPlayScreen (bool noborder=false);
void    DrawPlayBorderSides (void);

void    PlayDemo (int demonumber);
void    RecordDemo (void);

enum
{
	NEWMAP_KEEPFACING = 1,
	NEWMAP_KEEPPOSITION = 2
};
extern struct NewMap_t
{
	fixed x;
	fixed y;
	angle_t angle;
	int newmap;
	int flags;
} NewMap;

// JAB
#define PlaySoundLocMapSpot(s,spot)     PlaySoundLocGlobal(s,(((int32_t)spot->GetX() << TILESHIFT) + (1L << (TILESHIFT - 1))),(((int32_t)spot->GetY() << TILESHIFT) + (1L << (TILESHIFT - 1))),SD_GENERIC)
#define PlaySoundLocTile(s,tx,ty)       PlaySoundLocGlobal(s,(((int32_t)(tx) << TILESHIFT) + (1L << (TILESHIFT - 1))),(((int32_t)ty << TILESHIFT) + (1L << (TILESHIFT - 1))),SD_GENERIC)
#define PlaySoundLocActorBoss(s,ob)     PlaySoundLocActor(s,ob,SD_BOSSWEAPONS)
void PlaySoundLocActor(const char* s, AActor *ob, SoundChannel chan=SD_GENERIC);
bool C7SoundLocTooFar(fixed gx, fixed gy);
void PlaySoundLocGlobal(const char* s, fixed gx, fixed gy, SoundChannel chan=SD_GENERIC);
void UpdateSoundLoc(void);

#endif
