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
#include "g_botnav.h"
#include "g_combat.h"

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

	// Where it is going, and how far along.
	TArray<BotNav::NodeId> route;
	unsigned int   waypoint = 0;
	BotNav::NodeId goal = BotNav::NO_NODE;

	// Stuck detection. Progress is measured in tiles reached, not in distance
	// travelled: a pawn grinding along a wall covers ground without getting
	// anywhere, and the second number is the one that matters.
	uint16_t lastTileX = 0;
	uint16_t lastTileY = 0;
	uint32_t lastProgressSeq = 0;
	// Did last tic's command ask to move? The stuck clock only runs when it
	// did; see the comment where it is read.
	bool     wasAskedToMove = false;

	unsigned int routesPlanned = 0;
	unsigned int routesCompleted = 0;
	unsigned int routesAbandoned = 0;
	// A step the graph offered and the pawn could not walk. This is the number
	// the traversal gate cannot produce, because it can only compare what the
	// pawn did against what the query allows -- never the other way round. A
	// query that is too permissive shows up here and nowhere else.
	unsigned int stepsRefused = 0;
	// Nowhere reachable to go. Not a fault in itself -- an arena's graph can
	// come apart into regions, and a bot in a small one has few choices -- but
	// a bot that never finds a goal never moves, and that should be a number
	// rather than a silence. What fragments these arenas is transporters, not
	// doors; see the step 5 record.
	unsigned int goalSearchFailures = 0;
	uint32_t     nextGoalSearch = 0;

	// The door protocol. A door is the one place the follower stops being a
	// plain "walk at the next waypoint" loop, because the boundary has to be
	// made passable before it can be crossed and the making takes time.
	BotNav::NodeId doorNode = BotNav::NO_NODE;
	uint32_t     doorSince = 0;
	unsigned int doorPulses = 0;
	// bt_use is pulsed, not held: Door_Open refuses a held use outright (it
	// checks buttonheld and returns), so a bot leaning on the key would stand
	// in front of an unopened door forever.
	bool         doorUseLastTic = false;
	uint32_t     doorPulsedAt = 0;
	unsigned int doorsOpened = 0;
	unsigned int doorsGivenUp = 0;

	// Unstuck. Backing off and turning away is what a person does when they
	// walk into geometry; abandoning the route without moving leaves the bot
	// in the same corner to pick a route out of it that starts the same way.
	uint32_t     unstuckUntil = 0;
	int          unstuckStrafe = 0;
	unsigned int unstuckEntered = 0;
	// Which rung of section 12.11's ladder the next failure gets. Escalates
	// while failures keep happening in the same place and resets on progress,
	// so an ordinary bump costs a moment of strafing and a genuine blockage
	// works its way up to giving the goal away.
	unsigned int stuckStage = 0;
	uint32_t     stageResetAt = 0;
	// Cells this bot could not get through lately, priced up in its own
	// searches and nobody else's.
	BotNav::BlockedCells blocked;
	unsigned int cellsBlocked = 0;

	// Presses made while dead, and lives actually returned to. Two numbers,
	// because a bot pulses use for as long as it takes and one respawn can
	// cost thirty-six presses: "asked" and "came back" answer different
	// questions and only the second is an outcome.
	unsigned int respawnPresses = 0;
	unsigned int respawnsCompleted = 0;

	// Where the pawn was last tic, for spotting a jump. Distinct from the
	// stuck clock's lastTile, which only moves when progress is made: this one
	// moves every tic and exists to notice when the world moved the pawn
	// rather than the bot.
	uint16_t     seenTileX = 0;
	uint16_t     seenTileY = 0;
	bool         haveSeenTile = false;
	// What this bot can see, and what it last saw. Section 13.7's contact
	// memory in its first form: who was visible on the last sense update, and
	// when each slot was last actually seen.
	//
	// Kept as values with a tic on them rather than as a live query, because
	// the difference between "I can see you" and "I saw you a moment ago" is
	// the whole of what stops a bot tracking somebody through a wall.
	// When the decision layer is allowed to know about each contact, as
	// opposed to when the sensor saw it. Section 13.3: detection and action
	// are separate, and a bot that acts on the tic its eye caught something is
	// a bot with no reaction time at all.
	//
	// Paid on acquisition only. A target held in view keeps updating at the
	// tracking cadence without buying the delay again, which is how a person
	// works: noticing costs, following does not.
	// When the sensor first caught this contact, and when the brain is
	// allowed to know. Both, because the gap between them is the reaction
	// time and a gate has to be able to read it off the trace.
	uint32_t     sightedAt[MAXPLAYERS];
	uint32_t     noticeAt[MAXPLAYERS];
	bool         knownNow[MAXPLAYERS];
	unsigned int contactsNoticed = 0;
	// Summed release delay, so a gate can check the average rather than only
	// the bounds.
	unsigned int reactionTicsTotal = 0;

	// Combat. Section 16.
	//
	// The target is a slot this bot has been *told about* -- a released
	// observation, not a sighting the sensor made this tic and the brain has
	// not yet reacted to.
	unsigned int target = MAXPLAYERS;
	uint32_t     targetSince = 0;
	unsigned int targetsAcquired = 0;
	unsigned int targetSwitches = 0;
	unsigned int shotsFired = 0;
	// Tics spent with a target and a clear enough shot to take it.
	unsigned int ticsOnTarget = 0;
	Combat::AimError aim;
	// When the trigger may next be considered, so a bot does not decide about
	// firing on every single tic.
	uint32_t     nextTrigger = 0;
	// The weapon being carried, as a slot number, and when to reconsider.
	int          holdingSlot = 0;
	uint32_t     nextWeaponThink = 0;
	unsigned int weaponSwitches = 0;
	// Combat strafing, held for a commitment interval rather than rechosen
	// every tic.
	uint32_t     strafeUntil = 0;
	int          strafeSide = 0;

	// A short history of where the target was seen, so the aimer can use a
	// sample no newer than its tracking delay. Section 16.3: an aimer reading
	// the current position is an aimer that cannot be made to miss a moving
	// target, however much error is added afterwards.
	enum { AIM_HISTORY = 16 };
	fixed        seenX[AIM_HISTORY];
	fixed        seenY[AIM_HISTORY];
	uint32_t     seenWhen[AIM_HISTORY];
	unsigned int seenHead = 0;

	uint32_t     lastSeenAt[MAXPLAYERS];
	uint16_t     lastSeenTileX[MAXPLAYERS];
	uint16_t     lastSeenTileY[MAXPLAYERS];
	bool         visibleNow[MAXPLAYERS];
	unsigned int contactsGained = 0;
	unsigned int contactsLost = 0;
	// Contacts walked to the last place they were seen, and contacts given up
	// on. Section 13.7: a bot may search a last known location or abandon the
	// contact, and may never keep an exact lock on somebody hidden.
	unsigned int searchesStarted = 0;
	unsigned int contactsForgotten = 0;
	// The slot being searched for, and where. NO_NODE-ish: MAXPLAYERS means
	// nobody.
	unsigned int searchingFor = MAXPLAYERS;
	// When to next reconsider what to fetch, and how many times a fetch has
	// been chosen.
	uint32_t     nextItemThink = 0;
	unsigned int itemGoals = 0;

	unsigned int teleports = 0;
	unsigned int frozenTics = 0;
	// Plan no transporters until this sequence. Set on arrival, because the
	// cell a transporter lands you on is usually beside its counterpart and
	// the cheapest way out of the arrival area is often straight back.
	uint32_t     portCooldownUntil = 0;

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

