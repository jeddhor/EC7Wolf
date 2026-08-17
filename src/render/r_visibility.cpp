// ===========================================================================
//
// r_visibility.cpp - portal cell visibility.
//
// See r_visibility.h for why this exists. The short version: the cell
// visibility set used by the automap and the sprite cull used to be a side
// effect of the software raycaster's DDA, which is the last thing tying the GL
// renderer to the software wall pass.
//
// ===========================================================================

#include <math.h>

#include "wl_def.h"
#include "gamemap.h"
#include "id_ca.h"
#include "wl_main.h"
#include "wl_agent.h"
#include "wl_draw.h"
#include "wl_play.h"
#include "r_visibility.h"
#include "tarray.h"

// The view basis CalcViewVariables leaves behind (wl_draw.cpp); viewx/viewy are
// declared in wl_draw.h, viewangle is not.
extern angle_t viewangle;

namespace
{
	// The angular window carried through a portal, in radians relative to the
	// view direction. Left is positive, matching pixelangle[].
	struct Window
	{
		double lo, hi;
	};

	struct Pending
	{
		int    x, y;
		Window w;
	};

	// Per-cell record of the angular coverage already expanded from it, as a
	// small set of disjoint intervals.
	//
	// Merging matters more than it looks. Without it a cell in an open room gets
	// re-expanded once per slightly-different window arriving from a neighbour,
	// which in a 64x64 map exhausts any sane expansion budget long before the
	// far corners are reached -- and cells the traversal never reaches are cells
	// a sprite can be culled in. Merging makes each cell's covered measure grow
	// monotonically, so repeats die out on their own.
	enum { MAX_WINDOWS_PER_CELL = 8 };

	struct CellRecord
	{
		unsigned char count;
		Window        w[MAX_WINDOWS_PER_CELL];
	};

	TArray<CellRecord> gCells;
	unsigned int       gMarked = 0;

	inline double NormalizeAngle(double a)
	{
		while(a <= -M_PI) a += 2.0*M_PI;
		while(a > M_PI)   a -= 2.0*M_PI;
		return a;
	}

	// Does sight pass through this cell?
	//
	// Deliberately coarser than the raycaster's per-ray test, and coarse in the
	// permissive direction. The DDA decides per ray, at the exact intercept: a
	// door is passed if that ray crosses above the leaf, a pushwall if the ray
	// misses the moving slab. A cell-level traversal cannot ask that question,
	// so anything that is open at all is treated as open, which can only add
	// cells.
	bool SightPasses(MapSpot spot)
	{
		if(spot == NULL)
			return false;
		if(spot->tile == NULL)
			return true;

		// Glass, force fields and the rest of Corridor 7's masked walls are
		// drawn as walls but seen through.
		if(spot->maskedWallType || spot->tile->renderMasked ||
			spot->tile->sightTransparent || spot->corridor7SightTransparent)
			return true;

		// A door with any part of its leaf retracted, or a pushwall part way
		// through its slab, shows something of what is behind it.
		for(int i = 0; i < 4; ++i)
		{
			if(spot->slideAmount[i] != 0)
				return true;
		}
		if(spot->pushAmount != 0 || spot->pushReceptor != NULL)
			return true;

		return false;
	}

	inline void Mark(MapSpot spot)
	{
		if(spot == NULL)
			return;
		if(!spot->visible)
			++gMarked;
		spot->visible = true;
		spot->amFlags |= AM_Visible;
	}

	// Folds a window into a cell's coverage. Returns true when the cell was
	// already covered over that whole span, which is the signal to stop: every
	// cell it could reach through this window has already been reached through a
	// window at least as wide.
	bool AlreadyCovered(CellRecord &rec, const Window &in)
	{
		Window w = in;
		for(int i = 0; i < rec.count; ++i)
		{
			if(w.lo >= rec.w[i].lo - 1e-9 && w.hi <= rec.w[i].hi + 1e-9)
				return true;
		}

		// Absorb every interval this one touches, then reinsert the union.
		int out = 0;
		for(int i = 0; i < rec.count; ++i)
		{
			if(rec.w[i].hi >= w.lo - 1e-9 && rec.w[i].lo <= w.hi + 1e-9)
			{
				w.lo = MIN(w.lo, rec.w[i].lo);
				w.hi = MAX(w.hi, rec.w[i].hi);
			}
			else
				rec.w[out++] = rec.w[i];
		}
		rec.count = (unsigned char)out;

		if(rec.count < MAX_WINDOWS_PER_CELL)
		{
			rec.w[rec.count++] = w;
		}
		else
		{
			// Out of slots: widen the nearest interval to swallow this one. That
			// over-covers, so a later window may be skipped that would have
			// found nothing new anyway -- and over-covering here can only cost a
			// cell that is already reachable through the widened span.
			int best = 0;
			double bestGap = 1e30;
			for(int i = 0; i < rec.count; ++i)
			{
				const double gap = MIN(fabs(rec.w[i].lo - w.hi), fabs(w.lo - rec.w[i].hi));
				if(gap < bestGap) { bestGap = gap; best = i; }
			}
			rec.w[best].lo = MIN(rec.w[best].lo, w.lo);
			rec.w[best].hi = MAX(rec.w[best].hi, w.hi);
		}
		return false;
	}
}

