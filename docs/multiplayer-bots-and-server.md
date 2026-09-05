# EC7Wolf multiplayer program: shared foundation, bots, and dedicated server

**Status:** implementation plan. Neither bots nor a dedicated server exist in
the source today.

**Scope:** one program covering three sequential projects that share a single
foundation — a session/roster/authority model that separates network peers from
player slots, then deathmatch bots, then a playerless headless server process.

**Source reviewed:** EC7Wolf `main` at `e897c6a`, 3 September 2026. The former
`multiplayer` branch is fully merged; all eight shipped multiplayer milestones
are described in [multiplayer.md](multiplayer.md).

**Lineage:** EC7Wolf forks ECWolf 1.4.2-9-g1bff92d, derived from Wolf4SDL with
substantial ZDoom-derived systems. EC7Wolf's own version remains `1.0-betaX`.

**Replaces:** the two separate planning documents `multiplayer-bots.md` and
`multiplayer-dedicated-server.md`. They were written independently, converged on
the same blocker from opposite directions, and disagreed about which project
should go first. This document resolves that, corrects the assumptions each made
about the other, and puts the work in one order.

---

## 0. How to read this document

Part I is the program: the decisions, the phase order and why it is this order,
what "done" means, and what the source actually looks like today. Read it before
anything else.

Parts II, III, and IV are the three projects, in execution order:

| Part | Phase | Delivers | Milestones |
| --- | --- | --- | --- |
| II | **S — shared foundation** | An engine in which authority, network peers, player slots, and the local view are four separate things | S1–S4 |
| III | **B — bots** | Deathmatch against fallible computer opponents, offline first | B1–B10 |
| IV | **D — dedicated server** | `ec7wolf-server`: a headless, zero-slot, authoritative process | D1–D12 |

Part V is program-wide material: risks, open decisions, execution protocol, and
provenance.

Each milestone ends in a runnable proof and an automated gate. Do not combine
milestones into one unreviewable patch merely because an agent can edit quickly.

---

# Part I — The program

## 1. Executive decisions

These are the decisions the rest of the document is built on. Changing one is a
design change, not an implementation detail.

### 1.1 Identity and authority

1. **Separate four identities.** Process/runtime role, network peer, session
   authority, and player slot are four different things. Today they are one
   thing. Every later decision depends on this one.

2. **Authority is a role, not a slot.** `IsArbiter()` must stop meaning
   `ConsolePlayer == 0`. A listen host is authority *and* owns a human slot; a
   dedicated server is authority and owns none; a client is neither.

3. **A bot occupies an ordinary player slot.** `players[slot]`, the configured
   `APlayerPawn` class, normal spawn selection, and normal frag accounting, with
   no bot-specific pawn class.

4. **The dedicated server occupies no slot at all.** A hidden host process, an
   invisible pawn, a spectator pawn, or a forced bot in slot 0 is not the
   feature. Such a mode may be a useful diagnostic, but it is named "headless
   listen host," never "dedicated server."

5. **A server configured for eleven slots hosts eleven players.** Its own
   process is a twelfth session participant, not the eleventh pawn. Peer count
   is not bounded by slot count in either direction.

6. **Bots run on the authority, whichever kind it is.** In a listen match the
   listen authority runs them; with a dedicated server the server runs them.
   Bot slots produce commands but never enter socket, acknowledgment,
   readiness, or timeout accounting.

### 1.2 Commands and simulation

7. **Every controller produces only ordinary player commands.** Movement and
   yaw through `controlx`/`controly`/`controlstrafe`; actions through the same
   button fields a human uses. No controller — bot, server, or human — writes
   actor coordinates, angle, or pitch directly. This rule currently has one
   human violation, in `PollMouseMove`; §5.6 and milestone S1 close it.

8. **The command frame gains a slot dimension.** The current wire format has no
   slot field: the sender's UDP address *is* the slot. A bot has no address and
   a server owns no slot, so neither project can express a command until this
   changes. This is the single technical fact that makes Phase S shared.

9. **Preserve deterministic lockstep.** Every participant simulates the whole
   world from an identical canonical command frame. No state replication, no
   client prediction, no server reconciliation in this program.

10. **Extract one presentation-independent simulation tic.** Both the rendered
    client loop and the dedicated loop call it with an already-finalized
    canonical command frame. Rendering, input sampling, audio output, menus,
    interpolation, and frame pacing stay outside it.

11. **Difficulty never changes the rules.** Bot skill may change perception
    quality, reaction time, aim stability, movement competence, and tactical
    judgment. It may not change health, damage, ammunition, inventory, collision
    radius, movement speed, pickup rights, respawn timing, or weapon timing.

### 1.3 Product and process

12. **Bots ship before the dedicated server.** See §2 for the argument. The
    short form: bots need no network, deliver value to a solo player, and carry
    design risk that wants many playtest iterations; the server needs no bots
    until its final milestone and carries engineering risk that wants a stable
    surface underneath it.

13. **Phase S changes no wire format beyond safety fixes.** The protocol
    rewrite belongs to Phase D. Phase S delivers the in-process model and an
    offline deathmatch session; that is enough for the entire first bot slice.

14. **The first AI is a small, explicit, inspectable C++ controller** — a
    hierarchical state machine plus utility scoring. No scripting VM, machine
    learning, behavior-tree framework, or imported Doom/Quake bot source.

15. **Ship a distinct `ec7wolf-server` executable.** A `--dedicated` path in
    the ordinary executable is a useful development stage but does not satisfy
    the final binary and dependency requirements.

16. **Use a star topology for the server.** Each client exchanges gameplay
    traffic only with the server. This simplifies NAT, hides peer addresses,
    creates one place for sequencing and disconnect decisions, and scales
    better than the current full mesh.

17. **Introduce a versioned protocol with an explicit codec in Phase D.** Do
    not extend the current packed C++ packet structs and raw-cast untrusted UDP
    bytes. Every field is length-checked before conversion or allocation.

18. **Direct-IP play is the operational target.** A master server, accounts,
    matchmaking, relay network, mod download, and NAT traversal are independent
    projects.

19. **Administration is local first.** Stdin/terminal and OS service control
    suffice. Do not expose existing debug packets as RCON.

20. **Never redistribute Corridor 7's commercial files.** Packages may contain
    the EC7Wolf binaries, `ec7wolf.pk3`, templates, and freely distributable
    libraries. Operators supply their own game data.

21. **GZDoom and Zandronum are design references, not code libraries.** Any
    copied code would need explicit file/commit provenance and a license
    review. Implement cleanly in EC7Wolf.

---

## 2. Phase order, and why it is this order

### 2.1 The two projects meet at one line of code

In [`src/wl_net.cpp`](../src/wl_net.cpp):

```c
#define Arbiter 0
bool IsArbiter() { return ConsolePlayer == Arbiter; }
```

The authority is hardcoded as *player slot 0 on this machine*. Alongside it,
`TicCmdPacket` carries `controlx`, `controly`, `controlstrafe`,
`buttonstate[]`, and `buttonheld[]` — and no slot number. The slot is implied by
the sender's address. One address, one player, forever.

From that, both projects are blocked at the same place for mirror-image reasons:

- a **bot** has no address, so it cannot express a command;
- a **server** has no player, so it cannot be the arbiter.

`Net::InitVars.numPlayers` is simultaneously the peer count, the slot count, the
handshake count, the per-tic wait count, the `Client[]` index bound, and the
spawn count. Untangling it is one refactor, described twice in the two
superseded plans. Implement it once.

### 2.2 Why bots come before the server

The superseded server plan put the zero-slot server before bot work, reasoning
that it would otherwise bake `authority == ConsolePlayer` into the AI. That
hazard is real, but it is eliminated by the identity split (Phase S), not by the
server binary. Once authority is a role and the command frame is slot-addressed,
a bot is one more command producer on the authority; whether that authority also
owns a human pawn is invisible to bot code. The server plan's own sequencing
builds and validates the entire hub model on a **listen authority** before
making it playerless, which is precisely the surface bots attach to.

Three reasons to then take bots first:

**Bots need no network.** The first playable slice — one human against one
visibly fallible bot on `MAP53` — is entirely offline and requires zero wire
changes. Protocol v2, star topology, reliability windows, hostile hardening, a
second binary, packaging, and operations are not on the critical path to it.
Server-first puts twelve milestones of networking between the foundation and the
first thing a player can enjoy.

**Bots are the feature that pays off alone.** A dedicated server is valuable
once you have people to play with. Corridor 7's realistic multiplayer population
is one person and whoever they invite. Bots make the eight arenas already
shipped usable by one player.

**The risks are of different kinds, and this order sequences them well.** Bots
carry design risk — fun, human-likeness, calibration — which is subjective and
needs many playtest iterations against a stable engine. The server carries
engineering risk — protocol, security, long-running service, cross-platform
packaging — which wants a settled gameplay surface beneath it.

### 2.3 What this ordering costs

Server milestone D11 becomes "re-home the bot manager from a listen authority to
a playerless one" rather than "add bots to a server that already exists." If the
foundation is honest that is a small change, and Phase S guarantees it: S2's
exit gate requires a unit test that constructs an authority with **zero local
player slots**, and §11.2 requires the bot manager to be written against that
API rather than against `ConsolePlayer`. If that test is ever weakened, this
cost stops being small. Treat it as a stop-the-line condition (§37.1).

### 2.4 Do not run the phases in parallel

All three touch `src/wl_net.cpp`, the session model, and the command path. The
current coupling is 77 `numPlayers` references across 19 files, 265
`ConsolePlayer` references across 30 files, and 54 transport-mode-as-rule checks.
Two concurrent branches over that surface would spend more time merging than
building. Plan together; implement sequentially.

---

## 3. Definition of done

### 3.1 Phase S is done when

- `IsArbiter()` no longer refers to `ConsolePlayer`, and no gameplay,
  spawn, score, or GC loop indexes players by peer number.
- A session model can hold a slot that no socket corresponds to, and nothing
  waits on a network peer for it.
- An offline deathmatch session with one local human and one placeholder slot
  reaches gameplay, spawns two pawns, scores both, and needs no UDP socket.
- Existing human multiplayer — menu, arenas, classes, teams, scoreboard, frag
  limit, latency, hostile-packet, and determinism gates — is unchanged and
  green.
- No variable-length packet is byte-swapped or dereferenced before its declared
  length is validated, proven by tests over real encoder output.
- Every command that reaches the simulation came through `TicCmd_t`. No input
  path writes pawn state directly.

### 3.2 Phase B is done when

- A local human starts a deathmatch and fills remaining positions with bots
  with no network connection.
- A network host starts a mixed match of remote humans and bots; every peer
  installs identical commands for every slot and reports identical digests.
- Bots appear in the ordinary scoreboard with an unambiguous `[BOT]` marker.
- Bots use the selected ordinary player class, normal starts, ordinary
  inventory, normal weapons, normal damage, and the normal respawn path.
- The host chooses bot count and a human-readable skill level before a match.
- Bots traverse all eight arenas — doors, transporters, hazards, and removable
  walls — without persistent stuck states, measured by a coverage gate.
- Bot behavior is fully explainable from a trace: every decision, route,
  perceived contact, aim error, and output command.
- No skill level has zero reaction delay, exact aim, unlimited turn rate, or
  knowledge a human could not obtain.

### 3.3 Phase D is done when

- `ec7wolf-server` on a machine with no display server and no audio device
  reaches a textual listening state and completes matches.
- No SDL video, OpenGL, Vulkan, GTK, window-system, joystick, game controller,
  mouse, or audio-output subsystem is initialized on the server path. Running
  under Xvfb, SDL's dummy driver, a hidden window, or offscreen rendering does
  not satisfy this.
- The server appears in no roster, scoreboard, team score, spawn list, frag
  limit, kill feed, automap, or player count.
- A server configured for eleven slots hosts eleven player slots.
- Slot 0 may belong to an ordinary remote human or a bot.
- Clients connect only to the server address and never need one another's.
- The server chooses and distributes map, mode, class policy, frag limit, seed,
  input delay, roster, and start sequence.
- Human input is accepted only for the slot owned by the sending peer.
- Server and clients produce the same full playsim digest for a fixed match
  under delay, jitter, loss, duplication, and reordering within the supported
  envelope.
- A malformed, spoofed, stale, or unauthorized packet cannot pause, end,
  debug-modify, or otherwise affect a match.
- A client may open local menus without freezing the match.
- A client disconnect produces one server-authored result at one specified
  command sequence and never leaves others waiting forever.
- `SIGINT`, `SIGTERM`, Windows console control events, and the local `quit`
  command stop accepting joins, notify clients where practical, close the
  socket, flush logs, and exit without a window or prompt.
- A packaged server runs from its own directory with an explicit local config,
  log/state directory, `ec7wolf.pk3`, and operator-supplied game data.

---

## 4. Non-goals

Program-wide, none of the following is in scope:

- Interoperation with the original DOS IPX, modem, or serial protocols.
- A Zandronum- or GZDoom-compatible wire protocol.
- Client prediction, server reconciliation, state snapshots, or unlagged hit
  validation.
- Host migration. If the authority leaves, the session ends.
- Mid-match join, spectator streaming, seamless reconnect, or live slot
  takeover.
- Saving and resuming live multiplayer worlds.
- Public accounts, ranking, matchmaking, master-server listing, automatic
  mod download, or a web control panel.
- Encryption of all gameplay traffic, or a comprehensive anti-cheat system.
- Voice or text chat, generated or otherwise.
- Packaging any commercial Corridor 7 data.

Bot-specific non-goals:

- Cooperative bots, monsters controlled as players, single-player companion AI,
  capture-the-flag, or objective modes.
- Learning during play, neural networks, external AI services, or an LLM in the
  game loop.
- Perfect imitation of a particular human player.
- Navigation through arbitrary mod mechanics for which no traversal metadata
  exists.
- A general-purpose bot scripting language.
- Reusing monster chase code as player locomotion.

Team play is a partial non-goal and needs care: Corridor 7's teams are derived
from the player class, and human team deathmatch already ships. The program must
not break it, and the roster model must represent it, but *bot team tactics* are
deferred.

---

## 5. Terminology

| Term | Meaning |
| --- | --- |
| **runtime role** | Standalone client, network client, listen authority, or dedicated authority |
| **peer** | One authenticated network connection/process in a session |
| **authority** | The one session participant that owns roster, sequencing, rules, and lifecycle |
| **player slot** | An index into the simulated player arrays and its pawn; never a process |
| **controller** | The source of a slot's commands: a local human, a remote human, or an authority-owned bot |
| **local player** | The human slot sampled by an interactive process, if one exists |
| **local view** | The slot/camera rendered by an interactive process, if one exists |
| **listen authority** | A rendered host that is authority and also owns a local human slot |
| **dedicated authority** | A playerless, headless server process |
| **input submission** | A client's proposed command for its owned future tic |
| **input epoch** | A match-local command timeline created at begin/resume; old-epoch commands are never reused |
| **canonical input frame** | The authority-approved commands for every active slot at one sequence |
| **playout depth `P`** | Contiguous canonical frames a rendered client buffers to absorb jitter and clock drift |
| **playsim digest** | A stable hash of replicated, decision-relevant simulation state at one tic; excludes authority-private bot-brain state |
| **bot-brain digest** | A separate authority-only hash of bot memory, perception, path, utility, and PRNG state |

"Human-only," in the original multiplayer description, means "human-controlled
player slots" — not a new monster mode. A bot is a simulated player controller,
not a single-player enemy actor.

---

## 6. What exists now

A source audit of `main` at `e897c6a`, not an assumption from ECWolf's
ancestry. Line numbers move; the named functions and responsibilities are the
durable references.

### 6.1 Multiplayer is player-to-player lockstep, and one count means everything

[`src/wl_net.h`](../src/wl_net.h) defines only `MODE_SinglePlayer`,
`MODE_Host`, and `MODE_Client`. `NetInit::numPlayers` means all of the
following at once, depending on the call site:

- number of UDP participants;
- number of command producers;
- number of connected addresses;
- number of initialized `player_t` objects;
- bound for spawn, score, frag, inventory, and respawn loops.

Measured coupling on `main`: **77 `numPlayers` references across 19 files, 265
`ConsolePlayer` references across 30 files, and 54 arbiter/transport-mode
checks.** `MAXPLAYERS` is 11.

[`src/wl_net.cpp`](../src/wl_net.cpp) hardcodes the arbiter:

```c
// TODO: Handle transfer of arbiter status as client quit
#define Arbiter 0
bool IsArbiter() { return ConsolePlayer == Arbiter; }
```

`StartHost()` begins at `nextclient = 1` because "0 is the host" and waits for
`numPlayers - 1` addresses. `StartJoin()` receives `playerNumber` and writes it
straight into `ConsolePlayer`. `NetClient Client[MAXPLAYERS]` is indexed by
player number. The start packet contains every other player's address, creating
a full mesh. `Net::NewGame()` contributes one setup record at
`newGamePackets[ConsolePlayer]` and treats player 0's map and difficulty as
authoritative. The tic paths serialize exactly one local command from
`control[ConsolePlayer]`, skip that index when sending, and wait over the player
count.

Consequences:

- Adding `MODE_Dedicated` alone cannot work.
- Leaving `ConsolePlayer == 0` creates a local player even if nothing is drawn.
- Setting `ConsolePlayer` to `-1` or `MAXPLAYERS` is unsafe: it is an unsigned
  index used directly in hundreds of array expressions.
- Incrementing `numPlayers` for a server creates a pawn and consumes a slot.
- Setting `numPlayers = humans + bots` makes both the startup handshake and
  every tic wait for a UDP peer per bot. Creating fake clients for bots would
  compound the error and make offline play depend on networking.
- Excluding one index from spawn loops while leaving it in network loops
  produces mismatched arrays and deadlocks.
- A server with eleven remote humans needs eleven slots plus one authority
  process; `MAXPLAYERS` cannot remain the bound for "all session nodes."

### 6.2 The command seam exists and is good

[`src/wl_play.h`](../src/wl_play.h) defines `TicCmd_t` and
`control[MAXPLAYERS]`:

```cpp
struct TicCmd_t
{
    int controlx, controly, controlstrafe; // range from -100 to 100
    int controlpanx, controlpany;
    BYTE buttonstate[NUMBUTTONS], ambuttonstate[NUMAMBUTTONS];
    BYTE buttonheld[NUMBUTTONS], ambuttonheld[NUMAMBUTTONS];
};
```

`PollControls` builds only the local human command, then calls
`Net::PollControls`. [`APlayerPawn::Tick`](../src/g_shared/a_playerpawn.cpp)
reads `control[player->GetPlayerNum()]`, handles use, weapon selection, attack,
reload, and zoom, then calls `ControlMovement` in
[`src/wl_agent.cpp`](../src/wl_agent.cpp):

```text
controller intent -> finalized TicCmd_t for one slot -> APlayerPawn::Tick
    +-- Cmd_Use / weapon state machine / inventory
    +-- ControlMovement -> Thrust -> ClipMove/TryMove
    -> ordinary collision, triggers, damage, death, frags, respawn
```

That is exactly the boundary this program needs. Details that matter to any new
command producer:

- Axis range is documented `-100..100`; keyboard movement uses `BASEMOVE`/
  `RUNMOVE` (35/70). Clamp every axis at the producer even though some
  downstream code clamps too.
- **Yaw is not clamped in `ControlMovement`.** An unrestricted producer could
  turn instantly, so a human turn-rate envelope is mandatory, not cosmetic.
- Movement buttons such as `bt_moveforward` are converted into axes during
  local input polling. Setting the button alone moves nothing; a producer must
  emit axes.
- `buttonheld` is semantically important — use is edge-triggered, as are
  several weapon and equipment actions. Common command-installation code should
  derive held state from the previous applied command rather than trusting a
  producer or a remote packet to get it right.
- A non-human producer must whitelist gameplay controls and never emit escape,
  pause, automap, status-bar, or menu buttons.

### 6.3 The lifecycle is already controller-agnostic

[`player_t`](../src/wl_agent.h) holds the pawn, state, health, frags, weapons,
inventory-facing state, and respawn timing. The level-start path creates every
active player through `CheckSpawnPlayer` and `SpawnPlayer`. `player_t::TakeDamage`
records frags; `DeathTick` supplies the use-button/timeout respawn path;
`Reborn` grants starting and battle inventory.

Keep these functions controller-agnostic. A bot-specific spawn, inventory,
damage, or respawn function is a design failure.

### 6.4 The simulation seam is usable but not extracted

Inside [`PlayLoop`](../src/wl_play.cpp), the deterministic body is roughly:

```text
install finalized commands
increment gamestate.TimeCount
CheckSpawnPlayer
tick VICTORY, WORLD, PLAYER, NORMAL thinkers in that order,
  with the existing post-VICTORY short-circuit when victoryflag is set
AActor::FinishSpawningActors
compute deterministic capture/digest
```

It is surrounded by client-only work: SDL event processing and local input,
render-derived tic calculation, interpolation and dynamic-wall render snapshots,
`PlayFrame`, HUD, automap, scoreboard, buffer presentation, screenshot/capture
actions, texture animation, positional sound localization, and keyboard/debug/
menu checks.

Extracting `RunSimulationTic(const CanonicalInputFrame&)` is the central
headless seam. Every slot's command must exist before any thinker is ticked, so
slot iteration order cannot affect command decisions.

### 6.5 Startup is unconditionally client-oriented

The POSIX entry point calls `gtk_init_check()` unless built with `NO_GTK`.
[`WL_Main`](../src/wl_main.cpp) locates data, initializes WADs, probes CD music/
upscale/FLIC content, initializes renderer resources, calls `InitGame`, and
enters `DemoLoop`. `InitGame()` performs, in one path: SDL base init; MAPINFO,
texture manager, palette, font, lookup-table, and actor setup; a renderer
capability check and temporary VGA/window mode; graphics shutdown registration;
input/joystick/controller startup; sound/audio-device startup; key messages,
status bar, and quiz setup; interactive network status callbacks; menu creation,
sign-on display, input waits, jukebox check; and renderer backend init.

`R_InitRenderer()` is called before `InitGame` and is distinct from
`R_InitRendererBackend`: it creates no window but initializes software 2-D
drawing/translation tables and forms a source/link seam.

`DemoLoop`, `GameLoop`, and `PlayLoop` assume presentation. Suppressing
`PlayFrame()` would still create a window, start audio and input, construct
menus, access a local player, and use presentation-driven lifecycle screens.

The required split is not `if (!dedicated)` sprinkled through a function:

```text
WL_Main
  +-- parse role before platform presentation startup
  +-- initialize paths/config/logging
  +-- initialize common resource and gameplay metadata
  +-- client role: initialize presentation, enter ClientMainLoop
  `-- server role: initialize server services, enter DedicatedMainLoop
```

A failure to bind, load the configured map, validate data, or initialize the
protocol must be fatal on the dedicated path. Today a failed network setup is
abandoned and the game silently enters single player — dangerous for a service,
and a documented source of confusing test results.

### 6.6 One input path already violates the command boundary

[`PollMouseMove`](../src/wl_play.cpp) writes pawn pitch directly:

```cpp
players[ConsolePlayer].mo->pitch += mousey * (ANGLE_1 / (21 - mouseyadjustment));
```

`TicCmdPacket` carries no pitch, so in a netgame each machine's copy of a pawn
has a different pitch. This is both a determinism hole and — more importantly
for this program — the one place where a *human* bypasses the command boundary
that every bot is required to respect. Closing it in Phase S means the rule
"only commands reach the simulation" is true before anything depends on it.

### 6.7 Current packet safety is not a server-grade baseline

The new protocol must not inherit these patterns, and the worst of them cannot
wait for Phase D:

- `RequestPacket` is a bare type byte: no magic, version, session, nonce,
  cookie, compatibility data, or anti-spoof proof.
- The first distinct source addresses occupy lobby positions, allowing trivial
  slot exhaustion.
- Packed C++ structs (`#pragma pack(1)`) are cast directly over untrusted UDP
  bytes.
- `CheckPacketType<T>` checks only `packet->len >= sizeof(T)` and the type byte,
  **then byte-swaps** — before any variable-length content can be validated.
- Some control packets are acted on or acknowledged without proving the source
  is an authenticated peer or the authorized authority. A forged
  `EndGamePacket` reaches the end-game path; block, input-ack, and debug
  handling have similarly weak boundaries.
- Tic packets infer slot identity from the source address and carry no explicit
  ownership claim, axis envelope, or gameplay-button mask.
- There is no session ID, connection token, replay window, or authority-only
  control-event validation.
- Startup and lobby waits can be indefinite. The peer-timeout work improved the
  "wait forever" failure mode but remains locally decided, peer-as-player logic.

**The `StartPacket` trailing-array defect is live and is a memory-safety bug.**
A partial fix landed: `ValidStartPacket()` correctly requires
`len >= sizeof(StartPacket) + sizeof(Client) * (numPlayers - 1)`. But it runs
*after* `CheckPacketType<StartPacket>()` has already called `ByteSwap()`, and
`ByteSwap()` loops over the unvalidated, attacker-supplied `numPlayers`:

```cpp
for(BYTE i = 0; i < numPlayers; ++i) {
    clients[i].host = LittleLong(clients[i].host);
    clients[i].port = LittleShort(clients[i].port);
}
```

With `#pragma pack(1)`, `clients` begins at offset 10 and each entry is 6 bytes,
so a packet declaring `numPlayers = 255` reads and writes through offset 1539 of
a receive buffer allocated at `SDLNet_AllocPacket(1500)` — **40 bytes past the
end of the allocation, from a single unauthenticated UDP datagram.** Even a
well-formed packet swaps one entry more than exists, because the encoder writes
`numPlayers - 1` entries and the decoder swaps `numPlayers`.

The host is reachable too: `CheckPacketType<StartPacket>` is called on received
traffic during a game to answer a lost start ack, so the same swap runs there.

This is milestone S1's headline item and is not deferrable to the protocol
rewrite.

### 6.8 Mid-match loss ends the match for everyone, deliberately

`Abandon()` in [`src/wl_net.cpp`](../src/wl_net.cpp) documents the reasoning:

> Dropping one player and playing on is the thing that cannot be done safely:
> every machine would have to drop them in the same tic or the simulations
> diverge. Ending the match needs no such agreement.

That is the correct v1 policy and this program keeps it, but it must become an
*authority* decision at a *named sequence* rather than each machine's local
conclusion (§25.1). [multiplayer.md](multiplayer.md) also records that roughly
half of connections complete at 5% packet loss — the level-start exchange, not
the tic loop. Both are Phase S/S1 prerequisites, not bot or server problems.

### 6.9 "No rendering" does not mean "no resource metadata"

Dependencies that an over-aggressive server-only source list will break:

- `IWad::SelectGame` may open an interactive picker when data selection is
  ambiguous. A server must resolve data explicitly and fail to stderr.
- Corridor 7 startup validates map, audio, VGA, and graphic file families. A
  maps-only data promise requires changing that contract first.
- `ClassDef::LoadActors` parses actor definitions and initializes sprite
  metadata; actor spawning may reject or replace an actor with an invalid
  sprite. Sprite registry information is part of a valid gameplay load even
  when no pixels are drawn.
- Corridor 7 map translation reads texture pixels to derive `maskedWallType`,
  but its consumers are renderer/visibility code. Movement uses tile presence,
  `sideSolid`, slide/push state, and a sight query that treats every extant tile
  as blocking. Texture names/IDs, sprite validity, map markers, tile solidity,
  triggers, wall IDs, and mutable map state are gameplay data. Retain
  pixel-derived masking through the first headless stage for parity, then
  separate it from the authoritative map before removing pixel decoders.
- `CA_CacheMap` calls render visibility calculation, which depends on projection
  values created by video setup. That call must become client-only; feeding it
  dummy projection constants would conceal the coupling.
- `SetupGameLevel` mixes common map/spawn work with music start and render
  snapshot reset; it needs common and presentation phases.
- `StartMusic`/`SelectLevelMusic` uses the separately named `Corridor7Music`
  RNG even under CD audio. It selects a soundtrack only, so it is presentation
  state, excluded from the authoritative RNG registry and digest. The server may
  skip it; clients may retain it for repeatable soundtrack order.

### 6.10 `ConsolePlayer` and presentation reach into gameplay

Risk classes among the 265 references:

- rendering and projection index `players[ConsolePlayer]` directly;
- `NewGame` initializes only `playerClassNames[ConsolePlayer]` before the
  network exchange;
- gameplay-side FOV/rebirth paths recalculate global projection;
- weapon and door sound calls compare against `players[ConsolePlayer].camera`;
- door zone-linking dereferences the console pawn while deciding whether to
  start a sound sequence;
- damage, inventory, keys, dispensers, chambers, elevators, and death fades
  call `StatusBar`;
- local-camera map visibility flags are updated from gameplay/map code;
- global cheats such as `godmode` could affect all players if inherited from a
  server config.

Never encode "no local player" as an out-of-range `ConsolePlayer`. Introduce
explicit queries and nullable handles:

