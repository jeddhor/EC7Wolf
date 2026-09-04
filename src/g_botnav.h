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
	// Not built yet. Declared so the shape does not change when they are.
	UseDoor,
	UseSwitchOrField,
	Transporter
};

// Integer, and scaled so a diagonal is expressible: 100 for a cardinal step,
// 141 for the diagonal, which is sqrt(2) to three figures. Floating point in a
// cost that two machines compare is a way of disagreeing very slightly.
enum { COST_CARDINAL = 100, COST_DIAGONAL = 141 };

struct Node
{
	uint16_t x = 0;
	uint16_t y = 0;
	// Contiguous run in the edge array. Edges are sorted by (from, id), so a
	// node's edges are always visited in the same order.
	uint32_t firstEdge = 0;
	uint16_t edgeCount = 0;
};

struct Edge
{
	NodeId   from = 0;
	NodeId   to = 0;
	uint16_t cost = 0;
	EdgeType type = EdgeType::WalkCardinal;
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
		SearchStats &stats, unsigned int maxExpansions = 0) const;

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

private:
	TArray<Node>   nodes;
	TArray<Edge>   edges;
	TArray<NodeId> lookup;		// tile index -> node id, NO_NODE for none
	unsigned int   width = 0;
	unsigned int   height = 0;
	bool           built = false;
};

// The graph for the map currently loaded, built on first use.
Graph &Current();
void Invalidate();

}

#endif
