# EC7Wolf dedicated multiplayer server development plan

**Status:** implementation plan; no dedicated-server implementation exists yet

**Scope:** a separate Corridor 7 multiplayer server process that creates no
window, opens no audio device, accepts no gameplay input, owns no human player
slot, coordinates clients, and runs the canonical deathmatch session

**Source snapshot reviewed:** EC7Wolf `multiplayer` branch at `aea72271258b`,
28 August 2026, including the peer-timeout and delayed-button work

**Lineage:** EC7Wolf is based on ECWolf 1.4.2-9-g1bff92d (18 February 2026),
which is derived from Wolf4SDL and incorporates substantial ZDoom-derived
systems. EC7Wolf's own version remains `1.0-betaX`.

**Related plan:** [EC7Wolf multiplayer bot development plan](multiplayer-bots.md)

This document is deliberately exhaustive. It defines what “dedicated” means,
corrects an important upstream assumption, records the current source
constraints, chooses a network architecture, specifies the process and wire
protocol boundaries, describes the headless simulation split, and gives an
ordered implementation and verification program suitable for an AI coding
agent or a human developer.

The short answer is **yes, this can be done**. It is a substantial but bounded
engine project. The existing deterministic 70 Hz playsim and command-driven
players are good foundations. The hard part is not suppressing a window; it is
removing the current assumption that the host, arbiter, network node, local
console, player slot 0, and command producer are all the same entity.

The central design rule is:

> The dedicated server is the session authority and a network peer, but it is
> not a player. It owns no pawn, spawn, inventory, score row, frag target,
> camera, HUD, or local `TicCmd_t`.

The recommended server remains compatible with EC7Wolf's deterministic
lockstep playsim. It receives human inputs, produces any server-owned bot
inputs, validates and sequences one canonical all-player input frame, runs the
same simulation headlessly, and distributes that frame to clients. This is a
**command-authoritative lockstep server**, not a Zandronum-style authoritative
state/event-replication and client-prediction rewrite.

For review, the document is organized into five blocks:

- Sections 1–5 answer feasibility, define the requested result, audit the
  current source/upstreams, and select the architecture.
- Sections 6–10 specify identities, lifecycle, wire protocol, canonical input,
  timing, and the common simulation seam.
- Sections 11–18 specify headless services, build layout, configuration,
  operations, security, failure policy, bots, and performance.
- Sections 19–25 specify tests, milestones, packaging, risks, completion
  criteria, policy decisions, and AI-agent execution rules.
- Section 26 and the appendices provide primary sources, compact flows, review
  questions, rejected shortcuts, and the final feasibility statement.

---

## 1. Executive decisions

These are the decisions around which the plan is written. Changing one is a
design change, not a small implementation detail.

1. **Ship a distinct `ec7wolf-server` executable.** A `--dedicated` path in
   the ordinary executable is useful during development, but it does not by
   itself satisfy the final binary and dependency requirements.

2. **Give the server zero player slots.** A hidden host process, an invisible
   pawn, a spectator pawn, or a forced bot in slot 0 is not the requested
   feature. Such a mode may be a useful temporary diagnostic, but it must be
   named “headless listen host,” not “dedicated server.”

3. **Separate four identities:** process/runtime role, network peer, session
   authority, and player slot. A listen host may be both authority and a
   player-owning peer. A dedicated server is authority and owns no human slot.

4. **Use a star topology.** Each client exchanges gameplay traffic only with
   the server. The server no longer sends every client's address to every
   other client. This simplifies NAT, hides peer addresses, creates one place
   for sequencing and disconnect decisions, and scales better than a full
   mesh.

5. **Preserve deterministic lockstep in the first server release.** Clients
   continue to simulate the full world. The server also runs the full headless
   playsim and is the canonical reference for rules, scores, bot decisions,
   checksums, and match transitions.

6. **Do not begin with full state replication.** A modern server that sends
   actor snapshots/deltas while clients predict and reconcile is possible, but
   it would replace the networking model rather than extend it. It is not
   required to deliver a zero-slot server.

7. **Do not ship a relay-only server as the final design.** A dumb relay can
   sequence packets without loading Corridor 7 data, but it cannot author bot
   inputs, validate the world, determine the canonical winner, diagnose
   desyncs, or enforce gameplay transitions. It may be used as a short-lived
   transport prototype only.

8. **Extract one presentation-independent simulation-tic function.** Both the
   rendered client loop and the dedicated loop call it with an already
   finalized canonical command frame. Rendering, input sampling, audio output,
   menus, interpolation, and frame pacing remain outside it.

9. **Headless means no graphical subsystem initialization.** Running under
   Xvfb, using SDL's dummy video driver, creating a hidden 1x1 window, or
   rendering offscreen does not meet the final requirement.

10. **Audio is a semantic/data service and a presentation service.** The
    server may need sound definitions and deterministic gameplay sound events,
    especially for future bots, but it must never open an audio device or run
    positional mixing.

11. **Retain resource metadata required by gameplay and loading.** Actor
    definitions, sprite-name validity, texture IDs/names, and explicit Corridor
    7 map markers, solidity, triggers, and mutable wall state participate in
    gameplay. Palette-derived structures and pixel-derived masked-wall
    classification are loading/presentation couplings retained during Stage A,
    not asserted authoritative collision state. “No graphics output” must not
    be confused with “load no currently required data.”

12. **Introduce a versioned protocol with an explicit codec.** Do not extend
    the current packed/flexible C++ packet structs and raw-cast untrusted UDP
    bytes. Every field is length-checked before conversion or allocation.

13. **The server controls all lifecycle transitions.** Start, pause, resume,
    disconnect, map change, and shutdown are canonical authority actions; any
    visual countdown is only a canonical-frame-counted client overlay.
    Pre-scheduled actions use explicit simulation phases or control epochs.
    Natural frag-limit outcomes are discovered deterministically while
    every node simulates the terminal tic, then reliably confirmed by the
    authority. A client menu or missing window focus cannot block the match.

14. **Joining is lobby-only in version 1.** Mid-match join and seamless
    reconnect require a complete serialized world snapshot or replay catch-up.
    They are explicitly deferred, with protocol room reserved for them.

15. **A lost client initially causes an authority-scheduled match abort.** A
    later milestone may remove a slot or replace it with a bot at a canonical
    tic. No peer independently drops a player based on its own wall clock.

16. **A lost server always ends the session.** There is no host migration in
    the first release. Clients do not elect a player as a replacement arbiter.

17. **Bots run on the authority.** In a listen match the listen authority runs
    them; with a dedicated server the server runs them. Bot slots produce
    commands but never enter socket, acknowledgement, readiness, or timeout
    accounting.

18. **Administration is local first.** Stdin/terminal and OS service control
    are sufficient for version 1. Do not expose existing debug packets as
    RCON. Any later remote administration uses a separately authenticated,
    replay-protected, rate-limited channel.

19. **Direct-IP play is the first operational target.** A public master
    server, account service, matchmaking, relay network, automatic mod
    download, and NAT traversal service are independent projects.

20. **Linux is the first dependency-slim target, but the architecture is
    portable.** Windows gets a console-subsystem server executable; macOS gets
    a command-line executable rather than an application bundle. Android is
    not a dedicated-server platform.

21. **Never redistribute Corridor 7's commercial files.** The server package
    may contain the EC7Wolf binary, `ec7wolf.pk3`, templates, and freely
    distributable libraries. Operators supply their own Corridor 7 data.

22. **Implement this cleanly in EC7Wolf.** GZDoom and Zandronum are design
    references, not drop-in code libraries. Any copied code would require an
    explicit file/commit provenance and license review.

---

## 2. Definition of done and non-goals

### 2.1 Required user-visible behavior

The feature is complete only when all of the following are true:

- Running `ec7wolf-server` on a machine with no display server and no audio
  device reaches a textual listening state and can complete matches.
- No SDL video, OpenGL, Vulkan, GTK, window-system, joystick, game-controller,
  mouse, or audio-output subsystem is initialized by the server path.
- The server does not appear in the roster, scoreboard, team score, spawn
  list, frag limit, kill feed, automap, or player count.
- A server configured for eleven player slots can host eleven actual player
  slots; its own process is a twelfth session process, not the eleventh pawn.
- Slot 0 may belong to an ordinary remote human or a bot. Authority identity
  is unrelated to slot number.
- Clients connect only to the server address and do not require one another's
  addresses.
