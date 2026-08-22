/*
** a_playerpawn.cpp
**
**---------------------------------------------------------------------------
** Copyright 2011 Braden Obrzut
** All rights reserved.
**
** Redistribution and use in source and binary forms, with or without
** modification, are permitted provided that the following conditions
** are met:
**
** 1. Redistributions of source code must retain the above copyright
**    notice, this list of conditions and the following disclaimer.
** 2. Redistributions in binary form must reproduce the above copyright
**    notice, this list of conditions and the following disclaimer in the
**    documentation and/or other materials provided with the distribution.
** 3. The name of the author may not be used to endorse or promote products
**    derived from this software without specific prior written permission.
**
** THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
** IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
** OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
** IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
** INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
** NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
** DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
** THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
** (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
** THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
**---------------------------------------------------------------------------
**
**
*/

#include "a_inventory.h"
#include "a_playerpawn.h"
#include "c_cvars.h"
#include "g_mapinfo.h"
#include "g_shared/a_keys.h"
#include "id_ca.h"
#include "id_sd.h"
#include "lnspec.h"
#include "m_random.h"
#include "thingdef/thingdef.h"
#include "wl_agent.h"
#include "wl_game.h"
#include "wl_iwad.h"
#include "wl_main.h"
#include "wl_net.h"
#include "wl_play.h"
#include "wl_draw.h"

#include <climits>

IMPLEMENT_CLASS(PlayerPawn)

PointerIndexTable<AActor::DropList> APlayerPawn::startInventory;

AWeapon *APlayerPawn::BestWeapon(const ClassDef *ammo)
{
	AWeapon *best = NULL;
	int order = INT_MAX;

	for(AInventory *item = inventory;item != NULL;item = item->inventory)
	{
		if(!item->IsKindOf(NATIVE_CLASS(Weapon)))
			continue;

		const int thisOrder = item->GetClass()->Meta.GetMetaInt(AWMETA_SelectionOrder);
		if(thisOrder > order)
			continue;

		AWeapon *weapon = static_cast<AWeapon *>(item);
		if(ammo && (weapon->ammo[0] == NULL || weapon->ammo[0]->GetClass() != ammo))
			continue;
		if(!weapon->CheckAmmo(AWeapon::PrimaryFire, false))
			continue;

		order = thisOrder;
		best = weapon;
	}

	return best;
}

void APlayerPawn::CheckWeaponSwitch(const ClassDef *ammo)
{
	if(player->PendingWeapon != WP_NOCHANGE)
		return;

	AWeapon *weapon = BestWeapon(ammo);
	if(!weapon)
		return;

	const int selectionOrder = weapon->GetClass()->Meta.GetMetaInt(AWMETA_SelectionOrder);
	const int currentOrder = player->ReadyWeapon ? player->ReadyWeapon->GetClass()->Meta.GetMetaInt(AWMETA_SelectionOrder) : 0;
	if(selectionOrder < currentOrder)
		player->PendingWeapon = weapon;
}

void APlayerPawn::DeathTick()
{
	angle_t iangle;

	//
	// swing around to face attacker
	//
	if(player->killerobj)
	{
		int dx = player->killerobj->x - x;
		int dy = y - player->killerobj->y;

		float fangle = (float) atan2((float) dy, (float) dx);     // returns -pi to pi
		if (fangle<0)
			fangle = (float) (M_PI*2+fangle);

		iangle = (angle_t) (fangle*ANGLE_180/M_PI);
	}
	else
	{
		iangle = angle;
	}

	static const angle_t DEATHROTATE = ANGLE_1*2;
	angle_t &curangle = angle;
	const int rotate = angle - iangle > ANGLE_180 ? 1 : -1;

	if (angle - iangle < DEATHROTATE)
		angle = iangle;
	else
		angle += rotate*DEATHROTATE;

	if(player->RespawnEligible == -1)
	{
		if(player->psprite[player_t::ps_weapon].frame == NULL && angle == iangle)
		{
			player->RespawnEligible = gamestate.TimeCount + 70;
			player->DeathFade();
		}
	}
	else
	{
		TicCmd_t &cmd = control[player->GetPlayerNum()];

		if((player->RespawnEligible <= gamestate.TimeCount && cmd.buttonstate[bt_use]) || player->RespawnEligible + 100 <= gamestate.TimeCount)
		{
			if(Net::InitVars.mode == Net::MODE_SinglePlayer)
			{
				player->state = player_t::PST_ENTER;
				playstate = ex_died;
			}
			else
			{
				player->state = player_t::PST_REBORN;
				player->DeathFadeClear();
			}
		}
	}
}

