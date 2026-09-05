// WL_AGENT.C

#include <cmath>
#include <climits>

#include "doomerrors.h"
#include "wl_def.h"
#include "g_traversal.h"
#include "g_session.h"
#include "id_ca.h"
#include "id_sd.h"
#include "id_vl.h"
#include "id_vh.h"
#include "id_us.h"
#include "actor.h"
#include "thingdef/thingdef.h"
#include "lnspec.h"
#include "wl_agent.h"
#include "a_inventory.h"
#include "a_keys.h"
#include "m_random.h"
#include "g_mapinfo.h"
#include "thinker.h"
#include "wl_draw.h"
#include "wl_game.h"
#include "wl_iwad.h"
#include "wl_loadsave.h"
#include "wl_net.h"
#include "wl_state.h"
#include "g_perception.h"
#include "wl_play.h"
#include "templates.h"

#include "w_wad.h"
#include "scanner.h"

/*
=============================================================================

								LOCAL CONSTANTS

=============================================================================
*/

#define MAXMOUSETURN    10


#define MOVESCALE       150l
#define ANGLESCALE      20

/*
=============================================================================

								GLOBAL VARIABLES

=============================================================================
*/



//
// player state info
//
player_t		players[MAXPLAYERS];

void ClipMove (AActor *ob, int32_t xmove, int32_t ymove);
static void Thrust (APlayerPawn *player, angle_t angle, int32_t speed);

/*
=============================================================================

								GLOBAL VARIABLES

=============================================================================
*/

DBaseStatusBar *StatusBar;

DBaseStatusBar *CreateStatusBar_Blake();
DBaseStatusBar *CreateStatusBar_Wolf3D();

void DestroyStatusBar() { delete StatusBar; }
void CreateStatusBar()
{
	if(IWad::CheckGameFilter("Blake"))
		StatusBar = CreateStatusBar_Blake();
	else
		StatusBar = CreateStatusBar_Wolf3D();
	atterm(DestroyStatusBar);
}

/*
=============================================================================

								CONTROL STUFF

=============================================================================
*/

/*
======================
=
= CheckWeaponChange
=
= Keys 1-4 change weapons
=
======================
*/

void CheckWeaponChange (AActor *self)
{
	if(self->player->flags & player_t::PF_DISABLESWITCH)
		return;

	AWeapon *newWeapon = NULL;

	TicCmd_t &cmd = control[self->player->GetPlayerNum()];

	if(cmd.buttonstate[bt_nextweapon] && !cmd.buttonheld[bt_nextweapon])
	{
		newWeapon = self->player->weapons.PickNextWeapon(self->player);
		cmd.buttonheld[bt_nextweapon] = true;
	}
	else if(cmd.buttonstate[bt_prevweapon] && !cmd.buttonheld[bt_prevweapon])
	{
		newWeapon = self->player->weapons.PickPrevWeapon(self->player);
		cmd.buttonheld[bt_prevweapon] = true;
	}
	else
	{
		for(int i = 0;i <= 9;++i)
		{
			if(cmd.buttonstate[bt_slot0 + i] && !cmd.buttonheld[bt_slot0 + i])
			{
				newWeapon = self->player->weapons.Slots[i].PickWeapon(self->player);
				cmd.buttonheld[bt_slot0 + i] = true;
				break;
			}
		}
	}

	if(newWeapon && newWeapon != self->player->ReadyWeapon)
		self->player->PendingWeapon = newWeapon;
}


/*
=======================
=
= ControlMovement
=
= Changes the players's angle and position
=
=======================
*/

void ControlMovement (APlayerPawn *ob)
{
	if(playstate == ex_died)
		return;

	const unsigned int playernum = ob->player->GetPlayerNum();
	int controlx = control[playernum].controlx;
	int controly = control[playernum].controly;
	int controlstrafe = control[playernum].controlstrafe;

	int32_t oldx,oldy;
	angle_t angle;
	int strafe = controlstrafe;

	ob->player->thrustspeed = 0;

	oldx = ob->x;
	oldy = ob->y;

	//
	// side to side move
	//
	if (control[playernum].buttonstate[bt_strafe])
	{
		//
		// strafing
		//
		//
		strafe += controlx;
	}
	else
	{
		if(ob->player->ReadyWeapon && ob->player->ReadyWeapon->fovscale > 0)
			controlx = xs_ToInt(controlx*ob->player->ReadyWeapon->fovscale);

		//
		// not strafing
		//
		ob->angle -= controlx*(ANGLE_1/ANGLESCALE);
	}

	if(strafe)
	{
		// Cap the speed
		if (strafe > 100)
			strafe = 100;
		else if (strafe < -100)
			strafe = -100;

		strafe = FixedMul(ob->speed<<7, FixedMul(strafe, ob->sidemove[abs(strafe) >= RUNMOVE]));

		if (strafe > 0)
		{
			angle = ob->angle - ANGLE_90;
			Thrust (ob,angle,strafe*MOVESCALE);      // move to left
		}
		else if (strafe < 0)
		{
			angle = ob->angle + ANGLE_90;
			Thrust (ob,angle,-strafe*MOVESCALE);     // move to right
		}
	}

	//
	// forward/backwards move
	//
	if (controly < 0)
	{
		if(controly < -100)
			controly = -100;

		controly = FixedMul(ob->speed<<7, FixedMul(controly, ob->forwardmove[controly <= -RUNMOVE]));

		Thrust (ob,ob->angle,-controly*MOVESCALE); // move forwards
	}
	else if (controly > 0)
	{
		if(controly > 100)
			controly = 100;

		controly = FixedMul(ob->speed<<7, FixedMul(controly, ob->forwardmove[controly >= RUNMOVE]));

		angle = ob->angle + ANGLE_180;
		Thrust (ob,angle,controly*MOVESCALE*2/3);          // move backwards
	}

	// Running animation
	if (ob->player->thrustspeed)
	{
		if(ob->SeeState && ob->InStateSequence(ob->SpawnState))
			ob->SetState(ob->SeeState);
	}
	else
	{
		if(ob->SpawnState && ob->InStateSequence(ob->SeeState))
			ob->SetState(ob->SpawnState);
	}

	if (gamestate.victoryflag)              // watching the BJ actor
		return;
}

/*
===============
=
= GiveExtraMan
=
===============
*/

void player_t::GiveExtraMan (int amount)
{
	if (gamestate.difficulty->LivesCount >= 0)
	{
		lives += amount;
		if (lives < 0)
			lives = 0;
		else if(lives > 9)
			lives = 9;
	}
	PlaySoundLocActor ("misc/1up", mo);
}

/*
===============
=
= GivePoints
=
===============
*/

void player_t::GivePoints (int32_t points)
{
	score += FixedMul(points, gamestate.difficulty->ScoreMultiplier);
	while (score >= nextextra)
	{
		nextextra += EXTRAPOINTS;
		GiveExtraMan (1);
	}
}