```cpp
bool HasLocalPlayer();
std::optional<PlayerSlot> LocalPlayerSlot();
bool HasLocalView();
std::optional<PlayerSlot> LocalViewSlot();
bool IsLocalViewSlot(PlayerSlot slot);
```

Common simulation code takes an explicit slot or actor. Presentation calls go
through event sinks with real client and deliberate null-server implementations.
A `NullStatusBar` is a safe transition tool because the abstract interface
already exists, but the endpoint is a notification sink, not a fake HUD in the
server.

### 6.11 Gameplay rules depend on transport mode

Several paths use `MODE_SinglePlayer` versus network mode as a proxy for rules —
respawning, item persistence, pausing, menus, sound, saving. A one-human-plus-
bots match is a multiplayer deathmatch in gameplay terms with no remote peer, so
that proxy breaks in Phase B. Introduce semantic predicates and audit every use:

```cpp
Session::IsDeathmatch()        Session::IsMultiplayerGameplay()
Session::AllowsRespawn()       Session::RespawnsItems()
Session::NoMonsters()          Net::IsNetworked()
Net::IsAuthority()             Net::HasRemotePeers()
```

Transport code asks whether it is networked. Damage, death, inventory, HUD,
pause, and match flow ask what rules the session uses.

### 6.12 Build system is a single client executable

[`src/CMakeLists.txt`](../src/CMakeLists.txt) creates one monolithic `engine`
target containing gameplay, renderers, UI, input, audio, networking, resource
loaders, menus, and platform entry points. It always links SDL2, SDL2_net,
SDL2_mixer, JPEG, xBRZ and others; desktop options add GTK and OpenGL/libepoxy.
There is no server or common-core target, and the PK3 build/install logic
assumes the `engine` target's output directory.

### 6.13 What already works and must not regress

From [multiplayer.md](multiplayer.md), all shipped and gated: menu-driven host
and join over the internet; eight arenas (`MAP51`–`MAP58`); Marine and alien
classes; free-for-all and team deathmatch; scoreboard; frag limit; an arbiter;
acked reliable packets; input delay carried in the start packet; a peer-timeout
watchdog ([`net_watchdog.h`](../src/net_watchdog.h)); and the determinism
harness (`--capture-checksum`, the `corridor7_determinism` gate). The existing
gates are `tools/test_multiplayer_{arenas,cancel,classes,hostile,latency,
loopback,menu,presentation,rules,setup}.sh` plus `tools/netdelay.py` and
`tools/netfuzz.py`.

Every one of those is a Phase S regression gate.

---

# Part II — Phase S: the shared foundation

## 7. What Phase S is, and what it is not

Phase S makes the engine capable of describing a player that no socket
corresponds to, and an authority that owns no player. That is all. It ships no
bot and no server.

**In scope**

- Closing the packet-safety and command-boundary defects that both later phases
  would otherwise inherit.
- Splitting runtime role, network peer, player slot, and local view into four
  independent concepts.
- Replacing transport-mode-as-gameplay-rule with semantic session predicates.
- A command production seam that can finalize commands for more slots than
  there are peers.
- An offline deathmatch session that needs no UDP socket.

**Explicitly not in scope**

- The protocol v2 rewrite, star topology, reliability windows, and bounded
  codec. Those are Phase D. Phase S changes the wire only where a live defect
  requires it.
- Any headless or windowless mode.
- Any AI.

The discipline that keeps Phase S finite: **every change must leave existing
human multiplayer working and every existing gate green.** Adapters are
acceptable during the phase; a broken netgame is not.

---

## 8. Data model

Names are illustrative; the separation is mandatory.

```cpp
enum class RuntimeRole : uint8_t
{
    Standalone,        // no socket; offline single player or offline deathmatch
    NetworkClient,
    ListenAuthority,   // rendered host: authority AND owns a local human slot
    DedicatedAuthority // Phase D: authority, owns nothing
};

using PeerId = uint16_t;
using PlayerSlot = uint8_t;

enum class SlotKind : uint8_t { Empty, Human, Bot };

struct PlayerSlotInfo
{
    PlayerSlot slot;
    SlotKind   kind;
    uint32_t   controllerGeneration;      // increments on replacement
    std::optional<PeerId> ownerPeer;      // required for Human, absent for Bot
    FString    name;
    FName      playerClass;
    // Corridor 7 derives team from playerClass via PlayerTeam(slot).
    // Do not store an independent, possibly contradictory team here.
    std::optional<BotProfileId> botProfile;    // Bot only
    std::optional<uint64_t>     controllerSeed; // Bot only
};

struct PeerInfo
{
    PeerId       id;
    ConnectionId connection;
    PeerState    state;
    std::optional<PlayerSlot> humanSlot;
    Address      address;          // authority-side only
    CapabilityBits capabilities;
    LivenessState  liveness;
};

struct SessionState
{
    RuntimeRole role;
    PeerId      authorityPeer;
    std::optional<PeerId>     localPeer;
    std::optional<PlayerSlot> localHumanSlot;
    std::optional<PlayerSlot> localViewSlot;
    PlayerSlotInfo slots[MAX_PLAYER_SLOTS];
    MatchRules     rules;
    SessionLifecycle lifecycle;
};
```

Do not serialize `LocalHuman` versus `RemoteHuman` as slot kinds — those labels
are perspective-dependent. The canonical description is `Human + ownerPeer`;
local versus remote is derived by comparing that owner with the local peer.

### 8.1 Separate capacities

Define and validate independently:

```text
MAX_PLAYER_SLOTS  = 11    simulated humans + bots
MAX_CLIENT_PEERS  = 11    remote human connections in v1
MAX_SESSION_PEERS = 12    dedicated authority + all clients
```

Future spectators may make `MAX_CLIENT_PEERS` exceed `MAX_PLAYER_SLOTS`, so
never bake equality back into a new API. The authority does not need an entry in
an array of remote client connections merely because it has a `PeerId`.

### 8.2 Non-negotiable invariants

Assert in debug builds, test in release behavior:

1. Exactly one peer is the authority.
2. A dedicated authority has no human slot and no local view.
3. A listen authority has zero or one local human slot; if present, its local
   peer owns it.
4. Every active human slot has exactly one authenticated owner peer.
5. No peer owns more than one human slot in v1.
6. A bot slot has no network owner and no liveness or readiness obligation; it
   has exactly one validated profile, controller seed, and controller
   generation.
7. An empty slot has no pawn, controller, score row, or command.
8. A `PeerId` is never used as a player-array index without an explicit map.
9. A `PlayerSlot` is never used as a connection-array index without an explicit
   map.
10. `MAX_PLAYER_SLOTS` bounds simulation arrays only.
11. Only the authority emits canonical input frames and lifecycle events.
12. A client may submit commands only for its owned human slot.
13. All active slots appear exactly once in each canonical input frame.
14. No synthetic slot representing a server process ever enters spawn, frag,
    inventory, camera, or scoreboard loops.
15. Gameplay simulation never requires `ConsolePlayer` or a local camera.
16. In Corridor 7 team deathmatch, a slot's team is derived canonically from its
    player class through the existing `PlayerTeam` rule. If independent teams
    are ever added, migrate damage, aggregate frags, scoreboard, and frag-limit
    code together with a validated `TeamId`.

### 8.3 Classifying the existing counts

The `numPlayers` audit is mechanical and must be complete. Rename at the
compiler level rather than leaving the old name with two meanings, so that every
call site is forced through review:

| Use category | New bound or query |
| --- | --- |
| Spawn, player thinkers, actors, scores, HUD, GC, class assignment | active slots |
| Socket addresses, joins, acknowledgments, disconnects, reliable exchange | peers |
| Per-tic command completeness | required active-slot command mask |
| Local rendering and input | local human slot / local view slot |
| Bot brain iteration (Phase B) | authority-owned bot slots |

### 8.4 Roster mutability

V1 locks the roster before loading a match. Configuration may change in
`LobbyOpen` and after results; it may not add, remove, or reassign slots while
`Running`.

A disconnect is not an ordinary roster edit. While `Running` with no unresolved
stop, the authority schedules `StopAfterTic(AbortMatch)`; if a stop already
exists it retains that sole boundary, updates the survivor set, neutralizes the
lost slot through it, and records disconnect metadata. A later versioned
`RosterChange(ApplyBeforeTic(E))` can remove a pawn or replace a human with a
bot deterministically. Never let each peer infer that change from its own
timeout clock.

---

## 9. Milestones

### S1 — Safety baseline and the command boundary

**Purpose:** fix what is actually broken today, before anything is built on it.
No new abstractions; no behavior changes a player would notice except that
hostile packets stop working.

**Work**

1. **Validate before decode.** `CheckPacketType<T>` currently checks
   `len >= sizeof(T)` and then calls `ByteSwap()`. For any packet with a
   trailing array that is wrong by construction. Split the two steps:
   type/length check, then explicit validation of declared counts, then decode.
   No packet is byte-swapped, dereferenced, or allocated from until its declared
   length is proven against the received length.
2. **Close the `StartPacket` overflow.** `ByteSwap()` loops
   `i < numPlayers` over `clients[]` using an unvalidated attacker-supplied
   byte, past the end of a 1500-byte receive buffer (§6.7). Validate first, and
   correct the count: the encoder writes `numPlayers - 1` entries, so the
   decoder swaps `numPlayers - 1`.
3. **Source and role validation for control packets.** A packet that can end,
   pause, block, or debug-modify a match is honored only from the address of the
   peer entitled to send it. Add one explicit table of
   message → permitted sender → permitted session state → side effect, and make
   the handler consult it rather than each site deciding for itself.
4. **A protocol version and magic in the handshake.** `RequestPacket` is a bare
   type byte today, so any future wire change is a silent desync. Add a magic
   and a protocol version, reject a mismatch with a message that names both
   versions, and make the version a compile-time constant that Phase D's codec
   will increment.
5. **Close the pitch hole.** `PollMouseMove` writes
   `players[ConsolePlayer].mo->pitch` directly, `TicCmdPacket` carries no pitch,
   and `ChecksumThisTic()` **hashes `pitch`** — so mouselook desynchronizes the
   determinism instrument itself. Mouselook is a debug toggle
   (`wl_debug.cpp`), default off, with no menu entry, so the correct v1 fix is
   to refuse the local pitch write whenever the session is not standalone, and
   to state in one comment that a synchronized bounded pitch field belongs to
   the canonical command in Phase D if mouselook ever ships. Do not solve this
   by removing `pitch` from the digest, and do not remove the field from
   `AActor::Serialize` — that would break save compatibility.
6. **Record the baselines** the later phases regress against: two-player
   checksum equality, level-start completion rate against packet loss, tic
   latency distribution, and match-result agreement.
7. **Commit this plan** as the design record, and record that the protocol is
   intentionally versioned from here on.

**Exit gate**

- Every existing multiplayer gate passes unchanged.
- A hostile `StartPacket` declaring 255 clients in a 12-byte datagram is
  rejected, and the run is clean under ASan/UBSan.
- A well-formed start packet swaps exactly `numPlayers - 1` trailing entries.
- Forged end-game, block, and debug packets from a non-authority source change
  nothing.
- A client built with a different protocol version is rejected with a message
  naming both versions, rather than desynchronizing.
- With mouselook toggled on in a two-machine game, per-tic checksums stay
  equal.
- Baselines are recorded in the repository as the reference for later phases.

### S2 — Identity split: role, peer, slot, view

**Purpose:** represent the four identities separately, with existing multiplayer
still working through adapters.

**Work**

- Add `RuntimeRole`, `PeerId`, `PlayerSlot`, `SlotKind`, the session/roster
  model, the ownership map, and the separate capacities of §8.1.
- Add the minimal `SessionLifecycle` states needed by admission, manifest
  loading, ready/begin, running, terminal-pending, and shutdown. Do not infer
  those phases from menus or socket waits.
- Replace `IsArbiter() == (ConsolePlayer == 0)` with authority semantics.
- Classify every `numPlayers`, `Client[]`, `ConsolePlayer`, `players[0]`, and
  transport-mode check by its actual meaning, per §8.3.
- Convert gameplay, spawn, score, and GC loops to active player slots.
- Add `HasLocalPlayer()`, `LocalPlayerSlot()`, `HasLocalView()`,
  `LocalViewSlot()`, `IsLocalViewSlot()`; never encode "no local player" as an
  out-of-range `ConsolePlayer`.

**Exit gate**

- The listen host still runs existing human multiplayer; every gate green.
- Tests construct a session with an authority peer and **zero local player
  slots** without indexing any player array. *This test is the guarantee that
  Phase D's bot re-homing stays cheap (§2.3); weakening it is a stop-the-line
  condition.*
- Slot 0 can be owned by a non-authority peer in model and unit tests.
- `MAX_PLAYER_SLOTS`, `MAX_CLIENT_PEERS`, and `MAX_SESSION_PEERS` are validated
  independently.
- A debug assertion fires for each violated invariant in §8.2 under a
  deliberately corrupted roster.

### S3 — Session rules, and an offline deathmatch

**Purpose:** stop gameplay rules from asking the transport layer what game this
is, and produce the first session with a slot no socket corresponds to.

**Work**

- Add the semantic predicates of §6.11 and audit every current
  `InitVars.mode != MODE_SinglePlayer`. Some mean deathmatch rules, some mean
  multiple simulated players, some mean sockets are active, some mean local
  menus and saves should be disabled. Those meanings diverge the moment offline
  bots exist.
- Cover at minimum: death and respawn in `a_playerpawn.cpp`, player tick in
  `wl_play.cpp`, weapon and key persistence in the inventory code, automap
  pausing, multiplayer fades and positional sound, save/high-score/menu gating.
- Add a `Standalone` deathmatch session: deathmatch rules, one local peer, one
  or more slots, **no UDP socket**.
- Add an `Empty`-kind placeholder slot that spawns nothing and is waited on by
  nothing, so the roster can hold a position before a controller exists.

**Exit gate**

- An offline deathmatch on an arena reaches gameplay with deathmatch rules
  (respawn, item respawn, no monsters) and never opens a socket.
- Single player is unchanged; the full single-player gate suite is green.
- No gameplay rule reads `InitVars.mode`; a grep gate enforces it outside
  transport code.

### S4 — Slot-addressed command production

**Purpose:** finalize commands for more slots than there are peers, in process.

**Work**

- Refactor command production so that "sample the local human" and "finalize
  the frame" are separate steps, and the finalizer consumes a per-slot producer
  rather than reading `control[ConsolePlayer]`.
- Introduce the canonical input frame: all active slots, exactly once, for one
  sequence, built before any thinker ticks.
- Derive `buttonheld` in common command-installation code from the previously
  applied command, rather than trusting a producer or a remote packet.
- Add a per-slot output whitelist and axis clamp at the producer boundary, so
  no producer can emit a UI button or an out-of-range axis.
- Add a per-slot command trace and a command digest, separate from the world
  digest.
- Prove the seam with a `ScriptedProducer` that replays a fixed command tape.
  It queries no world state. **No AI exists at the end of Phase S.**

**Exit gate**

- An offline session runs two slots — one live human, one scripted tape — with
  both pawns spawned, moving, scored, and killable.
- Existing networked play is unchanged and produces byte-identical command
  traces to the S1 baseline.
- A producer that emits an escape, pause, automap, or menu button fails a test.
- A producer that emits an out-of-range axis is clamped, and the clamp is
  asserted.

---

## 10. Phase S verification

Beyond each milestone's gate:

| Gate | Asserts |
| --- | --- |
| Existing `test_multiplayer_*.sh` suite | No regression, every milestone |
| `corridor7_determinism` | The simulation is still bit-reproducible |
| New hostile-packet vectors | Truncated, oversized, and forged packets are rejected before decode |
| ASan/UBSan network run | No out-of-bounds access from any received datagram |
| Zero-slot session model test | An authority can exist with no player array entry |
| Rule-predicate grep gate | No gameplay file reads `InitVars.mode` |
| Command whitelist test | No producer can emit a UI button |
| Baseline comparison | Checksums, latency, and loss-tolerance match the S1 record |

---

## 10a. S1 baselines

Recorded 3 September 2026 on `multiplayer-foundation`, from
`builds/release-build` against `corr7/CORR7CD`. These are the numbers later
phases regress against; re-record them, do not quietly adjust them.

**Determinism.** `test_multiplayer_loopback.sh` — MAP53, seed 1, input delay 6,
two processes:

```text
120 tics, both sides identical every tic, summary checksum=5960981e
```

**Latency and loss.** `test_multiplayer_latency.sh` — 80 ms round trip, 2%
loss, 140 tics each way:

| Input delay | Throughput | In sync |
| ---: | ---: | --- |
| 8 | 23 tics/sec | every tic |
| 0 | 8 tics/sec | every tic |

The delay is worth roughly 3x on a link like this, which is the measurement
that justifies a positive negotiated lead in §25.1 and makes `D = 0` a
loopback-only diagnostic.

**Single-player determinism.** `test_corridor7_determinism.sh`:

```text
run-to-run determinism            500 tics, checksum=ae626557
interpolation on/off              identical simulation
software and OpenGL               identical simulation
```

**Rules and content.** `rules`, `classes`, `arenas`, `menu`, `setup`, `cancel`,
and `presentation` all pass: player-versus-player damage and frag attribution,
team damage refusal and aggregate team frags, both classes differing in pawn,
health, side and measured speed, and all eight arenas placing players apart with
both machines agreeing.

**Hostile traffic.** `test_multiplayer_hostile.sh` passes on both the ordinary
build and an ASan+UBSan build, including the two new protocol-mismatch sections.

**Wire format**, as the engine reports it through `ec7wolf --netvectors -`:

```text
protocol 2      magic 45374e      maxplayers 11      maxextratics 64
RequestConnection 0/6   ConnectionStart 1/12   Ack 2/6    TicCmd 3/79
NewGame 4/19            BlockPlaysim 5/5       InAck 6/9  DebugCmd 7/269
EndGame 8/5
ConnectionStart: version@1 player@3 count@4 mode@5 delay@6 frags@7
                 seed@8 clients@12, 6 bytes each, numPlayers-1 of them
```

**One exit criterion is met by construction rather than by a gate.** "With
mouselook toggled on in a two-machine game, per-tic checksums stay equal" has
no gate, because mouselook is reachable only through a debug key and there is
no command-line way to turn it on -- adding one would put a new option into an
argv surface that already has seven independent scanners, to test three lines.
The write is simply unreachable while networked. If a later phase gives
mouselook a menu entry, it needs the canonical pitch field first (§24.3), and
that comes with a real gate.

**Known open behaviors**, carried forward from
[multiplayer.md](multiplayer.md) rather than measured here: roughly half of
connections complete the level-start exchange at 5% packet loss, and a
mid-match departure ends the match for everyone through `Abandon()` rather than
dropping one player. Both are Phase D work (§23.3, §32); neither regressed.

### What S1 actually changed

For the record, since three of the five items were live defects rather than
hardening:

1. **`StartPacket::ByteSwap()` overran two different buffers.** The receiving
   half is the one that matters -- one forged datagram, `numPlayers = 255`, and
   the swap walked forty bytes past a 1500-byte receive buffer, reading and
   writing, before any validation ran. `ValidStartPacket` existed and was
   correct; it was simply called afterwards. The sending half was an
   independent off-by-one: the encoder writes `numPlayers - 1` trailing entries
   and the swap walked `numPlayers`, so a host overran its own `malloc` on
   every sync packet it had ever sent. Both are proven by ASan, and both were
   reintroduced deliberately to confirm the gate detects them.
2. **No control packet checked its sender.** `EndGamePacket` reached
   `DoEndGame()` from any source: five bytes from anyone who guessed the port
   ended the match. `BlockPlaysim` and `InAck` were the same, and `DebugCmd`
   acknowledged an unknown sender before rejecting it.
3. **`tools/netfuzz.py` had never fired the packets it claimed.** Its copy of
   the `NET_` enum had `NewGame` and `TicCmd` transposed and `InAck`,
   `DebugCmd`, and `EndGame` misnumbered; its start packet was laid out for
   natural alignment when the struct is `#pragma pack(1)`. It was shooting
   well-formed nonsense at the wrong message types and passing. The engine now
   states its own layout through `--netvectors`, and the fuzzer rebuilds the
   engine's golden packet and refuses to run if the bytes differ.
4. **Two null-pawn crashes, found only because item 3 was fixed.** The
   battery's one genuinely well-formed start packet -- "well-formed, with 60kB
   of trailing rubbish" -- had been built with the wrong layout for as long as
   it had existed, so no client under test had ever actually synced with the
   forger. Once it did, the window between syncing and loading a level turned
   out to be reachable and unguarded: `BlockPlaysim` called `PlayFrame()` and
   `EndGame` called `DoEndGame()`, both walking into `players[i].mo == NULL`,
   both a SEGV. `HandleCommandPackets` now requires a game to exist before
   anything touches the playsim.

   This is the clearest argument in the program for the "real encoder vectors"
   rule in §24.1 and §39.2. The gate did not fail for years and it did not
   half-work; it passed confidently while firing at nothing.
5. **Pitch left the command boundary and broke the instrument.** Covered in
   §6.6; `ChecksumThisTic()` hashes actor pitch, so mouselook desynchronized
   the determinism harness itself.
6. **The protocol had no version.** Now `NET_PROTOCOL_VERSION 2`, with magic in
   the connection request, refused by name at both ends -- and a joining
   client holds the reason on screen rather than falling silently back to
   single player, through a new `InitStatus::failure`.

---

## 10b. S2 classification audit

The milestone's third work item is to classify every `numPlayers`, `Client[]`,
`ConsolePlayer`, `players[0]`, and transport-mode check by what it actually
means. This is that record. Counts are from `main` at the S2 commit; the point
of writing them down is that the next milestone can tell a conversion from a
regression.

### `Net::InitVars.numPlayers`

77 uses at the start of Phase S. Outside `wl_net.cpp` the meaning turned out to
be almost perfectly uniform -- 32 of 34 were the bound of a loop over
`players[]` -- which is what made this safe to do mechanically.

| Meaning | Count | Now reads | Where |
| --- | ---: | --- | --- |
| active player slots | 32 | `Session::ActiveSlotCount()` | `wl_game`, `wl_state`, `wl_agent`, `wl_play`, `wl_inter`, `wl_loadsave`, `wl_act2`, `actor`, `dobjgc`, `gamemap`, `c7_scoreboard`, `r_capture`, `g_intermission`, `a_deathcam`, `thingdef_codeptr`, `wl_main`, `wl_menu` |
| the operator's configured player count | 4 | unchanged | `--host N` in `wl_main`, the menu in `wl_menu`, one status string |
| network peers | 40 | unchanged, commented | `wl_net.cpp` only |
| the adapter that reconciles the two | 1 | `AdoptLegacyNetState()` | `g_session.cpp` |

The 40 in `wl_net.cpp` are the transport's own working state: how many
addresses to collect, how many acknowledgements to wait for, how many entries a
start packet carries, which `Client[]` slots to send to. Those become peer
counts properly in Phase D when the protocol stops implying a slot from an
address; converting them now would mean inventing a peer table the wire cannot
yet describe.

### `ConsolePlayer`

265 uses at the start of Phase S, 260 now. It means three different things and
the split matters, because a dedicated authority answers "none" to two of them:

| Meaning | Approx. | Disposition |
| --- | ---: | --- |
| **local view** -- the slot this process draws, and the HUD, camera, projection, automap, and view-model state that follows from it | ~200 | Behind `Session::LocalViewSlot()` / `IsLocalViewSlot()` where gameplay code asks it; the renderer keeps the variable until Phase D gives presentation a null implementation (§26.3) |
| **local human input** -- the slot this machine samples into `control[]` | ~25 | `Session::LocalPlayerSlot()`. `wl_play.cpp` is the concentration |
| **legacy peer index** -- this machine's position in `Client[]` and in the per-peer exchange arrays | ~29 | `wl_net.cpp` only; becomes a `PeerId` in Phase D |

The eleven sites converted in S2 are the ones where **gameplay** code asks a
presentation question -- `a_playerpawn.cpp` deciding whether to set a HUD
message, start a chamber readout, run the weapon-bob interpolation, or update
the status face, and `wl_agent.cpp` deciding whether to flash the screen. Those
are exactly the calls that a playerless process reaches and must be able to
decline, and they now decline by the session answering "no local view" rather
than by a comparison against a number that happens to be zero.

The remaining ~200 are inside the renderer, the status bars, the automap and
the input backends. Converting them is not deferred out of laziness: the plan's
endpoint for them is a presentation event sink with a real client
implementation and a deliberate null server one (§26.3), and rewriting them
twice would be worse than rewriting them once.

### `IsArbiter()`

Was `ConsolePlayer == Arbiter`, which conflated being the authority, occupying
slot zero, and being this machine. Now `Session::IsAuthority()`. Its six
callers -- menu abort/restart permissions and three debug keys -- are asking the
role question and get it unchanged today, because a listen host is still all
three things at once.

`#define Arbiter 0` survives in `wl_net.cpp` as what it always was: the legacy
protocol's peer zero, used as an index into `Client[]`. It is commented as
such.

### Transport mode as a gameplay rule

`Net::InitVars.mode` is read outside transport code in a handful of places, all
of which mean one of "are sockets open", "is this deathmatch", or "should local
menus and saves be available". `Net::IsNetworked()` and the existing
`Deathmatch()` / `RespawnItems()` / `NoMonsters()` cover the first two.
Separating the third, and adding the grep gate that keeps them separated, is
S3's work -- the audit belongs with the milestone that has an offline
deathmatch to prove the difference against.

### How S2 is verified

`tools/test_multiplayer_session.sh` runs `ec7wolf --sessiontest`, which is
data-free and windowless like `--flictest` and `--netvectors`, and is
registered in `run_gates.sh` among the data-free gates. Sixty checks:

| Group | What it constructs |
| --- | --- |
| shapes that exist today | single player; a listen host; the same session seen from a client |
| shapes the engine cannot play yet | an authority with eleven players and none of its own; slot 0 owned by a peer that is not the authority; a roster with more slots than peers; one with more peers than slots |
| capacities | the maximal valid session, then each of the three bounds pushed past on its own |
| rosters that cannot be true | 22 corruptions, each of which must be refused |

None of it indexes `players[]`, reads `ConsolePlayer`, or opens a socket. That
is most of what it proves: if a playerless authority could only be described by
code that touches a player array, it could not exist, and Phase D would be a
very late place to discover that.

Two notes on what the gate does and does not say:

- The plan's exit-gate wording is "a debug assertion fires for each violated
  invariant". What is actually proven is that `Validate()` **detects** each
  corruption and names it; the assertion is the debug-build mechanism layered
  on that detection. A fatal-error path cannot be exercised in-process without
  killing the test, so detection is what is measured.
- The self-test was checked for the ability to fail, twice: breaking
  `Validate()` produces 22 failures, and breaking `HasLocalPlayer()` produces
  the specific dedicated-authority failure. A green gate that cannot go red is
  the failure mode this program has already been bitten by once (§10a, item 4).

`AssertValid()` runs in the adoption path in debug builds, so a netgame on the
ASan+UBSan build is the check that it does not fire on legitimate play. It
passes, at the unchanged `checksum=5960981e`.

The S1 baselines are unchanged by the whole conversion: loopback
`5960981e`, determinism 500 tics `ae626557`. Thirty-two loop bounds and eleven
local-view questions moved, and the simulation did not.

### What S2 deliberately did not finish

`Lifecycle` exists as a type with all the phases §23 needs, and the adoption
path sets it at the two moments that exist today -- roster lock and running.
**Nothing reads it yet.** The states are there so that D2 and D3 have somewhere
to put admission, the ready barrier and terminal-pending without inventing a
second vocabulary; treating the enum as working lifecycle control would be
reading more into this milestone than is in it. The rule that goes with it --
never infer a phase from whether a menu is open or a socket is blocked -- is a
constraint on the code that will read it, not a claim about code that does.

Likewise the roster is still built by an adapter, `AdoptLegacyNetState()`, from
`Net::InitVars` and `ConsolePlayer` rather than being the source of truth. Two
counts therefore exist, and the milestone's job was to make their meanings
separate rather than to eliminate one. A debug assertion at the start-of-game
exchange fails the build loudly if they ever disagree, because two machines
quietly iterating different numbers of players is a desync that would be blamed
on the netcode for a week.

---

## 10c. S3 record

### The rule/transport split

Thirty-two `InitVars.mode` reads outside the transport, and every one of them
was asking one of four different questions through the same hole in the wall:

| What it really asked | Sites | Now |
| --- | ---: | --- |
| do multiplayer rules apply | 5 | `ItemsStayInWorld()`, `AllowsRespawn()` — keys, weapons, respawn, the death fade |
| is anyone else in the world | 4 | `HasMultiplePlayers()` — positional sound, the scoreboard, the tally, whether death stops the world |
| is a socket open | 3 | `Net::IsNetworked()` — command exchange, event blocking, the watchdog |
| does saving or a high score make sense, and may I leave | 12 | `AllowsSaving()`, `TracksHighScores()`, `CanLeaveSessionUnilaterally()`, `CanPauseLocally()` |

