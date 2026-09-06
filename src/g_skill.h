/*
** g_skill.h
**
** How good a bot is, as distinct from what it likes.
**
** Section 17.1 is explicit that these are two axes and that a menu difficulty
** must not collapse to one accuracy number. Skill governs motor and sensory
** *limits* -- how fast it can turn, how often it looks, how long it takes to
** notice, how steady its aim is. Personality governs preferences -- how close
** it fights, when it breaks off, what it reaches for. A Recruit and an Elite
** with the same personality want the same things and are differently able to
** get them; two Elites with different personalities are equally able and want
** different things.
**
** Everything here is a limit or a delay. Nothing in this file can make a bot
** better than a person at something a person is not limited by, because there
** is nothing here to turn up: damage, health, ammunition, pickup rules and
** command range are not skill traits and do not appear. That is section 17.3
** enforced by what the type is capable of expressing.
**
** The table in section 17.2 is written in human units -- degrees per second,
** hertz, milliseconds -- because those are reviewable. The conversions to
** command units live in this file and are tested against the engine's own
** ControlMovement arithmetic rather than restated from it.
*/

#ifndef __G_SKILL_H__
#define __G_SKILL_H__

#include <stdint.h>

#include "wl_def.h"

namespace Bot {

class Random;

// The four shipped levels, plus one that is not shipped.
//
// Perfect exists for isolated mechanics tests and section 17.5 governs it: it
// is explicitly named, refused in ordinary play, and is never evidence about
// how good the bots are. It is in this enum rather than hidden behind a
// separate code path so that the fairness clamp below has something concrete
// to exclude, and so a test can assert it is excluded.
enum class SkillLevel : uint8_t
{
	Recruit,
	Marine,
	Veteran,
	Elite,
	Perfect,
	NUM
};

const char *SkillName(SkillLevel level);

// Is this a level an ordinary match may use? False for Perfect, which needs
// an explicit developer opt-in.
bool IsShippable(SkillLevel level);

// A closed range of tics. Drawn once per bot, not per tic: section 17.2's
// ranges "vary by stable personality and seed, not by a fresh draw every
// tic", and a trait redrawn every tic is noise rather than a personality.
struct Band
{
	unsigned int low = 0;
	unsigned int high = 0;
};

// The band table for one level. Ranges, not values.
struct SkillBands
{
	Band reaction;			// tics before a new target reaches the decision
	Band visionInterval;	// tics between sensor updates
	Band maxYaw;			// controlx units, the per-tic turn ceiling
	Band yawAccel;			// controlx units per tic, scaled by ACCEL_SCALE
	Band aimEnvelope;		// angle_t, the static error envelope
	Band trackingDelay;		// tics the aim runs behind the target
	Band thinkInterval;		// tics between tactical reconsiderations
	Band searchMemory;		// tics a lost contact is still worth chasing
	Band strafeCommit;		// tics a strafe direction is held
	Band respawnDelay;		// tics of hesitation before pressing use
	Band routeWobble;		// angle_t of steering error while following a route
};

// Acceleration is a fraction of a command unit per tic at every shipped level
// -- Recruit's 600 deg/s^2 is under two and a half -- so it is carried scaled
// rather than rounded to an integer that would make three of the four levels
// identical.
enum { ACCEL_SCALE = 256 };

// The shipped table, section 17.2, converted.
SkillBands BandsFor(SkillLevel level);

// One bot's drawn values.
struct Traits
{
	unsigned int reaction = 0;
	unsigned int visionInterval = 0;
	int          maxYaw = 0;
	int          yawAccel = 0;
	angle_t      aimEnvelope = 0;
	unsigned int trackingDelay = 0;
	unsigned int thinkInterval = 0;
	unsigned int searchMemory = 0;
	unsigned int strafeCommit = 0;
	unsigned int respawnDelay = 0;
	angle_t      routeWobble = 0;
};

// Draw one bot's traits from its level's bands, using its own stream so that
// adding a bot to a match cannot change another bot's numbers.
Traits Draw(SkillLevel level, Random &rng);

// The fairness clamp, applied to every drawn set before it is used.
//
// Section 17.5's ceiling and the B8 requirement that no ordinary configuration
// reaches zero delay. This is not a tuning helper: it is the thing that makes
// "an ordinary profile with an instant reaction" unrepresentable rather than
// merely unintended. Returns false if anything had to be changed, which is a
// bug in the table rather than a runtime condition -- the self-test asserts it
// never happens for a shipped level.
bool Clamp(SkillLevel level, Traits &traits);

// The engine's own turn arithmetic, in one place.
//
// ControlMovement turns controlx into an angle with `controlx * (ANGLE_1/20)`
// each tic, so a command unit is a twentieth of a degree per tic and the
// canonical +/-100 range is a hard 350 deg/s. Stated here as functions so the
// table can be written in the units section 17.2 uses and checked against the
// engine rather than against a comment.
int  YawUnitsFromDegreesPerSecond(int degreesPerSecond);
int  DegreesPerSecondFromYawUnits(int units);
int  AccelUnitsFromDegreesPerSecondSquared(int degreesPerSecondSquared);

// The ceiling the command range imposes, in controlx units. No shipped level
// may exceed it, and neither may Perfect: it is a property of the command
// interface, not of skill.
enum { YAW_CEILING = 100 };

// A profile carries both axes: skill in the low byte, personality above it.
uint32_t   MakeProfile(SkillLevel level, unsigned int persona);
SkillLevel SkillOf(uint32_t profile);
unsigned int PersonaOf(uint32_t profile);

int SkillSelfTest();

}

#endif