/*
===============
=
= TakeDamage
=
===============
*/

// End the match when someone has won it.
//
// Evaluated on every machine from state every machine already agrees on -- a
// frag only changes when damage is applied, and damage is applied in the same
// tic everywhere -- so all of them end the match together without a packet
// being sent about it. Announcing it over the wire instead would put the
// decision on one machine and make everyone else wait for it.
static void CheckFragLimit()
{
	if(Net::InitVars.fragLimit == 0 || !Net::Deathmatch())
		return;

	const int limit = Net::InitVars.fragLimit;

	if(Net::InitVars.gameMode == Net::GM_TeamBattle)
	{
		for(byte team = 0;team < 2;++team)
		{
			if(Net::TeamFrags(team) >= limit)
			{
				Printf("Team %d reached the frag limit (%d).\n", team + 1, limit);
				playstate = ex_completed;
				return;
			}
		}
		return;
	}

	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
	{
		if(players[i].frags >= limit)
		{
			Printf("Player %u reached the frag limit (%d).\n", i + 1, limit);
			playstate = ex_completed;
			return;
		}
	}
}

static FRandom pr_damageplayer("PlayerTakeDamge");
void player_t::TakeDamage (int points, AActor *attacker)
{
	if (gamestate.victoryflag)
		return;
	points = (points*gamestate.difficulty->DamageFactor)>>FRACBITS;

	// Corridor 7 applies its timed invulnerability and body armor after the
	// rank damage multiplier. Armor absorbs the same half of the hit that is
	// removed from health, matching the released DOS executable.
	if (IWad::CheckGameFilter("Corridor7") && !godmode)
	{
		AInventory *invulnerability = mo->FindInventory(ClassDef::FindClass("C7Invulnerability"));
		if (invulnerability && invulnerability->amount > 0)
			return;

		AInventory *armor = mo->FindInventory(ClassDef::FindClass("C7BodyArmor"));
		if (armor && armor->amount > 0)
		{
			points >>= 1;
			if (armor->amount > (unsigned int)points)
				armor->amount -= points;
			else
				armor->amount = 0;
		}
	}
	NetDPrintf("%s %d points\n", __FUNCTION__, points);

	// Getting hurt is audible, and dying more so. Emitted from the damage
	// path rather than from wherever the sample is played, so a server with no
	// sound still produces the event.
	if(mo != NULL && points > 0)
		Perception::Emit(health - points <= 0 ? Perception::SoundKind::Death
			: Perception::SoundKind::Pain, mo, health - points <= 0 ? 20 : 12);

	if (!godmode)
		mo->health = health -= points;

	if (godmode != 2 && Session::IsLocalViewSlot(GetPlayerNum()))
		StartDamageFlash (points);

	// Bonus floors are point runs, not lives. When the player's health expires,
	// the DOS game awards the run and advances to the next campaign floor. End
	// the level while the traveling pawn is still alive so score, weapons,
	// access cards, and bonus pickups survive the transition.
	if (health<=0 && IWad::CheckGameFilter("Corridor7") && levelInfo->BonusLevel)
	{
		health = mo->health = mo->SpawnHealth();
		killerobj = NULL;
		playstate = ex_completed;
		if (points > 0)
			PlaySoundLocActor("player/pain", mo);
		StatusBar->UpdateFace(points);
		StatusBar->DrawStatusBar();
		return;
	}

	if (health<=0)
	{
		mo->target = attacker;
		mo->Die();
		health = 0;
		killerobj = attacker;

		if(attacker && attacker->player)
		{
			if(attacker == mo)
				--frags;
			else
				++attacker->player->frags;

			CheckFragLimit();
		}
	}
	else
	{
		if(mo->PainState && pr_damageplayer() < mo->painchance)
			mo->SetState(mo->PainState);
	}

	if (points > 0)
		PlaySoundLocActor("player/pain", mo);

	StatusBar->UpdateFace(points);
	StatusBar->DrawStatusBar();
}

/*
=============================================================================

								MOVEMENT

=============================================================================
*/

/*
===================
=
= TryMove
=
= returns true if move ok
= debug: use pointers to optimize
===================
*/

static int32_t c7LastElectricDamageTic[MAXPLAYERS];

// The Invulnerability Sphere's timer. player_t::TakeDamage checks this too, but
// Corridor 7's contact hazards do not all go through it -- the energized walls
// subtract from the health counter directly, which is what the released
// executable does -- so the ones that bypass it have to ask here.
bool C7IsInvulnerable(APlayerPawn *pawn)
{
	if(!pawn || !pawn->player || !IWad::CheckGameFilter("Corridor7"))
		return false;
	AInventory *sphere = pawn->FindInventory(ClassDef::FindClass("C7Invulnerability"));
	return sphere && sphere->amount > 0;
}

static void DamageC7ElectricField(APlayerPawn *pawn, AActor *source)
{
	if(!pawn || !pawn->player || pawn->player->health <= 0)
		return;
	// Immunity is immunity: no damage, and no zap sound or shock palette
	// either, because neither of those is anything but a reaction to being
	// hurt. Leaving them in also stamped the shock DAC over the sphere's own
	// yellow strobe every half second while the player leaned on a wall.
	if(C7IsInvulnerable(pawn))
		return;
	const int playerNumber = pawn->player->GetPlayerNum();
	// A controlled DOSBox capture of the released game measured sample-13
	// zaps roughly twice per second while the player pushed through an
	// energized barrier, each removing 2 points. Match that cadence instead
	// of retriggering every game tic.
	static const int32_t C7_ELECTRIC_DAMAGE_INTERVAL = 35;
	if(playerNumber < 0 || playerNumber >= MAXPLAYERS)
		return;
	const int32_t sinceLastZap =
		gamestate.TimeCount - c7LastElectricDamageTic[playerNumber];
	if(c7LastElectricDamageTic[playerNumber] != 0 &&
		sinceLastZap >= 0 && sinceLastZap < C7_ELECTRIC_DAMAGE_INTERVAL)
	{
		return;
	}

	c7LastElectricDamageTic[playerNumber] = gamestate.TimeCount;
	PlaySoundLocActor("c7/electric/damage", pawn);
	// The released executable subtracts a flat 2 points per zap directly from
	// the health counter, before and independent of the rank multiplier and
	// body armor, honoring only god mode. Routing this through DamageActor
	// with the pawn as its own attacker also tripped the friendly-fire guard,
	// which silently discarded the damage entirely.
	if(!godmode)
	{
		pawn->player->mo->health = pawn->player->health -= 2;
		if(pawn->player->health <= 0)
			pawn->player->TakeDamage(0, NULL);
	}
	if(Session::IsLocalViewSlot(playerNumber))
		StartC7ElectricFlash();
}

static int32_t c7LastLaserDamageTic[MAXPLAYERS];

