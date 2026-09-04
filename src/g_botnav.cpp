/*
** g_botnav.cpp
**
** See g_botnav.h for the three decisions this rests on.
*/

#include <string.h>

#include "g_botnav.h"
#include "id_ca.h"
#include "gamemap.h"
#include "wl_main.h"

namespace BotNav {

void Graph::Clear()
{
	nodes.Clear();
	edges.Clear();
	lookup.Clear();
	width = height = 0;
	built = false;
}

NodeId Graph::NodeAt(unsigned int tileX, unsigned int tileY) const
{
	if(!built || tileX >= width || tileY >= height)
		return NO_NODE;
	return lookup[tileY*width + tileX];
}

bool Graph::Build(const Traversal::Body &body)
{
	Clear();
	if(map == NULL)
		return false;

	width = map->GetHeader().width;
	height = map->GetHeader().height;
	if(width == 0 || height == 0)
		return false;

	lookup.Resize(width*height);
	for(unsigned int i = 0;i < lookup.Size();++i)
		lookup[i] = NO_NODE;

	// Nodes in raster order, so a node's id is a function of where it is and
	// nothing else. Rebuild the same map and get the same ids.
	for(unsigned int y = 0;y < height;++y)
	{
		for(unsigned int x = 0;x < width;++x)
		{
			if(!Traversal::CanOccupyTile(body, x, y))
				continue;
			if(nodes.Size() >= NO_NODE)
				break;		// 65535 nodes is sixteen times a Corridor 7 arena
			Node node;
			node.x = (uint16_t)x;
			node.y = (uint16_t)y;
			lookup[y*width + x] = (NodeId)nodes.Size();
			nodes.Push(node);
		}
	}

	if(nodes.Size() == 0)
		return false;

	// Edges, in node order and within a node in a fixed direction order, so
	// the edge array is a function of the graph and not of how it was walked.
	static const int dx[8] = {  1,  0, -1,  0,  1,  1, -1, -1 };
	static const int dy[8] = {  0, -1,  0,  1, -1,  1, -1,  1 };

	for(unsigned int n = 0;n < nodes.Size();++n)
	{
		Node &node = nodes[n];
		node.firstEdge = edges.Size();
		node.edgeCount = 0;

		for(unsigned int d = 0;d < 8;++d)
		{
			const int nx = (int)node.x + dx[d];
			const int ny = (int)node.y + dy[d];
			if(nx < 0 || ny < 0 || (unsigned)nx >= width || (unsigned)ny >= height)
				continue;

			const NodeId to = lookup[(unsigned)ny*width + (unsigned)nx];
			if(to == NO_NODE)
				continue;

			const bool diagonal = d >= 4;
			if(diagonal)
			{
				// A diagonal may not cut a corner: squeezing between two
				// blocked cardinals means passing through the point where the
				// two walls meet, which no body with width can do.
				//
				// Measured, and currently redundant. Removing this check
				// changes none of the four shipped arenas by a single edge,
				// because the sampled sweep below already rejects every one of
				// these: a 22-unit body crossing a corner diagonally collides
				// at some sample whatever the corner looks like.
				//
				// Kept anyway, and labelled rather than quietly left in. The
				// sweep is a finite approximation -- four samples to the tile,
				// so sixteen units apart -- and a body under about eight units
				// wide could thread a corner between two of them. No Corridor
				// 7 class is that small; a mod's could be. This is the
				// guarantee, and the sweep is what happens to be enforcing it
				// today.
				const NodeId sideA = lookup[(unsigned)node.y*width + (unsigned)nx];
				const NodeId sideB = lookup[(unsigned)ny*width + (unsigned)node.x];
				if(sideA == NO_NODE || sideB == NO_NODE)
					continue;
			}

			// And the sweep itself, asked of the same code the pawn obeys.
			if(!Traversal::CanStepBetweenTiles(body, node.x, node.y,
				(unsigned)nx, (unsigned)ny))
				continue;

			Edge edge;
			edge.from = (NodeId)n;
			edge.to = to;
			edge.cost = diagonal ? COST_DIAGONAL : COST_CARDINAL;
			edge.type = diagonal ? EdgeType::WalkDiagonal : EdgeType::WalkCardinal;
			edges.Push(edge);
			++node.edgeCount;
		}
	}

	built = true;
	return true;
}

bool Graph::FindPath(NodeId from, NodeId to, TArray<NodeId> &path,
	SearchStats &stats, unsigned int maxExpansions) const
{
	path.Clear();
	stats = SearchStats();

	if(!built || from >= nodes.Size() || to >= nodes.Size())
		return false;
	if(from == to)
	{
		path.Push(from);
		stats.found = true;
		return true;
	}

	if(maxExpansions == 0)
		maxExpansions = nodes.Size() + 1;

	// Dijkstra. Not A*: see the header. A binary heap keyed on (cost, node),
	// so equal costs break on the lower node id and the search is the same
	// search every time it is run.
	const uint32_t Unreached = 0xFFFFFFFFu;
	TArray<uint32_t> best;
	TArray<NodeId>   cameFrom;
	TArray<bool>     closed;
	best.Resize(nodes.Size());
	cameFrom.Resize(nodes.Size());
	closed.Resize(nodes.Size());
	for(unsigned int i = 0;i < nodes.Size();++i)
	{
		best[i] = Unreached;
		cameFrom[i] = NO_NODE;
		closed[i] = false;
	}

	struct Entry
	{
		uint32_t cost;
		NodeId   node;
		// Lower cost first; equal cost breaks on the lower id, so the answer
		// does not depend on which of two equal routes was pushed first.
		bool Worse(const Entry &other) const
		{
			if(cost != other.cost)
				return cost > other.cost;
			return node > other.node;
		}
	};

	TArray<Entry> heap;
	struct Heap
	{
		static void Push(TArray<Entry> &h, const Entry &e)
		{
			h.Push(e);
			unsigned int i = h.Size() - 1;
			while(i > 0)
			{
				const unsigned int parent = (i - 1)/2;
				if(!h[parent].Worse(h[i]))
					break;
				const Entry tmp = h[parent];
				h[parent] = h[i];
				h[i] = tmp;
				i = parent;
			}
		}
		static Entry Pop(TArray<Entry> &h)
		{
			const Entry top = h[0];
			h[0] = h[h.Size() - 1];
			h.Delete(h.Size() - 1);
			unsigned int i = 0;
			for(;;)
			{
				const unsigned int l = i*2 + 1, r = l + 1;
				unsigned int small = i;
				if(l < h.Size() && h[small].Worse(h[l]))
					small = l;
				if(r < h.Size() && h[small].Worse(h[r]))
					small = r;
				if(small == i)
					break;
				const Entry tmp = h[small];
				h[small] = h[i];
				h[i] = tmp;
				i = small;
			}
			return top;
		}
	};

	best[from] = 0;
	Entry start = { 0, from };
	Heap::Push(heap, start);

	while(heap.Size() > 0)
	{
		const Entry current = Heap::Pop(heap);
		if(closed[current.node])
			continue;			// a stale copy left by a cheaper route
		closed[current.node] = true;

		if(current.node == to)
			break;

		if(++stats.expansions > maxExpansions)
		{
			// Says so rather than returning the best it happened to have. A
			// path that was not finished being found is not a path.
			stats.exhaustedBudget = true;
			return false;
		}

		const Node &node = nodes[current.node];
		for(unsigned int e = 0;e < node.edgeCount;++e)
		{
			const Edge &edge = edges[node.firstEdge + e];
			if(closed[edge.to])
				continue;
			const uint32_t through = current.cost + edge.cost;
			if(through >= best[edge.to])
				continue;
			if(best[edge.to] != Unreached)
				++stats.reopenings;
			best[edge.to] = through;
			cameFrom[edge.to] = current.node;
			Entry next = { through, edge.to };
			Heap::Push(heap, next);
		}
	}

	if(best[to] == Unreached)
		return false;

	// Walk the parents back and reverse, so the caller gets it start first.
	TArray<NodeId> reversed;
	for(NodeId at = to;at != NO_NODE;at = cameFrom[at])
	{
		reversed.Push(at);
		if(at == from)
			break;
	}
	for(unsigned int i = reversed.Size();i-- > 0;)
		path.Push(reversed[i]);

	stats.found = true;
	return true;
}

// Can a body walk straight from one node to another, ignoring the grid?
//
// Sampled along the actual line at a step finer than the body is wide, because
// the question a shortcut asks is whether the pawn fits all the way along it,
// and a shortcut that only checks its ends is how a route ends up going
// through a corner.
bool Graph::StraightLineFits(const Traversal::Body &body, NodeId a, NodeId b) const
{
	const Node &na = nodes[a];
	const Node &nb = nodes[b];

	const fixed half = (fixed)(1<<(TILESHIFT-1));
	const fixed ax = (fixed)(na.x<<TILESHIFT) + half;
	const fixed ay = (fixed)(na.y<<TILESHIFT) + half;
	const fixed bx = (fixed)(nb.x<<TILESHIFT) + half;
	const fixed by = (fixed)(nb.y<<TILESHIFT) + half;

	const int tiles = abs((int)nb.x - (int)na.x) + abs((int)nb.y - (int)na.y);
	// Four samples per tile crossed: a sixteen-unit step against a body
	// twenty-two units wide, so nothing the body would collide with can fall
	// between two samples.
	const unsigned int steps = (unsigned int)(tiles*4 + 1);
	for(unsigned int i = 1;i < steps;++i)
	{
		const fixed x = ax + (fixed)(((int64_t)(bx - ax)*i)/steps);
		const fixed y = ay + (fixed)(((int64_t)(by - ay)*i)/steps);
		if(!Traversal::CheckPositionAt(body, x, y, NULL))
			return false;
	}
	return true;
}

void Graph::Smooth(const Traversal::Body &body, TArray<NodeId> &path) const
{
	if(path.Size() < 3)
		return;

	TArray<NodeId> out;
	out.Push(path[0]);

	unsigned int anchor = 0;
	while(anchor + 1 < path.Size())
	{
		// The furthest node still reachable in a straight line from the
		// anchor. Checked with the traversal query rather than by looking at
		// the tiles, because a run of standable tiles is not the same as a
		// corridor a body fits along.
		unsigned int furthest = anchor + 1;
		for(unsigned int probe = anchor + 2;probe < path.Size();++probe)
		{
			if(!StraightLineFits(body, path[anchor], path[probe]))
				break;
			furthest = probe;
		}
		out.Push(path[furthest]);
		anchor = furthest;
	}

	path = out;
}

uint32_t Graph::Digest() const
{
	// FNV-1a over the graph in id order. Two graphs that hash alike are the
	// same graph, which is what makes "did the map change under us" and "did
	// the build change" separable questions.
	uint32_t hash = 2166136261u;
	struct Fold
	{
		static void Bytes(uint32_t &h, const void *data, size_t len)
		{
			const unsigned char *p = (const unsigned char *)data;
			for(size_t i = 0;i < len;++i)
			{
				h ^= p[i];
				h *= 16777619u;
			}
		}
	};

	const uint32_t nodeCount = nodes.Size();
	const uint32_t edgeCount = edges.Size();
	Fold::Bytes(hash, &nodeCount, sizeof(nodeCount));
	Fold::Bytes(hash, &edgeCount, sizeof(edgeCount));
	for(unsigned int i = 0;i < nodes.Size();++i)
	{
		Fold::Bytes(hash, &nodes[i].x, sizeof(nodes[i].x));
		Fold::Bytes(hash, &nodes[i].y, sizeof(nodes[i].y));
		Fold::Bytes(hash, &nodes[i].edgeCount, sizeof(nodes[i].edgeCount));
	}
	for(unsigned int i = 0;i < edges.Size();++i)
	{
		Fold::Bytes(hash, &edges[i].from, sizeof(edges[i].from));
		Fold::Bytes(hash, &edges[i].to, sizeof(edges[i].to));
		Fold::Bytes(hash, &edges[i].cost, sizeof(edges[i].cost));
		const uint8_t type = (uint8_t)edges[i].type;
		Fold::Bytes(hash, &type, sizeof(type));
	}
	return hash;
}

Graph &Current()
{
	static Graph graph;
	return graph;
}

void Invalidate()
{
	Current().Clear();
}

}
