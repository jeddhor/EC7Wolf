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
#include "wl_draw.h"
#include "g_botnav.h"
#include "g_perception.h"
#include "g_items.h"
#include "thingdef/thingdef.h"
#include "a_inventory.h"
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
uint64_t g_seedOverride = 0;
bool     g_haveSeedOverride = false;
// Marine by default: the middle of the ladder, so an unconfigured match is an
// ordinary one rather than the easiest or the hardest.
SkillLevel g_skill = SkillLevel::Marine;
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

Personality PersonalityFor(uint32_t profile)
{
	// Which temperament each bot gets, in the order they are added.
	//
	// The index used to be the slot, so a two-bot match handed out slots 1 and
	// 2 and got the cautious one first -- the temperament that holds twelve
	// tiles and backs away when you close. A playtest with two bots therefore
	// met one opponent that kept leaving, which reads as the bots not wanting
	// to fight rather than as one of three personalities doing its job.
	//
	// Steady first, then aggressive, then cautious. A small match gets the
	// ones that come at you; the full mix still appears once there are three.
	static const unsigned int order[3] = { 0, 2, 1 };
	const unsigned int persona = PersonaOf(profile);
	Personality p;
	switch(order[(persona == 0 ? 0 : persona - 1) % 3])
	{
		case 0:		// steady: the baseline the gates were tuned against
			p.retreatNeed = 250;
			p.preferRange = 8;
			p.mineEagerness = 100;
			p.itemAppetite = 100;
			break;
		case 1:		// cautious: leaves earlier, hangs back, mines readily
			p.retreatNeed = 180;
			// Ten, not twelve. Twelve is most of an arena away and reads as
			// disengagement rather than caution.
			p.preferRange = 10;
			p.mineEagerness = 140;
			p.itemAppetite = 120;
			break;
		default:	// aggressive: closes in and stays longer, and pays for it
			p.retreatNeed = 400;
			p.preferRange = 5;
			p.mineEagerness = 70;
			p.itemAppetite = 90;
			break;
	}
	return p;
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

	// Drawn once, here, from its own stream: a trait redrawn during a match is
	// not a trait, and drawing from a shared stream would make one bot's
	// reflexes depend on how many other bots are in the game.
	bot.traits = Draw(SkillOf(profile), bot.rng[(unsigned int)Stream::Skill]);

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
	detail.Format("profile=%u skill=%s persona=%u seed=%llu react=%u vision=%u "
		"yaw=%u accel=%d aim=%u track=%u think=%u memory=%u strafe=%u "
		"respawn=%u", profile, SkillName(SkillOf(profile)), PersonaOf(profile),
		(unsigned long long)matchSeed, bot.traits.reaction,
		bot.traits.visionInterval, (unsigned)bot.traits.maxYaw,
		bot.traits.yawAccel, (unsigned)(bot.traits.aimEnvelope/ANGLE_1),
		bot.traits.trackingDelay, bot.traits.thinkInterval,
		bot.traits.searchMemory, bot.traits.strafeCommit,
		bot.traits.respawnDelay);
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

// How often a bot reconsiders what to fetch. Not every tic: section 14.3's
// point is that noisy utility recomputed constantly makes a bot visibly
// indecisive, and this is the cheapest half of the answer.
const uint32_t ITEM_THINK_INTERVAL = 70;

// Health need at which a bot stops fighting and goes to fix it. The need curve
// is quadratic, so 400 is roughly a third of health gone.
//
// At namespace scope because both the producer and the goal chooser ask it,
// and the goal chooser is a free function: the same scope trap that caught
// ITEM_THINK_INTERVAL an hour earlier.
// Set at 250, which is half health, and deliberately not lower-sounding than
// it reads: the curve is quadratic, so 400 is a third of health left and by
// the time a bot notices it is usually well past that -- combat damage arrives
// in ten and twenty point pieces, so a bot checked at 40% and found itself at
// 16%. At that point the nearest dispenser is thirteen tiles away and it dies
// on the way, which is a retreat in name only.
const int RETREAT_NEED = 250;

// How far from the arrival pad counts as clear of it. Four tiles is outside
// the ring of cells a pad's trigger reaches, with one to spare for a bot still
// turning round.
//
// Out here at namespace scope rather than in the producer's enum, because the
// goal chooser is a free function and cannot see that enum -- the same trap
// that hid RETREAT_NEED above from the code that needed it.
// How long a bot spends looking at whatever just shot at it or made a noise.
// About a second: long enough to turn most of the way round at any skill,
// short enough that a noisy arena does not leave everybody standing still.
const uint32_t ALERT_TICS = 60;
// And how long it then ignores further noises, so that a bot within earshot of
// a fight cannot be held still by it.
const uint32_t ALERT_REST = 105;

const int PORT_CLEAR_TILES = 4;

// And how long a bot keeps walking rather than turning after a crossing. Long
// enough to carry it out of the pad's trigger at walking pace, short enough
// that a bot which arrives facing a wall is not committed to it.
const uint32_t PORT_CLEAR_TICS = 28;

}   // anonymous

// The bot's own pawn, and nothing else's. Section 11.4 permits a bot exact
// knowledge of itself and nothing about anyone else.
//
// No longer file-private: the sensor layer needs somewhere to look from. It is
// still the only place a bot's own body is read, and nothing that calls this
// may hand the pointer on to a brain -- a brain holding an actor can see
// through walls without anyone writing code that means it to.
AActor *OwnPawn(Session::PlayerSlot slot)
{
	if(slot >= MAXPLAYERS)
		return NULL;
	if(players[slot].mo == NULL || players[slot].health <= 0)
		return NULL;
	return players[slot].mo;
}

namespace {

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
	// One set of rules for both planners below: whatever this bot may not
	// route through at this moment.
	BotNav::SearchOptions options;
	// Keep clear of transporters until this bot has actually got clear of the
	// one it arrived on --- distance first, with the timer only as a backstop.
	//
	// It was the timer alone, and B8 broke it without touching it. The
	// avoidance exists to stop a bot stepping straight back onto the pad it
	// just came out of, and 210 tics was long enough to walk out of the ring
	// while bots pivoted instantly. Give them a human turn acceleration and
	// the same 210 tics no longer gets them out, so the bounce came back on
	// MAP60 --- twice in the first three hundred tics of a match.
	//
	// A rule measured in tics is a rule about how fast the bot walks, which is
	// a thing that changes. "Far enough away" does not.
	const int fromPadX = (int)pawn->tilex - (int)bot.portArrivedTileX;
	const int fromPadY = (int)pawn->tiley - (int)bot.portArrivedTileY;
	const bool nearArrivalPad = bot.portCooldownUntil != 0 &&
		abs(fromPadX) <= PORT_CLEAR_TILES && abs(fromPadY) <= PORT_CLEAR_TILES;
	options.avoidTransporters =
		sequence < bot.portCooldownUntil || nearArrivalPad;

	// And separately: no crossing at all while the cooldown runs.
	//
	// Kept apart from avoidTransporters because that one is relaxed by the
	// pass ladder below, and this one must not be. The ladder's last pass
	// exists so a bot with nowhere else to go still goes somewhere, and it
	// drops the pad avoidance to do it -- which on MAP60 handed a bot that
	// had crossed forty tics earlier a seven waypoint route whose first move
	// was the crossing back. Three separate attempts to fix that in the edge
	// filter changed nothing, because the filter was reading a flag the
	// ladder had already turned off.
	//
	// Walking near a pad is a preference and can be traded away. Crossing one
	// forty tics after arriving is the bounce itself.
	options.refuseCrossings = sequence < bot.portCooldownUntil;
	options.blocked = &bot.blocked;
	options.lethal = &bot.mined;
	options.now = sequence;

	// A transporter is never a destination.
	//
	// Walking onto one is the whole interaction: the bot arrives somewhere
	// else and the route it was following is void. Stated here rather than at
	// each site because the first version of this rule was applied only to
	// randomly chosen roam goals, and the very next match produced the same
	// stall from the *search* goal instead -- a bot had been seen standing on
	// a pad, so the place it was last seen was a pad, so that is where the
	// searcher went.
	//
	// The forced goal stays exempt: naming a pad is how the per-pad coverage
	// test drives one.
	struct Destination
	{
		static bool Usable(const BotNav::Graph &g, BotNav::NodeId id)
		{
			return id != BotNav::NO_NODE && !g.NodeOf(id).isTransporter;
		}
	};

	// Somewhere a contact was last seen, if this bot is looking for one. The
	// route is planned like any other and walked by the ordinary follower: a
	// bot searching is a bot walking to a place it has a reason to walk to,
	// not a special mode.
	//
	// It goes at the last *observed* position, which by now is old. That is
	// the point -- it is where the contact was, not where it is, and a bot
	// that arrives and finds nobody has learned what a player learns.
	if(bot.searchingFor < MAXPLAYERS)
	{
		const unsigned int who = bot.searchingFor;
		const BotNav::NodeId target =
			graph.NodeAt(bot.lastSeenTileX[who], bot.lastSeenTileY[who]);
		bot.searchingFor = MAXPLAYERS;		// one attempt, then ordinary roaming
		if(Destination::Usable(graph, target) && target != here)
		{
			BotNav::SearchStats stats;
			if(graph.FindPath(here, target, bot.route, stats, 0, &options))
			{
				bot.goal = target;
				bot.waypoint = 0;
				++bot.routesPlanned;
				FString detail;
				detail.Format("search slot=%u to=%u,%u len=%u", who,
					bot.lastSeenTileX[who], bot.lastSeenTileY[who],
					bot.route.Size());
				TraceEvent(bot.slot, "route", detail.GetChars());
				return true;
			}
		}
	}