// Contact with a laser barrier static (map objects 28/84, the strategy
// guide's "Infrared Invisible Barrier") deals the released executable's
// 10-point invisible-barrier damage through the standard rank/armor path,
// repeating on a cooldown while the player keeps pressing into the beams.
static void DamageC7LaserBarrier(APlayerPawn *pawn)
{
	if(!pawn || !pawn->player || pawn->player->health <= 0)
		return;
	static const int32_t C7_LASER_DAMAGE_INTERVAL = 64;
	const int playerNumber = pawn->player->GetPlayerNum();
	if(playerNumber < 0 || playerNumber >= MAXPLAYERS)
		return;
	const int32_t sinceLastZap =
		gamestate.TimeCount - c7LastLaserDamageTic[playerNumber];
	if(c7LastLaserDamageTic[playerNumber] != 0 &&
		sinceLastZap >= 0 && sinceLastZap < C7_LASER_DAMAGE_INTERVAL)
	{
		return;
	}
	c7LastLaserDamageTic[playerNumber] = gamestate.TimeCount;
	PlaySoundLocActor("c7/electric/damage", pawn);
	// Walking into it is the honest way to find one. The fact goes to whoever
	// it happened to and to nobody else.
	Perception::NoteHazardContact(pawn);
	pawn->player->TakeDamage(10, NULL);
}

// Standing in the beams has to hurt as much as walking into them. The contact
// test in TryMove is not enough on its own: TryMove is only reached from
// Thrust, and Thrust only runs while an input is actually moving the player, so
// someone who stepped into a barrier and stopped took the first zap and then
// nothing at all. A barrier is not a wall to lean on -- which is what the 6/14
// electric fields are, and why their contact damage belongs in TryMove where it
// is -- it is a volume the player stands inside, so the overlap has to be
// retested every tic regardless of movement.
//
// Both paths funnel through DamageC7LaserBarrier, so its cooldown is what sets
// the rate and the two cannot double up on a tic where the player both moves
// and is standing in the beams.
void C7TouchLaserBarriers(APlayerPawn *pawn)
{
	if(!pawn || noclip || !IWad::CheckGameFilter("Corridor7"))
		return;

	for(AActor::Iterator iter = AActor::GetIterator();iter.Next();)
	{
		AActor *check = iter;
		if(check == pawn || !Corridor7IsLaserBarrierActor(check))
			continue;

		const fixed r = check->radius + pawn->radius;
		if(abs(pawn->x - check->x) <= r && abs(pawn->y - check->y) <= r)
		{
			DamageC7LaserBarrier(pawn);
			return;
		}
	}
}

// The three things only a real move may do. The geometry that decides whether
// the move happens at all lives in g_traversal.cpp, and is the same code a
// navigator asks -- which is the point: a graph that predicts movement
// differently from ClipMove is not a graph, it is a second opinion.
namespace
{
	struct MoveEffects
	{
		AActor *ob;
	};

	void OnWallBlocked(void *context, MapSpot spot)
	{
		MoveEffects *fx = (MoveEffects *)context;
		// Corridor 7's original collision routine applies the electric contact
		// effect to wall tile IDs 6 and 14. The plane-one marker is not part
		// of that decision. The barriers stay solid: pressing against one zaps
		// the player on contact, and again on every repeated contact, but
		// never lets them through.
		if(IWad::CheckGameFilter("Corridor7") && fx->ob->player &&
			(spot->corridor7WallID == 6 || spot->corridor7WallID == 14))
		{
			DamageC7ElectricField(static_cast<APlayerPawn *>(fx->ob), fx->ob);
		}
	}

	void OnOverlap(void *context, AActor *other)
	{
		MoveEffects *fx = (MoveEffects *)context;
		// The laser barrier statics (map objects 28/84) never block movement:
		// walking through the hidden beams zaps the player through the
		// standard rank/armor damage path on a cooldown, exactly as the
		// released game does.
		if(fx->ob->player && Corridor7IsLaserBarrierActor(other))
			DamageC7LaserBarrier(static_cast<APlayerPawn *>(fx->ob));
		other->Touch(fx->ob);
	}
}

static bool TryMove (AActor *ob)
{
	if (noclip)
	{
		return (ob->x-ob->radius >= 0 && ob->y-ob->radius >= 0
			&& ob->x+ob->radius < (((int32_t)(map->GetHeader().width))<<TILESHIFT)
			&& ob->y+ob->radius < (((int32_t)(map->GetHeader().height))<<TILESHIFT) );
	}

	Traversal::Body body;
	body.radius = ob->radius;
	body.isPlayer = ob->player != NULL;
	body.ignore = ob;

	MoveEffects fx = { ob };
	Traversal::Hooks hooks;
	hooks.onWallBlocked = OnWallBlocked;
	hooks.onOverlap = OnOverlap;
	hooks.context = &fx;

	return Traversal::CheckPositionAt(body, ob->x, ob->y, &hooks);
}

static void ExecuteWalkTriggers(AActor *ob, MapSpot spot, MapTrigger::Side dir)
{
	if(!spot)
		return;

	for(unsigned int i = spot->triggers.Size();i-- > 0;)
	{
		MapTrigger &trigger = spot->triggers[i];
		if(trigger.playerCross && trigger.activate[dir])
			map->ActivateTrigger(trigger, dir, ob);
	}
}

static void CheckWalkTriggers(AActor *ob, int32_t xmove, int32_t ymove)
{
	MapSpot spot;

	if(ob->fracx <= abs(xmove) || ob->fracx >= 0xFFFF-abs(xmove))
	{
		spot = map->GetSpot((ob->x-xmove)>>FRACBITS, ob->y>>FRACBITS, 0);
		if(xmove > 0)
			ExecuteWalkTriggers(ob, spot->GetAdjacent(MapTile::East), MapTrigger::West);
		else if(xmove < 0)
			ExecuteWalkTriggers(ob, spot->GetAdjacent(MapTile::West), MapTrigger::East);
	}

	if(ob->fracy <= abs(ymove) || ob->fracy >= 0xFFFF-abs(ymove))
	{
		spot = map->GetSpot(ob->x>>FRACBITS, (ob->y-ymove)>>FRACBITS, 0);
		if(ymove > 0)
			ExecuteWalkTriggers(ob, spot->GetAdjacent(MapTile::South), MapTrigger::North);
		else if(ymove < 0)
			ExecuteWalkTriggers(ob, spot->GetAdjacent(MapTile::North), MapTrigger::South);
	}
}


/*
===================
=
= ClipMove
=
===================
*/