Afterwards `InitVars.mode` appears in exactly five places outside the
transport and the session adapter, and all five **set** it: `--host`/`--join`
in `wl_main.cpp`, the menu in `wl_menu.cpp`, and one status string.

`IsMultiplayerGameplay()` is the only predicate that consults the transport,
and it does so deliberately. While cooperative play over the wire exists there
is no way to answer "do multiplayer rules apply" from the rules alone — a co-op
netgame is not a deathmatch and is still multiplayer. Asking whether a socket
is open is exactly right for that case and exactly wrong for an offline
deathmatch, so it is asked once, in one function, with the reason written
above it. It is also what makes the milestone behavior-preserving: a host
sitting alone in a one-player netgame still answers every question the way it
always did.

### The truth table

The self-test grew from 60 checks to 106. The new rows are the substance:

| Session | multiplayer rules | respawn | items stay | saving | high scores | local pause | >1 player |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single player | no | no | no | **yes** | **yes** | yes | no |
| **offline deathmatch** | **yes** | **yes** | **yes** | no | no | **yes** | yes |
| networked co-op | yes | yes | yes | no | no | no | yes |
| networked deathmatch | yes | yes | yes | no | no | no | yes |
| host waiting alone | yes | yes | yes | no | no | no | **no** |

The second row is the one the old code could not express at all: every rules
question answered yes, every transport question answered no. The fifth is the
mirror image and the reason `HasMultiplePlayers()` is separate from
`IsMultiplayerGameplay()`.

Checked for the ability to fail: reverting `AllowsRespawn()` to the old
socket test produces exactly one failure, `offline deathmatch: respawn`.

### The offline gate

`tools/test_multiplayer_offline.sh` starts a deathmatch with no network and
proves three things behaviorally:

- it reaches gameplay on `MAP53` and simulates 200 tics;
- it opens **no internet socket at all**, proven by `strace -e trace=socket`
  rather than by the absence of a log line. If ptrace is unavailable the gate
  says the check was skipped rather than passing quietly;
- `MAP01` holds five aliens normally and none under `--battle`, so a
  deathmatch rule is being applied with no socket to justify it.

What was *not* proven behaviorally at the time, and why: respawning in place
rather than restarting, and an item left behind for somebody else, both need a
second pawn to observe. They were checked as predicates in the table above.

**S4 supplied the second pawn, and respawn is now proven behaviorally.** In the
duel the command gate runs, slot 0 dies around tic 80 and returns around tic
236 across four hundred *continuous* tics with no level reload -- which is
exactly the difference between "you respawned" and "the level restarted", in an
offline deathmatch with no socket anywhere. `test_multiplayer_commands.sh`
asserts it. Item-stay remains predicate-only: proving it wants a pickup placed
between two players, which is a map-authoring problem rather than a command one.

The general point is worth keeping: a claim deferred because it could not be
measured should be revisited when the measurement becomes possible, not left
standing as a permanent caveat.

### The source contract

`test_multiplayer_session.sh` now also greps the tree: no file outside
`wl_net.{h,cpp}`, `g_session.{h,cpp}`, `wl_main.cpp` and `wl_menu.cpp` may name
`InitVars.mode`, and the last two may only assign it. Verified to fail by
putting the old automap check back — it names the file and the line.

### Reserved slots

`State::reservedSlots` is the plan's "position before a controller exists": a
lobby row reading open, or the slot a bot will take once there is a bot.
Reserved slots are **not** in the match — they spawn nothing, score nothing,
and nothing waits on a socket for them — which is what lets a roster name a
position without breaking the contiguity that every `[0, count)` loop in the
engine depends on. Validation covers the new range, and the self-test refuses
a roster that reserves fewer positions than it is playing, one that puts a
player in a position it only held open, and one that reserves more than the
engine has slots for.

---

## 10d. S4 record

### The seam

`src/g_command.{h,cpp}`. A producer emits an `Intent` -- normalized movement
and requested actions, with no actor handles and no way to touch the world --
and one finalizer clamps the axes, strips everything that is not a gameplay
control, derives the held state, and installs the result. The rule the whole
bot design rests on now holds by construction rather than by convention:

> nothing reaches the simulation except through a command, and every command
> has been through here.

Held state moved with it. It is derived from the previous command **applied to
that slot**, not carried by whoever produced it. The old scheme computed it at
the sender against raw input, which is equivalent only while commands are
applied in the order sent and none are ever substituted -- and Phase D's
neutral substitution (§25.3) breaks exactly that assumption. The engine's own
comment recorded what getting this wrong looks like: one tap of the visor
cycling it eleven times.

### Local UI came out of the command

Forcing every command through a whitelist immediately exposed five buttons that
had no business travelling: `bt_pause`, `bt_automap`, `bt_c7map`,
`bt_scoreboard`, `bt_showstatusbar`. They are things a machine does to its own
screen, and they were being sampled into a command, replicated, and read back
out of `control[]` by presentation code. They now live in a separate local
buffer, `Command::LocalUi()`.

Two consequences, both improvements, both worth stating because they are
behavior changes:

- **A remote player's pause key used to pause your machine.** The pause handler
  read `bt_pause` out of *every* slot's command. It reads one machine's own
  keyboard now. This is the hazard §23.5 warns about -- "never reuse a player
  `bt_pause` bit" -- found by building the whitelist rather than by reading the
  code.
- **The scoreboard key took effect a delay window late** in a netgame, because
  it was read from `control[ConsolePlayer]`, which holds a command from
  `ticDelay` tics ago. Local UI has no reason to wait for the network.

### What the gate measured

```text
frags 1 and 1; lowest health 0 and 0
400 continuous tics of slot 0, across its death and return
the tape visited 8 distinct tiles
clamped 300 axes, stripped 600 buttons, 0 missing commands
turn 100 forward -100 strafe 100 buttons 1000000...
  (asked for 500 / -900 / 400 and six UI buttons)
800 commands over 400 sequences for 2 slots
both machines finalized byte-identical commands
```

A slot with no keyboard and no socket spawned, walked eight tiles through the
ordinary movement code, shot, scored a frag, and died -- and killed the human
back. Verified to fail by breaking the whitelist: `stripped 0`, two failures.

The netgame section compares the two peers' command traces line by line rather
than comparing digests, because a digest mismatch says only that something
differed, and the first differing line says which slot on which tic.

### The tape is not an AI

`ScriptedProducer` replays a fixed text file: `turn forward strafe [buttons]`,
plus `repeat N` and `loop`. It reads no world state and makes no decisions. It
exists to prove the boundary carries a command for a slot that cannot produce
one for itself. **No AI exists at the end of Phase S**, which was the
milestone's own condition; the AI arrives in Phase B and arrives behind this
same `Producer` interface.

It is wired through the capture harness (`--capture-tape`, `--capture-commands`)
rather than through a game option, because it is test scaffolding and should
not look like a feature. A tape that fails to load is fatal rather than
skipped: a gate that quietly ran with one fewer player than it asked for would
still pass, and would be testing something nobody chose.

### A slot with no peer

`Session::AddAuthoritySlot()` appends a slot the authority owns and no socket
corresponds to -- the shape a bot occupies in Phase B. Its `SlotKind` is `Bot`
because what the *roster* needs to know is "authority-owned, no peer"; what is
actually driving it belongs to the command layer. The S2 drift assertion was
corrected at the same time: it compares peers against **human** slots now,
since counting an authority-owned slot would make the split this phase exists
to create look like a fault.

---

## 10e. Phase S is complete

Each criterion in §3.1, and where it is proven:

| Criterion | Where | Evidence |
| --- | --- | --- |
| `IsArbiter()` no longer refers to `ConsolePlayer`, and no gameplay, spawn, score or GC loop indexes players by peer number | S2 | `Session::IsAuthority()`; 32 loop bounds converted to `ActiveSlotCount()`; §10b |
| A session model can hold a slot no socket corresponds to, and nothing waits on a peer for it | S2, S4 | `--sessiontest`, 106 checks; `AddAuthoritySlot()` exercised by the command gate |
| An offline deathmatch with one human and one placeholder reaches gameplay, spawns two pawns, scores both, and needs no UDP socket | S3, S4 | `test_multiplayer_commands.sh`: two pawns, one frag each, both dead, **0 internet sockets opened during the duel** |
| Existing human multiplayer unchanged and green | all | thirteen multiplayer gates plus twelve single-player gates |
| No variable-length packet byte-swapped or dereferenced before its declared length is validated, over real encoder output | S1 | `--netvectors` golden packet, ASan-proven both ways |
| Every command that reaches the simulation came through `TicCmd_t`; no input path writes pawn state directly | S1, S4 | the pitch write closed; the whitelist and clamp enforced in one finalizer |

Baselines are identical to the ones recorded at S1, through four milestones and
roughly nine hundred lines of change: loopback `5960981e`, determinism 500 tics
`ae626557`.

### What Phase B inherits

- A roster that can name a slot with no peer, and an authority that is a role
  rather than a slot number.
- A command boundary that clamps, whitelists, and derives held state in one
  place, with a `Producer` interface a brain plugs into unchanged.
- A per-slot command trace and a command digest separate from the world digest,
  so "the machines disagree about what was pressed" is a distinguishable
  failure from "the machines disagree about what happened".
- An offline deathmatch to develop against, needing no second machine and no
  socket.
- Rules predicates that answer correctly with no network present, so a bot
  match is a deathmatch by the same rules a networked one is.

### What Phase B must not assume

- `Lifecycle` is a type with no readers yet (§10b). D2 and D3 give it meaning.
- The roster is still built by an adapter from `Net::InitVars`; two counts
  exist, and a debug assertion fails the build if they disagree.
- `SlotKind::Bot` currently means "authority-owned, no peer" and is occupied by
  a scripted tape. B2 gives it a brain; nothing about the roster changes when
  it does, which is the point.
- The ~200 remaining `ConsolePlayer` uses in the renderer and status bars are
  Phase D's, behind a presentation sink. A bot must never need one.

---

# Part III — Phase B: bots

## 11. Bot architecture

### 11.1 Layering

```text
                    AUTHORITY ONLY

  start-of-tic world
        |
        v
  BotSensorAdapter --> BotObservation + remembered contacts
        |                        |
        |                        v
        |               BotDecision / utility
        |                        |
        |                        v
        +--------------> BotNavigation
                                 |
                                 v
                        BotCombat + steering
                                 |
                                 v
                            BotHumanizer
                                 |
                                 v
                        validated TicCmd_t
                                 |
        +------------------------+-------------------------+
        |  canonical command frame / history / broadcast   |
        +------------------------+-------------------------+
                                 |
             ALL PEERS           v
                        ordinary APlayerPawn::Tick
```

### 11.2 Source layout

```text
src/g_bot.h/.cpp            BotManager, lifecycle, brain state, command output
src/g_botperception.h/.cpp  observations, hearing events, memory
src/g_botnav.h/.cpp         map graph, A*, route following, stuck recovery
src/g_botcombat.h/.cpp      target choice, weapon utility, aim/fire controller
src/g_botprofile.h/.cpp     profiles, validation, private PRNG setup
src/g_botdebug.h/.cpp       traces, metrics, developer overlays and commands
```

`g_session.h/.cpp` is delivered by Phase S and is shared. Fewer translation
units are acceptable; fewer *interfaces* are not. New sources go in the explicit
lists in `src/CMakeLists.txt`.

**The bot manager attaches to the session authority, never to `ConsolePlayer`.**
It must construct and run against a session with no local player. This is what
keeps Phase D's re-homing (§32) cheap, and it is testable from B2 onward without
any server existing.

### 11.3 Brain state

`BotState` belongs to `BotManager`, keyed by stable slot, never stored in the
pawn's gameplay statistics:

```text
identity / profile / private RNG streams
high-level state and committed goal
visible contacts and decaying memories
current route and typed transition state
aim observation history and motor state
weapon preference and cadence state
stuck / progress / recovery state
next scheduled sense, think, and path updates
debug counters and last command
```

Store player targets by slot, never by raw pointer. For non-player goals use a
stable map/spawn serial plus class and position. A bot reference must never keep
an actor alive through garbage collection.

### 11.4 The world-access boundary

Only `BotSensorAdapter` and the low-level collision query may read the world.
Decision, goal, combat, and aim code consume immutable observations.

**Allowed:** own pawn status, inventory, ammo, weapon, ready flags, and command;
game rules, public scores, time and frag limits, spawn/death state; static map
topology, door and transporter locations, learned pickup spawn locations;
players currently inside FOV with gameplay LOS; gameplay-generated audible
events within the hearing model; perceived projectiles, hazards, and items;
remembered facts with timestamps and uncertainty; short-range side-effect-free
collision probes used only for locomotion.

**Forbidden:** an unseen enemy's coordinates, velocity, health, armor,
inventory, weapon cooldown, command, queued future command, or target; global
active/inactive state for an unseen pickup; unseen door, forcefield, removable
wall, mine, or laser state; the spawn choice before the engine spawns someone;
future random values or weapon hit results; renderer visibility or camera state;
pointer and iteration-order artifacts; anything that mutates the world.

Static map knowledge is fair — experienced humans memorize these arenas.
Dynamic state is not.

### 11.5 Update rates

| Layer | Cadence | Notes |
| --- | --- | --- |
| Command finalization, immediate collision steering | every tic | always emits one complete command |
| Aim motor integration | every tic | rate/acceleration limits need continuous integration |
| Immediate hazard/projectile response | 1–2 tics | still subject to perception and reaction limits |
| Vision refresh | ~7–35 Hz by profile | staggered across bots |
| Tactical state and utility | ~5–10 Hz | also on material events |
| New A* route | on goal/path invalidation | incremental and budgeted |
| Long-term goal reconsideration | ~2–5 Hz | commitment prevents thrashing |
| Debug metric aggregation | 1–5 Hz | trace raw events separately |

Schedule by `(tic + slotOffset) % interval` so all bots do not search on the
same tic. A critical event may request reconsideration; the global per-tic
budget still applies.

### 11.6 Command production and the safety boundary

Phase S4 delivered the seam:

```text
PollLocalHumanInput(slot, gameplayIntent, localUiIntent)
ProcessLocalUiIntent(localUiIntent)              // never serialized
BuildBotIntent(slot, observation, intent)        // authority only
FinalizeOwnedCommand(intent, wireCmd)
ValidateGameplayCommand(slot, wireCmd)
QueueOwnedCommand(sequence, slot, wireCmd)
GatherOwnedCommands(sequence, wireCmds[])
InstallGameplayCommand(previousApplied, wireCmd, control[slot])
```

An intent exposes no actor mutation: normalized movement, desired turn, and
requested gameplay actions. Finalization and installation clamp axes and yaw,
clear forbidden buttons, convert one-shot requests to a one-sequence pulse,
derive `buttonheld` from the previous applied state, and record provenance in
debug builds.

**Output whitelist.** Permit yaw, forward/back, strafe, attack, use, weapon
slots 1–8 or next/previous, reload once mines are supported, and zoom once the
visor is supported. Explicitly clear escape and pause, automap and Corridor 7
map toggles, status-bar and UI controls, menu keys, unsupported alternate
attacks, and pan/pitch until multiplayer has a synchronized canonical
representation (§9, S1).

`bt_run` is a producer-local modifier: polling converts it into axis magnitude
before the pawn moves, and `ControlMovement` picks walk/run from
`abs(axis) >= RUNMOVE`. Do not serialize it. A bot selects human-range walk or
run magnitudes, and any presentation needing a "running" state derives it from
the finalized magnitude so always-run humans and bots agree.

**Debug assertions.** A bot-owned slot's command has authority provenance; no
axis exceeds its global or profile envelope; exactly one command is finalized
per active slot per sequence; no AI function runs during actor/thinker
iteration; decision code receives observations, not mutable `AActor *`; use and
weapon edges are followed by release; a dead bot emits only an eligible respawn
action; bot code never advances a gameplay RNG stream.

Review must reject any direct write from `g_bot*` to pawn position, angle,
health, inventory, `ReadyWeapon`, `PendingWeapon`, state, or frags, and any
direct call to movement, trigger, pickup, fire, damage, die, or spawn.

### 11.7 Private random streams

Bot variation must never consume the playsim's weapon, damage, spawn, or actor
RNG. Derive per-bot streams from:

```text
match bot seed + stable slot + profile ID + stream purpose
```

Use distinct purposes for at least goal tie-breaking, perception uncertainty,
aim motor noise, movement variation, and cosmetic timing, so an extra roaming
choice cannot change the next aim error. Never use wall-clock time, `rand()`,
pointer values, or frame counters.

### 11.8 Why the authority owns every brain

The authority runs all brains and broadcasts finalized commands. Clients do not
re-run AI; they simulate the resulting pawns. Private brain state therefore does
not have to be bit-identical across machines — only the bounded command enters
the replicated simulation.

A replicated-brain design sends no bot commands but would require perception
iteration and tie-breaking, path-search ordering and budgets, bot RNG schedules,
angle and utility arithmetic, dynamic actor identity, state transitions, and
every future tuning change to stay identical across compilers, architectures,
and mods — with divergence often invisible until a later command changes the
world. Keep it as an experimental optimization only after command bandwidth is
measured, and only behind byte-identical cross-platform command traces. Never
silently mix authority models.

The authority is already trusted to author its own input and match setup, so
this expands no trust boundary.

---

## 12. Navigation

### 12.1 The problem is favorable

The eight arenas are 64×64 tile maps. Corridor 7's translated `GameMap` exposes
per-cell sector, tile, directional solidity, slide amounts, sound zones,
triggers, pushwall state, and Corridor-specific markers, which makes a compact
runtime graph better than a Doom-style navigation mesh.

Build the graph after map translation from the live `GameMap` and the same
runtime actor definitions the player uses — never from raw commercial file
numbers inside the bot. The translation layer is the authority for what a raw
value means.

**The arenas are `MAP51`–`MAP57` and `MAP60`.** `MAP58` and `MAP59` are the
unused "Network Level 9/10" boxes. `src/wl_menu.cpp` and
`tools/test_multiplayer_arenas.sh` already use the correct list; the prose in
[multiplayer.md](multiplayer.md) calling it a contiguous `MAP51`–`MAP58` block
is wrong and should be corrected. Bot gates must use the same authoritative list
as the menu.

| Arena | Cases that must be covered |
| --- | --- |
| `MAP51` | Blue locked door, electric wall cells, invisible laser barriers, masked/removable wall markers, broad weapon set |
| `MAP52` | Electric walls, several invulnerability pickups, masked-wall geometry |
| `MAP53` | Simple geometry, sparse pickups — the baseline map |
| `MAP54` | Laser barriers, many energy charge packs, armor and weapon choices |
| `MAP55` | Electric walls, extensive masked-wall geometry |
| `MAP56` | Four transporter pairs and their field actors |
| `MAP57` | Three transporter pairs |
| `MAP60` | All eight transporter pairs, electric walls, all major weapons |

Most of `MAP51`–`MAP57` also contain ordinary exit switches. Until battle mode
suppresses them, the usable-special classifier must blacklist level exits. A
roam routine that presses every nearby switch must not end the deathmatch.

### 12.2 Three separate concepts

1. **Shared static potential graph** — learnable cells, portals, door and
   transporter locations, possible transitions. It never says an unseen dynamic
   portal is open now, and never contains hidden laser or mine locations.
2. **Physical traversal cache** — the authority's collision truth, used to keep
   pure collision queries correct. Invalidated by world specials. Tactical code
   cannot read it globally.
3. **Per-bot belief overlay** — that bot's perceived and remembered dynamic
   portal, obstacle, item, mine, and hazard state, with timestamps and
   confidence. A planner uses its own overlay, never another bot's discoveries.

The short-range collision oracle may stop a bot from issuing movement through a
boundary it is presently touching — analogous to a human feeling a wall — and
that result may create a contact observation for that bot alone. It must never
become arbitrary-distance tactical knowledge.

**Node record:** stable ID; plane and cell; a reachable standing position
(normally tile center or a validated portal sample); sector and sound zone;
local clearance for the configured player radius; static human-knowable hazard
annotation; known pickup spawn annotations; outgoing typed edge IDs in stable
order.

**Edge record:** stable ID and endpoints; traversal type; base distance cost;
required approach and facing; associated trigger or portal identity; whether its
state can change; expected traversal and wait time; hazard and exposure
annotations.

```text
WalkCardinal  WalkDiagonal  UseDoor  UseSwitchOrField  Transporter
```

Reserve types for pushwalls and elevators only when an arena or supported mod
requires deliberate activation. Use node and ascending edge IDs as deterministic
tie-breakers — never pointer value, hash iteration order, or actor-list order.

### 12.3 Walkability

`C7Player` radius is 22 units in a 64-unit tile. A cell with a sector is not
automatically walkable; a cell with a tile is not automatically blocked forever.

```cpp
TraversalResult QueryPlayerTraversal(
    const APlayerPawn &prototype,
    fixed_t fromX, fixed_t fromY, fixed_t toX, fixed_t toY,
    TraversalQueryFlags flags);
```

It uses the same dimensions and boundary rules as player collision and must not
move an actor, collect an item, fire a trigger, make a sound, open a door, or
touch a thinker. Do not call mutating `TryMove` on a disposable actor and hope
the side effects are harmless — extract and share-test the pure collision
portion.

Graph construction tests cardinal connections at player radius; adds a diagonal
only when the diagonal sweep is valid and cannot cut a corner between two
blocked cardinals; accounts for solid static actors; treats dynamic actors as a
physical-query plus belief problem rather than deleting topology; records a
door/use edge instead of treating a closed usable door as open; represents
traversable damaging volumes with cost, not false solidity; and validates every
smoothed shortcut with the same query.

Parity tests must compare the query against a scripted pawn attempting the same
move in an isolated map. A graph that predicts movement differently from
`ClipMove` is not acceptable.

### 12.4 Doors and usable transitions

Corridor 7 doors are directional, can be locked, open over time, wait, close,
and jam. Battle players receive all keys through ordinary deathmatch inventory,
so a bot opens `MAP51`'s blue door through the same possession and use checks —
never an AI exception.

A `UseDoor` edge is a small state machine: navigate to a validated approach
point on a permitted face; turn through the ordinary yaw controller into the
use-facing tolerance; pulse `bt_use` for one command edge; observe whether the
door actually began opening rather than assuming success; wait or strafe safely
while the boundary is still solid; cross only when the traversal query reports
sufficient opening; time out and replan on a jam, a close, a wrong-side
activation, or an unusable door.

The collision path requires a sliding boundary to be fully open before crossing.
Use that truth, not a visual approximation. The brain never calls `Door_Open`,
`ActivateTrigger`, or a line special.

### 12.5 Forcefields, masked walls, removable walls, pushwalls

Graph build records the underlying portal and its possible transition. World
specials invalidate the authority's physical cache **without** broadcasting into
every brain. Vision, audible events, or a near-field failed traversal update
only the observing bot's belief generation. Each route records the belief
generation it planned against; the follower revalidates physical traversal
before committing to a boundary and only then supplies a local contact result if
belief was stale. A perceived change triggers a bounded replan, never a position
correction. An occupant preventing a wall from closing is a temporary state.

There is a live semantic mismatch among rendered visibility, gameplay LOS, and
projectile collision for some masked walls. Bot perception and attack
feasibility must call the same gameplay queries that decide human hits. Resolve
the mismatch in a focused gameplay regression; do not let bot code invent a
fourth interpretation.

### 12.6 Transporters

Directed edges linking the translated source and counterpart destination while
preserving arrival behavior. The follower approaches and crosses the ordinary
trigger through movement commands, never calls teleport logic, expects the
translated destination and centered arrival, models the 35-tic movement freeze
as traversal time, emits no movement while frozen (firing may remain legal),
clears obsolete steering after arrival, and replans from the actual arrival
position.

Every pair in `MAP56`, `MAP57`, and `MAP60` needs an automated traversal test.
The planner must choose a transporter when it lowers route cost and must not
oscillate through a pair in both directions.

### 12.7 Hazards

Distinguish electric wall IDs that are solid and damage on contact; nonsolid
laser barriers that damage on overlap; mines and splash learned through
perception; and ordinary combat exposure.

Laser barriers are visible only in infrared. A bot without that visor state must
not scan their actors and route around them from the start; it discovers a laser
through contact, damage, or a fair sensory cue, remembers the location, and
prices it into later routes.

```text
cost = expected damage x health/armor urgency x contact probability
     + time exposed + self-trap risk
```

Invulnerability can make a dangerous shortcut reasonable; low health can make
the same edge unacceptable. This changes planning only — damage stays ordinary
gameplay damage.

### 12.8 Items as annotations

Record known spawn location, class/category, and stable identity at map load. A
spawn annotation is not current availability. An item counts as present only
when currently perceived, or when memory says it was present with no contrary
observation, or when a remembered respawn timer makes its return plausible.
Battle items respawn through ordinary inventory actor state and map weapons have
multiplayer stay behavior; item evaluation must use those real semantics.

### 12.9 A* and costs

A conventional compact A* with stable integer/fixed costs. Correctness and
diagnostics matter more than exotic optimization on 64×64 maps.

```text
base geometric distance + expected door/use/wait time + transporter freeze
+ hazard risk + recent edge failure penalty + congestion penalty
+ tactical exposure + excessive turn/reversal penalty
```

Requirements: an admissible heuristic when optimality is required — because a
distant transporter can make Manhattan or Euclidean distance *overestimate* true
cost, **start with `h = 0` (Dijkstra) on every map** and adopt a proven
transporter-aware lower bound only later; stable tie-breaking; bounded
expansions per bot per tic and a bounded authority-wide budget; continuation
state for incremental searches; a clear "no path" result; cancellation when the
goal or belief generation changes; separate workspaces for route planning and
cheap cost estimation; no fixed path length silently truncating a valid route;
counters for expansions, reopenings, budget, and failure reason.

Try a direct validated route first. After A* succeeds, smooth by removing
intermediate nodes only when the player-radius traversal query accepts the whole
shortcut. Retain typed interaction nodes even when geometrically skippable.

### 12.10 Route following

The graph produces waypoints; the locomotor produces human-like commands. Each
tic: choose a short look-ahead target; calculate desired facing without writing
actor angle; blend route and combat intent; reduce forward input for turns too
sharp to take cleanly; use short-range collision feelers; preserve strafe
direction for a commitment interval; exploit ordinary wall sliding instead of
oscillating axes; advance a waypoint only on edge-specific completion criteria;
measure actual progress.

To avoid robotic centerline movement, use a seeded, slowly changing
within-clearance offset in broad corridors — never near tight doors, corners,
hazards, or transporter triggers. Humanization must not turn a good path into
chronic wall scraping.

Player pawns do not currently collide with one another. Local avoidance may look
natural and reduce clumping, but must not treat opponents as impassable.

### 12.11 Stuck detection and recovery

Track desired movement, actual displacement, waypoint progress, collision
results, repeated use attempts, and route generation. The ladder:

1. **Minor obstruction** — keep the goal; reduce forward input and strafe away
   for a short seeded interval.
2. **Corner oscillation** — back up, commit to one side, retry the waypoint.
3. **Closed interaction** — face and pulse use again after a cooldown.
4. **Dynamic obstruction** — invalidate the local edge and replan.
5. **Route failure** — penalize the failed edge, choose another path to the same
   goal.
6. **Goal failure** — abandon with a cooldown, select another goal.
7. **Emergency roam** — pick a visible reachable point to recover a valid graph
   location.

No stage may teleport, noclip, set velocity or coordinates, ignore collision, or
invoke a trigger. Persistent failure produces a trace with map, seed, slot,
position, path, last commands, and obstruction state.

---

## 13. Perception, hearing, and memory

### 13.1 Observations

At each scheduled sense update, build a `BotObservation` from a start-of-tic
snapshot containing values, stable IDs, and timestamps — never mutable actor
pointers:

```text
OwnState  VisiblePlayerObservation  VisibleProjectileObservation
VisibleItemObservation  VisibleHazardObservation  AudibleEventObservation
DamageCueObservation  PublicMatchState
```

All bots sense the same completed world before any current command is applied.
Iterate candidate slots in ascending slot order. Give non-player entities stable
serials before relying on them in ties or memory.

### 13.2 Vision

A player observation requires: active, alive, and targetable under current
rules; not the observing slot; inside the profile's horizontal FOV; gameplay
line of sight through `CheckLine` or its canonical successor; visibility rules
for masked geometry, effects, and equipment; range or contrast limits if
modeled; and perception update and reaction timing.

Never use renderer-marked cells or `ConsolePlayer` camera state — rendering may
not run at all, and it describes one camera, not each bot.

A bot may track a contact for a short grace interval as it crosses the FOV edge,
but must not refresh exact position through a wall. A visible record holds
observed position, facing or velocity only as far as consecutive observations
allow, sighting tic, confidence, and visibility quality.

### 13.3 Reaction queue

