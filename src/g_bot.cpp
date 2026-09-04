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
#include "g_botnav.h"
#include "actor.h"
#include "wl_agent.h"
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

// How close to a waypoint counts as reaching it. Under half a tile, so a
// waypoint is not ticked off from the next cell along, and comfortably more
// than a tic's travel so it is not skated past.
const fixed ARRIVE_WITHIN = (fixed)(24<<10);

// A tic of no new tile, times this many, and the bot decides the route is not
// working. Generous: a legitimate turn at a corner can take most of a second.
const unsigned int STUCK_TICS = 105;

// The bot's own pawn, and nothing else's. Section 11.4 permits a bot exact
// knowledge of itself and nothing about anyone else; this is the only place a
// bot reads the world at all until perception arrives in step five.
AActor *OwnPawn(Session::PlayerSlot slot)
{
	if(slot >= MAXPLAYERS)
		return NULL;
	if(players[slot].mo == NULL || players[slot].health <= 0)
		return NULL;
	return players[slot].mo;
}

// The private state a repeat run has to reproduce. Not the command: that is
// in the world digest already, by way of the pawn it moves.
void Record(State &bot, uint32_t sequence, Session::PlayerSlot slot)
{
	bot.commandsProduced++;
	bot.lastSequence = sequence;

	FoldDigest(&sequence, sizeof(sequence));
	const uint8_t s = (uint8_t)slot;
	FoldDigest(&s, sizeof(s));
	const uint8_t behavior = (uint8_t)bot.behavior;
	FoldDigest(&behavior, sizeof(behavior));
	const uint32_t waypoint = bot.waypoint;
	FoldDigest(&waypoint, sizeof(waypoint));
	const uint16_t goal = (uint16_t)bot.goal;
	FoldDigest(&goal, sizeof(goal));
	for(unsigned int i = 0;i < (unsigned int)Stream::NUM;++i)
	{
		const uint64_t st = bot.rng[i].State();
		FoldDigest(&st, sizeof(st));
	}
}