void ClipMove (AActor *ob, int32_t xmove, int32_t ymove)
{
	fixed basex = ob->x;
	fixed basey = ob->y;

	ob->x = basex+xmove;
	ob->y = basey+ymove;

	if (TryMove (ob))
	{
		CheckWalkTriggers(ob, xmove, ymove);
		return;
	}

	// Corridor 7 only plays its failure cue for an explicit Use action. The
	// Wolf3D collision thump sounds like that cue and made every harmless bump
	// into scenery produce a false alert.
	if (!IWad::CheckGameFilter("Corridor7") && !SD_SoundPlaying())
		PlaySoundLocActor ("world/hitwall", ob);

	ob->x = basex+xmove;
	ob->y = basey;
	if (TryMove (ob))
	{
		CheckWalkTriggers(ob, xmove, 0);
		return;
	}

	ob->x = basex;
	ob->y = basey+ymove;
	if (TryMove (ob))
	{
		CheckWalkTriggers(ob, 0, ymove);
		return;
	}

	ob->x = basex;
	ob->y = basey;
}

//==========================================================================

/*
===================
=
= Thrust
=
===================
*/

static void Thrust (APlayerPawn *player, angle_t angle, int32_t speed)
{
	static const int MAXTHRUST = 0x5800l * 2;
	int32_t xmove,ymove;

	//
	// ZERO FUNNY COUNTER IF MOVED!
	//
	if (speed)
		funnyticount = 0;

	player->player->thrustspeed += speed;
	//
	// moving bounds speed
	//
	if (speed >= MAXTHRUST)
		speed = MAXTHRUST-1;

	xmove = FixedMul(speed,finecosine[angle>>ANGLETOFINESHIFT]);
	ymove = -FixedMul(speed,finesine[angle>>ANGLETOFINESHIFT]);

	ClipMove(player,xmove,ymove);

	player->EnterZone(map->GetSpot(player->tilex, player->tiley, 0)->zone);
}


/*
=============================================================================

								ACTIONS

=============================================================================
*/

//===========================================================================

/*
===============
=
= Cmd_Use
=
===============
*/

void APlayerPawn::Cmd_Use()
{
	if(TryUseC7HealthChamber())
		return;

	int     checkx,checky;
	MapTrigger::Side direction;

	//
	// find which cardinal direction the player is facing
	//
	if (angle < ANGLE_45 || angle > 7*ANGLE_45)
	{
		checkx = tilex + 1;
		checky = tiley;
		direction = MapTrigger::West;
	}
	else if (angle < 3*ANGLE_45)
	{
		checkx = tilex;
		checky = tiley-1;
		direction = MapTrigger::South;
	}
	else if (angle < 5*ANGLE_45)
	{
		checkx = tilex - 1;
		checky = tiley;
		direction = MapTrigger::East;
	}
	else
	{
		checkx = tilex;
		checky = tiley + 1;
		direction = MapTrigger::North;
	}

	bool doNothing = true;
	bool isRepeatable = false;
	BYTE lastTrigger = 0;
	MapSpot spot = map->GetSpot(checkx, checky, 0);
	for(unsigned int i = 0;i < spot->triggers.Size();++i)
	{
		MapTrigger &trig = spot->triggers[i];
		if(trig.activate[direction] && trig.playerUse)
		{
			if(map->ActivateTrigger(trig, direction, this))
			{
				isRepeatable |= trig.repeatable;
				lastTrigger = trig.action;
				doNothing = false;
			}
		}
	}

	if(doNothing)
		PlaySoundLocActor("misc/do_nothing", this);
	else
		P_ChangeSwitchTexture(spot, static_cast<MapTile::Side>(direction), isRepeatable, lastTrigger);
}

/*
=============================================================================

								PLAYER CONTROL

=============================================================================
*/

player_t::player_t() : levelShotsFired(0), levelShotsHit(0), c7MuzzleFlashTics(0),
	c7ApparitionTics(0),
	c7ChamberX(-1), c7ChamberY(-1), c7ChamberPower(100), c7ChamberTics(0),
	c7ChamberState(0), c7ClearanceNotified(false), c7FloorSecuredNotified(false),
	FOV(90), DesiredFOV(90), bob(0), attackheld(false)
{
}

// P_BobWeapon From ZDoom
//============================================================================
//
// P_BobWeapon
//
// [RH] Moved this out of A_WeaponReady so that the weapon can bob every
// tic and not just when A_WeaponReady is called. Not all weapons execute
// A_WeaponReady every tic, and it looks bad if they don't bob smoothly.
//
// [XA] Added new bob styles and exposed bob properties. Thanks, Ryan Cordell!
//
//============================================================================

void player_t::BobWeapon (fixed *x, fixed *y)
{
	AWeapon *weapon;

	weapon = ReadyWeapon;

	if (weapon == NULL || weapon->weaponFlags & WF_DONTBOB)
	{
		*x = *y = 0;
		return;
	}

	// [XA] Get the current weapon's bob properties.
	int bobstyle = weapon->BobStyle;
	int bobspeed = (weapon->BobSpeed * 128) >> 16;
	fixed rangex = weapon->BobRangeX;
	fixed rangey = weapon->BobRangeY;

	// Bob the weapon based on movement speed.
	int angle = (bobspeed*35/TICRATE*gamestate.TimeCount)&FINEMASK;
	fixed curbob = (flags & PF_WEAPONBOBBING) ? bob : 0;

	if (curbob != 0)
	{
		fixed_t bobx = FixedMul(curbob, rangex);
		fixed_t boby = FixedMul(curbob, rangey);
		switch (bobstyle)
		{
		case AWeapon::BobNormal:
			*x = FixedMul(bobx, finecosine[angle]);
			*y = FixedMul(boby, finesine[angle & (FINEANGLES/2-1)]);
			break;

		case AWeapon::BobInverse:
			*x = FixedMul(bobx, finecosine[angle]);
			*y = boby - FixedMul(boby, finesine[angle & (FINEANGLES/2-1)]);
			break;

		case AWeapon::BobAlpha:
			*x = FixedMul(bobx, finesine[angle]);
			*y = FixedMul(boby, finesine[angle & (FINEANGLES/2-1)]);
			break;

		case AWeapon::BobInverseAlpha:
			*x = FixedMul(bobx, finesine[angle]);
			*y = boby - FixedMul(boby, finesine[angle & (FINEANGLES/2-1)]);
			break;

		case AWeapon::BobSmooth:
			*x = FixedMul(bobx, finecosine[angle]);
			*y = (boby - FixedMul(boby, finecosine[angle*2 & (FINEANGLES-1)])) / 2;
			break;

		case AWeapon::BobInverseSmooth:
			*x = FixedMul(bobx, finecosine[angle]);
			*y = (FixedMul(boby, finecosine[angle*2 & (FINEANGLES-1)]) + boby) / 2;
			break;

		case AWeapon::BobThrust:
			{
				*x = 0;

				// Down thrust is faster than up
				// Blake Stone uses a linearly increasing velocity,
				// we use a sin table since it's available and requires no extra storage
				const int thrustPosition = (((angle<<3)*3)&(FRACUNIT-1)) * 3;
				if(thrustPosition < FRACUNIT*2)
					*y = -FixedMul(boby, thrustPosition - finesine[(thrustPosition/2)>>5] - FRACUNIT/2);
				else
					*y = FixedMul(boby, finesine[(thrustPosition - FRACUNIT*2)>>5] - FRACUNIT/2);
			}
			break;
		}
	}
	else
	{
		*x = 0;
		*y = 0;
	}
}

