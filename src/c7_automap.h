/*
** c7_automap.h
**
** Corridor 7's own inset map panel, as distinct from ECWolf's full-viewport
** automap (am_map.h). Both exist: Tab raises this panel, M raises ECWolf's.
**
*/

#ifndef __C7_AUTOMAP_H__
#define __C7_AUTOMAP_H__

// Whether the panel is currently shown. Tab toggles it; it is not a held key.
bool C7Map_Active();
void C7Map_Toggle();

// Drops the panel and forgets per-level state. Called on level entry, matching
// the floor plan itself not surviving a floor change.
void C7Map_LevelReset();

// Draws the panel over the 3D view. Must be a pure drawing function: the GL
// backend calls it more than once to measure which view texels it paints.
// See IRenderer::DrawViewOverlay.
void C7Map_Draw();

#endif
