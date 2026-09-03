/*
** g_session.cpp
**
** See g_session.h for what this separates and why.
*/

#include <string.h>

#include "g_session.h"
#include "wl_net.h"
#include "wl_play.h"
#include "wl_main.h"

namespace Session {

// Built on first use rather than by a file-scope constructor. Something has to
// guarantee that the very first code to ask how many player slots there are
// gets 1 and not 0, and static initialization order across translation units is
// not a thing to bet a player count on -- a loop that runs zero times because
// the session had not been constructed yet would be a very quiet bug.
static State MakeStandaloneSinglePlayer()
{
	State s;
	s.SetStandaloneSinglePlayer();
	return s;
}

static State &Live()
{
	static State live = MakeStandaloneSinglePlayer();
	return live;
}

State &Current() { return Live(); }

void State::Reset()
{
	role = RuntimeRole::Standalone;
	lifecycle = Lifecycle::Boot;
	authorityPeer = 0;
	localPeer.reset();
	localHumanSlot.reset();
	localViewSlot.reset();
	for(unsigned int i = 0;i < MAX_PLAYER_SLOTS;++i)
		slots[i] = PlayerSlotInfo();
	activeSlots = 0;
	reservedSlots = 0;
	for(unsigned int i = 0;i < MAX_SESSION_PEERS;++i)
		peers[i] = PeerInfo();
	peerCount = 0;
}

void State::SetStandaloneSinglePlayer()
{
	Reset();
	role = RuntimeRole::Standalone;
	lifecycle = Lifecycle::Running;

	peers[0].id = 0;
	peers[0].authority = true;
	peers[0].humanSlot = (PlayerSlot)0;
	peerCount = 1;

	authorityPeer = 0;
	localPeer = (PeerId)0;

	slots[0].kind = SlotKind::Human;
	slots[0].ownerPeer = (PeerId)0;
	activeSlots = 1;
	reservedSlots = 1;

	localHumanSlot = (PlayerSlot)0;
	localViewSlot = (PlayerSlot)0;
}

// --- the four identities ------------------------------------------------------

RuntimeRole Role() { return Live().role; }

bool IsAuthority()
{
	return Live().role == RuntimeRole::Standalone ||
		Live().role == RuntimeRole::ListenAuthority ||
		Live().role == RuntimeRole::DedicatedAuthority;
}

bool IsDedicated() { return Live().role == RuntimeRole::DedicatedAuthority; }

bool IsNetworked()
{
	return Live().role == RuntimeRole::NetworkClient ||
		Live().role == RuntimeRole::ListenAuthority ||
		Live().role == RuntimeRole::DedicatedAuthority;
}

unsigned int ActiveSlotCount() { return Live().activeSlots; }

unsigned int ReservedSlotCount() { return Live().reservedSlots; }

unsigned int AddAuthoritySlot(uint32_t profile, uint64_t seed)
{
	State &s = Live();
	if(s.activeSlots >= MAX_PLAYER_SLOTS)
		return MAX_PLAYER_SLOTS;

	const unsigned int slot = s.activeSlots;
	s.slots[slot] = PlayerSlotInfo();
	s.slots[slot].kind = SlotKind::Bot;
	s.slots[slot].botProfile = profile;
	s.slots[slot].controllerSeed = seed;
	s.slots[slot].name.Format("Slot %u", slot + 1);
	s.activeSlots = slot + 1;
	if(s.reservedSlots < s.activeSlots)
		s.reservedSlots = s.activeSlots;
	AssertValid(s);
	return slot;
}

bool ReserveSlots(unsigned int n)
{
	if(n < Live().activeSlots || n > MAX_PLAYER_SLOTS)
		return false;
	Live().reservedSlots = n;
	AssertValid(Live());
	return true;
}

bool SlotActive(PlayerSlot slot)
{
	return slot < Live().activeSlots &&
		Live().slots[slot].kind != SlotKind::Empty;
}

SlotKind KindOf(PlayerSlot slot)
{
	if(slot >= MAX_PLAYER_SLOTS)
		return SlotKind::Empty;
	return Live().slots[slot].kind;
}

bool SlotIsBot(PlayerSlot slot) { return KindOf(slot) == SlotKind::Bot; }

unsigned int PeerCount() { return Live().peerCount; }

bool HasLocalPlayer() { return Live().localHumanSlot.has_value(); }
std::optional<PlayerSlot> LocalPlayerSlot() { return Live().localHumanSlot; }
bool HasLocalView() { return Live().localViewSlot.has_value(); }
std::optional<PlayerSlot> LocalViewSlot() { return Live().localViewSlot; }

bool IsLocalViewSlot(PlayerSlot slot)
{
	return Live().localViewSlot.has_value() &&
		*Live().localViewSlot == slot;
}

// --- what kind of game this is -------------------------------------------------

bool IsDeathmatch() { return Net::Deathmatch(); }

bool HasMultiplePlayers() { return ActiveSlotCount() > 1; }

// The one predicate here allowed to consult the transport, and it does so
// deliberately. While cooperative play over the wire still exists there is no
// way to answer "do multiplayer rules apply" from the rules alone: a co-op
// netgame is not a deathmatch and is still multiplayer. Asking whether a socket
// is open is exactly right for that case and exactly wrong for an offline
// deathmatch, so both are asked, once, here.
//
// It is also what keeps this milestone behavior-preserving: every site
// converted below previously read the socket question directly, and a host
// sitting alone in a one-player netgame still answers the same way it always
// did.
bool IsMultiplayerGameplay()
{
	return Net::IsNetworked() || IsDeathmatch();
}

bool AllowsRespawn()     { return IsMultiplayerGameplay(); }
bool ItemsStayInWorld()  { return IsMultiplayerGameplay(); }
bool RespawnItems()      { return Net::RespawnItems(); }
bool NoMonsters()        { return Net::NoMonsters(); }

// Saving and high scores belong to the single-player campaign. Multiplayer
// saves have never been supported, and an offline deathmatch is not a campaign
// to record a score for -- see the plan's section 19.3.
bool AllowsSaving()      { return !IsMultiplayerGameplay(); }
bool TracksHighScores()  { return !IsMultiplayerGameplay(); }

bool CanPauseLocally()   { return !Net::IsNetworked(); }
bool CanLeaveSessionUnilaterally() { return !Net::IsNetworked(); }

// --- invariants ---------------------------------------------------------------

static const PeerInfo *FindPeer(const State &state, PeerId id)
{
	for(unsigned int i = 0;i < state.peerCount;++i)
	{
		if(state.peers[i].id == id)
			return &state.peers[i];
	}
	return NULL;
}

// The data half of the plan's section 8.2. Rules 8, 9, 11, 12, 13 and 15 are
// about what code may do -- a peer id used as a player index, a client
// submitting somebody else's command -- and no amount of looking at a struct
// will catch them; they are review and test rules, and are listed in the plan
// rather than pretended at here.
bool Validate(const State &state, FString *why)
{
#define FAIL(...) do { if(why != NULL) why->Format(__VA_ARGS__); return false; } while(0)

	// 10. Each capacity bounds its own array and nothing else.
	if(state.activeSlots > MAX_PLAYER_SLOTS)
		FAIL("activeSlots %u exceeds MAX_PLAYER_SLOTS %u",
			state.activeSlots, (unsigned)MAX_PLAYER_SLOTS);
	if(state.peerCount > MAX_SESSION_PEERS)
		FAIL("peerCount %u exceeds MAX_SESSION_PEERS %u",
			state.peerCount, (unsigned)MAX_SESSION_PEERS);
	if(state.reservedSlots > MAX_PLAYER_SLOTS)
		FAIL("reservedSlots %u exceeds MAX_PLAYER_SLOTS %u",
			state.reservedSlots, (unsigned)MAX_PLAYER_SLOTS);
	if(state.reservedSlots < state.activeSlots)
		FAIL("%u slots are in the match but only %u are reserved",
			state.activeSlots, state.reservedSlots);

	unsigned int clientPeers = 0;
	unsigned int authorities = 0;
	for(unsigned int i = 0;i < state.peerCount;++i)
	{
		const PeerInfo &peer = state.peers[i];
		if(peer.authority)
			++authorities;
		else
			++clientPeers;

		for(unsigned int j = i + 1;j < state.peerCount;++j)
		{
			if(state.peers[j].id == peer.id)
				FAIL("peer id %u appears twice", (unsigned)peer.id);
		}

		// 5. One human slot per peer in version 1.
		if(peer.humanSlot.has_value())
		{
			for(unsigned int j = i + 1;j < state.peerCount;++j)
			{
				if(state.peers[j].humanSlot == peer.humanSlot)
					FAIL("peers %u and %u both own slot %u",
						(unsigned)peer.id, (unsigned)state.peers[j].id,
						(unsigned)*peer.humanSlot);
			}
			if(*peer.humanSlot >= state.activeSlots)
				FAIL("peer %u owns slot %u, which is not in the match",
					(unsigned)peer.id, (unsigned)*peer.humanSlot);
			const PlayerSlotInfo &owned = state.slots[*peer.humanSlot];
			if(owned.kind != SlotKind::Human)
				FAIL("peer %u owns slot %u, which is not a human slot",
					(unsigned)peer.id, (unsigned)*peer.humanSlot);
			if(owned.ownerPeer != peer.id)
				FAIL("peer %u claims slot %u but the slot names another owner",
					(unsigned)peer.id, (unsigned)*peer.humanSlot);
		}
	}
	if(clientPeers > MAX_CLIENT_PEERS)
		FAIL("%u client peers exceeds MAX_CLIENT_PEERS %u",
			clientPeers, (unsigned)MAX_CLIENT_PEERS);

	// 1. Exactly one authority.
	if(authorities != 1)
		FAIL("%u peers claim to be the authority, need exactly 1", authorities);
	const PeerInfo *authority = FindPeer(state, state.authorityPeer);
	if(authority == NULL)
		FAIL("authorityPeer %u is not a peer in this session",
			(unsigned)state.authorityPeer);
	if(!authority->authority)
		FAIL("authorityPeer %u is not the peer marked as authority",
			(unsigned)state.authorityPeer);

	for(unsigned int slot = 0;slot < MAX_PLAYER_SLOTS;++slot)
	{
		const PlayerSlotInfo &info = state.slots[slot];
		const bool inMatch = slot < state.activeSlots;

		// Occupied slots are contiguous in version 1, so an empty slot below
		// the active count is a hole that every "for slot in [0, count)" loop
		// in the engine would walk straight into.
		if(inMatch && info.kind == SlotKind::Empty)
			FAIL("slot %u is empty but inside the active range", slot);
		// 7. Nothing above the active count owns anything -- reserved or not.
		// A set-aside position is a name for a place, not a participant.
		if(!inMatch)
		{
			if(info.kind != SlotKind::Empty)
				FAIL("slot %u is occupied but outside the active range", slot);
			if(info.ownerPeer.has_value())
				FAIL("empty slot %u has an owner", slot);
			if(info.botProfile.has_value() || info.controllerSeed.has_value())
				FAIL("empty slot %u carries controller data", slot);
			continue;
		}

		if(info.kind == SlotKind::Human)
		{
			// 4. Exactly one owner, and it exists.
			if(!info.ownerPeer.has_value())
				FAIL("human slot %u has no owner peer", slot);
			if(FindPeer(state, *info.ownerPeer) == NULL)
				FAIL("human slot %u is owned by peer %u, which is not here",
					slot, (unsigned)*info.ownerPeer);
			if(info.botProfile.has_value() || info.controllerSeed.has_value())
				FAIL("human slot %u carries bot controller data", slot);
		}
		else if(info.kind == SlotKind::Bot)
		{
			// 6. A bot owns no socket, and must never end up in an address,
			// readiness, acknowledgement or timeout array by way of one.
			if(info.ownerPeer.has_value())
				FAIL("bot slot %u has an owner peer", slot);
			if(!info.botProfile.has_value())
				FAIL("bot slot %u has no profile", slot);
			if(!info.controllerSeed.has_value())
				FAIL("bot slot %u has no controller seed", slot);
		}
	}

	// 2 and 14. The authority process is not a player.
	if(state.role == RuntimeRole::DedicatedAuthority)
	{
		if(authority->humanSlot.has_value())
			FAIL("a dedicated authority owns human slot %u",
				(unsigned)*authority->humanSlot);
		if(state.localHumanSlot.has_value())
			FAIL("a dedicated authority has a local player slot");
		if(state.localViewSlot.has_value())
			FAIL("a dedicated authority has a local view");
	}

	// 3. A local human slot belongs to this process's own peer.
	if(state.localHumanSlot.has_value())
	{
		const PlayerSlot slot = *state.localHumanSlot;
		if(slot >= state.activeSlots)
			FAIL("local human slot %u is not in the match", (unsigned)slot);
		if(state.slots[slot].kind != SlotKind::Human)
			FAIL("local human slot %u is not a human slot", (unsigned)slot);
		if(!state.localPeer.has_value())
			FAIL("a local human slot with no local peer to own it");
		if(state.slots[slot].ownerPeer != *state.localPeer)
			FAIL("local human slot %u is owned by another peer", (unsigned)slot);
	}
	if(state.localViewSlot.has_value() &&
		*state.localViewSlot >= state.activeSlots)
		FAIL("local view slot %u is not in the match",
			(unsigned)*state.localViewSlot);
	if(state.localPeer.has_value() &&
		FindPeer(state, *state.localPeer) == NULL)
		FAIL("local peer %u is not in this session", (unsigned)*state.localPeer);

	return true;
#undef FAIL
}

void AssertValid(const State &state)
{
#ifndef NDEBUG
	FString why;
	if(!Validate(state, &why))
		I_FatalError("Session roster is impossible: %s", why.GetChars());
#else
	(void)state;
#endif
}

// --- adoption -----------------------------------------------------------------

void AdoptLegacyNetState()
{
	State &s = Live();
	s.Reset();

	if(Net::InitVars.mode == Net::MODE_SinglePlayer)
	{
		s.SetStandaloneSinglePlayer();
		AssertValid(s);
		return;
	}

	const unsigned int count = Net::InitVars.numPlayers;
	s.role = (Net::InitVars.mode == Net::MODE_Host)
		? RuntimeRole::ListenAuthority : RuntimeRole::NetworkClient;
	s.lifecycle = Lifecycle::RosterLocked;

	// One peer per slot, because that is exactly what the legacy protocol can
	// express: the sender's address is the slot. The whole point of the split
	// is that later milestones stop being able to say this -- a bot slot with
	// no peer, an authority peer with no slot -- so nothing outside this
	// function may assume the two counts match.
	s.peerCount = count;
	for(unsigned int i = 0;i < count;++i)
	{
		s.peers[i].id = (PeerId)i;
		s.peers[i].authority = (i == 0);	// legacy: #define Arbiter 0
		s.peers[i].humanSlot = (PlayerSlot)i;

		s.slots[i].kind = SlotKind::Human;
		s.slots[i].ownerPeer = (PeerId)i;
		s.slots[i].name.Format("Player %u", i + 1);
	}
	s.activeSlots = count;
	s.reservedSlots = count;

	s.authorityPeer = 0;
	s.localPeer = (PeerId)ConsolePlayer;
	s.localHumanSlot = (PlayerSlot)ConsolePlayer;
	s.localViewSlot = (PlayerSlot)ConsolePlayer;

	AssertValid(s);
}

void AdoptLegacyRoster(const FName (&playerClassNames)[MAXPLAYERS])
{
	State &s = Live();

	// While the adapter exists there are two counts, and they must agree. The
	// start-of-game exchange is the last moment before a match where anything
	// could have changed one without the other, so it is where drift is worth
	// catching: two machines quietly iterating different numbers of players is
	// a desync that would be blamed on the netcode for a week.
#ifndef NDEBUG
	// Peers against *human* slots, not against every slot: a slot the
	// authority owns has no peer by definition, and counting it here would
	// make the split this milestone exists to create look like a fault.
	unsigned int humans = 0;
	for(unsigned int i = 0;i < s.activeSlots;++i)
	{
		if(s.slots[i].kind == SlotKind::Human)
			++humans;
	}
	if(Net::InitVars.mode != Net::MODE_SinglePlayer &&
		Net::InitVars.numPlayers != humans)
	{
		I_FatalError("Session has %u human slots but the transport has %u peers",
			humans, (unsigned)Net::InitVars.numPlayers);
	}
#endif

	for(unsigned int i = 0;i < s.activeSlots;++i)
		s.slots[i].playerClass = playerClassNames[i];
	s.lifecycle = Lifecycle::Running;
	AssertValid(s);
}

// --- self-test ----------------------------------------------------------------
//
// Builds sessions the running game cannot yet produce and checks the model
// describes them: an authority that owns no player, a slot 0 owned by somebody
// who is not the authority, a roster with more slots than peers and one with
// more peers than slots. Then it corrupts a roster in every way the invariants
// forbid and checks each one is caught.
//
// Nothing in here indexes players[], reads ConsolePlayer, or opens a socket.
// That is the point: if a dedicated authority can only be described by code
// that touches a player array, it cannot exist, and finding that out in Phase D
// would be finding it out far too late.

namespace {

unsigned int g_checks = 0;
unsigned int g_failures = 0;

void Check(bool ok, const char *what)
{
	++g_checks;
	if(ok)
		return;
	++g_failures;
	Printf("  FAIL %s\n", what);
}

// A roster that breaks one rule must be refused, and the reason must name it.
void CheckRefused(const State &state, const char *what)
{
	++g_checks;
	FString why;
	if(Validate(state, &why))
	{
		++g_failures;
		Printf("  FAIL accepted a roster that %s\n", what);
	}
}

void CheckAccepted(const State &state, const char *what)
{
	++g_checks;
	FString why;
	if(!Validate(state, &why))
	{
		++g_failures;
		Printf("  FAIL rejected %s: %s\n", what, why.GetChars());
	}
}

// A listen host: authority, and holding a player of its own.
State ListenAuthority(unsigned int players)
{
	State s;
	s.Reset();
	s.role = RuntimeRole::ListenAuthority;
	s.lifecycle = Lifecycle::Running;
	s.peerCount = players;
	for(unsigned int i = 0;i < players;++i)
	{
		s.peers[i].id = (PeerId)i;
		s.peers[i].authority = (i == 0);
		s.peers[i].humanSlot = (PlayerSlot)i;
		s.slots[i].kind = SlotKind::Human;
		s.slots[i].ownerPeer = (PeerId)i;
	}
	s.activeSlots = players;
	s.reservedSlots = players;
	s.authorityPeer = 0;
	s.localPeer = (PeerId)0;
	s.localHumanSlot = (PlayerSlot)0;
	s.localViewSlot = (PlayerSlot)0;
	return s;
}

// The shape this whole milestone exists to make expressible: an authority
// process that is a peer, owns the session, and is not a player. Its peer id
// is deliberately the highest rather than zero, so that nothing can quietly
// keep working because the authority happened to be peer 0 again.
State DedicatedAuthority(unsigned int humans, unsigned int bots)
{
	State s;
	s.Reset();
	s.role = RuntimeRole::DedicatedAuthority;
	s.lifecycle = Lifecycle::Running;

	const PeerId serverPeer = (PeerId)(humans + 1);
	for(unsigned int i = 0;i < humans;++i)
	{
		s.peers[i].id = (PeerId)i;
		s.peers[i].authority = false;
		s.peers[i].humanSlot = (PlayerSlot)i;
		s.slots[i].kind = SlotKind::Human;
		s.slots[i].ownerPeer = (PeerId)i;
	}
	for(unsigned int i = 0;i < bots;++i)
	{
		PlayerSlotInfo &slot = s.slots[humans + i];
		slot.kind = SlotKind::Bot;
		slot.botProfile = (uint32_t)1;
		slot.controllerSeed = (uint64_t)(0x5eed0000u + i);
	}
	s.activeSlots = humans + bots;
	s.reservedSlots = humans + bots;

	s.peers[humans].id = serverPeer;
	s.peers[humans].authority = true;
	// and no humanSlot: this is the line the old model could not write down.
	s.peerCount = humans + 1;
	s.authorityPeer = serverPeer;
	s.localPeer = serverPeer;
	// No local human slot and no local view.
	return s;
}

}

int SelfTest()
{
	g_checks = g_failures = 0;

	Printf("Session model self-test\n");

	Printf("\nThe shapes that exist today\n");
	{
		State s;
		s.SetStandaloneSinglePlayer();
		CheckAccepted(s, "single player");
		Live() = s;
		Check(HasLocalPlayer(), "single player has a local player");
		Check(HasLocalView(), "single player has a local view");
		Check(ActiveSlotCount() == 1, "single player has one slot");
		Check(PeerCount() == 1, "single player has one peer");
		Check(IsAuthority(), "single player is its own authority");
		Check(!IsNetworked(), "single player is not networked");
	}
	{
		State s = ListenAuthority(2);
		CheckAccepted(s, "a listen host with two players");
		Live() = s;
		Check(IsAuthority(), "a listen host is the authority");
		Check(IsNetworked(), "a listen host is networked");
		Check(LocalPlayerSlot() == std::optional<PlayerSlot>(0),
			"a listen host plays from slot 0");
		Check(IsLocalViewSlot(0) && !IsLocalViewSlot(1),
			"a listen host draws only its own slot");
	}
	{
		State s = ListenAuthority(2);
		// The same session seen from the other machine.
		s.role = RuntimeRole::NetworkClient;
		s.localPeer = (PeerId)1;
		s.localHumanSlot = (PlayerSlot)1;
		s.localViewSlot = (PlayerSlot)1;
		CheckAccepted(s, "a client in slot 1");
		Live() = s;
		Check(!IsAuthority(), "a client is not the authority");
		Check(IsNetworked(), "a client is networked");
	}

	Printf("\nThe shapes the engine cannot produce yet\n");
	{
		// The exit-gate case. Eleven players, none of them this process.
		State s = DedicatedAuthority(MAX_PLAYER_SLOTS, 0);
		CheckAccepted(s, "an authority with eleven players and no player of its own");
		Live() = s;
		Check(!HasLocalPlayer(), "a dedicated authority has no local player");
		Check(!HasLocalView(), "a dedicated authority has no local view");
		Check(!LocalPlayerSlot().has_value(),
			"a dedicated authority answers 'no slot', not 'slot zero'");
		Check(ActiveSlotCount() == MAX_PLAYER_SLOTS,
			"an eleven-slot server hosts eleven players");
		Check(PeerCount() == MAX_PLAYER_SLOTS + 1,
			"and is a twelfth process, not the eleventh pawn");
		Check(IsAuthority() && IsDedicated(),
			"a dedicated authority is the authority");

		// Slot 0 belongs to a remote human, and the authority is somebody else
		// entirely. Both halves of "authority is a role, not a slot number".
		Check(KindOf(0) == SlotKind::Human, "slot 0 is an ordinary human slot");
		Check(s.slots[0].ownerPeer == std::optional<PeerId>(0),
			"slot 0 is owned by a peer");
		Check(s.slots[0].ownerPeer != std::optional<PeerId>(s.authorityPeer),
			"and that peer is not the authority");
	}
	{
		// More slots than peers: bots occupy slots and own no socket.
		State s = DedicatedAuthority(2, 4);
		CheckAccepted(s, "a server running two humans and four bots");
		Live() = s;
		Check(ActiveSlotCount() == 6, "six slots are in the match");
		Check(PeerCount() == 3, "but only three processes are");
		Check(PeerCount() < ActiveSlotCount(),
			"peer count is not bounded below by slot count");
		Check(SlotIsBot(2) && SlotIsBot(5), "the bot slots are bots");
		Check(!s.slots[2].ownerPeer.has_value(),
			"a bot slot owns no socket");
	}
	{
		// Fewer slots than peers, the other way the counts come apart.
		State s = DedicatedAuthority(1, 0);
		CheckAccepted(s, "a server with one player waiting for more");
		Live() = s;
		Check(PeerCount() > ActiveSlotCount(),
			"peer count is not bounded above by slot count either");
	}

	Printf("\nThe three capacities, bounded independently\n");
	{
		Check(MAX_PLAYER_SLOTS == MAXPLAYERS, "slots are bounded by MAXPLAYERS");
		Check(MAX_SESSION_PEERS > MAX_CLIENT_PEERS,
			"a session holds one more process than it holds clients");
		Check(MAX_SESSION_PEERS > MAX_PLAYER_SLOTS,
			"a session holds one more process than it holds players");

		State s = DedicatedAuthority(MAX_PLAYER_SLOTS, 0);
		CheckAccepted(s, "a full house");

		State tooManySlots = s;
		tooManySlots.activeSlots = MAX_PLAYER_SLOTS + 1;
		CheckRefused(tooManySlots, "claims more slots than the engine has");

		State tooManyPeers = s;
		tooManyPeers.peerCount = MAX_SESSION_PEERS + 1;
		CheckRefused(tooManyPeers, "claims more peers than a session holds");
	}

	Printf("\nRosters that cannot be true\n");
	{
		const State good = DedicatedAuthority(3, 1);
		CheckAccepted(good, "the roster the corruptions start from");

		State s = good;
		s.peers[0].authority = true;
		CheckRefused(s, "has two authorities");

		s = good;
		for(unsigned int i = 0;i < s.peerCount;++i)
			s.peers[i].authority = false;
		CheckRefused(s, "has no authority");

		s = good;
		s.peers[s.peerCount - 1].humanSlot = (PlayerSlot)0;
		CheckRefused(s, "gives the dedicated authority a player slot");

		s = good;
		s.localHumanSlot = (PlayerSlot)0;
		CheckRefused(s, "gives the dedicated authority a local player");

		s = good;
		s.localViewSlot = (PlayerSlot)0;
		CheckRefused(s, "gives the dedicated authority a camera");

		s = good;
		s.slots[0].ownerPeer.reset();
		CheckRefused(s, "leaves a human slot unowned");

		s = good;
		s.slots[0].ownerPeer = (PeerId)999;
		CheckRefused(s, "owns a human slot from a peer that is not here");

		s = good;
		s.peers[1].humanSlot = (PlayerSlot)0;
		CheckRefused(s, "lets two peers own one slot");

		s = good;
		s.peers[0].humanSlot = (PlayerSlot)1;
		CheckRefused(s, "has a peer and a slot disagreeing about who owns whom");

		s = good;
		s.slots[3].ownerPeer = (PeerId)0;
		CheckRefused(s, "gives a bot slot a socket");

		s = good;
		s.slots[3].botProfile.reset();
		CheckRefused(s, "has a bot with no profile");

		s = good;
		s.slots[3].controllerSeed.reset();
		CheckRefused(s, "has a bot with no seed");

		s = good;
		s.slots[1].kind = SlotKind::Empty;
		s.slots[1].ownerPeer.reset();
		CheckRefused(s, "leaves a hole in the middle of the roster");

		s = good;
		s.slots[s.activeSlots].kind = SlotKind::Human;
		CheckRefused(s, "occupies a slot outside the match");

		s = good;
		s.slots[s.activeSlots].ownerPeer = (PeerId)0;
		CheckRefused(s, "gives an empty slot an owner");

		s = good;
		s.authorityPeer = (PeerId)999;
		CheckRefused(s, "names an authority that is not a peer");

		s = good;
		s.localPeer = (PeerId)999;
		CheckRefused(s, "names a local peer that is not in the session");

		s = good;
		s.peers[1].id = s.peers[0].id;
		CheckRefused(s, "has the same peer twice");

		// And a listen host's own rules.
		const State listen = ListenAuthority(2);
		s = listen;
		s.localHumanSlot = (PlayerSlot)1;
		CheckRefused(s, "has a host playing a slot another peer owns");

		s = listen;
		s.localHumanSlot = (PlayerSlot)5;
		CheckRefused(s, "has a host playing a slot that is not in the match");
	}

	Printf("\nPositions held before a controller exists\n");
	{
		State s = ListenAuthority(2);
		s.reservedSlots = 4;
		CheckAccepted(s, "two players and two positions held open");
		Live() = s;
		Check(ActiveSlotCount() == 2, "two slots are in the match");
		Check(ReservedSlotCount() == 4, "four positions are spoken for");
		Check(KindOf(2) == SlotKind::Empty && KindOf(3) == SlotKind::Empty,
			"a held position has no controller");
		Check(!SlotActive(2), "and is not in the match");

		State bad = s;
		bad.reservedSlots = 1;
		CheckRefused(bad, "reserves fewer positions than it is playing");

		bad = s;
		bad.slots[2].kind = SlotKind::Human;
		bad.slots[2].ownerPeer = (PeerId)0;
		CheckRefused(bad, "puts a player in a position it only held open");

		bad = s;
		bad.reservedSlots = MAX_PLAYER_SLOTS + 1;
		CheckRefused(bad, "holds open more positions than the engine has");

		Live() = s;
		Check(!ReserveSlots(1), "refuses to unreserve a slot in play");
		Check(ReserveSlots(MAX_PLAYER_SLOTS), "reserves up to the maximum");
		Check(ReserveSlots(2), "and back down to what is in the match");
	}

	Printf("\nWhat kind of game this is, without asking about sockets\n");
	{
		// The rules predicates read Net::InitVars, so the truth table is built
		// by setting the same variables the game sets. Restored afterwards.
		const Net::Mode wasMode = Net::InitVars.mode;
		const Net::GameMode wasGame = Net::InitVars.gameMode;

		struct Row
		{
			const char *what;
			Net::Mode mode;
			Net::GameMode game;
			unsigned int slots;
			bool multiplayerRules, respawn, itemsStay, saving, highScores,
				pauseLocally, manyPlayers;
		};
		// The row that matters is the second: a deathmatch with no socket. It
		// answers "yes" to every rules question and "no" to every transport
		// one, which the old mode check could not express at all.
		static const Row rows[] = {
			{ "single player",        Net::MODE_SinglePlayer, Net::GM_Cooperative, 1,
			  false, false, false, true,  true,  true,  false },
			{ "offline deathmatch",   Net::MODE_SinglePlayer, Net::GM_Battle,      2,
			  true,  true,  true,  false, false, true,  true  },
			{ "networked co-op",      Net::MODE_Host,         Net::GM_Cooperative, 2,
			  true,  true,  true,  false, false, false, true  },
			{ "networked deathmatch", Net::MODE_Host,         Net::GM_Battle,      2,
			  true,  true,  true,  false, false, false, true  },
			{ "host waiting alone",   Net::MODE_Host,         Net::GM_Battle,      1,
			  true,  true,  true,  false, false, false, false },
		};

		for(unsigned int r = 0;r < sizeof(rows)/sizeof(rows[0]);++r)
		{
			const Row &row = rows[r];
			Net::InitVars.mode = row.mode;
			Net::InitVars.gameMode = row.game;
			State s = (row.mode == Net::MODE_SinglePlayer)
				? ListenAuthority(row.slots) : ListenAuthority(row.slots);
			s.role = (row.mode == Net::MODE_SinglePlayer)
				? RuntimeRole::Standalone : RuntimeRole::ListenAuthority;
			Live() = s;

			FString label;
#define ROW_CHECK(expr, name) 			label.Format("%s: %s", row.what, #name); 			Check((expr) == row.name, label.GetChars())
			ROW_CHECK(IsMultiplayerGameplay(), multiplayerRules);
			ROW_CHECK(AllowsRespawn(), respawn);
			ROW_CHECK(ItemsStayInWorld(), itemsStay);
			ROW_CHECK(AllowsSaving(), saving);
			ROW_CHECK(TracksHighScores(), highScores);
			ROW_CHECK(CanPauseLocally(), pauseLocally);
			ROW_CHECK(HasMultiplePlayers(), manyPlayers);
#undef ROW_CHECK
		}

		Net::InitVars.mode = wasMode;
		Net::InitVars.gameMode = wasGame;
	}

	// Leave the process as it was found, in case anything runs after this.
	Live().SetStandaloneSinglePlayer();

	Printf("\n%u checks, %u failures\n", g_checks, g_failures);
	if(g_failures == 0)
		Printf("PASS: authority, peer, slot and view are four separate things.\n");
	else
		Printf("FAIL: the session model does not hold.\n");
	return g_failures == 0 ? 0 : 1;
}

}