const fixed RAISERANGE = 96*FRACUNIT;
const fixed RAISESPEED = FRACUNIT*6;

void player_t::BringUpWeapon()
{
	if(PendingWeapon == WP_NOCHANGE)
	{
		SetPSprite(ReadyWeapon ? ReadyWeapon->GetReadyState() : NULL, player_t::ps_weapon);
		return;
	}

	psprite[player_t::ps_weapon].sy = RAISERANGE;
	psprite[player_t::ps_weapon].sx = 0;

	ReadyWeapon = PendingWeapon;
	PendingWeapon = WP_NOCHANGE;
	SetPSprite(ReadyWeapon ? ReadyWeapon->GetUpState() : NULL, player_t::ps_weapon);
}
ACTION_FUNCTION(A_Lower)
{
	player_t *player = self->player;

	player->psprite[player_t::ps_weapon].sy += RAISESPEED;
	if(player->psprite[player_t::ps_weapon].sy < RAISERANGE)
		return false;
	player->psprite[player_t::ps_weapon].sy = RAISERANGE;

	if(player->PendingWeapon == WP_NOCHANGE)
		player->PendingWeapon = NULL;

	player->SetPSprite(NULL, player_t::ps_flash);
	// If we're dead, don't bother trying to raise a weapon.
	// In fact, we want to keep the current weapon "up" so that the status bar
	// displays the correct information.
	if(player->state != player_t::PST_DEAD)
		player->BringUpWeapon();
	else
		player->SetPSprite(NULL, player_t::ps_weapon);
	return true;
}
ACTION_FUNCTION(A_Raise)
{
	player_t *player = self->player;

	if(player->PendingWeapon != WP_NOCHANGE)
	{
		player->SetPSprite(player->ReadyWeapon->GetDownState(), player_t::ps_weapon);
		return false;
	}

	player->psprite[player_t::ps_weapon].sy -= RAISESPEED;
	if(player->psprite[player_t::ps_weapon].sy > 0)
		return false;
	player->psprite[player_t::ps_weapon].sy = 0;

	if(player->ReadyWeapon)
		player->SetPSprite(player->ReadyWeapon->GetReadyState(), player_t::ps_weapon);
	else
		player->psprite[player_t::ps_weapon].frame = NULL;
	return true;
}

void player_t::DeathFade()
{
	if(ScreenFader)
		return; // Already setup

	if(Session::IsLocalViewSlot(GetPlayerNum()))
		FinishPaletteShifts();

	switch(gameinfo.DeathTransition)
	{
		case GameInfo::TRANSITION_Fizzle:
		{
			// Fizzle fade used a slightly darker shade of red.
			const byte fr = RPART(mo->damagecolor)*2/3;
			const byte fg = GPART(mo->damagecolor)*2/3;
			const byte fb = BPART(mo->damagecolor)*2/3;

			FFizzleFader* fader = new FFizzleFader(viewscreenx,viewscreeny,viewwidth,viewheight,70,false);
			fader->FadeToColor(fr, fg, fb);
			ScreenFader = fader;
			break;
		}

		case GameInfo::TRANSITION_Fade:
			ScreenFader = new FBlendFader(0, 255, 0, 0, 0, 64);
			break;
	}
}

void player_t::DeathFadeClear()
{
	if(ScreenFader)
		ScreenFader.Reset();

	switch(gameinfo.DeathTransition)
	{
		case GameInfo::TRANSITION_Fade:
			V_SetBlend(0, 0, 0, 0);
			break;

		case GameInfo::TRANSITION_Fizzle:
			break;
	}
}

// Finds the target closest to the player within shooting range.
AActor *player_t::FindTarget()
{
	//
	// find potential targets
	//

	int32_t viewdist = 0x7fffffffl;
	AActor *closest = NULL, *oldclosest = NULL;

	while (1)
	{
		oldclosest = closest;

		for(AActor::Iterator check = AActor::GetIterator();check.Next();)
		{
			if(check == mo)
				continue;

			if ((check->flags & FL_SHOOTABLE) &&
				Net::CanDamage(mo, check) &&
				mo->CheckVisibility(check, ANGLE_90/9))
			{
				const int dist = MAX(abs(check->x - mo->x), abs(check->y - mo->y));

				if(dist < viewdist)
				{
					viewdist = dist;
					closest = check;
				}
			}
		}

		if (closest == oldclosest)
			return NULL; // no more targets, all missed

		//
		// trace a line from player to enemey
		//
		if (CheckLine(closest, mo))
			break;
	}

	return closest;
}

size_t player_t::PropagateMark()
{
	GC::Mark(mo);
	GC::Mark(camera);
	GC::Mark(ReadyWeapon);
	if(PendingWeapon != WP_NOCHANGE)
		GC::Mark(PendingWeapon);
	return sizeof(*this);
}

void player_t::Reborn()
{
	ScreenFader.Reset();
	ReadyWeapon = NULL;
	PendingWeapon = WP_NOCHANGE;
	flags = 0;
	FOV = DesiredFOV;
	RespawnEligible = -1;
	c7MuzzleFlashTics = 0;
	c7ApparitionTics = 0;
	c7ChamberState = 0;
	c7ChamberTics = 0;

	if(state == PST_ENTER)
	{
		lives = gamestate.difficulty->LivesCount;
		score = oldscore = 0;
		nextextra = EXTRAPOINTS;
		frags = 0;
	}

	mo->GiveStartingInventory();
	health = mo->health;

	// Recalculate the projection here so that player classes with differing radii are supported.
	CalcProjection(mo->radius);
}