- The server chooses and distributes map, mode, class policy (and therefore
  Corridor 7's class-derived teams), frag limit, seed, input delay, roster,
  and start sequence.
- Human inputs are accepted only for the slot owned by the sending peer.
- Every participant installs the same canonical command frame for each tic.
- The server and all clients produce the same full replicated playsim digest
  for a fixed match, including under delay, jitter, loss, duplication, and
  packet reordering within the supported envelope.
- A malformed, spoofed, stale, or unauthorized packet cannot pause, end,
  debug-modify, or otherwise affect a match.
- A client may open local menus without freezing the match. Local UI input is
  never sent as gameplay input.
- A client disconnect produces one server-authored result at one specified
  command sequence; it never leaves the other clients waiting forever.
- `SIGINT`, `SIGTERM`, Windows console close/control, and the local `quit`
  command stop accepting joins, notify clients where practical, close the UDP
  socket, flush logs, and exit without a window or prompt.
- A packaged server runs from its own directory with an explicit local config,
  log/state directory, `ec7wolf.pk3`, and user-supplied game data.

### 2.2 Version 1 scope

- Corridor 7 free-for-all and team deathmatch on the existing multiplayer
  arenas.
- Existing Marine/alien player classes and current frag-limit rules.
- Direct IPv4 UDP connection on the existing default port 5029, with a
  configurable port. Stage A's retained SDL2_net backend binds all interfaces;
  a configurable local address requires the transport abstraction to gain a
  native-socket or other backend that supports it.
- Lobby admission before a match, ready/loading barrier, one or more matches,
  results timing, and deterministic map rotation.
- Up to `MAXPLAYERS == 11` occupied game slots.
- Human-only sessions first; authority-owned bots become an integration
  milestone once the bot implementation exists.
- Local terminal administration and structured/plain text logging.

### 2.3 Explicit non-goals for the first release

- Mid-match join, spectator streaming, seamless reconnect, live slot takeover,
  or host migration.
- A Zandronum-compatible or GZDoom-compatible wire protocol.
- Interoperation with the original DOS IPX, modem, or serial protocols.
- Client prediction and server reconciliation of state snapshots.
- Server-side rewind/unlagged hit validation.
- Encryption of all gameplay traffic or a comprehensive anti-cheat system.
- Public accounts, identity federation, ranking, matchmaking, master-server
  listing, automatic downloads, or a web control panel.
- Voice chat, server-recorded video, graphical administration, or a virtual
  spectator camera.
- Saving and resuming live multiplayer worlds.
- Packaging any commercial Corridor 7 data.

### 2.4 Terminology

| Term | Meaning in this plan |
| --- | --- |
| **runtime role** | Standalone client, network client, listen authority, or dedicated authority |
| **peer** | One authenticated network connection/process in a session |
| **authority** | The one server-side peer that owns roster, sequencing, rules, and lifecycle |
| **player slot** | An index into the simulated player arrays and its pawn; never the server process |
| **controller** | The source of a slot's commands: a human peer or an authority-owned bot |
| **local player** | The human slot sampled by an interactive process, if one exists |
| **local view** | The slot/camera rendered by an interactive process, if one exists |
| **listen authority** | A rendered host that is authority and also owns a local human slot |
| **dedicated authority** | A playerless, headless server process |
| **input submission** | A client's proposed command for its owned future tic |
| **input epoch** | A match-local command timeline created at begin/resume; old-epoch commands are never reused |
| **canonical input frame** | The authority-approved commands for every active slot at one sequence |
| **playout depth `P`** | The target number of contiguous canonical frames a rendered client buffers to absorb jitter/clock drift |
| **playsim/world digest** | A stable hash of replicated, decision-relevant simulation state at one tic; excludes authority-private bot-brain state |

---

## 3. What exists now

This is a source audit, not an assumption based on ECWolf's ancestry. Line
numbers will move; the named functions and responsibilities are the durable
references.

### 3.1 Current multiplayer is player-to-player lockstep

[`src/wl_net.h`](../src/wl_net.h) defines only `MODE_SinglePlayer`,
`MODE_Host`, and `MODE_Client`. `NetInit::numPlayers` means, depending on the
call site, all of these at once:

- number of UDP participants;
- number of command producers;
- number of connected addresses;
- number of initialized `player_t` objects;
- bound for spawn, score, frag, inventory, and respawn loops.

[`src/wl_net.cpp`](../src/wl_net.cpp) hard-codes the arbiter as 0.
`Net::IsArbiter()` is currently `ConsolePlayer == Arbiter`. `StartHost()` begins
at `nextclient = 1` because “0 is the host”; it waits for `numPlayers - 1`
addresses. `StartJoin()` receives `playerNumber` and writes it directly to
`ConsolePlayer`.

`NetClient Client[MAXPLAYERS]` is indexed by player number. The start packet
contains the other players' addresses, creating a full mesh. `Net::NewGame()`
contributes one setup record at `newGamePackets[ConsolePlayer]` and treats
player 0's map and difficulty as authoritative. The tic paths serialize
exactly one local command from `control[ConsolePlayer]`, skip that index when
sending, and wait over the player count.

Consequences:

- Adding `MODE_Dedicated` alone cannot work.
- Leaving `ConsolePlayer == 0` creates a local player even if nothing is drawn.
- Setting `ConsolePlayer` to `-1` or `MAXPLAYERS` is unsafe because it is an
  unsigned index used directly in hundreds of array expressions.
- Incrementing `numPlayers` for the server creates a pawn and consumes a slot.
- Excluding one index from spawn loops while leaving it in network loops
  produces mismatched arrays and deadlocks.
- A server with eleven remote humans needs eleven player slots plus one
  authority process; `MAXPLAYERS` cannot remain the bound for “all session
  nodes.”

The first architectural milestone must therefore split peer identity from
player-slot identity. No headless flag can substitute for it.

### 3.2 The simulation seam is usable but not yet extracted

[`PollControls`](../src/wl_play.cpp) currently samples keyboard, mouse, and
joystick into `control[ConsolePlayer]`, performs network exchange, and also
handles local/global UI buttons. [`APlayerPawn::Tick`](../src/g_shared/a_playerpawn.cpp)
then consumes `control[player->GetPlayerNum()]` and enters normal use, weapon,
movement, collision, pickup, damage, death, frag, and respawn paths.

Within [`PlayLoop`](../src/wl_play.cpp), the useful deterministic body is
approximately:

```text
install finalized commands
increment gamestate.TimeCount
CheckSpawnPlayer
tick VICTORY, WORLD, PLAYER, and NORMAL thinker categories in that order,
  with the existing post-VICTORY short-circuit when victoryflag is set
AActor::FinishSpawningActors
compute deterministic capture/digest
```

It is currently surrounded by client-only work:

- SDL event processing and local input;
- render-derived tic calculation;
- interpolation and dynamic-wall render snapshots;
- `PlayFrame`, HUD, automap, scoreboard, and buffer presentation;
- screenshot/capture frame actions;
- texture animation updates;
- positional sound localization;
- keyboard/debug/menu checks.

Extracting `RunSimulationTic(const CanonicalInputFrame&)` is the central
headless seam. Generate or receive every slot's command before any thinker is
ticked so player-slot iteration order cannot affect command decisions.

There is also a present determinism hole that must be closed before a headless
authority can be a reference world: mouse-look input changes the local
console pawn's pitch directly, while the current network tic packet carries no
pitch delta. Either add a bounded synchronized pitch field to the canonical
gameplay command and apply it only at the command boundary, or disable/reset
mouse look for network deathmatch if it is intentionally unsupported. A client
must never mutate simulated actor orientation from local input outside the
canonical frame.

### 3.3 Startup is unconditionally client-oriented

The POSIX entry point calls `gtk_init_check()` unless built with `NO_GTK`.
[`WL_Main`](../src/wl_main.cpp) locates data, initializes WADs, probes CD
music/upscale/FLIC content, initializes renderer resources, calls `InitGame`,
and enters `DemoLoop`.

`InitGame()` currently performs all of the following in one path:

- SDL base initialization;
- MAPINFO, texture manager, palette, font, lookup-table, and actor setup;
- renderer capability check and a temporary VGA/window mode;
- graphics shutdown registration;
- input/joystick/controller startup;
- sound/audio-device startup;
- key messages, status bar, and quiz module setup;
- interactive network status callbacks;
- menu creation, sign-on display, input waits, jukebox check;
- renderer backend initialization.

Before `InitGame`, `WL_Main` also calls `R_InitRenderer()`. This is distinct
from `R_InitRendererBackend`: it does not create the window, but initializes
software 2-D drawing/translation function tables and creates a Stage B source/
link seam. Runtime headlessness may retain it temporarily; the slim target
must split or skip it before omitting `r_2d` implementation units.

`DemoLoop`, `GameLoop`, and `PlayLoop` assume presentation. Suppressing
`PlayFrame()` would still create a window, start audio and input, construct
menus, access a local player, and use presentation-driven lifecycle screens.

The required split is not “sprinkle `if (!dedicated)` around this function.”
It is:

```text
WL_Main
  +-- parse role before platform presentation startup
  +-- initialize paths/config/logging
  +-- initialize common resource and gameplay metadata
  +-- client role: initialize presentation and enter ClientMainLoop
  `-- server role: initialize server services and enter DedicatedMainLoop
```

A failure to bind, load the configured map, validate data, or initialize the
server protocol must be fatal on the dedicated path. The current behavior of
abandoning a failed network setup and silently entering single-player would be
dangerous for a service.

### 3.4 “No rendering” does not mean “no resource metadata”

Several current dependencies are easy to break with an over-aggressive
server-only source list:

- `IWad::SelectGame` may open an interactive picker when data selection is
  ambiguous. A server must require or deterministically resolve explicit data
  and fail to stderr instead.
- Corridor 7 startup currently validates map, audio, VGA, and graphic file
  families. A maps-only data promise cannot be made without first changing
  that validation contract.
- `ClassDef::LoadActors` parses actor definitions, initializes sprite
  metadata, and actor spawning may reject/replace an actor with an invalid
  sprite. Sprite registry information is presently part of a valid gameplay
  load even if no pixels are displayed.
- Corridor 7 map translation reads texture pixels to derive
  `maskedWallType`, but current consumers are renderer/visibility code.
  Movement instead uses tile presence, `sideSolid`, slide/push state, and
  Corridor 7's current gameplay sight query treats every extant tile as
  blocking. Texture names/IDs, sprite validity, explicit map markers, tile
  solidity, triggers, wall IDs, and mutable map state remain gameplay data.
  Retain pixel-derived masking in Stage A for parity, then separate that
  presentation classification from the authoritative map before removing
  pixel decoders.
- `CA_CacheMap` currently calls render visibility calculation, which depends
  on projection values created by video setup. That call must become
  client-only; feeding it dummy projection constants would conceal the
  coupling rather than remove it.
- `SetupGameLevel` mixes common map/spawn work with music start and render
  snapshot reset. It needs common and presentation phases.
- `StartMusic`/`SelectLevelMusic` uses the already separate named
  `Corridor7Music` RNG even when CD audio is selected. That stream is used only
  for soundtrack choice, so it is presentation state—not playsim state—and is
  excluded from the authoritative RNG registry/digest. The server may skip it;
  rendered clients may retain/advance it for repeatable soundtrack order.

The first headless target may retain texture codecs, sprite metadata, palette
tables, and SDL base timing. The final criterion is no graphical launch or
device, not the smallest possible executable on day one.

### 3.5 `ConsolePlayer` and presentation effects reach gameplay code

The source contains hundreds of `ConsolePlayer` references. Important classes
of risk include:

- rendering and projection directly index `players[ConsolePlayer]`;
- `NewGame` initializes only `playerClassNames[ConsolePlayer]` before network
  exchange;
- gameplay-side FOV/rebirth paths recalculate global projection;
- weapon and door sound calls compare against
  `players[ConsolePlayer].camera`;
- door zone-linking code dereferences the console pawn while deciding whether
  to start presentation sound sequences;
- damage, inventory, keys, dispensers, chambers, elevators, death fades, and
  other simulation-reachable code calls `StatusBar`;
- local-camera map visibility flags are updated from gameplay/map code;
- global cheats such as `godmode` can affect all players if inherited from a
  server config.

Never encode “no local player” as an out-of-range `ConsolePlayer`. Introduce
explicit queries and nullable handles:

```cpp
bool HasLocalPlayer();
std::optional<PlayerSlot> LocalPlayerSlot();
bool HasLocalView();
std::optional<PlayerSlot> LocalViewSlot();
bool IsLocalViewSlot(PlayerSlot slot);
```

Common simulation code takes an explicit slot or actor. Presentation calls go
through event sinks/services that have real client and deliberate null-server
implementations. A `NullStatusBar` is a safe transition tool because the
abstract interface already exists, but the desired endpoint is a presentation
notification sink rather than a fake HUD object in the server.

### 3.6 Current packet safety is not a server-grade baseline

The new protocol must not inherit these patterns:

- `RequestPacket` is a bare type byte with no magic, version, session, nonce,
  cookie, compatibility data, or anti-spoof proof.
- The first distinct source addresses can occupy lobby positions, allowing
  trivial slot exhaustion.
- Packed C++ structs are cast directly over untrusted UDP bytes.
- `CheckPacketType<T>` checks only `sizeof(T)` and the type, then byte-swaps
  before a variable-length packet can be validated.
- `StartPacket` allocates `numPlayers - 1` trailing `Client` entries, while
  `StartPacket::ByteSwap()` loops `i < numPlayers`. Both encoding and decoding
  can access one entry beyond the allocation.
- Some control packets are acted upon or acknowledged without first proving
  the source is an authenticated peer and authorized authority.
- A forged `EndGamePacket` can reach the end-game path; block, input-ack, and
  debug handling have similarly weak source/role boundaries.
- Tic packets infer slot identity from address and do not carry or validate an
  explicit ownership claim, axis envelope, or gameplay-button mask.
- There is no session ID, connection token, replay window, or authority-only
  control-event validation.
- Startup and lobby waits can be indefinite.

The in-progress working-tree timeout improves the “wait forever” failure mode,
but it remains locally decided, peer-as-player logic. A dedicated server needs
one persistent liveness record per peer and one canonical disconnect/abort
event chosen by the authority.

The hostile-network test must use the real protocol codec or fixed vectors
emitted by it. A separately hand-maintained Python enum/packing guess can test
the wrong message type and create false confidence.

### 3.7 Build system is a single client executable

[`src/CMakeLists.txt`](../src/CMakeLists.txt) currently creates one monolithic
`engine` target containing gameplay, renderers, UI, input, audio, networking,
resource loaders, menus, and platform entry points. It always links SDL2,
SDL2_net, SDL2_mixer, JPEG, xBRZ, and other dependencies; desktop options add
GTK and OpenGL/libepoxy.

There is no server target or common-core target. The PK3 build/install logic
also assumes the `engine` target's output directory. A real server build
requires source-list and target restructuring, but behavior should be proven
before aggressively trimming metadata/resource dependencies.

---

## 4. What GZDoom and Zandronum actually prove

### 4.1 The GZDoom premise needs one correction

Current mainline GZDoom does not provide a zero-slot dedicated-server binary.
Its network modes are `NET_PeerToPeer` and `NET_PacketServer`; the latter makes
the **playable host** collect and redistribute command streams. `-host N`
counts the host as a connected player, and the source reports the host as
“Player 1 of N.” Every process still runs deterministic tics. The host path
suppresses a decorative startup screen, not graphics, input, audio
infrastructure, texture/render initialization, or the display loop.

Primary evidence:

- [GZDoom network-mode enum](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/common/engine/i_net.h#L38-L42)
- [GZDoom `HostGame`, including the host as the first connected player](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/common/engine/i_net.cpp#L976-L1035)
- [GZDoom's `D_CheckNetGame` “Player N of N” reporting](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_net.cpp#L1900-L1923)
- [GZDoom packet-server collection and redistribution](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_net.cpp#L1546-L1785)
- [GZDoom game/display loop](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_main.cpp#L1236-L1278)
- [GZDoom host still follows graphics initialization](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_main.cpp#L3286-L3452)

That packet-server model is nevertheless a useful conceptual precedent for a
central command hub. It is not the requested process semantics.

### 4.2 Zandronum is the relevant dedicated-server precedent

Zandronum has an explicit zero-player `NETSTATE_SERVER`. On POSIX, `-host`
initializes only SDL timing and the server skips framebuffer/display output,
gameplay input, and audio-device output. On current non-Windows, non-Apple
builds, `SERVERONLY` additionally sets `NO_SOUND`, `NO_GTK`, `NO_GL`, and
`NO_LIBSECRET`, defines `SERVER_ONLY`, and names the output
`zandronum-server`. It still links SDL and retains a software-renderer
abstraction plus substantial texture, sound-definition, menu, and gameplay
metadata initialization. Windows `-host` instead opens a graphical
server-console dialog.

Primary evidence:

- [Zandronum runtime network states](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/network.h#L267-L282)
- [The server is never a console player](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/network.cpp#L1572-L1584)
- [Runtime role dispatch to `SERVER_Tick`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/d_main.cpp#L1275-L1363)
- [Zandronum's server tick loop](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sv_main.cpp#L703-L942)
- [Zandronum `SERVERONLY` build configuration](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/CMakeLists.txt#L188-L202)
- [Zandronum POSIX timer-only host startup](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sdl/i_main.cpp#L273-L303)
- [Zandronum server screen/metadata initialization split](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/d_main.cpp#L2921-L2950)
- [Zandronum null sound selection for `-host`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sound/i_sound.cpp#L249-L272)
- [Zandronum Windows server-console startup](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/win32/i_main.cpp#L929-L935)
- [Official Linux client/server-only build matrix](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/.github/workflows/ci-linux.yml#L16-L76)

Zandronum also retains substantial data-side texture/render infrastructure in
server builds. That validates the distinction between “no display” and “no
asset metadata.”

### 4.3 What not to copy from Zandronum

Zandronum is a full client/server state/event-replication engine with join in
progress, an on-connect full update, explicit server commands for incremental
actor/world changes, client prediction, unlagged history, master-server
functions, bans, RCON, and many years of Doom-specific protocol behavior.
Transplanting it would be a larger and riskier project than adapting EC7Wolf's
existing deterministic model. See its
[`SERVER_SendFullUpdate`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sv_main.cpp#L2590-L3031)
as an indication of the state surface a true join-in-progress client needs.

Use these ideas:

- explicit server runtime role before subsystem initialization;
- zero console-player semantics;
- separate server tick loop;
- socket polling while waiting for the next fixed tic;
- null presentation and dependency-reduced server build;
- local administrative input and orderly shutdown;
- separate maximum clients and maximum active players;
- server-owned bots without a server pawn.

Do not copy its protocol, Doom actor replication, unlagged system, master
server, RCON, or residual renderer abstractions into the first implementation.

### 4.4 Licensing/provenance rule

Current GZDoom is distributed under GPLv3, and the reviewed `d_net.cpp` is
explicitly GPL-3.0-or-later; see the
[GZDoom license](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/LICENSE)
and
[`d_net.cpp` notice](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_net.cpp#L1-L22).
EC7Wolf's own [`docs/copyright`](copyright) records that the linked binary is
already distributable under GPLv3 because of xBRZ, but that does not remove
file-level provenance, attribution, notice, or corresponding-source duties.

Zandronum's server files retain Skulltag's four-condition license, including
source and binary notice retention, no endorsement, and complete-source
availability information. The project describes it as GPL-compatible, while
individual files may carry additional notices; see the
[root license](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/LICENSE.txt),
[project explanation](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/README.md#L46-L53),
and
[`sv_main.cpp` notice](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sv_main.cpp#L1-L49).

The plan therefore requires an independently written EC7Wolf implementation
based on observed architecture. Before copying any external source, record:

- repository and immutable commit;
- exact source file and lines;
- license header and required notices;
- compatibility with the complete EC7Wolf distribution;
- corresponding source and attribution changes.

This plan uses architectural observations and requires an independently
written implementation. Paraphrasing or mechanically translating source does
not avoid its license obligations.

---

## 5. Architecture alternatives and selected design

### 5.1 Decision matrix

| Design | No window | No server slot | Server validates world | Preserves current lockstep | Late join | Relative effort | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Hidden/dummy-video listen host | partial | no | same as current host | yes | no | low | reject as final |
| Playerless packet relay only | yes | yes | no | yes | no | medium | prototype only |
| Playerless command-authoritative lockstep server | yes | yes | yes | yes | no in v1 | high but bounded | **selected** |
| Full authoritative state replication | yes | yes | yes | no; replaces it | possible | very high | future project |

### 5.2 Why the selected model fits EC7Wolf

The existing simulation already expects one command per active slot per tic.
Movement, collision, doors, weapons, pickups, damage, death, frag credit, and
respawn happen after that command boundary. The current determinism harness can
be extended to compare server and clients. The selected design changes who
collects and finalizes commands, not how the game interprets them.

The server loads the same gameplay data and runs the same world for four
reasons:

1. It can determine the canonical score, frag-limit event, winner, and next
   match instead of trusting a client.
2. It can run future bot brains from the correct start-of-tic world.
3. It can compare client digest reports with its own and diagnose/descope a
   divergent client.
4. It prevents clients from fabricating inventory, damage, position, or score
   messages because those messages do not exist; clients submit only bounded
   inputs.

Clients still know and simulate the full world. This is not secrecy-based
anti-cheat. A modified client can still automate aim or reveal local world
information. Preventing that would require a very different trust model.

### 5.3 Target process topology

```text
                       control plane / authority
                 +--------------------------------+
                 |        ec7wolf-server          |
                 |                                |
 human input --->| validate ownership + sequence  |
 bot brains ---->| build canonical InputFrame[T]  |
                 | run full headless playsim      |
                 | score/digest/lifecycle/admin   |
                 +-------+-------------+----------+
                         |             |
                 canonical frames  canonical frames
                         |             |
                  +------v------+ +----v---------+
                  | EC7Wolf     | | EC7Wolf      |
                  | client A    | | client B     |
                  | slot 0      | | slot 1       |
                  | full playsim| | full playsim |
                  | render/audio| | render/audio |
                  +-------------+ +--------------+

No client-to-client gameplay datagrams.
The server has a PeerId, but no PlayerSlot.
```

### 5.4 Listen authority and dedicated authority share one model

The session library should support both:

- **listen authority:** one interactive process is authority, has a local
  human slot and local view, and uses the same canonical input-frame machinery;
- **dedicated authority:** one headless process is authority, has neither a
  local human slot nor local view.

They should not be implemented as unrelated protocols. A listen authority can
initially keep a local transport shortcut, but its local command must still be
validated/finalized into the same canonical frame before simulation. This
keeps bots, pause, disconnect, roster, and tests consistent.

That shortcut includes epoch priming. For each Begin/Resume record, a listen
authority samples its local human exactly once and creates an immutable in-
process `EpochPrime` containing the same match, record hash, parent/successor
epochs, target sequence, slot, and encoded command as a remote ACK prime. It
passes the identical ownership/range/button validation and participates in the
complete prime barrier; only UDP transport and a network ACK are omitted. The
authority may not activate/arm the epoch until this local record and every
required remote ACK/prime exist. Dedicated authorities have no local prime.

Legacy peer-to-peer protocol compatibility may be retained temporarily behind
an explicit version/mode. A new client must never guess whether an unversioned
datagram is legacy or dedicated protocol.

---

## 6. Required data model and invariants

### 6.1 Runtime and session types

The names are illustrative; the separation is mandatory.

```cpp
enum class RuntimeRole : uint8_t
{
    Standalone,
    NetworkClient,
    ListenAuthority,
    DedicatedAuthority
};

using PeerId = uint16_t;
using PlayerSlot = uint8_t;

enum class SlotKind : uint8_t
{
    Empty,
    Human,
    Bot
};

struct PlayerSlotInfo
{
    PlayerSlot slot;
    SlotKind kind;
    uint32_t controllerGeneration; // manifest-assigned; increments on replacement
    std::optional<PeerId> ownerPeer; // required for Human, none for Bot
    FString name;
    FName playerClass;
    // Corridor 7 v1 derives team from playerClass via PlayerTeam(slot).
    // Do not serialize an independent, possibly contradictory team here.
    std::optional<BotProfileId> botProfile; // required for Bot only
    std::optional<uint64_t> controllerSeed; // required for Bot only
};

struct PeerInfo
{
    PeerId id;
    ConnectionId connection;
    PeerState state;
    std::optional<PlayerSlot> humanSlot;
    Address address;                // authority-side only
    CapabilityBits capabilities;
    LivenessState liveness;
};

struct SessionState
{
    RuntimeRole role;
    PeerId authorityPeer;
    std::optional<PeerId> localPeer;
    std::optional<PlayerSlot> localHumanSlot;
    std::optional<PlayerSlot> localViewSlot;
    PlayerSlotInfo slots[MAX_PLAYER_SLOTS];
    MatchRules rules;
    SessionLifecycle lifecycle;
};
```

Do not serialize `LocalHuman` versus `RemoteHuman` as slot kinds. Those labels
are perspective-dependent. The canonical description is `Human + ownerPeer`;
local/remote is derived by comparing that owner with the process's local peer.

### 6.2 Separate capacities

At minimum define and validate these independently:

```text
MAX_PLAYER_SLOTS  = 11     simulated humans + bots
MAX_CLIENT_PEERS  = 11     remote human connections in v1
MAX_SESSION_PEERS = 12     dedicated authority + all clients
```

Future spectators may make `MAX_CLIENT_PEERS` exceed `MAX_PLAYER_SLOTS`, so
avoid baking equality back into new APIs. The authority need not occupy an
entry in an array of remote client connections merely because it has a logical
PeerId.

### 6.3 Non-negotiable invariants

Assert these in debug builds and test them in release behavior:

1. Exactly one peer is the authority.
2. Dedicated authority has no human slot and no local view.
3. A listen authority has zero or one local human slot; if present, that slot
   is owned by its local peer.
4. Every active human slot has exactly one authenticated owner peer.
5. No peer owns more human slots in version 1.
6. A bot slot has no network owner and no liveness/readiness obligation; it
   has exactly one validated profile, controller seed, and controller
   generation.
7. An empty slot has no pawn, controller, score row, or command.
8. A peer ID is never used as a player-array index without an explicit map.
9. A player slot is never used as a connection-array index without an
   explicit map.
10. `MAX_PLAYER_SLOTS` bounds simulation arrays only.
11. Only the authority emits canonical input frames and lifecycle events.
12. A client may submit commands only for its owned human slot.
13. All active slots appear exactly once in each canonical input frame.
14. No synthetic slot representing the server process enters spawn, frag,
   inventory, camera, or scoreboard loops. The headless server still runs the
   ordinary loops for every active remote-human and bot slot.
15. Gameplay simulation never requires `ConsolePlayer` or a local camera.
16. In Corridor 7 team deathmatch v1, a slot's team is derived canonically
   from its player class through the existing `PlayerTeam` rule. If independent
   teams are ever added, introduce a validated `TeamId` and migrate damage,
   aggregate frags, scoreboard, and frag-limit code together.

### 6.4 Replace overloaded conditionals with semantic predicates

Transport mode is not a gameplay rule. Add and use narrow queries such as:

```cpp
Session::IsNetworked();
Session::IsAuthority();
Session::IsDedicated();
Session::HasLocalPlayer();
Session::HasLocalView();
Session::IsDeathmatch();
Session::AllowsRespawn();
Session::RespawnsItems();
Session::NoMonsters();
NetTransport::IsOpen();
```

Audit every current `Net::InitVars.mode != MODE_SinglePlayer` use. Some mean
deathmatch rules, some mean multiple simulated players, some mean sockets are
active, and some mean local menus/saves should be disabled. Those meanings
diverge in offline bots, listen servers, and dedicated servers.

### 6.5 Roster mutability policy

Version 1 locks the player roster before loading a match. Configuration may
change in `LobbyOpen` and after results; it may not add/remove/reassign slots
while `Running`.

A disconnect is not an ordinary roster edit. While `Running` with no unresolved
stop, the authority schedules `StopAfterTic(AbortMatch)`; if a stop already
exists, it retains that sole boundary, updates the survivor set, neutralizes
the lost slot through it, and records disconnect metadata. While paused, it
confirms the existing frozen terminal tic as section 16.1 defines. Later, a
versioned `RosterChange(ApplyBeforeTic(E))` can remove a pawn or
replace a human controller with a bot deterministically. Never let each peer
infer that change from local timeout time.

---

## 7. Session lifecycle

### 7.1 Explicit state machine

```text
Boot
  -> LoadingData
  -> LobbyOpen
  -> RosterLocked
  -> LoadingMatch
  -> ReadyBarrier
  -> Running
  -> TerminalPending
  -> Results
  -> LobbyOpen       (configuration/roster may change)
  -> LoadingMatch    (automatic fixed roster rotation)
  -> ShuttingDown

Any state -> FatalError
Any nonterminal state -> ShuttingDown
LobbyOpen/RosterLocked/LoadingMatch/ReadyBarrier -> Aborting
  -> LobbyOpen or ShuttingDown
Running -> Paused -> ResumeBarrier -> Running  (new input/control epoch)
Paused or ResumeBarrier -> TerminalPending     (abort at frozen completed tic)
```

Each transition has one owner and one timeout. Do not infer lifecycle from
whether a particular graphical function returned.

### 7.2 Boot and data loading

The server:

1. parses server role and command line before GUI/video setup;
2. installs signal/control handlers;
3. opens logging and validates writable state paths;
4. reads server configuration with documented precedence;
5. loads `ec7wolf.pk3` and explicitly selected Corridor 7 data;
6. validates engine protocol, data profile, maps, definitions, and rotation;
7. initializes deterministic RNG streams and common simulation services;
8. initializes UDP transport and starts listening;
9. reports one machine-readable readiness line only after all required steps
   succeed.

There is no IWAD picker, startup page, jukebox, cinematic probe that opens a
window, menu fallback, or “continue single-player” path.

### 7.3 Lobby

The authority owns:

- connection admission and optional password policy;
- unique display-name normalization;
- one human slot assignment per accepted gameplay peer;
- class selection policy and the resulting class-derived team assignment;
- maximum clients, maximum players, and minimum ready players;
- bot fill configuration when bots exist;
- match rules, map/rotation, seed, and delay;
- ready state and start policy.

Version 1 accepts gameplay joins only in `LobbyOpen`. While a match is running,
the server may answer a bounded status query or a join request with an explicit
`MatchInProgress` rejection; it must not silently discard the request and make
the client wait.

### 7.4 Roster lock, loading, and ready barrier

When start conditions are met:

1. Authority freezes the roster and computes its canonical hash.
2. Authority chooses a new unpredictable match ID, map, mode/rules, seed,
   input delay, and first executable simulation sequence.
3. `MatchManifest` is sent reliably to every accepted peer.
4. Authority and every client call the same
   `InitializeMatchWorld(manifest)`: assign the seed; reset the versioned
   gameplay-authoritative RNG streams and all per-match state; load/translate
   the map; generate arena starts; and spawn map actors and players through the
   same **pre-first-tic** boundary as current `SetupGameLevel`.
   `AActor::FinishSpawningActors()` is deliberately not called early: the
   baseline digest is computed with a canonical representation of the pending-
   spawn order plus relevant just-spawned state. The first executable tic later
   reaches the ordinary thinker/finish-spawning boundary in its legacy order.
5. Each client replies `MatchReady` containing the manifest hash, map/data
   hash, and initial deterministic state digest.
6. Authority waits until all required humans are ready or the ready timeout
   expires.
7. Authority creates the canonical neutral bootstrap interval required by the
   negotiated input delay and sends a reliable `BeginMatch` carrying the match
   ID, first sequence, delay, **successor** input epoch, client playout target,
   and canonical neutral-bootstrap definition/hash. Its common-header epoch is
   the parent epoch (`0` before the first match command epoch); the successor
   is named only in the authenticated payload.
8. Each required remote client samples its owned human command exactly once from the
   `start - 1` baseline for target `start + D`, freezes those bytes for retry,
   and semantically acknowledges the exact begin record with a `BeginAck` that
   contains the command. The ACK header still uses the parent epoch and its
   payload echoes the begin semantic ID, parent epoch, successor epoch, target
   sequence, exact begin-record hash, and primed command. A retransmission
   resends the same command; it never resamples physical input. A listen
   authority creates section 5.4's equivalent immutable local `EpochPrime`; it
   is not exempt from the barrier or validation merely because it has no client
   socket to itself.
9. Receiving a remote ACK or installing the local prime creates or confirms
   only a **pending** successor epoch. If
   a required peer fails, dropping it invalidates the roster/manifest and
   returns the session through the lobby/ready process; the authority must not
   start the old manifest with one peer silently removed. After every required
   remote ACK and local/remote prime is validated, the authority generates and
   caches each bot's first
   decision for `start + D` exactly once, promotes the successor epoch, and
   only then arms a fresh monotonic deadline. The first canonical frame carries
   the successor epoch and commits that transition for clients that already
   hold the matching pending record. No deadline accrues during the barrier.
   Canonical-frame emission begins at the agreed first sequence. There is no
   authoritative `Countdown` lifecycle state. A visual
   countdown, if desired, is a client overlay counted from canonical bootstrap
   frames while the session is already `Running`; it has no correctness-
   critical wall-clock, input, or thinker semantics of its own.

A client is not considered ready merely because it acknowledged a UDP packet.
The initial state digest is defined at the completed-sequence baseline one tic
before the first executable sequence. No node starts because its local clock
reached a server timestamp. A future polished synchronized countdown would
need an explicit clock-offset/uncertainty protocol; it is not smuggled into
the first dedicated implementation.

This reset boundary is mandatory because current global random streams are
cleared at process initialization rather than `NewGame`, while arena start
generation and level setup consume seed/state in source-sensitive order.
Match B with manifest X must have the same initial digest in a fresh process
and after any unrelated match A, including through repeated server rotation.

### 7.5 Running and results

The authority advances only canonical input sequences. The full server playsim
and every client deterministically discover frag limit or another natural
outcome while simulating terminal tic `N`. `RunSimulationTic(N)` returns a
candidate outcome. Each node immediately enters `TerminalPending`, does not
simulate `N + 1`, and keeps pumping transport. The authority verifies its own
candidate/digest and reliably emits the generic
`ConfirmTerminal(matchId, inputEpoch, N, terminalKind, reason, worldDigest,
scoreDigest, standings, winnerOrTie?)`. A matching client records the terminal
result and may display a provisional results overlay, but retains the terminal
match context; a mismatch is a desync/failure, not permission to keep playing.

A client that receives `ConfirmTerminal` before it has locally completed `N`
queues it and continues only through `N`; it never skips simulation to display
results. A client that has completed `N` may wait in `TerminalPending` for the
reliable confirmation while continuing transport/liveness.

For the frozen-tic failure path, a valid confirmation received in `Paused` or
`ResumeBarrier` atomically retires any pending successor epoch, transitions the
client to `TerminalPending`, validates the unchanged completed-`N` digests, and
only then permits `TerminalAck`. It cannot remain paused and subsequently
reject the matching results commit.

Each surviving client semantically acknowledges the exact confirmation with
`TerminalAck(hashOfConfirmTerminal)`. The authority retains terminal canonical
history and match context until every survivor ACKs or the terminal-ACK timeout
causes an explicit peer drop. It then reliably emits
`ResultsCommit(matchId, inputEpoch, N, hashOfConfirmTerminal,
commitSemanticId, resultsDuration)`; receipt is the client's authoritative
transition to `Results`, and clients return
`ResultsCommitAck(hashOfResultsCommit)`. The commit hash canonically covers all
fields, including its never-reused session semantic ID; an ACK from a prior
terminal record, match, or commit cannot satisfy this barrier. Sending the
commit moves the authority to `Results` with a `commitAckPending` substate. A
client queues a commit that somehow arrives
before its exact terminal record is validated; it cannot transition merely on
the hash or ACK a terminal state it has not simulated. The authority retains
terminal recovery state and does not start the results timer or send the next
manifest until every remaining peer ACKs that commit or is explicitly dropped.
Only after this second barrier may it discard old playsim/frame history or
reset match-local sequence windows.

`resultsDuration` therefore cannot expire either barrier. Its authoritative
timer starts after the ResultsCommit-ACK/drop barrier, not when the first
terminal confirmation datagram was sent. A reordered next-manifest packet is
rejected/queued until `ResultsCommit` has transitioned that client to
`Results`.

Natural outcomes are therefore not fictional events scheduled at `N` after
`N` has already happened. A scheduled abort also ends with the same
`ConfirmTerminal`/`TerminalAck`/`ResultsCommit` protocol after its committed
stop tic. A disconnect discovered while paused uses the same protocol for the
already completed frozen tic without pretending another tic occurred, as
specified in section 16.1. A controlled `ServerOverload` that cannot safely
advance another derivable input frame likewise confirms the last completed tic
without charging clients or fabricating a world event. Only externally
requested actions known in advance, such as admin abort or a running-state
disconnect policy, use a future explicit boundary phase.
Clients render their own non-blocking scoreboard/tally from the confirmed
outcome; the server never calls `C7Scoreboard_ShowTally()` or waits for
`ACK_Any`.

At results expiry, the authority either:

- returns to an open lobby;
- locks the unchanged roster for the next rotation entry **only if every human
  in that roster remains admitted**;
- if any terminal/commit timeout or explicit leave dropped a human, returns to
  `LobbyOpen` and builds a new roster hash/manifest/match ID. An explicit next-
  match bot-fill policy may occupy the missing slot, but that is a new roster,
  never “unchanged” automatic rotation;
- stops after one match when `--once` is configured;
- shuts down on admin/service request.

### 7.6 Pause policy

Client pause/menu/status/automap buttons are local UI and must not enter the
gameplay command codec. Deathmatch defaults to unpausable.

While a client has a local menu open, its network and simulation pumps keep
running and it submits canonicalizable neutral gameplay intent for its human
slot. The pawn remains in the match and may be attacked. Closing the menu does
not require a global unblock packet. If a future overlay intentionally permits
movement while open, that is an explicit client UX policy; it still sends only
normal gameplay fields.

If admin pause is supported, it uses a control epoch rather than pretending a
future simulation sequence can elapse while simulation is stopped:

1. Authority chooses `N` beyond both the semantic-ACK margin and the greatest
   bot-decision horizon already built, then reliably preannounces tentative
   `PauseAfter(N, controlEpoch)`. From that decision onward, clients stop
   producing and the authority stops accepting/building human or bot input
   beyond `N`; bot brain/PRNG state must not advance for a command that will be
   discarded. A non-ACKing peer is dropped/causes the declared abort policy;
   the server does not silently cancel pause and resume with a hole in the
   input pipeline. If a disconnect is detected while this pause stop is
   unresolved, do not schedule a competing abort stop: complete the surviving-
   peer pause barrier and terminate from its frozen `N` as section 16.1
   specifies.
2. Every node completes `N`, enters `Paused(controlEpoch)`, emits no `N + 1`, and
   continues transport, liveness, admin, and UI processing. The authority and
   clients freeze the old scheduler/input epoch; no wall-clock deadline keeps
   accruing.
3. Authority reliably sends `Resume(oldControlEpoch, oldInputEpoch,
   newInputEpoch, N + 1, D)` and enters `ResumeBarrier`. The message header uses
   the still-active old input epoch; its payload proposes the successor.
   Remote clients discard old future submissions and canonical playout buffers and
   reset the pending epoch's canonical prior-button baseline to all released.
   From frozen world `N`, each remote client samples exactly one newly released-
   baseline command for target `N + D + 1`, freezes it, and includes it in
   `ResumeAck` with the resume semantic ID, old/new epochs, target, and exact
   resume-record hash. Retransmission never resamples. A listen authority
   creates the same immutable local `EpochPrime` in process under section 5.4.
   No gameplay release/press edge is processed while paused.
4. A remote resume ACK or local prime establishes only a pending successor.
   After every required remote semantic ACK and local/remote prime is
   validated, the authority generates and caches each
   bot's decision for `N + D + 1` exactly once, promotes the successor epoch,
   and only then arms a fresh monotonic deadline. It runs the normal `D`-frame
   neutral bootstrap over `[N + 1, N + D + 1)`. The first canonical frame in
   the successor epoch commits the transition at each client. No buffered pre-
   pause fire/use/movement can execute after resume; only intent newly sampled
   in the new input epoch may do so. A failed required peer follows section
   16.1's frozen-tic terminal policy; it cannot strand the resume barrier.
5. Authority emits exactly one canonical `N + 1`; duplicates from an old
   match/input/control epoch are harmlessly rejected.

Never reuse a player `bt_pause` bit or `BlockPlaysimPacket`. Test lost,
duplicated, reordered, and stale pause/resume records, long pauses, held and
released buttons, stale future submissions, and `D = 0/1/max` resume.

---

## 8. Protocol version 2

The new protocol is intentionally incompatible with the current raw packet
layout. “Version 2” here means the first dedicated-capable EC7Wolf protocol;
choose the final numeric constant once existing protocol versioning is audited.

### 8.1 Encoding rules

- Use an explicit byte reader/writer; never cast packet storage to a C++
  struct.
- Use fixed-width integer types and a single documented byte order.
- Validate magic, version, header length, payload length, type, and maximum
  before reading the payload.
- Validate every count before loops or allocation.
- Use checked addition/multiplication for variable-length size calculations.
- Reject trailing bytes unless the message version explicitly permits TLV
  extensions.
- Treat enums as untrusted integers until range-checked.
- Reject non-canonical encodings and duplicate fields.
- Never mutate the receive buffer in place to byte-swap it.
- Fuzz the decoder as a pure function with no socket or world side effects.

An illustrative common header:

```text
magic[4]          "E7N2"
protocolVersion   u16
messageType       u8
flags             u8
headerBytes       u16
payloadBytes      u16
sessionId         u64
connectionId      u64
matchId           u64
inputEpoch        u32
packetSequence    u32
ackSequence       u32
ackBits           u32
authenticator[16]
```

The exact fields may change after MTU and reliability design, but a session,
connection, match, sequence, declared length, and authenticated connection
context are required. `matchId` is zero for session/lobby traffic and is the
current manifest's ID for every match-scoped input, canonical-frame, digest,
and control message. `inputEpoch` is zero outside match command flow and
changes at each begin/resume barrier. Starting a new map creates a new match
ID even if slot numbers and command sequences are reset to the same values.

`connectionId` is a public lookup key, **not** a credential. After admission,
version 1 uses at least 128 unpredictable bits of direction-specific
connection authentication material: a distinct client-to-server and
server-to-client bearer authenticator, or a keyed tag with equivalent forgery
resistance. Validate source endpoint, direction, authenticator, match/session,
and replay window before changing peer reliability state. Hello/challenge and
bounded public status messages use their explicitly unauthenticated formats.
If plaintext bearer authenticators are selected, document the exact boundary:
they prevent off-path spoofing but do not protect against an on-path sniffer.
Transport confidentiality and on-path attack resistance require a separately
designed secure channel; do not claim that endpoint binding supplies them.

The authenticated packet replay window is per direction and remains monotonic
for the entire admitted connection. Session-scoped reliable semantic IDs also
remain monotonic until disconnect/rekey. **Do not reset either at match begin.**
Only match-local command/frame ordering windows reset, and they are keyed by
`(sessionId, matchId, inputEpoch)`. This prevents an authenticated old lobby,
ready, leave, pause, or control record from becoming fresh after rotation.

Epoch-establishing controls use a two-epoch rule so loss/reordering cannot
make a half-created command stream look active:

- `BeginMatch` and `BeginAck` common headers carry parent input epoch `0`;
  their authenticated bodies name the proposed nonzero successor epoch.
- `Resume` and `ResumeAck` headers carry the currently active old epoch; their
  bodies name both old and proposed successor epochs.
- An ACK echoes the control's semantic ID, both epoch values, target sequence,
  and exact canonical record hash. It also carries the immutable primed human
  command described in sections 7.4, 7.6, and 9.4.
- A listen-local `EpochPrime` contains and validates those same fields without
  wire-header or retransmission fields and occupies the local human's barrier
  position.
- A valid ACK or local prime records a pending successor; it does not activate it. The
  authority activates the successor and arms its monotonic scheduler only
  after the complete ACK/prime barrier. A client activates it only when the
  first authenticated canonical frame names that exact pending successor.
- Traffic naming an unannounced successor, a retired proposal, or the old
  epoch after activation is rejected. Deadlines do not run in the pending
  barrier.

This parent-header rule is part of the wire contract, not an implementation
hint. It lets a receiver authenticate and route an epoch-changing record using
state that both sides already agree exists.

### 8.2 Handshake messages

Recommended flow:

```text
ClientHello
  protocol range, build/product version, capabilities, 128-bit client nonce,
  requested name/class, data-profile summary

ServerChallenge
  echoed client nonce, server nonce, stateless address cookie,
  protocol selection and canonical Hello/Challenge transcript hash,
  retry/backoff hint

ClientJoin
  echoed cookie/nonces and transcript hash, complete compatibility hashes,
  optional password proof, requested settings

ServerWelcome or JoinReject
  echoed nonces and complete join-transcript hash,
  session/connection/peer IDs, directional connection authenticators,
  assigned human slot,
  server identity, lobby/rules/roster snapshot, reason code on failure

LobbyAck / RosterUpdate / ReadyState
```

The stateless cookie should bind source address, client nonce, server secret,
and a short time bucket. This prevents a spoofed one-byte datagram from
allocating full peer state or causing amplification. It is not player identity
authentication.

Accept `ServerChallenge` and `ServerWelcome` only for the outstanding endpoint,
client nonce, server nonce/cookie, selected protocol, and canonical transcript
the client actually initiated. An identical retransmitted `ClientJoin` within
the admission window returns the same logical connection/slot and Welcome
credentials; it must not allocate a second peer. A conflicting reuse of the
nonce/cookie is rejected. Keep bounded pending-transcript state and test blind
spoofed Challenge/Welcome, a lost Welcome, and duplicate/reordered Join.

Compatibility data must cover at least:

- protocol version and capability set;
- EC7Wolf build/protocol compatibility version;
- game family/profile (`Corridor7` CD data);
- authoritative gameplay-data hash in deterministic load order;
- actor/map definitions and server-authorized add-on list;
- platform-independent determinism format version.

Return structured reject reasons such as `ProtocolMismatch`, `ServerFull`,
`MatchInProgress`, `DataMismatch`, `BadPasswordProof`, `NameRejected`, or
`RateLimited`. Clients must show the reason rather than timing out.

### 8.3 Peer privacy and address binding

The welcome/manifest does not contain other client addresses. The server binds
each connection's unpredictable directional authenticator to the admitted
source endpoint; the public connection ID only finds that record. Endpoint
migration is out of scope unless it performs an explicit rebind challenge.
Unknown sources cannot send gameplay/control messages by guessing a peer or
connection ID. Authenticator comparison is constant-time, and a wrong-token
packet must not advance ACK/replay state or reveal whether another field was
otherwise valid.

### 8.4 Gameplay messages

At minimum:

```text
InputSubmission
  manifest/roster hash, firstSequence, count, ownedPlayerSlot,
  one or more proposed commands, submission acknowledgements

CanonicalInputFrames
  manifest/roster hash, firstSequence, frameCount,
  command for every active slot in stable slot order,
  complete small deterministic event bodies, server digest checkpoints

FrameAck
  latest contiguous canonical sequence + selective ack bits

DigestReport
  manifest/roster hash, completed sequence, digest version, playsim digest,
  optional subsystem digests for diagnosis
```

The common header's `matchId` plus the manifest/roster hash makes an old map's
packet invalid even if a new match reuses sequence zero and the same slots.
Create fresh command/frame ordering windows at begin/resume, keyed by the full
match/input epoch. Do not reset the connection packet replay window or session
semantic-event IDs; never accept a stale packet merely because its numeric
match-local sequence is currently in range.

Commands should contain stable gameplay fields only: bounded yaw/forward/
strafe axes and an explicit gameplay-button bit mask. Local automap, status,
menu, screenshot, pause, escape, console, and debug controls are never encoded.
Do not send raw `NUMBUTTONS` arrays whose layout changes when a local enum is
edited.

Transmit current gameplay-button bits, not a client-authored `buttonheld`
array. When installing a canonical command, every node derives held/edge state
from the prior canonical button bits in the same way. Exclude `bt_run` from the
canonical mask: current input code has already scaled keyboard/joystick axes
before networking, and the remaining consumer is first-person presentation.
Transmit the resulting bounded axes and derive view-model gait from canonical
movement magnitude. Pitch/mouselook must be either a bounded canonical field
or explicitly unavailable in network deathmatch—never a local actor write.

The exact legal axis range must come from an audit of keyboard, mouse,
controller, and touch sampling. Normalize all human input into the documented
wire envelope before server validation. Do not pick a narrow security clamp
that silently changes legitimate mouse turning, and do not leave yaw
effectively unbounded merely because current movement code clamps other axes.

The server validates:

- authenticated source and connection;
- claimed peer and slot ownership;
- sequence window and wrap-safe ordering;
- count and payload size;
- one submission per slot/sequence: the first valid command is locked;
  byte-identical retransmissions are harmless, while a differing duplicate is
  rejected and counted as a protocol violation rather than winning a
  last-packet race;
- axis bounds and impossible values;
- allowed gameplay button bits;
- rate and history limits.

### 8.5 Reliable control messages

Lobby state, manifest, ready, start, pause/resume, kick/disconnect, abort,
match end, next map, and shutdown require reliable delivery and idempotent
handlers. Their semantic ID is separate from a UDP packet sequence, so a
retransmission cannot apply the action twice.

Every deterministic event names an explicit boundary phase:

- `ApplyBeforeTic(E)`: apply the complete event in stable type/semantic-ID
  order before commands/thinkers for `E`; or
- `StopAfterTic(N)`: simulate all of `N`, including normal outcome evaluation
  and finish-spawning, then stop before `N + 1` for pause, scheduled abort,
  disconnect policy, or graceful shutdown.

`ConfirmTerminal(N)` is not an event retroactively applied at `N`; it confirms
either the natural candidate already discovered after that tic or the terminal
result of a stop-after event that was committed before that tic. V1 also permits
a session-control failure that cannot safely advance—paused disconnect or
controlled exhausted-lead `ServerOverload`—to confirm the unchanged, already
completed `N` with an explicit terminal kind. It does not claim a gameplay
event was applied in the past. An unrecoverable authority crash that cannot
exchange the barrier is still an emergency session failure, not a fake result.

Choose a tentative `StopAfterTic(N)` no earlier than the greatest authority bot
decision already produced plus the acknowledgement margin. Once that stop is
accepted as the authority policy, do not generate controller decisions beyond
`N`; discarding a bot command after advancing private brain/PRNG state would
corrupt later reproducibility.

Each bot's production is an exactly-once state transition keyed by
`(matchId, inputEpoch, targetSequence, botSlot, controllerGeneration)`.
`controllerGeneration` is manifest-assigned (zero for the initial v1
controller) and prevents a future takeover/replacement from aliasing cached
work for the former controller. Before invoking a brain, the authority
must prove that the target does not exceed a committed production/stop horizon
and that advancing the current executable tic will not exhaust the human lead
that clients could have derived. It then stores an immutable decision record
and returns that record on scheduler retry or deadline rebase; it never invokes
the brain twice for the same key. Retain the cache and highest-produced horizon
through pause, retry, controlled overload, and terminal diagnostics. Destroy
an old epoch's immutable command records only after its rejection/history
window is safely retired. Preserve continuing brain memory/PRNG across resume;
destroy that private state only with the entire match. Never roll a brain back
piecemeal or reuse its advanced state in another match.

Likewise, do not commit an `ApplyBeforeTic(E)` that invalidates controller
commands already produced for `E` or later. Either the command producer has a
specified deterministic forecast of that event, or the event creates a fresh
input epoch with an explicit neutral rebootstrap. Version 1 should keep this
event set deliberately small.

For a small pre-scheduled deterministic event, the authority reliably
preannounces the complete typed event and waits for semantic ACK before its
apply horizon. The complete event body is also embedded in the canonical
frame at that horizon and retained with frame history; embedding is the commit,
while preannouncement is tentative. A frame must never contain only a
reference to a body the receiver may have missed. If a required peer has not
ACKed before the commit deadline, the authority moves/cancels the tentative
event while there is still time, or executes the explicit peer-drop/match-
abort policy—it never commits an event only some surviving peers are prepared
to apply.

Define same-sequence precedence once and test it. Recommended v1 order:

1. validate and apply compatible `ApplyBeforeTic(N)` events in canonical
   order;
2. install commands and simulate all of `N`;
3. if a natural match outcome exists, enter `TerminalPending`; it wins over an
   ordinary planned abort or pause at the same `N`;
4. otherwise a committed disconnect/admin abort wins over pause;
5. otherwise a committed pause enters `Paused`;
6. graceful shutdown follows terminal confirmation/ACK policy. An unrecoverable
   authority failure is a separate emergency stop at the last committed tic,
   not a forged canonical event.

Reject mutually incompatible before-tic events and more than one unresolved
stop action rather than relying on packet arrival order. Natural match
outcomes use section 7.5; pause/resume uses section 7.6.

In particular, a disconnect detected while **any** `StopAfterTic(N)` is
unresolved does not allocate a second stop. Retain the existing typed boundary,
remove the departed peer from its required ACK/survivor set, neutralize its
locked slot through `N`, and record the additional disconnect as terminal
session metadata. A pause remains the sole stop and is followed by frozen-tic
disconnect confirmation; an abort/shutdown keeps its existing terminal kind
and precedence. This is one boundary with updated session metadata, not two
competing canonical stop bodies.

Clients accept authority events only from the authenticated server connection.
Client requests such as “ready” or “leave” are requests, never authority
events.

### 8.6 Loss recovery and MTU

- Keep datagrams below a conservative path MTU; target at most 1200 bytes
  until measured otherwise.
- Do not depend on IP fragmentation.
- Batch as many complete canonical frames as fit; never split one field across
  untracked UDP fragments.
- Include redundant recent human submissions so one lost uplink packet does
  not immediately stall/fill neutral input.
- Keep bounded send histories for canonical frames and reliable control.
- Use cumulative acknowledgement plus a selective acknowledgement bitmap.
- Retransmit by sequence/history, not by looking in a pending ring whose entry
  was already consumed.
- Rate-limit retransmit requests and ignore acknowledgements outside retained
  history.
- Test sequence wrap with a reduced-width test codec and long-run production
  arithmetic.

With 11 slots, explicit per-frame command sizing must be calculated before the
wire format is frozen. If the current command representation is too large,
encode bounded axes compactly and use button bitsets; do not raise the UDP
payload past the MTU to avoid designing it.

### 8.7 Legacy compatibility

Choose one explicit policy:

- recommended: retain legacy P2P/listen multiplayer temporarily, while
  dedicated/listen-v2 uses the new magic and protocol; or
- migrate all network games to the v2 star/session model in one release.

In either case, protocol mismatch fails immediately with an actionable
message. Do not make a new server interpret legacy packed structs, and do not
let a legacy client consume a v2 packet based only on its first type byte.

---

## 9. Canonical command flow and 70 Hz timing

### 9.1 Per-sequence algorithm

Use one unambiguous convention:

```text
S = most recently completed world sequence
E = S + 1                         next sequence eligible to execute
D = negotiated full input delay in frames
F = S + D + 1                     future input target observed after S
```

Future command production and current-frame execution are two different
pipeline lanes:

1. After completing `S`, each interactive client samples local gameplay
   intent for `F` and redundantly submits it for its owned slot.
2. After completing server world `S`, and only after stop/lead feasibility has
   been checked, the authority visits bots in stable slot order, builds every
   absent command for `F` from that boundary, and stores it under the full
   match/epoch/target/slot/controller-generation key. A partial scheduler retry
   reuses completed entries and advances only missing bots; no bot is invoked
   twice. It does not simulate `F`.
3. Independently, at `E`'s finalization deadline, the authority obtains the
   already buffered human and bot proposals for `E`, validates them, and
   produces exactly one command for every active slot. A missing human follows
   the neutral-input policy.
4. The authority embeds any fully acknowledged `ApplyBeforeTic(E)` or
   `StopAfterTic(E)` body, emits `CanonicalInputFrame(E)`, and installs that
   same frame locally.
5. Server and clients call `RunSimulationTic(E)` exactly once; that common
   function applies compatible before-tic events in canonical order, then
   installs the frame's commands.
6. Each computes the completed-`E` playsim digest. Selected sequences are
   reported to the authority.
7. Resolve post-tic precedence: natural outcome, committed abort, then pause.
   If any wins, all nodes stop before `E + 1`; otherwise `E` becomes the new
   `S` and the pipeline repeats.

A local client must not apply its proposed command early. It applies only the
canonical frame returned by the authority, otherwise loss/substitution creates
an immediate divergence. At `D = 0`, `F == E`, so the authority must receive
the newly produced command and return its canonical frame before execution;
that mode is suitable only for loopback/listen diagnostics unless measured
latency proves otherwise. Internet sessions require a positive negotiated
lead.

### 9.2 Input-delay meaning in a hub

The delay window must cover:

```text
client sampling -> client/server uplink -> server finalization
-> server/client downlink -> client simulation deadline
```

It is not merely one peer-to-peer round trip. The server can measure each
client's latency/jitter during lobby and choose a session-wide delay or a
documented per-client submission lead while keeping one canonical execution
sequence. The simplest first release uses one server-selected session delay
and one advertised client playout target `P`, with validation that the client
trail still leaves every peer enough future-command lead.

### 9.3 Missing-input policy

Waiting forever is unacceptable; silently inventing arbitrary movement is
also unacceptable. Define one deterministic authority policy and log every
use. Recommended version 1 behavior:

1. Accept redundant submissions until the frame's finalization deadline.
2. If a human command is missing, synthesize a **neutral command**:
   zero movement/yaw, no current gameplay buttons, and held-edge state derived
   from the previous canonical command so release semantics remain valid.
3. Mark that peer late and continue liveness/retransmit handling.
4. Continue neutral commands while missing; never repeat attack/use or leave a
   pawn running indefinitely.
5. After configured consecutive-missing or wall-clock timeout, schedule
   `StopAfterTic(AbortMatch)` at a future canonical sequence and notify all
   peers reliably.

Charge a missing command to a client only when the authority is operating in
its normal deadline epoch and the client had the advertised canonical history
and lead needed to produce it. If an authority stall/catch-up outruns the
future commands clients could possibly have derived from frames it had emitted,
that is `ServerOverload`, not client lateness: stop catch-up, poll/rebase or
perform the controlled overload-abort policy, and do not increment peer late/
timeout counters for those sequences.

An alternative strict mode may pause finalization within a bounded grace
period for LAN/testing, but the authority still makes the one decision. No
client applies its own timeout.

The exact `buttonheld` derivation needs a unit test because EC7Wolf uses held
state for edge-triggered use, weapon slots, mines, visor, and non-autofire
weapons.

### 9.4 Input-pipeline bootstrap

Input delay means the first `D` execution sequences cannot contain commands
sampled `D` tics earlier. Define them explicitly; never wait for commands that
can never exist.

Recommended bootstrap:

1. `BeginMatch` identifies first executable sequence `start`, defines the
   completed baseline as `start - 1`, and carries delay `D`.
2. Authority creates canonical neutral bootstrap frames for the half-open
   interval `[start, start + D)`. Its length is exactly `D`; at `D = 0` it is
   empty. Prior-button state starts from the manifest's explicit all-released
   baseline.
3. Before waiting for canonical playout occupancy, every interactive human
   owner samples its controller exactly once against completed baseline
   `start - 1` for target `start + D`. A remote client freezes the encoded
   command in reliable semantic `BeginAck`; a listen authority freezes it in
   section 5.4's local `EpochPrime`. Lost or duplicated ACKs resend identical
   bytes, so retry/reordering cannot lose the prime or change which physical
   sample wins.
4. All remote clients acknowledge the begin record/bootstrap hash, and any
   listen-local `EpochPrime` is validated, before authority execution. After
   the barrier,
   the authority generates each bot's first decision for `start + D` exactly
   once, caches it, promotes the pending input epoch, and arms the deadline.
   It then emits each bootstrap frame at its normal server tic; it does not
   pre-authorize a rendered client to run ahead.
5. The human prime and first bot decision target `F = start + D`. At `D = 0`,
   that is the first executable frame itself: the authority waits for the
   prime barrier, finalizes `start`, and emits it without deadlock or an
   unintended neutral command.
6. The authority emits and nodes execute bootstrap/current canonical frames in
   sequence order. A rendered client waits for its target contiguous playout
   depth `P` while the authority advances. The first sampled action can execute
   at `start + D`, after exactly `D` earlier neutral frames.

Resume uses the same algorithm with frozen completed baseline `N`, first
executable sequence `N + 1`, and prime target `N + D + 1`. The immutable human
prime is bundled in remote `ResumeAck` or installed as a listen-local
`EpochPrime`; each authority bot prime is generated once after the complete
prime barrier and before the resumed deadline is armed. Thus
`D = P = 0` remains a latency-sensitive diagnostic mode, but it is executable.

Reset match/input-epoch command histories and prior-button state at every new
match, roster change, resume, and reconnect snapshot boundary. Never reset the
connection's authenticated packet replay window or session semantic IDs. A
delayed command from the preceding match/input epoch must be rejected by the
full `(sessionId, matchId, inputEpoch)`, not treated as warm-up input.

### 9.5 Fixed-rate server scheduler

Use a monotonic 64-bit clock, not render-frame tics or wall-clock calendar
time. The dedicated loop should:

```text
while running:
    poll network/admin/signals until next deadline or activity
    process bounded incoming work
    for each due tic, up to catch-up cap:
        poll/process a bounded amount of transport again
        let S be the just-completed world sequence
        let E = S+1 and F = S+D+1
        if E exceeds a committed stop horizon:
            leave the simulation loop at the already completed boundary
        if advancing E would exhaust derivable human lead:
            stop catch-up; rebase/slow or controlled ServerOverload abort
        if F is within the production horizon:
            for each bot slot in stable order whose generation-keyed decision is absent:
                build/store that authority bot decision exactly once
        finalize and emit current frame E = S+1
        install and simulate E exactly once
        emit digest/outcome and stop immediately on terminal E
    run non-simulation maintenance under budgets
```

Requirements:

- target exactly `TICRATE == 70` simulation tics per second;
- no busy-spin while idle;
- continue receiving packets while waiting for the next deadline;
- poll bounded transport between caught-up tics so newly emitted frames and
  resulting client submissions can make progress;
- do not skip a world tic to catch up;
- cap tics processed in one outer iteration to prevent a spiral that starves
  networking/admin;
- interleave decision, finalization, and simulation for each caught-up tic;
  never finalize a batch against stale world state and then run the batch;
- perform stop-horizon and derivable-human-lead checks before any controller
  brain can mutate memory or PRNG state;
- key immutable bot decisions by `(matchId,inputEpoch,targetSequence,botSlot,
  controllerGeneration)`, record per-controller and aggregate highest-produced
  horizons, and reuse each cache hit across scheduler retry or deadline rebase
  rather than running that brain again;
- never build later bot decisions or simulate beyond a terminal tic merely
  because several deadlines were due;
- log overload duration, maximum catch-up, and command backlog;
- define when sustained overload aborts a match rather than running silently
  slow;
- when overload catch-up reaches the end of derivable human command lead,
  stop rather than synthesize a burst of client-blamed neutral frames. Rebase
  the next deadline and run temporarily slow within policy; if overload is
  terminal while transport remains serviceable, enter `TerminalPending` at the
  last completed tic and run the generic `ConfirmTerminal(ServerOverload)`/
  results-commit barriers without simulating another frame. Retain any already
  produced bot decisions through diagnostics, then destroy them with the
  match;
- create and arm a fresh deadline epoch only after the complete Begin/Resume
  ACK/prime barrier (and any manifest-invalidating drop resolution), never on
  first receipt or send of the control record. Deadlines do not accrue in boot,
  lobby, loading, ready, pause,
  terminal-pending, results, or shutdown, so a long barrier cannot create a
  catch-up burst;
- keep network callbacks from mutating world state; queue validated messages
  for the tic boundary;
- initially prefer a single deterministic simulation thread. If I/O later
  moves to another thread, it communicates through bounded queues and never
  exposes mutable actor state.

Current render-derived `CalcTics`/`CalcTicsInterpolated` are not server clocks.

### 9.6 Rendered-client playout and clock drift

Normal remote clients do not execute a canonical frame immediately merely
because a UDP packet arrived, and no client infers a sequence from its local
clock. Use a contiguous sequence-driven playout queue plus a local monotonic
70 Hz pacing deadline. The manifest/begin record chooses target queued-frame
depth `P` and
low/high watermarks. Remote play normally uses `P > 0`; loopback diagnostics
may use `P = 0` immediate playout. Input delay `D` must include this client
trail plus measured uplink/jitter margin—configuration must reject a `P/D`
combination that leaves no command-production lead. The baseline constraint is
`0 <= P <= D`; practical remote settings require `D - P` to cover the measured
submission path and margin, while `D = P = 0` is diagnostic-only.

For each client input epoch:

1. From the advertised completed baseline, sample exactly one human prime for
   the advertised first non-bootstrap target and freeze its bytes. A network
   client bundles it into the semantic Begin/Resume ACK; a listen authority
   submits the equivalent in-process `EpochPrime`. Install the proposed input
   epoch as pending, not active.
2. A network client retransmits the same ACK/prime until acknowledged; a listen
   authority retains its immutable local record through the barrier. Buffer
   only contiguous authenticated/canonical frames from the expected pending
   epoch. The first such frame commits the epoch locally; a frame for any other
   epoch is rejected.
3. For `P > 0`, begin local pacing only after the target startup occupancy is
   available. Initialize a fresh local deadline; do not inherit time spent in
   loading, pause, results, or another match.
4. On each local deadline, execute only the next contiguous sequence. After
   completing `S`, sample/submit owned intent for `F = S + D + 1`.
5. If the next sequence is missing or occupancy falls below the low watermark,
   idle/pump transport and rebase within the bounded underrun policy. Never
   skip a sequence or apply a private proposal.
6. If occupancy exceeds the high watermark because frames arrived batched or
   the local clock is slow, execute bounded extra contiguous tics, polling
   transport/UI between them. Never alter tic duration, skip simulation, or
   let catch-up starve rendering/networking indefinitely.
7. Inspect terminal outcome and committed `StopAfterTic` events after every
   tic, including inside a catch-up batch; stop exactly at the boundary and
   discard/re-epoch any later buffered frame as policy requires.
8. Treat a persistent gap/history overrun or authority timeout as connection
   failure, not permission to jump to the newest packet.

This makes small server/client clock drift change queue occupancy rather than
world state. Renderer frame rate is independent: a rendered outer iteration
may simulate zero, one, or bounded multiple 70 Hz tics, then interpolate/present
the latest completed pair. Digest comparisons always name the completed
sequence; they do not compare “current wall-clock frame.”

Test positive/negative local clock skew, delayed and batched frames, a missing
middle sequence, renderer rates above/below 70 Hz, low/high-water correction,
history overrun, and pause/terminal boundaries inside a multi-tic batch.

### 9.7 Command validation is not game-state anti-cheat

The authority rejects malformed axes, unauthorized bits, wrong ownership,
future-window abuse, duplicates, and floods. Normal player simulation then
enforces movement speed, collision, weapon timing, ammunition, health, damage,
and scores.

Because clients receive and simulate the world, this architecture cannot stop
a modified client from using an aimbot or rendering hidden information. State
replication with filtered visibility would be needed for a stronger secrecy
boundary. State that limitation plainly rather than promising “server
authoritative” as a universal anti-cheat guarantee.

---

## 10. Headless authoritative simulation

### 10.1 Common one-tic API

Create a narrow API whose inputs and outputs are testable:

```cpp
struct SimulationTicResult
{
    WorldDigest digest;
    TicBoundaryResult boundary; // continue, natural candidate, abort, or pause
    TArray<GameplayEvent> events;
};

SimulationTicResult RunSimulationTic(
    Sequence sequence,
    const CanonicalInputFrame& commands,
    const SimulationServices& services);
```

Responsibilities:

- validate that the frame roster/hash matches the active match;
- validate and apply `ApplyBeforeTic(sequence)` bodies in canonical order;
- install each active slot's command once;
- advance the deterministic time counter once;
- perform pending spawn/respawn work;
- tick thinkers in the existing required category order;
- finish actor spawning;
- evaluate deterministic match termination;
- resolve natural-outcome/abort/pause `StopAfterTic(sequence)` precedence and
  return the exact post-tic boundary decision;
- build the stable world digest;
- emit semantic gameplay/presentation events without rendering or playing
  them.

If a non-continue boundary is returned, natural or scheduled terminal results
enter `TerminalPending`, while pause enters `Paused`; the caller must not invoke
the function for the next sequence until the applicable barrier resolves.
`Aborting` is reserved for pre-running lifecycle cancellation that has no
executable world tic.

It must not:

- sample physical input;
- poll sockets directly;
- read a local camera or `ConsolePlayer`;
- draw, update a HUD, fade, animate a screen, or present a frame;
- open or mix audio;
- wait for user acknowledgement;
- process local pause/menu/debug keys;
- choose a map or mutate the roster;
- read wall time.

### 10.2 Thinker and command ordering

All commands, including bots, are finalized from the same completed-world
boundary. Preserve the complete existing thinker order:

```text
VICTORY -> WORLD -> PLAYER -> NORMAL
```

After the VICTORY category, preserve the existing `victoryflag` check before
every later category; this also handles a flag that was already set on entry.
Do not tick the remaining categories once it is true. WORLD is
gameplay-critical for Corridor 7 doors, elevators, pushwalls, dispensers, and
other mutable map machinery. Do not let slot 0 tick, then use its changed
position to decide slot 1's command in the same tic.

The server uses ordinary `player_t`, `APlayerPawn`, inventory, movement,
weapon, collision, damage, death, frag, and respawn code. It does not use a
special server pawn and does not directly award kills.

### 10.3 Presentation event boundary

Simulation-reachable calls should become semantic events where appropriate:

```text
PlayerDamaged(slot, amount, source)
PickupSucceeded(slot, item)
PickupFailed(slot, reason)
DoorActivated(actor/line id)
SoundEmitted(source, sound class, position, gameplay-audible flag)
PlayerDied(slot, killer slot/reason)
FragChanged(slot/team, total)
MatchEnded(reason, standings)
```

Interactive clients consume events into HUD messages, face changes, audio, and
effects. The server's presentation sink is a deliberate no-op or structured
logger. Future bot hearing consumes only deterministic gameplay-audible sound
events, not the audio mixer.

Use null objects during migration for interfaces that are currently assumed
non-null (`StatusBar`, audio sink), but avoid constructing fake render state
just to satisfy gameplay calls.

### 10.4 Render-only simulation neighbors

Classify these rather than blindly removing them:

- interpolation snapshots: render-only, skip on server;
- dynamic-wall render snapshots: render-only if collision state lives
  elsewhere; prove this with door/pushwall tests;
- texture animation: presentation-paced and currently consumes the named
  `AnimatePics` RNG stream; do not move that stream into gameplay merely to
  make a checksum agree;
- garbage collection: preserve the `GC::CheckGC()` calls already performed
  after each live thinker inside `ThinkerList::Tick`. The additional once-per-
  rendered-outer-frame call may be removed/rescheduled only after spawn/
  destroy/reclamation and pointer-reuse stress proves parity;
- capture screenshots: client-only;
- capture/world checksum: common diagnostic, expanded for server use;
- map visibility/automap flags: local presentation, never bot/server
  perception;
- deterministic music selection: `Corridor7Music` is already an independent
  presentation stream; exclude it from authoritative state, while clients may
  preserve its draw ordering for repeatable soundtrack selection;
- sound definition/sequence parsing: retain required metadata, but treat
  mixer/local-zone sequence playback as presentation and suppress output
  device and camera localization.

### 10.5 World digest

The existing capture checksum is a starting point, not sufficient authority
validation. A versioned digest should cover stable, decision-relevant state:

- match sequence/time, map, rules, active roster, player states;
- each player's transform, health, class, lives/state, frags/team, weapon
  states, inventory/ammo, status effects, respawn timers;
- all gameplay actors with stable IDs and relevant transform/state/health/
  ownership/flags;
- doors, pushwalls, forcefields, transporters, triggers, hazards, and mutable
  map state;
- a versioned allow-list of gameplay-authoritative RNG streams and/or their
  full stable state;
- match controller and pending canonical events;
- canonical bot commands and every bot pawn's ordinary replicated playsim
  state when bots exist.

Do not hash pointers, unordered-container iteration, padding bytes, render
interpolation, audio channels, wall time, or local UI state. Produce optional
sub-digests so “world mismatch” can be narrowed to players, actors, map, RNG,
or canonical bot-controlled pawn state.

Do not hash every registered RNG indiscriminately. `AnimatePics` advances at
client render cadence, while `M_Random` is explicitly non-gameplay and is used
by sound-sequence random delays. Texture/UI/audio sequencing and other
presentation streams are excluded from the authoritative digest or reported
only as separate local diagnostics. Maintain a reviewed, versioned gameplay-
RNG registry; changing membership changes the deterministic compatibility
format. Tests vary render rate, texture-animation cadence, audio availability,
and headless mode while the gameplay RNG digest remains equal, then perturb a
listed gameplay stream and require detection.

Do **not** put authority-private bot brain memory, perceived-world beliefs,
path search state, utility scores, or private bot PRNG into the cross-node
playsim digest: clients do not run those brains and cannot reproduce that
state. The server should compute a separate `BotBrainDigest` for diagnostics,
recordings, repeat-server-run tests, and bug reports. It never compares that
private digest with an ordinary client. A bot decision becomes replicated
state only through its canonical command and the normal world effects of that
command.

The current actor model does not expose a purpose-built network-stable object
ID. Add a deterministic actor serial assigned from simulation spawn order, or
define and prove an equally stable canonical actor ordering. Never use a raw
pointer as a digest key, tie-breaker, lifecycle reference, or log identity.
Actor-ID creation, destruction, map transition, and serialization must be
covered before the digest is treated as authoritative.

The digest detects divergence; it does not repair it. Version 1 logs and ends
or removes a mismatched client according to policy. State resynchronization is
a later feature.

### 10.6 Determinism ABI and authoritative angle math

Current authoritative state is not automatically cross-platform merely
because most movement uses fixed-point values. Startup builds trigonometric
tables with runtime `tan()`/`sin()`, and gameplay paths convert `atan2()`
results to integer angles for visibility, enemy facing/missiles, player death
rotation, and Corridor 7 chamber behavior. Different libm/compiler targets can
round a boundary differently and permanently split lockstep.

Create and version a determinism ABI:

- inventory every floating/libm call reachable from map initialization and
  playsim;
- replace authoritative angle conversion with a proved fixed/integer lookup
  helper, or temporarily restrict compatible build/platform pairs until
  golden cross-platform vectors prove identical behavior;
- generate trig tables from checked canonical data/algorithm, or hash the
  generated tables into ready-barrier compatibility diagnostics;
- define integer widths, overflow/wrap assumptions, fixed-point rounding,
  endianness encoding, actor ordering, and authoritative RNG registry;
- run boundary vectors around axes, quadrants, FOV limits, death rotation, and
  projectile directions on every supported server/client platform and build
  mode.

Do not advertise Linux-server/Windows-client compatibility until this gate is
green. A digest that reports the split after play begins is useful evidence,
not a substitute for a deterministic ABI.

---

## 11. Headless initialization and services

### 11.1 Select the runtime role before presentation initialization

The dedicated role must be known before GTK, SDL video, renderer capability
checks, window creation, audio, input, IWAD selection dialogs, or client config
callbacks. Parse a minimal early option set in the platform entry point or a
shared bootstrap layer:

```text
--dedicated / server executable identity
--config
--data-dir / --iwad-profile
--port
--log / --state-dir
--help / --version
```

The final `ec7wolf-server` binary implies dedicated role without requiring a
flag. A development-time `ec7wolf --dedicated` can route to the same code, but
must not become a separately maintained implementation.

### 11.2 Initialization phases

Refactor startup into explicit phases:

| Phase | Client | Dedicated server |
| --- | --- | --- |
| process paths/logging/config | yes | yes, server-specific paths |
| SDL base/timer if still required | yes | yes, no video/audio flags |
| resource archives and game profile | yes | yes |
| map/actor/texture/sprite metadata | yes | yes, only required metadata/pixels |
| `LOCKDEFS`/key-group parsing (`P_InitKeyMessages`) | yes | **yes, gameplay** |
| deterministic tables/RNG | yes | yes |
| renderer capability and window | yes | **never** |
| fonts/HUD/menu/cinematics | yes | no |
| keyboard/mouse/joystick/controller | yes | no |
| audio device/mixer/music playback | yes | no |
| sound definitions/gameplay events | yes | yes |
| client renderer backend | yes | no |
| server transport/lobby/admin | listen authority optionally | yes |
| fixed server loop | no | yes |

Potential common routines:

```text
BootstrapProcess
InitializeCommonResources
InitializeGameplayDefinitions
InitializeDeterministicRuntime
InitializeClientPresentation
InitializeServerRuntime
ShutdownClientPresentation
ShutdownServerRuntime
ShutdownCommonRuntime
```

Each phase owns its termination handlers. Avoid a single global termination
stack whose server path writes a client config, destroys never-created video,
or waits for an acknowledgement.

Retain `P_InitKeyMessages()` in common initialization despite its name: it
parses `LOCKDEFS`, constructs key groups, and assigns the numbers used by
gameplay `P_CheckKeys()`. Only the failed-use HUD text/sound belongs in the
presentation event sink. A headless locked-door test must cover both an
accepted key group and rejection without a required key.

### 11.3 Video and GUI prohibition

Server startup must not call:

- `gtk_init_check` or an IWAD picker;
- `CheckRendererAvailable`;
- `VL_SetVGAPlaneMode` or `I_InitGraphics`;
- `R_InitRendererBackend` or create a framebuffer/window/context;
- client resolution/projection setup;
- `VH_UpdateScreen`, fades, sign-on/startup console drawing;
- menu/status/scoreboard/cinematic presentation.

Build the POSIX server with `NO_GTK`. Build Windows as a console application,
not the `WIN32` GUI target and not a wrapper around it. Build macOS as a plain
command-line executable without a `.app` bundle.

Classify the earlier `R_InitRenderer()` separately. It initializes software
2-D function tables rather than a backend/window, so Stage A may retain it
without violating runtime headlessness. Stage B must split/replace the common
parts or prove they are unnecessary before dropping `r_2d` source/linkage; it
must not confuse this call with `R_InitRendererBackend()`.

No-video tests set `DISPLAY`, `WAYLAND_DISPLAY`, and related variables absent
and deliberately set invalid SDL video/audio drivers. Reaching a listening
state must not depend on dummy backends.

### 11.4 Input prohibition and cancellation replacement

Do not call `IN_Startup`, joystick/controller initialization, mouse grabbing,
or gameplay event sampling. Current network waits call `IN_ProcessEvents` and
`CheckKeys` to remain cancellable. Replace those dependencies with a
platform-neutral service poll that checks:

- atomic shutdown/signal state;
- local terminal/admin command queue;
- socket readiness and timers;
- service-control notification.

Server terminal input is administration, never a gameplay controller. An
admin command may enqueue an authority event; it may not write
`control[ConsolePlayer]` or mutate actors from the input-reading callback.

### 11.5 Null audio without changing deterministic behavior

Split current sound startup into:

- sound definition and sequence metadata initialization;
- semantic gameplay sound-event creation;
- client mixer/device/music playback.

The server retains the first two and uses `NullAudioOutput`. It must not call
SDL_mixer, open an audio device, initialize OPL playback, localize channels
against renderer camera globals, or wait for a sound to finish.

Audit every early return for RNG and game-state effects. The named
`Corridor7Music` stream is presentation-only and independent of gameplay
streams, so the headless server need not consume it. A CD-present/absent test
must prove identical gameplay RNG/digests; a separate optional client test may
require repeatable soundtrack-choice order.

A null mixer alone is insufficient. `SndSeqPlayer::Tick()` waits on global
`SoundPlaying`, consumes presentation `M_Random` for random delays, and its
pointer/substate is embedded in WORLD thinkers. Door code creates those
sequences conditionally from the local console pawn's sound zone. Therefore:

- exclude local sound-sequence playback substate from the authoritative
  door/pushwall digest;
- emit deterministic bot-hearing/gameplay sound events unconditionally at the
  authoritative action site, before local-zone or mixer filtering;
- never derive bot hearing from `SndSeqPlayer` or an audio channel;
- keep presentation sequence timing client-local, or replace it with a
  separately specified semantic sequence scheduler if gameplay later needs
  it.

Test one door with rendered clients in different sound zones and with audio
enabled/disabled against a headless server. Gameplay digests and bot-hearing
events must agree even when presentation sequence state does not.

### 11.6 Status, notifications, death effects, and projection

During migration:

- instantiate a `NullStatusBar` on the server so unexpected legacy calls are
  safe and traceable;
- add debug counters or assertions for server-side presentation calls rather
  than silently accepting them forever;
- move HUD text/face/chamber/elevator notifications to a presentation event
  sink;
- make death fades and view effects presentation-only;
- make projection local-camera-specific and remove gameplay-side global
  `CalcProjection` calls;
- constrain server/client player-class radius behavior only if necessary for a
  temporary milestone, and record that constraint explicitly.

A null pointer is not an acceptable server status-bar implementation because
simulation-reachable code currently calls the interface.

### 11.7 Common data without interactive selection

The server configuration must identify Corridor 7 data unambiguously, for
example by an explicit data directory/profile. It may search deterministic
documented paths, but if zero or multiple valid installations remain it fails
with a list and an instruction. It never opens a picker.

Load-order and hashing rules must be identical on every participant. Optional
client-only content such as high-resolution presentation replacements may be
excluded from the gameplay compatibility hash only after the loader can prove
it does not replace definitions, maps, collision-derived textures, actors, or
other deterministic data.

### 11.8 Non-blocking client overlays and results

Making the server headless does not help if a rendered client stops receiving
canonical frames whenever a legacy synchronous menu or tally owns the thread.
Refactor `US_ControlPanel`, scoreboard/tally acknowledgement waits, and similar
modal loops into client state machines serviced by the normal outer loop:

- while a local menu/overlay is open during `Running`, keep pumping transport,
  installing canonical frames, and simulating; submit neutral local gameplay
  intent unless the overlay explicitly permits normal controls;
- local UI never serializes menu, pause, escape, automap, status, screenshot,
  or debug bits into gameplay commands;
- after a terminal tic, stop playsim but continue transport, reliable terminal/
  results-commit ACKs, liveness, and results rendering; accept next-match
  manifest/loading only after the authority's `ResultsCommitAck`/drop barrier
  completes;
- drive simulation through the contiguous playout queue/watermarks in section
  9.6 rather than tying one game tic to one rendered frame;
- closing an overlay never tries to catch up by replaying expired private
  input or by applying a local proposal; canonical retained history remains
  the only catch-up source;
- if a client falls beyond supported canonical history, fail explicitly rather
  than resume from a divergent world.

Hold both an in-match menu and the results overlay open longer than normal
history/timeout windows in tests. Other peers and the authority must remain
healthy, and closing the overlay must not desynchronize or trigger an
unbounded catch-up burst.

---

## 12. Source and build architecture

### 12.1 Staged target split

Do not attempt a perfect library boundary before the first zero-window parity
test. Use two stages.

**Stage A — behavioral headless target**

- Add `ec7wolf-server` with a server entry point and `EC7WOLF_DEDICATED`
  target definition.
- Define `NO_GTK`; omit client platform entry/resource files where simple.
- Retain SDL2 base and SDL2_net initially.
- Accept all-interface UDP binding in Stage A: SDL2_net's
  `SDLNet_UDP_Open(port)` has no local-address parameter. A real `--bind`
  option waits for a native-socket or other transport backend.
- Retain resource/texture/sprite metadata code required for map and actor
  loading.
- Route runtime through server initialization and server loop.
- Link no SDL2_mixer or OpenGL/libepoxy when the null services are ready.
- Prove exact simulation parity before further source removal.

**Stage B — durable component split**

Illustrative CMake structure:

```cmake
add_library(ec7wolf_core OBJECT
    # object model, resources needed by gameplay, maps, actors,
    # players, thinkers, inventory, rules, deterministic RNG, digest
)

add_library(ec7wolf_net_common OBJECT
    # codec, reliability, session/roster, command frames
)

add_library(ec7wolf_client_runtime OBJECT
    # video/renderers, UI, HUD, input, audio output, client loop
)

add_library(ec7wolf_server_runtime OBJECT
    # lobby, authority transport, server clock, admin, null services
)

add_executable(ec7wolf ...)
target_sources(ec7wolf PRIVATE
    $<TARGET_OBJECTS:ec7wolf_core>
    $<TARGET_OBJECTS:ec7wolf_net_common>
    $<TARGET_OBJECTS:ec7wolf_client_runtime>)
target_link_libraries(ec7wolf PRIVATE ...)

add_executable(ec7wolf-server ...)
target_sources(ec7wolf-server PRIVATE
    $<TARGET_OBJECTS:ec7wolf_core>
    $<TARGET_OBJECTS:ec7wolf_net_common>
    $<TARGET_OBJECTS:ec7wolf_server_runtime>)
target_link_libraries(ec7wolf-server PRIVATE SDL2_net ...)
```

The actual split will expose old global dependencies. Resolve them through
narrow interfaces, not by placing all sources back into both targets and
calling the work complete.

`OBJECT` plus `$<TARGET_OBJECTS:...>` is intentional in the first split and is
compatible with the repository's current CMake 3.6 floor; linking object
libraries as ordinary targets would require CMake 3.12 or raising that floor.
Native actor classes register via
global initializers and some units may be referenced only by definition/string
name; an ordinary static archive can dead-strip those units. A later `STATIC`
layout must use documented whole-archive linkage or explicit registration
anchors. Compare the complete client/server class registry and all-arena
spawned class/counts before accepting any linkage change.

### 12.2 Proposed new modules

Names may follow project conventions, but responsibilities should remain
separate:

| Module | Responsibility |
| --- | --- |
| `g_session.h/.cpp` | runtime role, peer/slot mapping, roster, rules, predicates |
| `net_codec.h/.cpp` | pure bounded byte codec and protocol message definitions |
| `net_reliability.h/.cpp` | sequence windows, ACK bits, history, resend |
| `net_client.h/.cpp` | client handshake, submissions, canonical-frame receive |
| `net_server.h/.cpp` | admission, peers, input collection/finalization, broadcast |
| `g_simulation.h/.cpp` | one canonical presentation-independent tic |
| `g_matchcontroller.h/.cpp` | lobby-to-match manifest, outcome, results, rotation |
| `i_presentation.h/.cpp` | HUD/audio/view notification interfaces and null services |
| `server_main.cpp` | CLI/bootstrap and lifecycle dispatch only |
| `server_loop.h/.cpp` | monotonic pacing, service poll, shutdown |
| `server_config.h/.cpp` | validated server configuration and precedence |
| `server_admin.h/.cpp` | stdin/local admin parsing and scheduled actions |
| `g_digest.h/.cpp` | versioned full simulation/subsystem digest |

Avoid one enormous `server.cpp` that duplicates client startup, network codec,
match rules, and loop logic.

### 12.3 Existing source areas requiring audit/refactor

This is a work inventory, not a mandate to edit every file in one change:

- `wl_net.h/.cpp`: modes, packed packets, peer arrays, startup, reliability,
  new game, tic exchange, arbiter, timeouts, control authority;
- `wl_play.h/.cpp`: `ConsolePlayer`, input sampling, UI/gameplay command split,
  simulation tic, outer client loop;
- `wl_main.cpp`: early role parsing, common/client/server init, NewGame class
  initialization, `R_InitRenderer()` versus backend initialization,
  projection, shutdown;
- `wl_game.cpp`: common level setup, client GameLoop, server match lifecycle,
  intermission/high-score/presentation branches;
- `wl_agent.h/.cpp`, `g_shared/a_playerpawn.cpp`: player-slot loops,
  presentation calls, damage/death/frag outcome, projection/FOV;
- `gamemap.cpp`, `gamemap_planes.cpp`, `id_ca.cpp`: map translation metadata
  versus render visibility;
- `lnspec.cpp`, inventory/key code: sound/HUD/local-camera dependencies in
  simulation paths;
- `g_shared/a_keys.cpp`: retain `P_InitKeyMessages`/`LOCKDEFS` key-group
  construction as gameplay; route only failure presentation to event sinks;
- `id_sd.cpp`, `sndinfo.cpp`, `sndseq.cpp`: definition/event/output split;
- `id_in.cpp` and platform entry points: exclude from server runtime;
- renderer, HUD, automap, menu, scoreboard, intermission, cinematic modules:
  client-only linkage or entry paths;
- capture/checksum code: extract full common digest from screenshot tooling;
- root and `src/CMakeLists.txt`, dependency discovery, PK3 target assumptions,
  install/package rules;
- multiplayer test tools: topology, codecs, hostile datagrams, readiness,
  server logs.

### 12.4 Dependency targets

Final server acceptance should distinguish direct from transitive dependencies:

- required/acceptable initially: C/C++ runtime, zlib/archive/data decoders,
  SDL2 base if used for timers, SDL2_net, gameplay-resource dependencies;
- prohibited direct server linkage: SDL2_mixer, OpenGL, libepoxy, GTK, client
  audio codec stacks used only for playback, xBRZ if purely presentation;
- desired later: replace or configure SDL2 base if the distribution's SDL2
  transitively pulls large window-system libraries and a truly slim artifact
  is important.

If specific-address `--bind` is a release requirement, the transport split
also replaces/wraps SDL2_net UDP open with native sockets or another backend
that accepts a local address. Do not expose a parsed bind option that the
backend silently ignores.

The behavioral requirement is stricter than `ldd`: even if SDL2 contains
video backends, the server must not initialize them. The packaging/dependency
goal can then reduce linkage in a measured second pass.

### 12.5 Generated resources and product version

Generalize PK3 custom commands so both executables can depend on or locate
`ec7wolf.pk3` without hard-coded `$<TARGET_FILE_DIR:engine>` assumptions.
Report the normal EC7Wolf `1.0-betaX` and protocol compatibility version in
server `--version` output. Do not change `VERSION_MAJOR/MINOR/PATCH` away from
the intentional 1.5.0 save-product values.

---

## 13. Server configuration and command-line contract

### 13.1 Configuration precedence and validation

Use one documented order:

```text
compiled safe defaults
  < server config file
  < command-line arguments
  < local admin changes allowed for next match
```

Reject unknown keys/options by default. Validate all numeric ranges before
casting to byte-sized fields. Print the final effective non-secret
configuration at startup. Never log passwords/proofs or reusable connection
tokens.

### 13.2 Proposed CLI

Illustrative, not yet a compatibility promise:

```text
ec7wolf-server
  --config <server.cfg>
  --data-dir <Corridor7-data-directory>
  --bind <address>                 Stage B/native transport; default 0.0.0.0
  --port <1..65535>                default 5029/udp
  --max-clients <0..11>            zero is valid only for bot-capable matches
  --max-players <1..11>
  --min-players <1..11>
  --map <MAP51..MAP57|MAP60>
  --rotation <MAP51,MAP52,...,MAP57,MAP60>
  --mode <deathmatch|team-deathmatch>
  --frag-limit <0..255>
  --input-delay <bounded tics|auto>
  --client-playout <bounded frames|auto>
  --ready-timeout <duration>
  --peer-timeout <duration>
  --results-duration <duration>
  --auto-start / --no-auto-start
  --once
  --password-file <path>
  --state-dir <path>
  --log <path|->
  --log-format <text|json>
  --seed <fixed seed>              test/admin use
  --no-stdin
  --version
```

Rules:

- Stage A with SDL2_net supports `--port` but binds all interfaces; it must
  reject a non-wildcard `--bind` as unsupported rather than claim it worked;
  Stage B enables `--bind` only with a transport backend that can bind a
  specific local address;

- `maxPlayers <= MAX_PLAYER_SLOTS`;
- `maxClients <= MAX_CLIENT_PEERS`;
- without bots, `minPlayers <= min(maxPlayers, maxClients)`;
- with configured bots,
  `minPlayers <= min(maxPlayers, maxClients + configuredBotSlots)`, where
  `configuredBotSlots` comes from the validated fixed-reservation/fill policy,
  not an assumed ability to invent bots at match start;
- the default Corridor 7 deathmatch allow-list is exactly `MAP51`–`MAP57`
  plus `MAP60`; `MAP58` and `MAP59` are placeholder boxes and are rejected
  unless a future explicit custom-map policy supersedes the built-in list;
- team/class policies must be coherent;
- input delay must fit protocol history and sequence windows;
- client playout target/watermarks must fit retained frame history, and input
  delay must leave measured command-production lead after the client trail;
- duration parsing must reject overflow/negative/ambiguous units;
- a missing/ambiguous data profile is fatal;
- fixed seeds are logged and clearly marked; randomly chosen seeds are
  generated securely enough to avoid accidental repetition, then distributed
  as deterministic match data.

### 13.3 Rendered client connection contract

The v2 server is usable only if the rendered client has an equally explicit
join path. Add a client option and menu field such as:

```text
ec7wolf --connect <host-or-address[:remote-port]>
         [--local-port <0..65535>]
```

The remote server endpoint and local UDP bind are separate values. By default,
the client binds local port `0` (ephemeral) and connects to remote port 5029;
it must not reuse the remote port as its local port as current `StartJoin()`
does. `--local-port` is a diagnostics/firewall escape hatch, not normally
needed. The menu, command line, invite/status text, and logs all use the same
parser and display IPv4 address/hostname plus effective remote port. Joining
the v2 dedicated protocol never falls back to a legacy P2P session or single
player after failure.

Test two through eleven clients on one machine with default ephemeral local
ports, DNS/address errors, explicit remote ports, an occupied requested local
port, and clean reconnect after socket close.

### 13.4 Example config shape

```ini
[server]
name = EC7Wolf Corridor 7 Server
bind = 0.0.0.0
port = 5029
max_clients = 8
max_players = 8
min_players = 2
auto_start = true
ready_timeout_seconds = 60
peer_timeout_seconds = 15
results_seconds = 10

[match]
mode = deathmatch
frag_limit = 20
input_delay = auto
client_playout_frames = auto
rotation = MAP51, MAP52, MAP53, MAP54, MAP55, MAP56, MAP57, MAP60

[data]
directory = /srv/ec7wolf/corridor7

[logging]
format = text
file = -
```

Use the project's existing config machinery only if it can operate without
client cvars, GUI defaults, and local-player side effects. A small typed server
config layer may be safer than loading arbitrary client configuration into an
authority.

### 13.5 Configuration change classes

Every setting is documented as one of:

- **immediate non-gameplay:** log verbosity, status-query visibility;
- **next lobby/match:** map rotation, mode, frag limit, bot fill, class policy;
- **restart required:** bind address/port, protocol/transport parameters,
  gameplay data set;
- **immutable during process:** hard capacity or deterministic format version.

An admin edit during `Running` updates the pending next-match config unless an
explicit canonical event supports it. Never let a terminal command change a
gameplay cvar on only the server midway through a tic.

---

## 14. Administration and operations

### 14.1 Local command set

Version 1 should support a small auditable set:

```text
help
status
players
peers
match
kick <peer-or-slot> [reason]
start
pause
resume
end [reason]
restart
map <map>             # next match unless explicitly documented
next
set <approved-key> <value>
reload-config         # approved next-match keys only
say <message>         # only if client system messages exist
quit
```

Commands resolve stable peer/slot IDs and print the target before action.
Gameplay-affecting actions enqueue authority events at a defined sequence.
`kick` must distinguish connection termination from deterministic pawn/roster
handling; in v1 it generally schedules a match abort then closes the peer.

Do not expose arbitrary console command execution, script evaluation, debug
keys, actor spawning, give/godmode, or file-system access through the server
admin surface.

### 14.2 Remote administration

Remote administration is deferred. If added later:

- do not send a reusable plaintext password in UDP;
- use a separate protocol/channel with mutual transcript binding,
  authentication, replay protection, confidentiality where secrets/commands
  require it, rate limits, and complete audit records;
- consider SSH/OS service access as the supported solution before inventing a
  cryptographic protocol;
- expose an allow-list of typed administrative operations, not the game's
  unrestricted debug/console parser;
- keep gameplay connection tokens separate from administrator credentials.

### 14.3 Logs and structured events

Log to stdout/stderr by default so systemd/container supervisors can capture
output. Optional files use explicit server state paths, rotation policy, and
failure handling.

Every line/event should have:

- UTC timestamp and monotonic uptime where useful;
- severity and stable event code;
- server session ID, match ID, and input/control epoch where relevant;
- peer ID/slot ID only when relevant;
- no secrets, raw password proof, connection token, or unnecessary full IP at
  normal verbosity.

Important events:

- boot/version/protocol/data profile and hashes;
- bind/listening/readiness;
- challenge/admission/rejection/rate limiting;
- lobby roster and ready transitions;
- manifest/start/seed/map/rules;
- late/missing inputs, loss/retransmit/RTT/jitter;
- digest agreement/mismatch with subsystem hashes;
- frag-limit outcome/results/rotation;
- admin commands and their authenticated local source;
- disconnect/timeout/abort;
- overload/catch-up/queue saturation;
- signal/shutdown and exit status.

### 14.4 Metrics and status

Start with local `status` plus periodic structured log metrics. Do not require a
web server. Useful gauges/counters:

- state, uptime, current map/match/input epoch and sequence;
- connected/ready/active humans and bots;
- server tick duration percentiles and maximum catch-up;
- per-peer RTT/jitter/loss/late inputs/retransmits;
- canonical frame backlog/history use, per-peer ACK trail, and negotiated
  client playout target;
- packet and byte rates, rejects by reason, rate-limit hits;
- digest mismatch count;
- memory/actor/thinker/GC counts;
- matches completed/aborted and shutdown reason.

If a metrics endpoint is later added, bind it separately and default it to
loopback. It must not share the gameplay packet parser.

### 14.5 Service deployment

Provide examples, not mandatory infrastructure:

- systemd unit with dedicated unprivileged user, explicit data/config/state
  directories, restart policy, `SIGTERM` timeout, and capability-free high
  port;
- container image/manifest that runs non-root, mounts commercial data read
  only, keeps state/logs separate, and exposes one UDP port;
- Windows service guidance or a normal console process managed by an external
  service wrapper;
- macOS launchd example if supported.

The binary must work without these wrappers. Do not require root, a desktop
session, home-directory write access, or a writable game-data directory.

### 14.6 NAT and discovery

For direct Internet hosting, the operator exposes/forwards one UDP port to the
server. Clients initiate outbound traffic, so they normally need no inbound
mapping. IPv4 direct address is version 1. IPv6, UPnP, LAN broadcast, and public
listing are separate tested extensions.

Avoid copying Zandronum's master-server behavior merely because its source is
available. A public directory creates availability, privacy, abuse, protocol,
and operations obligations beyond a dedicated binary.

### 14.7 Server recordings and reproducibility

The legacy demo format is not suitable for a dedicated match: current playback
is disabled, the format represents only a subset of one player's command
fields, and recording is entangled with the existing network-poll branch. Do
not make the server recompute historical bot AI or infer omitted slot inputs.

For diagnostics and a future replay feature, define a versioned authoritative
recording that stores:

- protocol/digest format, complete match manifest, roster/rules/data hashes,
  seed, and initial state digest;
- every finalized canonical input frame for every active slot;
- canonical lifecycle/roster/admin events with before-tic or stop-after phases;
- periodic world/subsystem digests plus the exact `ConfirmTerminal` and
  `ResultsCommit` records;
- no client address, password proof, connection token, or other secret.

Recording must happen after authority finalization and before simulation
consumption, using a bounded non-blocking writer or a policy that disables the
recording rather than stalling the match on disk. Replay reads the finalized
commands; it does not rerun historical network deadlines or bot decisions.

This diagnostic stream is highly valuable for reproducing desyncs, but it is
not required to promise polished user demo playback in dedicated version 1.
Live multiplayer save/resume remains out of scope.

---

## 15. Security and trust model

### 15.1 Assets and trust boundaries

Protect:

- server process availability and memory safety;
- canonical match state, roster, results, and lifecycle;
- operator filesystem/config/secrets;
- client addresses and connection identifiers;
- administrative authority;
- predictable resource limits.

Untrusted inputs:

- every UDP datagram, including before admission;
- client names, class requests, capability lists, hashes, and timings;
- client input sequences and digest reports;
- status queries;
- server config files and admin command text to the degree an operator can
  make mistakes;
- gameplay data/add-ons unless explicitly trusted and hashed.

The server's own playsim and match controller are trusted after loading
approved data. Clients are never trusted to report position, inventory,
damage, frags, winner, or map state.

### 15.2 Threat/control table

| Threat | Required controls |
| --- | --- |
| malformed/truncated packet | pure bounded codec, exact lengths, fuzzing, sanitizers |
| integer/count overflow | checked arithmetic, hard counts before allocation/loops |
| spoofed join slot exhaustion | stateless cookie, per-prefix/address rate limits, allocation only after proof |
| spoofed/lost/duplicate handshake leg | nonce/transcript/endpoint binding and idempotent Join-to-Welcome allocation |
| reflection/amplification | response-before-cookie no larger than request, bounded status replies |
| stale/replayed packet | session/connection/match IDs, packet and semantic replay windows |
| address impersonation | directional 128-bit authenticator plus source binding/rebind challenge; public connection ID is not a credential |
| unauthorized slot input | peer-to-slot ownership validation on every submission |
| forged start/pause/end/map/debug | authority-only messages accepted only on authenticated authority connection |
| command flood/history exhaustion | byte/packet/semantic rate limits and bounded queues/history |
| log flood | aggregation/sampling and per-source rejection counters |
| path traversal/config abuse | server-owned paths, normalized allow-listed filenames/maps, no remote file paths |
| data mismatch/desync | compatibility manifest, initial digest, periodic versioned digests |
| slow client stalls match | input deadline, neutral substitution, late counters, authority timeout |
| server overload | budgets, catch-up cap, queue limits, monitoring, controlled abort |
| RCON credential theft | no network RCON v1; secure separate design later |
| debug/cheat abuse | debug protocol disabled; local typed admin allow-list; cheats forced off |

### 15.3 Packet authority rules

Generate a policy table in code and exercise every row. At minimum, define
receiver-side legal states/transitions this narrowly:

| Message | Legal sender | Receiver state(s) | Permitted effect |
| --- | --- | --- | --- |
| `ClientHello` / `ClientJoin` | unknown/pending client with valid transcript | `LobbyOpen` admission | bounded challenge or one idempotent peer allocation |
| `ServerChallenge` / `Welcome` / `JoinReject` | challenged authority endpoint | client admission state only | advance the matching transcript; no playsim state |
| lobby selection / lobby-ready | admitted human owner | `LobbyOpen` | request owned settings/readiness only |
| `MatchManifest` | authority | `LobbyOpen`, `RosterLocked`, or `Results` after the `ResultsCommitAck`/drop barrier | enter `LoadingMatch` for a new match ID |
| `MatchReady` | admitted client | `LoadingMatch` or `ReadyBarrier` | mark exact manifest/baseline digest ready |
| `BeginMatch` | authority | client `ReadyBarrier` | install the exact first successor as pending; sample/freeze the owned human prime |
| `BeginAck` | admitted client | authority `ReadyBarrier` | validate exact record/epochs/target/immutable prime; activate and arm only after the full barrier; a drop invalidates the manifest |
| `InputSubmission` | admitted remote human owner | `Running` in the exact active epoch | store owned future command only; remote epoch primes travel in Begin/Resume ACKs |
| `CanonicalInputFrames` | authority | `ReadyBarrier`, `ResumeBarrier`, or `Running` after the authority completed the begin/resume barrier | first matching frame commits the pending epoch; install contiguous frames and enter/continue `Running` |
| frame ACK | admitted client | `Running`, `Paused`, `TerminalPending`, or `Results` while history is retained | release acknowledged history only above pause/terminal retention floors |
| digest report | admitted client | `Running`, `Paused`, `TerminalPending`, or `Results` | diagnostic/liveness comparison only |
| `PauseAfter` / pause ACK | authority / admitted client | `Running` | tentatively announce/ACK, then commit `StopAfterTic(N)` in frame N |
| `Resume` | authority | client `Paused` | retire old future input, install successor as pending, enter `ResumeBarrier`, and sample/freeze the owned human prime |
| `ResumeAck` | admitted client | authority `ResumeBarrier` | validate exact record/epochs/target/immutable prime; activate and arm only after the full barrier |
| `ConfirmTerminal` | authority | client `Running` through named N, `Paused`, `ResumeBarrier`, or `TerminalPending`; duplicate also in `Results` | queue until N or validate exact terminal N/reason/digests; from `Paused`/`ResumeBarrier`, atomically retire a pending successor and enter `TerminalPending`; send `TerminalAck` only after validation |
| `TerminalAck` | surviving client | authority `TerminalPending` | satisfy the exact confirmation-hash barrier; no world transition |
| `ResultsCommit` | authority | client with exact confirmed context in `TerminalPending`; duplicate also in `Results` | transition to `Results` and send `ResultsCommitAck`; queue if exact terminal validation is not yet complete |
| `ResultsCommitAck(hashOfResultsCommit)` | surviving client | authority `Results` with `commitAckPending` | satisfy only the exact commit barrier; enable timer/history release/rotation only after all survivor ACKs or drops |
| pre-tic or stop-after event | authority | `Running` and exact match/input epoch | apply only when committed in the named canonical frame/phase |
| lobby/loading/session abort | authority | `LobbyOpen`, `RosterLocked`, `LoadingMatch`, or `ReadyBarrier` | enter pre-running `Aborting`; never impersonate a gameplay command |
| controlled overload terminal at last completed tic | authority | client `Running` | enter `TerminalPending` without simulating another frame; use the generic terminal/commit barriers |
| emergency authority stop at last committed tic | authority | `Running`, `Paused`, or `TerminalPending` | drain retained history only through named tic, then fail session |
| next manifest | authority | `Results` after the `ResultsCommitAck`/drop barrier | begin the next roster/load barrier |
| leave | admitted client | any admitted nonterminal state | request only; authority chooses transition |
| shutdown notice/ACK | authority / admitted client | any nonterminal state | enter/ack bounded `ShuttingDown` |
| status query | unknown, if enabled | any nonfatal state | bounded read-only response |

Unknown messages, wrong-state messages, wrong-role messages, duplicates, and
out-of-window sequences have no world side effects.

A listen authority's local `EpochPrime` is deliberately not a wire message,
but it is processed through the same generated validation/policy function as
the corresponding ACK payload and is a required barrier member. A direct
function call may not bypass ownership, target, hash, epoch, or command checks.

### 15.4 Passwords and connection tokens

An optional join password must use a nonce-bound proof so the reusable secret
is not sent verbatim. Do not invent ad-hoc “XOR encryption.” If the project is
not prepared to add and maintain an appropriate cryptographic primitive,
document direct-IP/private-network operation and defer password protection.

Directional connection authenticators prevent off-path guessing when combined
with replay windows and endpoint binding; plaintext bearer values do not stop
an on-path observer. They are not accounts. Generate tokens, server secrets,
and nonces with an OS CSPRNG, not the deterministic gameplay RNG. Never feed
connection randomness into simulation streams.

### 15.5 Anti-cheat boundary

The server can enforce:

- command syntax/ranges/rates and slot ownership;
- ordinary playsim movement/weapon/ammo/health/collision/rules;
- canonical scores/outcomes;
- deterministic data compatibility and divergence detection.

It cannot reliably detect:

- aim assistance that emits legal human commands;
- wallhacks using the client's locally simulated world;
- collusion, stream sniping, or external automation;
- a client lying in cosmetic/UI-only state.

Do not ban based solely on latency or a digest mismatch that could be an engine
bug. Preserve evidence and distinguish protocol abuse, deterministic
incompatibility, and suspected gameplay automation.

---

## 16. Disconnects, reconnects, spectators, and roster changes

### 16.1 Human disconnect in version 1

Version 1 ends rather than silently changing a locked in-match roster, but the
executable transition depends on the lifecycle state where loss is detected:

- **`LobbyOpen`/`RosterLocked`/`LoadingMatch`/`ReadyBarrier`:** close the peer,
  invalidate any manifest containing its slot, and return to/rebuild the lobby,
  load, and ready barriers with a new roster hash and match ID. A `BeginAck`
  timeout never starts the old manifest minus that client.
- **`Running`, no unresolved stop:** finalize neutral commands for the lost
  slot while transition is pending. Reliably preannounce
  `AbortMatch(reason, StopAfterTic(N))` far enough ahead for all remaining
  clients to ACK; choose `N` beyond the already produced bot horizon; commit
  the complete body in canonical frame `N`; and simulate through exactly `N`.
  The departed peer is removed from required ACK sets, not from the locked
  simulation roster.
- **`Running` with any unresolved `StopAfterTic(N)`:** do not create a second
  stop, whether the first is pause, admin/disconnect abort, or graceful
  shutdown and whether it is preannounced or already committed. Retain its
  type and `N`, remove the departed peer from its required ACK/survivor set,
  neutralize the lost slot through `N`, complete/retransmit the existing
  semantic barrier for remaining peers, and record the additional disconnect
  as terminal/session metadata. If the sole stop is pause, freeze at `N` and
  then issue disconnect `ConfirmTerminal` for that unchanged world. Otherwise
  preserve the existing abort/shutdown terminal kind. A natural outcome at
  `N` still wins by normal precedence.
- **`Paused` or `ResumeBarrier`:** cancel and retire any pending resume/
  successor epoch and do not invent `N + 1`. The world is already frozen after
  completed tic `N`; lock the departed slot controller neutral as terminal
  session metadata, exclude that peer from survivors, and emit
  `ConfirmTerminal` for that existing `N`, current active input epoch, current
  world/score digest, and disconnect reason. No thinker, command, bot decision,
  score, or RNG state advances to manufacture an abort tic.
- **`TerminalPending`:** remove the peer from the remaining terminal or results-
  commit ACK set, mark the next-match roster dirty, and continue the generic
  barrier with the same terminal record.
- **`Results`:** remove the peer from any outstanding `ResultsCommitAck` set
  and mark the next-match roster dirty. Continue the current results barrier,
  but return through `LobbyOpen` for a new roster/hash/ID rather than automatic
  unchanged-roster rotation; explicit next-match bot fill may create a new
  roster.

The running and frozen paths converge on the generic
`ConfirmTerminal`/`TerminalAck` then `ResultsCommit`/`ResultsCommitAck`
protocol. Every surviving node records the same reason, terminal sequence,
standings, and digests. This is less ambitious than playing on, but it is
deterministic and cannot strand a pause/resume barrier. It must be authority
authored rather than independently inferred from local timeout time.

### 16.2 Later deterministic drop or bot takeover

Playing on requires a real protocol feature:

- `RosterChange` identifies slot, old/new controller, pawn disposition, score
  policy, bot seed/profile if applicable, and `ApplyBeforeTic(E)` boundary;
- every peer acknowledges it before the apply horizon or is itself removed;
- all nodes apply it at the same boundary;
- command frames before and after use the correct roster hash;
- bot takeover begins with neutral/reaction state, not omniscient inherited
  knowledge;
- UI clearly marks the change.

Do not destroy a pawn immediately in a socket timeout callback.

### 16.3 Reconnect and late join

Version 1 returns an explicit rejection while `Running`. A reconnect may be
accepted into the next lobby after the old connection expires.

True mid-match join requires one of:

- a complete versioned world snapshot plus deterministic object IDs, player/
  inventory/RNG/map/bot state serialization and a command catch-up tail; or
- replay from match start, which becomes increasingly impractical.

That is a separate milestone after stable server saves/snapshots. Do not
promise it via a “ready” packet alone.

### 16.4 Spectators

Spectators are not version 1. The data model reserves room by separating
client peers from active player slots. A future spectator still needs initial
world synchronization and ongoing canonical frames, plus a local view that is
not a controller. It must never be represented by an invulnerable pawn or
consume the active-player count.

### 16.5 Coordinator failure

Clients maintain an authority timeout distinct from ordinary player timeout.
If the authority is still alive but must terminate for sustained overload, it
stops after its last completed canonical tic `N` and uses the ordinary
`ConfirmTerminal(..., terminalKind = ServerOverload, N, digest)` then
`ResultsCommit` barriers. Lagging clients drain retained canonical history only
through `N`; no extra frame is invented and no client lateness is charged. If
the authority is so damaged that it cannot exchange that barrier, clients use
the genuine connection-loss path below rather than trusting a special
unauthenticated or half-delivered result.

On loss:

- stop advancing when canonical-frame history is exhausted;
- show/log “server connection lost,” not “player 1 left”;
- do not elect an arbiter or continue from locally proposed commands;
- close the match and return to a safe client menu state;
- retain recent command/digest diagnostics when enabled.

---

## 17. Integration with multiplayer bots

The dedicated-server and bot projects share the roster/command foundation.
Implement it once.

### 17.1 Authority ownership

- A bot occupies an ordinary active player slot.
- Its canonical `SlotKind` is `Bot`; it has no network `ownerPeer`.
- The authority runs every bot brain and generates its future command before
  finalizing the canonical frame.
- A dedicated authority can own any number of bot command producers while
  remaining a zero-slot process.
- A bot never appears in peer address, handshake, readiness, ACK, RTT, or
  timeout arrays.

### 17.2 Corrections to assumptions in the bot plan

When dedicated support is implemented, update the related plan/code so that:

- authority is a peer role, not “the host's local human slot”;
- a dedicated authority may have no local human;
- session processes can outnumber active player slots because the server is an
  extra process;
- peer count is not required to be less than or equal to active slot count;
- bot commands are included in server canonical frames and are not separately
  simulated by clients;
- offline skirmish and listen authority use the same roster/controller model
  without requiring a UDP socket.

### 17.3 Deterministic decision boundary

After completed world sequence `S`, the server builds all bot commands for
future target `F = S + D + 1`, before running any thinker for the next
executable frame. Those commands are authority outputs; clients consume them
from canonical frames and do not rerun bot brains. Canonical commands, bot
pawns, and their effects enter the cross-node playsim digest. Private bot
memory, perception beliefs, path state, utility state, and bot PRNG enter a
separate authority-only `BotBrainDigest`. If a bot command builder fails, that
is an authority software fault; it is not treated as a missing network peer.
Build in stable slot order and cache each immutable command by
`(matchId,inputEpoch,F,botSlot,controllerGeneration)` so multiple bots cannot
alias and a partial scheduler retry advances only missing producers.
For a preannounced stop/pause, choose the horizon beyond commands already
built and cease decisions beyond it; never discard a command after advancing
private brain/PRNG state and then resume from that advanced state.

### 17.4 Recommended implementation order with both projects

1. Protocol safety baseline.
2. Shared session/roster/peer-slot separation.
3. Canonical command-frame transport and listen-authority validation.
4. Zero-slot headless dedicated server.
5. Bot command producer and navigation/perception work.
6. Dedicated mixed human/bot and bot-only soak tests.

This prevents the bot implementation from deepening the current
peer-equals-player assumption and prevents the server implementation from
inventing a second bot roster.

---

## 18. Performance and resource budgets

### 18.1 Baseline measurements before optimization

Measure on all eight arenas with 1, 2, 8, and 11 active slots:

- headless simulation tic time and percentiles;
- client rendered tic time for parity comparison;
- packet/byte rate per client and aggregate;
- canonical frame size and history memory;
- actor/thinker counts and GC time;
- startup/map-load time and peak memory;
- idle lobby CPU use;
- one-hour and overnight memory growth.

Do not optimize away common resource initialization before profiling proves it
is meaningful and parity tests cover the change.

### 18.2 Tic budget

At 70 Hz the nominal per-tic wall budget is approximately 14.286 ms. The
server should normally use a small fraction of it, leaving room for packet
bursts and hosted environments. Define warning/failure thresholds from actual
hardware rather than asserting that every machine will meet a fixed percentage.

Track:

- time spent receiving/decoding;
- bot decision time;
- command finalization;
- authority catch-up debt, between-tic transport work, and remaining derivable
  human-command lead;
- playsim;
- digest generation;
- encode/send;
- GC/maintenance.

Expensive diagnostics may run at a lower interval, but the canonical
simulation digest schedule must remain deterministic and sufficient to catch
early divergence.

### 18.3 Network budget

Calculate the worst case for 11 slots, 70 canonical frames per second,
redundancy, ACK headers, control traffic, and N clients. Star topology gives
server outbound roughly O(clients × frame size), while clients have one uplink
and one downlink stream. Compare it with current mesh O(players²) traffic.

Set hard per-peer and global ingress/egress budgets. A client should not be
able to make the server spend unbounded CPU resending old history or formatting
reject logs.

Measure rendered-client playout occupancy/underrun/overrun and bounded
catch-up separately from server frame history. Choose `P`, `D`, watermarks,
and retained history from measured jitter/skew rather than treating them as
interchangeable buffers.

### 18.4 Long-running service concerns

- use 64-bit monotonic durations and tested wrap-safe 32-bit wire sequences;
- bound every queue/history/cache;
- avoid per-match leaked actor/class/resource state;
- reset deterministic world/RNG/bot state only through the specified
  `InitializeMatchWorld(manifest)` boundary between matches;
- prove socket rebind/rotation without process restart;
- handle log rotation/failure without blocking the sim;
- avoid accumulating addresses/nonces for rejected joins forever;
- run sanitizer/Valgrind or equivalent long soaks;
- make shutdown bounded even if a peer never acknowledges it.

---

## 19. Verification strategy

Testing is part of the architecture. A server that merely “seems to run” can
silently desynchronize or accidentally create a local pawn.

### 19.1 Unit tests

**Codec**

- round-trip every message type;
- zero/minimum/maximum counts and lengths;
- truncation at every byte offset;
- oversized declared length and actual length;
- invalid enum, count, slot, peer, sequence, and UTF-8/name policy;
- endian fixed vectors;
- duplicate/unknown extension policy;
- checked arithmetic near integer limits;
- no receive-buffer mutation;
- fuzz corpus seeded by real encoder output.

**Sequence/reliability**

- wrap-safe before/equal/after comparisons;
- cumulative/selective ACK behavior;
- duplicate, reorder, gap, old, and too-future packets;
- history expiry/retransmit;
- bounded queue behavior under floods;
- idempotent reliable event application;
- stale match ID with an otherwise current session/connection/sequence;
- connection packet replay and session semantic IDs remain monotonic across
  begin/resume/rotation, while only `(matchId,inputEpoch)` command windows
  reset;
- epoch-establishing headers carry the agreed parent epoch; bodies/ACKs bind
  parent, successor, semantic record hash, target, and immutable prime;
- the successor remains pending and no deadline accrues until every required
  ACK/prime is present; the first matching canonical frame commits it locally;
- full preannounced event body, semantic ACK before horizon, canonical-frame
  embedding/history recovery, and rejection when the body was never ready;
- `ApplyBeforeTic` versus `StopAfterTic`, incompatible-event rejection, and
  same-sequence natural-outcome/abort/pause/shutdown precedence;
- pause/resume control-epoch loss, duplication, reordering, and stale epochs.
- generic natural/scheduled/frozen-tic `ConfirmTerminal` validation;
  `TerminalAck` survivor barrier; reordered/lost/duplicate `ResultsCommit` and
  `ResultsCommitAck`; and prohibition on timer/rotation/history release before
  the second barrier.
- a delayed `ResultsCommitAck` hash from a prior commit/match cannot satisfy a
  later commit barrier.

**Session/roster**

- dedicated authority with no local player/view;
- listen authority with local human;
- slot 0 remote human, slot 0 bot, empty slots;
- max player/client/session counts;
- owner mapping and unauthorized input rejection;
- bot slots excluded from peer accounting;
- roster hash stable across platforms.

**Command finalization**

- complete inputs;
- one/multiple missing inputs;
- neutral substitution and correct held-edge derivation;
- late duplicate cannot replace finalized frame;
- local proposal is not applied before authority frame;
- button whitelist excludes UI/debug/pause;
- `bt_run` is excluded, resulting axes carry speed, and presentation gait is
  derived from canonical magnitude;
- axis range and invalid combination handling;
- exact `S/E/F` arithmetic and bootstrap intervals at `D = 0`, `D = 1`, and
  maximum supported delay, including sequence wrap;
- first non-neutral human/bot command executes at exactly `start + D` and
  `N + D + 1` after resume for `P = 0`, `P = D`, and `D = 0/1/max`, despite
  ACK loss, duplication, or ACK/input reordering;
- listen-authority-only and mixed listen/remote games produce the same
  immutable target-bound local/remote primes, including at `D = 0`;
- catch-up interleaves one future decision, one current finalization, and one
  simulation tic, and stops at a terminal tic;
- scheduler retry/deadline rebase invokes each bot producer exactly once per
  `(matchId,inputEpoch,targetSequence,botSlot,controllerGeneration)`; two or
  more bots at one target cannot alias; stop horizons, pause, and overload never
  advance a discarded decision or reuse it in another epoch;
- old buffered commands/retransmissions are rejected after resume input-epoch
  change; held/released button baselines and `D` neutral rebootstrap are exact;
- authority-overload exhaustion of derivable lead never increments client late
  counters or emits a burst of neutral commands.

**Config/admin**

- precedence, range errors, unknown keys, invalid maps/rotation;
- accept `MAP51`–`MAP57` and `MAP60`, and reject `MAP58`/`MAP59` from the
  built-in deathmatch allow-list;
- human-only and bot-filled `minPlayers` capacity inequalities, including
  `maxClients < maxPlayers`, zero bot capacity, exact capacity, and overflow;
- `P/D` playout/lead/history constraints at zero, exact bounds, auto choice,
  and unsupported remote `D = P = 0`;
- secret redaction;
- action classification immediate/next-match/restart;
- admin actions schedule rather than mutate mid-tic.
- Stage A rejects unsupported non-wildcard bind addresses; the later backend
  passes loopback-only binding, invalid-address, occupied-port, and
  unintended-interface reachability tests.

### 19.2 Headless startup gates

Create `tools/test_dedicated_server_startup.sh` or equivalent that:

1. launches from a temporary/package directory;
2. unsets `DISPLAY`, `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, and desktop
   environment variables;
3. assigns intentionally invalid video and audio driver names;
4. supplies explicit data/config paths;
5. waits for a textual/machine-readable listening-ready event;
6. sends a status/handshake probe;
7. terminates with `SIGTERM`;
8. verifies clean exit, socket release/rebind, and no video/audio/GUI init log.

An optional `strace`/platform gate asserts no window-system socket, GPU device,
audio device, or joystick is opened. That test is diagnostic where syscall
tracing is unavailable, not a reason to weaken normal startup assertions.

### 19.3 Zero-slot and capacity gates

For server plus 1, 2, and maximum human clients:

- active pawn count equals human/bot slot count exactly;
- the server simulates `player_t` objects for remote/bot slots, but no
  `player_t`, pawn, camera, inventory, command, score row, team, spawn, or frag
  identity represents the server process itself;
- an eleven-player match accepts eleven clients;
- slot 0 is ordinary and can be remote;
- killing every player never targets a server object;
- results list only active slots;
- no loop waits for a server `TicCmd_t` or bot network ACK.

### 19.4 Determinism/parity gates

Adapt the existing loopback/capture harness:

- dedicated server + two rendered clients, fixed seed and scripted commands;
- byte-identical canonical input-frame logs on all nodes;
- identical full replicated playsim/subsystem digest at every tic;
- bot-enabled matches compare canonical bot commands and ordinary bot-pawn
  world state across all nodes, while `BotBrainDigest` is checked only between
  reset-equivalent authority runs and never expected from clients;
- all eight multiplayer arenas;
- free-for-all and team rules, both player classes, frag limit, death/respawn,
  doors, forcefields, transporters, mines, pickups, hazards, and map rotation;
- authoritative tile/solidity/trigger/wall fields, movement collision, and
  gameplay `CheckLine` remain identical when pixel-derived render masking is
  retained, disabled in a test build, or split from the map representation;
- CD music/content present versus absent where permitted: gameplay RNG/digest
  must remain equal; optional client-only checks may compare repeatable
  soundtrack-choice sequence separately;
- varied client render rate, texture-animation cadence, audio availability,
  and sound zone leave the gameplay RNG/digest and bot-hearing events equal;
- cross-platform trig-table hashes and fixed/integer angle golden vectors at
  every boundary used by authoritative gameplay;
- rendered listen authority versus dedicated authority from reset snapshots
  with the same roster/commands/seed;
- debug and optimized builds and supported compiler/platform combinations.

Do not compare two simultaneous symmetric slots as a “same controller parity”
test; actor/RNG ordering and interaction differ. Replay the same scenario from
reset state, changing only runtime role/presentation metadata.

### 19.5 Network impairment gates

Use the existing userspace network-delay tools extended to the star topology:

- asymmetric client A/B latency;
- jitter, loss, duplication, and reordering;
- 80 ms and 150 ms round-trip targets;
- burst loss across submission and canonical directions;
- lost manifest/start/control ACKs;
- loss/reordering of `ConfirmTerminal`, `TerminalAck`, `ResultsCommit`, and
  `ResultsCommitAck` beyond `resultsDuration`, with terminal history retained,
  results duration unstarted, and the next manifest barred until ACK/drop;
- lost latest command with recovery from redundant history;
- late input neutral substitution;
- server and client frame-history expiry;
- positive/negative client clock skew, delayed/batched canonical delivery,
  renderer rates above/below 70 Hz, low/high playout watermarks, and gaps;
- authority stalls longer than `D` and the catch-up cap, including bounded
  between-tic transport polling and `ServerOverload` rebase/abort;
- no client-to-client gameplay datagrams;
- sustained full tic rate within the test environment's measured processing
  ceiling;
- deterministic clean failure outside the supported envelope.

### 19.6 Lifecycle/failure gates

- lobby open with no clients for a bounded test period;
- duplicate hello/join and slot exhaustion attempts;
- blind spoofed Challenge/Welcome, lost Welcome, and duplicate identical Join
  returning exactly one logical connection/slot;
- wrong protocol/build/data/capability with exact rejection reason;
- ready timeout and client load failure;
- client explicit leave and process kill in lobby/loading/running/paused/
  resume-barrier/terminal-pending/results;
- paused/resume-barrier loss retires the successor proposal and confirms the
  already completed frozen tic without executing `N + 1` or advancing bots/
  RNG; loading/ready loss invalidates and rebuilds the manifest;
- running loss while pause/abort/shutdown `StopAfterTic` is unresolved retains
  that one typed stop and never installs a competing stop; the pause case then
  terminates from the frozen tic;
- a peer dropped during terminal/results-commit barriers forces a rebuilt
  next-match roster/hash/ID (or explicit bot fill), never unchanged rotation;
- authority process loss at each client state;
- `SIGINT`/`SIGTERM` during boot, lobby, packet wait, running tic, results, and
  map transition;
- repeated match rotation without process restart;
- long lobby/loading/pause/results intervals create fresh deadline epochs and
  never burst accrued tics on begin/resume;
- pause/terminal `StopAfterTic` inside a batched client catch-up stops at the
  exact sequence and produces exactly one resumed `N + 1`;
- in-match menu held open beyond canonical-history and ordinary peer-timeout
  durations while network/simulation continue, then closed without desync;
- results overlay held open while terminal/results-commit ACKs, liveness, and
  next-match readiness continue;
- `--once` exit;
- socket immediately reusable after clean shutdown;
- no fallback into single player or menu.

### 19.7 Hostile network gates

From unknown, stale, authenticated-but-wrong-role, and spoofed sources:

- malformed start/manifest and length/count attacks;
- forged ACK and connection IDs;
- correct public connection ID with a wrong uplink authenticator and forged
  server traffic with the right connection ID but wrong downlink
  authenticator;
- unauthorized slot submissions;
- forged canonical frames;
- forged end, block, pause, debug, input-ack, roster, map, and shutdown events;
- packet floods, join floods, status amplification, log floods;
- replay from prior session/match, including the same roster and reset command
  sequence under a different match ID;
- cross-rotation replay of authenticated old lobby-ready, leave, pause/resume,
  outcome, and shutdown semantic records;
- oversized name/config-like payloads;
- invalid UTF-8/control-character names;
- history and retransmit abuse.

Assert no world/lifecycle side effect, no unbounded memory/log growth, and no
crash under ASan/UBSan. Generate hostile fixed vectors through the shared codec
where possible so enum/packing drift cannot invalidate the test.

### 19.8 Presentation-coupling sanitizer gates

Run a dedicated ASan/UBSan match through known hotspots:

- player spawn/rebirth/class/FOV/projection;
- damage, death, respawn, frag limit;
- doors opening/closing and zone linking;
- pushwalls and dynamic walls;
- inventory full/success messages and keys;
- locked-door success/failure after common `LOCKDEFS`/key-group parsing;
- Corridor 7 health chamber, ammo dispenser, elevator/clearance;
- weapons and positional sound events;
- local pause/menu attempts received from clients;
- results/rotation.

Track unexpected calls into null presentation services as test failures once
migration is complete.

### 19.9 Build and packaging gates

- build client and server in one clean configure;
- compare complete native class registries and all-arena spawned class/count
  manifests so static-library dead stripping cannot silently remove actors;
- server binary carries correct `1.0-betaX` and protocol output;
- `ldd`/platform import inspection excludes GTK, OpenGL/libepoxy, and
  SDL2_mixer from the final server target;
- no window/audio initialization despite environment;
- package contains server executable, `ec7wolf.pk3`, templates/launcher/docs,
  and required redistributable libraries;
- package contains no commercial Corridor 7 file;
- forbidden-file scan rejects `CORR7CD.EXE`, every `*.CO7`, extracted FLICs,
  ripped music, and any other commercial client-package asset;
- server starts from packaged directory with operator-supplied data;
- ordinary client release package/startup gate remains green.

### 19.10 Soak and performance gates

- server idle lobby CPU and memory;
- one-hour impairment match;
- overnight repeated rotation at maximum players/scripted clients;
- accelerated sequence-wrap test;
- actor/GC/memory counters return to baseline between matches;
- sustained overload test produces warnings and controlled policy, not a
  silent spiral;
- log/state disk failure is reported without corrupting simulation or hanging;
- deterministic seed/replay artifacts can reproduce a failure.

---

## 20. Milestone plan

Every milestone ends in a runnable proof. Do not combine several milestones
into one unreviewable patch merely because an AI agent can edit quickly.

### D0 — Freeze the contract and repair the safety baseline

**Work**

- Record the selected command-authoritative lockstep design and v1 non-goals.
- Inventory current dirty multiplayer work; preserve and integrate it rather
  than overwriting it.
- Fix the legacy `StartPacket` trailing-array off-by-one and ensure no
  variable-length packet is swapped/read before full validation.
- Correct hostile-test enum/packing drift using real encoder vectors.
- Lock down current control packets by authenticated source/known authority
  where possible before exposing a long-running service.
- Add codec/parser unit-test infrastructure and sanitizer target.
- Capture current two-player checksums/rules/latency behavior as regression
  baselines.

**Exit gate**

- Existing multiplayer suite passes.
- Truncated/malformed legacy startup and forged control packets cannot access
  out of bounds or alter a match.
- Design-decision record names the new protocol as intentionally incompatible.

### D1 — Session, authority, peer, and slot separation

**Work**

- Add runtime roles, `PeerId`, `PlayerSlot`, session/roster, ownership map,
  separate counts, optional local human/view.
- Add the minimal `SessionLifecycle` states and typed transition owner needed
  by admission, manifest loading, ready/begin, running, terminal-pending, and
  shutdown; do not infer those phases from menus or socket waits.
- Replace `IsArbiter == ConsolePlayer` with authority semantics.
- Classify every `numPlayers`, `Client[]`, `ConsolePlayer`, players[0], and
  network-mode check by its actual meaning.
- Convert gameplay/spawn/score/GC loops to active player slots.
- Keep current rendered multiplayer functional through adapters.
- Align the shared foundation with the bot plan.

**Exit gate**

- Listen host still runs existing human multiplayer.
- Tests construct a dedicated session model with authority peer and zero local
  slot without indexing player arrays.
- Slot 0 can be owned by a non-authority peer in model/unit tests.
- `MAX_PLAYER_SLOTS` and client/session capacities are independently validated.

### D2 — New bounded codec, reliability, and protocol vectors

**Work**

- Implement v2 header, pure byte reader/writer, message types, sequence/ACK
  windows, bounded histories, and fuzz target.
- Define canonical gameplay command fields/button mask.
- Implement session/connection/match IDs, directional authenticators, and
  non-resetting connection/semantic replay windows plus tuple-keyed
  match/input command windows; prove a public connection ID alone grants no
  authority.
- Produce checked golden vectors from the real encoder for other-language test
  tools.
- Add structured rejection codes and protocol version reporting.

**Exit gate**

- All unit/fuzz/sanitizer codec gates pass.
- Every message has a sender/state/side-effect policy test.
- Worst-case command frames fit the chosen MTU or have a tested batching
  design.

### D3 — Star handshake and lobby with a listen authority

**Work**

- Implement transcript-bound, duplicate-safe
  hello/challenge/cookie/join/welcome.
- Bind peers to endpoints/tokens; stop distributing peer addresses.
- Add compatibility manifest, a single-match canonical
  `InitializeMatchWorld(manifest)`, lobby roster/settings, loading/ready
  barrier, and baseline digest. Stop at `ReadyBarrier`; executable
  begin/bootstrap belongs to D4 with canonical-frame transport.
- Add admission, load, ready, and base peer-liveness timeouts/rate limits so a
  silent peer cannot hold the first match forever.
- Define the rendered client's v2 connect contract, using a remote
  `--connect host[:port]`/menu address independently from an ephemeral local
  UDP port.
- Run it first in a rendered listen authority to isolate networking from
  headless work.
- Explicitly reject match-in-progress joins.

**Exit gate**

- Two or more clients connect only to the authority.
- Packet capture/test instrumentation shows no client-to-client gameplay
  datagrams or disclosed peer address list.
- Mismatch/full/in-progress/rate-limited joins receive exact errors.
- Spoofed one-packet joins cannot allocate full slots.
- Independent fresh-process clients agree on the exact ready-barrier baseline
  digest and pending-spawn ordering for one manifest.
- Multiple clients on one machine connect without manually assigning distinct
  local ports.

### D4 — Canonical hub input transport

**Work**

- Implement owned `InputSubmission` and authority `CanonicalInputFrame`.
- Implement the semantic `BeginMatch` ACK barrier, `D` neutral bootstrap,
  immutable baseline command prime, pending-to-active epoch handoff, fresh
  deadline/input epochs, fixed authority scheduler, and bounded rendered-client
  playout buffer.
- Implement listen-local `EpochPrime` through the same validation/barrier path
  as remote ACK primes; do not create a self-UDP peer merely to satisfy it.
- Move input delay, resend history, ACKs, and liveness to hub semantics.
- Split local UI controls from serialized gameplay controls.
- Validate axes/buttons/ownership/rate/sequence.
- Implement neutral missing-command synthesis and late accounting.
- Implement base hub liveness and neutral/timeout behavior before relying on
  it for continued simulation.
- Implement the minimum reliable `StopAfterTic(AbortMatch)` primitive used by
  the D4 missing-input timeout; D9 later applies and hardens it across every
  disconnect/lifecycle case.
- Implement complete embedded deterministic event bodies, semantic ACK before
  apply horizon, natural terminal-pending confirmation, and pause control
  epochs; the generic `ConfirmTerminal`/`TerminalAck` and
  `ResultsCommit`/`ResultsCommitAck` history barriers; and per-message lifecycle
  policy. Make begin, pause/resume, abort, terminal confirmation, and results
  commit authority control, never player buttons; natural end remains playsim-
  discovered.
- Convert in-match client menus from synchronous waits to non-blocking overlays
  that keep transport and playsim running.

**Exit gate**

- Listen authority and clients install byte-identical command frames.
- Determinism passes under asymmetric loss/jitter/reordering.
- Client menus do not pause/block the match.
- Missing input follows the exact neutral/timeout policy.
- No participant simulates its local proposal before canonical return.
- `D = 0`, `D = 1`, and maximum delay execute the exact bootstrap and `S/E/F`
  sequence/prime contract without startup deadlock or unintended neutral first
  command; catch-up stops at a natural terminal tic.
- Listen-authority-only and mixed local/remote games prime begin/resume
  identically, including `D = 0`; no authority-local human bypass exists.
- Lost/duplicated pause, resume, preannounced event, terminal confirmation, and
  results-commit packets cannot double-apply or strand acknowledged peers.
- Client/server clock skew, batched frames, server stalls beyond `D`, and long
  pause/results intervals follow the defined playout/overload/epoch policy
  without blaming clients or bursting stale commands.

### D5 — Extract the common simulation tic and full digest

**Work**

- Extract `RunSimulationTic` from `PlayLoop`.
- Separate gameplay semantic events from HUD/audio/view effects.
- Introduce null presentation services and local-view guards.
- Expand stable world/subsystem digests.
- Add a deterministic actor serial with specified creation, destruction,
  map-reset, serialization/diagnostic, GC, and stable-order rules.
- Preserve VICTORY→WORLD→PLAYER→NORMAL order, victory short-circuit, internal
  per-thinker GC behavior, and audited outer-loop maintenance.
- Define the determinism ABI; inventory authoritative libm use, implement or
  select the canonical angle/table strategy, and add cross-platform golden
  vectors before claiming mixed-platform lockstep.
- Keep rendered client behavior unchanged around the new seam.

**Exit gate**

- Recorded canonical frames drive the same world with and without rendered
  outer loop from reset snapshots.
- Digest covers player/inventory/actors/map/RNG/match state and catches
  injected divergence before visible actor movement where applicable.
- Simulation tic has no wall-clock, socket, physical-input, render, or audio
  output dependency.
- Actor serials and digest ordering match across debug/optimized builds and
  spawn/destroy/reuse/map-reset stress; no pointer is a canonical identity.
- Extracted tics advance a door, elevator, pushwall, dispenser/WORLD wall
  animation, and locked-door success/failure exactly like the rendered loop.
- Initial pending actors retain legacy just-spawned/PostBeginPlay/first-action
  timing; ready-barrier digest ordering matches without early
  `FinishSpawningActors()`.
- Gameplay RNG registry/table hashes and angle-boundary vectors match every
  declared compatible build/platform pair.

### D6 — Playerless authority inside the development binary

**Work**

- Add `DedicatedAuthority` runtime path using common resources, server
  services, and fixed scheduler.
- Skip all video/input/audio-output/menu paths.
- Add explicit data/config validation and textual lifecycle.
- Run server plus rendered clients before dependency/source slimming.
- Add signal and stdin administration.
- Add an early console-only platform entry for the behavioral server: at
  minimum a `NO_GTK` POSIX target/harness here. Do not claim general no-display
  behavior from a branch reached only after GTK/NSApplication startup.

**Exit gate**

- No-display/no-audio startup passes on the explicitly supported D6 harness;
  D7 completes native platform entries and final target coverage.
- Server plus two clients creates exactly two player pawns and identical
  digests.
- Server never uses `ConsolePlayer`, local view, status screen, or command slot.
- Graceful stop works in lobby and match.

### D7 — Separate `ec7wolf-server` target

**Work**

- Add server entry point/target and common/client/server libraries or source
  groups.
- Remove GTK, render backend, input, SDL2_mixer, and client-only UI linkage.
- Preserve necessary resource metadata/decoders.
- Generalize PK3 build/output assumptions.
- Add native Windows console and macOS plain-CLI entry points that reach
  server bootstrap without GUI subsystem/`NSApplication` startup.

**Exit gate**

- Clean build produces both client and server.
- Server target passes import/dependency policy and behavior parity.
- Client target and ordinary renderer/audio/input tests remain green.

### D8 — Match controller, results, rotation, and config

**Work**

- Complete results, rotation, richer config, and next-match policy on the
  minimal lifecycle/manifest foundation delivered in D1–D4.
- Move map/rules/seed/frag outcome/rotation authority out of presentation
  loops.
- Harden and reuse D3's `InitializeMatchWorld(manifest)` across rotation,
  proving complete reset/load/spawn/pending-state behavior before every ready
  digest.
- Implement typed server config/CLI, validation, `--once`, auto/manual start.
- Render client results as a non-blocking overlay from the confirmed terminal
  record; keep reliable ACK/liveness active, and do not start the results timer
  or send the next manifest until the `ResultsCommitAck`/drop barrier completes.
- Mark the next-match roster dirty when either terminal barrier drops a human;
  return through `LobbyOpen` and rebuild its hash/manifest/ID, unless explicit
  next-match bot-fill creates a newly declared roster.

**Exit gate**

- Multi-map rotation completes without menu/user acknowledgement or process
  restart.
- Frag limit/team/class/map rules agree on server/clients.
- Invalid config/data fails before listening; next-match changes apply only at
  the documented boundary.
- Match B has the same initial digest from a fresh process and after any
  unrelated match A when B's manifest is identical.

### D9 — Disconnect and failure semantics

**Work**

- Finish peer and authority liveness/failure transitions for every lifecycle
  phase, building on the base D3/D4 timers.
- Implement reliable authority-scheduled match abort on human loss.
- Implement the paused/resume-barrier loss branch: retire a pending successor,
  exclude the lost peer, and confirm the already frozen completed tic without
  generating another command or simulation tic.
- If loss occurs while any stop is unresolved, retain and complete that sole
  survivor-ACKed boundary, neutralize the slot through it, and attach the loss
  as terminal metadata; a pause then terminates from its frozen tic. Never
  queue a second stop for the same running world.
- Complete the generic terminal and results-commit ACK/drop survivor-set
  handling for loss in `Running`, `TerminalPending`, and `Results`.
- Complete client server-loss behavior and harden D3 ready/load/lobby timeout
  transitions under loss, duplication, and shutdown races.
- Add bounded shutdown notification and socket cleanup.
- Optionally design, but do not silently add, canonical slot removal/bot
  takeover.

**Exit gate**

- Kill any participant in every lifecycle state without indefinite wait or
  desync.
- Remaining clients see the same reason/terminal sequence.
- Coordinator loss never elects a client or continues locally.
- Socket can be rebound immediately after clean exit.

### D10 — Security and operations hardening

**Work**

- Complete cookies/tokens/rate limits/replay protection and hostile gates.
- Add structured logs, status/metrics, local admin allow-list and audit.
- Add service examples and resource/overload budgets.
- Threat-review every message and config/admin path.
- Keep remote RCON disabled unless separately designed and tested.

**Exit gate**

- Hostile corpus/fuzz/ASan/UBSan has no crash/world side effect.
- Floods remain within memory/CPU/log budgets.
- Admin actions are scheduled/audited; secrets are redacted.
- Long-running status contains actionable tick/network/digest health.

### D11 — Bot authority integration

**Dependency:** the bot implementation exists far enough to produce normal
commands.

**Work**

- Map bot slots into the shared roster with no peer.
- Run brains at the authority decision boundary behind an immutable per-bot
  decision cache keyed by `(matchId,inputEpoch,targetSequence,botSlot,
  controllerGeneration)` and visited in stable slot order.
- Track and enforce the greatest produced and committed stop horizons; check
  human-lead/stop feasibility before brain mutation; freeze through pause; and
  retain decisions across scheduler retry, deadline rebase, and terminal
  diagnostics until the whole match/epoch reset policy destroys them.
- Include commands in canonical frames and ordinary bot-pawn state in the
  replicated playsim digest; add a separate authority-only `BotBrainDigest`
  for brain memory/path/PRNG diagnostics.
- Add human/bot, bot-only, listen/dedicated parity and soak tests.

**Exit gate**

- Server remains absent from player count while bots occupy ordinary slots.
- Bots never enter network liveness/readiness.
- Every node consumes identical bot commands; all ordinary gameplay rules
  apply.
- Instrumented retries, pause/resume, and overload rebase/abort with at least
  two bots prove exactly one brain/PRNG advance per bot/produced target, no key
  aliasing, and no decision beyond a committed horizon.
- Reset-equivalent authority runs reproduce the private bot-brain digest;
  clients are never expected to generate or match it.

### D12 — Packaging, cross-platform, and release qualification

**Work**

- Create a redistributable server package/launcher/template separate from
  commercial data.
- Extend CI/build matrix and package-startup gate.
- Run all arenas, maximum capacity, impairment, hostile, cross-build, and
  overnight rotation tests.
- Write operator and protocol compatibility documentation.
- Rebuild and validate the ordinary Corridor 7 release package as required by
  project policy.

**Exit gate**

- Fresh-machine/package no-display startup succeeds with user-supplied data.
- No commercial files are in the server archive or version control.
- Client release package startup remains green.
- All completion criteria in section 23 are evidenced by commands/logs/tests.

---

## 21. Packaging and distribution design

### 21.1 Keep client and server artifacts conceptually separate

The existing Corridor 7 release package is a self-contained **client** package
and, by local project policy, includes the operator's commercial game files.
That directory must never be committed or redistributed.

The dedicated **server** deliverable should instead contain:

```text
ec7wolf-server
ec7wolf.pk3
run-server.sh / run-server.cmd as appropriate
server.cfg.example
README-server.md
LICENSE / copyright notices
required redistributable shared libraries, if packaging them
optional systemd/container examples
```

It must not contain any commercial Corridor 7 file. The explicit forbidden
scan includes at least:

```text
CORR7CD.EXE
MAPTEMP.CO7
GFXTILES.CO7
VGADICT.CO7
VGAHEAD.CO7
VGAGRAPH.CO7
AUDIOHED.CO7
AUDIOT.CO7
*.CO7
```

Also reject extracted FLIC/cinematic assets, ripped music, and any future
commercial filenames added to the client package. Keep packaging allow-listed
rather than trusting only a forbidden list. The launcher/config points at an
operator-owned data directory.

### 21.2 Server launcher behavior

The launcher should:

- resolve its own directory without changing global system configuration;
- default config/state/log paths to package-local or explicitly documented
  service paths;
- preserve quoted paths and forward arguments safely;
- require/accept an explicit commercial data directory;
- never copy commercial files into the server package automatically;
- print the exact binary/config/data paths on failure;
- return the server's exit code;
- avoid desktop-launch behavior or a terminal that closes before an error is
  readable.

For service deployment, running the binary directly with absolute paths is
preferable to relying on a convenience launcher.

### 21.3 Package gates

Add a dedicated package script and startup test rather than weakening the
client release test, which intentionally uses Xvfb/audio scaffolding.

The server package test should:

1. stage only the allowed manifest;
2. scan the package for known commercial Corridor 7 filenames and hashes;
3. start from the packaged directory with display/audio unavailable;
4. point at a test/operator data directory outside the package;
5. reach listening, accept a probe/client, and shut down;
6. verify config/log/state stay in the selected writable location;
7. inspect direct dynamic imports;
8. print a reproducible package manifest and checksums.

The normal project completion workflow still runs
`tools/package_corridor7_release.sh` and
`tools/test_corridor7_release_startup.sh` for the ordinary client package. The
server workflow is additive.

### 21.4 Data compatibility versus redistribution

The server may require the same commercial data as clients to run the full
playsim. That is an operator prerequisite, not a reason to ship the data. The
documentation should explain which purchased Corridor 7 edition/profile is
supported, how to point the server at it, and how a compatibility hash mismatch
is reported without publishing proprietary content.

Do not log or expose full proprietary lump/file contents. File names, sizes,
and cryptographic hashes used for compatibility are normally sufficient.

---

## 22. Risk register and mitigations

| Risk | Likelihood | Impact | Early signal | Mitigation/decision |
| --- | --- | --- | --- | --- |
| Peer/slot assumptions survive behind adapters | high | critical | server still needs `ConsolePlayer` or marks itself received | assertions, semantic types, zero-slot max-capacity gate before headless work |
| Protocol rewrite regresses existing multiplayer | high | high | listen tests fail or legacy hangs | staged listen-authority v2, retain explicit legacy path temporarily, baseline checksums |
| Packed legacy packet vulnerability is exposed longer | high | critical | sanitizer/hostile failure | D0 safety fixes before service/lobby work |
| “Headless” still creates hidden/dummy window | medium | high | requires Xvfb/SDL dummy driver | invalid-driver/no-display gate and syscall/import audit |
| Removing renderer code breaks loading/gameplay metadata | high | high | missing actors or changed solidity/triggers/LOS | behavior-first build, retain required metadata, separate pixel masking, authoritative-map/collision/LOS parity |
| Audio early return changes gameplay events/RNG | medium | critical | digest or bot-hearing differs by sound zone/device | semantic sound events, gameplay-RNG allow-list, sound-zone/audio parity gate; keep `Corridor7Music` presentation-only |
| Null local player causes array UB | high | critical | ASan crash in doors/death/HUD/FOV | optional local-player API, no sentinel indexing, hotspot sanitizer suite |
| Local presentation side effects crash server | high | high | `StatusBar`/camera/screen null dereference | event services + transitional null objects and unexpected-call counters |
| Command hub doubles latency beyond configured delay | medium | high | repeated neutral inputs on healthy links | measure two-leg path, server-selected delay, redundant submissions/frames |
| Client clock drift empties/overfills canonical queue | high over long runs | high | recurring underruns or growing frame backlog | negotiated playout target, contiguous watermarks, bounded idle/catch-up, skew tests |
| One slow client degrades everyone | high | high | frame deadline misses | neutral substitution, liveness policy, metrics, bounded abort |
| Neutral command edge semantics are wrong | medium | high | stuck firing/use/weapon behavior | explicit prior canonical state and unit/integration tests |
| Digest omits early divergence | high | high | clients disagree before checksum | comprehensive versioned subsystem digest and command traces |
| Digest hashes unstable data | medium | high | platform/compiler-only mismatch | stable IDs/order/encoding, no pointers/padding/unordered iteration |
| Server overload causes catch-up spiral | medium | high | networking starved while processing tics | monotonic scheduler, catch-up cap, budgets, controlled abort |
| Pause/rotation reuses stale deadlines or commands | medium | critical | burst tics or pre-pause fire after resume | fresh deadline/input epochs, discard old future input, neutral rebootstrap |
| Begin/resume epoch starts without its first command | medium | critical | `D=0` deadlock or unintended neutral action | immutable command prime inside semantic ACK; activate/arm only after full barrier |
| Scheduler retry advances a bot brain twice | medium | critical | bot PRNG/path diverges after overload or pause | tuple-keyed immutable decision cache, pre-mutation horizon/lead checks, exactly-once instrumentation |
| Terminal confirmation/commit is lost during rotation | medium | high | client remains terminal while server loads next map | semantic `TerminalAck` then `ResultsCommitAck`/drop barriers and retained terminal history |
| Barrier-time peer drop is reused in “unchanged” rotation | medium | high | next manifest names a dead owner | dirty-next-roster flag; return through lobby and rebuild hash/ID or explicitly bot-fill |
| UDP amplification/slot exhaustion | high for public server | high | many unknown-source allocations/replies | stateless cookies, response sizing, per-source/global rate limits |
| Unauthorized control packet ends match | high in current protocol | critical | hostile test changes playstate | authority/source/session validation table and v2 codec |
| Remote admin becomes arbitrary code/debug path | medium | critical | reuse of debug/console packet | local admin only v1; separate secured allow-listed design later |
| Full state replication scope creeps into v1 | medium | high | actor snapshot/join work blocks zero-slot server | explicit command-lockstep ADR and deferred late join/spectator |
| Bot and server projects build duplicate rosters | medium | high | two owner/kind mappings | shared `g_session` milestone and cross-plan update |
| Server package leaks commercial data | low/medium | critical | `CORR7CD.EXE`, `*.CO7`, FLIC/music assets in archive/git | allow-list manifest, explicit forbidden-file scan, separate package root |
| Long-running leaks/wrap bugs | medium | high | memory grows each rotation; sequence anomalies | overnight rotation, accelerated wrap, bounded caches, 64-bit time |
| Platform split becomes Linux-only `#ifdef` maze | medium | medium | common code full of `SERVER_ONLY` | service interfaces and target source lists; platform entry adapters only |
| Source import creates license conflict | low if plan followed | high | copied external blocks/notices missing | original implementation, immutable provenance and license review |

### 22.1 Stop-the-line conditions

Pause feature expansion and fix the foundation if any of these occurs:

- the server needs a dummy player/pawn to boot;
- any participant applies a non-canonical local command;
- a received packet is cast/read before validated bounds;
- server/client digests diverge in a baseline match;
- a no-display test initializes video/window/GUI;
- game rules depend on server wall time or packet arrival order;
- an unknown or non-authority source can schedule a lifecycle action;
- renderer/audio removal changes collision, spawn, RNG, or match outcome;
- one test process silently falls back to single player;
- a package manifest includes commercial data.

---

## 23. Final completion checklist

### 23.1 Process and player identity

- [ ] `ec7wolf-server` is a separate executable.
- [ ] Dedicated role is selected before presentation initialization.
- [ ] Server owns no human slot, local view, pawn, `TicCmd_t`, inventory, team,
  score, spawn, or frag identity.
- [ ] Slot 0 is not synonymous with authority.
- [ ] Eleven humans can occupy eleven player slots on a dedicated server.
- [ ] Peer, player, authority, local-human, and local-view types/maps are
  explicit and asserted.

### 23.2 Headless runtime

- [ ] Server starts and runs with display/audio/session variables absent and
  invalid SDL video/audio drivers.
- [ ] No video/window/GL/GTK/input/joystick/audio-output subsystem initializes.
- [ ] No menu, startup page, cinematic, fade, scoreboard page, HUD, or local
  acknowledgement controls server lifecycle.
- [ ] Required texture/sprite/map metadata remains correct on all arenas.
- [ ] `Corridor7Music` remains presentation-only, while gameplay RNG/digests
  and semantic sound events are invariant across soundtrack/audio choices.
- [ ] Server handles signals/admin/shutdown cleanly from every lifecycle state.

### 23.3 Network and protocol

- [ ] Clients send gameplay traffic only to the server.
- [ ] V2 protocol has magic/version/length/session/connection/match/input-
  epoch/sequence/authenticator fields and a pure bounded codec.
- [ ] Handshake validates a nonce/cookie-bound transcript, duplicate Join
  idempotency, compatibility, admission, manifest, and ready state with
  actionable rejection errors.
- [ ] No packed-struct or pre-validation byte-swap remains in the v2 path.
- [ ] Every message has legal sender/state/side-effect enforcement.
- [ ] Ownership, axis, button, sequence, count, size, replay, and rate checks
  are applied.
- [ ] Connection packet/semantic replay scopes stay monotonic across rotation;
  only tuple-keyed match/input command windows reset.
- [ ] Begin/Resume headers bind the parent epoch; remote ACKs and listen-local
  `EpochPrime` records bind an identically validated immutable first human
  command; successor activation waits for the complete prime barrier; and the
  70 Hz deadline is armed only afterward.
- [ ] Canonical frames fit the path-MTU design and recover supported loss.
- [ ] Client addresses are not distributed to peers.

### 23.4 Simulation and determinism

- [ ] One common simulation-tic function serves rendered and dedicated roles.
- [ ] It has no local input, UI, render, audio-output, socket, camera, or wall-
  clock dependency.
- [ ] Every active slot receives exactly one canonical command per tic.
- [ ] Clients never apply proposed input before canonical return.
- [ ] Rendered clients execute a contiguous 70 Hz playout queue with bounded
  watermarks/catch-up and no skip under clock drift or renderer-rate changes.
- [ ] Missing input follows tested neutral/held-edge and timeout policy.
- [ ] Authority bot commands are immutable exactly-once decisions keyed by
  match/epoch/target/slot/controller generation; stop, pause, retry, rebase,
  multiple bots, and overload cannot alias, double-advance, or discard private
  brain/PRNG state.
- [ ] Server and all clients agree on full versioned world/subsystem digests.
- [ ] FFA/team, classes, all arenas, weapons/items/hazards, doors/transporters,
  death/respawn, frag outcome, results, and rotation are covered.

### 23.5 Lifecycle and failure

- [ ] Lobby, lock, load, ready/begin barrier, run, pause/resume barrier,
  terminal-pending, results, rotation, abort, and shutdown are explicit
  states/transitions; countdown is presentation-only.
- [ ] Client local menus/UI cannot block or pause gameplay.
- [ ] Pre-scheduled map/admin actions use complete authority event bodies at
  explicit before-tic/stop-after phases; pause/resume creates an acknowledged
  fresh input/deadline epoch; natural outcomes use terminal-pending
  confirmation.
- [ ] Terminal history survives confirmation/commit loss until every surviving
  peer sends `TerminalAck` and `ResultsCommitAck`, or is explicitly dropped,
  before the results timer or rotation can advance.
- [ ] Client loss has one canonical reason and terminal sequence; loss while
  paused/resuming confirms the existing frozen tic and never fabricates the
  next one.
- [ ] Server loss ends clients safely without host election.
- [ ] Mid-match joins receive explicit v1 rejection.
- [ ] No lobby/load/packet wait is infinite.

### 23.6 Security and operations

- [ ] Join allocation and replies are protected by cookies and rate/size
  limits.
- [ ] Unknown/stale/replayed/forged control or gameplay packets have no world
  side effect.
- [ ] Debug packet functionality is unavailable remotely.
- [ ] Local admin is typed, allow-listed, scheduled, and audited.
- [ ] Logs redact secrets/tokens and aggregate floods.
- [ ] Tick/network/digest/peer status is observable.
- [ ] Sanitizer, fuzz, hostile, impairment, overload, and soak gates pass.

### 23.7 Build and distribution

- [ ] Client and server build together cleanly.
- [ ] Final server target omits direct GTK, OpenGL/libepoxy, and SDL2_mixer
  linkage.
- [ ] Server version reports EC7Wolf `1.0-betaX`, ECWolf base lineage, and
  protocol compatibility accurately.
- [ ] Server package runs from its own directory with user-supplied data.
- [ ] Server package and version control contain no commercial Corridor 7
  files.
- [ ] Ordinary client package and startup test remain green.
- [ ] Operator documentation covers ports, data, config, service, shutdown,
  compatibility, limitations, and troubleshooting.

The feature is not complete if only a hidden window, SDL dummy driver, local
bot host, or packet relay passes. All applicable items above are part of the
requested dedicated server.

---

## 24. Decisions to make before coding each optional extension

The core architecture above is decided. These policy choices may be resolved
during their stated milestone without blocking D0/D1:

### 24.1 Legacy multiplayer migration

- Keep current P2P protocol as a selectable legacy mode while v2 matures; or
- move all listen/dedicated multiplayer to v2 at once.

**Recommendation:** retain legacy temporarily for regression comparison, but
make new menu/server sessions default to v2 once stable. Remove legacy only
after feature/rules/impairment parity.

### 24.2 Automatic input delay

- fixed server setting; or
- lobby measurement and server-selected common delay.

**Recommendation:** implement fixed validated delay first, add auto selection
after the hub latency/jitter metrics are trustworthy. Never allow clients to
silently choose different execution delays.

### 24.3 Missing command grace

- finalize strictly at the scheduled deadline with neutral input; or
- permit a small bounded server grace/catch-up period.

**Recommendation:** neutral-at-deadline for Internet mode, optional strict-
wait diagnostic mode. Measure playability before exposing knobs.

### 24.4 One-player matches

- allow for testing/bots; or
- require two humans by default.

**Recommendation:** engine permits one active slot, operator default
`minPlayers = 2`; bot-only/one-human tests use explicit config.

### 24.5 Password support

- defer entirely; or
- add a reviewed nonce-bound password proof.

**Recommendation:** do not ship plaintext/reversible custom password handling.
Direct IP without password is better than false security; add proof only with
an appropriate maintained primitive and tests.

### 24.6 Disconnect continuation

- v1 abort match; later remove slot or bot takeover.

**Recommendation:** ship canonical abort first. Add play-on only with an
explicit roster-change protocol and tested score/pawn policy.

### 24.7 Time limit and rotation policy

Current multiplayer has a frag limit but may not have a complete time-limit
rule. Decide whether a server time limit is a new gameplay feature or deferred.

**Recommendation:** do not bury a time-limit rule in networking. Implement it
as a deterministic `MatchRules` feature with its own tests, or omit it in v1.

### 24.8 Remote status/browser query

**Recommendation:** a minimal bounded unauthenticated query may be added after
the gameplay handshake, with amplification tests. Public master listing stays
out of scope.

### 24.9 IPv6

**Recommendation:** reserve address abstractions for it, deliver direct IPv4
first if SDL_net/current tooling makes that the bounded path, then add dual-
stack with independent tests.

---

## 25. AI-agent execution protocol

This section turns the engineering milestones into guardrails for an AI coding
agent. It supplements, not replaces, repository instructions and user
direction.

### 25.1 Before a milestone

1. Read the current `AGENTS.md`, this plan, the relevant completed multiplayer
   documentation, and the related bot-plan sections.
2. Inspect `git status` and current branch/HEAD. Treat pre-existing and
   untracked changes as user-owned.
3. Re-read the exact current source symbols; do not trust line numbers or this
   plan over changed code.
4. Run the milestone's baseline gates and save concise evidence.
5. State assumptions and the smallest milestone boundary before editing.
6. Do not start an optional later feature to work around a prerequisite.

### 25.2 During implementation

- Make one architecture change at a time and keep existing client behavior
  runnable.
- Prefer explicit semantic types and narrow APIs over booleans/indices with
  comments.
- Do not introduce an out-of-range `ConsolePlayer` sentinel.
- Do not add a dummy/invisible server pawn.
- Do not cast UDP bytes to new protocol structs.
- Do not initialize dummy video/audio to make a test pass.
- Do not consume render, camera, audio mixer, wall clock, pointer address, or
  unordered iteration in deterministic decisions/digests.
- Do not call world mutation from socket, signal, terminal, or UI callbacks;
  enqueue validated boundary actions.
- Preserve commercial files and unrelated worktree edits.
- Record external source provenance before copying anything; prefer original
  code.
- Add the failure/hostile test with the implementation, not as cleanup.
- Keep the server's absence from player count asserted continuously.

### 25.3 Evidence at milestone exit

Report:

- files/symbols changed and architectural outcome;
- commands/tests run and their results;
- server/client command-frame and digest evidence where applicable;
- no-display/no-audio/dependency evidence where applicable;
- any skipped platform/gate and exact reason;
- known limitations that remain within the milestone contract;
- working-tree status, distinguishing prior user changes;
- release/package startup results when required.

Do not mark a milestone done because it compiles or because one local client
connects.

### 25.4 Recommended parallel work packages

These may be delegated once interfaces are frozen:

- protocol codec/fuzzer and fixed vectors;
- session/roster audit and semantic loop conversion;
- headless startup/presentation-service audit;
- server clock/lifecycle/config/admin;
- digest expansion and deterministic fixtures;
- impairment/hostile/lifecycle test harness;
- CMake/dependency/package work;
- documentation/service examples.

Avoid parallel edits to `wl_net.cpp`, `wl_play.cpp`, or startup until ownership
and interfaces are agreed. Integrate and test each shared-boundary change
before both branches build on it.

### 25.5 Required review lenses

For every nontrivial patch, review separately for:

1. peer/slot/authority correctness;
2. deterministic sequence and simulation order;
3. hostile packet/length/source/state behavior;
4. no-local-player/no-presentation safety;
5. client/regression behavior;
6. resource/gameplay metadata parity;
7. failure, shutdown, and bounded-resource behavior;
8. license/data-distribution implications.

---

## 26. Primary references

### 26.1 EC7Wolf source and project documents

- [`docs/multiplayer.md`](multiplayer.md) — current human multiplayer plan,
  results, delay and test history
- [`docs/multiplayer-bots.md`](multiplayer-bots.md) — ordinary-slot bot plan
- [`src/wl_net.h`](../src/wl_net.h) and
  [`src/wl_net.cpp`](../src/wl_net.cpp) — current protocol, peer/player
  conflation, handshake, reliability, commands, timeout work
- [`src/wl_play.h`](../src/wl_play.h) and
  [`src/wl_play.cpp`](../src/wl_play.cpp) — `TicCmd_t`, local input,
  `ConsolePlayer`, client/simulation loop
- [`src/wl_main.cpp`](../src/wl_main.cpp) — startup, data/resource init,
  projection, net/client initialization
- [`src/wl_game.cpp`](../src/wl_game.cpp) — level and presentation-driven game
  lifecycle
- [`src/wl_agent.cpp`](../src/wl_agent.cpp) and
  [`src/g_shared/a_playerpawn.cpp`](../src/g_shared/a_playerpawn.cpp) — player
  simulation, damage/death/frag/respawn, presentation coupling
- [`src/gamemap.cpp`](../src/gamemap.cpp),
  [`src/gamemap_planes.cpp`](../src/gamemap_planes.cpp), and
  [`src/id_ca.cpp`](../src/id_ca.cpp) — map/resource metadata and visibility
- [`src/thinker.h`](../src/thinker.h), [`src/thinker.cpp`](../src/thinker.cpp),
  and [`src/lnspec.cpp`](../src/lnspec.cpp) — thinker-category order, GC
  cadence, WORLD map machinery, and presentation-coupled sound sequences
- [`src/g_shared/a_keys.cpp`](../src/g_shared/a_keys.cpp) — gameplay
  `LOCKDEFS`/key-group initialization versus failed-use presentation
- [`src/id_sd.cpp`](../src/id_sd.cpp), [`src/sndinfo.cpp`](../src/sndinfo.cpp),
  and [`src/sndseq.cpp`](../src/sndseq.cpp) — sound data/output split
- [`src/m_random.h`](../src/m_random.h), [`src/m_random.cpp`](../src/m_random.cpp),
  and [`src/textures/animations.cpp`](../src/textures/animations.cpp) —
  gameplay/presentation RNG distinction and render-paced `AnimatePics`
- [`src/actordef.h`](../src/actordef.h) and
  [`src/thingdef/thingdef.h`](../src/thingdef/thingdef.h) — global native-class
  registration that build-library splitting must preserve
- [`src/version.h`](../src/version.h) and
  [`wadsrc/CMakeLists.txt`](../wadsrc/CMakeLists.txt) — authoritative
  `ec7wolf.pk3` artifact name
- [`src/CMakeLists.txt`](../src/CMakeLists.txt) — monolithic client target and
  dependencies
- [`tools/test_multiplayer_arenas.sh`](../tools/test_multiplayer_arenas.sh) —
  real Corridor 7 arena set (`MAP51`–`MAP57`, `MAP60`)
- [`tools/package_corridor7_release.sh`](../tools/package_corridor7_release.sh)
  — current client packaging and commercial Corridor 7 filename set
- [`tools/test_multiplayer_loopback.sh`](../tools/test_multiplayer_loopback.sh),
  [`tools/test_multiplayer_latency.sh`](../tools/test_multiplayer_latency.sh),
  and related gates — existing deterministic/network harness

### 26.2 GZDoom references

Snapshot reviewed: GZDoom master commit
[`c26ce2e`](https://github.com/ZDoom/gzdoom/tree/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7),
10 August 2026.

- [network modes](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/common/engine/i_net.h#L38-L42)
- [network command-line initialization](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/common/engine/i_net.cpp#L1270-L1321)
- [host includes itself as a player](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/common/engine/i_net.cpp#L976-L1035)
- [packet-server command hub](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_net.cpp#L1546-L1785)
- [all peers still run game tics](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_net.cpp#L2170-L2317)
- [ordinary display loop](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_main.cpp#L1236-L1278)
- [graphics initialization remains on host path](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/d_main.cpp#L3286-L3452)
- [single executable target](https://github.com/ZDoom/gzdoom/blob/c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/src/CMakeLists.txt#L1267-L1282)

### 26.3 Zandronum references

Snapshot reviewed: Zandronum master commit
[`bdd0f7b`](https://github.com/TorrSamaho/zandronum/tree/bdd0f7beb43d9786cc13502395f60aa84d34e28d).

- [runtime server state](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/network.h#L267-L282)
- [server has no console player](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/network.cpp#L1572-L1584)
- [server runtime dispatch](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/d_main.cpp#L1275-L1363)
- [server fixed-tic/network/admin loop](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sv_main.cpp#L703-L942)
- [server construction and clients/RCON](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sv_main.cpp#L487-L615)
- [headless POSIX host initialization](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sdl/i_main.cpp#L273-L303)
- [server-only CMake option](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/CMakeLists.txt#L188-L202)
- [server-only CI/package matrix](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/.github/workflows/ci-linux.yml#L16-L76)
- [Zandronum license](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/LICENSE.txt)

---

## Appendix A — Canonical flow summaries

### A.1 Dedicated startup

```text
server executable entry
  -> parse role/config/data paths
  -> install signals and logging
  -> load common resource/gameplay metadata
  -> initialize deterministic tables/RNG
  -> validate rotation/rules/capacity
  -> open UDP authority transport
  -> LobbyOpen + readiness log
  -> poll network/admin without any window/audio/input
```

### A.2 Client admission

```text
ClientHello
  -> transcript-bound stateless ServerChallenge cookie
  -> ClientJoin + transcript/compatibility/password proof
  -> validate/rate-limit/allocate PeerId
  -> duplicate identical Join reuses that allocation
  -> assign one Human PlayerSlot
  -> ServerWelcome + lobby snapshot
  -> lobby updates/ready
```

### A.3 Match start

```text
authority locks roster
  -> choose map/rules/seed/D/P/match ID/successor input epoch
  -> reliable MatchManifest
  -> every node InitializeMatchWorld(manifest)
  -> clients send MatchReady(manifest hash, baseline digest)
  -> authority ready barrier
  -> reliable BeginMatch(parent epoch 0, successor, first sequence, D, P,
                         bootstrap hash)
  -> each remote client samples/fixes command[start+D] in BeginAck;
     listen authority uses local EpochPrime
  -> semantic remote-ACK/all-prime barrier; authority caches bot prime[start+D]
  -> promote successor and arm deadline
  -> sequence-driven bootstrap/canonical-frame emission
  -> Running
```

### A.4 One running tic

```text
completed world S; next executable E=S+1; future target F=S+D+1
clients submit owned human intent for F
authority checks stop/derivable-lead feasibility
authority builds/stores bot intent for F from world S exactly once, or reuses it
authority validates and finalizes all slots for current E
  -> missing human becomes tested neutral command
authority commits before/stop-after event bodies in CanonicalInputFrame[E]
all nodes install identical frame
all nodes RunSimulationTic(E)
all nodes compute digest
clients periodically report digest
client playout uses contiguous 70 Hz queue around target P
authority compares health; post-tic precedence may stop after E
natural or scheduled terminal -> ConfirmTerminal/TerminalAck
  -> ResultsCommit/ResultsCommitAck(hashOfResultsCommit) barrier
  -> Results timer/rotation eligible
```

### A.5 Human loss in v1

```text
missing/leave detected by authority
  -> if Running with no stop: neutral commands while pending
       -> AbortMatch preannounced as StopAfterTic(N)
       -> semantic ACK; canonical frame N commits it
       -> all nodes simulate through N
  -> if Running with an unresolved stop: retain its type/N;
       update survivor ACK set, neutralize lost slot through N,
       attach disconnect metadata, and commit only that boundary
  -> if Paused/ResumeBarrier: retire successor and keep frozen completed N;
       do not execute N+1
  -> select terminal by normal precedence:
       natural outcome at N wins; retained abort/shutdown keeps its kind/reason;
       otherwise kind/reason = disconnect; always attach disconnect metadata
  -> ConfirmTerminal(N, selected kind/reason/metadata) / TerminalAck
  -> ResultsCommit / ResultsCommitAck(hashOfResultsCommit) barrier
  -> Results timer/rotation eligible
  -> close peer / lobby or next policy
```

### A.6 Pause and resume

```text
authority preannounces PauseAfter(N, controlEpoch)
  -> semantic ACK; frame N commits StopAfterTic
  -> all nodes complete N and freeze old scheduler/input epoch
  -> discard old commands beyond N; transport/UI/liveness continue
  -> reliable Resume(old epoch, new epoch, N+1, D)
  -> each remote client samples/fixes command[N+D+1] in ResumeAck;
     listen authority uses local EpochPrime
  -> remote-ACK/all-prime barrier; authority caches bot prime[N+D+1]
  -> promote successor; fresh authority/client deadlines; D neutral frames
  -> exactly one canonical N+1; Running
```

### A.7 Graceful shutdown

```text
signal/local quit
  -> stop accepting joins
  -> schedule/announce shutdown or match abort
  -> bounded reliable send period
  -> close peers/socket
  -> flush diagnostics/logs
  -> destroy server services/common runtime
  -> exit status
```

---

## Appendix B — Review questions for each design change

Before accepting a change, answer all applicable questions with code/tests:

1. Is this index a peer or a player slot? Can the type system tell?
2. Does it work when the authority has no local player and slot 0 is remote?
3. Does it work at 11 players plus the server process?
4. Who is permitted to send this message, in which state, for which slot?
5. Are lengths/counts validated before byte conversion, loops, or allocation?
6. Is the action applied immediately or at a canonical sequence?
7. Can arrival order, wall clock, frame rate, platform, pointer order, or local
   UI change deterministic outcome?
8. Does a client apply anything before authority finalization?
9. What happens on loss, duplicate, replay, reorder, timeout, and wrap?
10. Does the server path touch a camera, `ConsolePlayer`, HUD, screen, input, or
    audio output?
11. Does removing presentation change resource metadata, RNG, collision, LOS,
    spawn, or scores?
12. Is the queue/history/cache bounded and observable?
13. Can an unknown source amplify traffic, allocate state, flood logs, or
    trigger a control action?
14. How is the behavior reproduced from seed, manifest, canonical commands,
    and digests?
15. Does packaging preserve license notices and exclude commercial data?

---

## Appendix C — Why the quick alternatives do not meet the request

### Hidden graphical host

Running ordinary `--host` under Xvfb or SDL dummy video may be useful in CI,
but the process remains player 0, spawns, appears in score, and consumes a
slot. It also retains graphical/audio/input initialization and dependencies.

### Invisible/invulnerable server pawn

This consumes a slot and changes spawn-distance selection, collision/target
scans, scoreboard/team counts, frag-limit logic, map visibility, and possibly
sound/trigger behavior. Hiding it in the HUD does not remove it from the
simulation.

### Spectator server pawn

A spectator is still a client/view concept and still requires a player/special
slot in the current architecture. The requested server is an authority process,
not a spectator.

### Bot in host slot 0

This gives a headless automated participant, useful for tests, but it is an AI
opponent and score/spawn slot. It does not provide eleven usable positions to
eleven clients.

### Dumb UDP relay

A relay can remove the full mesh and consume no slot, but without the playsim
it cannot author bots, verify digests against its own world, enforce canonical
scores/outcomes, or distinguish a valid state from mutually consistent client
lies. It is a transport experiment, not the selected dedicated game server.

### Full Zandronum protocol transplant

It would require snapshot/state replication for Corridor 7 actors, map state,
inventory, weapons, hazards, joins, prediction, and compatibility, plus a broad
license/provenance review. The existing command boundary already solves the
first dedicated version more directly.

---

## Appendix D — Final feasibility statement

The feature is feasible because EC7Wolf already has three of the four hardest
ingredients:

1. a fixed-rate deterministic simulation;
2. a complete per-player command boundary;
3. normal multi-player-slot spawn, movement, weapon, damage, death, and frag
   rules;
4. **missing today:** an identity/protocol/runtime separation that permits the
   authority to exist without a player or presentation.

The work is larger than adding a GZDoom flag because current GZDoom does not in
fact contain the requested zero-slot mode, and EC7Wolf's own host is tightly
bound to `ConsolePlayer == 0`. Zandronum proves that a ZDoom-family codebase can
support a real server-only process, but EC7Wolf should reach it through its own
smaller deterministic command architecture.

The correct implementation path is therefore:

> make authority independent of player 0; replace the peer mesh with a
> versioned canonical command hub; extract one headless simulation tic; add a
> separate no-presentation server lifecycle and binary; then harden, package,
> and integrate bots on that shared authority.