void APlayerPawn::Die()
{
	if(player)
	{
		player->state = player_t::PST_DEAD;

		player->extralight = 0;
		player->PendingWeapon = WP_NOCHANGE;
		if(player->ReadyWeapon)
			player->SetPSprite(player->ReadyWeapon->GetDownState(), player_t::ps_weapon);
	}

	Super::Die();
}

AActor::DropList *APlayerPawn::GetStartInventory()
{
	int index = GetClass()->Meta.GetMetaInt(APMETA_StartInventory);
	if(index >= 0)
		return startInventory[index];
	return NULL;
}

void APlayerPawn::GiveDeathmatchInventory()
{
	ClassDef::ClassIterator iter = ClassDef::GetClassIterator();
	ClassDef::ClassPair *pair;
	while(iter.NextPair(pair))
	{
		const ClassDef *cls = pair->Value;
		if(cls->IsDescendantOf(NATIVE_CLASS(Key)))
		{
			if(((AKey *)cls->GetDefault())->KeyNumber != 0)
			{
				AKey *key = (AKey *)AActor::Spawn(cls, 0, 0, 0, 0);
				key->RemoveFromWorld();
				if(!key->CallTryPickup(this))
					key->Destroy();
			}
		}
	}
}

void APlayerPawn::GiveStartingInventory()
{
	if(Net::Deathmatch())
		GiveDeathmatchInventory();

	if(!GetStartInventory())
		return;

	DropList::Iterator item = GetStartInventory()->Head();
	do
	{
		DropItem &inv = item;
		const ClassDef *cls = ClassDef::FindClass(inv.className);
		if(!cls || !cls->IsDescendantOf(NATIVE_CLASS(Inventory)))
			continue;

		AInventory *invItem = (AInventory *)AActor::Spawn(cls, 0, 0, 0, 0);
		invItem->RemoveFromWorld();
		invItem->amount = inv.amount;
		if(cls->IsDescendantOf(NATIVE_CLASS(Weapon)))
		{
			player->PendingWeapon = (AWeapon *)invItem;

			// Empty weapon.
			((AWeapon *)invItem)->ammogive[0] = ((AWeapon *)invItem)->ammogive[1] = 0;
		}
		if(!invItem->CallTryPickup(this))
			invItem->Destroy();
	}
	while(item.Next());

	// The lowest released rank begins with a full 200-point armor meter.
	if(IWad::CheckGameFilter("Corridor7") &&
		SkillInfo::GetSkillIndex(*gamestate.difficulty) == 0)
	{
		const ClassDef *armorClass = ClassDef::FindClass("C7BodyArmor");
		AInventory *armor = static_cast<AInventory *>(AActor::Spawn(armorClass, 0, 0, 0, 0));
		armor->RemoveFromWorld();
		armor->amount = 200;
		if(!armor->CallTryPickup(this))
			armor->Destroy();
	}

	SetupWeaponSlots();

#if 0
	AInventory *inv = inventory;
	while(inv)
	{
		Printf("%s %d/%d\n", inv->GetClass()->GetName().GetChars(), inv->amount, inv->maxamount);
		inv = inv->inventory;
	}
#endif
}

AWeapon *APlayerPawn::PickNewWeapon()
{
	AWeapon *best = BestWeapon();

	if(best)
	{
		player->PendingWeapon = best;
		if(player->ReadyWeapon)
			player->SetPSprite(player->ReadyWeapon->GetDownState(), player_t::ps_weapon);
	}

	return best;
}

void APlayerPawn::RemoveInventory(AInventory *item)
{
	bool pickWeap = false;
	if(item == player->PendingWeapon)
		player->PendingWeapon = WP_NOCHANGE;
	else if(item == player->ReadyWeapon)
	{
		if(player->PendingWeapon == WP_NOCHANGE)
			pickWeap = true;
	}

	Super::RemoveInventory(item);

	if(pickWeap)
		PickNewWeapon();
}

void APlayerPawn::Serialize(FArchive &arc)
{
	arc << maxhealth;

	Super::Serialize(arc);
}

void APlayerPawn::SetupWeaponSlots()
{
	player->weapons.StandardSetup(GetClass());
}

