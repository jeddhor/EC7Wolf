/*
** g_command.h
**
** Where a command comes from, and what it is allowed to say.
**
** The engine has exactly one command producer: PollControls samples this
** machine's keyboard, mouse and joystick into control[ConsolePlayer], and
** everything else in a netgame arrives from a socket. That is a complete
** description of the world right up until a slot needs a command and has
** neither a keyboard nor an address -- which is every bot, and every slot on a
** server with no player of its own.
**
** So sampling and finalizing become two steps. A producer emits an Intent:
** normalized movement and a set of requested actions, with no actor handles
** and no way to touch the world. Finalization clamps it, strips anything that
** is not a gameplay control, and installs it as the slot's TicCmd_t. The rule
** that follows is the one the whole bot design rests on:
**
**     nothing reaches the simulation except through a command, and every
**     command has been through here.
**
** Held state is derived here too, from the previous command actually applied to
** that slot, rather than being carried by whoever produced it. A producer that
** got it wrong -- or a packet that lied about it -- could otherwise turn one
** tap into a hold, or a hold into eleven taps.
**
** See docs/multiplayer-bots-and-server.md, milestone S4.
*/

#ifndef __G_COMMAND_H__
#define __G_COMMAND_H__

#include <stdint.h>

#include "wl_def.h"
#include "g_session.h"
#include "zstring.h"

struct TicCmd_t;

namespace Command {

// The canonical axis range. PollControls already produces values in it, and
// ControlMovement reads walk or run out of the magnitude, so a producer that
// exceeds it is not "fast" -- it is outside the range the game was balanced
// and tested in. Clamped rather than rejected, and the clamp is counted.
enum { AXIS_MIN = -100, AXIS_MAX = 100 };

// What a producer says it wants. Deliberately not a TicCmd_t: there is no
// pan/pitch here (multiplayer has no canonical representation for it, see
// S1), no held state (derived, never asserted), and no automap fields.
struct Intent
{
	int  forward = 0;
	int  strafe  = 0;
	int  turn    = 0;
	bool press[NUMBUTTONS] = {};

	void Clear();
	void Press(int button);
};

// A command producer for one slot. Implementations must not read or mutate the
// world: everything they need arrives as arguments, and everything they can say
// leaves as an Intent.
class Producer
{
public:
	virtual ~Producer() {}
	// Fill `out` for this slot at this sequence. Returning false means the
	// producer has nothing left to say and the slot gets a neutral command.
	virtual bool Produce(Session::PlayerSlot slot, uint32_t sequence,
		Intent &out) = 0;
	virtual const char *Describe() const = 0;
};

// Is this button a gameplay control, or a thing this machine does to its own
// screen? Escape, pause, the automap toggles, the status bar and the
// scoreboard are local UI: they are processed by the instance whose keyboard
// they came from and never enter a command. A producer that emits one is a
// bug, and gets counted as one.
bool IsGameplayButton(int button);

// --- the canonical frame -----------------------------------------------------

// Begin the frame for one sequence. Every active slot must be given exactly one
// command before Finish(), and the whole frame is built before any thinker
// runs, so that one slot's movement cannot change another slot's command in the
// same tic.
void BeginFrame(uint32_t sequence);
// Install a finalized command for a slot that produced one elsewhere -- the
// local human's sampled command, or a command that arrived from a peer. The
// held state is recomputed here regardless of what the caller had in it.
void InstallSampled(Session::PlayerSlot slot, const TicCmd_t &sampled);
// Run the registered producer for a slot and install what it says.
void ProduceAndInstall(Session::PlayerSlot slot, uint32_t sequence);
// Every active slot has a command. In debug builds, says so loudly if not.
void FinishFrame();

// --- producers ---------------------------------------------------------------

// Takes ownership. A slot may have at most one.
void SetProducer(Session::PlayerSlot slot, Producer *producer);
Producer *ProducerFor(Session::PlayerSlot slot);
bool HasProducer(Session::PlayerSlot slot);
void ClearProducers();

// A fixed tape of commands, replayed in order. Queries nothing, decides
// nothing, and exists to prove the seam carries a command for a slot that has
// neither a keyboard nor a socket. This is not an AI and is not a step toward
// one; the AI arrives in Phase B and arrives behind this same interface.
Producer *MakeScriptedProducer(const char *tapePath, FString &error);

// --- local UI intent ----------------------------------------------------------
//
// Escape, pause, the automap toggles, the status bar and the scoreboard are
// things this machine does to its own screen. They are sampled from this
// keyboard, processed by this instance, and never enter a command -- so the
// finalizer strips them, and the presentation code that used to read them out
// of control[ConsolePlayer] reads them from here instead.
//
// That also fixes a smaller thing: in a netgame control[] holds a command from
// a delay window ago, so a scoreboard key used to take effect several tics
// after it was pressed. Local UI has no reason to wait for the network.
void SetLocalUi(const TicCmd_t &sampled);
const TicCmd_t &LocalUi();

// --- diagnostics --------------------------------------------------------------

// One line per slot per sequence, and a rolling digest of the commands alone --
// separate from the world digest, because "the machines disagree about what was
// pressed" and "the machines disagree about what happened" are different
// failures with different causes.
void OpenTrace(const char *path);
void CloseTrace();
uint32_t Digest();

// Counters the tests read: how many times a producer had to be corrected.
struct Violations
{
	unsigned int clampedAxes = 0;
	unsigned int strippedButtons = 0;
	unsigned int missingCommands = 0;
};
const Violations &GetViolations();
void ResetViolations();

}

#endif
