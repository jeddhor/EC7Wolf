/*
** g_combat.h
**
** Aiming badly, on purpose, in a way that actually misses.
**
** Section 16.2 is the load-bearing fact here, and it is worth restating
** because it invalidates the obvious implementation. Corridor 7's hitscan
** weapons call player_t::FindTarget, which acquires the nearest shootable
** target within ten degrees of where the player is facing and then applies
** ordinary line-of-sight and weapon randomness. Verified in the code:
** CheckVisibility(check, ANGLE_90/9), an absolute angular difference against a
** ten-degree tolerance.
**
** So an aim error of two degrees is not an aim error. A bot with a slightly
** noisy reticle that only fires while pointed near its target hits every
** single time, and no amount of tuning the noise changes that. Missing has to
** come from somewhere else:
**
**   * an error large enough to leave the cone entirely;
**   * firing early or late, while the aim is still swinging through;
**   * tracking a delayed bearing, so a moving target is genuinely not where
**     the bot is pointing.
**
** The error is a drifting state rather than a fresh random angle each tic --
** section 16.4. Independent noise per tic averages out over the handful of
** tics a shot takes to line up, which is another way of never missing; a bias
** that drifts and is corrected produces the overshoot-and-settle a person
** actually shows.
*/

#ifndef __G_COMBAT_H__
#define __G_COMBAT_H__

#include <stdint.h>

#include "wl_def.h"
#include "g_session.h"

namespace Bot { class Random; }

namespace Combat {

// A bot's aim, as an angular error that moves like a hand rather than like a
// random number generator.
struct AimError
{
	// Where the error is now, and how fast it is moving. Signed angle_t
	// deltas, applied to the bearing the bot believes in.
	int32_t angle = 0;
	int32_t velocity = 0;
	// What it is currently drifting toward, and when it will pick a new one.
	int32_t bias = 0;
	uint32_t nextBias = 0;

	void Reset();
};

// Move the error one tic.
//
// `envelope` is the width of the bot's error in angle_t: the bias is drawn
// inside it, and the resulting angle is clamped to it. A envelope well under
// ten degrees is a bot that cannot miss; one well over is a bot that cannot
// hit. The interesting profiles straddle it.
void Step(AimError &error, Bot::Random &rng, uint32_t sequence,
	int32_t envelope);

// Ten degrees, as the engine measures it: the half-angle inside which
// FindTarget will acquire regardless of how carefully the bot is aiming.
#define AUTO_AIM_CONE ((int32_t)(ANGLE_90/9))

// What a weapon is, as far as choosing one goes.
//
// Section 16.6 asks for an explicit descriptor table rather than a chain of
// special cases, and the reason is visible in the list: eight weapons whose
// differences are real gameplay facts -- a shotgun is not a long-range weapon
// and a disintegrator is not an ordinary single-target gun -- and a bot that
// encodes them implicitly encodes them wrongly.
//
// `supported` is the maturity flag the plan asks for. A weapon a bot cannot
// yet use well is one it should not switch to, and saying so in the table is
// better than pretending the behaviour exists.
enum class WeaponKind : uint8_t
{
	Melee,
	Hitscan,
	Burst,
	Projectile,
	MultiTarget
};

struct WeaponInfo
{
	const char *cls;
	// The slot button a player presses, as a number: bt_slot1 + slot - 1.
	int         slot;
	WeaponKind  kind;
	// The range band, in tiles, where this weapon is the right answer.
	int         nearTiles;
	int         farTiles;
	// Rough preference within its band, for breaking ties between two weapons
	// that both fit.
	int         value;
	bool        supported;
};

// The table, in slot order.
const WeaponInfo *Weapons(unsigned int &count);

// The choice itself, as a function of what is carried and how far away the
// target is. `carried` is a bitmask of slots, bit 0 for slot 1.
//
// Separated from the inventory lookup so it can be tested without a world:
// section 16.6 asks for a deterministic test per weapon, and a rule that can
// only be exercised by running a match is a rule tested by luck.
int ChooseSlotFrom(unsigned int carried, int rangeTiles);

// Which slot this bot should be holding against a target this far away, or 0
// for "what it has is fine". Considers only what the bot is carrying and what
// it can see -- never the target's health or armour.
int ChooseSlot(Session::PlayerSlot slot, int rangeTiles);

int SelfTest();

}

#endif