	// Something worth fetching.
	//
	// Section 14.2's utility, in the form the milestone actually needs:
	//
	//     utility = need - route cost
	//
	// with the terms that require combat or a threat model left for B6 rather
	// than written as zeroes now. Every candidate is scored and every
	// rejection is named, because the exit criterion is that a bot collects
	// the expected thing *for explainable reasons*, and a choice nobody can
	// read is not explainable.
	int ignoredX = 0, ignoredY = 0;
	if(sequence >= bot.nextItemThink && !ForcedGoal(ignoredX, ignoredY))
	{
		bot.nextItemThink = sequence + ITEM_THINK_INTERVAL;

		unsigned int bestIndex = 0;
		int bestUtility = 0;
		bool haveBest = false;
		TArray<BotNav::NodeId> bestRoute;

		// Counted rather than logged one by one. Every candidate's fate is
		// still explained, in a line whose length does not grow with the
		// number of pickups on the map -- eleven annotations times three bots
		// times twenty decisions is six hundred lines of nearly identical
		// text, which explains nothing to anybody.
		unsigned int rejected[8] = { 0, 0, 0, 0, 0, 0, 0, 0 };

		// A bot that broke off a fight because it is bleeding wants health,
		// not the nearest useful thing. Without this it walks to whichever
		// dispenser scores highest -- and on MAP53, where ammunition
		// dispensers outnumber health ones two to one, that is usually
		// ammunition. Correct arithmetic, wrong answer: it is about to die.
		const bool wantsHealth =
			Items::Need(bot.slot, Items::Category::Health) >= RETREAT_NEED;

		for(unsigned int i = 0;i < Items::Count();++i)
		{
			const Items::Annotation &note = Items::At(i);
			const Items::Knowledge *known = Items::KnownTo(bot.slot, i);
			Items::Reject why = Items::Reject::None;
			int need = 0, cost = 0, utility = 0;

			if(wantsHealth && note.category != Items::Category::Health)
			{
				++rejected[(unsigned int)Items::Reject::NoNeed];
				continue;
			}

			// A pickup has to have been seen; a wall dispenser does not.
			//
			// Section 12.8's rule is that a spawn annotation is not current
			// availability, and it is about things that can be taken away: the
			// shotgun somebody else already collected is not there any more.
			// A dispenser is a wall. It does not move, it cannot be carried
			// off, and a player who has walked this arena once knows where the
			// health is without having to look at it again.
			//
			// Treating both the same left a bot bleeding to death beside a
			// health dispenser it had never happened to glance at.
			const bool believable = known != NULL &&
				(known->belief == Items::Belief::Present ||
					(note.dispenser && known->belief != Items::Belief::Gone));
			if(!believable)
			{
				why = known != NULL && known->belief == Items::Belief::Unknown
					? Items::Reject::Stale : Items::Reject::NotPresent;
			}
			else
			{
				need = note.category == Items::Category::Weapon
					? Items::NeedWeapon(bot.slot, note.cls)
					: Items::Need(bot.slot, note.category);
				if(need <= 0)
				{
					why = note.category == Items::Category::Weapon
						? Items::Reject::AlreadyHave : Items::Reject::NoNeed;
				}
				else
				{
					// A dispenser is a wall: the bot goes to a cell beside it
					// and presses use, so the routing target is a neighbour
					// rather than the tile itself.
					BotNav::NodeId to = BotNav::NO_NODE;
					if(note.dispenser)
					{
						static const int ax[4] = { 1, 0, -1, 0 };
						static const int ay[4] = { 0, -1, 0, 1 };
						for(unsigned int d = 0;d < 4;++d)
						{
							const int nx = (int)note.tileX + ax[d];
							const int ny = (int)note.tileY + ay[d];
							if(nx < 0 || ny < 0)
								continue;
							const BotNav::NodeId beside =
								graph.NodeAt((unsigned)nx, (unsigned)ny);
							if(beside != BotNav::NO_NODE)
							{
								to = beside;
								break;
							}
						}
					}
					else
						to = graph.NodeAt(note.tileX, note.tileY);
					TArray<BotNav::NodeId> route;
					BotNav::SearchStats stats;
					if(!Destination::Usable(graph, to) || to == here ||
						!graph.FindPath(here, to, route, stats, 0, &options))
						why = Items::Reject::Unreachable;
					else
					{
						// Route cost is in the graph's units, a cardinal step
						// being 100. Divided down so that a need of 1000 pays
						// for roughly thirty tiles of walking, which is most
						// of an arena and about right for something a bot
						// actually wants.
						cost = (int)(route.Size()*100)/3;
						utility = need - cost;
						if(utility <= 0)
							why = Items::Reject::TooFar;
						else if(haveBest && utility <= bestUtility)
							why = Items::Reject::LostToBetter;
						else
						{
							if(haveBest)
								++rejected[(unsigned int)Items::Reject::LostToBetter];
							haveBest = true;
							bestIndex = i;
							bestUtility = utility;
							bestRoute = route;
						}
					}
				}
			}

			if(why != Items::Reject::None)
				++rejected[(unsigned int)why];
		}

		// One line saying what was considered and why nearly all of it lost.
		{
			FString why;
			for(unsigned int r = 1;r < 8;++r)
			{
				if(rejected[r] == 0)
					continue;
				FString one;
				one.Format("%s%s=%u", why.IsEmpty() ? "" : " ",
					Items::RejectName((Items::Reject)r), rejected[r]);
				why += one;
			}
			FString detail;
			detail.Format("considered=%u %s", Items::Count(),
				why.IsEmpty() ? "none-rejected" : why.GetChars());
			TraceEvent(bot.slot, "item-scan", detail.GetChars());
		}

		if(haveBest)
		{
			const Items::Annotation &won = Items::At(bestIndex);
			bot.route = bestRoute;
			bot.goal = graph.NodeAt(won.tileX, won.tileY);
			bot.waypoint = 0;
			++bot.routesPlanned;
			++bot.itemGoals;
			// Remember a dispenser so the follower knows to use it on arrival
			// rather than just standing next to a wall.
			bot.healing = won.dispenser;
			bot.healTileX = won.tileX;
			bot.healTileY = won.tileY;
			bot.healUses = 0;

			FString detail;
			detail.Format("item %s%s at=%u,%u utility=%d len=%u",
				Items::CategoryName(won.category),
				won.dispenser ? " dispenser" : "", won.tileX, won.tileY,
				bestUtility, bot.route.Size());
			TraceEvent(bot.slot, "route", detail.GetChars());
			return true;
		}
	}