unsigned int R_VisibleCellCount()
{
	return gMarked;
}

// ---------------------------------------------------------------------------
// Comparison harness
// ---------------------------------------------------------------------------

bool r_visdiff = false;

namespace
{
	TArray<unsigned char> gSnapA, gSnapB;
	unsigned long gDiffFrames  = 0;
	unsigned long gDiffBoth    = 0;
	unsigned long gDiffDDAOnly = 0;   // must stay 0: cells the portal missed
	unsigned long gDiffPortalOnly = 0;
	unsigned long gDiffWorstDDAOnly = 0;

	void Snapshot(TArray<unsigned char> &out)
	{
		const unsigned int mw = map->GetHeader().width;
		const unsigned int mh = map->GetHeader().height;
		if(out.Size() != mw*mh)
			out.Resize(mw*mh);
		for(unsigned int y = 0; y < mh; ++y)
			for(unsigned int x = 0; x < mw; ++x)
				out[y*mw + x] = map->GetSpot(x, y, 0)->visible ? 1 : 0;
	}
}

void WallRefreshVisibilityOnly();

void R_VisibilityDiffFrame()
{
	if(!r_visdiff || map == NULL || players[ConsolePlayer].camera == NULL)
		return;

	const unsigned int mw = map->GetHeader().width;
	const unsigned int mh = map->GetHeader().height;

	// The caller has just run one of the two; run each from a clean slate so
	// neither inherits the other's marks.
	map->ClearVisibility();
	WallRefreshVisibilityOnly();
	Snapshot(gSnapA);

	map->ClearVisibility();
	R_MarkVisibleCells();
	Snapshot(gSnapB);

	unsigned long both = 0, ddaOnly = 0, portalOnly = 0;
	for(unsigned int i = 0; i < mw*mh; ++i)
	{
		if(gSnapA[i] && gSnapB[i])      ++both;
		else if(gSnapA[i])              ++ddaOnly;
		else if(gSnapB[i])              ++portalOnly;
	}

	++gDiffFrames;
	gDiffBoth       += both;
	gDiffDDAOnly    += ddaOnly;
	gDiffPortalOnly += portalOnly;
	if(ddaOnly > gDiffWorstDDAOnly)
	{
		gDiffWorstDDAOnly = ddaOnly;
		// Name the cells the portal traversal failed to reach. This is the only
		// failure that matters -- an unreached cell culls whatever stands in it
		// -- and the properties printed here are what SightPasses decided on.
		static int budget = 24;
		int shown = 0;
		if(budget <= 0)
			shown = 8;
		budget -= 8;
		for(unsigned int i = 0; i < mw*mh && shown < 8; ++i)
		{
			if(!gSnapA[i] || gSnapB[i])
				continue;
			MapSpot s = map->GetSpot(i%mw, i/mw, 0);
			Printf("VISMISS (%u,%u) tile=%d masked=%d rmask=%d sightT=%d c7T=%d slide=%u/%u/%u/%u push=%u recv=%d\n",
				i%mw, i/mw, s->tile?1:0, (int)s->maskedWallType,
				s->tile && s->tile->renderMasked ? 1 : 0,
				s->tile && s->tile->sightTransparent ? 1 : 0,
				s->corridor7SightTransparent ? 1 : 0,
				s->slideAmount[0], s->slideAmount[1], s->slideAmount[2], s->slideAmount[3],
				s->pushAmount, s->pushReceptor?1:0);
			++shown;
		}
	}

	// Leave the portal set standing: it is what the renderer is being asked to
	// use, and re-running it here would only repeat work already done.

	// Report periodically rather than at exit, so a run that is killed (or one
	// driven by --capture-maxframes) still says something.
	if((gDiffFrames % 100) == 0)
		R_VisibilityDiffReport();
}

void R_VisibilityDiffReport()
{
	if(!r_visdiff || gDiffFrames == 0)
		return;
	Printf("Visibility diff: %lu frames, both %lu, portal-only %lu, raycaster-only %lu (worst frame %lu)\n",
		gDiffFrames, gDiffBoth, gDiffPortalOnly, gDiffDDAOnly, gDiffWorstDDAOnly);
}

