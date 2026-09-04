/*
** g_bot.cpp
**
** See g_bot.h for what this is and where it hangs.
*/

#include <stdio.h>
#include <string.h>

#include "g_bot.h"
#include "wl_play.h"
#include "wl_main.h"
#include "zstring.h"
#include "m_random.h"
#include "wl_game.h"
#include "name.h"

namespace Bot {

// --- private random ---------------------------------------------------------

void Random::Seed(uint64_t matchSeed, unsigned int slot, uint32_t profile,
	Bot::Stream purpose)
{
	// Mixed rather than concatenated: slot and purpose are small numbers, and
	// seeding two streams with adjacent values makes their first few draws
	// visibly related.
	uint64_t mixed = matchSeed;
	mixed = mixed*0x9E3779B97F4A7C15ull + (uint64_t)slot;
	mixed = mixed*0x9E3779B97F4A7C15ull + (uint64_t)profile;
	mixed = mixed*0x9E3779B97F4A7C15ull + (uint64_t)purpose;
	if(mixed == 0)
		mixed = 0x9E3779B97F4A7C15ull;
	state = mixed;
}

uint32_t Random::Next()
{
	state += 0x9E3779B97F4A7C15ull;
	uint64_t z = state;
	z = (z ^ (z >> 30))*0xBF58476D1CE4E5B9ull;
	z = (z ^ (z >> 27))*0x94D049BB133111EBull;
	z = z ^ (z >> 31);
	return (uint32_t)(z >> 32);
}

unsigned int Random::Below(unsigned int bound)
{
	if(bound == 0)
		return 0;
	// Rejection rather than modulo: a plain % favors the low end whenever the
	// bound does not divide 2^32, which over a match is a bot that turns left
	// slightly more often than right for no reason anyone could find.
	const uint32_t limit = (uint32_t)(0x100000000ull % bound);
	uint32_t draw;
	do
	{
		draw = Next();
	} while(draw < limit);
	return draw % bound;
}

int Random::Range(int low, int high)
{
	if(high <= low)
		return low;
	return low + (int)Below((unsigned int)(high - low + 1));
}

const char *BehaviorName(Behavior behavior)
{
	switch(behavior)
	{
		case Behavior::DeadWaitingToRespawn: return "dead";
		case Behavior::SpawnOrient:          return "spawn";
		case Behavior::Roam:                 return "roam";
		case Behavior::SeekPickup:           return "pickup";
		case Behavior::EngageEnemy:          return "engage";
		case Behavior::ChaseOrSearchLastContact: return "chase";
		case Behavior::RetreatOrRecover:     return "retreat";
		case Behavior::UseTraversal:         return "traverse";
		case Behavior::Unstuck:              return "unstuck";
	}
	return "?";
}

// --- state ------------------------------------------------------------------

namespace {

State    g_state[MAXPLAYERS];
bool     g_active[MAXPLAYERS] = { false };
int      g_requested = -1;
uint32_t g_brainDigest = 0;
FILE    *g_trace = NULL;

void FoldDigest(const void *data, size_t len)
{
	const unsigned char *p = (const unsigned char *)data;
	for(size_t i = 0;i < len;++i)
	{
		g_brainDigest ^= p[i];
		g_brainDigest *= 16777619u;
	}
}

}

void Reset()
{
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		g_state[i] = State();
		g_active[i] = false;
	}
	g_brainDigest = 0;
}

void Configure(Session::PlayerSlot slot, uint32_t profile, uint64_t matchSeed)
{
	if(slot >= MAXPLAYERS)
		return;

	State &bot = g_state[slot];
	bot = State();
	bot.slot = slot;
	bot.profile = profile;
	bot.seed = matchSeed;
	for(unsigned int s = 0;s < (unsigned int)Stream::NUM;++s)
		bot.rng[s].Seed(matchSeed, slot, profile, (Stream)s);

	// Staggered from the start, so that the first think of eight bots does not
	// land on one tic.
	bot.nextSense = slot;
	bot.nextThink = slot;
	bot.nextPath = slot;
	bot.behavior = Behavior::SpawnOrient;
	bot.behaviorSince = 0;
	memset(&bot.lastCommand, 0, sizeof(bot.lastCommand));

	g_active[slot] = true;

	FString detail;
	detail.Format("profile=%u seed=%llu", profile,
		(unsigned long long)matchSeed);
	TraceEvent(slot, "configure", detail.GetChars());
}