Detection and action are separate. A sensory event enters a per-bot queue with a
profile-dependent release tic; the decision layer sees it only when released.
Events needing reaction delay: newly seen enemy; target reappearing or turning
sharply; nearby projectile or hazard discovery; weapon fire heard behind; damage
cue; pickup appearing or disappearing; door or path failure.

An already-tracked target updates at aim-tracking cadence without paying full
acquisition delay again, but still through delayed observed samples.

### 13.4 Hearing

The global `madenoise` Boolean has no source, location, type, or history and is
insufficient. Add a deterministic gameplay event ring emitted at semantic action
points — never by querying the audio mixer, which the server will not have.

```text
event sequence/tic
category (weapon, impact, door, use, pickup, footstep if supported, pain, death)
source slot or anonymous source
world position and sound zone
base loudness/radius
optional weapon family, only if the sound is human-recognizable
```

Per bot, the sensor applies distance, zone and door connectivity, occlusion,
profile perception, and seeded position uncertainty. The released observation
gives an approximate bearing or region, never an exact unseen coordinate.

Start with weapon, impact/explosion, door/use, pain, and death. Add footsteps
only if a human can hear an equivalent sound — do not invent sensory data for AI
convenience. Corridor 7's sound zones matter: a floor word of 0 means no zone,
and nothing can hear anything there.

### 13.5 Damage cues

A bot knows it lost health and may receive whatever directional cue the human
presentation reasonably provides. If the game shows only a damage flash, do not
hand the AI an exact unseen attacker merely because `killerobj` contains one.

Represent: exact damage and resulting own status; approximate bearing if
perceptible; exact source slot only when the attacker was already visible or the
attack itself identifies it; otherwise a high-priority search/evade stimulus
with uncertainty.

### 13.6 Items, lasers, and equipment

Memorize static pickup spawns; never iterate inventory actors to learn which
unseen pickup is active. A perceived pickup record decays to "unknown," not to
"absent." Seeing a location empty, observing a pickup event, or collecting an
item updates memory and a respawn window, using item category semantics rather
than one global timer.

Hidden lasers: without infrared, do not expose them through vision or actor
scans; contact or damage may create a remembered hazard at the experienced
location; with the visor active, expose them through the ordinary vision path;
losing infrared does not erase memory, but memory ages. Visor mode is entered
only through the ordinary zoom/equipment command and consumes ordinary charge.

### 13.7 Memory

Per contact: stable slot; last seen position and tic; a short observed-position
history sufficient for perceived velocity; last heard region and tic; last known
heading or action category if visibly inferable; confidence and uncertainty
radius; and whether the fact is seen, heard, inferred, or stale.

Confidence decays with time and occlusion. Prediction is capped and uses only
observed history. A bot may search the last known location, sweep likely exits
from map knowledge, or abandon the contact. It may never keep an exact lock on a
hidden player. Memory quality is a skill axis; even the highest normal skill has
finite update time and prediction error.

---

## 14. Decision architecture

### 14.1 Hierarchical state machine plus utility

A small explicit state machine gives debuggable control flow; utility scoring
chooses among sensible goals without a brittle maze of conditionals.

```text
DeadWaitingToRespawn  SpawnOrient  Roam  SeekPickup  EngageEnemy
ChaseOrSearchLastContact  RetreatOrRecover  UseTraversal  Unstuck
```

States are not animations and never bypass gameplay; they select an intent that
becomes a command. Global interrupts, in order: dead/respawn lifecycle;
immediate lethal hazard; newly perceived close threat; invalid or stuck
traversal; normal continuation.

### 14.2 Goals and utility

Construct only candidates justified by observations and knowledge: attack a
visible enemy; chase or search a recent contact; obtain health, armor or
invulnerability, a useful weapon, or ammunition/energy/mines/visor charge;
contest a high-value known pickup when plausible; move to a safer or more useful
region; leave a hazardous or dead-end region; roam to a seeded reachable point.
Never create a goal for an unseen actor merely because it exists in the global
actor list.

```text
utility = need x category value x availability confidence
        - route time/cost - expected hazard/exposure - contest risk
        - stale-information penalty
        + personality bias + current-goal persistence + small seeded variation
```

Integer/fixed terms with named debug output. Every selected goal trace shows
candidate scores and rejection reasons. Health value rises nonlinearly as health
falls; ammunition is nearly worthless near capacity or for an unusable family; a
weapon already owned may be worthless under stay-in-world rules;
invulnerability is valuable but not worth repeated lethal traversal; engagement
is less attractive when badly hurt with a credible health route; stale pickups
are discounted; a transporter shortcut carries its freeze and exposure cost.

### 14.3 Commitment

Without commitment, noisy utility makes a bot visibly indecisive. Each goal has
a minimum commitment time unless invalidated or interrupted, a switch threshold
over current-goal utility, a cooldown after failure, a maximum pursuit time, and
explicit completion conditions. Target changes additionally require material
advantage, loss of the old target, or immediate threat — not two distance scores
alternating by one unit.

### 14.4 State behavior

**DeadWaitingToRespawn** — clear target, path, and fire state; observe ordinary
`RespawnEligible`, never force `PST_REBORN`; after a profile delay pulse use;
accept the engine's forced timeout.

**SpawnOrient** — begin with no inherited enemy lock; process new sights and
sounds after reaction delay; choose a short safe orientation goal; receive
invulnerability only if gameplay supplies it.

**Roam / SeekPickup** — follow a committed route; scan on normal cadence;
re-evaluate at completion, invalidity, material threat, or scheduled think.

**EngageEnemy** — maintain a preferred range for usable weapons; combine combat
strafe, line-of-fire movement, aiming, weapon choice, fire gating, and survival
utility; use only visible or delayed remembered samples.

**ChaseOrSearchLastContact** — route to the last seen or heard region; check
plausible exits for a bounded time; expand uncertainty rather than following the
hidden actor; abandon cleanly when confidence expires.

**RetreatOrRecover** — break LOS or route toward a known resource or safer node;
keep fighting when cornered; never use unseen enemy health to decide it can
"finish" them.

**UseTraversal / Unstuck** — execute only typed protocols from navigation, then
return control to the interrupted state.

### 14.5 Fairness check for every input

1. Could an attentive human know this from the HUD, view, sound, or a learned
   map?
2. Is its precision no better than the human presentation supports?
3. Is it delayed by the perception and reaction model?
4. Does acting on it still require ordinary input and game rules?

Any "no" means move the query behind the sensor boundary, degrade it, or remove
it.

---

## 15. Movement humanization

**Motor model.** Maintain state rather than choosing raw axes each tic: current
and desired forward and strafe magnitude; current and desired yaw rate;
acceleration and deceleration limits; strafe side and commitment expiry; short
hesitation timers; locomotion mode (route, combat, avoid, use, frozen, dead).
Rate-limit changes to prevent button chatter. The game still determines actual
speed from pawn properties.

**Walk, run, backpedal.** The planner chooses normalized intent; the profile
maps it to ordinary magnitudes — run for long traversal and combat, walk for
precise door and turn approaches, backpedal only to hold a target or escape an
obstruction. Never compensate a slower class with commands beyond the human
range; the configured pawn class's speed is authoritative.

**Turning.** Derive a desired bearing from route or aim, then pass it through
perception-delayed target bearing, profile maximum yaw speed, yaw acceleration
and deceleration, damping near the target angle, smooth correlated motor error,
occasional bounded overshoot, and conversion to a clamped integer `controlx`.
Large turns take visible time. **The controller never assigns
`APlayerPawn::angle`** — not when stuck, spawning, or using a door.

**Combat movement.** Approach, hold range, circle, retreat, break line of fire,
route to a resource — with committed strafe intervals rather than frame-perfect
mirroring, imperfect reversal timing, reduced precision during large aim
corrections, collision-aware changes near walls, avoidance of self-splash and
remembered mines, and no perfect dodge of an unseen shot. Since player pawns pass
through one another, avoid visibly running through an opponent where practical
without treating them as a wall.

**Mistakes that read as human:** a slightly longer valid route; overshooting a
wide corner and correcting; hesitating at a newly discovered door; holding a
strafe a little too long; missing the globally optimal pickup route; losing route
efficiency while fighting. **Mistakes that read as bugs:** walking into a known
wall, oscillating at a doorway, ignoring a visible lethal hazard, per-tic axis
jitter.

---

## 16. Combat

### 16.1 Target acquisition

Candidates come only from released observations or recent memory; filter dead,
non-shootable, and self. In free-for-all every other live player is an enemy.
Score by immediate threat, angular and travel distance, visibility quality and
recency, whether the target is attacking the bot, line-of-fire opportunity,
current weapon suitability, and the cost of abandoning the current target. Never
score unseen health, armor, inventory, or frag opportunity. Stable slot ID
breaks exact ties.

### 16.2 Corridor 7 aiming reality

Combat here is effectively planar and human yaw is driven through `controlx`.
Most hitscan weapons call `player_t::FindTarget`, which acquires the nearest
shootable target inside roughly a ten-degree cone and then applies normal LOS
and weapon randomness.

**This is the single most important tuning consequence in the whole plan:** an
aim error smaller than the auto-target cone still produces a hit. Bot inaccuracy
therefore cannot be implemented as small reticle noise while firing exclusively
inside the cone. Lower skills must sometimes fire early or late, track the wrong
delayed bearing, or remain outside the acquisition cone entirely. Ordinary
weapon code then decides the hit.

Never call `FindTarget` as a perception oracle, and never inspect the next damage
or random outcome.

### 16.3 Aim and prediction

Keep a timestamped history of perceived target positions; the aimer chooses a
sample no newer than its tracking delay and estimates velocity only from
released observations.

*Hitscan:* aim at the delayed observed position, add motor bias and bounded
tracking prediction, gate fire by profile and weapon confidence.

*Plasma:* estimate lead from known projectile speed and perceived velocity; add
uncertainty proportional to range, target maneuvering, and observation age;
reject or heavily penalize unsafe self-splash shots; still fire only through
ordinary input.

Prediction stops or broadens when the target disappears. No extrapolator may
refresh from the hidden current position.

### 16.4 Correlated aim error

Never draw an independent random angle each tic. Maintain an error state that
drifts toward a seeded bias:

```text
errorVelocity += restoring force toward current bias + bounded noise
errorVelocity = clamp(errorVelocity)
errorAngle    += errorVelocity
occasionally choose a new bounded bias after a dwell interval
```

Scale the envelope with skill, range and apparent target size, target angular
velocity, observer movement, time since acquisition, visibility quality, weapon
family, and recent firing cadence. Allow occasional overshoot and correction.
The highest normal profile must never converge to exact continuous tracking.

### 16.5 Fire gating

Consider whether an allowed observation or memory exists; current facing error
and its trend; normal weapon-ready flags and usable ammo from own inventory;
line of fire; expected self-splash or mine risk; range suitability; acquisition
and trigger reaction timers; burst commitment and release; seeded hesitation.
Request `bt_attack` and let the weapon state machine decide when a shot occurs —
never force `attackheld`, psprite state, cooldown, or ammo.

Intentional imperfection: occasionally pulling the trigger just outside the
ideal cone, holding a burst as the target leaves view, hesitating on a new
target. Bounded and measurable.

### 16.6 Weapon selection

Build an explicit weapon descriptor table — in code or validated data — holding
inventory class, slot input, hitscan/melee/projectile/multi-target behavior,
usable range band, ammo and energy costs from gameplay definitions, cycle and
burst characteristics, projectile speed and splash risk, whether holding fire
helps, switch cost, and bot support maturity.

Utility combines perceived range, target motion, ammo economy, self-risk,
readiness, and personality. Selection is a slot button pulse followed by waiting
for ordinary switch completion. **Never assign `PendingWeapon` or
`ReadyWeapon`.**

Cases needing explicit tuning and tests: bayonet/security taser at melee range;
M16 as the baseline; M343 burst behavior; dual blaster energy and capacity;
shotgun close-range value and long recovery; plasma leading and splash; assault
cannon multi-roll; and the disintegrator's exceptional energy cost and broad
multi-target attack. The disintegrator is not an ordinary single-target hitscan
weapon and needs its own tests.

### 16.7 Mines and visor

Both are staged after ordinary guns are solid.

*Mines:* know own count; choose placement from learned routes and choke points
and current risk, never hidden enemy paths; face and position through ordinary
movement; pulse the existing reload action; clear own mine before arming as
gameplay requires; remember visible and placed mines with uncertainty; price
blast risk by the game's actual radius and through-wall behavior. Never spawn a
mine actor. Tests cover owner-clear timing, shootable detonation, self-damage,
opponent damage, memory, and ammo consumption.

*Visor:* choose a mode from perceived lighting and laser usefulness, but issue
the same zoom action and consume the same charge. Until implemented, leave the
visor in its normal state and accept the perception limits.

### 16.8 Respawn

On death, stop movement, aim, weapon, route, and fire intent; preserve only
profile and the match memory a human could retain. When `RespawnEligible`
becomes true, wait a bounded profile delay and pulse use; the forced timeout is
the final authority. After `Reborn`, reacquire own pawn and inventory, clear
obsolete contacts, and enter `SpawnOrient`. Never choose or alter the spawn.

### 16.9 Gameplay bugs must not be hidden in AI

The source review found that player-owned projectile collision can skip players,
letting plasma pass through an opponent. Fix and test the gameplay path before
tuning weapon utility around plasma performance. The same applies to masked-wall
sight and projectile inconsistencies and to battle exit behavior: those are
gameplay rules. Bot code consumes the corrected canonical result and never
recognizes maps to work around engine defects.

---

## 17. Skill and personality

### 17.1 Separate axes

One menu difficulty maps to many internal traits. Do not collapse it to one
accuracy number.

```text
reactionMinTics / reactionMaxTics      visionUpdateInterval
hearingAccuracy / hearingRangeScale    memoryHalfLife / searchPersistence
maxYawRate / maxYawAcceleration        aimErrorRange / aimErrorVelocity
trackingDelay / predictionQuality      triggerDelay / burstLength / releaseDelay
movementAcceleration / routeLookAhead  strafeCommitRange / reversalDelay
goalThinkInterval / goalSwitchThreshold pathSearchBudget / tacticalLookAhead
riskTolerance / pickup biases / weapon preferences   respawnDelayRange
```

Skill governs quality and motor and sensory limits. Personality prefers
aggression, resource control, weapon families, risk, or roaming patterns without
making one profile objectively superhuman.

### 17.2 Provisional shipped levels

Starting hypotheses, not promises. All reaction values are *additional* to the
match's input delay.

| Trait | Recruit | Marine | Veteran | Elite |
| --- | ---: | ---: | ---: | ---: |
| New-target reaction | 24–45 tics (343–643 ms) | 17–32 (243–457 ms) | 12–24 (171–343 ms) | 10–19 (143–271 ms) |
| Vision refresh | 7–10 Hz | 10–14 Hz | 14–20 Hz | 20–28 Hz |
| Max yaw rate | 140–210°/s | 190–260°/s | 240–310°/s | 280–350°/s |
| Max yaw acceleration | 600–900°/s² | 850–1,300°/s² | 1,200–1,800°/s² | 1,600–2,400°/s² |
| Static aim-error envelope | 8–16° | 5–11° | 2.5–7° | 1.5–5° |
| Tracking delay after acquisition | 10–22 tics | 7–16 | 4–11 | 3–8 |
| Tactical reconsideration | 4–6 Hz | 5–7 Hz | 6–9 Hz | 7–10 Hz |
| Search memory | 2–5 s | 4–8 s | 6–12 s | 8–15 s |
| Strafe commitment | 0.5–1.5 s | 0.6–1.6 s | 0.7–1.8 s | 0.7–2.0 s |
| Respawn hesitation | 18–55 tics | 12–40 | 8–28 | 6–22 |

Qualifications:

- Degrees per second are easier to review than raw `controlx`, but the code must
  derive and test the exact conversion `ControlMovement` uses. At 70 Hz,
  `controlx * (ANGLE_1 / 20)` with the canonical ±100 range imposes a hard
  **350°/s ceiling**; no profile may exceed it unless that command range is
  deliberately changed for humans and bots together.
- Aim error expands with range, movement, occlusion, tracking age, and target
  angular velocity. The table is not a constant random cone.
- The auto-target cone (§16.2) means these values will not map linearly to hit
  percentage.
- Elite is deliberately fallible: finite reaction, nonzero error floor, bounded
  turn rate, imperfect prediction, nonzero decision noise.
- Ranges vary by stable personality and seed, not by a fresh draw every tic.

### 17.3 No statistical cheats

Every profile uses the same pawn class and properties, command range, movement
and collision, health and armor, damage and spread, ammo consumption, pickup and
key rules, spawn and respawn rules, tick rate, and input-delay schedule.
Difficulty is never implemented by multiplying outgoing damage, reducing
incoming damage, granting ammo, increasing speed, shortening weapon states,
enlarging LOS through walls, or reading hidden state.

### 17.4 Performance is a distribution

Avoid a target like "50% accurate." Evaluate distributions by weapon, range,
movement state, visibility, and skill: acquisition latency; target-switch
latency; yaw velocity and acceleration; angular error at trigger time; burst
length and release delay; accuracy and damage per shot; path efficiency; time
stuck; resource choices and goal changes; exposure before retreat; search
duration after loss; frags over many seeds.

A bot that misses half the time by alternately snapping perfectly and firing 90°
away is not human-like. The time series and the circumstances matter.

### 17.5 Fairness ceiling

The highest normal profile must satisfy: no event released on the same tic as a
previously unknown stimulus; no instant 180° turn; no exact tracking of an
occluded target; no zero-variance aim lock; no perfect projectile dodge on the
first possible tic; no knowledge of unseen item availability; no target choice
from unseen health; no 100% accuracy in a sufficiently large contested test; no
action outside the canonical command interface.

A developer-only `Perfect` profile may exist for isolated mechanics tests. It
must be explicitly named, unavailable in ordinary menus and lobbies, and never
cited as evidence of shippable quality.

### 17.6 Calibration

Capture human `TicCmd_t` streams and combat events opt-in in local test matches;
derive broad anonymized distributions for yaw speed and acceleration, movement
commitment, reaction, trigger error, and burst cadence; tune motor limits into
plausible human percentiles rather than copying one player's quirks; run seeded
duels and mixed playtests; inspect traces for *why* misses, switches, and route
choices occur; adjust one trait family at a time with recorded before-and-after
metrics; keep deterministic regressions separate from probabilistic benchmarks.

Human captures are opt-in, local by default, carry no personal identifiers, and
are never silently uploaded.

---

## 18. Interface, configuration, administration

### 18.1 Lobby

Extend host setup with expected human players (including host), bot count, bot
skill (Recruit, Marine, Veteran, Elite), the existing arena/rules/class/limit
fields, and a derived **Total slots** validated against the supported cap.

Start is allowed when at least one local human exists in an interactive match,
at least two slots are occupied, all expected humans have joined, the total is
within the cap, every class and profile is valid, and all peers acknowledged the
same locked roster.

Build the explicit per-slot roster internally even if the first UI assigns
humans then bots. A later lobby can expose each row as `Human`, `Open`, `Bot`,
or `Closed`. Joining clients see the roster and bot configuration read-only and
never instantiate a brain.

### 18.2 Offline skirmish

The multiplayer menu offers a "Skirmish" path creating a deathmatch roster with
one local peer and no socket wait. It is the same session with `peerCount == 1`
— do not duplicate setup in a separate single-player path.

### 18.3 Names and identity

Identity belongs in the session roster; `player_t` has no name or bot metadata
model. Requirements: a stable display name for the match; stable slot and bot
marker; valid class and appearance; duplicate-name disambiguation; length and
character validation before network or display use; and no name used as a
programmatic identity.

Ship original project-owned generic or numbered names such as `Bot 1`. Do not
copy Zandronum's persona names or data.

### 18.4 Profiles

Start with validated built-in profiles so behavior work is not blocked on a
parser. If profile lumps are added later: a versioned schema with documented
units and ranges; rejection of unknown mandatory fields, invalid enums,
duplicate IDs, NaN, overflow, and out-of-range values; canonical profile data
hashed into the match compatibility setup; no executable code or native
libraries loaded from a profile; absolute fairness clamps applied *after*
parsing; and a missing profile ID as a startup error, not a per-peer fallback.

### 18.5 Controls

```text
--bots <count>                 scripted/headless setup
--bot-skill <name-or-index>    profile mapping
--bot-seed <integer>           developer reproducibility override
bot_list                       roster / controller / profile / state
bot_debug <slot|all>           select diagnostics
bot_fill                       lobby or match-boundary fill
bot_remove <slot|name|all>     lobby or match-boundary removal
```

Note the standing hazard: EC7Wolf has several independent argv scanners and only
the last has a catch-all, so an option that is merely peeked at becomes a
filename. Register these in the same scanner as the other gameplay options.

Live `addbot`/`removebot` refuse while the playsim is active and explain that
roster changes happen at match boundaries. Bot administration is authority-only;
a remote client's request is rejected or routed through a future authorized
lobby protocol, never applied to its local roster.

### 18.6 Presentation

Every normal presentation path uses roster identity: scoreboard row, name,
frags, deaths, class and color; a `[BOT]` label or icon; kill and death
messages; end-of-match tally; lobby roster; debug listing. Bots never get a
separate score table — `player_t::frags` and the ordinary result code stay
authoritative. Chat taunts are deferred; silence beats copied or repetitive text.

### 18.7 Limits

`MAXPLAYERS` is 11 while the Corridor 7 menu exposes a smaller human-facing
range. Decide and document the supported total-slot cap from actual gameplay,
network, and UI tests. The bot system introduces no additional arbitrary cap and
must test the chosen maximum. Command-line and menu layers validate counts
before narrowing or indexing, and errors state human count, bot count, total,
and supported maximum.

---

## 19. Determinism, diagnostics, and performance

### 19.1 The boundary

- **Not replicated:** bot memory, utility scores, open lists, aim-noise state,
  private PRNG.
- **Replicated input:** the finalized bot `TicCmd_t` for an explicit slot and
  sequence.
- **Replicated simulation:** pawns, actors, inventory, map specials, damage,
  score, time.

Every peer receives byte-equivalent canonical commands for every active slot. A
bot bug may make a bad decision; it must never create a decision disagreement
between nodes.

### 19.2 Recording and replay

The legacy demo format records a subset of one local player's input and bypasses
the network path. Leave it unchanged and explicitly unsupported for mixed bot
multiplayer. Design a versioned multiplayer command recording only after the
command bundle and roster protocol are stable, recording the canonical roster,
rules, map and data hash, protocol version, match seed, input delay, and the
final command for every active slot and sequence. **Replay recorded commands;
never re-run a historical AI implementation.** Include periodic state digests
and explicit truncation handling. This gives a powerful bug reproducer without
making replay depend on private brain serialization.

### 19.3 Saves

Multiplayer saves are disabled today. Keep offline bot-deathmatch saves
explicitly unsupported in the first release. If enabled later, the archive must
carry the roster and controller kinds, profile IDs and private RNG state, state
machine and timers, perception and memory with stable identities, goal and path
state (or enough to rebuild safely), aim and motor state, world-event queue
position, and version migration. Never serialize raw actor pointers, and never
silently reset a brain on load in a way that grants or loses knowledge.

### 19.4 Trace

An opt-in authority trace in JSON Lines or another streamable stable format,
covering roster/profile/seed initialization; sense updates and released events;
memory updates and expiry; state transitions; goal candidates, scores, selection
and rejection; path request, result, cost, expansions, invalidation; typed
traversal progress; target acquisition, loss, switch; ideal bearing, delayed
bearing, aim error, yaw command; weapon candidates, choice, fire decision; stuck
detection and recovery phase; final command and validation result; damage,
death, respawn, frag observations; periodic CPU and budget counters.

Every record carries match/session ID, map, seed, slot, command sequence, and
tic as applicable. Off by default, and it must not change timing-sensitive
results or PRNG advancement.

```text
--capture-bots <path-or-prefix>
```

Anchor measurements to tics, not frames — the project has been bitten by this
before. Also support a compact canonical command/state digest for gates.

### 19.5 Overlays and console

A developer overlay may show, for one selected bot: walkable nodes and typed
edges; current path, smoothed segments, waypoint; collision feelers; state and
goal; top utility candidates; FOV, contacts, last-seen and last-heard regions,
confidence; ideal, delayed, and commanded aim with the error envelope; weapon
utility and fire-gate reason; stuck counters; per-layer timing. **The bot never
reads the overlay, render visibility, camera, or screen coordinates.**

Console categories with slot filters — `bot_debug_state`, `_sense`, `_goal`,
`_path`, `_move`, `_aim`, `_weapon`, `_command`, `_timing` — so state changes
and failures are visible without per-tic flooding. A one-line summary states
slot, name, profile, state, goal, target, waypoint, health, weapon, last
command, and stuck status.

### 19.6 Simulation digest

Extend test-only comparison beyond actor positions: active roster hash and
rules; command sequence and canonical commands by slot; relevant gameplay RNG
state; player state, health, frags, inventory, ready and pending weapon; actor
identity, class, position, angle, health, flags, state; item active and respawn
state; door, pushwall, forcefield, and transporter mutable state; match timer,
limit, and result; plus the bot-command digest on the authority. Stable ordering,
fixed-width encoding, and a report naming the **first divergent component**, not
one opaque checksum.

### 19.7 Budgets

Measure on a documented low-end system in an optimized release build. Targets:
fixed bounded command/motor work per bot per tic; bounded, staggered vision
scans; capped A* expansions per bot and globally; no allocations in the 70 Hz
command path after map init; shared graph memory independent of bot count; a
documented per-bot state bound; ten bots not causing the 70 Hz playsim to miss
its budget; and p95/p99 AI time plus worst-case expansions captured in soak
output.

Never hide an overrun by skipping required command output or by using
wall-clock-dependent behavior. Defer a tactical think or continue an incremental
search deterministically while command generation stays complete.

### 19.8 Failure diagnostics

A fatal consistency failure identifies session and protocol version, map and
data hash, match and bot seed, peer and slot ownership, expected and received
sequence and mask, profile ID, last good digest, and trace location. A
navigation or AI failure degrades to bounded safe roaming, never corrupting
network state. A malformed packet or ownership violation is a network error,
rejected before it reaches the bot.

---

## 20. Phase B milestones

### B1 — Authoritative multi-slot command transport

**Purpose:** carry commands the authority owns for more than one slot, over the
wire. Phase S4 proved the seam in process; this proves it on a network.

**Work**

- Extend the tic exchange so the authority sends a bundle covering every slot it
  owns — its local human plus every bot slot — instead of one address-implied
  command. Bump the S1 protocol version.
- Per-slot history, gather mask, and resend integration for every owned slot.
- Validate sender ownership, axis range, button whitelist, and sequence on
  receipt. A remote peer claiming a bot slot is rejected.
- Canonical per-slot command trace and digest across peers.
- Drive it with S4's `ScriptedProducer`, not AI.

**Exit gate**

- Two processes run a mixed roster of one human and one scripted tape; both
  report byte-identical per-slot commands and identical world digests under
  induced delay, loss, duplication, and reordering.
- A remote-submitted bot-slot command is rejected and logged.
- Version mismatch is refused with a clear message.
- No AI code exists beyond the scripted producer.

### B1 record

**The plan named three things this needed and there were four.** "Extend the
tic exchange so the authority sends a bundle covering every slot it owns" is
necessary and not sufficient: on the first networked run the host had three
slots and the client had two. A slot with no peer cannot be *inferred* from an
address list -- it exists because the authority says so, and until it says so
on the wire it exists on exactly one machine, which is one machine's worth of
extra pawns and an immediate disagreement about how many commands a tic needs.
`NewGamePacket` carries the authority's slot table now, and every peer adopts
it at roster lock.

**On the wire.** `TicCmdPacket` became `TicCmdBundlePacket` and the protocol
version went to 3. A sender names the slots it speaks for instead of implying
one from its address. `buttonheld` came off the wire entirely: S4 derives it at
installation, so sending it was sending something the receiver overwrites, and
handing a hostile sender a field to lie in for no purpose. The buffer is keyed
by slot rather than by peer -- those were the same array because they were the
same thing.

**The zero-delay path is gone**, and this is a simplification rather than a
removal. It was a synchronous exchange that sent the command for the tic about
to run and blocked on an acknowledgement; the delayed ring stamps for
`TicSeq + 0 + 1`, which is the tic about to run, and blocks until it has
arrived. Two implementations of one idea, and only one of them was ever going
to learn about slots that own no socket. Zero delay is still a menu option and
still passes the loopback gate at the same checksum.

**Ownership could not be tested from outside the game.** An unknown sender is
refused long before ownership is consulted, so a forged datagram proves
nothing. The check is exercised by a genuine, connected peer misbehaving on
purpose (`--capture-forge-slot`, test scaffolding): the host refused 94
commands for a slot the sender did not own, and the world was unaffected.
Breaking the check makes the gate fail exactly where it should -- the two
machines diverge at tic 13, on precisely the forged slot.