bool APlayerPawn::TryUseC7HealthChamber()
{
	if(!IWad::CheckGameFilter("Corridor7") || player->c7ChamberState)
		return false;

	// A released health chamber is exactly one walkable cell deep. The use
	// panel is wall 35 at its rear and the four-page aperture (wall 53,
	// marker 107 while open) is one cell behind the player. Decorative HEALTH
	// CHAMBER signs use wall 2 and must never activate the unit.
	int dx = 0, dy = 0;
	if(angle < ANGLE_45 || angle > 7*ANGLE_45)
		dx = 1;
	else if(angle < 3*ANGLE_45)
		dy = -1;
	else if(angle < 5*ANGLE_45)
		dx = -1;
	else
		dy = 1;

	MapSpot panel = map->GetSpot(tilex+dx, tiley+dy, 0);
	MapSpot door = map->GetSpot(tilex-dx, tiley-dy, 0);
	if(!panel || !panel->tile || panel->corridor7WallID != 35 ||
		!door || !door->tile || door->corridor7WallID != 53 ||
		door->corridor7WallMarker != 107)
		return false;
	if(player->health >= maxhealth)
	{
		if(player->GetPlayerNum() == ConsolePlayer)
			StatusBar->SetTopMessage("FULL HEALTH");
		return true;
	}
	if(door->corridor7ChamberPower == 0)
	{
		if(player->GetPlayerNum() == ConsolePlayer)
		{
			StatusBar->SetTopMessage("HEALTH CHAMBER DEPLETED");
			StatusBar->SetC7HealthChamberPower(0, 4*TICRATE);
		}
		return true;
	}

	player->c7ChamberX = static_cast<int16_t>(door->GetX());
	player->c7ChamberY = static_cast<int16_t>(door->GetY());
	player->c7ChamberPower = door->corridor7ChamberPower;
	player->c7ChamberTics = 0;
	player->c7ChamberState = 1;
	if(player->GetPlayerNum() == ConsolePlayer)
		StatusBar->SetC7HealthChamberPower(player->c7ChamberPower, 4*TICRATE);
	SD_PlaySound("c7/chamber/activate");
	return true;
}

static angle_t C7ChamberExitAngle(const APlayerPawn *pawn)
{
	const fixed doorX = (static_cast<fixed>(pawn->player->c7ChamberX) << TILESHIFT) + TILEGLOBAL/2;
	const fixed doorY = (static_cast<fixed>(pawn->player->c7ChamberY) << TILESHIFT) + TILEGLOBAL/2;
	float fangle = static_cast<float>(atan2(static_cast<double>(pawn->y-doorY),
		static_cast<double>(doorX-pawn->x)));
	if(fangle < 0)
		fangle = static_cast<float>(M_PI*2 + fangle);
	return static_cast<angle_t>(fangle*ANGLE_180/M_PI);
}

static void SetC7ChamberDoorFrame(MapSpot door, unsigned int wallID)
{
	FString textureName;
	textureName.Format("C7W%04u", wallID-1);
	const FTextureID texture = TexMan.CheckForTexture(textureName, FTexture::TEX_Wall);
	if(texture.isValid())
		for(unsigned int side = 0;side < 4;++side)
			door->texture[side] = texture;
}

