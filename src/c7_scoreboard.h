/*
** c7_scoreboard.h
**
** The multiplayer scoreboard and the end-of-match tally, drawn in the
** Corridor 7 high-score page's visual language.
*/

#ifndef __C7_SCOREBOARD_H__
#define __C7_SCOREBOARD_H__

// Overlay drawn on top of the play view while the scoreboard key is held.
// Draws nothing outside a netgame: there is no score to compare in a game of
// one.
void C7Scoreboard_DrawOverlay();

// The full page shown when a match ends, on the same backdrop the high-score
// page uses. Waits for every player, so the next round starts together.
void C7Scoreboard_ShowTally();

#endif