**Impairment gained duplication.** `netdelay.py` had delay, jitter and loss.
Duplication is the impairment a lockstep game is least likely to be tested
against and most likely to get wrong, because a resend that arrives twice has
to be idempotent and a receiver that stores both copies fills its ring with one
sequence. The gate runs at 25 ms delay, 12 ms jitter, 3% loss, 8% duplication,
and both machines still finalize byte-identical commands.

### The bug the gate suite caught, and the one I nearly believed

**Sender-side sanitization was missing.** B1 made a receiver refuse any bundle
containing a button that is not a gameplay control -- correct, and the same
rule S4 applies at installation. But the host put its *raw sampled* command on
the wire:

```cpp
authored = control[slot];   // everything, including bt_scoreboard
```

So the moment a player held the scoreboard key, every peer refused every bundle
from them and **the match stopped dead**. Not a cosmetic failure: a hang. Every
manual networked test passed because none of them held a UI key;
`test_multiplayer_presentation.sh` holds one deliberately, to photograph the
scoreboard, and caught it.

The asymmetry was the mistake. Producers went through `ProduceForWire()`, which
sanitizes; sampled input took a different route to the same wire. There is one
function now, `SanitizeForWire()`, and the comment above it says what
forgetting it costs.

**And a measurement I contaminated.** Diagnosing that failure, I ran three
overlapping copies of a gate that uses a fixed display and fixed ports. The
second and third collided with the first: every host log truncated identically
at startup, no client logs at all. I read that as "the fix did not work" when it
was "the test environment is no longer valid". Only the first run -- the clean
one -- was evidence, and it had already identified the bug correctly.

Two rules follow, and both are about the harness rather than the engine: gates
with fixed ports and displays cannot be run concurrently with themselves, and a
failure whose signature changes between runs is a fact about the harness before
it is a fact about the code.

### A pre-existing defect found on the way, and not fixed here

`GameMap::GenerateDeathmatchStarts()` can choose a cell a player cannot leave.
On `MAP51` a third slot spawned at tile (1,37), against the map edge, and did
not move for a hundred tics with full forward held. The generator requires a
cell to have a sector and no wall tile and to be five tiles from another start;
none of that establishes that the cell connects to the rest of the arena.

This is not a B1 defect -- it predates every milestone here and affects a third
*human* player identically -- and the arenas gate does not catch it because it
tests two players, which take the first two starts. It is recorded here rather
than fixed because folding an unrelated map-generation change into a transport
milestone would make both harder to review. It wants its own change, and a
reachability check (flood fill from one start) rather than a spacing check.

### B2 — Bot manager, lifecycle, basic locomotion

**Work:** `BotManager`, per-slot state, private PRNG streams, update scheduling,
command validation and provenance, death and respawn lifecycle; base tile graph
and the side-effect-free traversal query; stable integer A*, direct route,
smoothing, basic follower, progress and stuck diagnostics; `SpawnOrient`,
`Roam`, `UseDoor`, `Unstuck`, ordinary respawn; graph, path, and state overlays
and trace.

**Exit:** a bot spawns, roams simple regions, uses a normal door, dies, and
respawns through input; it never mutates actor state outside commands; the
manager constructs against a session with **no local player**; synthetic
navigation parity tests and a `MAP53` roam baseline pass.

**Status: complete.** See the B2 record below.

### B2 step 5 record — doors, unstuck, respawn

**The arenas have one door.** Not one kind of door: one door, at `MAP51`
(25,38), in all eight of them. `MAP52`, `MAP53`, `MAP54`, `MAP55`, `MAP57` and
`MAP60` contain none. That number is why this step ships with a named-goal test
affordance rather than a roam baseline: one cell in 960, behind a 600-cost
edge, is not a cell a random walk visits during a match.

**A correction to something I asserted while planning step 4.** I reported that
`MAP60`'s graph came apart into five regions because doors were not edges yet.
That was wrong, and measuring it was what showed it. `MAP60` has no doors; it
has *sixteen transporters*, and those are what separate its regions. Door edges
merged `MAP51` from two regions into one and changed no other arena by a single
node. Reconnecting the fragmented arenas is B3's transporter work, not this
step's.

Region counts are now a measurement rather than a claim -- `Graph::Regions()`,
reported in the `--capture-nav` header:

| Arena | Nodes | Regions | Largest | Doors | Transporters |
| --- | ---: | ---: | ---: | ---: | ---: |
| MAP51 | 960 | **1** (was 2) | 960 | 1 | 0 |
| MAP52 | 1230 | 1 | 1230 | 0 | 0 |
| MAP53 | 1394 | 1 | 1394 | 0 | 0 |
| MAP54 | 1338 | 1 | 1338 | 0 | 0 |
| MAP55 | 1005 | 5 | 970 | 0 | 0 |
| MAP56 | 1498 | 5 | 970 | 0 | 8 |
| MAP57 | 1480 | 2 | 1153 | 0 | 6 |
| MAP60 | 545 | 5 | 274 | 0 | 16 |

`MAP55` has neither a door nor a transporter and is still in five pieces, so
something else divides it. That is B3's to find; recording it here so it is not
discovered twice.

**Planning asks a different question from moving, and the difference is a rule,
not a write.** A closed door is not somewhere a body can stand, and
`CanOccupyTile` is right to say so. A planner needs to know where a body could
stand once a door it is allowed to open has opened. The first implementation
answered that by opening the door, asking, and closing it again -- a query
mutating simulation state, which is exactly what `g_traversal.h` promises not
to do. It is a field on the body instead: `openDoor` plus the faces that
actually slide, read by the same wall test the pawn obeys.

**Two bugs the region count caught immediately.** Treating door cells as
standable initially made *every* cell standable -- 4096 nodes on a 64 by 64
map -- because a body of radius 22 at the centre of a 64-unit tile reaches none
of that tile's own faces, so nothing collides and every wall answers yes. The
guard that rejects wall tiles is the only thing that ever refused them, and the
door path had walked around it. Having the region count in front of me turned
that from a subtle wrong-routes bug into an obvious one.

**Pressing use twice shuts the door.** `Door_Open` hands an already-open door to
`Reactivate`, which closes it. A follower that pulses use while waiting
therefore opens the door and shuts it again, forever. From outside this is
indistinguishable from a door that will not open -- and the instrumented engine
reported the trigger firing 292 times while the boundary was never once
crossable. The protocol presses once and then watches, re-pressing only after
105 tics of nothing. This is what §12.4's "observe whether the door actually
began opening rather than assuming success" is protecting against, and it is a
sharper hazard than it sounds.

**The crossing test cannot be asked from inside the doorway.** `pawn -> door`
is a step to itself once the pawn is in the door cell, and a door cell still
holds a tile, so `CanOccupyTile` refuses it and the protocol never notices it
has succeeded. Standing in the doorway is checked first, and success advances
the route past the door node -- without that the follower hands back a waypoint
that is still the door, re-enters, succeeds again, and reports one door opened
517 times in a single match.

**The lock is enforced through ordinary possession, and it is satisfied.**
`MAP51`'s door is lock 2, RED, requiring `C7Static001`. Battle players spawn
holding both access cards: a battle player reports `cards RB` at spawn where a
single player reports `cards --`. So the bot passes the same `P_CheckKeys` a
human passes, with no AI exception, and the gate would fail rather than quietly
test an unlocked door if that ever changed. I briefly concluded the opposite --
that battle granted no keys -- on the strength of a grep that found no granting
code; the inventory at the moment of use is what settled it.

**Unstuck moves before it replans.** A route is a function of where the bot is
standing, so replanning from the corner it is wedged in returns a route that
begins by walking into the same wall. It backs off and turns for 24 tics first.
Exercised twice on `MAP60` in a 2400-tic match.

**Respawn is a keypress.** The engine respawns a dead player on `bt_use` once
`RespawnEligible` passes, and gives up waiting 100 tics later -- so a bot that
pressed nothing would still come back, always late and never by its own doing.
It presses use, pulsed for the same reason a door is.

**The axis rule is redundant, like the corner rule.** A door may only be
entered along the axis its panel slides on. Removing that check from the
builder leaves `MAP51`'s graph byte-identical -- same 5822 edges, same digest
`ca9f4b5e` -- because the sampled sweep already refuses an off-axis step: only
the sliding pair of faces is opened for planning, so the jambs stay solid and a
step across one collides. Kept and labelled as the guarantee it is, in the same
terms §12.3's corner rule is, rather than left in implying it does work it does
not currently do.

**Gates:** `tools/test_bot_doors.sh` is new. A bot routed through the door
opens it and arrives; a bot routed to the near side of the same door never
touches it, which is what distinguishes a door protocol from a bot that presses
use constantly; one press, not a train; and the same match twice produces the
same brain. Proven able to fail by restoring the pulse train: 292 presses, 0
doors opened, four checks red.

`tools/test_bot_navigation.sh` learned what a door is, from the map's own
triggers rather than from the graph, so that "the graph thinks this is a door"
and "this is a door" stay separable. It now checks the claim both ways -- every
600-cost edge touches a door, and every edge touching a door costs 600 -- since
only the second catches a door quietly priced as an ordinary step. Proven able
to fail by pricing `COST_DOOR` at 100.

### B2 record — the milestone closed

Every exit criterion, and what shows it:

| Exit criterion | Shown by |
| --- | --- |
| a bot spawns | `test_bot_roam.sh` |
| roams simple regions | `test_bot_roam.sh` — MAP53, MAP51, MAP60 |
| uses a normal door | `test_bot_doors.sh` |
| dies, and respawns through input | `test_bot_lifecycle.sh` |
| never mutates actor state outside commands | `test_bot_lifecycle.sh`, source check |
| constructs against a session with no local player | `--bottest`, `test_multiplayer_session.sh` |
| navigation parity tests | `test_bot_navigation.sh`, `test_bot_traversal.sh` |
| a MAP53 roam baseline | `test_bot_roam.sh` |
| graph, path, and state overlays and trace | `test_bot_overlay.sh`, `--capture-bots` |

**Respawning cannot be seen by watching it happen.** The engine returns a dead
player to the world on `bt_use` once `RespawnEligible` has passed, and gives up
waiting a hundred tics later. So a bot that pressed nothing still comes back --
always late, never by its own doing -- and "it respawned" is not evidence of
anything. The latency is: measured at 72 tics as shipped and 171 with the press
disabled, against the engine's 70 and 170. The gate asserts under 100, which is
the only form of this check that can fail.

Killing a bot needed `--capture-kill-slot SLOT TIC`, through `TakeDamage`
rather than by assigning health, so the lifecycle that runs is the one a real
death runs. Nothing in a B2 arena can otherwise kill a bot: they have no combat
until B6, and nothing else has a reason to shoot them.

**The overlay is three things** -- routes, the graph they were planned on, and
what each bot thinks it is doing, on debug key J or `--capture-bot-overlay`.
It reads bot state through copies and can write none of it, which is the
property `test_bot_overlay.sh` checks first: same seed and tic count, the world
checksum and the brain digest are identical at every level. A debug view that
perturbs what it shows is worse than none, because it sends you hunting a bug
that exists only while you are looking.

**And a gate that could not fail, caught by its own control.** The three checks
that the overlay actually draws compared rendered frames, and passed against a
build with the drawing disabled outright. The frames were not reproducible:
the view is interpolated between tics by a fraction that depends on how fast
the frame arrived, so two identical runs snapshotted at the same tic differ.
The gate now runs with `R_Interpolate = 0` and asserts *first* that the same
level twice renders the same frame -- without that control, "the overlay drew
something" and "frames are noise" are the same observation. With it, disabling
the drawing fails two checks and the control still passes.

This is the only gate in the milestone that went green on the very fault it was
written to catch, and it was found the same way the others were checked: by
breaking the code on purpose and expecting red. Worth separating from the two
neighbouring cases it resembles and is not. The door gate never falsely passed
-- it was written after the pulse-train fix and fails on it. And the navigation
gate's axis check cannot currently fail at all, but that is a redundant
guarantee held up by the sweep, not a broken test: it asserts something true
that nothing is presently able to violate.

The distinction that matters: a check that cannot fail because the property is
over-determined is fine and should be labelled. A check that cannot fail
because it is measuring noise is worthless and looks exactly like a passing
test. Only running it against a deliberately broken build tells them apart.

### B3 — Complete arena traversal

**Work:** physical-cache invalidation plus per-bot belief for doors,
forcefields, walls, and pushwalls; transporter edges, freeze handling, and
post-arrival replan; hazard annotations, costs, and local dynamic avoidance;
the full stuck-recovery ladder and route-failure cooldowns; exercise every real
arena start, region, and special.

**Exit:** all eight arena traversal tests pass over multiple seeds and spawns;
every transporter pair is exercised; no permanent stuck state within the soak
threshold; battle exit switches are never activated.

**Status: complete.** See the B3 record below.

### B3 record — what actually connects these arenas

**Transporters, and the correction they force.** Adding transporter edges is
what makes three arenas whole:

| Arena | Regions before | after | Largest region | Pads |
| --- | ---: | ---: | ---: | ---: |
| MAP56 | 5 | **1** | 970 → 1498 | 8 |
| MAP57 | 2 | **1** | 1153 → 1480 | 6 |
| MAP60 | 5 | **1** | 274 → 545 | 16 |

MAP60 roaming coverage went from 75 tiles to 176 over the same match.

**MAP55 is not fragmented, and never was.** It has no doors and no
transporters and stays in five pieces. Four of them are 14, 13, 4 and 4 cells:
strips sealed behind masked walls -- markers 104 and 105, which change a wall's
rendering and sight behaviour and leave it solid. 970 of its 1005 cells are one
region and the other 35 are decoration no player can reach either. Any arena
check therefore measures the share of cells in the largest region, not whether
there is exactly one; demanding one region fails a correct map.

**Entering a transporter is the whole interaction.** `CheckWalkTriggers` fires
on crossing into a tile, from any side on every shipped pad, so a route cannot
walk across one and continue -- the body is elsewhere before it takes another
step. The search models that: a pad reached by walking has exactly one way
onward.

What that turns on is *how the pad was arrived at*. Arriving by teleport leaves
the body standing on it with nothing fired, free to walk off in any direction.
Treating that the same as walking in forces an immediate second teleport, and
MAP60's 545 cells collapse into reachable pockets of 27, 57, 170 and 280 -- an
arena that cannot be walked around. The implausibility of those numbers is what
exposed the bug; the fix is to record the edge type each node was reached by.
Every cell now reaches all 545.

**The bounce.** A relative teleport applies its offset to wherever the body is
when the trigger fires, which is often a tile short of the pad, and on MAP56
that lands directly beside the pad that sends it back. Bots ping-ponged every
38 tics -- freeze, three steps, back again -- for as long as the match ran.

Three fixes went in before one of them worked, and the first two were inert:
the assignment that set the cooldown had been lost to an aborted edit, so
`avoidTransporters` was never true. Worth recording as a diagnostic lesson --
three consecutive changes produced byte-identical traces, and identical output
across a real change is evidence the change is not running, not evidence it did
not help.

The fix that worked has two parts. Avoidance covers the pad *and the ring of
cells around it*, because the trigger fires when the body comes within one
movement step of the boundary rather than on entry. And the unrestricted
fallback applies only when no goal anywhere is reachable under the restriction,
not per candidate: goals are drawn from the whole map, most are across a
transporter, so a per-candidate fallback succeeds every time and the route goes
straight back through the pad.

**Hazards, and an honest null result.** Corridor 7 energizes wall IDs 6 and 14:
solid, two damage per 35 tics of contact. MAP51, MAP55 and MAP60 have 19, 10
and 14 such cells. Cells touching one are annotated and priced at +200, about
two tiles of detour, which is section 12.7's cost with urgency and contact
probability held at one until health and armour are modelled.

It changes routes and does not change outcomes. Measured health lost across
three bots over 1400 tics on all three maps, with the cost and without: **zero
either way**. Bots do not touch these walls, because the follower routes centre
to centre and the traversal query already keeps a 22-unit body clear of
geometry. The annotation is 1-4% of edges and is kept as the baseline the plan
asks for, but no benefit has been demonstrated and none should be claimed until
combat pushes bots into contact.

**The recovery ladder** now escalates rather than doing one thing. A first
failure gets a nudge -- keep the route, strafe out of it, retry the same
waypoint. A second records the cell in a short per-bot memory that prices it up
in that bot's searches and nobody else's, and backs up properly. A third gives
the goal away with a cooldown. The stage resets on progress, so three failures
means three at the same obstruction.

That memory is checked in the data-free self-test rather than by playing,
deliberately: player pawns do not collide in this game, so nothing routinely
blocks a bot and a healthy match never reaches these rungs. Code that only runs
when things go wrong cannot be left to be exercised by luck.

**Exit switches.** Every arena has an `Exit_Normal` on a wall tile, playerUse,
that ends the match for everyone. Bots press use in two places -- at a door
they are opening, and while dead asking to respawn -- and neither can reach
one: a dead player never runs `Cmd_Use`, and the door protocol only presses
square-on to a door. That is an accident of what bots currently do rather than
a property, so `test_bot_arenas.sh` asserts every match runs its full length,
which a fired exit would cut short.

**The exit criteria, measured.** All eight arenas on two seeds, three bots,
900 tics each: every match ran its full length, no step the graph offered was
refused, no bot ever failed to find a goal, and coverage ran 147 to 298 tiles.
Connectivity is 100% of cells in the largest region everywhere except MAP55,
which is 96% for the reason above.

Every transporter pair is exercised by naming each pad as a goal in turn --
thirty of them across MAP56, MAP57 and MAP60 -- because roaming visits only a
handful per match. Walking onto a pad is the crossing, so the bot never
"arrives": it is somewhere else before the arrival check runs, and that is the
event being counted.

The budget is part of that test's correctness, which the first version got
wrong. At 450 tics a pad, MAP56's western pair came back as never crossed; they
sit at the far edge of a 1498-cell arena and a bot spawning across the map
spends most of that walking. At 1200 the same bot crosses one of them seventeen
times. A coverage check that is too impatient reports a working thing as
broken, in exactly the language of a real failure. The sweep runs at 700 and
takes about seven minutes, nearly all of it process startup rather than
simulation.

**Gates:** `tools/test_bot_transporters.sh` and `tools/test_bot_arenas.sh` are
new. `test_bot_navigation.sh` now derives every edge's cost independently --
base by type plus the hazard surcharge where the destination touches a live
wall, computed from the map's own wall list -- so "the graph priced this
correctly" is a real question rather than a restatement. All three proven able
to fail: the bounce check against a build with the cooldown disabled, the cost
check against `COST_HAZARD = 150`.

### B4 — Perception, hearing, memory

**Work:** immutable observations and sensor-only world access; FOV and gameplay
LOS observations for players, items, projectiles, hazards; stable entity
identities; the semantic sound event ring and per-bot hearing filters; reaction
queue, contact/item/hazard memory, uncertainty, and expiry; infrared-gated laser
perception with headless and offscreen tests.

**Exit:** a bot detects, loses, hears, searches for, and forgets a scripted
player with exactly the expected timing; adversarial tests find no through-wall,
hidden-position, or unseen-item leak; renderer and `ConsolePlayer` state have no
effect on any result.

### B4 record — the sensor boundary (steps 1-2)

**Why a boundary at all.** A brain holding an `AActor*` can see through walls
without anybody writing a line of code that means it to. So an observation is
values and stable ids, taken once, and a brain reads that and nothing else.
Every bot senses the same completed world in `Command::BeginFrame`, before any
of the tic's commands are applied -- sensing inside each `Produce` would let
the second bot react to the first one's move within the tic that made it, which
is both a small unfairness and an ordering dependency between bots that would
not survive two machines.

Vision is the profile's field of view plus `CheckLine`, the gameplay sight
check the game's own monsters use. Never a renderer visibility mark and never
`ConsolePlayer`'s camera: rendering may not run at all on a server, and when it
does it describes one screen rather than what eight bots can each see.

**The gate re-derives the answer rather than restating it.** It marches every
sight line itself over the map's solid cells and fails if one passes through a
wall. With `CheckLine` removed, MAP53's sightings go from 446 to 2607 and 1721
are flagged; with it, 1508 sightings across three maps and none. Software and
OpenGL produce byte-identical perception.

Two corrections to that check, both instructive. It first ran at tile
precision, because the trace rounded positions to tile indices -- so the line
being checked was not the line the engine tested, and fifteen sightings in four
hundred came back as leaks that were nothing of the sort. Then one survived: a
line grazing a wall face for a full tile of travel while never more than 0.08
of a tile inside it, which is looking along a surface rather than through it.
The check measures penetration depth now. **A check less precise than the thing
it checks manufactures failures, and they read exactly like real ones.**

**Detection and action are separate.** A sighting is released to the decision
layer 14 to 20 tics later -- about a fifth of a second, seeded so two bots
seeing the same thing do not move on the same tic. Paid on acquisition only: a
target held in view keeps updating without buying the delay again, because
noticing costs and following does not. Losing sight cancels an unreleased
notice, so a glimpse too brief to react to never reaches the brain; that
happens in the gate's own run, where 7 sightings produce 6 releases.

**Hearing replaces a boolean.** `madenoise` is one global with no source, no
place, no kind and no history. Semantic events are emitted at the four player
attack sites and at the damage path, with a source, a position and a sound
zone, and filtered per bot by distance, by Corridor 7's sound zones and by the
doors between them.

What the brain receives is deliberately worse than what the sensor knows: a
bearing quantised to a 45-degree sector, a range as one of three bands, and a
source slot **only when the listener can already see who made the noise**. The
true range is in the trace so a gate can bound it, and not in the observation.
Attributing every sound to its source would leak 93 of 107 sounds to listeners
who could not see the shooter, which is what the check reports when the rule is
removed.

**Gates:** `test_bot_perception.sh` covers wall leaks, field of view, reaction
timing, and hearing; `--percepttest` checks the angle folding and the
field-of-view edges with no map and no window. Every check proven able to fail:
LOS removed, FOV widened to 90 degrees, `REACT_BASE` set to 0, and attribution
unconditional.

Two smaller things worth keeping. The half-FOV is written `ANGLE_45` and not
`45*ANGLE_1`, which falls 32 units short because `ANGLE_1` is a truncated
division -- a rounding artifact sitting exactly on the edge of a bot's vision.
And a distance typed `fixed` while holding whole tiles produced a unit error
within the hour; the field says `distanceTiles` now.

**Infrared-gated lasers (step 3).** Corridor 7's laser barriers -- actor
classes `C7Static005` and `C7Static061`, which are the plane-1 markers 28 and
84 under a different numbering -- are invisible without the infrared visor, and
that invisibility is their whole design.

This is the one place in B4 a bot could cheat without ever looking wrong. It
would not behave oddly; it would simply stop walking into them, and every
behavioural test would stay green while it played a different game from the
human beside it. So the rule is checked directly rather than inferred from
conduct.

Two honest ways to know, and only those two:

| Condition | Barriers seen | Learned by contact |
| --- | ---: | ---: |
| No visor | **0** | 8 |
| Infrared on | 734 | — |
| With the gate removed | 734 | — |

Measured on MAP51, which has them; MAP53, MAP55 and MAP60 have none, so running
this there would have proved nothing at all.

Two details worth keeping. The actor scan does not run without infrared -- not
"runs and is filtered afterwards", because a filtered scan is one refactor away
from an unfiltered one. And the visor is read from **the observing bot's own
inventory**, never from `ConsolePlayer`'s camera the way the renderer's
equivalent check does; that is the same requirement as renderer independence,
and it is what makes the answer right on a server that draws nothing.

Contact knowledge is recorded at the place it happened, for the bot it happened
to, and for nobody else. Losing the visor does not erase what was learned.

**Damage cues (step 4).** `StartDamageFlash` takes a number of points and no
direction: Corridor 7 shows a screen-wide red flash and nothing else. So a hit
tells a bot how much and what it left, and never where it came from. The
attacker's identity is included only when the victim could already see them --
being shot by somebody in plain view tells you who shot you, and being shot
from behind does not. Section 13.5 names this exact trap: do not hand the AI an
unseen attacker merely because `killerobj` holds one.

**Searching is walking, not a mode.** A bot that loses a contact it was
actually told about routes to the last *observed* position through the ordinary
planner and follower. That position is stale by construction -- it is where the
contact was, not where it is -- so a bot that arrives and finds nobody has
learned exactly what a player learns. A contact the bot never noticed starts no
search, because it does not know anything was there.

**Forgetting is what stops a permanent lock.** After 350 tics without a
sighting the contact stops being a fact about anybody's position and becomes
nothing. Section 13.7's "may never keep an exact lock on a hidden player", made
mechanical. Observed in a real match: lost at tic 290, a twenty-waypoint search
route at 425, forgotten at 981 -- exactly 350 tics later.

**The engine's own sight check leaks, and bots do not inherit it.**

`CheckLine` walks the grid a tile at a time and, at some slopes, steps past a
corner it should have hit. The engine knows: `wl_state.cpp` carries a helper
called `CheckAdjacentTileBlockage` whose comment is "Helps prevent leakage
cases", and that mitigation does not cover every case. One sighting in 699 on
MAP51 ran squarely through the interior of a solid cell, nearly a third of a
tile deep, and `CheckLine` allowed it.

Monsters have always had that, and a bot could reasonably inherit it -- "bots
see exactly what the game's own AI sees" is a defensible story. It does not,
because the promise worth keeping is not *sees what a monster sees* but **never
sees through a wall**, and the second is the one a person losing a deathmatch
cares about. Bot vision is a strict subset of the engine's now: `CheckLine` must
pass, and so must a sampled geometric check that looks every eighth of a tile
and rejects anything ten map units inside a sight-blocking cell. It removed
exactly one sighting: 699 became 698, and 4009 sightings across three maps now
cross nothing.

Two things about how this was found. It only appeared because the match length
went from 900 tics to 1400 for the memory tests, taking MAP51 from 425
sightings to 699 -- **a rare leak needs volume before it shows**, and this one
would have shipped green. And it was findable at all because the gate
re-derives the geometry itself: a check that called `CheckLine` to verify
`CheckLine` would have agreed with the leak forever.

**What the fairness checks do and do not cover.** Every rule is proven able to
fail by breaking it on purpose:

| Rule | Leak direction | Permitted direction |
| --- | --- | --- |
| Line of sight | 1721 leaks when removed | 1508 sightings |
| Field of view | 53 wide when widened to 90 | in view |
| Reaction delay | caught at 0 tics | 14-20 tics |
| Sound attribution | 93 leaked when unconditional | 14 named, all visible |
| Infrared lasers | 734 seen when ungated | 8 learned by contact |
| Damage attribution | shares the sighting check | **not yet tested** |
| Forgetting | caught at 60 tics | 2 at exactly 350 |

The gap is real and worth stating rather than leaving implied by a green tick.
Damage cues report zero named attackers because the only damage available is a
laser barrier, which has no attacker at all. The no-leak direction holds; there
is no evidence yet that the *permitted* case works, and there cannot be until
bots shoot each other in B6.

**Still open in B4:** static pickup memory, which wants items worth remembering
and so belongs with B5's resource play.

### B5 — Goals and resource play

**Work:** utility candidates, need and value model, path-cost queries,
commitment, hysteresis, goal cooldown; visible and remembered health, armor,
invulnerability, weapon, ammo, energy, mine, and visor-charge goals; correct
inactive-item and weapon-stay semantics; state and goal explanation trace.

**Exit:** seeded scenarios select and collect the expected resource for
explainable reasons; goals do not thrash and never use unseen availability;
arena item-navigation soak progresses without unbounded replans.

**Status: complete.** See the B5 record below.

### B5 record — wanting things, and being able to say why

**A spawn is not an availability.** Section 12.8's distinction is the whole
design. Where a pickup spawns is map knowledge -- a player who has played an
arena twice knows where the shotgun is, and a bot knowing the same is not
cheating. Whether it is there *now* has only two honest sources: having just
looked, or having looked recently with no reason to think otherwise.

So annotations are built once at level load from the map's own placement, and
belief is per bot and moves only when that bot sees the place. The failure this
prevents is quiet in the same way the laser one was: a bot walking the global
actor list would collect everything the moment it respawned, from anywhere, and
would look exactly like a bot with good item timing.

Removing the visibility gate produces 33 beliefs instead of 8, with 18 outside
the field of view and 16 through walls.

**Stale decays to unknown, never to absent.** Section 13.6 is explicit and the
reason is behavioural: a bot that lets old news become "there is nothing there"
stops going to look and never finds out otherwise. Checked directly in
`--itemtest`.

**The need model.** Health rises nonlinearly as health falls -- the gap between
100 and 80 is not worth crossing a map for, and the gap between 20 and 40 is
the difference between winning the next fight and not. Ammunition is worth
nothing at capacity and nothing at all for a weapon the bot does not carry.
A weapon already held is worth *nothing* rather than less, because under
multiplayer stay-in-world rules it stays in the world and collecting it again
does nothing whatsoever.

