/*
** g_botnav.h
**
** A graph of where a body can stand, and the shortest way between two of them.
**
** Corridor 7's arenas are 64 by 64 tiles with per-cell solidity, doors and
** transporters already decoded by the map translator, so the useful structure
** is a compact tile graph rather than anything resembling a navigation mesh.
** Every cell a player can stand in is a node; every way of getting from one to
** the next is a typed edge.
**
** Three decisions are fixed here rather than discovered later.
**
** Search starts as Dijkstra, not A*. A transporter links two distant cells at
** small cost, which makes straight-line distance an *over*estimate of the true
** cost -- and an overestimating heuristic is not admissible, so A* would
** quietly return paths that are not shortest. h = 0 until a transporter-aware
** lower bound has been proved. See the plan, section 12.9.
**
** Ties break on node and edge id, never on pointer value or container order.
** Two machines building the same graph have to choose the same route, and
** anything derived from an address does not survive being run twice, let alone
** on two computers.
**
** Edge types are declared in full now even though only walking is implemented.
** Doors, switches and transporters then arrive as behaviour on an existing
** shape rather than as a reason to restructure the graph.
*/

#ifndef __G_BOTNAV_H__
#define __G_BOTNAV_H__

#include <stdint.h>

#include "wl_def.h"
#include "tarray.h"
#include "g_traversal.h"

namespace BotNav {

typedef uint16_t NodeId;
typedef uint32_t EdgeId;

enum { NO_NODE = 0xFFFF };

enum class EdgeType : uint8_t
{
	WalkCardinal,
	WalkDiagonal,
	// Entering or leaving a cell whose door must be opened first.
	UseDoor,
	// Not built yet. Declared so the shape does not change when they are.
	UseSwitchOrField,
	// Crossing a transporter. The only directed edge type: a transporter
	// sends a body one way, and whether anything sends it back depends on
	// whether the far end has a transporter of its own.
	Transporter
};

// Integer, and scaled so a diagonal is expressible: 100 for a cardinal step,
// 141 for the diagonal, which is sqrt(2) to three figures. Floating point in a
// cost that two machines compare is a way of disagreeing very slightly.
enum { COST_CARDINAL = 100, COST_DIAGONAL = 141 };

// A door is a step plus the time spent opening it and waiting for it. Priced
// at roughly six ordinary steps so a route prefers an open way round when one
// exists and still uses the door when it does not -- which is the behaviour a
// human shows, and the reason this is a cost rather than a prohibition.
enum { COST_DOOR = 600 };

// A transporter costs the 35-tic freeze it imposes and nothing else: the
// distance it covers is free, which is the entire point of one. Priced against
// a run of about nine tics to the tile, so 35 tics is a touch under four
// tiles' worth -- enough that a bot walks to somewhere three tiles away rather
// than teleporting, and takes the transporter for anything further.
enum { COST_TRANSPORTER = 390 };

// Entering a cell that touches an energized wall. Two tiles' worth of walking,
// so a route takes a detour of up to two tiles to keep off one and squeezes
// past when the detour is longer than that.
//
// A flat number, and deliberately the simplest form of section 12.7's cost:
// expected damage times urgency times contact probability, with urgency and
// probability held at one. Health, armour and invulnerability are what turn it
// into the real thing, and none of them are modelled until the bot has a
// reason to care about its own condition.
enum { COST_HAZARD = 200 };

struct Node
{
	uint16_t x = 0;
	uint16_t y = 0;
	// Contiguous run in the edge array. Edges are sorted by (from, id), so a
	// node's edges are always visited in the same order.
	uint32_t firstEdge = 0;
	uint16_t edgeCount = 0;
	// A cell whose door has to be opened before it can be walked through.
	bool     isDoor = false;
	// A cell that moves whoever steps into it. Walking in is the whole of the
	// interaction; there is no walking on through.
	bool     isTransporter = false;
	// This cell, or one touching it. The engine fires a crossing trigger when
	// the body comes within a single movement step of the boundary rather than
	// on entering the tile, so standing next to a transporter is already close
	// enough to be taken by it: avoiding the pad alone does not avoid the pad.
	bool     nearTransporter = false;
	// Touching one of Corridor 7's energized walls. Not a reason to refuse the
	// cell -- a corridor lined with them is still a corridor, and sometimes
	// the only way through -- but a reason to prefer going round.
	bool     nearHazard = false;
};

struct Edge
{
	NodeId   from = 0;
	NodeId   to = 0;
	uint16_t cost = 0;
	EdgeType type = EdgeType::WalkCardinal;
	// The key the door demands, or 0. Carried on the edge rather than checked
	// during the build, because the graph is built once and what a bot is
	// carrying changes all match. A follower that reaches a locked edge
	// without the key replans; it does not get an exception.
	int      lock = 0;
};

// What a search cost, whether or not it found anything. Counted because "the
// bot did not go anywhere" and "the bot could not find a way" are different
// failures, and a number is how they are told apart.
struct SearchStats
{
	unsigned int expansions = 0;
	unsigned int reopenings = 0;
	bool         exhaustedBudget = false;
	bool         found = false;
};

// What a particular search is allowed to do, beyond what the graph says.
//
// Per-search rather than baked into edge costs, because these are properties of
// the bot doing the searching and the moment it is searching in, not of the
// map. Two bots planning on one graph in the same tic can want different
// answers.
// Cells this particular bot has recently failed to get through, and until
// when. Section 12.9's "recent edge failure penalty", and the memory rungs 4
// and 5 of the recovery ladder need: a bot that could not get past something
// should stop planning routes through it for a while, without that becoming a
// fact about the map that every other bot inherits.
//
// Small and fixed: a bot that is failing in eight different places has a
// problem no bookkeeping will fix, and the oldest entry is the least
// interesting one to keep.
enum { MAX_BLOCKED = 8 };
struct BlockedCells
{
	NodeId   node[MAX_BLOCKED];
	uint32_t until[MAX_BLOCKED];
	unsigned int count = 0;

