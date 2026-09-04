/*
** g_bot.h
**
** The thing that decides, and everything it is allowed to remember.
**
** A bot is an ordinary player slot with a controller that is not a person.
** Everything it does reaches the world the same way a person's input does --
** through Command::Producer, clamped and whitelisted by the same finalizer --
** and nothing in here may write a pawn, a score, an inventory or a trigger.
** That rule is the whole design; see docs/multiplayer-bots-and-server.md,
** section 11.6, and the review checklist that goes with it.
**
** Two things follow from where this hangs.
**
** It hangs off the session authority rather than off ConsolePlayer, so it
** constructs and runs on a process with no local player at all. That is not
** hypothetical tidiness: it is what keeps the dedicated server's bot work
** (Phase D, milestone D10) a re-home rather than a rewrite, and it is checked
** by the session self-test rather than left to good intentions.
**
** And its state lives here, keyed by slot, rather than on the pawn. The pawn
** is replicated; this is not. Every machine simulates the same bot pawn from
** the same commands, and exactly one machine knows why.
*/

#ifndef __G_BOT_H__
#define __G_BOT_H__

#include <stdint.h>

#include "wl_def.h"
#include "g_session.h"
#include "g_command.h"
#include "name.h"
#include "wl_play.h"

namespace Bot {

// Private random, per bot, per purpose.
//
// Bot variation must never draw from the playsim's streams: those are shared
// with weapons, damage and spawning, and taking a number here would make the
// number of bots in a match a term in every later random number in it. These
// are separate, deterministic, and seeded from data every machine agrees on,
// so a recorded match can be replayed and a bug report can be reproduced.
//
// Separate streams per purpose, so that an extra roaming decision cannot
// change the next aim error -- which would make one bot's behavior depend on
// another's in a way nobody could follow.
enum class Stream : uint8_t
{
	GoalTieBreak,
	Perception,
	Aim,
	Movement,
	Timing,
	NUM
};

class Random
{
public:
	void Seed(uint64_t matchSeed, unsigned int slot, uint32_t profile,
		Stream purpose);
	// splitmix64: small, fixed, and not the platform's, because the platform's
	// changes between libraries and this has to be the same everywhere.
	uint32_t Next();
	// Unbiased, so that a bound which is not a power of two does not quietly
	// favor the low end of the range.
	unsigned int Below(unsigned int bound);
	int Range(int low, int high);
	uint64_t State() const { return state; }

private:
	uint64_t state = 0;
};

// What a bot is doing, in the large. States are not animations and never
// bypass gameplay: each one selects an intent that becomes an ordinary
// command.
enum class Behavior : uint8_t
{
	DeadWaitingToRespawn,
	SpawnOrient,
	Roam,
	SeekPickup,
	EngageEnemy,
	ChaseOrSearchLastContact,
	RetreatOrRecover,
	UseTraversal,
	Unstuck
};

const char *BehaviorName(Behavior behavior);

struct State
{
	Session::PlayerSlot slot = 0;
	uint32_t profile = 0;
	uint64_t seed = 0;

	Random rng[(unsigned int)Stream::NUM];

	Behavior behavior = Behavior::SpawnOrient;
	uint32_t behaviorSince = 0;

	// Expensive work is staggered by slot so that eight bots do not all think
	// on the same tic; see section 11.5. Sequences, not wall clock.
	uint32_t nextSense = 0;
	uint32_t nextThink = 0;
	uint32_t nextPath = 0;

	// Provenance, for the assertions in section 11.6 and for the trace.
	unsigned int commandsProduced = 0;
	uint32_t lastSequence = 0;
	TicCmd_t lastCommand;

	// Named Draw rather than Stream: a member function with the same name as
	// the enum it takes changes what that name means inside the class, which
	// the compiler is right to object to.
	Random &Draw(Bot::Stream purpose)
	{
		return rng[(unsigned int)purpose];
	}
};

// --- lifecycle -----------------------------------------------------------------

void Reset();
// Attach a brain to a slot the authority owns. The seed is match data every
// machine has, so two runs of the same match produce the same bot.
void Configure(Session::PlayerSlot slot, uint32_t profile, uint64_t matchSeed);
bool Active(Session::PlayerSlot slot);
State *StateFor(Session::PlayerSlot slot);
unsigned int Count();

// How many bots the command line asked for, and the slots to carry them.
// Called where the tape's slots are added: after the human roster is settled,
// before the player classes are resolved, because a slot that appears later
// never gets a pawn.
void SetupSlots(FName (&playerClassNames)[MAXPLAYERS]);
int Requested();
void SetRequested(int count);

// A producer for one bot slot. Ownership passes to the command layer.
Command::Producer *MakeProducer(Session::PlayerSlot slot);

// --- diagnostics ----------------------------------------------------------------

// Deliberately built before there is anything to decide.
//
// "It sometimes gets stuck" is not an actionable bug report, and the way that
// gets answered is by dumping what the bot believed and chose rather than by
// inferring it from where the pawn ended up. Inferring it from where the pawn
// ended up is exactly how three separate investigations of a non-existent
// arena bug went wrong; the instrument comes first this time.
void OpenTrace(const char *path);
void CloseTrace();
void TraceEvent(Session::PlayerSlot slot, const char *event, const char *detail);

// Authority-only, and never compared with a client: clients do not run these
// brains and cannot reproduce this state. Separate from the world digest so
// that "the machines disagree about what happened" and "this machine's brains
// did something different than last run" stay separate questions.
uint32_t BrainDigest();

// Constructs brains against a session with no local player and no socket, and
// checks the private random is reproducible, independent per purpose, and
// unbiased. Data-free and windowless; --bottest.
int SelfTest();

}

#endif