// The pawn a bot is driving, or NULL when it is dead or has not spawned.
// Exposed for the sensor layer, which needs an eye to look from; nothing that
// reads this may hand the pointer to a brain.
AActor *OwnPawn(Session::PlayerSlot slot);
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

// Totals across every bot, for the summary line and for gates. `refused` is
// the one to watch: a step the graph offered and a pawn could not walk, which
// is the failure the traversal gate structurally cannot see.
struct Totals
{
	unsigned int routesPlanned = 0;
	unsigned int routesCompleted = 0;
	unsigned int routesAbandoned = 0;
	unsigned int stepsRefused = 0;
	// Nowhere reachable to go. Not a fault in itself -- an arena's graph can
	// come apart into regions, and a bot in a small one has few choices -- but
	// a bot that never finds a goal never moves, and that should be a number
	// rather than a silence.
	//
	// What actually fragments these arenas is transporters, not doors: seven
	// of the eight have no door in them at all. See the step 5 record.
	unsigned int goalSearchFailures = 0;
	unsigned int doorsOpened = 0;
	unsigned int doorsGivenUp = 0;
	unsigned int unstuckEntered = 0;
	unsigned int respawnPresses = 0;
	unsigned int respawnsCompleted = 0;
	unsigned int teleports = 0;
	unsigned int frozenTics = 0;
	unsigned int cellsBlocked = 0;
	unsigned int contactsGained = 0;
	unsigned int contactsLost = 0;
	unsigned int contactsNoticed = 0;
	unsigned int reactionTicsTotal = 0;
	unsigned int searchesStarted = 0;
	unsigned int contactsForgotten = 0;
	unsigned int itemGoals = 0;
	unsigned int targetsAcquired = 0;
	unsigned int shotsFired = 0;
	unsigned int ticsOnTarget = 0;
	unsigned int weaponSwitches = 0;
};
Totals Tally();

// Send every bot to one tile, over and over, instead of roaming.
//
// A gate needs this because the interesting cells are rare: there is exactly
// one door in the eight shipped arenas, one cell of MAP51's 960, and a random
// walk priced against it does not find that cell in a match. Naming the
// destination is how the door protocol gets tested at all -- and it tests the
// real protocol, since everything downstream of the goal is the ordinary
// follower.
void SetForcedGoal(int tileX, int tileY);
bool ForcedGoal(int &tileX, int &tileY);

// Debug overlay support.
//
// Read-only views, by copy, of what a bot is currently doing. The drawing code
// gets no pointer into a brain and so cannot disturb one: a debug view that
// perturbs the thing it shows sends you hunting a bug that exists only while
// you are looking at it. test_bot_overlay.sh checks the world and the brains
// come out identical with the overlay off, on, and drawing the whole graph.

// 0 off, 1 routes and state, 2 adds the graph the routes were planned on. A
// level rather than a flag because the graph is thousands of edges: useful
// when the question is "could it have gone that way", noise otherwise.
int  Overlay();
void SetOverlay(int level);
enum { OVERLAY_LEVELS = 3 };

// An active bot's route as tile coordinates, and how far along it the bot has
// got. False when the slot holds no active bot, or there is no graph yet.
bool RouteOf(Session::PlayerSlot slot, TArray<uint16_t> &tileX,
	TArray<uint16_t> &tileY, unsigned int &waypoint);
// What it thinks it is doing. NULL for a slot with no active bot.
const char *BehaviorOf(Session::PlayerSlot slot);
// And where its pawn is, in map units, so the overlay can label it there
// without reaching for the pawn itself.
bool WhereIs(Session::PlayerSlot slot, fixed &x, fixed &y);

// Constructs brains against a session with no local player and no socket, and
// checks the private random is reproducible, independent per purpose, and
// unbiased. Data-free and windowless; --bottest.
int SelfTest();

}

#endif