	BlockedCells()
	{
		for(unsigned int i = 0;i < MAX_BLOCKED;++i)
		{
			node[i] = NO_NODE;
			until[i] = 0;
		}
	}

	void Add(NodeId id, uint32_t expires)
	{
		for(unsigned int i = 0;i < count;++i)
		{
			if(node[i] == id)
			{
				until[i] = expires;
				return;
			}
		}
		if(count < MAX_BLOCKED)
		{
			node[count] = id;
			until[count] = expires;
			++count;
			return;
		}
		// Full: replace whichever entry expires soonest.
		unsigned int oldest = 0;
		for(unsigned int i = 1;i < count;++i)
		{
			if(until[i] < until[oldest])
				oldest = i;
		}
		node[oldest] = id;
		until[oldest] = expires;
	}

	bool Blocked(NodeId id, uint32_t now) const
	{
		for(unsigned int i = 0;i < count;++i)
		{
			if(node[i] == id && now < until[i])
				return true;
		}
		return false;
	}
};

// What entering a cell this bot recently failed at costs. Steep enough that
// any way round is preferred, finite so that a bot walled into a corner by its
// own history can still plan out of it.
enum { COST_BLOCKED = 1500 };

struct SearchOptions
{
	// Keep clear of transporters entirely -- the pads and the ring of cells
	// around them. Set for a short while after using one.
	//
	// The ring is the part that matters. A relative teleport lands a body a
	// tile short of the nominal destination, which on MAP56 is directly beside
	// the pad that sends it back; the trigger then fires as soon as the body
	// moves within one step of that pad's edge. Avoiding only the pad cell
	// leaves the bot standing next to the return trip, and it bounced between
	// two pads every 38 tics -- freeze, three steps, back again.
	//
	// Start and goal are exempt, because the bot may well be standing on a pad
	// when it plans, and a pad is a legitimate place to be going.
	bool avoidTransporters = false;

