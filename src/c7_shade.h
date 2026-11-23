// Corridor 7's own distance shading for walls and sprites (GitHub #57).
//
// The original does not shade through a light model. Its compiled scalers
// darken every texel by a whole number of palette steps, chosen per column from
// the projected height, and send a texel that reaches the bottom of its colour
// ramp to black. See c7_shade.cpp for the native code this reproduces.

#ifndef __C7_SHADE_H__
#define __C7_SHADE_H__

#include "wl_def.h"

namespace C7Shade
{
	// The deepest shade the original applies: c0a2[0].
	enum { MAX_SHADE = 16, ROWS = MAX_SHADE + 1 };

	// True when Corridor 7 is loaded and the Original lighting is selected.
	bool Active();

	// Rebuilds the 17 shade rows from the current palette. Physical index in,
	// physical index out, so the palette's color-0 remap is accounted for.
	void BuildTables();

	// Row S (0..16): what the scaler writes for each texel at shade S.
	const BYTE *Row(int shade);

	// Per-frame: the brightness level (0..10) and the muzzle flash, which the
	// original adds to the height index before looking the shade up.
	void SetFrameBonus(int bonus);
	int FrameBonus();

	// Shade for a wall column or a sprite, from the port's projected height
	// ((heightnumerator<<8)/z, the same quantity as the original's). The
	// conversion to the original's 320-wide projection makes the result a
	// function of distance alone, whatever the resolution or field of view.
	int WallShade(int portHeight);
	int SpriteShade(int portHeight);

	// The shade for a height index (see c7_shade.cpp); GL computes the index.
	int ShadeForIndex(int index);

	// The floor and ceiling as the original paints them: a fixed screen-space
	// pattern of palette pairs, 80 rows per plane in the 320x160 view, the
	// two colors alternating in four-pixel groups. Indexed by the row counted
	// from the plane's near edge (the top of the view for the ceiling, the
	// bottom for the floor) and by the group's parity. Returns NULL when the
	// level has no C7Planes for its current flats or Original lighting is off.
	// FLATCOLOR is the flat's own palette index: only texels of that color
	// take the pattern, so other flats keep their texture.
	enum { PLANE_ROWS = 80 };
	const BYTE (*PlanePattern(bool ceiling, int &flatColor))[2];
}

#endif