void player_t::Serialize(FArchive &arc)
{
	BYTE state = this->state;
	arc << state;
	this->state = static_cast<State>(state);

	arc << mo
		<< camera
		<< killerobj
		<< oldscore
		<< score
		<< nextextra
		<< lives
		<< health
		<< ReadyWeapon
		<< PendingWeapon
		<< flags
		<< extralight;

	for(unsigned int i = 0;i < NUM_PSPRITES;++i)
	{
		arc << psprite[i].frame
			<< psprite[i].ticcount
			<< psprite[i].sx
			<< psprite[i].sy;
	}

	if(GameSave::SaveProdVersion >= 0x001002FF && GameSave::SaveVersion > 1374729160)
		arc << FOV << DesiredFOV;

	if(GameSave::SaveVersion > 1672116695)
		arc << frags;
	else
		frags = 0;

	if(GameSave::SaveVersion > 1690159133)
		arc << RespawnEligible;
	else
		RespawnEligible = -1;

	// Per-floor Corridor 7 hit/miss statistics. The date gate preserves save
	// compatibility with builds made before these fields were added.
	if(GameSave::SaveVersion >= 1784147000ULL)
		arc << levelShotsFired << levelShotsHit;
	else
		levelShotsFired = levelShotsHit = 0;

	if(GameSave::SaveVersion >= 1784246700ULL)
		arc << c7MuzzleFlashTics << c7ChamberX << c7ChamberY
			<< c7ChamberPower << c7ChamberTics << c7ChamberState
			<< c7ClearanceNotified << c7FloorSecuredNotified;
	else
	{
		c7MuzzleFlashTics = c7ChamberTics = c7ChamberState = 0;
		c7ChamberX = c7ChamberY = -1;
		c7ChamberPower = 100;
		c7ClearanceNotified = c7FloorSecuredNotified = false;
	}

	if(GameSave::SaveVersion >= 1784319000ULL)
		arc << c7ApparitionTics;
	else
		c7ApparitionTics = 0;

	if(arc.IsLoading())
	{
		mo->SetupWeaponSlots();
		CalcProjection(mo->radius);
		DeathFadeClear();
	}
}

void player_t::SetPSprite(const Frame *frame, player_t::PSprite layer)
{
	flags &= ~(player_t::PF_READYFLAGS);
	psprite[layer].frame = frame;

	while(psprite[layer].frame)
	{
		if(psprite[layer].frame->offsetX != 0)
			psprite[layer].sx = psprite[layer].frame->offsetX;

		if(psprite[layer].frame->offsetY != 0)
			psprite[layer].sy = psprite[layer].frame->offsetY;

		psprite[layer].ticcount = psprite[layer].frame->GetTics();
		psprite[layer].frame->action(mo, ReadyWeapon, psprite[layer].frame);

		if(mo->player->flags & player_t::PF_WEAPONBOBBING)
			psprite[layer].sx = psprite[layer].sy = 0;

		if(psprite[layer].frame && psprite[layer].ticcount == 0)
			psprite[layer].frame = psprite[layer].frame->next;
		else
			break;
	}
}

void player_t::SetFOV(float newlyDesiredFOV)
{
	DesiredFOV = newlyDesiredFOV;

		// If they're not dead, holding a weapon, and the weapon has a non-zero scale, then we adjust the FOV
	if(state != player_t::PST_DEAD && ReadyWeapon != NULL && ReadyWeapon->fovscale != 0) 
	{
		FOV = -DesiredFOV * ReadyWeapon->fovscale;
		if(mo != NULL) CalcProjection(mo->radius);
	}
	else
	{
		FOV = DesiredFOV;
	}
}

void player_t::AdjustFOV()
{
	// [RH] Zoom the player's FOV
	float desired = DesiredFOV;

	// Adjust FOV using on the currently held weapon.
	if (state != player_t::PST_DEAD &&		// No adjustment while dead.
		ReadyWeapon != NULL &&				// No adjustment if no weapon.
		ReadyWeapon->fovscale != 0)			// No adjustment if the adjustment is zero.
	{

		// A negative scale is used to prevent G_AddViewAngle/G_AddViewPitch
		// from scaling with the FOV scale.
		desired *= fabsf(ReadyWeapon->fovscale);
	}

	if (FOV != desired)
	{
		// Negative FOV means recalculate projection
		if (FOV < 0)
		{
			FOV *= -1;
		}
		else if (fabsf(FOV - desired) < 7.f)
		{
			FOV = desired;
		}
		else
		{
			float zoom = MAX(7.f, fabsf(FOV - desired) * 0.025f);
			if (FOV > desired)
			{
				FOV = FOV - zoom;
			}
			else
			{
				FOV = FOV + zoom;
			}
		}

		CalcProjection(mo->radius);
	}
}

FArchive &operator<< (FArchive &arc, player_t *&player)
{
	return arc.SerializePointer(players, (BYTE**)&player, sizeof(players[0]));
}

/*
===============
=
= CheckSpawnPlayer
=
= Look for any players waiting to be spawned
=
===============
*/

void CheckSpawnPlayer(bool setup)
{
	for(unsigned int p = 0;p < Session::ActiveSlotCount();++p)
	{
		if(setup || players[p].state == player_t::PST_ENTER || players[p].state == player_t::PST_REBORN)
		{
			SpawnPlayer(p);
			if(players[p].mo == NULL)
			{
				FString err;
				err.Format("No player %u start!", p+1);
				throw CRecoverableError(err);
			}
		}
	}
}

/*
===============
=
= SpawnPlayer
=
===============
*/

void SpawnPlayer (int num)
{
	const GameMap::PlayerSpawn *spot = map->GetPlayerSpawn(num);
	if(spot == NULL)
		return;

	player_t &player = players[num];

	if(player.state == player_t::PST_REBORN && player.mo) // Detach from previous pawn if it exists
	{
		player.mo->player = NULL;
		player.mo->SetPriority(ThinkerList::NORMAL);
	}

	player.mo = (APlayerPawn *) AActor::Spawn(gamestate.playerClass[num], spot->x, spot->y, 0, 0);
	player.mo->angle = spot->angle*ANGLE_1;
	player.mo->player = &player;
	Thrust (player.mo,0,0); // set some variables
	player.mo->SetPriority(ThinkerList::PLAYER);

	if(player.state == player_t::PST_ENTER || player.state == player_t::PST_REBORN)
		player.Reborn();

	player.camera = player.mo;
	player.state = player_t::PST_LIVE;
	player.extralight = 0;

	// Re-raise the weapon like Doom if we don't have the flag set in mapinfo.
	if(!levelInfo->SpawnWithWeaponRaised && player.PendingWeapon == WP_NOCHANGE)
		player.PendingWeapon = player.ReadyWeapon;
	player.BringUpWeapon();
}


//===========================================================================

/*
===============
=
= T_KnifeAttack
=
= Update player hands, and try to do damage when the proper frame is reached
=
===============
*/