**Collection is not visible as a disappearance.** Weapon-stay leaves the pickup
lying there afterwards, so the map looks identical and a belief of "present"
stays correct -- I went looking for "gone" observations and was right to find
none. What changes is whose backpack it is in, so that is what is measured:
bots end a MAP60 match holding 3 and 4 weapons against the 2 they spawn with.
The `already-have` rejection appearing afterwards is how we know a bot stopped
wanting what it just collected.

**The explanation is the deliverable.** The exit criterion says "for
explainable reasons", so every decision emits one line:

```text
item-scan considered=11 stale=8 already-have=1 no-need=2
```

The first version logged each rejected candidate separately: eleven
annotations, three bots, twenty decisions, six hundred nearly identical lines
that explain nothing to anybody. Same information, bounded length, legible.

**Thrash and replans.** Item choice happens only when a route runs out, so a
bot finishes what it starts rather than re-deliberating each tic: 4 to 5
decisions per bot per match, and 13 to 25 committed routes per match against a
runaway bound of 150.

**A gate that failed for a good reason.** MAP57's roaming transporter
crossings went from 2 to 0 once bots had items to fetch -- they now have
somewhere specific to be, and its pickups do not happen to lie across a pad.
Two properties were being conflated in one check: that *every pad works*, which
the per-pad sweep proves exhaustively and still does, and that *bots use
transporters unprompted*, which is a property of routing rather than of any
arena. The second is now summed across the arenas, and still fails (0
crossings) if the planner is made to avoid them.

This is the second time this session a probabilistic assertion about emergent
behaviour has broken for a good reason, after the arena-start episode. Such
checks want framing as "somewhere, sometimes" rather than "here, always", or
they encode today's behaviour as tomorrow's requirement.

**What these maps cannot exercise.** *(Corrected during B6: the arenas do carry
health, as wall dispensers -- `C7_Dispenser` with `args[0]` of 1, thirty-odd
per map -- rather than as floor pickups. Bots have no way to use one yet, which
is a gap in the bot rather than an absence in the map. And bots damage each
other now, so the second half of this paragraph no longer holds either.)*

The arenas carry weapons, charge packs and mine packs and almost no health or
armour as collectable items, and at the time of writing nothing damaged a bot
except a laser barrier. The health term's nonlinear shape is implemented and unit-tested
and *no match in these arenas has driven a bot below full health*. Like damage
attribution in B4, the code is there and the behaviour is unverified in play
until B6 gives bots a reason to get hurt. Recorded rather than left implied by
a passing gate.

**Gates:** `tools/test_bot_items.sh` is new, `--itemtest` checks belief and
ageing with no map, and `test_bot_arenas.sh` gained the replan bound. Proven
able to fail: item visibility removed, and the planner forced to avoid
transporters.

### B6 — Baseline deathmatch combat

**Purpose:** the first genuinely playable opponent.

**Work:** target acquisition and switching from observations; delayed aim
samples, bounded yaw motor, correlated error, fire gate; combat strafe and range
movement; weapon selection covering bayonet, M16, M343, dual blaster, shotgun,
plasma, assault cannon, and disintegrator; chase, search, and retreat. Mines and
visor stay behind explicit support flags.

**Exit:** human-versus-bot and bot-versus-bot matches produce ordinary kills,
frags, deaths, resource consumption, and respawns; every weapon-specific
deterministic test passes; the bot visibly misses and reacts within profile
bounds; no fairness invariant fails.

*This milestone completes the first playable slice: one human against one
visibly fallible bot on `MAP53`, offline, with no server in existence.*

### B6 record — an opponent that misses

**The fact the milestone turns on, verified rather than assumed.** Corridor 7's
hitscan weapons call `player_t::FindTarget`, which acquires anything within ten
degrees -- `CheckVisibility(check, ANGLE_90/9)`, an absolute angular difference
against a ten-degree tolerance -- and then applies ordinary weapon randomness.

So an aim error of two degrees is not an aim error. A bot with a slightly noisy
reticle that fires only while pointed at its target hits every time, and no
amount of tuning the noise changes it. This is measured, not argued: narrowing
the error envelope to a third of the cone produces **100% accuracy on both
seeds**, and the gate's ceiling catches it.

Missing therefore comes from an envelope wide enough to leave the cone, a
tracking delay that points the aim at where the target *was*, and a trigger
pulled while the aim is still swinging. At twice the cone the bot runs at 44 to
67 percent, which is an opponent rather than an execution.

**The error drifts, and that is not decoration.** Section 16.4 forbids an
independent random angle per tic, and the reason is arithmetic: independent
noise averages out over the handful of tics a shot takes to line up, which is
another way of never missing. The error springs weakly toward a bias that is
re-chosen every half to one and a half seconds, and the self-test checks a
single tic cannot move it across the envelope.

**I measured the wrong angle first.** The initial accuracy counter scored 36 of
37, because it measured how well the bot had converged on *its own aim point* --
and the aim point already contains the error, so a bot settling neatly onto a
badly wrong bearing scores perfectly. Measured against where the target really
is, the same run is 25 of 37.

**Weapons are a table, chosen by pulsing a slot button.** Eight descriptors with
range bands and a support flag; the disintegrator is present and deliberately
unsupported, because an enormous energy cost and a broad multi-target attack
want their own tests before a bot reaches for one. `ChooseSlotFrom(carried,
range)` is a pure function so the per-weapon cases section 16.6 asks for can be
tested without a running match -- a rule only exercisable by playing is a rule
tested by luck.

Nothing assigns `PendingWeapon`, `ReadyWeapon`, `attackheld` or a psprite. The
gate greps for it, on code with comments stripped: the first version failed on
a comment promising the code does not do it.

**Two things B4 and B5 recorded as untestable are now tested.** Damage
attribution has evidence in both directions -- 10 of 17 cues name an attacker
the victim could see, the rest are correctly anonymous -- which was impossible
until bots shot each other. And bots die and respawn through input in ordinary
play rather than only under a scripted kill.

**A gate that was right to fail, and nearly diagnosed wrongly.** `bot_items`
checked that bots end a match holding more weapons than they spawn with. That
stopped meaning anything the moment bots could die, because death returns a
player to its starting inventory: a bot that collected two weapons and was
killed reported as having collected nothing. What prevented me relaxing the
bound was the same run's rejection reasons showing `already-have`, which only
happens to a bot that owns the thing it is considering. The trace contradicted
the metric, and the metric was wrong. Pickups are counted as events now.

That is the third time this session an end-state proxy expired: coverage once
bots stopped to fight, transporter crossings once they had somewhere to be,
weapons held once they could die. Each time the capability was intact and the
measurement had quietly stopped measuring it.

**Still open in B6:** retreat behaviour, and mines and the visor, which section
16.7 stages behind ordinary guns being solid. Combat movement is strafing and
range-keeping; there is no breaking off when badly hurt, which wants the health
route that B7's dispenser work would provide.

**Gates:** `tools/test_bot_combat.sh` is new and `--combattest` covers the aim
model and weapon selection with no map. Proven able to fail: the aim envelope
narrowed inside the auto-aim cone (100% accuracy, caught by the ceiling).

### B7 — Special equipment and behavioral depth

**Work:** mines and self-risk; visor decisions and hidden-laser visibility;
transporter and door combat behavior; hazard, resource, and weapon utility
tuning; personality biases that do not change skill fairness.

**Exit:** mine, visor, disintegrator, plasma, hazard, transporter, and door
tests all pass; no equipment action bypasses normal input or inventory.

### B8 — Humanization and skill calibration

**Work:** the four profile mappings and fairness clamps; calibration of
reaction, perception, yaw, correlated error, cadence, strafe, commitment, route
imperfection, and memory; statistical reports and opt-in human baselines; mixed
blind playtests and trace-backed tuning; prevention of any ordinary zero-delay
configuration.

**Exit:** statistical bounds and reproducibility gates pass; skill progression is
perceptible without statistical cheats; Elite remains measurably fallible;
playtests find no repeatable wallhack, snap aim, or rules bypass.

### B9 — Interface, presentation, administration, recording

**Work:** human/bot/total/skill lobby controls and validation; the offline
skirmish route; roster identity and `[BOT]` presentation in scoreboard, kill
messages, and tally; authority-only list, fill, and remove-at-boundary
administration; documented command-line, debug, and profile controls; optional
versioned final-command recording, or an explicit documented demo limitation.

**Exit:** menu and command line create identical validated rosters; joining
peers see the same locked presentation; names, counts, and errors display safely
at minimum and maximum bounds.

### B10 — Hardening, soak, documentation, release

**Work:** protocol fuzz and sanitizers at maximum roster; per-change and
release-duration soak on all arenas; loopback latency, loss, and reorder mixed
matches; CPU and memory budgets measured and met; licensing and provenance
audit; user, admin, and mod documentation with known limitations; gates that
retain seeds and traces on failure; an optimized release package.

**Exit:** §3.2 is satisfied; `tools/package_corridor7_release.sh` refreshes
`builds/release`; `tools/test_corridor7_release_startup.sh builds/release`
passes against the packaged copy; commercial Corridor 7 files remain uncommitted.

---

## 21. Phase B verification

**Test layers:** pure unit tests for graph, A*, utility, motor, and error math;
scenario tests on purpose-built lab maps; integration tests on the real arenas;
statistical tests over many seeds; soak tests; and human playtests.

Suggested gates, consistent with the existing suite:

```text
tools/test_multiplayer_bots_roster.sh      tools/test_multiplayer_bot_navigation.sh
tools/test_multiplayer_bots_commands.sh    tools/test_multiplayer_bot_perception.sh
tools/test_multiplayer_bots_offline.sh     tools/test_multiplayer_bot_combat.sh
tools/test_multiplayer_bots_loopback.sh    tools/test_multiplayer_bot_fairness.sh
tools/test_multiplayer_bots_latency.sh     tools/test_multiplayer_bots_arenas.sh
tools/test_multiplayer_bots_soak.sh
```

Fast deterministic gates join `tools/run_gates.sh`; long soak and
commercial-data gates stay clearly selectable. Every script preserves logs on
failure, terminates all children, uses independent local ports, and prints the
exact reproduction command and seed. Measure ramps and timings on a lab map,
never a `MAP01` spawn.

**Playtesting protocol.** Automation cannot decide whether a bot feels human.
For each skill, run blind or minimally labeled mixed matches and collect
concrete observations: unfair information or instant response; robotic turning
or pathing; believable misses versus obvious sabotage; target persistence and
switching; door and transporter competence; resource and weapon choices;
camping versus aggression; difficulty progression; and moments where the trace
contradicts what was visible or audible. Pair every report with map, seed,
profile, slot, approximate tic, and trace. Never tune from win/loss anecdotes
alone.

---

# Part IV — Phase D: the dedicated server

## 22. Architecture

### 22.1 Alternatives considered

| Design | No window | No server slot | Validates world | Preserves lockstep | Effort | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Hidden/dummy-video listen host | partial | no | as today | yes | low | reject as final |
| Playerless packet relay only | yes | yes | no | yes | medium | prototype only |
| Playerless command-authoritative lockstep server | yes | yes | yes | yes | high but bounded | **selected** |
| Full authoritative state replication | yes | yes | yes | no — replaces it | very high | future project |

Why the selected model fits: the simulation already expects one command per
active slot per tic, and movement, collision, doors, weapons, pickups, damage,
death, frag credit, and respawn all happen after that boundary. The design
changes *who collects and finalizes commands*, not how the game interprets them.

The server runs the full world for four reasons: it determines the canonical
score, frag-limit event, winner, and next match rather than trusting a client;
it runs bot brains from the correct start-of-tic world; it compares client
digests with its own to diagnose divergence; and it makes fabricated inventory,
damage, position, and score messages impossible, because those messages do not
exist — clients submit only bounded inputs.

This is not secrecy-based anti-cheat. Clients still simulate the whole world; a
modified client can still automate aim. Preventing that needs a different trust
model and is out of scope.

### 22.2 Topology

```text
                       control plane / authority
                 +--------------------------------+
                 |        ec7wolf-server          |
 human input --->| validate ownership + sequence  |
 bot brains ---->| build canonical InputFrame[T]  |
                 | run full headless playsim      |
                 | score / digest / lifecycle     |
                 +-------+-------------+----------+
                         |             |
                 canonical frames  canonical frames
                         |             |
                  +------v------+ +----v---------+
                  | client A    | | client B     |
                  | slot 0      | | slot 1       |
                  | full playsim| | full playsim |
                  | render/audio| | render/audio |
                  +-------------+ +--------------+

No client-to-client gameplay datagrams.
The server has a PeerId and no PlayerSlot.
```

### 22.3 One model, two authorities

The session library supports a **listen authority** (interactive, owns a local
human slot and view, uses the same canonical frame machinery) and a **dedicated
authority** (headless, owns neither). They are not separate protocols.

A listen authority may keep a local transport shortcut, but its local command
must still be validated and finalized into the same canonical frame before
simulation, so bots, pause, disconnect, roster, and tests stay consistent.

That includes epoch priming: for each begin or resume record, a listen
authority samples its local human exactly once and creates an immutable
in-process `EpochPrime` carrying the same match, record hash, parent and
successor epochs, target sequence, slot, and encoded command as a remote ACK
prime. It passes identical ownership, range, and button validation and
participates in the full barrier; only UDP transport and a network ACK are
omitted. A dedicated authority has no local prime.

---

## 23. Session lifecycle

```text
Boot -> LoadingData -> LobbyOpen -> RosterLocked -> LoadingMatch
     -> ReadyBarrier -> Running -> TerminalPending -> Results
     -> LobbyOpen        (configuration/roster may change)
     -> LoadingMatch     (automatic fixed-roster rotation)
     -> ShuttingDown

Any state -> FatalError
Any nonterminal state -> ShuttingDown
LobbyOpen/RosterLocked/LoadingMatch/ReadyBarrier -> Aborting -> LobbyOpen | ShuttingDown
Running -> Paused -> ResumeBarrier -> Running   (new input/control epoch)
Paused | ResumeBarrier -> TerminalPending       (abort at the frozen completed tic)
```

Each transition has one owner and one timeout. **Never infer lifecycle from
whether a graphical function returned.**

### 23.1 Boot

1. Parse the server role and command line before any GUI or video setup.
2. Install signal and console-control handlers.
3. Open logging and validate writable state paths.
4. Read configuration with documented precedence.
5. Load `ec7wolf.pk3` and the explicitly selected Corridor 7 data.
6. Validate engine protocol, data profile, maps, definitions, and rotation.
7. Initialize deterministic RNG streams and common simulation services.
8. Initialize UDP transport and listen.
9. Emit one machine-readable readiness line, only after all of the above.

There is no IWAD picker, startup page, jukebox, window-opening cinematic probe,
menu fallback, or "continue in single player" path. Any failure here is fatal.

### 23.2 Lobby

The authority owns admission and optional password policy; unique display-name
normalization; one human slot per accepted gameplay peer; class policy and the
resulting class-derived teams; maximum clients, maximum players, minimum ready
players; bot fill configuration; match rules, map and rotation, seed, and delay;
and ready state and start policy.

V1 accepts gameplay joins only in `LobbyOpen`. During a match the server may
answer a bounded status query or reject a join with an explicit
`MatchInProgress` — it must not silently discard the request and leave the
client waiting.

### 23.3 Roster lock, load, ready barrier

1. Freeze the roster; compute its canonical hash.
2. Choose an unpredictable match ID, map, rules, seed, input delay, and first
   executable sequence.
3. Send `MatchManifest` reliably to every accepted peer.
4. Authority and every client call the same `InitializeMatchWorld(manifest)`:
   assign the seed; reset the versioned gameplay-authoritative RNG streams and
   all per-match state; load and translate the map; generate arena starts; spawn
   map actors and players through the same **pre-first-tic** boundary as
   `SetupGameLevel`. `AActor::FinishSpawningActors()` is deliberately *not*
   called early — the baseline digest uses a canonical representation of the
   pending-spawn order plus relevant just-spawned state, and the first
   executable tic reaches the ordinary boundary in its legacy order.
5. Each client replies `MatchReady` with the manifest hash, map/data hash, and
   initial state digest.
6. The authority waits for all required humans or the ready timeout.
7. The authority creates the canonical neutral bootstrap interval required by
   the negotiated delay and sends reliable `BeginMatch` carrying match ID, first
   sequence, delay, **successor** input epoch, client playout target, and the
   neutral-bootstrap definition and hash. Its header epoch is the *parent*; the
   successor is named only in the authenticated payload.
8. Each required remote client samples its owned command exactly once from the
   `start - 1` baseline for target `start + D`, freezes those bytes for retry,
   and acknowledges the exact begin record with `BeginAck` containing that
   command. A retransmission resends the same bytes and never resamples input.
9. A remote ACK or a local prime creates only a **pending** successor epoch.
   Losing a required peer invalidates the roster and manifest and returns the
   session through the lobby — the authority must never start the old manifest
   with a peer silently removed. Once every required ACK and prime is validated,
   the authority generates each bot's first decision for `start + D` exactly
   once, promotes the successor epoch, and only then arms a fresh monotonic
   deadline. **No deadline accrues during the barrier.** There is no
   authoritative `Countdown` state; a visual countdown is a client overlay
   counted from canonical bootstrap frames while already `Running`.

A client is not ready merely because it acknowledged a UDP packet, and no node
starts because its local clock reached a server timestamp.

**This reset boundary is mandatory** because the current global random streams
are cleared at process initialization rather than at `NewGame`, while arena
start generation and level setup consume seed state in source-sensitive order.
Match B with manifest X must produce the same initial digest in a fresh process
and after any unrelated match A, through repeated rotation.

### 23.4 Running and results

The authority advances only canonical sequences. Every node deterministically
discovers the frag limit or another natural outcome while simulating terminal
tic `N`; `RunSimulationTic(N)` returns a candidate. Each node immediately enters
`TerminalPending`, does not simulate `N + 1`, and keeps pumping transport. The
authority verifies its own candidate and digest and reliably emits
`ConfirmTerminal(matchId, inputEpoch, N, terminalKind, reason, worldDigest,
scoreDigest, standings, winnerOrTie?)`.

A client that receives the confirmation before completing `N` queues it and
continues only through `N` — it never skips simulation to show results. A
mismatch is a desync, not permission to keep playing.

Two barriers then run, and both matter:

1. Each survivor sends `TerminalAck(hashOfConfirmTerminal)`. The authority
   retains terminal history and match context until every survivor acknowledges
   or the terminal-ACK timeout drops a peer.
2. The authority emits `ResultsCommit(matchId, inputEpoch, N,
   hashOfConfirmTerminal, commitSemanticId, resultsDuration)`; receipt is the
   client's authoritative transition to `Results`, and clients return
   `ResultsCommitAck`. The commit hash covers all fields including a never-reused
   semantic ID, so an ACK from an earlier terminal record, match, or commit
   cannot satisfy it.

Only after the second barrier may the authority discard playsim and frame
history or reset match-local sequence windows. **`resultsDuration` cannot expire
either barrier** — its timer starts after the commit ACK/drop barrier, not when
the first terminal datagram was sent. A reordered next-manifest packet is queued
until `ResultsCommit` has moved that client to `Results`.

Natural outcomes are therefore never fictional events scheduled at `N` after `N`
already happened. A scheduled abort, a disconnect discovered while paused, and a
controlled `ServerOverload` all end through the same confirm/ack/commit protocol
for the last genuinely completed tic. Clients render their own non-blocking
tally; the server never calls `C7Scoreboard_ShowTally()` or waits for `ACK_Any`.

At results expiry the authority returns to an open lobby; or locks the unchanged
roster for the next rotation entry **only if every human in it remains
admitted**; or, if any timeout or leave dropped a human, returns to `LobbyOpen`
and builds a new roster hash, manifest, and match ID (an explicit bot-fill policy
may occupy the missing slot, but that is a *new* roster, never "unchanged"
rotation); or stops after one match under `--once`; or shuts down on request.

### 23.5 Pause

Client pause, menu, status, and automap buttons are local UI and never enter the
gameplay codec. **Deathmatch defaults to unpausable.** While a client has a menu
open its network and simulation pumps keep running and it submits neutral
gameplay intent; its pawn stays in the match and may be attacked. Closing the
menu requires no global unblock packet.

If admin pause is supported it uses a control epoch rather than pretending a
future sequence elapsed while simulation was stopped:

1. The authority chooses `N` beyond both the semantic-ACK margin and the
   greatest bot-decision horizon already built, then reliably preannounces
   tentative `PauseAfter(N, controlEpoch)`. From that decision on, clients stop
   producing and the authority stops accepting or building input beyond `N`;
   **bot brain and PRNG state must not advance for a command that will be
   discarded.** A non-acknowledging peer is dropped or triggers the declared
   abort policy — never a silent cancel that resumes with a hole in the pipeline.
2. Every node completes `N`, enters `Paused(controlEpoch)`, emits no `N + 1`, and
   continues transport, liveness, admin, and UI. Scheduler and input epochs
   freeze; no wall-clock deadline keeps accruing.
3. The authority sends `Resume(oldControlEpoch, oldInputEpoch, newInputEpoch,
   N + 1, D)` and enters `ResumeBarrier`. Clients discard old future submissions
   and playout buffers and reset the pending epoch's canonical prior-button
   baseline to **all released**. From frozen world `N` each client samples
   exactly one command for `N + D + 1`, freezes it, and returns it in
   `ResumeAck`. No gameplay press or release edge is processed while paused.
4. After every required ACK and prime, the authority builds each bot's decision
   for `N + D + 1` exactly once, promotes the successor epoch, arms a fresh
   deadline, and runs the normal `D`-frame neutral bootstrap. **No buffered
   pre-pause fire, use, or movement may execute after resume.**
5. The authority emits exactly one canonical `N + 1`; duplicates from an old
   epoch are harmlessly rejected.

Never reuse a player `bt_pause` bit or `BlockPlaysimPacket`. Test lost,
duplicated, reordered, and stale pause and resume records; long pauses; held and
released buttons; stale future submissions; and `D = 0/1/max` resume.

---

## 24. Protocol version 2

### 24.1 Encoding rules

Use an explicit byte reader and writer; never cast packet storage to a C++
struct. Fixed-width integers, one documented byte order. Validate magic,
version, header length, payload length, type, and maximum before reading the
payload. Validate every count before a loop or allocation. Use checked
arithmetic for variable-length sizes. Reject trailing bytes unless the version
permits TLV extensions. Treat enums as untrusted integers until range-checked.
Reject non-canonical encodings and duplicate fields. **Never mutate the receive
buffer in place to byte-swap it** — that is exactly the S1 defect, generalized.
Fuzz the decoder as a pure function with no socket or world side effects.

```text
magic[4] "E7N2"   protocolVersion u16   messageType u8   flags u8
headerBytes u16   payloadBytes u16
sessionId u64     connectionId u64      matchId u64      inputEpoch u32
packetSequence u32  ackSequence u32     ackBits u32
authenticator[16]
```

`matchId` is zero for lobby traffic and the current manifest's ID for every
match-scoped message. `inputEpoch` is zero outside match command flow and
changes at each begin/resume barrier. A new map creates a new match ID even when
slot numbers and sequences reset to the same values.

`connectionId` is a public lookup key, **not a credential.** After admission,
use at least 128 unpredictable bits of direction-specific authentication
material — a distinct client-to-server and server-to-client bearer
authenticator, or a keyed tag with equivalent forgery resistance. Validate
source endpoint, direction, authenticator, match/session, and replay window
before changing any peer reliability state. Comparison is constant-time, and a
wrong-token packet must not advance ACK or replay state or reveal whether
another field was valid. If plaintext bearer authenticators are chosen, document
the boundary honestly: they stop off-path spoofing and do nothing against an
on-path sniffer. Confidentiality needs a separately designed secure channel.

The authenticated replay window is per direction and stays monotonic for the
whole connection, and session-scoped reliable semantic IDs stay monotonic until
disconnect or rekey. **Do not reset either at match begin.** Only match-local
command and frame ordering windows reset, keyed by
`(sessionId, matchId, inputEpoch)`. Otherwise an authenticated old lobby, ready,
leave, pause, or control record becomes fresh again after rotation.

**The two-epoch rule** keeps loss and reordering from making a half-created
command stream look active. `BeginMatch`/`BeginAck` headers carry parent epoch
`0` and name the successor only in the authenticated body; `Resume`/`ResumeAck`
headers carry the active old epoch and name both in the body. An ACK echoes the
semantic ID, both epochs, target sequence, exact record hash, and the immutable
primed command. A valid ACK or local prime records a *pending* successor and
does not activate it: the authority activates and arms only after the complete
barrier, and a client activates only when the first authenticated canonical
frame names that exact pending successor. Traffic naming an unannounced
successor, a retired proposal, or the old epoch after activation is rejected.
This is part of the wire contract, not an implementation hint — it lets a
receiver authenticate and route an epoch-changing record using state both sides
already agree exists.

### 24.2 Handshake

```text
ClientHello       protocol range, build version, capabilities, 128-bit nonce,
                  requested name/class, data-profile summary
ServerChallenge   echoed client nonce, server nonce, stateless address cookie,
                  protocol selection, canonical transcript hash, backoff hint
ClientJoin        echoed cookie/nonces and transcript hash, compatibility
                  hashes, optional password proof, requested settings
ServerWelcome     echoed nonces and join-transcript hash, session/connection/
  or JoinReject   peer IDs, directional authenticators, assigned human slot,
                  server identity, lobby/rules/roster snapshot, or reason code
LobbyAck / RosterUpdate / ReadyState
```

The stateless cookie binds source address, client nonce, server secret, and a
short time bucket, so a spoofed one-byte datagram cannot allocate peer state or
cause amplification. It is not player identity.

Accept `ServerChallenge` and `ServerWelcome` only for the outstanding endpoint,
nonces, cookie, protocol, and transcript the client actually initiated. An
identical retransmitted `ClientJoin` inside the admission window returns the
*same* logical connection and slot — it must not allocate a second peer — while
a conflicting nonce reuse is rejected. Keep bounded pending-transcript state and
test blind spoofed Challenge and Welcome, a lost Welcome, and duplicate or
reordered Join.

Compatibility data covers protocol version and capabilities, EC7Wolf build and
protocol compatibility version, game family and profile, the authoritative
gameplay-data hash in deterministic load order, actor and map definitions plus
the server-authorized add-on list, and the platform-independent determinism
format version. Reject reasons are structured — `ProtocolMismatch`,
`ServerFull`, `MatchInProgress`, `DataMismatch`, `BadPasswordProof`,
`NameRejected`, `RateLimited` — and the client shows the reason rather than
timing out.

The welcome and manifest contain **no other client addresses**. Endpoint
migration is out of scope without an explicit rebind challenge.

### 24.3 Gameplay messages

```text
InputSubmission        roster hash, firstSequence, count, ownedPlayerSlot,
                       proposed commands, submission acknowledgments
CanonicalInputFrames   roster hash, firstSequence, frameCount, one command for
                       every active slot in stable order, complete small
                       deterministic event bodies, server digest checkpoints
FrameAck               latest contiguous canonical sequence + selective bits
DigestReport           roster hash, completed sequence, digest version, playsim
                       digest, optional subsystem digests
```

Commands carry stable gameplay fields only: bounded yaw, forward, and strafe
axes plus an explicit gameplay-button bitmask. Local automap, status, menu,
screenshot, pause, escape, console, and debug controls are never encoded, and
raw `NUMBUTTONS` arrays — whose layout changes when a local enum is edited — are
never sent.

Transmit current gameplay-button bits, **not** a client-authored `buttonheld`
array; every node derives held and edge state from the prior canonical bits the
same way. Exclude `bt_run`: input code already scales axes before networking and
the remaining consumer is first-person presentation, so transmit the resulting
bounded axes and derive view-model gait from canonical magnitude. Pitch is
either a bounded canonical field or explicitly unavailable in network deathmatch
— never a local actor write (§6.6, S1).

The legal axis range comes from an audit of keyboard, mouse, controller, and
touch sampling. Normalize all human input into the documented envelope before
server validation. Do not pick a narrow security clamp that silently changes
legitimate mouse turning, and do not leave yaw effectively unbounded merely
because movement code clamps other axes.

The server validates authenticated source and connection; claimed peer and slot
ownership; sequence window and wrap-safe ordering; count and payload size; **one
submission per slot per sequence** — the first valid command is locked, a
byte-identical retransmission is harmless, and a differing duplicate is rejected
and counted as a protocol violation rather than winning a last-packet race; axis
bounds; allowed button bits; and rate and history limits.

### 24.4 Reliable control and deterministic events

Lobby state, manifest, ready, start, pause and resume, kick, abort, match end,
next map, and shutdown are reliable with idempotent handlers. Their semantic ID
is separate from the packet sequence, so a retransmission cannot apply an action
twice.

Every deterministic event names an explicit boundary phase:

- `ApplyBeforeTic(E)` — apply the complete event in stable type and semantic-ID
  order before commands and thinkers for `E`; or