static bool TickC7HealthChamber(APlayerPawn *pawn)
{
	player_t *player = pawn->player;
	if(!player->c7ChamberState)
		return false;

	MapSpot door = map->GetSpot(player->c7ChamberX, player->c7ChamberY, 0);
	if(!door || !door->tile)
	{
		player->c7ChamberState = 0;
		return false;
	}

	if(player->c7ChamberState == 1)
	{
		const angle_t target = C7ChamberExitAngle(pawn);
		const angle_t clockwise = target-pawn->angle;
		const angle_t step = ANGLE_1*2;
		if(MIN(clockwise, static_cast<angle_t>(0-clockwise)) <= step)
		{
			pawn->angle = target;
			player->c7ChamberState = 2;
			player->c7ChamberTics = 0;
		}
		else if(clockwise < ANGLE_180)
			pawn->angle += step;
		else
			pawn->angle -= step;
		return true;
	}

	// Close the four-frame aperture in reverse, eight 70 Hz tics per page.
	if(++player->c7ChamberTics % 8 == 0)
	{
		const unsigned int phase = player->c7ChamberTics/8;
		SetC7ChamberDoorFrame(door, 56-MIN(phase, 3U));
		if(phase >= 3)
		{
			for(unsigned int side = 0;side < 4;++side)
				door->sideSolid[side] = true;
			// The closed door remains movement-solid, but keyed glass pixels must
			// still trace the room beyond instead of exposing an old framebuffer.
			door->corridor7SightTransparent = true;
			door->corridor7WallMarker = 106;
			for(unsigned int trigger = 0;trigger < door->triggers.Size();++trigger)
			{
				if(door->triggers[trigger].action == Specials::Wall_AnimateRemove)
				{
					door->triggers[trigger].active = true;
					door->triggers[trigger].repeatable = true;
				}
			}

			const unsigned int power = MIN<unsigned int>(door->corridor7ChamberPower, 100);
			if(power == 0)
			{
				if(player->GetPlayerNum() == ConsolePlayer)
					StatusBar->SetTopMessage("HEALTH CHAMBER DEPLETED");
				player->c7ChamberPower = 0;
				StatusBar->SetC7HealthChamberPower(0, 4*TICRATE);
				player->c7ChamberState = 0;
				player->c7ChamberTics = 0;
				return false;
			}

			// The chamber is a persistent 100-point reservoir. It spends only the
			// health actually restored, so a six-point treatment leaves 94 points
			// available for later visits instead of consuming a complete charge.
			const unsigned int missing = pawn->maxhealth > player->health ?
				pawn->maxhealth-player->health : 0;
			const unsigned int restored = MIN<unsigned int>(missing, power);
			player->health += restored;
			pawn->health = player->health;
			door->corridor7ChamberPower = power-restored;
			player->c7ChamberPower = door->corridor7ChamberPower;
			StartC7ChamberFlash();
			StatusBar->UpdateFace(-1);
			StatusBar->SetC7HealthChamberPower(player->c7ChamberPower, 4*TICRATE);
			player->c7ChamberState = 0;
			player->c7ChamberTics = 0;
		}
	}
	return true;
}

static FRandom pr_c7apparition("Corridor7Apparition");
static void TickC7Apparition(APlayerPawn *pawn)
{
	player_t *player = pawn->player;
	// CORR7CD.EXE tests this timer after 0x800 70 Hz tics, then requires a
	// zero from its byte RNG. The apparition is a non-kill-counting actor two
	// tiles in front of the player, travelling back toward them at 0x300 map
	// units per tic while frames C718..C725 play.
	if(++player->c7ApparitionTics <= 0x800)
		return;
	player->c7ApparitionTics = 0;
	if(pr_c7apparition() != 0 || player->state != player_t::PST_LIVE)
		return;

	const ClassDef *apparitionClass = ClassDef::FindClass("C7SkullApparition");
	if(!apparitionClass)
		return;
	const unsigned int fineangle = pawn->angle >> ANGLETOFINESHIFT;
	const fixed distance = 2*TILEGLOBAL;
	AActor *apparition = AActor::Spawn(apparitionClass,
		pawn->x + FixedMul(distance, finecosine[fineangle]),
		pawn->y - FixedMul(distance, finesine[fineangle]), 0,
		SPAWN_AllowReplacement);
	if(!apparition)
		return;

	apparition->angle = pawn->angle + ANGLE_180;
	const unsigned int returnAngle = apparition->angle >> ANGLETOFINESHIFT;
	apparition->velx = FixedMul(0x300, finecosine[returnAngle]);
	apparition->vely = -FixedMul(0x300, finesine[returnAngle]);
	apparition->target = NULL;
	SD_PlaySound("c7/apparition");
}