// Somewhere to go: a node picked from the graph with the bot's own random,
// far enough away to be worth walking to and reachable from here.
bool ChooseRoamGoal(State &bot, const BotNav::Graph &graph, AActor *pawn,
	uint32_t sequence)
{
	const BotNav::NodeId here = graph.NodeAt(pawn->tilex, pawn->tiley);
	if(here == BotNav::NO_NODE)
		return false;

	// A named destination, for a gate that needs the bot to go somewhere
	// specific rather than somewhere random. Everything after this point is
	// the ordinary follower, so what gets tested is the real thing.
	int forcedX = 0, forcedY = 0;
	if(ForcedGoal(forcedX, forcedY))
	{
		const BotNav::NodeId target = graph.NodeAt(forcedX, forcedY);
		if(target == BotNav::NO_NODE || target == here)
			return false;

		BotNav::SearchStats stats;
		if(!graph.FindPath(here, target, bot.route, stats))
		{
			++bot.goalSearchFailures;
			bot.nextGoalSearch = sequence + 35;
			return false;
		}
		bot.goal = target;
		bot.waypoint = 0;
		++bot.routesPlanned;
		FString detail;
		detail.Format("forced to=%d,%d len=%u", forcedX, forcedY,
			bot.route.Size());
		TraceEvent(bot.slot, "route", detail.GetChars());
		return true;
	}

	// Two passes. The first wants somewhere worth walking to; the second will
	// take anywhere at all.
	//
	// The distinction matters more than it looks. The graph of an arena is
	// often not one region but several -- MAP60 comes apart into 274, 166, 55,
	// 25 and 25 nodes -- and a bot that spawns in a small one has nothing six
	// tiles away that it can reach. The first version of this gave up,
	// silently, and then gave up again on the next tic, and stood still for
	// the entire match having written "none found" to its trace one thousand
	// one hundred and seventy-five times.
	//
	// What separates those regions is transporters, not doors: MAP60 has
	// sixteen of them and no door at all. Door edges, added in step 5, merged
	// MAP51 from two regions into one and changed nothing anywhere else,
	// because one door is all eight shipped arenas contain between them.
	//
	// A bot in a cupboard should pace the cupboard.
	for(unsigned int pass = 0;pass < 2;++pass)
	{
		const int wantDistanceSquared = pass == 0 ? 36 : 1;
		for(unsigned int attempt = 0;attempt < 8;++attempt)
		{
		const BotNav::NodeId candidate =
			(BotNav::NodeId)bot.Draw(Stream::GoalTieBreak).Below(graph.NodeCount());
		if(candidate == here)
			continue;

		const BotNav::Node &there = graph.NodeOf(candidate);
		const int dx = (int)there.x - (int)pawn->tilex;
		const int dy = (int)there.y - (int)pawn->tiley;
		if(dx*dx + dy*dy < wantDistanceSquared)
			continue;

		BotNav::SearchStats stats;
		TArray<BotNav::NodeId> route;
		if(!graph.FindPath(here, candidate, route, stats))
			continue;

		// Followed unsmoothed, on purpose.
		//
		// Smoothing a forty-tile route into four waypoints produces a
		// waypoint thirty-seven tiles away, and steering at it means walking a
		// straight line the follower cannot actually walk: it turns at a
		// limited rate, drifts, and grinds into the first wall the ideal line
		// passed close to. The first roam did exactly that and reported itself
		// stuck after a hundred tics.
		//
		// The plan's answer is a short look-ahead target on the path rather
		// than a distant waypoint, and the shortest look-ahead available is
		// the next node: one tile, always reachable in a straight line,
		// because the graph only has that edge if the body fits along it.
		// Smoothing stays -- it is what a cost estimate and a route summary
		// want -- and the follower stops using it until there is a follower
		// that aims at a point rather than a node.
		bot.route = route;
		bot.waypoint = 1;		// nought is where it already is
		bot.goal = candidate;
		++bot.routesPlanned;
		bot.lastTileX = pawn->tilex;
		bot.lastTileY = pawn->tiley;
		bot.lastProgressSeq = sequence;

		FString detail;
		detail.Format("to=%u,%u waypoints=%u expansions=%u",
			there.x, there.y, route.Size(), stats.expansions);
		TraceEvent(bot.slot, "route", detail.GetChars());
		return true;
		}
	}

	// Nowhere to go. Said once and then not again until the retry is due,
	// because a failure repeated seventy times a second is not seventy times
	// as informative.
	++bot.goalSearchFailures;
	if(bot.goalSearchFailures == 1 || (bot.goalSearchFailures % 32) == 0)
	{
		FString detail;
		detail.Format("at=%d,%d attempt=%u", pawn->tilex, pawn->tiley,
			bot.goalSearchFailures);
		TraceEvent(bot.slot, "nowhere", detail.GetChars());
	}
	bot.nextGoalSearch = sequence + 35;		// half a second
	return false;
}

// Step four: a brain that knows who it is, where it is going, and how to walk
// there. Perception arrives with the sensor boundary; until then it knows
// nothing whatever about anybody else, which is why it roams rather than
// hunts.
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

		AActor *pawn = OwnPawn(forSlot);
		if(pawn == NULL)
		{
			// Dead, or not spawned. Dropping the route matters: coming back
			// somewhere else and walking the old one would be a bot heading
			// for a waypoint chosen for a different life.
			if(bot->behavior != Behavior::DeadWaitingToRespawn)
			{
				bot->behavior = Behavior::DeadWaitingToRespawn;
				bot->behaviorSince = sequence;
				bot->route.Clear();
				bot->goal = BotNav::NO_NODE;
				bot->doorNode = BotNav::NO_NODE;
				bot->unstuckUntil = 0;
				TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
			}

			// Ask to come back the way a person does: press use. The engine
			// respawns a dead player on bt_use once RespawnEligible has
			// passed, and gives up waiting a hundred tics later -- so a bot
			// that pressed nothing would still return, just always late and
			// never by its own doing. Pulsed rather than held for the same
			// reason a door is.
			if(!bot->doorUseLastTic)
			{
				out.press[bt_use] = true;
				if(bot->respawnPresses < 0xFFFFFFFFu)
					++bot->respawnPresses;
			}
			bot->doorUseLastTic = out.press[bt_use];

			Record(*bot, sequence, forSlot);
			return true;
		}

		if(bot->behavior == Behavior::DeadWaitingToRespawn)
		{
			// Back in the world. Orienting first is not decoration: it is the
			// gap in which a bot has no business acting on anything it saw
			// before it died.
			++bot->respawnsCompleted;
			bot->behavior = Behavior::SpawnOrient;
			bot->behaviorSince = sequence;
			TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
		}

		// Scheduling is by sequence, never by wall clock: two machines have
		// different clocks and the same sequence numbers.
		if(sequence >= bot->nextThink)
		{
			bot->nextThink = sequence + ThinkInterval;
			if(bot->behavior == Behavior::SpawnOrient &&
				sequence - bot->behaviorSince >= OrientTics)
			{
				bot->behavior = Behavior::Roam;
				bot->behaviorSince = sequence;
				TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
			}
		}

		if(bot->behavior == Behavior::Unstuck)
			Unstuck(*bot, pawn, sequence, out);
		else if(bot->behavior == Behavior::UseTraversal)
			WorkDoor(*bot, pawn, sequence, out);
		else if(bot->behavior == Behavior::Roam)
			Steer(*bot, pawn, sequence, out);

		Record(*bot, sequence, forSlot);
		return true;
	}

	const char *Describe() const { return "bot"; }