bool Active(Session::PlayerSlot slot)
{
	return slot < MAXPLAYERS && g_active[slot];
}

State *StateFor(Session::PlayerSlot slot)
{
	return Active(slot) ? &g_state[slot] : NULL;
}

unsigned int Count()
{
	unsigned int count = 0;
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		if(g_active[i])
			++count;
	}
	return count;
}

// --- the producer -------------------------------------------------------------

namespace {

// Step one of B2 has a brain that knows who it is, remembers what it decided,
// and decides nothing. Navigation arrives with the graph; perception with the
// sensor boundary. Until then it stands still on purpose rather than moving at
// random, because a bot that wanders without a reason is indistinguishable
// from one whose reasons are broken.
class BotProducer : public Command::Producer
{
public:
	explicit BotProducer(Session::PlayerSlot slot) : slot(slot) {}

	bool Produce(Session::PlayerSlot forSlot, uint32_t sequence,
		Command::Intent &out)
	{
		State *bot = StateFor(forSlot);
		if(bot == NULL)
			return false;

		out.Clear();

		// Scheduling is by sequence, never by wall clock: two machines have
		// different clocks and the same sequence numbers.
		if(sequence >= bot->nextThink)
		{
			bot->nextThink = sequence + ThinkInterval;
			// Where the state machine will go. It has one transition today,
			// out of the state a bot starts in, so that the trace shows the
			// machinery running rather than an empty file.
			if(bot->behavior == Behavior::SpawnOrient &&
				sequence - bot->behaviorSince >= OrientTics)
			{
				bot->behavior = Behavior::Roam;
				bot->behaviorSince = sequence;
				TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
			}
		}

		bot->commandsProduced++;
		bot->lastSequence = sequence;

		// The private state that a repeat run has to reproduce. Not the
		// command -- that is in the world digest already, through the pawn.
		const uint32_t seq = sequence;
		FoldDigest(&seq, sizeof(seq));
		const uint8_t s = (uint8_t)forSlot;
		FoldDigest(&s, sizeof(s));
		const uint8_t behavior = (uint8_t)bot->behavior;
		FoldDigest(&behavior, sizeof(behavior));
		for(unsigned int i = 0;i < (unsigned int)Stream::NUM;++i)
		{
			const uint64_t st = bot->rng[i].State();
			FoldDigest(&st, sizeof(st));
		}

		return true;
	}

	const char *Describe() const { return "bot"; }

private:
	enum { ThinkInterval = 12, OrientTics = 14 };
	Session::PlayerSlot slot;
};

}

Command::Producer *MakeProducer(Session::PlayerSlot slot)
{
	return new BotProducer(slot);
}

void SetupSlots(FName (&playerClassNames)[MAXPLAYERS])
{
	const int wanted = Requested();
	if(wanted <= 0)
		return;

	// The seed every machine already agrees on, so two runs of one match
	// produce the same bots and a recorded match replays.
	const uint64_t matchSeed = (uint64_t)rngseed;

	for(int i = 0;i < wanted;++i)
	{
		const unsigned int slot = Session::AddAuthoritySlot((uint32_t)0,
			matchSeed ^ (uint64_t)i);
		if(slot >= Session::MAX_PLAYER_SLOTS)
		{
			Printf("Only room for %d bot%s; %d asked for.\n",
				i, i == 1 ? "" : "s", wanted);
			break;
		}

		Configure((Session::PlayerSlot)slot, 0, matchSeed);
		Command::SetProducer((Session::PlayerSlot)slot, MakeProducer(slot));
		// The same character as the player it stands in for, so it is an
		// ordinary opponent rather than something with different rules.
		playerClassNames[slot] = playerClassNames[0];
		Printf("Bot in slot %u.\n", slot);
	}
}

