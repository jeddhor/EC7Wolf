/*
** g_skill.cpp
**
** Section 17.2's table, converted once, in one place.
*/

#include "g_skill.h"
#include "g_bot.h"
#include "wl_def.h"
#include "zstring.h"

namespace Bot {

const char *SkillName(SkillLevel level)
{
	switch(level)
	{
		case SkillLevel::Recruit: return "Recruit";
		case SkillLevel::Marine:  return "Marine";
		case SkillLevel::Veteran: return "Veteran";
		case SkillLevel::Elite:   return "Elite";
		case SkillLevel::Perfect: return "Perfect";
		default: return "?";
	}
}

bool IsShippable(SkillLevel level)
{
	return level == SkillLevel::Recruit || level == SkillLevel::Marine ||
		level == SkillLevel::Veteran || level == SkillLevel::Elite;
}

// ControlMovement applies `controlx * (ANGLE_1/20)` once a tic, so one command
// unit is a twentieth of a degree per tic, and at 70 tics a second that is
// 70/20 = 3.5 degrees a second. The canonical +/-100 range is therefore a hard
// 350 deg/s, which is where YAW_CEILING comes from -- it is a property of the
// command interface that humans use too, not a difficulty setting.
enum { TICRATE_HZ = 70, UNITS_PER_DEGREE_TIC = 20 };

int YawUnitsFromDegreesPerSecond(int degreesPerSecond)
{
	// units = deg/s * 20 / 70
	return (degreesPerSecond*UNITS_PER_DEGREE_TIC + TICRATE_HZ/2)/TICRATE_HZ;
}

int DegreesPerSecondFromYawUnits(int units)
{
	return (units*TICRATE_HZ + UNITS_PER_DEGREE_TIC/2)/UNITS_PER_DEGREE_TIC;
}

int AccelUnitsFromDegreesPerSecondSquared(int degreesPerSecondSquared)
{
	// A change of this many degrees per second, per second, is that many
	// command units per tic per tic once divided by the tic rate a second
	// time. Scaled, because every shipped level lands under ten.
	const int64_t units = (int64_t)degreesPerSecondSquared*UNITS_PER_DEGREE_TIC;
	return (int)((units*ACCEL_SCALE + (int64_t)TICRATE_HZ*TICRATE_HZ/2)/
		((int64_t)TICRATE_HZ*TICRATE_HZ));
}

// Hertz to the gap between updates, in tics. A faster refresh is a smaller
// number, so the band's ends swap: the low end of an interval band comes from
// the high end of a frequency one.
static Band IntervalFromHz(unsigned int lowHz, unsigned int highHz)
{
	Band b;
	b.low = TICRATE_HZ/highHz;
	b.high = TICRATE_HZ/lowHz;
	if(b.low < 1) b.low = 1;
	if(b.high < b.low) b.high = b.low;
	return b;
}

static Band Tics(unsigned int low, unsigned int high)
{
	Band b; b.low = low; b.high = high; return b;
}

static Band Seconds(unsigned int lowTenths, unsigned int highTenths)
{
	Band b;
	b.low = (lowTenths*TICRATE_HZ)/10;
	b.high = (highTenths*TICRATE_HZ)/10;
	return b;
}

static Band Yaw(int lowDegPerSec, int highDegPerSec)
{
	Band b;
	b.low = (unsigned int)YawUnitsFromDegreesPerSecond(lowDegPerSec);
	b.high = (unsigned int)YawUnitsFromDegreesPerSecond(highDegPerSec);
	return b;
}

static Band Accel(int lowDegPerSec2, int highDegPerSec2)
{
	Band b;
	b.low = (unsigned int)AccelUnitsFromDegreesPerSecondSquared(lowDegPerSec2);
	b.high = (unsigned int)AccelUnitsFromDegreesPerSecondSquared(highDegPerSec2);
	return b;
}

// Tenths of a degree, so 2.5 and 1.5 survive the table.
static Band Envelope(unsigned int lowTenths, unsigned int highTenths)
{
	Band b;
	b.low = (unsigned int)((ANGLE_1*(angle_t)lowTenths)/10);
	b.high = (unsigned int)((ANGLE_1*(angle_t)highTenths)/10);
	return b;
}

SkillBands BandsFor(SkillLevel level)
{
	SkillBands s;
	switch(level)
	{
		case SkillLevel::Recruit:
			s.reaction      = Tics(24, 45);
			s.visionInterval= IntervalFromHz(7, 10);
			s.maxYaw        = Yaw(140, 210);
			s.yawAccel      = Accel(600, 900);
			s.aimEnvelope   = Envelope(80, 160);
			s.trackingDelay = Tics(10, 22);
			s.thinkInterval = IntervalFromHz(4, 6);
			s.searchMemory  = Seconds(20, 50);
			s.strafeCommit  = Seconds(5, 15);
			s.respawnDelay  = Tics(18, 55);
			s.routeWobble   = Envelope(40, 80);
			break;
		case SkillLevel::Marine:
			s.reaction      = Tics(17, 32);
			s.visionInterval= IntervalFromHz(10, 14);
			s.maxYaw        = Yaw(190, 260);
			s.yawAccel      = Accel(850, 1300);
			s.aimEnvelope   = Envelope(50, 110);
			s.trackingDelay = Tics(7, 16);
			s.thinkInterval = IntervalFromHz(5, 7);
			s.searchMemory  = Seconds(40, 80);
			s.strafeCommit  = Seconds(6, 16);
			s.respawnDelay  = Tics(12, 40);
			s.routeWobble   = Envelope(25, 55);
			break;
		case SkillLevel::Veteran:
			s.reaction      = Tics(12, 24);
			s.visionInterval= IntervalFromHz(14, 20);
			s.maxYaw        = Yaw(240, 310);
			s.yawAccel      = Accel(1200, 1800);
			s.aimEnvelope   = Envelope(25, 70);
			s.trackingDelay = Tics(4, 11);
			s.thinkInterval = IntervalFromHz(6, 9);
			s.searchMemory  = Seconds(60, 120);
			s.strafeCommit  = Seconds(7, 18);
			s.respawnDelay  = Tics(8, 28);
			s.routeWobble   = Envelope(12, 35);
			break;
		case SkillLevel::Elite:
			s.reaction      = Tics(10, 19);
			s.visionInterval= IntervalFromHz(20, 28);
			s.maxYaw        = Yaw(280, 350);
			s.yawAccel      = Accel(1600, 2400);
			s.aimEnvelope   = Envelope(15, 50);
			s.trackingDelay = Tics(3, 8);
			s.thinkInterval = IntervalFromHz(7, 10);
			s.searchMemory  = Seconds(80, 150);
			s.strafeCommit  = Seconds(7, 20);
			s.respawnDelay  = Tics(6, 22);
			s.routeWobble   = Envelope(6, 20);
			break;
		default:	// Perfect, and it is still bound by the command range
			s.reaction      = Tics(1, 1);
			s.visionInterval= Tics(1, 1);
			s.maxYaw        = Tics(YAW_CEILING, YAW_CEILING);
			s.yawAccel      = Tics(YAW_CEILING*ACCEL_SCALE, YAW_CEILING*ACCEL_SCALE);
			s.aimEnvelope   = Envelope(0, 0);
			s.trackingDelay = Tics(0, 0);
			s.thinkInterval = Tics(1, 1);
			s.searchMemory  = Seconds(150, 150);
			s.strafeCommit  = Seconds(5, 5);
			s.respawnDelay  = Tics(1, 1);
			s.routeWobble   = Envelope(0, 0);
			break;
	}
	return s;
}

static unsigned int Pick(const Band &band, Random &rng)
{
	if(band.high <= band.low)
		return band.low;
	return band.low + rng.Below(band.high - band.low + 1);
}

Traits Draw(SkillLevel level, Random &rng)
{
	const SkillBands bands = BandsFor(level);
	Traits t;
	// Fixed order. A trait added in the middle would renumber every draw after
	// it and change every existing bot, which is a thing to do deliberately.
	t.reaction       = Pick(bands.reaction, rng);
	t.visionInterval = Pick(bands.visionInterval, rng);
	t.maxYaw         = (int)Pick(bands.maxYaw, rng);
	t.yawAccel       = (int)Pick(bands.yawAccel, rng);
	t.aimEnvelope    = (angle_t)Pick(bands.aimEnvelope, rng);
	t.trackingDelay  = Pick(bands.trackingDelay, rng);
	t.thinkInterval  = Pick(bands.thinkInterval, rng);
	t.searchMemory   = Pick(bands.searchMemory, rng);
	t.strafeCommit   = Pick(bands.strafeCommit, rng);
	t.respawnDelay   = Pick(bands.respawnDelay, rng);
	// Appended, so that adding it did not renumber every draw before it and
	// silently give every existing bot a different set of reflexes.
	t.routeWobble    = (angle_t)Pick(bands.routeWobble, rng);
	Clamp(level, t);
	return t;
}

bool Clamp(SkillLevel level, Traits &traits)
{
	bool ok = true;

	// The command range binds everybody, Perfect included. It is not a
	// difficulty setting: a human's turn is clamped by the same number, and a
	// bot allowed past it would be using an interface nobody else has.
	if(traits.maxYaw > YAW_CEILING) { traits.maxYaw = YAW_CEILING; ok = false; }
	if(traits.maxYaw < 1) { traits.maxYaw = 1; ok = false; }
	if(traits.yawAccel < 1) { traits.yawAccel = 1; ok = false; }

	if(!IsShippable(level))
		return ok;

	// And no ordinary configuration reaches zero delay anywhere. B8 asks for
	// this to be prevented rather than merely not chosen, so it lives here
	// where every drawn set passes through it, instead of in the table where
	// a future edit could quietly walk past it.
	if(traits.reaction < 1) { traits.reaction = 1; ok = false; }
	if(traits.visionInterval < 1) { traits.visionInterval = 1; ok = false; }
	if(traits.thinkInterval < 1) { traits.thinkInterval = 1; ok = false; }
	if(traits.respawnDelay < 1) { traits.respawnDelay = 1; ok = false; }

	// Section 17.5: the highest normal profile still has a nonzero error
	// floor. An envelope of zero is an aim lock with no variance, which is the
	// one thing on that list that would be invisible in a trace and obvious to
	// play against.
	if(traits.aimEnvelope == 0) { traits.aimEnvelope = ANGLE_1; ok = false; }

	return ok;
}

// --- profiles ---------------------------------------------------------------
//
// One number carries both axes because that is what the session already
// replicates. Skill in the low byte, personality above it.

// --- self test ---------------------------------------------------------------

static int g_checks = 0, g_failures = 0;

static void Check(bool condition, const char *what)
{
	++g_checks;
	if(condition)
		Printf("  ok   %s\n", what);
	else
	{
		++g_failures;
		Printf("  FAIL %s\n", what);
	}
}

int SkillSelfTest()
{
	g_checks = g_failures = 0;

	Printf("The command range, not a difficulty setting\n");
	{
		// The conversion is checked against ControlMovement's arithmetic
		// written out longhand, not against the function under test.
		const int oneUnitPerTic = DegreesPerSecondFromYawUnits(1);
		Check(oneUnitPerTic == (1*70 + 10)/20,
			"a command unit is a twentieth of a degree a tic");
		Check(DegreesPerSecondFromYawUnits(YAW_CEILING) == 350,
			"and the canonical range tops out at 350 degrees a second");
		Check(YawUnitsFromDegreesPerSecond(350) == YAW_CEILING,
			"which is exactly the ceiling, converted back");
		Check(YawUnitsFromDegreesPerSecond(210) == 60,
			"the old single-speed constant was 210 degrees a second");
	}

	Printf("\nEvery shipped level is inside the interface\n");
	{
		bool ceiling = true, nonzero = true, unclamped = true;
		for(unsigned int i = 0;i < (unsigned int)SkillLevel::NUM;++i)
		{
			const SkillLevel level = (SkillLevel)i;
			const SkillBands b = BandsFor(level);
			ceiling = ceiling && b.maxYaw.high <= (unsigned int)YAW_CEILING;

			// Every draw a bot could make, not one sample of them: a band
			// whose top end breaks a rule is a bug that shows up in one match
			// in fifty otherwise.
			// The band's own ends, put through the clamp untouched. Asking
			// Draw for them would prove nothing: Draw clamps, so the answer
			// would already be legal and the clamp would report no change.
			// This is the difference between "the clamp works" and "the table
			// does not need it", and only the second one says the numbers in
			// section 17.2 were transcribed correctly.
			Traits ends[2];
			ends[0].reaction = b.reaction.low;
			ends[0].visionInterval = b.visionInterval.low;
			ends[0].maxYaw = (int)b.maxYaw.low;
			ends[0].yawAccel = (int)b.yawAccel.low;
			ends[0].aimEnvelope = (angle_t)b.aimEnvelope.low;
			ends[0].trackingDelay = b.trackingDelay.low;
			ends[0].thinkInterval = b.thinkInterval.low;
			ends[0].searchMemory = b.searchMemory.low;
			ends[0].strafeCommit = b.strafeCommit.low;
			ends[0].respawnDelay = b.respawnDelay.low;
			ends[0].routeWobble = (angle_t)b.routeWobble.low;
			ends[1].reaction = b.reaction.high;
			ends[1].visionInterval = b.visionInterval.high;
			ends[1].maxYaw = (int)b.maxYaw.high;
			ends[1].yawAccel = (int)b.yawAccel.high;
			ends[1].aimEnvelope = (angle_t)b.aimEnvelope.high;
			ends[1].trackingDelay = b.trackingDelay.high;
			ends[1].thinkInterval = b.thinkInterval.high;
			ends[1].searchMemory = b.searchMemory.high;
			ends[1].strafeCommit = b.strafeCommit.high;
			ends[1].respawnDelay = b.respawnDelay.high;
			ends[1].routeWobble = (angle_t)b.routeWobble.high;
			for(unsigned int e = 0;e < 2;++e)
				unclamped = unclamped && Clamp(level, ends[e]);

			Random rng;
			for(unsigned int seed = 0;seed < 64;++seed)
			{
				rng.Seed(0x5eed + seed, i, 0, Stream::Skill);
				const Traits t = Draw(level, rng);
				ceiling = ceiling && t.maxYaw <= YAW_CEILING;
				if(IsShippable(level))
					nonzero = nonzero && t.reaction >= 1 &&
						t.visionInterval >= 1 && t.thinkInterval >= 1 &&
						t.respawnDelay >= 1 && t.aimEnvelope > 0;
			}
		}
		Check(ceiling, "no level can turn faster than the command range allows");
		Check(nonzero, "and no shipped level has a zero delay anywhere");
		Check(unclamped, "the table needs no clamping, which is where it should be fixed");
	}

	Printf("\nSkill goes one way\n");
	{
		// Section 17.2's levels are a ladder, so the bands have to be ordered.
		// Checked on the band rather than on a draw: two draws can cross where
		// the bands overlap, which is deliberate, and asserting on them would
		// be asserting on the seed.
		const SkillBands r = BandsFor(SkillLevel::Recruit);
		const SkillBands m = BandsFor(SkillLevel::Marine);
		const SkillBands v = BandsFor(SkillLevel::Veteran);
		const SkillBands e = BandsFor(SkillLevel::Elite);

		Check(r.reaction.low > m.reaction.low && m.reaction.low > v.reaction.low &&
			v.reaction.low > e.reaction.low,
			"a better bot reacts sooner");
		Check(r.maxYaw.high < m.maxYaw.high && m.maxYaw.high < v.maxYaw.high &&
			v.maxYaw.high < e.maxYaw.high,
			"and turns faster");
		Check(r.aimEnvelope.low > m.aimEnvelope.low &&
			m.aimEnvelope.low > v.aimEnvelope.low &&
			v.aimEnvelope.low > e.aimEnvelope.low,
			"and aims straighter");
		Check(r.visionInterval.low >= m.visionInterval.low &&
			m.visionInterval.low >= v.visionInterval.low &&
			v.visionInterval.low >= e.visionInterval.low,
			"and looks more often");
		Check(r.searchMemory.high < m.searchMemory.high &&
			m.searchMemory.high < v.searchMemory.high &&
			v.searchMemory.high < e.searchMemory.high,
			"and remembers longer");
		Check(r.routeWobble.high > m.routeWobble.high &&
			m.routeWobble.high > v.routeWobble.high &&
			v.routeWobble.high > e.routeWobble.high,
			"and walks where it meant to");
	}

	Printf("\nElite is fallible on purpose\n");
	{
		const SkillBands e = BandsFor(SkillLevel::Elite);
		Check(e.reaction.low >= 10,
			"the best bot still takes a seventh of a second to notice");
		Check(e.aimEnvelope.low > 0, "still has an error floor");
		Check(e.trackingDelay.low > 0, "still aims behind a moving target");
		Check(e.maxYaw.high <= (unsigned int)YAW_CEILING,
			"and still cannot spin instantly");
		Check(!IsShippable(SkillLevel::Perfect),
			"and the profile that has none of those limits is not shippable");
	}

	Printf("\nA profile carries both axes\n");
	{
		const uint32_t p = MakeProfile(SkillLevel::Veteran, 2);
		Check(SkillOf(p) == SkillLevel::Veteran && PersonaOf(p) == 2,
			"skill and personality survive the round trip");
		Check(SkillOf(MakeProfile(SkillLevel::Elite, 7)) == SkillLevel::Elite,
			"and a high personality index does not leak into the skill");
		Check(SkillOf(0xFFFFFFFFu) == SkillLevel::Marine,
			"an unknown level reads as the middle of the ladder, not the top");
	}

	Printf("\nThe same bot twice\n");
	{
		Random a, b;
		a.Seed(99, 3, 0, Stream::Skill);
		b.Seed(99, 3, 0, Stream::Skill);
		const Traits ta = Draw(SkillLevel::Veteran, a);
		const Traits tb = Draw(SkillLevel::Veteran, b);
		Check(ta.reaction == tb.reaction && ta.maxYaw == tb.maxYaw &&
			ta.aimEnvelope == tb.aimEnvelope && ta.searchMemory == tb.searchMemory,
			"one seed draws one set of traits");

		Random c;
		c.Seed(99, 4, 0, Stream::Skill);
		const Traits tc = Draw(SkillLevel::Veteran, c);
		Check(ta.reaction != tc.reaction || ta.maxYaw != tc.maxYaw ||
			ta.aimEnvelope != tc.aimEnvelope,
			"and two bots of one level are not the same bot");
	}

	Printf("\n%d checks, %d failures\n", g_checks, g_failures);
	return g_failures;
}

uint32_t MakeProfile(SkillLevel level, unsigned int persona)
{
	return ((uint32_t)persona << 8) | (uint32_t)level;
}

SkillLevel SkillOf(uint32_t profile)
{
	const uint32_t raw = profile & 0xFF;
	if(raw >= (uint32_t)SkillLevel::NUM)
		return SkillLevel::Marine;
	return (SkillLevel)raw;
}

unsigned int PersonaOf(uint32_t profile)
{
	return (unsigned int)(profile >> 8);
}

}