private:
	enum { ThinkInterval = 12, OrientTics = 14 };
	Session::PlayerSlot slot;

	// Face a point, and report how far off the heading still is.
	//
	// Shared by the follower and the door protocol so that "turn toward it"
	// means one thing. The sign is worth stating twice: a positive controlx
	// *decreases* the pawn's angle, so turning toward a larger angle is a
	// negative command.
	static uint32_t FaceToward(AActor *pawn, fixed tx, fixed ty,
		Command::Intent &out)
	{
		const angle_t want = BotNav::BearingTo(pawn->x, pawn->y, tx, ty);
		const int32_t rotate = BotNav::ShortestTurn(pawn->angle, want);
		const int units = (int)((int64_t)rotate/(int64_t)(ANGLE_1/20));
		int turn = -units;
		if(turn > MAX_YAW) turn = MAX_YAW;
		if(turn < -MAX_YAW) turn = -MAX_YAW;
		out.turn = turn;

		return (uint32_t)rotate < 0x80000000u
			? (uint32_t)rotate : (uint32_t)(0u - (uint32_t)rotate);
	}

	// Back out of whatever the pawn walked into, then let the follower pick a
	// fresh route.
	//
	// Replanning alone is not enough. A route is a function of where the bot
	// is, so a bot wedged in a corner replans from the corner and gets a route
	// that begins by walking into the same wall. Moving first is what makes
	// the next plan a different plan.
	static void Unstuck(State &bot, AActor *pawn, uint32_t sequence,
		Command::Intent &out)
	{
		if(sequence >= bot.unstuckUntil)
		{
			bot.behavior = Behavior::Roam;
			bot.behaviorSince = sequence;
			bot.lastProgressSeq = sequence;
			bot.wasAskedToMove = false;
			TraceEvent(bot.slot, "behavior", BehaviorName(bot.behavior));
			return;
		}

		// Backwards and sideways at once, away from whatever is in front.
		// Both, because either alone has a corner it cannot leave: straight
		// back retraces the way in, and pure strafe grinds along the face it
		// is already touching.
		out.forward = -BASEMOVE;
		out.strafe = bot.unstuckStrafe;
		out.turn = bot.unstuckStrafe > 0 ? MAX_YAW/2 : -MAX_YAW/2;
		bot.wasAskedToMove = true;
	}

	// Open the door in front, then hand the route back to the follower.
	//
	// Section 12.4: approach on a permitted face, turn into the use-facing
	// tolerance, pulse use for one command edge, watch for the door actually
	// moving rather than assume it did, and cross only when the traversal
	// query says the boundary is open -- which is the same truth the collision
	// path uses, not a visual approximation of it.
	static void WorkDoor(State &bot, AActor *pawn, uint32_t sequence,
		Command::Intent &out)
	{
		BotNav::Graph &graph = BotNav::Current();
		if(bot.doorNode == BotNav::NO_NODE || !graph.Built())
		{
			bot.behavior = Behavior::Roam;
			bot.behaviorSince = sequence;
			return;
		}

		const BotNav::Node &door = graph.NodeOf(bot.doorNode);
		const fixed half = (fixed)(1<<(TILESHIFT-1));
		const fixed tx = (fixed)(door.x<<TILESHIFT) + half;
		const fixed ty = (fixed)(door.y<<TILESHIFT) + half;

		// Standing in the doorway means the boundary is behind us and the job
		// is done. This has to be asked before the step query, because the
		// step query cannot answer it: from inside the cell the step is to
		// itself, and a door cell still holds a tile, so CanOccupyTile refuses
		// it and the protocol would sit in an open doorway pressing use --
		// which shuts the door it just walked through.
		const bool inDoorway = (unsigned)pawn->tilex == door.x &&
			(unsigned)pawn->tiley == door.y;

		// Otherwise: has it opened? Asked of the query the pawn obeys, from
		// where the pawn is standing. This goes true on the tic the panel
		// finishes sliding and not before, which is what "sufficient opening"
		// means when the collision path requires a fully open boundary.
		Traversal::Body body;
		body.radius = pawn->radius;
		body.isPlayer = true;
		body.ignore = pawn;
		if(inDoorway || Traversal::CanStepBetweenTiles(body, pawn->tilex,
			pawn->tiley, door.x, door.y))
		{
			++bot.doorsOpened;
			TraceEvent(bot.slot, "door-open", NULL);

			// Step over the door in the route. Once the boundary is open the
			// door cell is just a cell, and the next waypoint is on the far
			// side of it -- so walking at that one crosses the doorway.
			//
			// Without this the follower hands straight back to a waypoint that
			// is still the door, re-enters the protocol, succeeds again, and
			// reports the same door opened five hundred and seventeen times in
			// one match.
			if(bot.waypoint < bot.route.Size() &&
				bot.route[bot.waypoint] == bot.doorNode)
				++bot.waypoint;

			bot.doorNode = BotNav::NO_NODE;
			bot.behavior = Behavior::Roam;
			bot.behaviorSince = sequence;
			bot.lastProgressSeq = sequence;
			return;
		}

		// Give up and replan. A door can be locked against this bot, jammed by
		// somebody standing in it, or approached from a face that does not
		// open; none of those are distinguishable from here and none of them
		// are worth standing in front of forever.
		if(sequence - bot.doorSince > DOOR_PATIENCE)
		{
			++bot.doorsGivenUp;
			++bot.routesAbandoned;
			FString detail;
			detail.Format("at=%d,%d door=%u,%u pulses=%u",
				pawn->tilex, pawn->tiley, door.x, door.y, bot.doorPulses);
			TraceEvent(bot.slot, "door-gave-up", detail.GetChars());
			bot.doorNode = BotNav::NO_NODE;
			bot.route.Clear();
			bot.goal = BotNav::NO_NODE;
			bot.behavior = Behavior::Roam;
			bot.behaviorSince = sequence;
			bot.lastProgressSeq = sequence;
			return;
		}

		const uint32_t off = FaceToward(pawn, tx, ty, out);

		// Square-on before pressing. Door_Open is dispatched from the pawn's
		// facing, so using it while pointed along the wall opens whatever is
		// over there instead of what is in front.
		if(off > ANGLE_45/3)
		{
			bot.wasAskedToMove = false;
			return;
		}

		// One command edge, then watch. Not a pulse train.
		//
		// Use on a door that is already open is not ignored: Door_Open hands
		// an existing door to Reactivate, which shuts it. A bot pressing every
		// other tic therefore opens the door and closes it again, forever, and
		// what that looks like from outside is a door that never opens -- the
		// engine reported the trigger firing 292 times while the boundary was
		// never once crossable.
		//
		// So press once, and press again only if nothing has happened for long
		// enough that the first press must have been lost. This is the "pulse
		// for one command edge; observe whether the door actually began
		// opening rather than assuming success" of section 12.4, and the
		// observation is the traversal query above.
		const bool firstPress = bot.doorPulses == 0;
		const bool longSilence = sequence - bot.doorPulsedAt > DOOR_REPULSE;
		if(!bot.doorUseLastTic && (firstPress || longSilence))
		{
			out.press[bt_use] = true;
			++bot.doorPulses;
			bot.doorPulsedAt = sequence;
			FString detail;
			detail.Format("at=%d,%d door=%u,%u ang=%u off=%u n=%u",
				pawn->tilex, pawn->tiley, door.x, door.y,
				(unsigned)(pawn->angle/ANGLE_1), (unsigned)(off/ANGLE_1),
				bot.doorPulses);
			TraceEvent(bot.slot, "door-press", detail.GetChars());
		}
		bot.doorUseLastTic = out.press[bt_use];

		// Ease up to the panel while it opens rather than standing off it, so
		// that the moment it clears the pawn is already there. Walking pace,
		// because the boundary is still solid and this is a controlled nudge
		// into it, not a run at it.
		out.forward = BASEMOVE;
		bot.wasAskedToMove = true;
	}

	// Walk the route, one waypoint at a time.
	static void Steer(State &bot, AActor *pawn, uint32_t sequence,
		Command::Intent &out)
	{
		BotNav::Graph &graph = BotNav::Current();
		if(!graph.Built())
		{
			Traversal::Body body;
			body.radius = pawn->radius;
			body.isPlayer = true;
			body.ignore = pawn;
			if(!graph.Build(body))
				return;
			FString detail;
			detail.Format("nodes=%u edges=%u digest=%08x",
				graph.NodeCount(), graph.EdgeCount(),
				(unsigned int)graph.Digest());
			TraceEvent(bot.slot, "graph", detail.GetChars());
		}

		if(bot.waypoint >= bot.route.Size())
		{
			if(bot.route.Size() > 0)
			{
				++bot.routesCompleted;
				TraceEvent(bot.slot, "arrived", NULL);
			}
			bot.route.Clear();
			if(sequence < bot.nextGoalSearch)
				return;
			if(!ChooseRoamGoal(bot, graph, pawn, sequence))
				return;
		}

		// Progress is a new tile, not distance covered: a pawn grinding along
		// a wall moves without getting anywhere.
		//
		// The clock only runs while the bot is asking to move. A bot turning
		// on the spot -- which this follower does deliberately whenever the
		// heading is more than forty-five degrees out -- is aiming, not stuck,
		// and a half-circle at three degrees a tic takes sixty of them. Timing
		// that as though it were a failure to move would report a route as
		// unwalkable because the bot took a moment to face down it.
		const bool tryingToMove = bot.wasAskedToMove;
		if(pawn->tilex != bot.lastTileX || pawn->tiley != bot.lastTileY)
		{
			bot.lastTileX = (uint16_t)pawn->tilex;
			bot.lastTileY = (uint16_t)pawn->tiley;
			bot.lastProgressSeq = sequence;
		}
		else if(!tryingToMove)
		{
			bot.lastProgressSeq = sequence;
		}
		else if(sequence - bot.lastProgressSeq > STUCK_TICS)
		{
			// The graph offered a step the pawn could not walk. This is the
			// one number the traversal gate cannot produce, because it can
			// only check that the pawn never went somewhere the query forbade
			// -- never that everything the query allowed was walkable.
			++bot.stepsRefused;
			++bot.routesAbandoned;

			FString detail;
			const BotNav::Node &target =
				graph.NodeOf(bot.route[MIN(bot.waypoint,
					(unsigned int)bot.route.Size() - 1)]);
			detail.Format("at=%d,%d toward=%u,%u after=%u tics",
				pawn->tilex, pawn->tiley, target.x, target.y,
				sequence - bot.lastProgressSeq);
			TraceEvent(bot.slot, "refused", detail.GetChars());

			bot.route.Clear();
			bot.goal = BotNav::NO_NODE;
			bot.lastProgressSeq = sequence;

			// Move before replanning. A route is a function of where the bot
			// is standing, so replanning from the corner it is wedged in
			// produces a route that starts by walking into the same wall.
			bot.behavior = Behavior::Unstuck;
			bot.behaviorSince = sequence;
			bot.unstuckUntil = sequence + UNSTUCK_TICS;
			bot.unstuckStrafe = bot.rng[(unsigned int)Stream::Movement].Below(2)
				? BASEMOVE : -BASEMOVE;
			++bot.unstuckEntered;
			TraceEvent(bot.slot, "behavior", BehaviorName(bot.behavior));
			return;
		}

		if(bot.waypoint >= bot.route.Size())
			return;

		// A door on the way. Handing over here rather than inside the walk
		// keeps the follower a follower: it walks at waypoints, and a boundary
		// that has to be operated before it can be crossed is a different job
		// with a different protocol and its own way of failing.
		if(graph.NodeOf(bot.route[bot.waypoint]).isDoor)
		{
			bot.doorNode = bot.route[bot.waypoint];
			bot.doorSince = sequence;
			bot.doorPulses = 0;
			bot.behavior = Behavior::UseTraversal;
			bot.behaviorSince = sequence;
			TraceEvent(bot.slot, "behavior", BehaviorName(bot.behavior));
			WorkDoor(bot, pawn, sequence, out);
			return;
		}

		const BotNav::Node &next = graph.NodeOf(bot.route[bot.waypoint]);
		const fixed half = (fixed)(1<<(TILESHIFT-1));
		const fixed tx = (fixed)(next.x<<TILESHIFT) + half;
		const fixed ty = (fixed)(next.y<<TILESHIFT) + half;

		const fixed dx = tx - pawn->x;
		const fixed dy = ty - pawn->y;
		if(abs(dx) < ARRIVE_WITHIN && abs(dy) < ARRIVE_WITHIN)
		{
			++bot.waypoint;
			return;
		}

		// Turn toward it, at a rate a hand could manage.
		const uint32_t off = FaceToward(pawn, tx, ty, out);

		if((sequence % 40) == 0)
		{
			// Recomputed for the trace rather than kept: both are integer
			// functions of state the trace already prints, and the follower
			// does not otherwise need them.
			const angle_t want = BotNav::BearingTo(pawn->x, pawn->y, tx, ty);
			const int32_t rotate = BotNav::ShortestTurn(pawn->angle, want);
			FString detail;
			detail.Format("wp=%u/%u at=%d,%d ang=%u want=%u off=%d turn=%d",
				bot.waypoint, bot.route.Size(),
				pawn->tilex, pawn->tiley,
				(unsigned)(pawn->angle/ANGLE_1), (unsigned)(want/ANGLE_1),
				(int)(rotate/(int32_t)ANGLE_1), out.turn);
			TraceEvent(bot.slot, "steer", detail.GetChars());
		}

		// Forward, and how much of it depends on how far off the heading is.
		//
		// The first version ran at walking pace while ninety degrees off, on
		// the theory that a bot should keep moving. What it actually does is
		// orbit: at three degrees a tic it cannot turn toward a target one
		// tile away faster than it walks past it, so it circles the waypoint
		// indefinitely -- angle winding steadily, bearing winding with it, and
		// the follower reporting a ninety degree error on every single tic.
		//
		// So a sharp heading error is turned out before moving. A quarter turn
		// takes about half a second, which is slower than a person and not by
		// much, and it converges.
		if(off > ANGLE_45)
			out.forward = 0;			// point at it first
		else if(off > ANGLE_45/3)
			out.forward = BASEMOVE;
		else
			out.forward = RUNMOVE;

		// Read on the next tic by the stuck clock, which only runs while the
		// bot was actually asking to go somewhere.
		bot.wasAskedToMove = out.forward != 0;
	}

	enum {
		MAX_YAW = 60,				// three degrees a tic, 210 a second
		// Long enough for a door to open and for a body blocking one to move
		// off it, short enough that a locked door is not a career.
		DOOR_PATIENCE = 210,
		// Long enough that a door which is opening is left alone to open --
		// pressing again would close it -- and short enough to recover from a
		// press that did nothing at all.
		DOOR_REPULSE = 105,
		UNSTUCK_TICS = 24
	};
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

