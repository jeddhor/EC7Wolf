/*
** g_session.h
**
** Four things that have always been one thing.
**
** The engine has a single number, Net::InitVars.numPlayers, that means the
** number of UDP participants, the number of command producers, the number of
** connected addresses, the number of player_t objects, and the bound of every
** spawn, score, frag, inventory and respawn loop -- all at once. Alongside it
** sits ConsolePlayer, which means the slot this machine's human occupies, the
** slot this machine renders from, and the slot that owns the arbiter role,
** also all at once. Neither confusion is a problem while one process holds
** exactly one player and every player holds exactly one socket.
**
** Both of the things this engine is being taken toward break that. A bot
** occupies a slot and owns no socket; a dedicated server owns a socket, is the
** authority, and occupies no slot at all. Neither can be described in the
** existing vocabulary, which is why they are blocked on the same refactor
** rather than on anything to do with AI or with headless rendering.
**
** So there are four separate identities here, and code should say which one it
** means:
**
**   runtime role  what this process is: standalone, client, listen authority,
**                 or (later) a dedicated authority
**   peer          one connected process in the session
**   player slot   one index into players[] and its pawn -- never a process
**   local view    the slot this process draws from, if it draws at all
**
** A listen host is authority and owns a human slot. A client is neither
** authority nor slot-0. A dedicated authority is authority and owns nothing.
** Version 1 keeps occupied slots contiguous, so ActiveSlotCount() is a drop-in
** replacement for the old count in every loop that was really counting slots.
**
** See docs/multiplayer-bots-and-server.md, Part II.
*/

#ifndef __G_SESSION_H__
#define __G_SESSION_H__

#include <optional>
#include <stdint.h>

#include "zstring.h"
#include "name.h"
#include "wl_def.h"

namespace Session {

// Three capacities, deliberately separate. They happen to be related today and
// will not stay that way: a dedicated authority is a session peer that owns no
// slot, so the session can hold more processes than there are players, and a
// future spectator is a client peer that owns no slot either. Any new API that
// assumes one bound for all three is reintroducing the problem this file
// exists to remove.
enum
{
	MAX_PLAYER_SLOTS  = MAXPLAYERS,		// simulated humans and bots
	MAX_CLIENT_PEERS  = MAXPLAYERS,		// remote human connections, v1
	MAX_SESSION_PEERS = MAXPLAYERS + 1	// + a playerless authority process
};

typedef uint16_t PeerId;
typedef uint8_t  PlayerSlot;

enum class RuntimeRole : uint8_t
{
	Standalone,			// no socket: single player, and later offline deathmatch
	NetworkClient,
	ListenAuthority,	// rendered host: authority AND owns a local human slot
	DedicatedAuthority	// Phase D: authority, owns nothing
};

// What is driving a slot. Deliberately not "LocalHuman" and "RemoteHuman":
// those are perspective-dependent, and the same human is local on one machine
// and remote on every other. The canonical description is Human plus an owner
// peer, and each process works out local or remote by comparing that owner
// with its own peer.
enum class SlotKind : uint8_t
{
	Empty,
	Human,
	Bot
};

// The minimum set of phases the later milestones need to name. Recorded
// explicitly rather than inferred from whether a menu is open or a socket is
// blocked, because "the game is running" and "PlayLoop has been entered" stop
// being the same statement once an authority runs without a window.
enum class Lifecycle : uint8_t
{
	Boot,
	LobbyOpen,
	RosterLocked,
	LoadingMatch,
	ReadyBarrier,
	Running,
	TerminalPending,
	Results,
	ShuttingDown,
	FatalError
};

struct PlayerSlotInfo
{
	SlotKind kind = SlotKind::Empty;
	// Manifest-assigned, and bumped when a controller is replaced, so cached
	// per-controller work can never be claimed by its successor. Zero for the
	// initial controller.
	uint32_t controllerGeneration = 0;
	// Required for Human, absent for Bot: a bot has no socket and must never
	// appear in an address, readiness, acknowledgement or timeout array.
	std::optional<PeerId> ownerPeer;
	FString name;
	FName playerClass = NAME_None;
	// Bot only. Corridor 7 derives team from the player class, so no team is
	// stored here: a second, independently settable copy could contradict the
	// rule that actually decides who may shoot whom.
	std::optional<uint32_t> botProfile;
	std::optional<uint64_t> controllerSeed;
};

struct PeerInfo
{
	PeerId id = 0;
	bool   authority = false;
	// Absent for a dedicated authority, which is a peer that owns no slot.
	std::optional<PlayerSlot> humanSlot;
};

struct State
{
	RuntimeRole role = RuntimeRole::Standalone;
	Lifecycle   lifecycle = Lifecycle::Boot;

	PeerId authorityPeer = 0;
	std::optional<PeerId> localPeer;
	// The slot this process's human occupies, and the slot it draws from. Not
	// the same question, and neither is answered by a number that indexes
	// players[] unconditionally: a dedicated authority answers "no" to both,
	// and must be able to say so without a sentinel that somebody later uses
	// as an index anyway.
	std::optional<PlayerSlot> localHumanSlot;
	std::optional<PlayerSlot> localViewSlot;