void R_MarkVisibleCells()
{
	gMarked = 0;

	if(map == NULL || players[ConsolePlayer].camera == NULL)
		return;

	const unsigned int mw = map->GetHeader().width;
	const unsigned int mh = map->GetHeader().height;
	if(mw == 0 || mh == 0)
		return;

	if(gCells.Size() != mw*mh)
		gCells.Resize(mw*mh);
	memset(&gCells[0], 0, sizeof(CellRecord)*mw*mh);

	// The half-angle of the view cone, taken from the table the raycaster's
	// leftmost column uses so the two agree by construction at every FOV, view
	// size and aspect. pixelangle is in fine-angle units.
	double halfFov = M_PI*0.5;
	if(pixelangle.Get() != NULL && viewwidth > 0)
	{
		const double fine = (double)pixelangle[0];
		halfFov = fine * (2.0*M_PI / (double)FINEANGLES);
		if(halfFov <= 0.0)
			halfFov = M_PI*0.5;
	}
	// One extra column's worth of margin. The raycaster's outermost ray is half
	// a pixel inside the edge of the view, and a cell clipped to exactly that
	// bound would be a coin toss at the frustum edge.
	halfFov = MIN(halfFov + (2.0*M_PI/(double)FINEANGLES)*2.0, M_PI*0.98);

	// The eye is the raycaster's eye, not the camera's centre: CalcViewVariables
	// pulls it back by focallength, and the visible set has to be built from the
	// same point or near-field cells disagree.
	const double eyex = (double)viewx / (double)FRACUNIT;
	const double eyey = (double)viewy / (double)FRACUNIT;
	// Forward is (cos, -sin) in map coordinates -- CalcViewVariables adds
	// FixedMul(focallength, viewsin) to y -- so a point's bearing is
	// atan2(-dy, dx) and the view direction is +viewangle in the same frame.
	const double dir  = (double)viewangle * (2.0*M_PI / 4294967296.0);

	// Whatever the camera stands in is seen, including the pushwall slab a
	// player can be inside of.
	const int camx = players[ConsolePlayer].camera->tilex;
	const int camy = players[ConsolePlayer].camera->tiley;
	if((unsigned)camx < mw && (unsigned)camy < mh)
		Mark(map->GetSpot(camx, camy, 0));

	int startx = (int)(viewx >> TILESHIFT);
	int starty = (int)(viewy >> TILESHIFT);
	startx = clamp(startx, 0, (int)mw-1);
	starty = clamp(starty, 0, (int)mh-1);

	// Breadth first, not depth first. The budget below can truncate the search,
	// and a queue makes that truncation happen at the far edge of the view where
	// it costs a distant cell, rather than partway down one arbitrary branch
	// while a whole half of the cone is still unvisited.
	TArray<Pending> queue;
	unsigned int head = 0;
	Pending first;
	first.x = startx;
	first.y = starty;
	first.w.lo = -halfFov;
	first.w.hi =  halfFov;
	queue.Push(first);

	// Expansion budget. Termination is already bounded by the per-cell window
	// cap; this is the belt to that pair of braces, and keeps a pathological
	// open map from costing more than the raycaster it replaced.
	unsigned int budget = mw*mh*32 + 65536;

	while(head < queue.Size() && budget-- > 0)
	{
		const Pending cur = queue[head++];

		MapSpot spot = map->GetSpot(cur.x, cur.y, 0);
		Mark(spot);

		// A wall is seen but not seen past.
		if(!SightPasses(spot))
			continue;

		CellRecord &rec = gCells[cur.y*mw + cur.x];
		if(AlreadyCovered(rec, cur.w))
			continue;

		// The cell's four edges, as (corner A, corner B, neighbour offset).
		// Corners are in tile units; the edge between this cell and the
		// neighbour is what the window is clipped to.
		static const int kEdge[4][6] =
		{
			//  ax, ay,  bx, by,  dx, dy
			{    1,  0,   1,  1,   1,  0 },   // east
			{    0,  0,   1,  0,   0, -1 },   // north
			{    0,  0,   0,  1,  -1,  0 },   // west
			{    0,  1,   1,  1,   0,  1 }    // south
		};

		for(int e = 0; e < 4; ++e)
		{
			const int nx = cur.x + kEdge[e][4];
			const int ny = cur.y + kEdge[e][5];
			if((unsigned)nx >= mw || (unsigned)ny >= mh)
				continue;

			const double ax = (double)(cur.x + kEdge[e][0]);
			const double ay = (double)(cur.y + kEdge[e][1]);
			const double bx = (double)(cur.x + kEdge[e][2]);
			const double by = (double)(cur.y + kEdge[e][3]);

			double a0 = NormalizeAngle(atan2(-(ay - eyey), ax - eyex) - dir);
			double a1 = NormalizeAngle(atan2(-(by - eyey), bx - eyex) - dir);

			double lo = MIN(a0, a1);
			double hi = MAX(a0, a1);

			// A straight segment can never subtend more than half a turn from a
			// point not on it, so an apparent span above pi means the short arc
			// between the endpoints is the one running through +/-pi -- that is,
			// the edge is behind the eye. The frustum is well under half a turn
			// and centred on zero, so nothing there can be in view.
			//
			// Inheriting the parent window here instead (an earlier attempt at
			// "the eye is inside this cell, so do not clip") let the search walk
			// backwards through the cell behind the camera at full width, and
			// every cell it reached did the same. Depth-first, that consumed the
			// entire expansion budget before most of the actual view was
			// visited: 84 cells per frame that the raycaster marked went unseen.
			if(hi - lo > M_PI)
				continue;

			lo = MAX(lo, cur.w.lo);
			hi = MIN(hi, cur.w.hi);

			if(hi <= lo)
				continue;

			Pending next;
			next.x = nx;
			next.y = ny;
			next.w.lo = lo;
			next.w.hi = hi;
			queue.Push(next);
		}
	}
}
