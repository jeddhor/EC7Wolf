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
	if(Net::InitVars.gameMode == Net::GM_Battle)
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

static bool IsInC7HealthChamber(const APlayerPawn *player)
{
	// Released chambers are identified by their HEALTH CHAMBER wall (ID 2).
	// The healing side is the open side of that sign; this distinguishes the
	// chamber interior from the corridor immediately outside it.
	const int px = player->tilex;
	const int py = player->tiley;
	for(int y = py-4;y <= py+4;++y)
	{
		for(int x = px-4;x <= px+4;++x)
		{
			if(x < 0 || y < 0 ||
				!map->IsValidTileCoordinate(static_cast<unsigned>(x), static_cast<unsigned>(y), 0))
				continue;
			MapSpot sign = map->GetSpot(x, y, 0);
			if(!sign->tile || sign->corridor7WallID != 2)
				continue;

			MapSpot side = sign->GetAdjacent(MapTile::East);
			if(side && !side->tile && px > x)
				return true;
			side = sign->GetAdjacent(MapTile::West);
			if(side && !side->tile && px < x)
				return true;
			side = sign->GetAdjacent(MapTile::South);
			if(side && !side->tile && py > y)
				return true;
			side = sign->GetAdjacent(MapTile::North);
			if(side && !side->tile && py < y)
				return true;
		}
	}
	return false;
}

void APlayerPawn::Tick()
{
	Super::Tick();
	if(!player)
		return;

	if(IWad::CheckGameFilter("Corridor7"))
	{
		// A chamber restores health continuously while the player remains inside.
		// Ten points per second matches the visible, gradual DOS behavior without
		// turning the chamber into a one-shot health pickup.
		if(gamestate.TimeCount % (TICRATE/10) == 0 &&
			player->health > 0 && player->health < maxhealth && IsInC7HealthChamber(this))
		{
			++player->health;
			health = player->health;
			StatusBar->UpdateFace(-1);
		}

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
		player->extralight = visorMode && visorMode->amount == 2 ? 20 : 0;

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
				const fixed distance = 40 * FRACUNIT;
				AActor *mine = AActor::Spawn(mineClass,
					x + FixedMul(distance, finecosine[fineangle]),
					y - FixedMul(distance, finesine[fineangle]), 0,
					SPAWN_AllowReplacement);
				mine->target = this;
				mine->angle = angle;
				if(--mines->amount == 0)
					mines->Destroy();
			}
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

	if(cmd.buttonstate[bt_use])
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
