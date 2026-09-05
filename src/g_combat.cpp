/*
** g_combat.cpp
**
** See g_combat.h.
*/

#include "g_combat.h"
#include "g_bot.h"
#include "wl_play.h"
#include "wl_agent.h"
#include "thingdef/thingdef.h"
#include "a_inventory.h"

namespace Combat {

void AimError::Reset()
{
	angle = 0;
	velocity = 0;
	bias = 0;
	nextBias = 0;
}

void Step(AimError &error, Bot::Random &rng, uint32_t sequence,
	int32_t envelope)
{
	if(envelope <= 0)
	{
		error.Reset();
		return;
	}

	// A new place to drift toward, every so often. The dwell is what makes the
	// error look like a hand settling somewhere slightly wrong and staying
	// there, rather than like noise.
	if(sequence >= error.nextBias)
	{
		// Uniform inside the envelope, signed.
		const int32_t span = envelope*2;
		error.bias = (int32_t)rng.Below((uint32_t)span) - envelope;
		// 35 to 105 tics: half a second to a second and a half.
		error.nextBias = sequence + 35 + rng.Below(70);
	}

	// Spring toward the bias, with a little noise on top. The restoring force
	// is deliberately weak -- a stiff spring snaps to the bias and holds it,
	// which is a constant offset and not an error at all.
	const int32_t toward = (error.bias - error.angle)/8;
	const int32_t jitter = (int32_t)rng.Below((uint32_t)(envelope/4 + 1)) -
		(envelope/8);
	error.velocity += toward + jitter;

	// Bounded, so the error cannot wind up into a spin.
	const int32_t maxSpeed = envelope/4 + 1;
	if(error.velocity > maxSpeed) error.velocity = maxSpeed;
	if(error.velocity < -maxSpeed) error.velocity = -maxSpeed;

	error.angle += error.velocity;

	// And clamped, with the velocity killed at the wall so it does not press
	// against it for tics on end.
	if(error.angle > envelope)  { error.angle = envelope;  error.velocity = 0; }
	if(error.angle < -envelope) { error.angle = -envelope; error.velocity = 0; }
}

// The eight, in slot order.
//
// Ranges and values are first estimates from what each weapon is for, not
// measurements: the bands say a bayonet is a melee weapon and a shotgun is a
// close one, which is true whatever the exact numbers turn out to be. Section
// 16.6 wants each of these tuned against its own test, and those tests are
// what will move these numbers.
static const WeaponInfo g_weapons[] =
{
	{ "C7Bayonet",       1, WeaponKind::Melee,       0,  2,  10, true  },
	{ "C7Shotgun",       2, WeaponKind::Hitscan,     0,  8,  70, true  },
	{ "C7M16",           3, WeaponKind::Hitscan,     0, 30,  50, true  },
	{ "C7M343",          4, WeaponKind::Burst,       2, 24,  60, true  },
	{ "C7DualBlaster",   5, WeaponKind::Hitscan,     0, 20,  55, true  },
	{ "C7PlasmaRifle",   6, WeaponKind::Projectile,  4, 30,  65, true  },
	{ "C7AssaultCannon", 7, WeaponKind::MultiTarget, 0, 26,  80, true  },
	// Enormous energy cost and a broad multi-target attack. Not an ordinary
	// gun, and not something to fire because it happened to score highest;
	// section 16.6 asks for its own tests before a bot reaches for it.
	{ "C7Disintegrator", 8, WeaponKind::MultiTarget, 0, 30,  90, false },
};

const WeaponInfo *Weapons(unsigned int &count)
{
	count = sizeof(g_weapons)/sizeof(g_weapons[0]);
	return g_weapons;
}

int ChooseSlotFrom(unsigned int carried, int rangeTiles)
{
	int bestSlot = 0, bestScore = 0;
	for(unsigned int i = 0;i < sizeof(g_weapons)/sizeof(g_weapons[0]);++i)
	{
		const WeaponInfo &w = g_weapons[i];
		if(!w.supported)
			continue;
		if(!(carried & (1u<<(w.slot - 1))))
			continue;		// not carrying it
		if(rangeTiles < w.nearTiles || rangeTiles > w.farTiles)
			continue;		// wrong range for this weapon

		// Within its band, prefer the more valuable weapon; ties break on the
		// lower slot so two bots with the same kit make the same choice.
		if(w.value > bestScore)
		{
			bestScore = w.value;
			bestSlot = w.slot;
		}
	}
	return bestSlot;
}

int ChooseSlot(Session::PlayerSlot slot, int rangeTiles)
{
	if(slot >= MAXPLAYERS || players[slot].mo == NULL)
		return 0;

	unsigned int carried = 0;
	for(unsigned int i = 0;i < sizeof(g_weapons)/sizeof(g_weapons[0]);++i)
	{
		const ClassDef *def = ClassDef::FindClass(g_weapons[i].cls);
		if(def != NULL && players[slot].mo->FindInventory(def) != NULL)
			carried |= 1u<<(g_weapons[i].slot - 1);
	}
	return ChooseSlotFrom(carried, rangeTiles);
}

// --- self-test ------------------------------------------------------------

namespace {
int g_checks = 0, g_failures = 0;
void Check(bool ok, const char *what)
{
	++g_checks;
	if(!ok)
	{
		++g_failures;
		Printf("  FAIL %s\n", what);
	}
	else
		Printf("  ok   %s\n", what);
}
}

int SelfTest()
{
	g_checks = g_failures = 0;
	Printf("Combat aim self-test\n");

	Printf("\nThe error stays inside its envelope\n");
	{
		const int32_t envelope = AUTO_AIM_CONE*2;   // twenty degrees
		Bot::Random rng;
		rng.Seed(1234, 0, 0, Bot::Stream::Aim);
		AimError error;
		int32_t worst = 0;
		for(uint32_t t = 0;t < 4000;++t)
		{
			Step(error, rng, t, envelope);
			const int32_t mag = error.angle < 0 ? -error.angle : error.angle;
			if(mag > worst)
				worst = mag;
		}
		Check(worst <= envelope, "never exceeds the envelope it was given");
		Check(worst > envelope/2,
			"and uses most of it rather than sitting near zero");
	}

	Printf("\nIt drifts rather than jumping\n");
	{
		const int32_t envelope = AUTO_AIM_CONE*2;
		Bot::Random rng;
		rng.Seed(99, 0, 0, Bot::Stream::Aim);
		AimError error;
		int32_t previous = 0, biggestJump = 0;
		for(uint32_t t = 0;t < 2000;++t)
		{
			Step(error, rng, t, envelope);
			const int32_t jump = error.angle - previous;
			const int32_t mag = jump < 0 ? -jump : jump;
			if(mag > biggestJump)
				biggestJump = mag;
			previous = error.angle;
		}
		// A tic-to-tic step is bounded by the velocity clamp. Independent
		// noise would routinely jump the width of the envelope, which is the
		// implementation this exists to rule out: it averages away over the
		// few tics a shot takes to line up, and the bot never misses.
		Check(biggestJump <= envelope/4 + 1,
			"one tic moves the aim by a bounded amount, not across the envelope");
	}

	Printf("\nA wide envelope actually leaves the auto-aim cone\n");
	{
		// The point of the whole file. Ten degrees of error is not an error:
		// FindTarget acquires anything within ten degrees regardless. A bot
		// only misses when its aim is outside that cone when it fires.
		const int32_t envelope = AUTO_AIM_CONE*2;
		Bot::Random rng;
		rng.Seed(7, 0, 0, Bot::Stream::Aim);
		AimError error;
		unsigned int outside = 0, total = 0;
		for(uint32_t t = 0;t < 4000;++t)
		{
			Step(error, rng, t, envelope);
			const int32_t mag = error.angle < 0 ? -error.angle : error.angle;
			if(mag > AUTO_AIM_CONE)
				++outside;
			++total;
		}
		Check(outside > total/20,
			"a twenty degree envelope spends real time outside the ten degree cone");

		// And the converse, which is the trap: a narrow envelope produces a
		// bot that is theoretically inaccurate and practically perfect.
		Bot::Random tight;
		tight.Seed(7, 0, 0, Bot::Stream::Aim);
		AimError small;
		unsigned int everOutside = 0;
		for(uint32_t t = 0;t < 4000;++t)
		{
			Step(small, tight, t, AUTO_AIM_CONE/2);
			const int32_t mag = small.angle < 0 ? -small.angle : small.angle;
			if(mag > AUTO_AIM_CONE)
				++everOutside;
		}
		Check(everOutside == 0,
			"a five degree envelope never leaves the cone, so it never misses");
	}

	Printf("\nThe weapon table\n");
	{
		unsigned int count = 0;
		const WeaponInfo *table = Weapons(count);
		Check(count == 8, "all eight weapons are described");

		bool slotsSane = true, bandsSane = true;
		unsigned int seen = 0;
		for(unsigned int i = 0;i < count;++i)
		{
			slotsSane = slotsSane && table[i].slot >= 1 && table[i].slot <= 8 &&
				!(seen & (1u<<table[i].slot));
			seen |= 1u<<table[i].slot;
			bandsSane = bandsSane && table[i].nearTiles <= table[i].farTiles;
		}
		Check(slotsSane, "each sits on its own slot, one to eight");
		Check(bandsSane, "and none has a band that runs backwards");
	}

	Printf("\nChoosing a weapon for the range\n");
	{
		// Bits are slots: 1 bayonet, 2 shotgun, 3 M16, 4 M343, 5 dual blaster,
		// 6 plasma, 7 assault cannon, 8 disintegrator.
		const unsigned int spawnKit = (1u<<0) | (1u<<2);        // bayonet, M16
		Check(ChooseSlotFrom(spawnKit, 1) == 3,
			"a gun beats a knife even in someone's face");
		Check(ChooseSlotFrom(spawnKit, 25) == 3,
			"and the M16 is the answer at range with nothing better");

		const unsigned int withShotgun = spawnKit | (1u<<1);
		Check(ChooseSlotFrom(withShotgun, 2) == 2,
			"a shotgun wins up close");
		Check(ChooseSlotFrom(withShotgun, 20) == 3,
			"and loses past its range, where the M16 still reaches");

		const unsigned int withCannon = withShotgun | (1u<<6);
		Check(ChooseSlotFrom(withCannon, 20) == 7,
			"the assault cannon outranks the M16 where both reach");

		// The disintegrator is in the table and deliberately not supported:
		// an enormous energy cost and a broad multi-target attack that section
		// 16.6 wants tested on its own before a bot reaches for it.
		Check(ChooseSlotFrom(withCannon | (1u<<7), 20) == 7,
			"and the disintegrator is not chosen while it is unsupported");

		Check(ChooseSlotFrom(0, 10) == 0, "carrying nothing chooses nothing");
		Check(ChooseSlotFrom(spawnKit, 999) == 0,
			"and nothing reaches a target that far away");
	}

	Printf("\nReproducible\n");
	{
		Bot::Random a, b;
		a.Seed(555, 1, 2, Bot::Stream::Aim);
		b.Seed(555, 1, 2, Bot::Stream::Aim);
		AimError ea, eb;
		bool same = true;
		for(uint32_t t = 0;t < 500;++t)
		{
			Step(ea, a, t, AUTO_AIM_CONE*2);
			Step(eb, b, t, AUTO_AIM_CONE*2);
			same = same && ea.angle == eb.angle;
		}
		Check(same, "the same seed aims the same way twice");
	}

	Printf("\n%d checks, %d failures\n", g_checks, g_failures);
	return g_failures;
}

}
