#ifndef __R_VISIBILITY_H__
#define __R_VISIBILITY_H__

// ===========================================================================
//
// Portal cell visibility.
//
// The engine's cell-visibility set -- `spot->visible` for the sprite cull and
// `AM_Visible` for the automap -- was historically a side effect of the
// software raycaster: whatever cells its per-column DDA walked through were
// what you had seen. That coupled the GL renderer to the software wall pass,
// which it otherwise has no use for.
//
// This replaces it with a traversal that answers the question directly: flood
// outwards from the camera cell through cells that sight can pass, carrying an
// angular window that each portal narrows. A cell is marked when a non-empty
// window reaches it; expansion continues only through cells sight passes.
//
// It is deliberately conservative -- it may mark a cell the raycaster's finite
// ray set happened to miss, never the reverse -- because the failure modes are
// asymmetric: an extra revealed automap cell is cosmetic, a missing one culls a
// sprite that should have been drawn. tools/test_gl_visibility.sh measures the
// difference against the raycaster across maps and viewpoints.
//
// ===========================================================================

// Marks every cell the camera can see, from the current view globals
// (viewx/viewy/viewangle, set by CalcViewVariables). Call after
// GameMap::ClearVisibility().
void R_MarkVisibleCells();

// Counts cells marked by the last R_MarkVisibleCells() call. Diagnostics only.
unsigned int R_VisibleCellCount();

// --- Comparison harness (--vis-diff) ------------------------------------------
//
// The portal traversal is allowed to mark cells the raycaster's finite ray set
// missed, but must never miss one the raycaster marked -- that direction culls
// sprites. When armed, this runs both for the same view and folds the result
// into a running tally; R_VisibilityDiffReport() prints it.
extern bool r_visdiff;

// Call once per frame, immediately after the active traversal has run. Leaves
// the map's visibility set exactly as it found it.
void R_VisibilityDiffFrame();
void R_VisibilityDiffReport();

#endif
