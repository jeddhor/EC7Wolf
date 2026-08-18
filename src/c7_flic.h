#ifndef __C7_FLIC_H__
#define __C7_FLIC_H__

// ===========================================================================
//
// Corridor 7 CD cinematics (Autodesk FLIC).
//
// The CD release ships three animations the floppy release does not, and the
// DOS installer leaves them on the disc because they were meant to be streamed
// from it -- so they are in nobody's installed game directory. tools/
// extract_c7_video.py pulls them off a disc image into a `video/` directory
// beside the game data, and this plays them.
//
// They are FLC: 320x200, 8-bit, 71 ms/frame, each carrying its own palette.
// That is exactly the shape of every other full-screen page in this game, so
// playback goes through the ordinary 2D page path and needs nothing from either
// renderer.
//
// See docs/corridor7-video.md.
//
// ===========================================================================

#include "zstring.h"

// Looks for the video directory beside the game data. Safe to call before any
// of the others; everything here is a no-op when nothing was found.
void C7Flic_Init();

// True when NAME (e.g. "SEQONE") was found and validated at startup.
bool C7Flic_Have(const char *name);

// Plays NAME to the screen, returning when it ends or the player skips it.
// Returns false if there was nothing to play, so callers can fall through to
// whatever they did before.
//
// Restores the palette it found, so the caller's screen state survives.
bool C7Flic_Play(const char *name);

// Decodes an animation and prints a per-frame checksum, without starting a game
// or opening a window. Drives --flictest; returns a process exit code.
int C7Flic_SelfTest(const char *path);

#endif