	int forcedX = 0, forcedY = 0;
	if(ForcedGoal(forcedX, forcedY))
	{
		const BotNav::NodeId target = graph.NodeAt(forcedX, forcedY);
		if(target == BotNav::NO_NODE || target == here)
			return false;

		BotNav::SearchStats stats;
		// Keeping clear of transporters is a preference, not a rule. A bot
		// that has just arrived is standing inside the zone it is trying to
		// avoid, and on a map where the pads sit in a corridor there may be no
		// way out that does not pass one. Refusing to move at all is worse
		// than crossing a pad again, so a failed search is retried without the
		// restriction rather than reported as nowhere to go.
		if(!graph.FindPath(here, target, bot.route, stats, 0, &options) &&
			!graph.FindPath(here, target, bot.route, stats))
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
	//
	// Three passes, not two, while a transporter cooldown is running. The
	// first two look for somewhere reachable without going near a pad; only if
	// the whole map offers nothing does the third drop the restriction.
	//
	// Trying unrestricted *per candidate* instead -- which is what the first
	// version did -- defeats the whole thing: goals are drawn from the entire
	// map, most of them are across a transporter, so the restricted search
	// fails, the fallback succeeds, and the route goes straight back through
	// the pad the bot just came out of. It bounced between two pads every 38
	// tics with the avoidance apparently in place.
	// Own mines ride the same ladder, and outlast the distance restriction on
	// it.
	//
	// They need their own rung. Pass 0 only considers goals six tiles away or
	// more, so a bot whose distant goals are all behind its own mine fails
	// that pass for two unrelated reasons at once -- and with the mine
	// restriction lifted on the very next pass, it never gets to ask whether
	// somewhere *close* is reachable without crossing it. That is how a bot
	// that had mined a choke point and then walked into the dead end past it
	// came back through the mine on the first retry.
	const unsigned int passes = (options.avoidTransporters ? 3 : 2) +
		(options.lethal != NULL ? 1 : 0);
	for(unsigned int pass = 0;pass < passes;++pass)
	{
		const bool restricted = options.avoidTransporters && pass < 2;
		const int wantDistanceSquared = pass == 0 ? 36 : 1;
		for(unsigned int attempt = 0;attempt < 8;++attempt)
		{
		const BotNav::NodeId candidate =
			(BotNav::NodeId)bot.Draw(Stream::GoalTieBreak).Below(graph.NodeCount());
		if(candidate == here)
			continue;

		// A transporter is not a destination. Walking onto one is the whole
		// interaction: the bot arrives somewhere else, the route it was
		// following is void, and to an observer it has bounced.
		//
		// The search already refuses to route *through* a pad while a cooldown
		// runs, with the goal exempt so that a named goal can still be a pad
		// for testing. That exemption is what let a roam goal land on one --
		// a bot stood on MAP56's western pad with the eastern pad as its
		// destination, could not make progress for a hundred tics, and was
		// thrown back the moment its unstuck nudge put it over the edge.
		if(!Destination::Usable(graph, candidate))
			continue;

		const BotNav::Node &there = graph.NodeOf(candidate);
		const int dx = (int)there.x - (int)pawn->tilex;
		const int dy = (int)there.y - (int)pawn->tiley;
		if(dx*dx + dy*dy < wantDistanceSquared)
			continue;

		BotNav::SearchStats stats;
		TArray<BotNav::NodeId> route;
		BotNav::SearchOptions pass_options = options;
		pass_options.avoidTransporters = restricted;
		pass_options.lethal = pass + 1 < passes ? options.lethal : NULL;
		pass_options.refuseCrossings = options.refuseCrossings;
		if(!graph.FindPath(here, candidate, route, stats, 0, &pass_options))
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
				// Coming back somewhere else is not a teleport to be reasoned
				// about; it is a new life. Forget where the body was.
				bot->haveSeenTile = false;
				TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
			}

			// Ask to come back the way a person does: press use. The engine
			// respawns a dead player on bt_use once RespawnEligible has
			// passed, and gives up waiting a hundred tics later -- so a bot
			// that pressed nothing would still return, just always late and
			// never by its own doing. Pulsed rather than held for the same
			// reason a door is.
			//
			// And not instantly. Section 17.2 gives a respawn hesitation from
			// 55 tics down to 6, which is the pause between dying and
			// deciding to get up again; a bot that presses use on the first
			// tic of every death is back before a person has focused on the
			// screen. Measured from entering the state, so it is a hesitation
			// rather than a queue.
			const bool hesitating =
				sequence - bot->behaviorSince < bot->traits.respawnDelay;
			if(!bot->doorUseLastTic && !hesitating)
			{
				out.press[bt_use] = true;
				if(bot->respawnPresses < 0xFFFFFFFFu)
					++bot->respawnPresses;
			}
			bot->doorUseLastTic = out.press[bt_use];

			Record(*bot, sequence, forSlot);
			return true;
		}

		// Take a look, at this bot's own rate.
		//
		// Section 17.2 gives vision refresh in hertz, from 7 for a Recruit to
		// 28 for an Elite, and the only way for that to mean anything is for
		// the brain to stop reading the sensor on the tics in between. What it
		// reads instead is the snapshot below -- so between looks it acts on
		// where somebody was, which is where the difference between a slow
		// pair of eyes and a fast one actually shows.
		//
		// The sensor itself still runs every tic and is still the only thing
		// that touches the world. What changes is how often the brain is
		// allowed to ask it.
		const bool looking = sequence >= bot->nextSense || !bot->view.ever;
		if(looking)
		{
			bot->nextSense = sequence + bot->traits.visionInterval;
			const Perception::Observation *obs = Perception::For(forSlot);
			bot->view.takenAt = sequence;
			bot->view.ever = true;
			for(unsigned int who = 0;who < MAXPLAYERS;++who)
			{
				const Perception::PlayerSighting *sighting =
					obs != NULL ? obs->Seen((Session::PlayerSlot)who) : NULL;
				bot->view.seen[who] = sighting != NULL;
				if(sighting != NULL)
				{
					bot->view.x[who] = sighting->x;
					bot->view.y[who] = sighting->y;
					bot->view.distanceTiles[who] = sighting->distanceTiles;
				}
			}
		}

		// Ears and pain, every tic, whatever the eyes are doing.
		//
		// Neither of these was read at all, and between them they are why a
		// player could follow a bot around an arena unshot: bots see a
		// ninety-degree cone, so a bot walking away from you never looks at
		// you, and being shot in the back told it nothing because nothing
		// asked. Two bots hunting each other had the same problem from both
		// ends -- they only ever met by walking into each other's view.
		//
		// A sound gives a bearing (the centre of a 45-degree sector) and a
		// band, which is what a person gets. Damage from someone already in
		// view names them; damage from behind names nobody, so the answer to
		// it is to look around rather than to spin onto a target the bot has
		// no right to know about.
		//
		// Not gated by the vision refresh: eyes blink, ears do not.
		if(const Perception::Observation *heard = Perception::For(forSlot))
		{
			for(unsigned int d = 0;d < heard->damage.Size();++d)
			{
				const Perception::DamageCue &cue = heard->damage[d];
				if(cue.attackerSlot >= 0)
					continue;		// seen, and handled by the ordinary path
				if(sequence < bot->alertRestUntil)
					continue;
				bot->alertRestUntil = sequence + ALERT_TICS + ALERT_REST;
				bot->alertUntil = sequence + ALERT_TICS;
				bot->alertHasBearing = false;
				++bot->alertsRaised;
				TraceEvent(forSlot, "alert", "hit from nowhere");
			}
			for(unsigned int n = 0;n < heard->sounds.Size();++n)
			{
				const Perception::AudibleEvent &noise = heard->sounds[n];
				if(noise.kind != Perception::SoundKind::Weapon &&
					noise.kind != Perception::SoundKind::Pain &&
					noise.kind != Perception::SoundKind::Death)
					continue;
				// One look per noise, and then a rest.
				//
				// Every sound used to restart the clock, so a bot in earshot
				// of a firefight was permanently a second from finishing its
				// look and never went anywhere. It is not hypothetical: a bot
				// sent thirty-seven waypoints across MAP51 to stand in front
				// of the laser barriers was still short of them when the run
				// ended, having stopped for each shot it heard on the way.
				//
				// A look costs sixty tics and buys a hundred and five of
				// quiet, so a noisy arena can take at most a third of a bot's
				// time and never all of it.
				if(sequence < bot->alertRestUntil)
					continue;
				bot->alertRestUntil = sequence + ALERT_TICS + ALERT_REST;
				bot->alertUntil = sequence + ALERT_TICS;
				bot->alertBearing = noise.bearing;
				bot->alertHasBearing = true;
				++bot->alertsRaised;
				if(bot->alertsRaised % 8 == 1)
				{
					FString d; d.Format("noise bearing=%u",
						(unsigned)(noise.bearing/ANGLE_1));
					TraceEvent(forSlot, "alert", d.GetChars());
				}
			}
		}

		// Read what the last look showed. The brain never looks at the world;
		// it looks at this.
		{
			for(unsigned int who = 0;who < MAXPLAYERS;++who)
			{
				const bool sightingNow = bot->view.seen[who];
				const bool was = bot->visibleNow[who];
				const bool now = sightingNow;

				if(now)
				{
					bot->lastSeenAt[who] = bot->view.takenAt;
					bot->lastSeenTileX[who] =
						(uint16_t)(bot->view.x[who]>>TILESHIFT);
					bot->lastSeenTileY[who] =
						(uint16_t)(bot->view.y[who]>>TILESHIFT);
				}
				if(now && !was)
				{
					++bot->contactsGained;

					// Seen, not yet known. The decision layer is told when
					// the reaction delay expires and not before.
					// The trait is this bot's own reaction time; the jitter
					// is the difference between two of its own reactions.
					// Section 17.2 wants the first stable per bot and seed,
					// and section 17.4 wants the second, because a bot whose
					// every reaction is identical to the tic is a metronome
					// however well the number was chosen. Kept inside the
					// band so the level still means what the table says.
					const Band band =
						BandsFor(SkillOf(bot->profile)).reaction;
					int jittered = (int)bot->traits.reaction +
						(int)bot->rng[(unsigned int)Stream::Timing]
							.Below(REACT_SPREAD*2 + 1) - REACT_SPREAD;
					if(jittered < (int)band.low) jittered = (int)band.low;
					if(jittered > (int)band.high) jittered = (int)band.high;
					const unsigned int delay = (unsigned int)jittered;
					bot->sightedAt[who] = sequence;
					bot->noticeAt[who] = sequence + delay;
					bot->reactionTicsTotal += delay;

					FString detail;
					detail.Format("slot=%u at=%u,%u range=%d in=%u", who,
						bot->lastSeenTileX[who], bot->lastSeenTileY[who],
						bot->view.distanceTiles[who], delay);
					TraceEvent(forSlot, "sighted", detail.GetChars());
				}
				else if(!now && was)
				{
					// Lost sight. The last known position stays -- that is
					// memory, and a player keeps it too -- but it stops being
					// refreshed, which is the part that matters.
					++bot->contactsLost;
					FString detail;
					detail.Format("slot=%u lastseen=%u,%u", who,
						bot->lastSeenTileX[who], bot->lastSeenTileY[who]);
					TraceEvent(forSlot, "lost", detail.GetChars());
					// Losing sight cancels a notice that has not landed. A
					// glimpse too brief to react to is a glimpse the brain
					// never gets to act on, which is the point of the delay.
					// A contact the brain had actually been told about is
					// worth going to look for. One it never noticed is not:
					// the bot does not know it was there.
					if(bot->knownNow[who] && bot->searchingFor == MAXPLAYERS)
					{
						bot->searchingFor = who;
						++bot->searchesStarted;
						FString where;
						where.Format("slot=%u to=%u,%u", who,
							bot->lastSeenTileX[who], bot->lastSeenTileY[who]);
						TraceEvent(forSlot, "searching", where.GetChars());
					}
					bot->noticeAt[who] = 0;
					bot->knownNow[who] = false;
				}
				bot->visibleNow[who] = now;

				// Release. One tic, one transition, so the gate can read the
				// delay straight off the trace.
				if(now && !bot->knownNow[who] && bot->noticeAt[who] != 0 &&
					sequence >= bot->noticeAt[who])
				{
					bot->knownNow[who] = true;
					++bot->contactsNoticed;
					FString detail;
					detail.Format("slot=%u after=%u tics", who,
						sequence - bot->sightedAt[who]);
					TraceEvent(forSlot, "noticed", detail.GetChars());
				}
			}
		}

		// Forgetting. A contact not seen for long enough stops being a fact
		// about where somebody is and becomes nothing at all -- which is the
		// rule that stops a bot holding an exact lock on a hidden player for
		// the rest of the match.
		for(unsigned int who = 0;who < MAXPLAYERS;++who)
		{
			if(bot->lastSeenAt[who] == 0 || bot->visibleNow[who])
				continue;
			if(sequence - bot->lastSeenAt[who] < bot->traits.searchMemory)
				continue;
			++bot->contactsForgotten;
			FString detail;
			detail.Format("slot=%u after=%u tics", who,
				sequence - bot->lastSeenAt[who]);
			TraceEvent(forSlot, "forgot", detail.GetChars());
			bot->lastSeenAt[who] = 0;
			if(bot->searchingFor == who)
				bot->searchingFor = MAXPLAYERS;
		}

		// The world can move a pawn without the bot asking. A transporter is
		// the case that matters here: crossing one is an ordinary step onto an
		// ordinary cell, and the reply is arriving somewhere else entirely,
		// frozen for half a second.
		//
		// Detected by the size of the jump rather than by the route, so it
		// holds for anything that relocates a pawn -- a transporter the bot
		// planned for, one it wandered onto, or whatever a future map special
		// does. A step is one tile; more than that was not walking.
		if(bot->haveSeenTile)
		{
			const int jx = abs((int)pawn->tilex - (int)bot->seenTileX);
			const int jy = abs((int)pawn->tiley - (int)bot->seenTileY);
			if(jx > 1 || jy > 1)
			{
				++bot->teleports;
				FString detail;
				detail.Format("from=%u,%u to=%d,%d", bot->seenTileX,
					bot->seenTileY, pawn->tilex, pawn->tiley);
				TraceEvent(forSlot, "teleported", detail.GetChars());

				// Replan from where the body actually is. Every waypoint left
				// in the route was chosen from somewhere else, and steering at
				// them from here would walk a line no one planned.
				bot->route.Clear();
				bot->waypoint = 0;
				bot->goal = BotNav::NO_NODE;
				bot->doorNode = BotNav::NO_NODE;
				bot->unstuckUntil = 0;
				bot->lastProgressSeq = sequence;
				bot->wasAskedToMove = false;
				bot->portCooldownUntil = sequence + PORT_COOLDOWN;
				bot->portArrivedTileX = (uint16_t)pawn->tilex;
				bot->portArrivedTileY = (uint16_t)pawn->tiley;
				// And get off the pad before doing anything else.
				//
				// A crossing leaves the body standing on the pad, frozen for
				// thirty-five tics. The freeze ends, the follower turns
				// towards its next waypoint -- and the follower will not walk
				// while it is more than forty-five degrees off, so the bot
				// turns on the spot, inside the trigger, and is sent straight
				// back. On MAP60 that happened one tic after the first
				// movement command, twice in three hundred tics.
				//
				// This is what B7's cooldown was for and it is not enough on
				// its own: the cooldown stops the bot *routing* over a pad,
				// and this is not a routing decision, it is standing still in
				// the wrong place. Nothing was wrong with it until B8 gave
				// turning an acceleration and made "turn first" take long
				// enough to matter.
				bot->portClearUntil = sequence + PORT_CLEAR_TICS;
				if(bot->behavior != Behavior::SpawnOrient)
				{
					bot->behavior = Behavior::Roam;
					bot->behaviorSince = sequence;
				}
			}
		}
		bot->seenTileX = (uint16_t)pawn->tilex;
		bot->seenTileY = (uint16_t)pawn->tiley;
		bot->haveSeenTile = true;

		// Frozen: the engine skips ControlMovement entirely while sighttime
		// runs, so a command sent now is a command thrown away. Send none, and
		// do not let the stuck clock count the half second as a failure to
		// move -- it is traversal time, and the plan prices it as such.
		if(pawn->sighttime > 0)
		{
			++bot->frozenTics;
			bot->wasAskedToMove = false;
			bot->lastProgressSeq = sequence;
			Record(*bot, sequence, forSlot);
			return true;
		}

		// Look at whatever that was, before deciding anything else.
		//
		// Stopping to do it is the point: this engine walks in the direction
		// the body faces, so a bot that turned while walking would wander off
		// wherever the noise came from. A person hearing a shot behind them
		// stops and turns, and so does this.
		if(bot->target == MAXPLAYERS && sequence < bot->alertUntil &&
			bot->behavior != Behavior::DeadWaitingToRespawn)
		{
			out.forward = 0;
			out.strafe = 0;
			bot->wasAskedToMove = false;
			bot->lastProgressSeq = sequence;
			if(bot->alertHasBearing)
			{
				const int32_t rotate =
					BotNav::ShortestTurn(pawn->angle, bot->alertBearing);
				const int units =
					(int)((int64_t)rotate/(int64_t)(ANGLE_1/20));
				out.turn = SteerYaw(*bot, -units);
				// Facing it is the end of it; there is nothing to stare at.
				if(BotNav::ShortestTurn(pawn->angle, bot->alertBearing) <
					(int32_t)(ANGLE_1*6) &&
					BotNav::ShortestTurn(pawn->angle, bot->alertBearing) >
					-(int32_t)(ANGLE_1*6))
					bot->alertUntil = sequence;
			}
			else
			{
				// No bearing: sweep, the way somebody shot from nowhere does.
				out.turn = SteerYaw(*bot, bot->traits.maxYaw);
			}
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

		// The visor, before anything else: it costs a button a person also
		// presses, and it changes what the next sense update can see.
		// Drift the steering error, once a tic, whatever the bot is doing.
		// Stepped here rather than inside FaceToward so that its walk does
		// not depend on how many times a tic something asked it to face
		// somewhere.
		Combat::Step(bot->steer, bot->rng[(unsigned int)Stream::Movement],
			sequence, bot->traits.routeWobble);

		MindTheVisor(*bot, pawn, sequence, out);
		MindTheMines(*bot, pawn, sequence, out);

		// Badly hurt is a reason to stop fighting.
		//
		// Decided on this bot's own health and nothing about anybody else's:
		// section 14.4 forbids using an enemy's unseen condition to decide a
		// fight is winnable, and the same rule read the other way forbids
		// using it to decide the fight is lost.
		const int hurt = Items::Need(forSlot, Items::Category::Health);
		if(hurt >= PersonalityFor(bot->profile).retreatNeed)
		{
			if(bot->target != MAXPLAYERS)
			{
				++bot->retreats;
				FString detail;
				detail.Format("hurt=%d dropping slot=%u", hurt, bot->target);
				TraceEvent(forSlot, "retreat", detail.GetChars());
				bot->target = MAXPLAYERS;
				// Drop the route too: it was chosen by a bot that was not in
				// trouble, and the item scan below will now be dominated by a
				// health need that has grown enormous.
				bot->route.Clear();
				bot->goal = BotNav::NO_NODE;
				// And decide where to go *now*. The item scan normally runs
				// at most every seventy tics, which is fine for wondering
				// whether to fetch a shotgun and fatal at sixteen percent
				// health: the first two retreats in a match both died waiting
				// for the next scheduled think.
				bot->nextItemThink = 0;
				bot->behavior = Behavior::RetreatOrRecover;
				bot->behaviorSince = sequence;
			}
		}
		// Somebody to shoot at takes precedence over somewhere to go.
		else
		ChooseTarget(*bot, pawn, sequence);
		if(bot->target != MAXPLAYERS)
		{
			if(bot->behavior != Behavior::EngageEnemy)
			{
				bot->behavior = Behavior::EngageEnemy;
				bot->behaviorSince = sequence;
				TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
			}
			Engage(*bot, pawn, sequence, out);
			Record(*bot, sequence, forSlot);
			return true;
		}
		// Standing next to the dispenser it walked to: face it and press use,
		// exactly as a player does. The engine decides whether anything comes
		// out, including refusing an empty one.
		if(bot->healing && pawn != NULL)
		{
			const int dx = (int)bot->healTileX - pawn->tilex;
			const int dy = (int)bot->healTileY - pawn->tiley;
			if(abs(dx) + abs(dy) <= 1)
			{
				const fixed hx = (fixed)(bot->healTileX<<TILESHIFT) + (1<<(TILESHIFT-1));
				const fixed hy = (fixed)(bot->healTileY<<TILESHIFT) + (1<<(TILESHIFT-1));
				const uint32_t off = FaceToward(*bot, pawn, hx, hy, out);
				out.forward = 0;
				bot->wasAskedToMove = false;
				if(off <= (uint32_t)ANGLE_45/3 && sequence >= bot->nextHealUse)
				{
					out.press[bt_use] = true;
					++bot->healUses;
					bot->nextHealUse = sequence + 21;
					if(bot->healUses > 6 || hurt < RETREAT_NEED/2)
						bot->healing = false;	// fixed, or it is not working
				}
				Record(*bot, sequence, forSlot);
				return true;
			}
		}

		if(bot->behavior == Behavior::EngageEnemy)
		{
			// Lost them. Back to whatever it was doing, which the contact
			// machinery has already turned into a search.
			bot->behavior = Behavior::Roam;
			bot->behaviorSince = sequence;
			TraceEvent(forSlot, "behavior", BehaviorName(bot->behavior));
		}

		if(bot->behavior == Behavior::Unstuck)
			Unstuck(*bot, pawn, sequence, out);
		else if(bot->behavior == Behavior::UseTraversal)
			WorkDoor(*bot, pawn, sequence, out);
		else if(bot->behavior == Behavior::Roam ||
			bot->behavior == Behavior::RetreatOrRecover)
		{
			// Retreating is walking somewhere, so it walks the same way. The
			// difference is in what the goal chooser will pick while the bot
			// is hurt, not in how it gets there.
			//
			// Adding a behaviour without adding it here is a bot that stands
			// perfectly still: the first version of the retreat set the state,
			// cleared the route, and then fell through every branch of this
			// chain doing nothing at all.
			Steer(*bot, pawn, sequence, out);
		}

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
	static uint32_t FaceToward(State &bot, AActor *pawn, fixed tx, fixed ty,
		Command::Intent &out)
	{
		const angle_t aimed = BotNav::BearingTo(pawn->x, pawn->y, tx, ty);
		const angle_t want = (angle_t)(aimed + bot.steer.angle);
		const int32_t rotate = BotNav::ShortestTurn(pawn->angle, want);
		const int units = (int)((int64_t)rotate/(int64_t)(ANGLE_1/20));
		int turn = -units;
		turn = SteerYaw(bot, turn);
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
		out.turn = SteerYaw(bot, bot.unstuckStrafe > 0 ?
			bot.traits.maxYaw/2 : -bot.traits.maxYaw/2);
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

		const uint32_t off = FaceToward(bot, pawn, tx, ty, out);

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

	// How much of something this bot is carrying, or -1 if it has none.
	static int Carrying(Session::PlayerSlot slot, const char *className)
	{
		if(slot >= MAXPLAYERS || players[slot].mo == NULL)
			return -1;
		const ClassDef *cls = ClassDef::FindClass(className);
		if(cls == NULL)
			return -1;
		AInventory *const held = players[slot].mo->FindInventory(cls);
		return held != NULL ? (int)held->amount : -1;
	}

	// Is this bot standing somewhere a mine would be worth leaving?
	//
	// A choke point, defined from the graph rather than from where anybody has
	// been seen walking: a cell with few ways through it is one most routes
	// across the arena have to use. That is map knowledge, which a player who
	// has learned an arena also has -- section 16.7 forbids choosing placement
	// from hidden enemy paths, and this never looks at where anyone has been.
	// Judged on the cell the mine will land in, which is not the cell the bot
	// is standing in: the drop goes 40/64 of a tile along the facing. Asking
	// about the bot's own cell approved a mine that then landed in the open
	// room next door -- MAP60 seed 5 put one at (34,4) with four ways out of
	// it, from a bot standing in the doorway beside it.
	static bool WorthMining(const BotNav::Graph &graph, int tileX, int tileY)
	{
		if(tileX < 0 || tileY < 0)
			return false;
		const BotNav::NodeId here =
			graph.NodeAt((unsigned)tileX, (unsigned)tileY);
		if(here == BotNav::NO_NODE)
			return false;
		// Eight neighbours is open floor; three or fewer is a corridor or a
		// doorway, which is where a mine is worth the ammunition.
		return graph.NodeOf(here).edgeCount <= 3;
	}

	// Leave a mine here, if this is a sensible place and the bot can spare one.
	static void MindTheMines(State &bot, AActor *pawn, uint32_t sequence,
		Command::Intent &out)
	{
		if(sequence < bot.nextMineThink)
			return;
		bot.nextMineThink = sequence + MINE_THINK_INTERVAL;

		const int mines = Carrying(bot.slot, "C7Mines");
		if(mines <= 0 || bot.mineCount >= State::MAX_OWN_MINES)
			return;
		// Not while fighting: dropping one takes a button press that is not a
		// trigger, and the bot has better uses for the moment.
		if(bot.target != MAXPLAYERS)
			return;

		// Not on top of one of its own. The blast reaches two tiles, so two
		// mines inside that of each other is one wasted and a bigger hole to
		// walk into later.
		for(unsigned int i = 0;i < bot.mineCount;++i)
		{
			const int dx = abs((int)bot.mineX[i] - pawn->tilex);
			const int dy = abs((int)bot.mineY[i] - pawn->tiley);
			if(dx <= MINE_BLAST_TILES && dy <= MINE_BLAST_TILES)
				return;
		}

		// Where the mine will actually land, not where the bot is standing.
		//
		// The engine drops it 40/64 of a tile along the facing (a_playerpawn),
		// which is frequently the next cell over. Recording the bot's own tile
		// put the remembered mine up to a tile away from the real one, so both
		// the avoidance below and the don't-stack test above were aimed at the
		// wrong cell.
		const unsigned fineangle = pawn->angle >> ANGLETOFINESHIFT;
		const fixed dropAhead = 40 * (FRACUNIT / 64);
		const fixed mineFX = pawn->x + FixedMul(dropAhead, finecosine[fineangle]);
		const fixed mineFY = pawn->y - FixedMul(dropAhead, finesine[fineangle]);

		// The square the trigger reaches, in cells. A_C7MineThink fires on
		// anything within half a tile of the mine's centre, measured between
		// actor origins -- so the danger is a 1x1 square around a point that
		// is not a cell centre, and it straddles up to four cells.
		const fixed triggerReach = FRACUNIT / 2;
		const int firstX = (mineFX - triggerReach) >> FRACBITS;
		const int lastX = (mineFX + triggerReach) >> FRACBITS;
		const int firstY = (mineFY - triggerReach) >> FRACBITS;
		const int lastY = (mineFY + triggerReach) >> FRACBITS;

		if(!WorthMining(BotNav::Current(), (int)(mineFX >> FRACBITS),
			(int)(mineFY >> FRACBITS)))
			return;

		// Laying one in front of itself is fine, and deliberately not
		// prevented here.
		//
		// bt_reload drops the mine 40/64 of a tile along the facing, so a bot
		// walking forward does lay it onto the cell it is about to cross --
		// but the mine spends 36 tics arming, which is longer than the
		// crossing takes, and the routing above will not bring it back over
		// the live one afterwards. Refusing those drops was tried: it cut
		// mines laid on MAP60 from three to one, to prevent a death that
		// turned out to be the bot's own plasma bolt.
		// The ordinary drop button, pulsed. Nothing here spawns an actor or
		// touches the mine count: the engine does both.
		out.press[bt_reload] = true;
		bot.mineX[bot.mineCount] = (uint16_t)(mineFX >> FRACBITS);
		bot.mineY[bot.mineCount] = (uint16_t)(mineFY >> FRACBITS);
		++bot.mineCount;
		++bot.minesPlaced;

		// And remember not to walk back over it.
		//
		// A mine goes live for its owner the moment the owner steps away, and
		// the trigger is anything within half a tile -- so the cell it sits in
		// is the thing to avoid, and the two-tile blast is what makes doing so
		// worth the detour. Reuses the per-bot blocked list the recovery
		// ladder already prices routes with, at an expiry long enough to
		// outlast a match: unlike a jammed doorway, a mine does not clear.
		// Every cell the trigger square touches, not just the one the mine
		// sits in.
		//
		// A_C7MineThink fires on anything within half a tile of the mine's
		// centre, measured between actor origins -- so the danger is a 1x1
		// square around a point that is not a cell centre, and that square
		// straddles up to four cells. Blocking only the mine's own cell let a
		// bot route through the neighbour and walk into the edge of the
		// square: MAP60 seed 1 killed a bot at (17,3) on a mine it had laid
		// near the (17,3)/(17,4) boundary 143 tics earlier.
		//
		// The owner is not spared, either. The grace in A_C7MineThink only
		// holds while the mine is still arming; once it goes live its trigger
		// loop excludes the mine itself and nothing else.
		for(int ty = firstY;ty <= lastY;++ty)
		{
			for(int tx = firstX;tx <= lastX;++tx)
			{
				const BotNav::NodeId cell = BotNav::Current().NodeAt(tx, ty);
				if(cell != BotNav::NO_NODE)
					bot.mined.Add(cell, sequence + MINE_MEMORY);
			}
		}

		// A route planned before the mine existed does not get to keep its
		// permission.
		//
		// The drop goes 40/64 of a tile along the facing, so a bot laying one
		// mid-route puts it on the cell it is walking towards. Crossing it is
		// survivable -- 36 tics of arming is longer than the crossing takes --
		// and that is exactly what makes it dangerous: the bot walks through
		// unharmed and only afterwards discovers that the mine is now between
		// it and everywhere else. On MAP60 one mined the corridor at (17,3),
		// walked north into the four-cell pocket beyond it, and had no way out
		// that did not cross the live mine; the goal ladder relaxed on its
		// last pass, as it must, and the bot walked back into it and died.
		//
		// Dropping the route sends it back through the planner with the mine
		// already in `mined`, which refuses the pocket while the bot is still
		// on the open side of it.
		for(unsigned int w = bot.waypoint;w < bot.route.Size();++w)
		{
			const BotNav::Node &step = BotNav::Current().NodeOf(bot.route[w]);
			if((int)step.x >= firstX && (int)step.x <= lastX &&
				(int)step.y >= firstY && (int)step.y <= lastY)
			{
				bot.route.Clear();
				bot.waypoint = 0;
				bot.goal = BotNav::NO_NODE;
				++bot.routesAbandoned;
				break;
			}
		}

		FString detail;
		detail.Format("at=%d,%d left=%d cells=%u", (int)(mineFX >> FRACBITS),
			(int)(mineFY >> FRACBITS), mines - 1, bot.mined.count);
		TraceEvent(bot.slot, "mine", detail.GetChars());
	}

	// Turn the visor up when there is something only it can show, and down
	// when there is not.
	//
	// Cycled with bt_zoom exactly as a player cycles it: modes run 1, 2, 3 and
	// wrap, so reaching infrared from normal costs two presses and every tic
	// above mode 1 costs charge. Nothing here sets the mode directly.
	static void MindTheVisor(State &bot, AActor *pawn, uint32_t sequence,
		Command::Intent &out)
	{
		const int mode = Carrying(bot.slot, "C7VisorMode");
		const int charge = Carrying(bot.slot, "C7VisorCharge");
		if(mode < 0 || charge < 0)
			return;

		// Worth it if this bot has learned about a barrier the hard way and
		// still has charge to spare. It cannot see them any other way, and
		// walking into another costs ten points.
		const TArray<Perception::HazardKnowledge> *known =
			Perception::HazardsKnownTo(bot.slot);
		const bool wantsInfrared = known != NULL && known->Size() > 0 &&
			charge > VISOR_CHARGE_FLOOR;

		bot.visorWant = wantsInfrared ? 3 : 1;
		if((unsigned int)mode == bot.visorWant)
			return;
		if(sequence < bot.nextVisorPulse)
			return;

		out.press[bt_zoom] = true;
		++bot.visorPulses;
		bot.nextVisorPulse = sequence + VISOR_PULSE_INTERVAL;
	}

	// Pick somebody to shoot at, and keep picking them.
	//
	// Candidates are contacts the brain has been told about, never sightings
	// the sensor made this tic: acting on an observation before the reaction
	// delay has released it is the same as having no reaction time. Section
	// 16.1 also forbids scoring on anything unseen -- health, ammunition, frag
	// value -- so this scores on distance and on staying with what it has.
	static void ChooseTarget(State &bot, AActor *pawn, uint32_t sequence)
	{
		unsigned int best = MAXPLAYERS;
		int bestScore = 0;

		for(unsigned int who = 0;who < MAXPLAYERS;++who)
		{
			if(who == bot.slot || !bot.knownNow[who])
				continue;
			if(!bot.view.seen[who])
				continue;

			// Nearer is better, and that is nearly all of it. Everything else
			// section 16.1 permits needs a threat model that does not exist
			// until something shoots back.
			int score = 1000 - bot.view.distanceTiles[who]*10;
			if(score < 1)
				score = 1;

			// Staying with the current target is worth something. Two
			// distance scores alternating by a tile is exactly the
			// indecision section 14.3 exists to prevent.
			if(who == bot.target)
				score += 250;

			if(score > bestScore || (score == bestScore && who < best))
			{
				bestScore = score;
				best = who;
			}
		}

		if(best == bot.target)
			return;

		if(best == MAXPLAYERS)
		{
			bot.target = MAXPLAYERS;
			return;
		}

		if(bot.target != MAXPLAYERS)
			++bot.targetSwitches;
		++bot.targetsAcquired;
		bot.target = best;
		bot.targetSince = sequence;
		bot.seenHead = 0;
		for(unsigned int i = 0;i < State::AIM_HISTORY;++i)
			bot.seenWhen[i] = 0;
		bot.aim.Reset();

		FString detail;
		detail.Format("slot=%u", best);
		TraceEvent(bot.slot, "target", detail.GetChars());
	}

	// Aim at where the target was, miss sometimes, and pull the trigger.
	static void Engage(State &bot, AActor *pawn, uint32_t sequence,
		Command::Intent &out)
	{
		// The last look, not the live sensor. Everything below -- the lead,
		// the range keeping, the trigger -- is therefore aiming at where the
		// target was when this bot last opened its eyes.
		const bool haveTarget = bot.target < MAXPLAYERS &&
			bot.view.seen[bot.target];
		const fixed seenAtX = haveTarget ? bot.view.x[bot.target] : 0;
		const fixed seenAtY = haveTarget ? bot.view.y[bot.target] : 0;
		const int seenRange = haveTarget ?
			bot.view.distanceTiles[bot.target] : 0;

		if(haveTarget && bot.view.takenAt != bot.lastAimSample)
		{
			bot.lastAimSample = bot.view.takenAt;
			bot.seenX[bot.seenHead] = seenAtX;
			bot.seenY[bot.seenHead] = seenAtY;
			bot.seenWhen[bot.seenHead] = bot.view.takenAt;
			bot.seenHead = (bot.seenHead + 1) % State::AIM_HISTORY;
		}

		// The oldest sample still inside the tracking window, so the aim is
		// always pointed at where the target *was*. A moving target is then
		// genuinely not where the bot is pointing, which is the only reason a
		// ten-degree auto-aim cone can ever be missed.
		fixed atX = 0, atY = 0;
		bool have = false;
		uint32_t bestAge = 0;
		for(unsigned int i = 0;i < State::AIM_HISTORY;++i)
		{
			if(bot.seenWhen[i] == 0)
				continue;
			const uint32_t age = sequence - bot.seenWhen[i];
			if(age < bot.traits.trackingDelay)
				continue;
			if(!have || age < bestAge)
			{
				have = true;
				bestAge = age;
				atX = bot.seenX[i];
				atY = bot.seenY[i];
			}
		}
		if(!have && haveTarget)
		{
			// Nothing old enough yet: just acquired. Use the newest sample and
			// let the acquisition hesitation below cover it.
			atX = seenAtX;
			atY = seenAtY;
			have = true;
		}
		if(!have)
			return;

		// Lead a projectile.
		//
		// Section 16.3: estimate the lead from the known projectile speed and
		// the target's *perceived* velocity -- the ring below holds observed
		// samples and nothing else, so a target the bot cannot see stops
		// contributing to the estimate rather than being extrapolated from its
		// hidden real position.
		//
		// A plasma bolt takes over half a second to cross eight tiles. Firing
		// at where somebody was is a miss at any range worth using it.
		if(Combat::IsProjectileSlot(bot.holdingSlot) && haveTarget)
		{
			fixed oldX = 0, oldY = 0;
			uint32_t oldWhen = 0;
			for(unsigned int i = 0;i < State::AIM_HISTORY;++i)
			{
				if(bot.seenWhen[i] == 0 || bot.seenWhen[i] >= sequence)
					continue;
				if(oldWhen == 0 || bot.seenWhen[i] < oldWhen)
				{
					oldWhen = bot.seenWhen[i];
					oldX = bot.seenX[i];
					oldY = bot.seenY[i];
				}
			}
			const uint32_t span = oldWhen != 0 ? sequence - oldWhen : 0;
			if(span >= 4)
			{
				const int flight =
					Combat::FlightTics(bot.holdingSlot, seenRange);
				atX += (fixed)(((int64_t)(seenAtX - oldX)*flight)/(int64_t)span);
				atY += (fixed)(((int64_t)(seenAtY - oldY)*flight)/(int64_t)span);
			}
		}

		// How hard this shot is, before any error is drawn.
		//
		// The age is what the aim is actually pointed at, not the trait: a
		// bot whose last look was four tics ago and whose tracking delay is
		// seven is aiming at something eleven tics stale, and both halves are
		// skill traits.
		int crossTiles = 0;
		{
			fixed oldestX = 0, oldestY = 0;
			uint32_t oldest = 0;
			for(unsigned int i = 0;i < State::AIM_HISTORY;++i)
			{
				if(bot.seenWhen[i] == 0 || bot.seenWhen[i] > sequence)
					continue;
				if(oldest == 0 || bot.seenWhen[i] < oldest)
				{
					oldest = bot.seenWhen[i];
					oldestX = bot.seenX[i];
					oldestY = bot.seenY[i];
				}
			}
			const uint32_t span = oldest != 0 && sequence > oldest ?
				sequence - oldest : 0;
			if(span > 0 && haveTarget)
			{
				const int dx = (int)((seenAtX - oldestX)>>TILESHIFT);
				const int dy = (int)((seenAtY - oldestY)>>TILESHIFT);
				const int moved = (dx < 0 ? -dx : dx) + (dy < 0 ? -dy : dy);
				crossTiles = (moved*70)/(int)span;
			}
		}

		const angle_t envelope = Combat::EnvelopeFor(bot.traits.aimEnvelope,
			seenRange, bestAge, crossTiles);
		Combat::Step(bot.aim, bot.rng[(unsigned int)Stream::Aim], sequence,
			envelope);

		const angle_t want =
			(angle_t)(BotNav::BearingTo(pawn->x, pawn->y, atX, atY) + bot.aim.angle);
		const int32_t rotate = BotNav::ShortestTurn(pawn->angle, want);
		int turn = -(int)((int64_t)rotate/(int64_t)(ANGLE_1/20));
		out.turn = SteerYaw(bot, turn);

		// Carry the right gun for the range.
		//
		// Requested by pulsing the slot button, exactly as a player does, and
		// then left alone: the weapon state machine runs the switch and
		// decides when it is finished. Section 16.6 forbids assigning
		// PendingWeapon or ReadyWeapon, and the reason is the same as with the
		// trigger -- a bot that sets the weapon directly switches instantly,
		// which no player can.
		if(haveTarget && sequence >= bot.nextWeaponThink)
		{
			bot.nextWeaponThink = sequence + bot.traits.thinkInterval;
			const int want = Combat::ChooseSlot(bot.slot, seenRange);
			if(want > 0 && want != bot.holdingSlot)
			{
				out.press[bt_slot1 + want - 1] = true;
				bot.holdingSlot = want;
				++bot.weaponSwitches;
				FString detail;
				detail.Format("slot=%d range=%d", want, seenRange);
				TraceEvent(bot.slot, "weapon", detail.GetChars());
			}
		}

		// Move while fighting. Standing still is both a poor opponent and an
		// easy one: a bot that never strafes is a stationary target that only
		// has to be aimed at once.
		//
		// The side is held for a commitment interval rather than chosen each
		// tic, for the same reason the aim error drifts rather than jumping --
		// alternating every tic averages to standing still while looking
		// frantic.
		// Do not fight backwards into your own minefield.
		//
		// Planned routes price a bot's own mines, but combat footwork is not a
		// planned route: strafing and backing off are chosen a step at a time,
		// and the aggressive personality closes to five tiles and stays until
		// badly hurt, so it fights exactly where it has been laying mines. One
		// bot blew itself up the first match after personalities landed.
		//
		// Section 16.7 asks for blast risk to be priced by the game's actual
		// radius, which is two tiles.
		int mineDX = 0, mineDY = 0;
		bool mineClose = false;
		for(unsigned int i = 0;i < bot.mineCount;++i)
		{
			const int dx = (int)bot.mineX[i] - pawn->tilex;
			const int dy = (int)bot.mineY[i] - pawn->tiley;
			if(abs(dx) <= MINE_BLAST_TILES && abs(dy) <= MINE_BLAST_TILES)
			{
				mineClose = true;
				mineDX = dx;
				mineDY = dy;
				break;
			}
		}

		// A doorway is not a place to hold a fight.
		//
		// Two separate reasons, and they point the same way. Section 15
		// lists oscillating at a doorway among the mistakes that read as
		// bugs, and combat footwork in a door frame is exactly that:
		// the strafe has nowhere to go, so the pawn grinds against the jamb
		// and shuffles on the spot. And a bot standing in an open door holds
		// it open, in the one cell where it is framed in the gap with no
		// room to move.
		//
		// So the bot clears the cell instead: no lateral movement, and
		// forward regardless of the range it would rather be holding. It
		// fights from the far side, which is where the doorway is worth
		// something to it.
		const BotNav::NodeId standingOn =
			BotNav::Current().NodeAt(pawn->tilex, pawn->tiley);
		const bool inDoorway = standingOn != BotNav::NO_NODE &&
			BotNav::Current().NodeOf(standingOn).isDoor;

		if(sequence >= bot.strafeUntil)
		{
			bot.strafeUntil = sequence + bot.traits.strafeCommit +
				bot.rng[(unsigned int)Stream::Movement].Below(STRAFE_JITTER);
			bot.strafeSide = bot.rng[(unsigned int)Stream::Movement].Below(2)
				? BASEMOVE : -BASEMOVE;
		}
		out.strafe = bot.strafeSide;

		// With a mine of its own within the blast radius, move away from it
		// rather than around the fight. Crude on purpose: a step in the
		// opposite direction is enough to leave a two-tile radius, and this is
		// footwork rather than a plan.
		if(mineClose)
		{
			// The mine's bearing relative to facing decides which way is out.
			const angle_t toward = BotNav::BearingTo(pawn->x, pawn->y,
				(fixed)((pawn->tilex + mineDX)<<TILESHIFT) + (1<<(TILESHIFT-1)),
				(fixed)((pawn->tiley + mineDY)<<TILESHIFT) + (1<<(TILESHIFT-1)));
			const int32_t rel = BotNav::ShortestTurn(pawn->angle, toward);
			// Positive rel means the mine is to one side; strafe the other way.
			out.strafe = rel > 0 ? -BASEMOVE : BASEMOVE;
			bot.strafeUntil = sequence + bot.traits.strafeCommit;
			bot.strafeSide = out.strafe;
		}

		// And keep a sensible distance: close if far away, back off if almost
		// touching. Range is the observed one, so a target that has moved
		// since is one the bot is wrong about, which is correct.
		if(haveTarget)
		{
			const int prefer = PersonalityFor(bot.profile).preferRange;
			if(seenRange > prefer + 2)
				out.forward = BASEMOVE;
			else if(seenRange < prefer - 2 && !mineClose)
				out.forward = -BASEMOVE;		// never back into one
			else
				out.forward = 0;
		}

		// Clearing the doorway outranks every preference above it.
		{
			const Combat::Footwork step =
				Combat::ClearDoorway(inDoorway, out.forward, out.strafe,
					BASEMOVE);
			out.forward = step.forward;
			out.strafe = step.strafe;
			if(inDoorway)
				++bot.doorwayFightsLeft;
		}
		bot.wasAskedToMove = out.forward != 0 || out.strafe != 0;

		// The trigger. Requested through the ordinary button; the weapon state
		// machine decides whether a shot actually happens, and this never
		// touches ammunition, cooldown or psprite state.
		if(sequence < bot.nextTrigger)
			return;
		// A moment to bring the gun round, and only a moment.
		//
		// This was a flat twenty-one tics on top of the skill reaction, which
		// double-counted the same human factor: a Marine already waits 17 to
		// 32 tics before the sighting even reaches the decision layer, so the
		// first shot came 38 to 53 tics -- up to three quarters of a second --
		// after the bot could see you. A person in a firefight is shooting
		// well before that, and a playtest called the default skill limp.
		//
		// A third of the bot's own reaction keeps the ladder (an Elite brings
		// it round quicker than a Recruit) without adding a second full
		// reaction time to it.
		if(sequence - bot.targetSince < bot.traits.reaction/3)
			return;			// still bringing it to bear

		const uint32_t off = (uint32_t)rotate < 0x80000000u
			? (uint32_t)rotate : (uint32_t)(0u - (uint32_t)rotate);
		// Fires a little outside the cone as well as inside it. Section 16.5
		// asks for exactly this: a trigger pulled while the aim is still
		// swinging through is how a bot misses without being blind.
		if(off > (uint32_t)(AUTO_AIM_CONE + AUTO_AIM_CONE/2))
			return;

		out.press[bt_attack] = true;
		++bot.shotsFired;
		bot.nextTrigger = sequence + TRIGGER_INTERVAL +
			bot.rng[(unsigned int)Stream::Timing].Below(TRIGGER_JITTER);

		// Was that shot actually on target?
		//
		// Counted for hitscan only. The ten-degree figure is FindTarget's
		// auto-aim cone, which is a hitscan mechanism; a plasma bolt is a real
		// projectile that has to physically arrive. And a correctly led shot
		// points *ahead* of where the target is, so measuring it against the
		// target's current position scores good leading as a miss -- the
		// metric would punish the very behaviour section 16.3 asks for.
		// Simply not counted: Produce records the tic on the way out, and
		// doing it here as well would count the command twice and change the
		// brain digest.
		if(Combat::IsProjectileSlot(bot.holdingSlot))
			return;
		++bot.hitscanShots;

		//
		// Not the same question as "had the bot finished turning", which is
		// what `off` answers -- that measures convergence on the aim point,
		// and the aim point already has the error baked into it, so a bot that
		// settles neatly onto a badly wrong bearing scores perfectly. The
		// number that decides a hit is the angle between where the pawn is
		// facing and where the target really is.
		if(haveTarget)
		{
			const angle_t truth =
				BotNav::BearingTo(pawn->x, pawn->y, seenAtX, seenAtY);
			const int32_t miss = BotNav::ShortestTurn(pawn->angle, truth);
			const uint32_t magnitude = (uint32_t)miss < 0x80000000u
				? (uint32_t)miss : (uint32_t)(0u - (uint32_t)miss);
			if(magnitude <= (uint32_t)AUTO_AIM_CONE)
				++bot.ticsOnTarget;
		}
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
			// Got somewhere: whatever the trouble was, it is behind us.
			bot.stuckStage = 0;
		}
		else if(!tryingToMove)
		{
			bot.lastProgressSeq = sequence;
		}
		else if(sequence - bot.lastProgressSeq > STUCK_TICS)
		{
			// Section 12.11's ladder. Which rung depends on how many times
			// this has already happened without progress in between: a bot
			// that clips a corner should lose a moment, and one genuinely
			// walled in should end up somewhere else entirely.
			//
			// The stage resets on progress, so "three failures" means three
			// failures at the same obstruction, not three in the match.
			if(sequence > bot.stageResetAt)
				bot.stuckStage = 0;
			++bot.stuckStage;
			bot.stageResetAt = sequence + STAGE_MEMORY;

			const BotNav::NodeId blockedAt = bot.route[MIN(bot.waypoint,
				(unsigned int)bot.route.Size() - 1)];
			const BotNav::Node &target = graph.NodeOf(blockedAt);

			FString detail;
			detail.Format("stage=%u at=%d,%d toward=%u,%u after=%u tics",
				bot.stuckStage, pawn->tilex, pawn->tiley, target.x, target.y,
				sequence - bot.lastProgressSeq);
			TraceEvent(bot.slot, "stuck", detail.GetChars());

			bot.lastProgressSeq = sequence;

			// Rung 1: a nudge. Keep the goal and the route, strafe out of
			// whatever is being leaned on, and try the same waypoint again.
			// Most obstructions are a corner clipped at a shallow angle and
			// this is the whole of the fix.
			if(bot.stuckStage == 1)
			{
				bot.behavior = Behavior::Unstuck;
				bot.behaviorSince = sequence;
				bot.unstuckUntil = sequence + NUDGE_TICS;
				bot.unstuckStrafe =
					bot.rng[(unsigned int)Stream::Movement].Below(2)
						? BASEMOVE : -BASEMOVE;
				++bot.unstuckEntered;
				TraceEvent(bot.slot, "behavior", BehaviorName(bot.behavior));
				return;
			}

			// The graph offered a step the pawn could not walk, twice. This is
			// the one number the traversal gate cannot produce, because it can
			// only check that the pawn never went somewhere the query forbade
			// -- never that everything the query allowed was walkable.
			++bot.stepsRefused;

			// Rungs 4 and 5: remember that this cell did not work, and plan
			// around it. Per bot, and with an expiry, because whatever was in
			// the way was probably another player and will move.
			bot.blocked.Add(blockedAt, sequence + BLOCK_MEMORY);
			++bot.cellsBlocked;

			bot.route.Clear();
			// Rung 6: from the third failure, give the goal away too. Keeping
			// it means planning another route to the same unreachable place.
			if(bot.stuckStage >= 3)
			{
				++bot.routesAbandoned;
				bot.goal = BotNav::NO_NODE;
				bot.nextGoalSearch = sequence + GOAL_COOLDOWN;
			}

			// Rung 2: back up and commit to a side. A route is a function of
			// where the bot is standing, so replanning from the corner it is
			// wedged in produces a route that starts by walking into the same
			// wall.
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
		const uint32_t off = FaceToward(bot, pawn, tx, ty, out);

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
		//
		// Walking the corner instead was tried when B8's turn acceleration
		// made stopping more expensive, and it is much worse: a bot that
		// moves while ninety degrees off course goes somewhere else and has
		// to come back. Eighteen waypoints of a seventy-nine waypoint route
		// in the budget that got sixty-one out of it standing still. The
		// threshold is not a tuning knob, it is what stops the follower
		// chasing its own error.
		// Walking off a transporter pad outranks turning to face the route.
		// See the crossing handler: standing still on a pad is how a bot gets
		// sent back through it.
		if(sequence < bot.portClearUntil)
			out.forward = BASEMOVE;
		else if(off > ANGLE_45)
			out.forward = 0;			// point at it first
		else if(off > ANGLE_45/3)
			out.forward = BASEMOVE;
		else
			out.forward = RUNMOVE;

		// Read on the next tic by the stuck clock, which only runs while the
		// bot was actually asking to go somewhere.
		bot.wasAskedToMove = out.forward != 0;
	}

	// One place a turn can come from, so that a yaw limit is a property of the
	// bot rather than of whichever code path happened to remember to clamp.
	//
	// Two limits, not one. The ceiling is how fast it can turn; the
	// acceleration is how fast it can *start* turning, and it is the one that
	// stops a bot snapping onto a target. Without it a Recruit and an Elite
	// both reach full speed on the first tic and differ only in the speed, so
	// the thing a person actually notices -- the head whipping round the
	// instant somebody appears -- survives every skill level. Section 17.5
	// forbids the instant 180, and a rate ceiling alone does not prevent it.
	//
	// Carried scaled, because every shipped acceleration is a fraction of a
	// command unit per tic and rounding it to an integer would make three of
	// the four levels identical.
	static int SteerYaw(State &bot, int wanted)
	{
		const int ceiling = bot.traits.maxYaw;
		if(wanted > ceiling) wanted = ceiling;
		if(wanted < -ceiling) wanted = -ceiling;

		const int have = bot.yawRate;
		const int step = bot.traits.yawAccel;
		int rate = wanted*ACCEL_SCALE;
		if(rate > have + step) rate = have + step;
		if(rate < have - step) rate = have - step;
		bot.yawRate = rate;

		int turn = rate/ACCEL_SCALE;
		if(turn > ceiling) turn = ceiling;
		if(turn < -ceiling) turn = -ceiling;
		return turn;
	}

	// What is left here after B8.
	//
	// Eight constants moved out of this block and into g_skill.h, where they
	// became bands rather than numbers: the turn ceiling, tracking delay, aim
	// envelope, weapon reconsideration, strafe commitment, preferred range,
	// reaction time and search memory. They are gone rather than left unused,
	// because a constant that no longer does anything is a trap -- the obvious
	// way to change a bot's reaction time would have been to edit REACT_BASE,
	// and it would have had no effect whatsoever.
	//
	// What remains is either not a skill (door timings, mine geometry, the
	// recovery ladder) or not yet one.
	enum {
		// Long enough for a door to open and for a body blocking one to move
		// off it, short enough that a locked door is not a career.
		DOOR_PATIENCE = 210,
		// Long enough that a door which is opening is left alone to open --
		// pressing again would close it -- and short enough to recover from a
		// press that did nothing at all.
		DOOR_REPULSE = 105,
		UNSTUCK_TICS = 24,
		// Three seconds without planning another transporter. Long enough to
		// walk clear of the arrival pad and its counterpart; short enough that
		// a bot which genuinely wants to cross again is only briefly stopped
		// from doing so.
		PORT_COOLDOWN = 210,
		// Reaction time, in tics, at 70 to the second. A person takes about a
		// fifth of a second to react to something appearing, so 14 tics, with
		// a seeded spread on top so that two bots seeing the same thing do not
		// move on the same tic.
		// How often the weapon choice is revisited, and how long a strafe
		// direction is held.
		STRAFE_JITTER = 28,
		// Charge to keep in reserve, and how often the zoom may be pressed.
		// The cycle wraps 1-2-3, so a mistimed second press lands on the wrong
		// mode and the next one has to go all the way round again.
		// How often a mine is considered, and how far its blast reaches. The
		// radius is 128 units in the DECORATE, which is two tiles.
		MINE_THINK_INTERVAL = 105,
		MINE_BLAST_TILES = 2,
		// Long enough to outlast a match. A mine does not go away.
		MINE_MEMORY = 100000,
		VISOR_CHARGE_FLOOR = 15,
		VISOR_PULSE_INTERVAL = 14,
		TRIGGER_INTERVAL = 12,
		TRIGGER_JITTER = 10,
		REACT_SPREAD = 7,
		// A short shove for a first failure, the full back-up for a second.
		NUDGE_TICS = 10,
		// How long a failure stays on the ladder. Longer than a recovery takes
		// so that a second failure at the same place escalates, short enough
		// that two unrelated bumps a match apart do not.
		STAGE_MEMORY = 210,
		// How long a cell that could not be got through stays expensive.
		// Whatever was in the way was most likely another player.
		BLOCK_MEMORY = 350,
		// And how long to leave a goal alone after giving it away.
		GOAL_COOLDOWN = 70
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
	// The override is a developer tool and says so when it is used: a match
	// whose bots came from somewhere other than the shared seed is not one to
	// compare against a recording, and finding that out from a silent flag
	// would cost an afternoon.
	uint64_t matchSeed = (uint64_t)rngseed;
	if(g_haveSeedOverride)
	{
		matchSeed = g_seedOverride;
		Printf("Bot seed overridden to %llu; this match's bots will not match "
			"a recording made without it.\n", (unsigned long long)matchSeed);
	}

	for(int i = 0;i < wanted;++i)
	{
		const unsigned int slot = Session::AddAuthoritySlot((uint32_t)0,
			matchSeed ^ (uint64_t)i);
		if(slot >= Session::MAX_PLAYER_SLOTS)
		{
			// All four numbers, as section 18.7 asks: a message naming only
			// the bots leaves the reader to work out how many humans were
			// already in the roster and what the limit is.
			Printf("%u player%s and %d bots is %d slots; this game supports "
				"%u. %d bot%s joined.\n",
				Session::ActiveSlotCount() - (unsigned)i,
				Session::ActiveSlotCount() - (unsigned)i == 1 ? "" : "s",
				wanted, (int)(Session::ActiveSlotCount() - (unsigned)i) + wanted,
				(unsigned)Session::MAX_PLAYER_SLOTS,
				i, i == 1 ? "" : "s");
			break;
		}

		// A different personality per slot, so a match is a mix rather than
		// three copies of one opponent. Personalities change decisions only --
		// section 17.3 -- and the class assigned below is the same for all of
		// them, which is what keeps that true.
		// Skill from the match setting, personality from the slot, so a
		// match is a mix of temperaments at one standard rather than a mix
		// of standards.
		Configure((Session::PlayerSlot)slot,
			MakeProfile(RequestedSkill(), (unsigned int)slot), matchSeed);
		Command::SetProducer((Session::PlayerSlot)slot, MakeProducer(slot));
		// The same character as the player it stands in for, so it is an
		// ordinary opponent rather than something with different rules.
		playerClassNames[slot] = playerClassNames[0];
		Printf("Bot in slot %u.\n", slot);
	}

	// Once, after the roster exists rather than while it is being built.
	ReportRoster();
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
		total.doorwayFightsLeft += g_state[i].doorwayFightsLeft;
		total.unstuckEntered += g_state[i].unstuckEntered;
		total.respawnPresses += g_state[i].respawnPresses;
		total.respawnsCompleted += g_state[i].respawnsCompleted;
		total.teleports += g_state[i].teleports;
		total.frozenTics += g_state[i].frozenTics;
		total.cellsBlocked += g_state[i].cellsBlocked;
		total.contactsGained += g_state[i].contactsGained;
		total.contactsLost += g_state[i].contactsLost;
		total.contactsNoticed += g_state[i].contactsNoticed;
		total.searchesStarted += g_state[i].searchesStarted;
		total.contactsForgotten += g_state[i].contactsForgotten;
		total.itemGoals += g_state[i].itemGoals;
		total.targetsAcquired += g_state[i].targetsAcquired;
		total.shotsFired += g_state[i].shotsFired;
		total.hitscanShots += g_state[i].hitscanShots;
		total.weaponSwitches += g_state[i].weaponSwitches;
		total.visorPulses += g_state[i].visorPulses;
		total.retreats += g_state[i].retreats;
		total.healUses += g_state[i].healUses;
		total.minesPlaced += g_state[i].minesPlaced;
		total.ticsOnTarget += g_state[i].ticsOnTarget;
		total.reactionTicsTotal += g_state[i].reactionTicsTotal;
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

SkillLevel RequestedSkill() { return g_skill; }

bool SetRequestedSkill(const char *name, bool allowDeveloper)
{
	if(name == NULL)
		return false;
	for(unsigned int i = 0;i < (unsigned int)SkillLevel::NUM;++i)
	{
		const SkillLevel level = (SkillLevel)i;
		if(stricmp(name, SkillName(level)) != 0)
			continue;
		// Section 17.5: Perfect is refused rather than hidden. A name that
		// silently fell back to Elite would put a developer profile into a
		// match nobody could tell was running one.
		if(!IsShippable(level) && !allowDeveloper)
			return false;
		g_skill = level;
		return true;
	}
	return false;
}

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
	}

	// Section 12.11's rungs 4 and 5 keep a short per-bot memory of places that
	// did not work. It is defensive code that a healthy match never reaches --
	// bots do not collide with one another in this game, so nothing routinely
	// blocks one -- which is exactly why it is checked here rather than left
	// to be exercised by luck.
	Printf("\nBlocked-cell memory\n");
	{
		BotNav::BlockedCells b;
		Check(!b.Blocked(5, 0), "nothing is blocked to begin with");

		b.Add(5, 100);
		Check(b.Blocked(5, 50), "a cell that failed is avoided");
		Check(!b.Blocked(5, 100), "until its expiry passes");
		Check(!b.Blocked(6, 50), "and only that cell");

		b.Add(5, 200);
		Check(b.Blocked(5, 150), "re-failing the same cell extends it");
		Check(b.count == 1, "without recording it twice");

		// Fill it, then one more: the entry expiring soonest is the one to
		// lose, because it is the one that was about to stop mattering.
		BotNav::BlockedCells full;
		for(unsigned int i = 0;i < BotNav::MAX_BLOCKED;++i)
			full.Add((BotNav::NodeId)(100 + i), 500 + i*10);
		Check(full.count == BotNav::MAX_BLOCKED, "the list fills to its bound");
		full.Add(999, 900);
		Check(full.count == BotNav::MAX_BLOCKED, "and stays there");
		Check(full.Blocked(999, 600), "the new cell is remembered");
		Check(!full.Blocked(100, 400), "the soonest to expire was dropped");
		Check(full.Blocked(107, 560), "and the others were kept");
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

namespace Bot {

// --- administration ----------------------------------------------------------
//
// Section 18.5 lists these as console commands -- bot_list, bot_debug,
// bot_fill, bot_remove. This engine has no console: every CCMD in the tree is
// inside an `#if 0`, because ECWolf inherited ZDoom's macro and not ZDoom's
// command layer. Inventing one for four diagnostics would be a large piece of
// interface work with its own input handling, history and parser, and none of
// it is what the milestone is for.
//
// So the two that report become command-line diagnostics, which is where a
// headless run and a bug report can both reach them, and the two that change
// the roster become the lobby's Bots row -- which is the better home anyway,
// since section 18.5 requires roster changes to happen at match boundaries and
// the lobby *is* the match boundary.

namespace {
int  g_listRoster = 0;
int  g_debugSlot  = -2;		// -2 nobody, -1 all, >=0 one slot
}

void SetSeedOverride(uint64_t seed)
{
	g_seedOverride = seed;
	g_haveSeedOverride = true;
}

void SetListRoster(bool on) { g_listRoster = on ? 1 : 0; }
void SetDebugSlot(int slot) { g_debugSlot = slot; }

void ReportRoster()
{
	if(!g_listRoster || Session::ActiveSlotCount() == 0)
		return;
	Printf("Roster: %u slot%s\n", Session::ActiveSlotCount(),
		Session::ActiveSlotCount() == 1 ? "" : "s");
	for(unsigned int i = 0;i < Session::ActiveSlotCount();++i)
	{
		const Session::PlayerSlot slot = (Session::PlayerSlot)i;
		const bool isBot = Session::SlotIsBot(slot);
		const State *bot = isBot ? StateFor(slot) : NULL;
		if(isBot && bot != NULL)
			Printf("  %u  %-10s bot    %-8s profile %u\n", i + 1,
				Session::NameOf(slot), SkillName(SkillOf(bot->profile)),
				bot->profile);
		else
			Printf("  %u  %-10s %s\n", i + 1, Session::NameOf(slot),
				isBot ? "bot    (unconfigured)" : "human");
	}
}

void ReportBotState()
{
	if(g_debugSlot == -2)
		return;
	for(unsigned int i = 0;i < MAXPLAYERS;++i)
	{
		if(!Active((Session::PlayerSlot)i))
			continue;
		if(g_debugSlot >= 0 && (int)i != g_debugSlot)
			continue;
		const State *bot = StateFor((Session::PlayerSlot)i);
		if(bot == NULL)
			continue;
		Printf("%s (slot %u): %s, %s\n", Session::NameOf(i), i + 1,
			SkillName(SkillOf(bot->profile)), BehaviorName(bot->behavior));
		Printf("  react %u  vision %u  yaw %d  aim %u deg  track %u  memory %u\n",
			bot->traits.reaction, bot->traits.visionInterval,
			bot->traits.maxYaw, (unsigned)(bot->traits.aimEnvelope/ANGLE_1),
			bot->traits.trackingDelay, bot->traits.searchMemory);
		Printf("  routes %u planned, %u reached, %u abandoned; %u doors, %u stuck\n",
			bot->routesPlanned, bot->routesCompleted, bot->routesAbandoned,
			bot->doorsOpened, bot->unstuckEntered);
		Printf("  %u shots, %u on target, %u targets, %u retreats\n",
			bot->shotsFired, bot->ticsOnTarget, bot->targetsAcquired,
			bot->retreats);
	}
}

}
