#ifndef __WL_AGENT__
#define __WL_AGENT__

#include "wl_def.h"
#include "a_playerpawn.h"
#include "id_vl.h"
#include "tmemory.h"
#include "weaponslots.h"

/*
=============================================================================

							WL_AGENT DEFINITIONS

=============================================================================
*/

extern  AActor   *LastAttacker;

void    CheckSpawnPlayer (bool setup=false);
void    SpawnPlayer (int num);
void    C7GiveDifficultyFloorPlan(AActor *pawn);

struct player_t;
// Corridor 7 bonus floors are score runs: what the player carried in is what
// they carry out. See player_t::c7BonusEntry.
void    C7CaptureBonusEntry(player_t &player);
bool    C7RestoreBonusEntry(player_t &player);
void    C7ClearBonusEntry(player_t &player);
// The per-floor resets of CORR7CD.EXE's floor setup that ECWolf's travel does
// not already perform.
void    C7NativeFloorSetup(player_t &player);

//
// Status bar interface
//
class DBaseStatusBar
{
public:
	virtual ~DBaseStatusBar() {}

	virtual void DrawStatusBar()=0;
	virtual void DrawTopOverlay() {}
	virtual void SetTopMessage(const char *message, unsigned int duration=3*TICRATE) {}
	virtual void SetC7HealthChamberPower(unsigned int power, unsigned int duration=3*TICRATE) {}
	virtual unsigned int GetHeight(bool top)=0;
	virtual void NewGame() {}
	virtual void Tick() {}
	virtual void RefreshBackground(bool noborder=false);
	virtual void UpdateFace (int damage=0) {}
	virtual void WeaponGrin () {}
};
extern DBaseStatusBar *StatusBar;
void	CreateStatusBar();

//
// player state info
//

void    CheckWeaponChange (AActor *self);
void    ControlMovement (class APlayerPawn *self);

// Corridor 7 laser barrier (map objects 28/84) contact damage for a player who
// is standing in the beams rather than walking into them. Called once per tic
// from the pawn's Tick; the movement-time contact test lives in TryMove.
void    C7TouchLaserBarriers (class APlayerPawn *pawn);

// True while the Invulnerability Sphere is running. Damage paths that do not go
// through player_t::TakeDamage have to consult this themselves.
bool    C7IsInvulnerable (class APlayerPawn *pawn);

////////////////////////////////////////////////////////////////////////////////

class AWeapon;

#define WP_NOCHANGE ((AWeapon*)~0)

extern class player_t
{
	public:
		enum PSprite
		{
			ps_weapon,
			ps_flash,

			NUM_PSPRITES
		};

		player_t();

		void	BobWeapon(fixed_t *x, fixed_t *y);
		void	BringUpWeapon();
		void	DeathFade();
		void	DeathFadeClear();
		AActor	*FindTarget();
		inline unsigned int GetPlayerNum() const;
		void	GiveExtraMan(int amount);
		void	GivePoints(int32_t points);
		size_t	PropagateMark();
		void	Reborn();
		void	Serialize(FArchive &arc);
		void	SetPSprite(const Frame *frame, PSprite layer);
		void	SetFOV(float newlyDesiredFOV);
		void	AdjustFOV();
		void	TakeDamage(int points, AActor *attacker);

		enum State
		{
			PST_ENTER,
			PST_DEAD,
			PST_REBORN,
			PST_LIVE
		};

		enum PlayerFlags
		{
			PF_WEAPONREADY = 0x1,
			PF_WEAPONBOBBING = 0x2,
			PF_WEAPONREADYALT = 0x4,
			PF_WEAPONSWITCHOK = 0x8,
			PF_DISABLESWITCH = 0x10,
			PF_WEAPONRELOADOK = 0x20,
			PF_WEAPONZOOMOK = 0x40,
			PF_REFIRESWITCHOK = 0x80,

			PF_READYFLAGS = PF_WEAPONREADY|PF_WEAPONBOBBING|PF_WEAPONREADYALT|PF_WEAPONSWITCHOK|PF_WEAPONRELOADOK|PF_WEAPONZOOMOK
		};

		APlayerPawn	*mo;
		TObjPtr<AActor>	camera;
		TObjPtr<AActor>	killerobj;

		TUniquePtr<FFader> ScreenFader;

		int32_t		oldscore,score,nextextra;
		uint32_t	levelShotsFired, levelShotsHit;
		// Every earlier floor's shots this game, for the MISSION HIT/MISS RATIO
		// page that ends a Corridor 7 campaign (DS:813e and DS:8144 in the
		// original; added at each floor's setup, cleared by a new game).
		uint32_t	c7MissionShotsFired, c7MissionShotsHit;

		// What a Corridor 7 bonus floor gives back when it ends (GitHub #23;
		// the addresses are in the running game's memory image, as
		// docs/github-issue-verification-2026-11-14.md explains).
		//
		// CORR7CD.EXE copies nine values to DS:40d2..40e2 when the player
		// takes a bonus elevator (a14a) and copies them back when the bonus
		// floor ends (a0f6), whether by its exit or by the player's health
		// running out: health, bullets, armor, visor charge, alien weapon
		// energy, the owned-weapon bits and the selected weapon with its two
		// selection-history words. Nothing else is copied. Ammo capacity
		// (8104) and mines (8116) are outside the set, so an upgrade or a
		// mine spent on a bonus floor stays spent -- the live DOS run in
		// analysis/verification/issues-2026-11-14 confirms both -- and score
		// is the point of the floor and is kept.
		enum { C7BONUS_COUNTERS = 4 };
		struct C7BonusEntry
		{
			bool valid;
			int32_t health;
			// C7Bullets, C7BodyArmor, C7VisorCharge, C7Energy: the amount
			// held, or -1 for none. Only amounts are restored; maxamount is
			// the capacity, which the original lets a bonus floor raise.
			int32_t counters[C7BONUS_COUNTERS];
			TArray<const ClassDef *> weapons;
			const ClassDef *readyWeapon;
		} c7BonusEntry;
		// Native Corridor 7 feedback and health-chamber state. Keeping this on
		// the player makes save/load and level transitions deterministic.
		uint16_t	c7MuzzleFlashTics;
		uint16_t	c7ApparitionTics;
		int16_t		c7ChamberX, c7ChamberY;
		uint16_t	c7ChamberPower;
		uint16_t	c7ChamberTics;
		BYTE		c7ChamberState;
		bool		c7ClearanceNotified, c7FloorSecuredNotified;
		int32_t		health;
		int32_t		frags;
		short		lives;
		float		FOV, DesiredFOV;

		int32_t		thrustspeed;
		// Tics of walk animation still owed after the last thrust. Keeps a
		// stride running across the short stops that turning produces; see
		// ControlMovement.
		int32_t		walkhold;

		FWeaponSlots	weapons;
		AWeapon			*ReadyWeapon;
		AWeapon			*PendingWeapon;
		struct
		{
			const Frame	*frame;
			short		ticcount;
			fixed		sx;
			fixed		sy;
		} psprite[NUM_PSPRITES];
		fixed			bob;

		// Attackheld is similar to buttonheld[bt_attack] only it only gets set
		// to true when an attack is registered. If the button is released and
		// then pressed again it should initiate a second attack even if
		// NOAUTOFIRE is set.
		bool		attackheld;
		short		extralight;

		int32_t		RespawnEligible;
		int32_t		flags;
		State		state;
} players[];

inline unsigned int player_t::GetPlayerNum() const
{
	return static_cast<unsigned int>(this - players);
}

FArchive &operator<< (FArchive &arc, player_t *&player);

#endif