// --- diagnostics ----------------------------------------------------------------

void OpenTrace(const char *path)
{
	CloseTrace();
	g_trace = fopen(path, "w");
	if(g_trace != NULL)
		fprintf(g_trace, "# tic slot event detail\n");
}

void CloseTrace()
{
	if(g_trace != NULL)
	{
		fclose(g_trace);
		g_trace = NULL;
	}
}

void TraceEvent(Session::PlayerSlot slot, const char *event, const char *detail)
{
	if(g_trace == NULL)
		return;
	// The tic, always. A record without one cannot be lined up against the
	// command trace or the player trace, and lining those three up is the
	// entire reason for having any of them.
	fprintf(g_trace, "%lu %u %s %s\n",
		(unsigned long)gamestate.TimeCount, (unsigned)slot, event,
		detail != NULL ? detail : "");
	fflush(g_trace);
}

uint32_t BrainDigest() { return g_brainDigest; }

int Requested() { return g_requested; }

void SetRequested(int count) { g_requested = count; }

// --- self-test ------------------------------------------------------------------
//
// Everything here runs against a session the game cannot yet play: an authority
// with slots and no player of its own. That is the shape a server has, and a
// brain that can only be built next to a local player is a brain Phase D would
// have to rewrite rather than re-home.
//
// Nothing below touches players[], ConsolePlayer, or a socket.

namespace {

unsigned int g_checks = 0;
unsigned int g_failures = 0;

void Check(bool ok, const char *what)
{
	++g_checks;
	if(ok)
		return;
	++g_failures;
	Printf("  FAIL %s\n", what);
}

void BuildPlayerlessAuthority(unsigned int bots)
{
	Session::State &s = Session::Current();
	s.Reset();
	s.role = Session::RuntimeRole::DedicatedAuthority;
	s.lifecycle = Session::Lifecycle::Running;

	const Session::PeerId server = (Session::PeerId)(bots + 1);
	s.peers[0].id = server;
	s.peers[0].authority = true;
	s.peerCount = 1;
	s.authorityPeer = server;
	s.localPeer = server;

	for(unsigned int i = 0;i < bots;++i)
	{
		s.slots[i].kind = Session::SlotKind::Bot;
		s.slots[i].botProfile = (uint32_t)0;
		s.slots[i].controllerSeed = (uint64_t)i;
	}
	s.activeSlots = bots;
	s.reservedSlots = bots;
}

uint32_t DrainDigest(unsigned int slots, unsigned int tics)
{
	for(unsigned int t = 0;t < tics;++t)
	{
		for(unsigned int slot = 0;slot < slots;++slot)
		{
			Command::Producer *producer = Command::ProducerFor(slot);
			if(producer == NULL)
				continue;
			Command::Intent intent;
			producer->Produce((Session::PlayerSlot)slot, t, intent);
		}
	}
	return BrainDigest();
}

void BuildFour(uint64_t seed)
{
	Reset();
	Command::ClearProducers();
	for(unsigned int slot = 0;slot < 4;++slot)
	{
		Configure((Session::PlayerSlot)slot, 0, seed);
		Command::SetProducer((Session::PlayerSlot)slot, MakeProducer(slot));
	}
}

}