- `StopAfterTic(N)` — simulate all of `N`, including outcome evaluation and
  finish-spawning, then stop before `N + 1`.

`ConfirmTerminal(N)` is not retroactively applied at `N`; it confirms either the
natural candidate already discovered after that tic or the result of a stop
committed before it.

Choose a tentative `StopAfterTic(N)` no earlier than the greatest bot decision
already produced plus the acknowledgment margin, and once accepted, generate no
decision beyond `N` — discarding a bot command after advancing its private brain
and PRNG would corrupt reproducibility. Each bot's production is an
exactly-once transition keyed by
`(matchId, inputEpoch, targetSequence, botSlot, controllerGeneration)`, where
`controllerGeneration` is manifest-assigned and prevents a future replacement
from aliasing cached work. Before invoking a brain the authority proves the
target is within the committed horizon and that advancing will not exhaust the
human lead clients could have derived; it stores an immutable record and returns
that record on scheduler retry or deadline rebase, never invoking the brain
twice for the same key. Preserve brain memory and PRNG across resume; destroy
private state only with the whole match. Never roll a brain back piecemeal or
reuse its advanced state in another match.

Likewise, never commit an `ApplyBeforeTic(E)` that invalidates commands already
produced for `E` or later: either the producer has a specified deterministic
forecast of the event, or the event creates a fresh input epoch with a neutral
rebootstrap. Keep this event set deliberately small in v1.

For a pre-scheduled event the authority preannounces the complete typed body and
waits for semantic ACK before its apply horizon; the complete body is **also
embedded in the canonical frame** at that horizon and retained with frame
history. Embedding is the commit; preannouncement is tentative. A frame must
never contain only a reference to a body the receiver may have missed. If a
required peer has not acknowledged before the commit deadline, move or cancel
the event while there is still time, or execute the explicit drop/abort
policy — never commit an event only some peers are prepared to apply.

**Same-sequence precedence**, defined once and tested:

1. Apply compatible `ApplyBeforeTic(N)` events in canonical order.
2. Install commands and simulate all of `N`.
3. A natural outcome wins and enters `TerminalPending`.
4. Otherwise a committed disconnect or admin abort wins over pause.
5. Otherwise a committed pause enters `Paused`.
6. Graceful shutdown follows the terminal confirmation policy; an unrecoverable
   authority failure is a separate emergency stop at the last committed tic,
   never a forged canonical event.

Reject mutually incompatible before-tic events and more than one unresolved stop
rather than relying on arrival order. A disconnect detected while **any**
`StopAfterTic(N)` is unresolved does not allocate a second stop: retain the
boundary, remove the departed peer from the survivor set, neutralize its slot
through `N`, and record the disconnect as terminal metadata.

Clients accept authority events only from the authenticated server connection.
Client "ready" and "leave" are requests, never authority events.

### 24.5 Loss recovery and MTU

Keep datagrams under a conservative path MTU — target 1200 bytes until measured.
Never depend on IP fragmentation. Batch as many complete canonical frames as
fit; never split a field across untracked fragments. Include redundant recent
human submissions so one lost uplink packet does not immediately stall into
neutral input. Keep bounded send histories. Use cumulative plus selective
acknowledgment. Retransmit from sequence history, not from a pending ring whose
entry was already consumed. Rate-limit retransmit requests and ignore
acknowledgments outside retained history. Test sequence wrap with a
reduced-width test codec.

With 11 slots, per-frame command sizing must be calculated before the format is
frozen. If the current representation is too large, encode bounded axes compactly
and use button bitsets — do not push the payload past the MTU to avoid designing
it.

### 24.6 Legacy compatibility

Choose one explicit policy: retain legacy peer-to-peer listen multiplayer
temporarily while dedicated and listen-v2 use the new magic; or migrate every
network game to the v2 star model in one release. Either way, a mismatch fails
immediately with an actionable message. A new server must never interpret legacy
packed structs, and a legacy client must never consume a v2 packet on the
strength of its first type byte. S1's protocol version makes this detectable.

---

## 25. Canonical command flow and 70 Hz timing

### 25.1 Per-sequence algorithm

```text
S = most recently completed world sequence
E = S + 1                  next sequence eligible to execute
D = negotiated full input delay in frames
F = S + D + 1              future input target observed after S
```

Future production and current execution are two different lanes:

1. After completing `S`, each interactive client samples local intent for `F`
   and redundantly submits it for its owned slot.
2. After completing server world `S`, and only after stop and lead feasibility
   are checked, the authority visits bots in stable slot order, builds every
   absent command for `F`, and stores it under the full key. A partial retry
   reuses completed entries and advances only missing bots. It does **not**
   simulate `F`.
3. Independently, at `E`'s finalization deadline, the authority takes the
   buffered human and bot proposals for `E`, validates them, and produces
   exactly one command per active slot. A missing human follows §25.3.
4. It embeds any fully acknowledged `ApplyBeforeTic(E)` or `StopAfterTic(E)`
   body, emits `CanonicalInputFrame(E)`, and installs the same frame locally.
5. Server and clients call `RunSimulationTic(E)` exactly once.
6. Each computes the completed-`E` digest; selected sequences are reported.
7. Resolve post-tic precedence. If any boundary wins, all nodes stop before
   `E + 1`; otherwise `E` becomes the new `S`.

**A client must never apply its own proposed command early.** It applies only
the canonical frame, or loss and substitution create immediate divergence. At
`D = 0`, `F == E`, so the authority must receive the new command and return its
frame before execution — suitable only for loopback diagnostics.

### 25.2 What input delay means in a hub

```text
client sampling -> uplink -> server finalization -> downlink -> client deadline
```

It is not one peer-to-peer round trip. The server measures each client's latency
and jitter during the lobby and chooses a session-wide delay, or a documented
per-client submission lead, while keeping one canonical execution sequence. The
first release uses one server-selected delay and one advertised client playout
target `P`, validating that the client trail still leaves every peer enough
future-command lead.

### 25.3 Missing input

Waiting forever is unacceptable; inventing movement is worse. One deterministic
authority policy, logged on every use:

1. Accept redundant submissions until the finalization deadline.
2. If a human command is missing, synthesize a **neutral command**: zero
   movement and yaw, no current buttons, held-edge state derived from the
   previous canonical command so release semantics stay valid.
3. Mark the peer late; continue liveness and retransmit handling.
4. Continue neutral commands while missing — never repeat attack or use, never
   leave a pawn running.
5. After the configured consecutive-missing or wall-clock timeout, schedule
   `StopAfterTic(AbortMatch)` at a future sequence and notify all peers reliably.

Charge a missing command to a client only when the authority is in its normal
deadline epoch and the client had the advertised history and lead needed to
produce it. If an authority stall or catch-up outruns the commands clients could
possibly have derived, that is `ServerOverload`, not client lateness: stop
catch-up, rebase or run the controlled overload-abort policy, and do not
increment peer late counters.

The `buttonheld` derivation needs its own unit test, because EC7Wolf uses held
state for edge-triggered use, weapon slots, mines, visor, and non-autofire
weapons.

### 25.4 Fixed-rate scheduler

A monotonic 64-bit clock — never render tics or calendar time.

```text
while running:
    poll network/admin/signals until next deadline or activity
    process bounded incoming work
    for each due tic, up to catch-up cap:
        poll bounded transport again
        S = just-completed world sequence; E = S+1; F = S+D+1
        if E exceeds a committed stop horizon: leave at the completed boundary
        if advancing E would exhaust derivable human lead:
            stop catch-up; rebase, slow, or controlled ServerOverload abort
        if F is within the production horizon:
            for each bot slot in stable order lacking a generation-keyed
              decision: build and store it exactly once
        finalize and emit frame E; install and simulate E exactly once
        emit digest/outcome; stop immediately on terminal E
    run non-simulation maintenance under budgets
```

Requirements: exactly `TICRATE == 70` simulation tics per second; no busy-spin
while idle; keep receiving while waiting; poll bounded transport *between*
caught-up tics so newly emitted frames and resulting submissions can progress;
never skip a world tic to catch up; cap tics per outer iteration so a spiral
cannot starve networking; interleave decision, finalization, and simulation per
tic rather than finalizing a batch against stale world state; perform stop and
lead checks before any brain can mutate memory or PRNG; reuse the immutable
decision cache across retry and rebase; never build later decisions or simulate
past a terminal tic merely because deadlines were due; log overload duration,
maximum catch-up, and backlog; and define when sustained overload aborts a match
rather than running silently slow.

### 25.5 Client playout

A rendered client buffers `P` contiguous canonical frames to absorb jitter and
clock drift, with negotiated watermarks and bounded idle and catch-up. Recurring
underruns or a growing backlog are the early signal of clock skew; test it
explicitly over long runs.

---

## 26. Headless simulation

### 26.1 The one-tic API

```cpp
struct SimulationTicResult
{
    WorldDigest digest;
    TicBoundaryResult boundary;   // continue, natural candidate, abort, pause
    TArray<GameplayEvent> events;
};

SimulationTicResult RunSimulationTic(
    Sequence sequence,
    const CanonicalInputFrame& commands,
    const SimulationServices& services);
```

**It does:** validate that the frame roster and hash match the active match;
apply `ApplyBeforeTic(sequence)` bodies in canonical order; install each active
slot's command once; advance the deterministic time counter once; perform
pending spawn and respawn work; tick thinkers in the required category order;
finish actor spawning; evaluate deterministic termination; resolve post-tic
precedence and return the boundary decision; build the stable digest; emit
semantic gameplay and presentation events without rendering or playing them.

**It must not:** sample physical input; poll sockets; read a local camera or
`ConsolePlayer`; draw, update a HUD, fade, animate, or present; open or mix
audio; wait for user acknowledgment; process local pause, menu, or debug keys;
choose a map or mutate the roster; read wall time.

### 26.2 Ordering

All commands, bots included, are finalized from the same completed-world
boundary. Preserve the existing thinker order:

```text
VICTORY -> WORLD -> PLAYER -> NORMAL
```

Keep the existing `victoryflag` check before every later category, including a
flag already set on entry. WORLD is gameplay-critical for Corridor 7 doors,
elevators, pushwalls, and dispensers. **Never let slot 0 tick and then use its
changed position to decide slot 1's command in the same tic.**

The server uses ordinary `player_t`, `APlayerPawn`, inventory, movement, weapon,
collision, damage, death, frag, and respawn code. There is no special server
pawn, and the server never directly awards kills.

### 26.3 The presentation event boundary

Simulation-reachable calls become semantic events:

```text
PlayerDamaged(slot, amount, source)   PickupSucceeded(slot, item)
PickupFailed(slot, reason)            DoorActivated(id)
SoundEmitted(source, class, position, gameplay-audible flag)
```

The client sink renders and plays them; the server sink counts them and feeds
bot hearing. A gameplay-audible sound event is *data* the server needs; opening
an audio device is not.

### 26.4 The world digest

The existing capture checksum is a starting point, not authority validation. A
versioned digest covers match sequence and time, map, rules, active roster, and
player states; each player's transform, health, class, state, frags and team,
weapon states, inventory and ammo, status effects, and respawn timers; all
gameplay actors with stable IDs and relevant transform, state, health,
ownership, and flags; doors, pushwalls, forcefields, transporters, triggers,
hazards, and mutable map state; a versioned allow-list of
gameplay-authoritative RNG streams; the match controller and pending canonical
events; and canonical bot commands plus every bot pawn's ordinary replicated
state.

Never hash pointers, unordered-container iteration, padding, render
interpolation, audio channels, wall time, or local UI state. Produce
sub-digests so "world mismatch" narrows to players, actors, map, RNG, or bot
pawns, and report the **first divergent component** rather than one opaque
checksum.

Do not hash every registered RNG. `AnimatePics` advances at client render
cadence; `M_Random` is explicitly non-gameplay and is used for sound-sequence
delays; `Corridor7Music` selects a soundtrack. Those are presentation streams
and are excluded. Maintain a reviewed, versioned gameplay-RNG registry —
changing its membership changes the deterministic compatibility format. Tests
vary render rate, texture animation cadence, audio availability, and headless
mode while the gameplay digest stays equal, then perturb a listed stream and
require detection.

**Authority-private bot state never enters the cross-node digest** — clients do
not run those brains and cannot reproduce it. The server computes a separate
`BotBrainDigest` for diagnostics, recordings, repeat-run tests, and bug reports,
and never compares it with a client. A bot decision becomes replicated state
only through its canonical command.

The actor model has no network-stable object ID. Add a deterministic actor
serial assigned from simulation spawn order, or prove an equally stable
canonical ordering. Never use a raw pointer as a digest key, tie-breaker,
lifecycle reference, or log identity. Cover actor creation, destruction, map
transition, and serialization before treating the digest as authoritative.

The digest detects divergence; it does not repair it. V1 logs and ends or
removes a mismatched client. Resynchronization is a later feature.

### 26.5 The determinism ABI

Authoritative state is **not** automatically cross-platform merely because most
movement is fixed-point. Startup builds trigonometric tables with runtime `tan()`
and `sin()`, and gameplay converts `atan2()` results to integer angles for
visibility, enemy facing and missiles, player death rotation, and Corridor 7
chamber behavior. A different libm or compiler target can round a boundary
differently and permanently split lockstep.

Create and version a determinism ABI: inventory every floating-point and libm
call reachable from map initialization and playsim; replace authoritative angle
conversion with a proved fixed or integer lookup helper, or restrict compatible
build and platform pairs until golden vectors prove identical behavior; generate
trig tables from checked canonical data, or hash the generated tables into
ready-barrier diagnostics; define integer widths, overflow and wrap assumptions,
fixed-point rounding, endianness, actor ordering, and the RNG registry; and run
boundary vectors around axes, quadrants, FOV limits, death rotation, and
projectile directions on every supported platform and build mode.

**Do not advertise Linux-server/Windows-client compatibility until this gate is
green.** A digest that reports the split after play begins is evidence, not a
substitute.

---

## 27. Headless initialization

### 27.1 Phases

| Phase | Client | Dedicated server |
| --- | --- | --- |
| paths, logging, config | yes | yes, server-specific paths |
| SDL base/timer if required | yes | yes, no video or audio flags |
| resource archives and game profile | yes | yes |
| map/actor/texture/sprite metadata | yes | yes, only what gameplay needs |
| `LOCKDEFS` / key groups (`P_InitKeyMessages`) | yes | **yes — this is gameplay** |
| deterministic tables and RNG | yes | yes |
| renderer capability and window | yes | **never** |
| fonts, HUD, menus, cinematics | yes | no |
| keyboard, mouse, joystick, controller | yes | no |
| audio device, mixer, music playback | yes | no |
| sound definitions and gameplay events | yes | yes |
| client renderer backend | yes | no |
| server transport, lobby, admin | optional for listen | yes |
| fixed server loop | no | yes |

```text
BootstrapProcess            InitializeCommonResources
InitializeGameplayDefinitions   InitializeDeterministicRuntime
InitializeClientPresentation    InitializeServerRuntime
ShutdownClientPresentation      ShutdownServerRuntime
ShutdownCommonRuntime
```

Each phase owns its termination handlers. Avoid one global termination stack
whose server path writes a client config, destroys never-created video, or waits
for an acknowledgment.

Keep `P_InitKeyMessages()` in common initialization despite its name: it parses
`LOCKDEFS`, constructs key groups, and assigns the numbers gameplay
`P_CheckKeys()` uses. Only the failed-use HUD text and sound belong to the
presentation sink. A headless locked-door test must cover both an accepted key
group and a rejection. *(Corridor 7's lock numbering is inverted and the artwork
will not tell you: lock 1 is BLUE, lock 2 is RED.)*

### 27.2 Prohibitions

Server startup must not call `gtk_init_check` or an IWAD picker;
`CheckRendererAvailable`; `VL_SetVGAPlaneMode` or `I_InitGraphics`;
`R_InitRendererBackend` or any framebuffer, window, or context creation; client
resolution or projection setup; `VH_UpdateScreen`, fades, or sign-on drawing; or
menu, status, scoreboard, or cinematic presentation.

Build POSIX with `NO_GTK`; build Windows as a **console** application, not the
`WIN32` GUI target nor a wrapper around it; build macOS as a plain command-line
executable with no `.app` bundle.

Classify `R_InitRenderer()` separately — it initializes software 2-D function
tables, not a backend or window, so the first stage may retain it without
violating runtime headlessness. The slim stage must split or prove it
unnecessary before dropping `r_2d` linkage, and must never confuse it with
`R_InitRendererBackend()`.

No-video tests unset `DISPLAY` and `WAYLAND_DISPLAY` and deliberately set
invalid SDL video and audio drivers. **Reaching a listening state must not
depend on dummy backends.** *(Note the inverse hazard the project already knows:
on a Wayland session, headless tests that do need SDL must set
`SDL_VIDEODRIVER=x11` or windows land on the user's screen. The server path must
need neither.)*

### 27.3 Input and audio

Do not call `IN_Startup`, joystick or controller initialization, mouse grabbing,
or gameplay event sampling. Current network waits call `IN_ProcessEvents` and
`CheckKeys` to stay cancellable; replace those with a platform-neutral service
poll checking atomic shutdown state, the local admin command queue, socket
readiness and timers, and service-control notifications.

Server terminal input is administration, never a gameplay controller. An admin
command may enqueue an authority event; it may not write a command slot or
mutate actors from the input callback.

Split sound startup into definition and sequence metadata; semantic gameplay
sound-event creation; and client mixer, device, and music playback. The server
keeps the first two with a `NullAudioOutput`. Gameplay sound *events* stay —
they feed bot hearing and the sound-zone rules — while the device never opens.

---

## 28. Source and build architecture

### 28.1 Staged split

Do not attempt a perfect library boundary before the first zero-window parity
test.

**Stage A — behavioral headless target.** Add `ec7wolf-server` with a server
entry point and an `EC7WOLF_DEDICATED` definition. Define `NO_GTK`; omit client
platform entry and resource files where simple. Retain SDL2 base and SDL2_net
initially, and accept all-interface UDP binding — `SDLNet_UDP_Open(port)` has no
local-address parameter, so a real `--bind` waits for a native-socket backend.
Retain resource, texture, and sprite metadata required for map and actor
loading. Route runtime through server initialization and the server loop. Link
no SDL2_mixer or OpenGL/libepoxy once the null services are ready. **Prove exact
simulation parity before any further source removal.**

**Stage B — durable component split.**

```cmake
add_library(ec7wolf_core OBJECT            # objects, resources gameplay needs,
    ...)                                   # maps, actors, players, thinkers,
add_library(ec7wolf_net_common OBJECT      # inventory, rules, RNG, digest
    ...)                                   # codec, reliability, session, frames
add_library(ec7wolf_client_runtime OBJECT  # renderers, UI, HUD, input, audio
    ...)
add_library(ec7wolf_server_runtime OBJECT  # lobby, authority transport, clock,
    ...)                                   # admin, null services

add_executable(ec7wolf ...)
target_sources(ec7wolf PRIVATE
    $<TARGET_OBJECTS:ec7wolf_core> $<TARGET_OBJECTS:ec7wolf_net_common>
    $<TARGET_OBJECTS:ec7wolf_client_runtime>)

add_executable(ec7wolf-server ...)
target_sources(ec7wolf-server PRIVATE
    $<TARGET_OBJECTS:ec7wolf_core> $<TARGET_OBJECTS:ec7wolf_net_common>
    $<TARGET_OBJECTS:ec7wolf_server_runtime>)
```

`OBJECT` plus `$<TARGET_OBJECTS:...>` is intentional and compatible with the
repository's CMake 3.6 floor; linking object libraries as ordinary targets would
require 3.12. Native actor classes register through global initializers and some
units are referenced only by definition or string name, so an ordinary static
archive can dead-strip them. A later `STATIC` layout must use documented
whole-archive linkage or explicit registration anchors, and any linkage change
must be accepted only after comparing the complete client and server class
registry and all-arena spawned class counts.

The split will expose old global dependencies. Resolve them through narrow
interfaces — not by putting all sources back into both targets and calling it
done.

### 28.2 New modules

| Module | Responsibility |
| --- | --- |
| `g_session.h/.cpp` | *(Phase S)* runtime role, peer/slot mapping, roster, rules, predicates |
| `net_codec.h/.cpp` | pure bounded byte codec and message definitions |
| `net_reliability.h/.cpp` | sequence windows, ACK bits, history, resend |
| `net_client.h/.cpp` | client handshake, submissions, canonical-frame receive |
| `net_server.h/.cpp` | admission, peers, input collection and finalization, broadcast |
| `g_simulation.h/.cpp` | one canonical presentation-independent tic |
| `g_matchcontroller.h/.cpp` | lobby-to-match manifest, outcome, results, rotation |
| `i_presentation.h/.cpp` | HUD/audio/view interfaces and null services |
| `server_main.cpp` | CLI and bootstrap dispatch only |
| `server_loop.h/.cpp` | monotonic pacing, service poll, shutdown |
| `server_config.h/.cpp` | validated configuration and precedence |
| `server_admin.h/.cpp` | stdin/local admin parsing and scheduled actions |
| `g_digest.h/.cpp` | versioned full simulation and subsystem digest |

Avoid one enormous `server.cpp` duplicating client startup, codec, rules, and
loop logic.

---

## 29. Configuration and CLI

```text
ec7wolf-server
  --config <server.cfg>          --data-dir <Corridor7-data-directory>
  --bind <address>               (Stage B; default 0.0.0.0)
  --port <1..65535>              (default 5029/udp)
  --max-clients <0..11>          --max-players <1..11>   --min-players <1..11>
  --map <MAP51..MAP57|MAP60>     --rotation <MAP51,...,MAP60>
  --mode <deathmatch|team-deathmatch>    --frag-limit <0..255>
  --input-delay <tics|auto>      --client-playout <frames|auto>
  --ready-timeout <duration>     --peer-timeout <duration>
  --results-duration <duration>
  --auto-start / --no-auto-start --once
  --password-file <path>         --state-dir <path>
  --log <path|->                 --log-format <text|json>
  --seed <fixed seed>            --no-stdin      --version
```

Rules: Stage A supports `--port` but binds all interfaces and must **reject** a
non-wildcard `--bind` as unsupported rather than claim it worked;
`maxPlayers <= MAX_PLAYER_SLOTS`; `maxClients <= MAX_CLIENT_PEERS`; without bots
`minPlayers <= min(maxPlayers, maxClients)`; with bots
`minPlayers <= min(maxPlayers, maxClients + configuredBotSlots)` where the bot
count comes from a validated reservation policy, not an assumed ability to
invent bots at start; the deathmatch allow-list is exactly `MAP51`–`MAP57` plus
`MAP60`, with `MAP58` and `MAP59` rejected as placeholder boxes; team and class
policies must be coherent; input delay must fit protocol history and sequence
windows; the playout target and watermarks must fit retained frame history and
leave measured production lead; duration parsing rejects overflow, negatives, and
ambiguous units; a missing or ambiguous data profile is fatal; fixed seeds are
logged and clearly marked, and random seeds are generated securely enough to
avoid accidental repetition and then distributed as deterministic match data.

Register every option in the same argv scanner as the other gameplay options —
the engine has several independent scanners and only the last has a catch-all,
so an option that is merely peeked at silently becomes a filename.

---

## 30. Administration and operations

**Local admin** over stdin and the terminal is sufficient for v1: status,
roster, kick, abort, pause and resume if enabled, next map, reload
configuration where safe, and quit. Commands are typed, allow-listed, audited,
and translated into authority events — never into a command slot or a direct
actor mutation. Debug and cheat protocols stay disabled; existing debug packets
are never repurposed as RCON. Any later remote administration uses a separately
authenticated, replay-protected, rate-limited channel.

**Logging** is structured with a stable event vocabulary: lifecycle
transitions, admissions and rejections with reason codes, roster and manifest
hashes, per-match seed and rules, terminal outcomes, digest mismatches, peer
liveness and drops, overload and catch-up statistics, and rate-limit
rejections aggregated rather than one line per hostile datagram. Secrets are
redacted. `--log-format json` exists for machines; the text format stays
readable.

**Status and metrics:** tic time percentiles, catch-up depth, frame backlog,
per-peer RTT and loss and late counts, canonical frame size, history memory,
actor and thinker counts, and uptime. A bounded, rate-limited public status
query may be enabled for server browsers; it never reveals peer addresses.

**Service deployment:** run the binary directly with absolute paths;
`systemd` and container examples ship as templates. `SIGINT`, `SIGTERM`, and
Windows console control events stop accepting joins, notify clients where
practical, close the socket, flush logs, and exit — with no window and no
prompt. The socket must be immediately rebindable after a clean exit.

**Recordings** for reproducibility follow §19.2: canonical roster, rules, data
hash, protocol version, seed, delay, and every slot's final command per
sequence, with periodic digests. Replay the commands; never re-run a historical
AI.

---

## 31. Security and trust

### 31.1 Threats and controls

| Threat | Controls |
| --- | --- |
| malformed or truncated packet | pure bounded codec, exact lengths, fuzzing, sanitizers |
| integer or count overflow | checked arithmetic, hard counts before allocation or loops |
| spoofed join, slot exhaustion | stateless cookie, per-address rate limits, allocation only after proof |
| spoofed, lost, or duplicate handshake leg | nonce/transcript/endpoint binding, idempotent Join-to-Welcome |
| reflection and amplification | pre-cookie response no larger than request, bounded status replies |
| stale or replayed packet | session/connection/match IDs, packet and semantic replay windows |
| address impersonation | directional 128-bit authenticator plus source binding; the public connection ID is not a credential |
| unauthorized slot input | peer-to-slot ownership validation on every submission |
| forged start, pause, end, map, debug | authority-only messages accepted only on the authenticated authority connection |
| command flood, history exhaustion | byte, packet, and semantic rate limits; bounded queues |
| log flood | aggregation, sampling, per-source rejection counters |
| path traversal, config abuse | server-owned paths, normalized allow-listed map names, no remote file paths |
| data mismatch, desync | compatibility manifest, initial digest, periodic versioned digests |
| slow client stalls the match | input deadline, neutral substitution, late counters, authority timeout |
| server overload | budgets, catch-up cap, queue limits, monitoring, controlled abort |
| RCON credential theft | no network RCON in v1 |
| debug and cheat abuse | debug protocol disabled, local typed allow-list, cheats forced off |

### 31.2 The message policy table

Generate a policy table in code — message, legal sender, legal receiver states,
permitted effect — and exercise **every row**. Unknown messages, wrong-state
messages, wrong-role messages, duplicates, and out-of-window sequences have no
world side effects.

A listen authority's local `EpochPrime` is deliberately not a wire message, but
it is processed through the same generated validation function as the
corresponding ACK payload and is a required barrier member. **A direct function
call may not bypass ownership, target, hash, epoch, or command checks.**

### 31.3 Passwords and the anti-cheat boundary

An optional join password uses a nonce-bound proof so the reusable secret is
never sent verbatim. No ad-hoc "XOR encryption."

State the anti-cheat boundary honestly in the operator documentation: the server
prevents fabricated state messages because such messages do not exist, and it
validates ownership, bounds, and rate on every input. It does **not** prevent a
modified client from automating aim or reading its own full world copy. Doing so
would require a different trust model and is out of scope.

---

## 32. Disconnects and roster changes

**Human disconnect while `Running`, v1:** the authority schedules
`StopAfterTic(AbortMatch)` at a future canonical sequence and notifies every
peer reliably, then runs the ordinary terminal confirmation and results-commit
barriers. No peer independently drops a player on its own wall clock. If a stop
is already unresolved, that boundary is retained and the disconnect becomes
terminal metadata (§24.4).

**Disconnect while `Paused` or in `ResumeBarrier`:** retire any pending
successor epoch, exclude the lost peer, and confirm the already frozen completed
tic — without generating another command or simulating another tic.

**Later deterministic drop or bot takeover:** a versioned
`RosterChange(ApplyBeforeTic(E))` can remove a pawn or replace a human
controller with a bot at a canonical tic. Design it, but do not add it silently.

**Reconnect, late join, and spectators** are deferred, with protocol room
reserved. **Authority loss always ends the session** — no host migration, and
clients never elect a replacement arbiter.

---

## 33. Bot re-homing

This is the milestone that the Phase B-before-Phase D ordering deliberately
defers, and §2.3 explains why it should be cheap.

- A bot occupies an ordinary active slot; its `SlotKind` is `Bot` and it has no
  `ownerPeer`.
- The authority runs every brain and generates its future command before
  finalizing the canonical frame.
- A dedicated authority may own any number of bot producers while remaining a
  zero-slot process.
- A bot never appears in peer address, handshake, readiness, ACK, RTT, or
  timeout arrays.
- After completed sequence `S`, the server builds all bot commands for
  `F = S + D + 1` before running any thinker for the next executable frame.
  Clients consume them from canonical frames and never rerun brains.
- Canonical commands, bot pawns, and their effects enter the cross-node digest.
  Private memory, beliefs, path state, utility state, and bot PRNG enter the
  authority-only `BotBrainDigest`.
