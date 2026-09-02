#ifndef __WL_INTER_H__
#define __WL_INTER_H__

/*
=============================================================================

								WL_INTER

=============================================================================
*/

extern struct LRstruct
{
	unsigned int killratio;
	unsigned int secretsratio;
	unsigned int treasureratio;
	unsigned int numLevels;
	unsigned int time;
	unsigned int par;
} LevelRatios;

void DrawHighScores(void);
void CheckHighScore (int32_t score, const class LevelInfo *levelInfo);
void Victory (bool fromIntermission);
void LevelCompleted (void);
void Corridor7Death (void);
// The Corridor 7 pages print through a stencil: a palette index rather than a
// color range, so the text lands in the page's own palette. Shared with the
// multiplayer scoreboard, which draws on the same backdrop.
void C7StencilPrintAt(class FFont *font, int x, int y, const char *text,
	BYTE paletteIndex);
void ClearSplitVWB (void);

void PreloadGraphics(bool showPsych);

#endif