Totals Tally()
{
	Totals total;
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		if(!g_active[i])
			continue;
		total.routesPlanned += g_state[i].routesPlanned;
		total.routesCompleted += g_state[i].routesCompleted;
		total.routesAbandoned += g_state[i].routesAbandoned;
		total.stepsRefused += g_state[i].stepsRefused;
		total.goalSearchFailures += g_state[i].goalSearchFailures;
		total.doorsOpened += g_state[i].doorsOpened;
		total.doorsGivenUp += g_state[i].doorsGivenUp;
		total.unstuckEntered += g_state[i].unstuckEntered;
		total.respawnPresses += g_state[i].respawnPresses;
		total.respawnsCompleted += g_state[i].respawnsCompleted;
	}
	return total;
}

static int g_forcedGoalX = -1;
static int g_forcedGoalY = -1;

void SetForcedGoal(int tileX, int tileY)
{
	g_forcedGoalX = tileX;
	g_forcedGoalY = tileY;
}

bool ForcedGoal(int &tileX, int &tileY)
{
	if(g_forcedGoalX < 0 || g_forcedGoalY < 0)
		return false;
	tileX = g_forcedGoalX;
	tileY = g_forcedGoalY;
	return true;
}

static int g_overlay = 0;

int  Overlay() { return g_overlay; }
void SetOverlay(int level)
{
	g_overlay = level < 0 ? 0 : (level >= OVERLAY_LEVELS ? OVERLAY_LEVELS - 1 : level);
}