int SelfTest()
{
	g_checks = g_failures = 0;
	Printf("Bot model self-test\n");

	Printf("\nPrivate random\n");
	{
		Random a, b;
		a.Seed(12345, 3, 7, Stream::Aim);
		b.Seed(12345, 3, 7, Stream::Aim);
		bool same = true;
		for(unsigned int i = 0;i < 64;++i)
			same = same && (a.Next() == b.Next());
		Check(same, "the same seed produces the same sequence");

		Random c, d;
		c.Seed(12345, 3, 7, Stream::Aim);
		d.Seed(12345, 3, 7, Stream::Movement);
		bool differs = false;
		for(unsigned int i = 0;i < 64 && !differs;++i)
			differs = c.Next() != d.Next();
		Check(differs, "two purposes do not share a sequence");

		Random e, f;
		e.Seed(12345, 3, 7, Stream::Aim);
		f.Seed(12345, 4, 7, Stream::Aim);
		differs = false;
		for(unsigned int i = 0;i < 64 && !differs;++i)
			differs = e.Next() != f.Next();
		Check(differs, "two slots do not share a sequence");

		Random g;
		g.Seed(1, 0, 0, Stream::GoalTieBreak);
		bool inRange = true;
		for(unsigned int i = 0;i < 4096;++i)
			inRange = inRange && g.Below(7) < 7;
		Check(inRange, "Below stays under its bound");

		// The rejection sampling in Below, tested where it can be seen.
		//
		// The first version drew seventy thousand values under seven and
		// looked for a lean. It could not have failed: at that bound folding
		// skews by about one part in a billion. A green check that cannot go
		// red is worse than no check.
		//
		// Bound 0x60000000, counting how often the result lands in the lower
		// 0x40000000 -- two thirds of the range, so a uniform draw lands there
		// two times in three. Folding would make it three in four: eight
		// points apart, against a standard error of a fifth of a point.
		const unsigned int bound = 0x60000000u;
		const unsigned int lower = 0x40000000u;	// two thirds of bound
		unsigned int landedLow = 0;
		const unsigned int draws = 60000;
		Random h;
		h.Seed(99, 1, 0, Stream::Movement);
		for(unsigned int i = 0;i < draws;++i)
		{
			if(h.Below(bound) < lower)
				++landedLow;
		}
		const double share = (double)landedLow/(double)draws;
		Check(share > 0.645 && share < 0.690,
			"and rejects rather than folding, so no value is favored");

		Random r;
		r.Seed(5, 2, 0, Stream::Timing);
		bool bounded = true;
		for(unsigned int i = 0;i < 1024;++i)
		{
			const int v = r.Range(-20, 20);
			bounded = bounded && v >= -20 && v <= 20;
		}
		Check(bounded, "Range stays inside its range");
	}

	Printf("\nBrains on a machine with no player\n");
	{
		BuildPlayerlessAuthority(4);
		Check(!Session::HasLocalPlayer(),
			"the session under test has no local player");
		Check(!Session::HasLocalView(), "and no local view");

		BuildFour(4242);
		Check(Count() == 4, "four brains were built without one");
		Check(StateFor(0) != NULL && StateFor(3) != NULL,
			"and each has state of its own");
		Check(StateFor(0)->slot == 0 && StateFor(3)->slot == 3,
			"keyed by the slot it belongs to");

		const uint32_t first = DrainDigest(4, 200);
		Check(StateFor(0)->commandsProduced == 200,
			"every brain produced a command every tic");
		Check(StateFor(0)->behavior == Behavior::Roam,
			"and got far enough to leave the state it started in");

		BuildFour(4242);
		const uint32_t again = DrainDigest(4, 200);
		Check(first == again, "and a repeat run reproduced them exactly");

		BuildFour(99);
		const uint32_t other = DrainDigest(4, 200);
		Check(first != other, "while a different seed did not");

		Reset();
		Check(Count() == 0, "and Reset leaves nothing behind");
		Command::ClearProducers();
	}

	Session::Current().SetStandaloneSinglePlayer();

	Printf("\n%u checks, %u failures\n", g_checks, g_failures);
	if(g_failures == 0)
		Printf("PASS: brains exist on a machine with no player, and repeat.\n");
	else
		Printf("FAIL: the bot model does not hold.\n");
	return g_failures == 0 ? 0 : 1;
}

}