void APlayerPawn::Tick()
{
	Super::Tick();
	if(!player)
		return;

	if(IWad::CheckGameFilter("Corridor7"))
	{
		const bool chamberBusy = TickC7HealthChamber(this);
		TickC7Apparition(this);

		AInventory *invulnerability = FindInventory(ClassDef::FindClass("C7Invulnerability"));
		if(invulnerability && invulnerability->amount > 0 && --invulnerability->amount == 0)
			invulnerability->Destroy();

		TicCmd_t &c7cmd = control[player->GetPlayerNum()];
		AInventory *visor = FindInventory(ClassDef::FindClass("C7VisorCharge"));
		AInventory *visorMode = FindInventory(ClassDef::FindClass("C7VisorMode"));
		if(visor && visorMode && c7cmd.buttonstate[bt_zoom] && !c7cmd.buttonheld[bt_zoom])
		{
			visorMode->amount = visor->amount > 0 ? visorMode->amount % 3 + 1 : 1;
		}
		if(visor && visorMode && visorMode->amount > 1 && gamestate.TimeCount % TICRATE == 0)
		{
			if(--visor->amount <= 0)
			{
				visor->amount = 0;
				visorMode->amount = 1;
			}
		}
		player->extralight = visorMode && visorMode->amount == 2 ? 20 :
			(player->c7MuzzleFlashTics ? 12 : 0);
		if(player->c7MuzzleFlashTics)
			--player->c7MuzzleFlashTics;

		// The infrared laser barrier statics (map objects 28/84) zap a player
		// standing in the beams, not only one walking into them. TryMove's
		// contact check covers the walking half but is only reached while an
		// input is moving the player, so this is what makes lingering hurt.
		C7TouchLaserBarriers(this);

		AInventory *energy = FindInventory(ClassDef::FindClass("C7Energy"));
		AInventory *capacity = FindInventory(ClassDef::FindClass("C7EnergyCapacity"));
		if(energy && capacity)
		{
			if(energy->amount > capacity->amount)
				energy->amount = capacity->amount;
			const ClassDef *dual = ClassDef::FindClass("C7DualBlaster");
			const ClassDef *plasma = ClassDef::FindClass("C7PlasmaRifle");
			const ClassDef *assault = ClassDef::FindClass("C7AssaultCannon");
			const ClassDef *disintegrator = ClassDef::FindClass("C7Disintegrator");
			AWeapon *ready = player->ReadyWeapon;
			if(ready && (ready->IsA(dual) || ready->IsA(plasma) ||
				ready->IsA(assault) || ready->IsA(disintegrator)) &&
				energy->amount < capacity->amount)
				energy->amount = MIN(energy->amount + 2, capacity->amount);
		}

		if(c7cmd.buttonstate[bt_reload] && !c7cmd.buttonheld[bt_reload])
		{
			AInventory *mines = FindInventory(ClassDef::FindClass("C7Mines"));
			const ClassDef *mineClass = ClassDef::FindClass("C7ProximityMine");
			if(mines && mines->amount > 0 && mineClass)
			{
				const unsigned fineangle = angle >> ANGLETOFINESHIFT;
				// Actor dimensions and DECORATE offsets use 64 world units per
				// tile. Using 40 * FRACUNIT here placed the mine 40 whole tiles
				// away, which could send its coordinates outside the map and make
				// AActor::Spawn index beyond the map plane. Drop it 40/64 of a
				// tile in front of the player instead.
				const fixed distance = 40 * (FRACUNIT / 64);
				fixed mineX = x + FixedMul(distance, finecosine[fineangle]);
				fixed mineY = y - FixedMul(distance, finesine[fineangle]);
				if(!map->IsValidTileCoordinate(mineX >> FRACBITS,
					mineY >> FRACBITS, 0))
				{
					mineX = x;
					mineY = y;
				}
				AActor *mine = AActor::Spawn(mineClass, mineX, mineY, 0,
					SPAWN_AllowReplacement);
				if(!mine)
					return;
				mine->target = this;
				mine->angle = angle;
				if(--mines->amount == 0)
					mines->Destroy();
			}
		}

		if(gamestate.killtotal > 0)
		{
			static const unsigned int clearance[4] = { 10, 75, 100, 100 };
			const unsigned int skill = MIN<unsigned int>(
				MAX<unsigned int>(1, gamestate.difficulty->SpawnFilter)-1, 3);
			const unsigned int destroyed =
				(static_cast<unsigned int>(gamestate.killcount)*100)/gamestate.killtotal;
			if(!player->c7FloorSecuredNotified && gamestate.killcount >= gamestate.killtotal)
			{
				player->c7FloorSecuredNotified = true;
				player->c7ClearanceNotified = true;
				if(player->GetPlayerNum() == ConsolePlayer)
				{
					StatusBar->SetTopMessage("FLOOR SECURED", 4*TICRATE);
					SD_PlaySound("c7/announcement/secured");
				}
			}
			else if(!player->c7ClearanceNotified && destroyed >= clearance[skill])
			{
				player->c7ClearanceNotified = true;
				if(player->GetPlayerNum() == ConsolePlayer)
				{
					StatusBar->SetTopMessage("ELEVATOR CLEARANCE ACQUIRED", 4*TICRATE);
					SD_PlaySound("c7/announcement/clearance");
				}
			}
		}

		if(chamberBusy)
		{
			TickPSprites();
			return;
		}
	}

	TickPSprites();

	if(player->GetPlayerNum() == ConsolePlayer)
	{
		// [RH] Smooth transitions between bobbing and not-bobbing frames.
		// This also fixes the bug where you can "stick" a weapon off-center by
		// shooting it when it's at the peak of its swing.
		static fixed curbob = 0;

		if(movebob)
		{
			static const fixed MAXBOB = 0x100000;
			fixed bobtarget = gamestate.victoryflag ? 0 : FixedMul(player->thrustspeed << 8, movebob);
			if(bobtarget > MAXBOB)
				bobtarget = MAXBOB;

			if (curbob != bobtarget)
			{
				if (abs (bobtarget - curbob) <= 1*FRACUNIT)
				{
					curbob = bobtarget;
				}
				else
				{
					fixed_t zoom = MAX<fixed_t> (1*FRACUNIT, abs (curbob - bobtarget) / 40);
					if (curbob > bobtarget)
					{
						curbob -= zoom;
					}
					else
					{
						curbob += zoom;
					}
				}
			}
		}
		else
			curbob = 0;

		player->bob = curbob;
	}

	player->AdjustFOV();

	// Watching BJ
	if(gamestate.victoryflag)
		return;

	if(player->state == player_t::PST_DEAD)
	{
		DeathTick();
		return;
	}

	if((player->GetPlayerNum()) == ConsolePlayer)
		StatusBar->UpdateFace();
	CheckWeaponChange(this);

	TicCmd_t &cmd = control[player->GetPlayerNum()];

	// Use is an edge-triggered action. Running it on every tic while the key is
	// held makes a successful one-shot switch immediately fall through to the
	// generic "nothing here" sound on the following tic.
	if(cmd.buttonstate[bt_use] && !cmd.buttonheld[bt_use])
		Cmd_Use();

	if((player->flags & (player_t::PF_WEAPONREADY|player_t::PF_WEAPONREADYALT)))
	{
		// Determine primary or alternate attack
		Button fireButton = bt_nobutton;
		if(cmd.buttonstate[bt_attack] && (player->flags & player_t::PF_WEAPONREADY))
		{
			fireButton = bt_attack;
			player->ReadyWeapon->mode = AWeapon::PrimaryFire;
		}
		else if(cmd.buttonstate[bt_altattack] && (player->flags & player_t::PF_WEAPONREADYALT))
		{
			fireButton = bt_altattack;
			player->ReadyWeapon->mode = AWeapon::AltFire;
		}

		// Try to fire
		if(fireButton != bt_nobutton && player->ReadyWeapon->CheckAmmo(player->ReadyWeapon->mode, true))
		{
			if(!cmd.buttonheld[fireButton])
				player->attackheld = false;
			if(!(player->ReadyWeapon->weaponFlags & WF_NOAUTOFIRE) || !player->attackheld)
			{
				player->attackheld = true;
				if(MissileState)
					SetState(MissileState);
				player->SetPSprite(player->ReadyWeapon->GetAtkState(player->ReadyWeapon->mode, false), player_t::ps_weapon);
			}
		}
		else if(player->PendingWeapon != WP_NOCHANGE && (player->flags & player_t::PF_WEAPONSWITCHOK))
		{
			player->SetPSprite(player->ReadyWeapon->GetDownState(), player_t::ps_weapon);
		}
	}
	else if(player->attackheld)
		player->attackheld = !!(cmd.buttonstate[bt_attack]|cmd.buttonstate[bt_altattack]);

	// Reload
	if((player->flags & player_t::PF_WEAPONRELOADOK) && cmd.buttonstate[bt_reload])
	{
		const Frame *reload = player->ReadyWeapon->GetReloadState();
		if(reload)
			player->SetPSprite(reload, player_t::ps_weapon);
	}
	// Zoom
	if((player->flags & player_t::PF_WEAPONZOOMOK) && cmd.buttonstate[bt_zoom])
	{
		const Frame *zoom = player->ReadyWeapon->GetZoomState();
		if(zoom)
			player->SetPSprite(zoom, player_t::ps_weapon);
	}

	if(sighttime) // Player is frozen
		--sighttime;
	else
		ControlMovement(this);
}

void APlayerPawn::TickPSprites()
{
	for(unsigned int layer = 0;layer < player_t::NUM_PSPRITES;++layer)
	{
		if(!player->psprite[layer].frame)
			return;

		if(player->psprite[layer].ticcount > 0)
			--player->psprite[layer].ticcount;

		if(player->psprite[layer].frame && player->psprite[layer].ticcount == 0)
			player->SetPSprite(player->psprite[layer].frame->next, static_cast<player_t::PSprite>(layer));

		if(player->psprite[layer].frame)
			player->psprite[layer].frame->thinker(this, player->ReadyWeapon, player->psprite[layer].frame);
	}
}