	// Cells to price up, and the sequence to judge their expiry against.
	const BlockedCells *blocked = NULL;
	uint32_t now = 0;
};

class Graph
{
public:
	// Build from the live map for a body of this size. Returns false when
	// there is no map, or nowhere in it to stand.
	bool Build(const Traversal::Body &body);
	void Clear();

	bool Built() const { return built; }
	unsigned int NodeCount() const { return nodes.Size(); }
	unsigned int EdgeCount() const { return edges.Size(); }

	// NO_NODE when the tile is not somewhere this body can stand.
	NodeId NodeAt(unsigned int tileX, unsigned int tileY) const;
	const Node &NodeOf(NodeId id) const { return nodes[id]; }
	const Edge &EdgeOf(EdgeId id) const { return edges[id]; }

	// Shortest path from one node to another, as a run of nodes starting with
	// `from` and ending with `to`. Empty when there is none.
	//
	// maxExpansions bounds the work: a search that runs out reports it rather
	// than returning a path it did not finish finding. Zero means the graph's
	// own size, which is the most a complete search can ever need.
	bool FindPath(NodeId from, NodeId to, TArray<NodeId> &path,
		SearchStats &stats, unsigned int maxExpansions = 0,
		const SearchOptions *options = NULL) const;

	// Can a body walk straight between two nodes, ignoring the grid? The
	// question a shortcut asks, and the one a follower asks before cutting a
	// corner.
	bool StraightLineFits(const Traversal::Body &body, NodeId a, NodeId b) const;

	// Drop the nodes a straight run can skip, keeping only turns -- but only
	// where the body genuinely fits along the whole shortcut, asked of the
	// same traversal query the pawn obeys.
	void Smooth(const Traversal::Body &body, TArray<NodeId> &path) const;

	// Stable across runs and machines: node and edge contents in id order. Two
	// graphs that hash alike are the same graph.
	uint32_t Digest() const;

	// How many pieces the graph is in, treating every edge as two-way, and how
	// big the largest is.
	//
	// Undirected deliberately, including over transporters. The question this
	// answers is "how much of this arena hangs together", and a one-way link
	// still joins two areas into one arena. Counting reachability instead
	// would make the answer depend on which node the walk happened to start
	// from, which is not a property of the map. This is the number that says whether a bot dropped into
	// an arena can get anywhere in it: a map in five regions is five separate
	// arenas as far as walking is concerned.
	//
	// Worth having as a measurement rather than an assertion, because it is
	// how a missing edge type announces itself -- MAP60 in five regions is
	// what a graph with no doors in it looks like.
	unsigned int Regions(unsigned int *largest = NULL) const;

private:
	TArray<Node>   nodes;
	TArray<Edge>   edges;
	TArray<NodeId> lookup;		// tile index -> node id, NO_NODE for none
	unsigned int   width = 0;
	unsigned int   height = 0;
	bool           built = false;
};

// The bearing from one point to another, in the engine's angle units, using
// integer arithmetic only.
//
// The obvious way to write this is atan2, and the plan's determinism ABI
// (section 26.5) is specifically about not doing that: converting a libm
// result to an integer angle rounds differently on different targets, and
// anything downstream of it stops being reproducible. Bot bearings do not
// enter the replicated simulation -- only the clamped turn command does, and
// only the authority computes it -- so this would not split lockstep. It would
// make one machine's brain digest differ from another's for no reason worth
// having, in the one part of the system whose whole job is being explainable.
//
// CORDIC, sixteen iterations, table hardcoded rather than generated by the
// trigonometry it is replacing. Accurate to well under a tenth of a degree,
// which is a hundred times finer than any turn a bot is allowed to make in a
// tic.
angle_t BearingTo(fixed fromX, fixed fromY, fixed toX, fixed toY);

// The shortest way round from one angle to another: positive to turn
// clockwise, which is what the engine does for a positive controlx.
int32_t ShortestTurn(angle_t from, angle_t to);

// The graph for the map currently loaded, built on first use.
Graph &Current();
void Invalidate();

}

#endif