- A failed bot command builder is an authority software fault, never a missing
  network peer.
- Build in stable slot order and cache each immutable command by
  `(matchId, inputEpoch, F, botSlot, controllerGeneration)`, so bots cannot
  alias and a partial retry advances only missing producers.
- For a preannounced stop or pause, choose the horizon beyond commands already
  built and cease decisions past it. **Never discard a command after advancing
  private brain and PRNG state and then resume from that advanced state.**

---

## 34. Performance budgets

Measure on all eight arenas with 1, 2, 8, and 11 active slots before optimizing:
headless tic time and percentiles; client rendered tic time for comparison;
packet and byte rate per client and aggregate; canonical frame size and history
memory; actor, thinker, and GC counts; startup and map-load time and peak
memory; idle lobby CPU; and one-hour and overnight memory growth.

At 70 Hz the nominal per-tic budget is **14.286 ms**, and the server should
normally use a small fraction of it, leaving room for packet bursts and hosted
environments. Define warning and failure thresholds from actual hardware rather
than asserting a fixed percentage.

Do not optimize away common resource initialization before profiling proves it
meaningful and parity tests cover the change. Long-running concerns —
allocation growth per rotation, sequence wrap, bounded caches, 64-bit time — get
an overnight rotation soak.

---

## 35. Phase D milestones

### D1 — Bounded codec, reliability, and protocol vectors

**Work:** v2 header, pure byte reader/writer, message types, sequence and ACK
windows, bounded histories, and a fuzz target. Canonical gameplay command fields
and button mask. Session, connection, and match IDs; directional authenticators;
non-resetting connection and semantic replay windows plus tuple-keyed
match/input windows; proof that a public connection ID alone grants no authority.
Checked golden vectors produced by the real encoder for other-language tools.
Structured rejection codes and protocol version reporting.

**Exit:** all unit, fuzz, and sanitizer codec gates pass; every message has a
sender/state/side-effect policy test; worst-case command frames fit the chosen
MTU or have a tested batching design.

### D2 — Star handshake and lobby on a listen authority

**Work:** the handshake flow, stateless cookies, admission, name normalization,
slot assignment, lobby state and roster distribution, ready state, and the
manifest — all driven by a *listen* authority so the model is validated before
anything is headless. Base liveness timers for lobby, load, and ready.

**Exit:** two clients join a listen authority over v2 with no client-to-client
traffic; a spoofed or replayed handshake leg allocates nothing; every reject
reason is surfaced to the client.

### D3 — Canonical hub input transport

**Work:** input submissions, canonical frame emission, frame ACK and selective
retransmission, the neutral-input policy, the input-pipeline bootstrap, the
two-epoch begin barrier, and client playout with watermarks.

**Exit:** a listen-authority match runs entirely through canonical frames under
induced delay, loss, duplication, and reordering; digests agree; `D = 0/1/max`
all behave as specified; no client ever applies its own proposed command.

### D4 — Extract the common simulation tic and the full digest

**Work:** `RunSimulationTic()` per §26.1, the versioned digest and sub-digests,
the deterministic actor serial, the gameplay-RNG registry, and the determinism
ABI inventory.

**Exit:** the rendered client uses the extracted function with no behavior
change and green determinism gates; the digest narrows an injected divergence to
the right component; render rate, texture cadence, and audio availability do not
change the gameplay digest.

### D5 — Playerless authority inside the development binary

**Work:** a `DedicatedAuthority` runtime path using common resources, server
services, and the fixed scheduler; skip all video, input, audio-output, and menu
paths; explicit data and config validation with textual lifecycle; server plus
rendered clients before any dependency slimming; signal and stdin
administration; an early console-only platform entry — at minimum a `NO_GTK`
POSIX target.

**Exit:** no-display, no-audio startup passes on the supported harness; server
plus two clients creates exactly **two** player pawns and identical digests; the
server never uses a local player, view, status screen, or command slot; graceful
stop works in lobby and in match.

### D6 — The separate `ec7wolf-server` target

**Work:** server entry point and target; common, client, and server libraries or
source groups; remove GTK, render backend, input, SDL2_mixer, and client UI
linkage; preserve necessary resource metadata and decoders; generalize the PK3
build and output assumptions; add native Windows console and macOS plain-CLI
entry points that reach server bootstrap without GUI or `NSApplication` startup.

**Exit:** a clean build produces both executables; the server target passes the
import and dependency policy and behavior parity; client renderer, audio, and
input tests stay green.

### D7 — Match controller, results, rotation, configuration

**Work:** complete results, rotation, richer config, and next-match policy on the
D2–D3 foundation; move map, rules, seed, outcome, and rotation authority out of
presentation loops; harden `InitializeMatchWorld(manifest)` across rotation;
typed config and CLI validation, `--once`, auto and manual start; a non-blocking
client results overlay driven by the confirmed terminal record; mark the next
roster dirty when a terminal barrier drops a human.

**Exit:** multi-map rotation completes with no menu acknowledgment or restart;
frag limit, team, class, and map rules agree everywhere; invalid config or data
fails *before* listening; **match B has the same initial digest from a fresh
process and after any unrelated match A** when the manifest is identical.

### D8 — Disconnect and failure semantics

**Work:** peer and authority liveness and failure transitions for every phase;
reliable authority-scheduled abort on human loss; the paused and resume-barrier
loss branch; single-boundary handling when a loss arrives with a stop already
unresolved; survivor-set handling for the terminal and commit barriers in
`Running`, `TerminalPending`, and `Results`; client server-loss behavior;
bounded shutdown notification and socket cleanup.

**Exit:** kill any participant in any lifecycle state without an indefinite wait
or a desync; remaining clients see the same reason and terminal sequence;
authority loss never elects a client; the socket rebinds immediately after a
clean exit.

### D9 — Security and operations hardening

**Work:** complete cookies, tokens, rate limits, replay protection, and hostile
gates; structured logs, status and metrics, local admin allow-list and audit;
service examples and overload budgets; a threat review of every message and
admin path; remote RCON stays disabled.

**Exit:** the hostile corpus, fuzzing, ASan, and UBSan produce no crash and no
world side effect; floods stay within memory, CPU, and log budgets; admin
actions are scheduled and audited with secrets redacted; long-running status
carries actionable tic, network, and digest health.

### D10 — Bot authority integration

**Dependency:** Phase B is complete.

**Work:** map bot slots into the shared roster with no peer; run brains at the
authority decision boundary behind the immutable generation-keyed decision
cache in stable slot order; track and enforce produced and committed stop
horizons; check lead and stop feasibility before any brain mutation; freeze
through pause; retain decisions across retry, rebase, and terminal diagnostics;
include commands in canonical frames and bot-pawn state in the replicated
digest; add the authority-only `BotBrainDigest`; add human/bot, bot-only, and
listen/dedicated parity and soak tests.

**Exit:** the server stays absent from the player count while bots occupy
ordinary slots; bots never enter liveness or readiness; every node consumes
identical bot commands under ordinary gameplay rules; instrumented retries,
pause/resume, and overload rebase with at least two bots prove **exactly one
brain and PRNG advance per bot per produced target**, no key aliasing, and no
decision beyond a committed horizon; reset-equivalent authority runs reproduce
the private brain digest, which no client is ever expected to match.

### D11 — Packaging, cross-platform, release qualification

**Work:** a redistributable server package, launcher, and templates separate
from commercial data; extended CI and build matrix plus a package-startup gate;
all arenas, maximum capacity, impairment, hostile, cross-build, and overnight
rotation tests; operator and protocol compatibility documentation; revalidation
of the ordinary client release package.

**Exit:** fresh-machine package startup with no display succeeds against
operator-supplied data; no commercial file appears in the archive or in version
control; the client release package startup gate stays green; every criterion in
§3.3 is evidenced by a command, log, or test.

---

## 36. Packaging

The existing Corridor 7 release package is a self-contained **client** package
that, by project policy, contains the operator's commercial game files and must
never be committed or redistributed. The **server** deliverable is separate:

```text
ec7wolf-server        ec7wolf.pk3        run-server.sh / run-server.cmd
server.cfg.example    README-server.md   LICENSE / copyright notices
required redistributable shared libraries, if packaged
optional systemd/container examples
```

It contains no commercial Corridor 7 file. The forbidden scan covers at least
`CORR7CD.EXE`, `MAPTEMP.CO7`, `GFXTILES.CO7`, `VGADICT.CO7`, `VGAHEAD.CO7`,
`VGAGRAPH.CO7`, `AUDIOHED.CO7`, `AUDIOT.CO7`, and `*.CO7`, plus extracted FLIC
and cinematic assets, ripped music, and any future commercial filename added to
the client package. Keep packaging **allow-listed**, not merely deny-listed.

The launcher resolves its own directory without changing global configuration;
defaults config, state, and log paths to package-local or documented service
paths; preserves quoted paths; requires an explicit operator data directory;
never copies commercial files into the package; prints exact binary, config, and
data paths on failure; returns the server's exit code; and avoids a terminal
that closes before an error can be read.

The package gate stages only the allowed manifest; scans for known commercial
filenames and hashes; starts from the packaged directory with display and audio
unavailable; points at a data directory outside the package; reaches listening,
accepts a probe, and shuts down; verifies config, log, and state stay in the
selected writable location; inspects direct dynamic imports; and prints a
reproducible manifest with checksums.

Operator documentation explains which purchased Corridor 7 edition is supported,
how to point the server at it, and how a compatibility mismatch is reported —
without publishing proprietary content. Never log full proprietary lump
contents; names, sizes, and hashes suffice.

---

# Part V — Program-wide

## 37. Risk register

### 37.1 Stop-the-line conditions

Pause feature work and repair the foundation if any of these occurs:

- **The Phase S2 zero-slot session test is weakened or deleted.** It is the only
  thing making Phase D's bot re-homing cheap (§2.3).
- The server needs a dummy player or pawn to boot.
- Any participant applies a non-canonical local command.
- A received packet is cast or read before its bounds are validated.
- Server and client digests diverge in a baseline match.
- A no-display test initializes video, a window, or a GUI.
- Game rules depend on server wall time or packet arrival order.
- An unknown or non-authority source can schedule a lifecycle action.
- Renderer or audio removal changes collision, spawn, RNG, or match outcome.
- One test process silently falls back to single player.
- A package manifest includes commercial data.
- A bot writes actor position, angle, health, inventory, or score directly.
- Any shipped skill profile becomes capable of zero-delay perfect play.

### 37.2 Register

| Risk | Likelihood | Impact | Early signal | Mitigation |
| --- | --- | --- | --- | --- |
| Peer/slot assumptions survive behind adapters | high | critical | the server still needs a local player, or marks itself received | semantic types, assertions, the zero-slot gate before any headless work |
| Bot code binds to `ConsolePlayer` because Phase B precedes Phase D | medium | high | `BotManager` cannot construct without a local player | §11.2 rule plus a B2 exit test constructing against a playerless session |
| Protocol rewrite regresses existing multiplayer | high | high | listen tests fail or legacy hangs | staged listen-authority v2, temporary explicit legacy path, S1 baselines |
| Packed legacy packet vulnerability stays exposed | high | critical | sanitizer or hostile-gate failure | **S1 is the first milestone of the program for this reason** |
| "Headless" still creates a hidden or dummy window | medium | high | the test needs Xvfb or a dummy driver | invalid-driver and no-display gates, import audit |
| Removing renderer code breaks loading metadata | high | high | missing actors, changed solidity, triggers, or LOS | behavior-first build, retain required metadata, separate pixel masking, parity gates |
| Audio early-return changes gameplay events or RNG | medium | critical | digest or bot hearing differs by sound zone | semantic sound events, gameplay-RNG allow-list, sound-zone parity gate |
| Null local player causes array UB | high | critical | ASan crash in doors, death, HUD, or FOV | optional local-player API, no sentinel indexing, hotspot sanitizer suite |
| Local presentation side effects crash the server | high | high | `StatusBar` or camera null dereference | event services, transitional null objects, unexpected-call counters |
| Command hub doubles latency beyond the configured delay | medium | high | repeated neutral inputs on healthy links | measure the two-leg path, server-selected delay, redundant submissions |
| Client clock drift empties or overfills the playout queue | high over long runs | high | recurring underruns or growing backlog | negotiated playout target, watermarks, bounded catch-up, skew tests |
| One slow client degrades everyone | high | high | frame deadline misses | neutral substitution, liveness policy, metrics, bounded abort |
| Neutral command edge semantics are wrong | medium | high | stuck firing, use, or weapon behavior | explicit prior canonical state, unit and integration tests |
| Digest omits early divergence | high | high | clients disagree before the checksum does | comprehensive versioned sub-digests and command traces |
| Digest hashes unstable data | medium | high | platform- or compiler-only mismatch | stable IDs, order, and encoding; no pointers, padding, or unordered iteration |
| Cross-platform libm splits lockstep | medium | critical | Linux server and Windows client disagree | the determinism ABI (§26.5); do not advertise mixed platforms until green |
| Scheduler retry advances a bot brain twice | medium | critical | bot PRNG or path diverges after overload or pause | tuple-keyed immutable decision cache, pre-mutation horizon checks, exactly-once instrumentation |
| Server overload causes a catch-up spiral | medium | high | networking starved while processing tics | monotonic scheduler, catch-up cap, budgets, controlled abort |
| Pause or rotation reuses stale deadlines or commands | medium | critical | burst tics, or pre-pause fire after resume | fresh deadlines and input epochs, discard old future input, neutral rebootstrap |
| Terminal confirmation lost during rotation | medium | high | a client stays terminal while the server loads the next map | the two-barrier terminal/commit protocol with retained history |
| Barrier-time peer drop reused in "unchanged" rotation | medium | high | the next manifest names a dead owner | dirty-next-roster flag, rebuild hash and ID, or explicit bot fill |
| UDP amplification or slot exhaustion | high for a public server | high | many unknown-source allocations | stateless cookies, response sizing, per-source and global rate limits |
| Unauthorized control packet ends a match | high in the current protocol | critical | the hostile test changes playstate | **S1 source/role table**, then the v2 policy table |
| Remote admin becomes an arbitrary code path | medium | critical | reuse of the debug or console packet | local admin only in v1; a separate authenticated design later |
| State replication scope creeps into v1 | medium | high | actor snapshot or join work blocks the zero-slot server | the explicit command-lockstep decision, deferred late join |
| Bot navigation graph disagrees with `ClipMove` | high | high | a bot walks into geometry the planner called open | pure traversal query shared with collision, scripted-pawn parity tests |
| Bot perception leaks hidden state | medium | critical | a bot reacts to an unseen player | the sensor boundary, adversarial through-wall tests, fairness gates |
| Bot difficulty implemented as statistics | medium | high | a profile changes damage, speed, or health | §17.3, and a gate asserting identical class properties across profiles |
| Tuning bots around engine defects | medium | high | AI workarounds keyed to specific maps | fix plasma/player collision, masked-wall LOS, and exits as gameplay first |
| Long-running leaks or wrap bugs | medium | high | memory grows each rotation | overnight rotation, accelerated wrap tests, bounded caches, 64-bit time |
| Platform split becomes a `SERVER_ONLY` maze | medium | medium | common code full of ifdefs | service interfaces and target source lists; platform entry adapters only |
| Source import creates a license conflict | low if the rule is followed | high | copied blocks, missing notices | original implementation; recorded provenance and license review |
| Commercial data leaks into a package or git | low/medium | critical | `*.CO7` or `CORR7CD.EXE` in an archive | allow-list manifest, explicit forbidden-file scan, separate package root |

---

## 38. Decisions to confirm before their dependent milestone

| Decision | Recommendation | Decide by |
| --- | --- | --- |
| Authority model | Command-authoritative lockstep; authority is a role | before S2 |
| Pitch in netplay | Refuse the local write outside standalone; defer a canonical field | **S1** |
| Legacy protocol | Version from S1; keep legacy listen play until D2, then choose one policy | S1, revisit D2 |
| Initial ruleset | Corridor 7 free-for-all and existing team deathmatch | before S3 |
| Offline mode | Same session and roster with one peer, no fake network | before S3 |
| Slot layout | Explicit kind and owner per slot; contiguous occupied slots in v1 | before S2 |
| Supported total count | Validate 11; expose only the proven, menu-approved cap | before B9 |
| Live add/remove/takeover | Match-boundary only in v1 | before B1 protocol freeze |
| Host migration | End the session on authority loss | before B1 |
| Bot brain authority | Authority alone; broadcast finalized commands | before B1 |
| Bot map knowledge | Full static topology and pickup spawns; dynamic state only by perception | before B4/B5 |
| Perception authority | Immutable sensor adapter; no tactical raw world access | before B4 |
| Damage-direction information | Match actual human feedback; never expose the hidden attacker | before B4 |
| Highest skill | Strong but finite and fallible; no ordinary perfect profile | before B8 |
| Skill presentation | Four levels: Recruit, Marine, Veteran, Elite | before B9 |
| Personas | Original built-in names; no copied external data | before B8/B9 |
| Bot profiles | Validated built-in data first; optional lump format later | before B2 |
| AI implementation | Explicit C++ states plus utility; no VM or ML in v1 | before B2 |
| Navigation | Runtime tile/portal graph with real collision validation | before B2 |
| Hearing | Semantic gameplay event ring; only sounds a human could receive | before B4 |
| Mines | Stage after baseline guns; ship only with focused tests | before B6/B7 |
| Visor and hidden lasers | Stage after baseline perception; ordinary command and charge | before B4/B7 |
| Player classes | Bot inherits the configured ordinary class; no bot-only stats | before an alternate class ships |
| Mixed class radii | Make projection console-specific first; otherwise v1 requires equal radius | before an alternate class ships |
| Pause and local UI | UI stays local; network pause disabled in v1; offline skirmish pauses locally | before B1 protocol freeze |
| Match end | Use the completed human frag/time/result rules; AI invents none | before B6 |
| Save support | Unsupported for v1 bot deathmatch | before B9 docs |
| Demo and replay | Legacy unsupported; optional versioned command recording | before B9 |
| Mods and custom maps | Support maps expressible by the typed graph; diagnose unknown traversal honestly | before any public mod claim |
| Automatic input delay | Server-selected session delay in v1; per-client lead later | before D3 |
| Missing-command grace | Neutral substitution with a logged authority timeout | before D3 |
| One-player matches | Allowed only with bots; otherwise the lobby waits | before D7 |
| Password support | Optional nonce-bound proof; no ad-hoc obfuscation | before D9 |
| Disconnect continuation | Abort in v1; deterministic slot removal later | before D8 |
| Time limit and rotation | Deterministic rotation with the dirty-roster rule | before D7 |
| Remote status query | Bounded, rate-limited, no peer addresses | before D9 |
| IPv6 | Out of scope for v1; do not bake IPv4 assumptions into the codec | before D1 |
| Cross-platform play | Not advertised until the determinism ABI gate is green | before D6 |

---

## 39. Execution protocol

### 39.1 Before a milestone

1. Read `AGENTS.md`, this plan, and [multiplayer.md](multiplayer.md).
2. Inspect `git status` and the branch. Treat pre-existing and untracked changes
   as user-owned.
3. Re-read the actual current source symbols. **Do not trust line numbers, or
   this plan, over changed code.**
4. Run the milestone's baseline gates and save concise evidence.
5. State assumptions and the smallest milestone boundary before editing.
6. Do not start a later optional feature to work around a prerequisite.

### 39.2 During implementation

- One architecture change at a time; keep existing client behavior runnable.
- Prefer explicit semantic types and narrow APIs over booleans and indices with
  comments.
- Never introduce an out-of-range `ConsolePlayer` sentinel.
- Never add a dummy or invisible server pawn.
- Never cast UDP bytes to a protocol struct.
- Never initialize dummy video or audio to make a test pass.
- Never consume render state, camera, audio mixer, wall clock, pointer address,
  or unordered iteration in a deterministic decision or digest.
- Never call world mutation from a socket, signal, terminal, or UI callback;
  enqueue a validated boundary action.
- Preserve commercial files and unrelated worktree edits.
- Record external source provenance before copying anything; prefer original
  code.
- Add the failure and hostile test **with** the implementation, not as cleanup.
- Keep the server's absence from the player count continuously asserted.

### 39.3 Evidence at milestone exit

Report the files and symbols changed and the architectural outcome; the commands
and tests run and their results; command-frame and digest evidence where
applicable; no-display, no-audio, and dependency evidence where applicable; any
skipped platform or gate with the exact reason; known limitations inside the
milestone contract; working-tree status distinguishing prior user changes; and
release or package startup results when required.

**Do not mark a milestone done because it compiles, or because one local client
connected.**

### 39.4 Parallel work packages

These may be delegated once interfaces are frozen: the protocol codec, fuzzer,
and fixed vectors; the session and roster audit with semantic loop conversion;
the headless startup and presentation-service audit; the server clock,
lifecycle, config, and admin; digest expansion and deterministic fixtures; the
impairment, hostile, and lifecycle test harness; CMake, dependency, and
packaging work; documentation and service examples. Within Phase B: navigation,
perception, and the weapon descriptor table are separable once the sensor and
command boundaries are frozen.

**Avoid parallel edits to `wl_net.cpp`, `wl_play.cpp`, or startup** until
ownership and interfaces are agreed. Integrate and test each shared-boundary
change before both branches build on it.

### 39.5 Review lenses

Review every nontrivial patch separately for: peer, slot, and authority
correctness; deterministic sequence and simulation order; hostile packet,
length, source, and state behavior; no-local-player and no-presentation safety;
client regression behavior; resource and gameplay metadata parity; failure,
shutdown, and bounded-resource behavior; bot fairness and the sensor boundary;
and license and data-distribution implications.

---

## 40. Provenance and licensing

The implementation is original EC7Wolf code informed by public architectural
ideas. GZDoom and Zandronum are design references; Zandronum is the relevant
precedent for a ZDoom-family codebase supporting a real server-only process, but
EC7Wolf reaches it through its own smaller deterministic command architecture.

- Do not copy Zandronum's compiled bot scripts, chat and persona data, names, or
  other creative assets. Its bot files retain Skulltag/Zandronum notices and a
  four-condition license; even GPL-compatible code needs a file-by-file notice
  and a source-distribution audit if adapted.
- Quake III's released source is GPL-2.0-or-later; provenance must still be
  recorded for any adaptation.
- ACEBot's additional "All Rights Reserved" and sale restrictions make it
  unsuitable for copying into this project.
- If anything is copied or closely translated despite the
  original-implementation rule, record the upstream repository, pinned commit,
  exact file and lines, retained notice, adaptation description, and
  distribution obligations **in the same change**, and update the project's
  copyright documentation before release.

Corridor 7's commercial files are never committed and never redistributed, in
any package produced by any phase of this program.

---

## Appendix A — Why the quick alternatives do not work

**Hidden graphical host.** Running ordinary `--host` under Xvfb or SDL dummy
video may be useful in CI, but the process is still player 0: it spawns, appears
in the score, and consumes a slot, while retaining graphical, audio, and input
initialization and dependencies.

**Invisible or invulnerable server pawn.** It consumes a slot and changes
spawn-distance selection, collision and target scans, scoreboard and team
counts, frag-limit logic, map visibility, and possibly sound and trigger
behavior. Hiding it in the HUD does not remove it from the simulation.

**Spectator server pawn.** A spectator is a client and view concept and still
needs a slot in the current architecture. The requested server is an authority
process, not a spectator.

**Bot in host slot 0.** A useful headless test participant, but it is an AI
opponent occupying a score and spawn slot. It does not give eleven positions to
eleven clients.

**Dumb UDP relay.** It removes the mesh and consumes no slot, but without the
playsim it cannot author bot commands, verify digests against its own world,
enforce canonical scores and outcomes, or tell a valid state from mutually
consistent client lies. A transport experiment, not the server.

**Full Zandronum protocol transplant.** It requires snapshot and state
replication for Corridor 7 actors, map state, inventory, weapons, hazards,
joins, prediction, and compatibility, plus a broad license review. The existing
command boundary solves the first dedicated version more directly.

**Replicated bot brains on every peer.** See §11.8 — it trades a small bandwidth
saving for a determinism obligation across every compiler, architecture, and
future tuning change, with divergence often invisible until much later.

---

## Appendix B — Compact invariants

Print these next to the keyboard.

**Identity**

1. Exactly one peer is the authority; authority is a role, never a slot number.
2. A dedicated authority owns no slot, pawn, camera, score row, or command.
3. A `PeerId` is never a player index; a `PlayerSlot` is never a connection
   index.
4. Peer count is not bounded by slot count in either direction.

**Commands**

5. Every controller emits only ordinary player commands, clamped and
   whitelisted.
6. Nothing writes actor position, angle, pitch, health, inventory, or frags
   outside the command boundary.
7. All active slots appear exactly once per canonical frame, built before any
   thinker ticks.
8. `buttonheld` is derived from the previous applied command, never trusted from
   a producer or a packet.
9. A client applies only the canonical frame, never its own proposal.

**Simulation**

10. Thinker order is `VICTORY -> WORLD -> PLAYER -> NORMAL`, with the existing
    `victoryflag` short-circuit.
11. One slot's tick never influences another slot's command in the same tic.
12. The digest hashes replicated gameplay state only — never pointers, render
    state, wall time, or private brain state.
13. Presentation streams (`AnimatePics`, `M_Random`, `Corridor7Music`) are not
    gameplay RNG.

**Network**

14. Validate length and counts before decode; never byte-swap in place.
15. Every control message has one legal sender, one legal state set, and one
    permitted effect.
16. A public ID is not a credential.
17. Only the authority emits canonical frames and lifecycle events.

**Bots**

18. Tactical code sees observations, not the world.
19. A bot knows only what an attentive human could know, no sooner and no more
    precisely.
20. Skill changes perception and motor limits, never rules.
21. Private bot PRNG never touches a gameplay stream, and a brain advances
    exactly once per produced target.

---

## Appendix C — Canonical flows

**Dedicated startup.** Parse role → handlers → logging and paths → config →
archives and data → validate → deterministic runtime → transport → listening
line.

**Client admission.** Hello → Challenge with cookie → Join with transcript and
compatibility → Welcome with IDs, authenticators, and slot → lobby snapshot.

**Match start.** Freeze roster → manifest → `InitializeMatchWorld` on every node
→ `MatchReady` with baseline digest → `BeginMatch` naming the successor epoch →
per-client frozen prime in `BeginAck` → full barrier → build first bot decisions
→ promote epoch and arm the deadline → first canonical frame.

**One running tic.** Poll transport → check stop horizon and derivable lead →
build absent bot commands for `F` → finalize and emit frame `E` → install and
`RunSimulationTic(E)` → digest → resolve precedence → stop or advance.

**Human loss in v1.** Detect → schedule `StopAfterTic(AbortMatch)` at a future
sequence → reliable notify → every node completes the stop tic →
`ConfirmTerminal` → `TerminalAck` barrier → `ResultsCommit` →
`ResultsCommitAck` barrier → results timer starts.

**Pause and resume.** `PauseAfter(N, controlEpoch)` → all complete `N` and
freeze → `Resume` naming the successor → frozen per-client prime in `ResumeAck`
→ full barrier → build bot decisions for `N + D + 1` → promote and arm → neutral
bootstrap → one canonical `N + 1`.

**Graceful shutdown.** Stop accepting joins → notify → complete or terminate the
current boundary → flush history and logs → close socket → exit with a code.

---

## Appendix D — Feasibility

EC7Wolf already has three of the four hardest ingredients:

1. a fixed-rate deterministic simulation;
2. a complete per-player command boundary;
3. normal multi-slot spawn, movement, weapon, damage, death, and frag rules;
4. **missing:** an identity, protocol, and runtime separation letting the
   authority exist without a player or a presentation.

That fourth item is Phase S, and it is what both projects were blocked on. The
path is:

> make authority independent of player 0; give the command frame a slot
> dimension; build bots as one more producer on that authority; then replace the
> peer mesh with a versioned canonical command hub, extract one headless
> simulation tic, add a no-presentation server lifecycle and binary, and
> re-home the bots onto it.

---

## Sources

- EC7Wolf source at `main` `e897c6a`: `src/wl_net.{h,cpp}`, `src/wl_play.{h,cpp}`,
  `src/wl_agent.{h,cpp}`, `src/g_shared/a_playerpawn.cpp`, `src/wl_main.cpp`,
  `src/r_capture.cpp`, `src/net_watchdog.{h,cpp}`, `src/wl_menu.cpp`,
  `src/CMakeLists.txt`, `wadsrc/static/mapinfo/corridor7.txt`.
- [multiplayer.md](multiplayer.md) — the eight shipped milestones, with the
  measurements and the two known open behaviors.
- [corridor7.md](corridor7.md) and the Technical & Strategy Compendium §9.1 and
  §9.5 — the original's network feature set.
- `tools/test_multiplayer_*.sh`, `tools/netdelay.py`, `tools/netfuzz.py` — the
  existing regression surface.
- GZDoom and Zandronum, as design references only (§40).