static FRandom pr_cwpunch("CustomWpPunch");
ACTION_FUNCTION(A_CustomPunch)
{
	enum
	{
		CPF_USEAMMO = 1,
		CPF_ALWAYSPLAYSOUND = 2
	};

	ACTION_PARAM_INT(damage, 0);
	ACTION_PARAM_BOOL(norandom, 1);
	ACTION_PARAM_INT(flags, 2);
	ACTION_PARAM_STRING(pufftype, 3);
	ACTION_PARAM_DOUBLE(range, 4);
	ACTION_PARAM_FIXED(lifesteal, 5);

	player_t *player = self->player;
	if(player && IWad::CheckGameFilter("Corridor7"))
		++player->levelShotsFired;

	if(flags & CPF_ALWAYSPLAYSOUND)
		PlaySoundLocActor(player->ReadyWeapon->attacksound, self, self == players[ConsolePlayer].camera ? SD_WEAPONS : SD_GENERIC);
	if(range == 0)
		range = 64;

	if(!(player->ReadyWeapon->weaponFlags & WF_NOALERT))
	{
		madenoise = true;
		// The same fact, with a source, a place and a kind on it. madenoise is
		// one global boolean: no who, no where, no what, and no history.
		Perception::Emit(Perception::SoundKind::Weapon, self, 24);
	}

	// actually fire
	int dist = 0x7fffffff;
	AActor *closest = NULL;
	for(AActor::Iterator check = AActor::GetIterator();check.Next();)
	{
		if(check == self)
			continue;

		if((check->flags & FL_SHOOTABLE) &&
			Net::CanDamage(self, check) &&
			self->CheckVisibility(check, ANGLE_90/9))
		{
			const int checkdist = MAX(abs(check->x - self->x), abs(check->y - self->y));

			if (checkdist < dist)
			{
				dist = checkdist;
				closest = check;
			}
		}
	}

	if (!closest || dist-(FRACUNIT/2) > (range/64)*FRACUNIT)
	{
		// missed
		return false;
	}

	if(!norandom)
		damage *= pr_cwpunch()%8 + 1;

	// hit something
	if(IWad::CheckGameFilter("Corridor7"))
		++player->levelShotsHit;
	if(!(flags & CPF_ALWAYSPLAYSOUND))
		PlaySoundLocActor(player->ReadyWeapon->attacksound, self, self == players[ConsolePlayer].camera ? SD_WEAPONS : SD_GENERIC);
	DamageActor(closest, self, damage);

	// Ammo is only used when hit
	if(flags & CPF_USEAMMO)
	{
		if(!player->ReadyWeapon->DepleteAmmo())
			return true;
	}

	if(lifesteal > 0 && player->health < self->health)
	{
		damage *= lifesteal;
		player->health += damage;
		if(player->health > self->health)
			player->health = self->health;
	}
	return true;
}

static FRandom pr_cwbullet("CustomWpBullet");
ACTION_FUNCTION(A_GunAttack)
{
	enum
	{
		GAF_NORANDOM = 1,
		GAF_NOAMMO = 2,
		GAF_MACDAMAGE = 4
	};

	player_t *player = self->player;
	int      dx,dy,dist;

	ACTION_PARAM_INT(flags, 0);
	ACTION_PARAM_STRING(sound, 1);
	ACTION_PARAM_FIXED(snipe, 2);
	ACTION_PARAM_INT(maxdamage, 3);
	ACTION_PARAM_INT(blocksize, 4);
	ACTION_PARAM_INT(pointblank, 5);
	ACTION_PARAM_INT(longrange, 6);
	ACTION_PARAM_INT(maxrange, 7);

	if(!(flags & GAF_NOAMMO))
	{
		if(!player->ReadyWeapon->DepleteAmmo())
			return false;
	}

	if(sound.Len() == 1 && sound[0] == '*')
		PlaySoundLocActor(player->ReadyWeapon->attacksound, self, self == players[ConsolePlayer].camera ? SD_WEAPONS : SD_GENERIC);
	else
		PlaySoundLocActor(sound, self, self == players[ConsolePlayer].camera ? SD_WEAPONS : SD_GENERIC);

	if(self->MeleeState)
		self->SetState(self->MeleeState);

	if(!(player->ReadyWeapon->weaponFlags & WF_NOALERT))
	{
		madenoise = true;
		// The same fact, with a source, a place and a kind on it. madenoise is
		// one global boolean: no who, no where, no what, and no history.
		Perception::Emit(Perception::SoundKind::Weapon, self, 24);
	}

	AActor *closest = player->FindTarget();
	if(!closest)
		return false;

	//
	// hit something
	//
	dx = abs(closest->x - self->x);
	dy = abs(closest->y - self->y);
	dist = dx>dy ? dx:dy;

	dist = FixedMul(dist, snipe);
	dist /= blocksize<<9;

	int damage = flags & GAF_NORANDOM ? maxdamage : (1 + (pr_cwbullet()%maxdamage));
	if (dist >= pointblank)
		damage = (flags & GAF_MACDAMAGE) ? damage >> 1 : damage * 2 / 3;
	if (dist >= longrange)
	{
		if ( (pr_cwbullet() % maxrange) < dist)           // missed
			return false;
	}
	DamageActor (closest, self, damage);
	return true;
}

// Corridor 7's released hitscan routine has weapon-specific falloff rather
// than Wolf3D's shared gun formula. The weapon number is the original index:
// 1 shotgun, 2 M-16, 3 M-343, 4 dual blaster, 6 assault cannon, and
// 7 disintegrator. Plasma (5) is a projectile and is defined in DECORATE.
static FRandom pr_c7bullet("Corridor7Bullet");

static void ConsumeC7AlienCharge(AActor *self, int currentCost, int capacityCost)
{
	AInventory *energy = self->FindInventory(ClassDef::FindClass("C7Energy"));
	AInventory *capacity = self->FindInventory(ClassDef::FindClass("C7EnergyCapacity"));
	// DepleteAmmo already consumed the first point.
	if(energy)
		energy->amount = energy->amount > static_cast<unsigned>(currentCost - 1) ?
			energy->amount - (currentCost - 1) : 0;
	if(capacity)
		capacity->amount = capacity->amount > static_cast<unsigned>(capacityCost) ?
			capacity->amount - capacityCost : 0;
}