bool RouteOf(Session::PlayerSlot slot, TArray<uint16_t> &tileX,
	TArray<uint16_t> &tileY, unsigned int &waypoint)
{
	tileX.Clear();
	tileY.Clear();
	waypoint = 0;
	if(slot >= MAXPLAYERS || !g_active[slot])
		return false;

	const State &bot = g_state[slot];
	const BotNav::Graph &graph = BotNav::Current();
	if(!graph.Built())
		return false;

	waypoint = bot.waypoint;
	for(unsigned int i = 0;i < bot.route.Size();++i)
	{
		const BotNav::Node &node = graph.NodeOf(bot.route[i]);
		tileX.Push(node.x);
		tileY.Push(node.y);
	}
	return true;
}

bool WhereIs(Session::PlayerSlot slot, fixed &x, fixed &y)
{
	AActor *const pawn = OwnPawn(slot);
	if(pawn == NULL || slot >= MAXPLAYERS || !g_active[slot])
		return false;
	x = pawn->x;
	y = pawn->y;
	return true;
}

const char *BehaviorOf(Session::PlayerSlot slot)
{
	if(slot >= MAXPLAYERS || !g_active[slot])
		return NULL;
	return BehaviorName(g_state[slot].behavior);
}

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

	Printf("\nBearings, without a library that rounds differently elsewhere\n");
	{
		// Eight compass points and a handful of awkward ones, against the
		// engine's own convention: angle 0 is east, angles increase
		// anticlockwise, and y increases downward.
		struct Case { int dx, dy; unsigned int degrees; const char *what; };
		static const Case cases[] = {
			{  100,    0,   0, "east" },
			{  100, -100,  45, "north-east" },
			{    0, -100,  90, "north" },
			{ -100, -100, 135, "north-west" },
			{ -100,    0, 180, "west" },
			{ -100,  100, 225, "south-west" },
			{    0,  100, 270, "south" },
			{  100,  100, 315, "south-east" },
			{ 1000,    1,   0, "very nearly east" },
			{    1, 1000, 270, "very nearly south" },
		};
		unsigned int worst = 0;
		for(unsigned int i = 0;i < sizeof(cases)/sizeof(cases[0]);++i)
		{
			const angle_t got = BotNav::BearingTo(0, 0,
				(fixed)cases[i].dx, (fixed)cases[i].dy);
			const angle_t want = (angle_t)(((uint64_t)cases[i].degrees<<32)/360);
			const uint32_t off = (uint32_t)got - (uint32_t)want;
			const uint32_t err = off < 0x80000000u ? off : (uint32_t)(0u - off);
			// A tenth of a degree, in angle_t units.
			const uint32_t tenth = (uint32_t)((1ull<<32)/3600);
			if(err > worst)
				worst = err;
			FString label;
			label.Format("bearing to %s is within a tenth of a degree",
				cases[i].what);
			Check(err < tenth*10, label.GetChars());
		}
		Printf("  ..   worst bearing error %.4f degrees\n",
			(double)worst*360.0/4294967296.0);

		// And it must be exactly reproducible, which is the whole reason it is
		// not atan2.
		bool stable = true;
		for(int i = 0;i < 500;++i)
		{
			const fixed x = (fixed)(i*7919), y = (fixed)(i*104729);
			stable = stable && BotNav::BearingTo(0, 0, x, y) ==
				BotNav::BearingTo(0, 0, x, y);
		}
		Check(stable, "and the same two points always give the same bearing");
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
		// There is no map and no pawn here, and the right answer to that is to
		// wait rather than to act. The check used to expect Roam, which was
		// true when the brain decided nothing and stopped being true the
		// moment it started looking for its own pawn before moving.
		Check(StateFor(0)->behavior == Behavior::DeadWaitingToRespawn,
			"a brain with no pawn waits instead of walking into nothing");

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