	PlayerSlotInfo slots[MAX_PLAYER_SLOTS];
	// Occupied slots are contiguous in version 1: [0, activeSlots) are in the
	// match and the rest are Empty. That is what lets every existing
	// "for(i = 0; i < count; ++i)" loop over players become a slot loop
	// without also becoming a different loop.
	unsigned int activeSlots = 0;
	// Positions the session has set aside that no controller has taken yet: a
	// lobby row reading "open", or the slot a bot will occupy once there is a
	// bot to put in it. Reserved slots are NOT in the match. They spawn
	// nothing, score nothing, and nothing waits on a socket for them -- which
	// is the whole point of being able to name a position before a controller
	// for it exists. [activeSlots, reservedSlots) are Empty.
	unsigned int reservedSlots = 0;

	PeerInfo     peers[MAX_SESSION_PEERS];
	unsigned int peerCount = 0;

	void Reset();
	// Single player: one standalone peer, one human slot, drawn from that
	// slot. The session is never empty, so a loop that asks it how many slots
	// there are never gets zero by accident.
	void SetStandaloneSinglePlayer();
};

// The session this process is in.
State &Current();

// --- the four identities, asked one at a time --------------------------------

RuntimeRole Role();
bool IsAuthority();
bool IsDedicated();
// A socket is open and other processes are simulating the same world. Distinct
// from Net::Deathmatch(), which is a question about rules.
bool IsNetworked();

unsigned int ActiveSlotCount();
// Active plus set-aside. Never a loop bound over players[]: nothing in
// [ActiveSlotCount(), ReservedSlotCount()) has a pawn.
unsigned int ReservedSlotCount();
// Set aside n positions beyond the ones in the match. Refuses to reserve fewer
// than are already active.
bool ReserveSlots(unsigned int n);

// Appends a slot the authority owns and no socket corresponds to. This is the
// shape a bot occupies in Phase B; in Phase S the only thing that occupies it
// is a scripted command tape, which is not an AI and is not a step toward one.
// The kind is Bot because what the roster needs to know is "authority-owned,
// no peer" -- what is actually driving it is the command layer's business.
// Returns the new slot, or an out-of-range value if there is no room.
unsigned int AddAuthoritySlot(uint32_t profile, uint64_t seed);
bool SlotActive(PlayerSlot slot);
SlotKind KindOf(PlayerSlot slot);
bool SlotIsBot(PlayerSlot slot);
unsigned int PeerCount();

bool HasLocalPlayer();
std::optional<PlayerSlot> LocalPlayerSlot();
bool HasLocalView();
std::optional<PlayerSlot> LocalViewSlot();
bool IsLocalViewSlot(PlayerSlot slot);

// --- what kind of game this is, as opposed to how it is transported ----------
//
// Every one of these was answered by "is Net::InitVars.mode something other
// than MODE_SinglePlayer" -- a question about sockets. That works only while a
// socket is evidence of an opponent. It stops working in both directions at
// once: an offline deathmatch has opponents and no socket, and a host sitting
// alone has a socket and no opponent.
//
// So gameplay asks what kind of match this is, and transport code asks whether
// a socket is open, and the two questions stop being the same one.

// The bridge while networked cooperative play still exists: a co-op netgame is
// multiplayer gameplay without being a deathmatch, and an offline deathmatch is
// multiplayer gameplay without a socket. Deliberately the only predicate here
// that consults the transport, and the only one that should.
bool IsMultiplayerGameplay();

bool IsDeathmatch();
// Death puts you back in the arena rather than restarting the level.
bool AllowsRespawn();
// A picked-up item is left behind for whoever else needs it.
bool ItemsStayInWorld();
bool RespawnItems();
bool NoMonsters();
// More than one slot is being simulated. Distinct from IsMultiplayerGameplay():
// a host waiting alone is multiplayer by rules and alone in the world.
bool HasMultiplePlayers();
bool AllowsSaving();
bool TracksHighScores();
// Nothing outside this process is simulating, so stopping the world is a local
// decision and harms nobody.
bool CanPauseLocally();
// Leaving or restarting does not strand anyone else.
bool CanLeaveSessionUnilaterally();

// --- invariants --------------------------------------------------------------

// The sixteen rules in the plan's section 8.2, checked as one function so that
// there is exactly one place that knows them. Returns false and fills `why`
// with the first rule broken. Called by the self-test, by the debug assertion
// below, and by anything that has just built a roster.
bool Validate(const State &state, FString *why);

// Debug builds only: fails loudly rather than playing on with a roster that
// cannot be true.
void AssertValid(const State &state);

// --- adoption ----------------------------------------------------------------

// Builds the session from the legacy Net::InitVars/ConsolePlayer state once a
// netgame has been established. This is the adapter: version 1 still keeps the
// old variables as the transport's own working state, and this is where their
// meaning is written down. Later milestones move the truth here and delete the
// adapter, not the other way round.
void AdoptLegacyNetState();

// Records the classes chosen during the start-of-game exchange. The roster is
// locked at this point in version 1 -- no slot is added, removed or reassigned
// while a match runs.
void AdoptLegacyRoster(const FName (&playerClassNames)[MAXPLAYERS]);

// --- self-test ---------------------------------------------------------------

// Constructs sessions the running game cannot yet produce -- an authority with
// no player slots, a slot 0 owned by somebody who is not the authority -- and
// checks that the model describes them and that a corrupted roster is caught.
// Needs no game data and no window; --sessiontest.
int SelfTest();

}

#endif