ACTION_FUNCTION(A_C7GunAttack)
{
	player_t *player = self->player;
	ACTION_PARAM_INT(weapon, 0);

	if(!player || !player->ReadyWeapon->DepleteAmmo())
		return false;
	PlaySoundLocActor(player->ReadyWeapon->attacksound, self,
		self == players[ConsolePlayer].camera ? SD_WEAPONS : SD_GENERIC);
	player->c7MuzzleFlashTics = 5;
	++player->levelShotsFired;
	if(weapon == 4)
		ConsumeC7AlienCharge(self, 5, 1);
	else if(weapon == 6)
		ConsumeC7AlienCharge(self, 10, 1);
	else if(weapon == 7)
		ConsumeC7AlienCharge(self, 50, 45);

	if(self->MeleeState)
		self->SetState(self->MeleeState);
	if(!(player->ReadyWeapon->weaponFlags & WF_NOALERT))
	{
		madenoise = true;
		// The same fact, with a source, a place and a kind on it. madenoise is
		// one global boolean: no who, no where, no what, and no history.
		Perception::Emit(Perception::SoundKind::Weapon, self, 24);
	}

	// The disintegrator damages every visible target in its broad firing band.
	// The DOS single-player path passes a fixed 1000-point hit to each target.
	if(weapon == 7)
	{
		bool hit = false;
		for(AActor::Iterator check = AActor::GetIterator(); check.Next();)
		{
			if(check == self || !(check->flags & FL_SHOOTABLE) ||
				!Net::CanDamage(self, check))
				continue;
			if(self->CheckVisibility(check, ANGLE_45))
			{
				DamageActor(check, self, 1000);
				hit = true;
			}
		}
		if(hit)
			++player->levelShotsHit;
		return true;
	}

	AActor *closest = player->FindTarget();
	if(!closest)
		return true;

	int dist = MAX(abs(closest->x - self->x), abs(closest->y - self->y)) / FRACUNIT;
	const int projectiles = weapon == 3 ? 3 : (weapon == 6 ? 4 : 1);
	bool hit = false;
	for(int projectile = 0; projectile < projectiles; ++projectile)
	{
		int damage;
		if(dist < 2 || weapon == 3 || weapon == 6)
		{
			damage = (pr_c7bullet.GenRand32() & 1023) / 4;
			if(weapon == 1)
				damage += 100;
		}
		else if(dist < 4 || weapon == 4)
		{
			damage = (pr_c7bullet.GenRand32() & 1023) / 6;
			if(weapon == 1)
				damage += 50;
		}
		else
		{
			if(static_cast<int>((pr_c7bullet.GenRand32() & 1023) / 12) < dist && weapon != 1)
				continue;
			damage = (pr_c7bullet.GenRand32() & 1023) / 6;
			if(weapon == 1)
				damage += 25;
		}
		DamageActor(closest, self, damage);
		hit = true;
	}
	if(hit)
		++player->levelShotsHit;
	return true;
}

// Ailoprobes, Eitaks, and exposed Bandors alert their local group. The
// Intruder Alert terminal intentionally uses the separate level-wide helper.
ACTION_FUNCTION(A_C7AlienAlarm)
{
	AActor *alertTarget = self->target;
	P_AlertCorridor7MonstersNear(self, alertTarget ? alertTarget : self,
		12*TILEGLOBAL);
	return true;
}

// Armed Corridor 7 mines use a square proximity check, matching the tile-based
// distance convention used throughout the original engine. The mine first
// waits for its owner to clear the trigger zone, then reacts to either a player
// or a living monster. It remains shootable, so plasma and other weapon impacts
// can detonate it early.
ACTION_FUNCTION(A_C7MineThink)
{
	const fixed triggerDistance = 32 * (FRACUNIT / 64);
	if(self->temp1 == 0)
	{
		AActor *owner = self->target;
		if(owner && MAX(abs(owner->x - self->x), abs(owner->y - self->y)) <= triggerDistance)
			return false;
		self->temp1 = 1;
		return false;
	}

	for(AActor::Iterator check = AActor::GetIterator(); check.Next();)
	{
		if(check == self || !(check->flags & FL_SHOOTABLE) ||
			(!check->player && !(check->flags & FL_ISMONSTER)))
			continue;
		if(MAX(abs(check->x - self->x), abs(check->y - self->y)) <= triggerDistance)
		{
			DamageActor(self, self->target, self->health);
			return true;
		}
	}
	return false;
}

ACTION_FUNCTION(A_C7TebazileMorph)
{
	const int maximum = MAX(1, self->SpawnHealth());
	const int fifth = (MAX(0, self->health) * 5) / maximum;
	const char *stableLabel = fifth >= 4 ? "See" :
		(fifth >= 3 ? "PhaseEniram" :
		(fifth >= 2 ? "PhaseTymok" :
		(fifth >= 1 ? "PhaseSolrac" : "PhaseFinal")));
	const Frame *stable = self->FindState(FName(stableLabel));
	if(stable && self->InStateSequence(stable))
		return true;

	const char *transitionLabel = fifth >= 3 ? "TransformEniram" :
		(fifth >= 2 ? "TransformTymok" :
		(fifth >= 1 ? "TransformSolrac" : "TransformFinal"));
	const Frame *desired = self->FindState(FName(transitionLabel));
	// Do not restart a transformation while its six native frames are still
	// running. The action only appears at the head of a stable phase loop.
	if(desired && desired != caller)
		self->SetState(desired);
	return true;
}

// The released vortex state calls its positioned sample only when no other
// digitized sample is active. This lets the 3.15-second sound finish instead
// of restarting it on every animation cycle.
ACTION_FUNCTION(A_C7VortexSound)
{
	if(!SD_AnySoundPlaying())
		PlaySoundLocActor("c7/vortex/ambient", self);
	return true;
}

ACTION_FUNCTION(A_FireCustomMissile)
{
	ACTION_PARAM_STRING(missiletype, 0);
	ACTION_PARAM_DOUBLE(angleOffset, 1);
	ACTION_PARAM_BOOL(useammo, 2);
	ACTION_PARAM_INT(spawnoffset, 3);
	ACTION_PARAM_INT(spawnheight, 4);
	ACTION_PARAM_BOOL(aim, 5);

	player_t *player = self->player;
	if(!player || !player->ReadyWeapon)
		return false;
	if(useammo && !player->ReadyWeapon->DepleteAmmo())
		return false;
	if(useammo && IWad::CheckGameFilter("Corridor7") && missiletype.CompareNoCase("C7PlasmaBolt") == 0)
	{
		PlaySoundLocActor(player->ReadyWeapon->attacksound, self,
			self == players[ConsolePlayer].camera ? SD_WEAPONS : SD_GENERIC);
		ConsumeC7AlienCharge(self, 33, 4);
		++player->levelShotsFired;
		player->c7MuzzleFlashTics = 5;
	}

	if(!(player->ReadyWeapon->weaponFlags & WF_NOALERT))
	{
		madenoise = true;
		// The same fact, with a source, a place and a kind on it. madenoise is
		// one global boolean: no who, no where, no what, and no history.
		Perception::Emit(Perception::SoundKind::Weapon, self, 24);
	}

	if(self->MeleeState)
		self->SetState(self->MeleeState);

	fixed newx = self->x + spawnoffset*finesine[self->angle>>ANGLETOFINESHIFT]/64;
	fixed newy = self->y + spawnoffset*finecosine[self->angle>>ANGLETOFINESHIFT]/64;

	angle_t iangle = self->angle + (angle_t) ((angleOffset*ANGLE_45)/45);

	const ClassDef *cls = ClassDef::FindClass(missiletype);
	if(!cls)
		return false;
	AActor *newobj = AActor::Spawn(cls, newx, newy, 0, SPAWN_AllowReplacement);
	newobj->target = self;
	newobj->angle = iangle;

	newobj->velx = FixedMul(newobj->speed,finecosine[iangle>>ANGLETOFINESHIFT]);
	newobj->vely = -FixedMul(newobj->speed,finesine[iangle>>ANGLETOFINESHIFT]);
	return true;
}
