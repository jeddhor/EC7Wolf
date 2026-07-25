#ifndef __R_CAPTURE_H__
#define __R_CAPTURE_H__

#include "zdoomsupport.h"

// ===========================================================================
//
// Deterministic capture & determinism-checksum harness.
//
// Renderer-redesign Phase 0.  Every feature here is opt-in through the command
// line and is a complete no-op in normal play, so gameplay, timing and the
// render path are unaffected unless a capture switch is supplied.
//
// Purpose:
//   * Produce byte-repeatable golden screenshots at a chosen rendered frame.
//   * Emit a per-simulation-tic checksum of deterministic world state so that
//     later phases (fixed-step timing, interpolation, hardware renderers) can
//     be proven to leave the simulation bit-identical.
//
// Command line switches (see r_capture.cpp for details):
//   --capture-rngseed N     Force the RNG seed for reproducible simulation.
//   --capture-checksum PATH Write a per-tic + summary checksum log to PATH.
//   --capture-frame N       Screenshot after rendered frame N (1-based).
//   --capture-file PATH     Destination PNG for --capture-frame.
//   --capture-maxframes N   Finalize the checksum log and quit after N frames.
//   --capture-open-doors N  Force every door to slide amount N (0..65535) each
//                           tic, so a mid-slide door can be compared between the
//                           software and GL renderers without scripted input.
//   --capture-blend R G B A Force a full-screen palette flash (0..255 each, alpha
//                           0..256) so a flashed frame can be captured to verify
//                           the GL renderer applies full-screen palette effects.
//   --capture-warp X Y DEG  Pin the player to tile (X,Y) facing DEG degrees every
//                           tic, so a specific viewpoint can be reproduced for a
//                           software-vs-GL comparison independent of the bot.
//
// ===========================================================================

namespace Capture
{
	// Scan argv for capture switches.  Safe to call before the video system or
	// game exist; only records intent.  Called once from the program entry.
	void ParseArgs(int argc, char **argv);

	// True if any capture feature is armed.  Hot-path callers use this to skip
	// all work in ordinary runs.
	bool Active();

	// If --capture-rngseed was supplied, overwrite seed with the fixed value
	// and return true.  Called right after the engine picks its RNG seed.
	bool OverrideRNGSeed(DWORD &seed);

	// Apply capture-time world overrides (e.g. --capture-open-doors) at the top
	// of each simulation tic, before thinkers run, so the forced state is picked
	// up by both the software render and the GL interpolation snapshots. No-op
	// unless an override switch was supplied.
	void PreTic();

	// Force a full-screen palette blend (--capture-blend R G B A) just before the
	// scene is rendered, after the gameplay palette shifts have run so it is not
	// clobbered. Lets a flashed frame be captured deterministically to prove the
	// GL renderer applies full-screen palette effects. No-op unless supplied.
	void ApplyPaletteOverride();

	// Fold this simulation tic's deterministic state into the running checksum.
	// Call exactly once per executed 70 Hz tic, after the tic is simulated.
	void PerTic();

	// Handle screenshot-on-frame-N and the frame-count quit condition.  Call
	// exactly once per rendered/presented frame.
	void PostFrame();
}

#endif
