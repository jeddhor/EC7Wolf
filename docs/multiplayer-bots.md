# EC7Wolf multiplayer bot development plan

**Status:** engineering plan; no bot implementation exists yet

**Scope:** Corridor 7 free-for-all deathmatch, with any non-spectator player
slot controlled by either one human or one AI controller

**Source snapshot reviewed:** EC7Wolf multiplayer branch, 21 August 2026

**Primary external reference:** Zandronum's Skulltag-derived bot system, with
Quake III Arena used as a second architectural reference

This document is deliberately more detailed than an ordinary feature plan. It
defines the fairness contract, the network and player-roster work that must
precede AI, the proposed bot architecture, the implementation sequence, the
tests, and the failure conditions. It is intended to be reviewed and corrected
before code is written.

For review, the document is organized into three blocks:

- Sections 1–7 define scope, source seams, architecture, networking, and the
  command-only fairness boundary.
- Sections 8–15 define navigation, perception, decisions, movement, combat,
  skill, user experience, diagnostics, and performance.
- Sections 16–22 define tests, milestones, source work, risks, completion
  criteria, decisions, and primary references; the appendices provide compact
  operational summaries.

The central design rule is simple:

> A bot is a controller for a normal multiplayer player slot. It may observe a
> deliberately limited view of the game and produce a `TicCmd_t`. It may not
> move an actor, turn an actor, activate a trigger, select a weapon, pick up an
> item, inflict damage, respawn, or alter game state by any other path.

If this boundary is kept, the existing player code remains the authority for
movement, collision, doors, pickups, ammunition, weapon timing, damage, death,
frags, and respawning. That is the strongest and most auditable meaning of
"subject to all the same rules as a human."

---

## 1. Executive decisions

These are the recommended decisions around which the rest of the plan is
written.

1. **Bots occupy ordinary player slots.** `players[slot]`, the configured
   `APlayerPawn` class, normal spawn selection, and normal frag accounting are
   used without a bot-specific pawn class.

2. **Bots produce only ordinary player commands.** Movement and yaw are
   expressed with `controlx`, `controly`, and `controlstrafe`; actions are
   expressed with the same button fields used by a human. The bot never writes
   actor coordinates or angle directly.

3. **The match host/arbiter is the sole bot-brain authority.** It evaluates all
   bot brains at a fixed simulation-tic boundary and sends their final commands
   as part of the lockstep input stream. Other peers do not run the bot AI.
   They simulate the resulting pawns normally.

4. **Network peers and occupied game slots become separate concepts before a
   bot is added.** The present `numPlayers` assumption means one network address
   equals one player slot. Raising it for bots would make the host wait forever
   for nonexistent sockets.

5. **The first AI is a small, explicit, inspectable C++ controller.** It uses a
   hierarchical state machine plus utility scoring. It does not begin with a
   scripting VM, machine-learning model, behavior-tree framework, or imported
   Doom/Quake bot source.

6. **Navigation is generated from Corridor 7's runtime tile map.** It uses
   typed edges for walking, using doors, and transporters, and it validates
   motion against the same player-radius/collision rules that actual movement
   uses.

7. **Tactical code never receives unrestricted world access.** A perception
   adapter supplies visible observations, audible events, own-player state,
   static map knowledge, and decaying memories. This prevents accidental
   wallhacks and omniscient item selection.

8. **Human-likeness is created by limited information and limited motor
   control, not just random misses.** Reaction delay, perception cadence,
   bounded turn rate and acceleration, delayed tracking, correlated aim error,
   fire hesitation, route imperfection, and decision commitment all matter.

9. **Difficulty never changes the rules.** It may change perception quality,
   reaction time, aim stability, movement competence, and tactical judgment.
   It may not change health, damage, ammunition, inventory, collision radius,
   movement speed, pickup rights, respawn timing, or weapon timing.

10. **Fixed seeds and deep diagnostics precede tuning.** Every bot decision,
    route, perceived contact, aim error, and output command must be explainable
    in a trace. "It sometimes gets stuck" is not an actionable bug report.

11. **The first supported ruleset is free-for-all deathmatch.** The design must
    not preclude teams, alternate player classes, spectators, or dedicated
    servers, but team tactics and cooperative monster AI are not part of this
    project.

12. **Roster changes are initially match-boundary operations.** Add/remove or
    human/bot replacement during a live lockstep match is deferred until a
    synchronized roster-change protocol exists.

---

## 2. Scope, terminology, and non-goals

### 2.1 Required player experience

The completed feature must support all of the following:

- A local human starts a deathmatch and fills one or more remaining positions
  with bots without requiring a network connection.
- A network host starts a mixed match containing remote humans and bots.
- A bot can occupy any roster position not reserved for the local interactive
  human. The data model must also permit slot 0 to be a bot in headless bot-only
  tests and a future dedicated-server mode.
- A match can contain one human and one bot, several humans and one bot, one
  human and all remaining positions as bots, or bots fighting only bots in a
  developer soak test.
- Bots appear in the ordinary score/frags presentation, with an unambiguous
  `[BOT]` marker or equivalent visual treatment.
- Bots use the selected ordinary player class, normal starts, ordinary
  inventory, normal weapons, normal damage, and normal respawn path.
- The host can choose a bot count and a human-readable skill level before the
  match.
- The game remains deterministic at the playsim level on every peer because
  every peer consumes the same finalized command for every occupied slot.

In this document, **slot** means an index into the ordinary player arrays and
the corresponding simulated pawn. **Peer** or **network node** means a human
game instance with a UDP address. **Controller** means the source of commands
for a slot. A controller is either a local human, a remote human, or a bot owned
by the host.

"Human-only" in the original multiplayer description is treated here as
"human-controlled player slots," not as a new monster or alien NPC mode. A bot
is a simulated player controller. It is not a single-player enemy actor.

### 2.2 Explicit non-goals for the first bot release

- Cooperative bots, monsters controlled as players, single-player companion
  AI, capture-the-flag, team tactics, or objective modes.
- Learning during play, neural networks, external AI services, or an LLM in the
  game loop.
- Voice or text chat generation.
- Perfect imitation of a particular human player.
- Navigation through arbitrary mod mechanics for which no traversal metadata
  exists.
- Live human-to-bot takeover, bot-to-human takeover, or late bot joins.
- Host migration. If the authoritative host leaves, the match ends normally.
- A general-purpose bot scripting language in the first implementation.
- Reusing monster chase code as player locomotion.
- Giving a high-skill bot zero reaction delay, exact aim, unlimited turning, or
  knowledge a human could not have.

### 2.3 Meaning of "the same rules"

The equality requirement is stronger than giving bots approximately equivalent
statistics. It establishes these invariants:

| Property | Required implementation |
| --- | --- |
| Spawn and respawn | Existing `CheckSpawnPlayer`, `SpawnPlayer`, `Reborn`, and `DeathTick` paths |
| Movement | `TicCmd_t` into `ControlMovement`, `Thrust`, `ClipMove`, and `TryMove` |
| Turning | Bounded `controlx`; never an actor-angle assignment |
| Doors and switches | Face the activation side and pulse `bt_use`; never invoke a line special directly |
| Weapon choice | Normal slot/next/previous input and normal `PendingWeapon` handling |
| Firing | `bt_attack`/alternate/reload through normal weapon-ready states |
| Ammunition and energy | Existing inventory consumption and regeneration only |
| Pickups | Physical overlap and ordinary `TryPickup` logic |
| Damage | Existing weapon/projectile/explosion and `TakeDamage` paths only |
| Collision | Same pawn radius, blockers, wall sliding, triggers, and hazards |
| Frags | Existing death attribution; no AI-owned score path |
| Network delay | Bot commands pass through the same delayed-command schedule as human commands |
| Simulation rate | At most one finalized command per occupied slot per game tic |

The bot is permitted to know its own exact health, armor, inventory, ammo,
ready weapon, and status effects because the human HUD exposes the useful
equivalent. It is not permitted to inspect an unseen opponent's health,
inventory, exact location, current command, or private weapon state.

---

## 3. Current EC7Wolf seams and prerequisites

This section records the source architecture found during planning. Symbol
names are more important than line numbers because the multiplayer branch is
actively changing.

### 3.1 The command seam already exists

[`src/wl_play.h`](../src/wl_play.h) defines `TicCmd_t` and
`control[MAXPLAYERS]`. A command contains forward/back movement, strafe,
turning, pan fields, present button state, and held button state.

[`PollControls`](../src/wl_play.cpp) builds only the local human command and
then calls `Net::PollControls`. [`APlayerPawn::Tick`](../src/g_shared/a_playerpawn.cpp)
reads `control[player->GetPlayerNum()]`, handles use, weapon selection, attack,
reload, zoom, and then calls [`ControlMovement`](../src/wl_agent.cpp).

This produces the desired flow:

```text
controller intent
      |
      v
finalized TicCmd_t for one slot
      |
      v
APlayerPawn::Tick
      |
      +--> Cmd_Use / weapon state machine / inventory
      |
      +--> ControlMovement --> Thrust --> ClipMove/TryMove
      |
      v
ordinary collision, triggers, damage, death, frags, respawn
```

The bot hook must run after the host has a stable start-of-tic world state and
before any player thinker consumes that tic's commands. Commands for all bot
slots must be generated before any pawn is ticked; otherwise a later bot could
observe the same-tic movement of an earlier player and gain a slot-order
advantage.

Important command details:

- Normal command-axis range is documented as `-100..100`; keyboard movement
  ordinarily uses magnitudes `BASEMOVE`/`RUNMOVE` (`35`/`70`). The AI output
  boundary must clamp every axis even if downstream movement also clamps some
  of them.
- Yaw is not clamped in `ControlMovement`. An unrestricted bot command could
  turn instantly, so a profile-specific human envelope is mandatory.
- Movement buttons such as `bt_moveforward` are converted into axes during
  local input polling. Setting the button alone does not move a bot; its
  command builder must emit axes.
- `buttonheld` is semantically important. Use is edge-triggered, as are several
  weapon and equipment actions. Common command-installation code should derive
  held state from the previous applied command instead of trusting a command
  producer or remote packet to get it right.
- A bot command must whitelist gameplay controls. It must never emit escape,
  pause, automap, status-bar, menu, or other local UI buttons.

### 3.2 Normal lifecycle is already suitable

[`player_t`](../src/wl_agent.h) contains the pawn, state, health, frags,
weapons, inventory-facing state, and respawn timing. The normal level-start
path creates every active player through `CheckSpawnPlayer` and `SpawnPlayer`.
The death path records frags in `player_t::TakeDamage`; `DeathTick` supplies
the use-button/timeout respawn path; `Reborn` grants the normal starting and
battle inventory.

The plan must keep those functions controller-agnostic. A bot-specific spawn,
inventory, damage, or respawn function would be a design failure.

### 3.3 The roster/network assumption is the first blocker

[`Net::NetInit`](../src/wl_net.h) has one `numPlayers` field. In
[`src/wl_net.cpp`](../src/wl_net.cpp), that count currently controls all of the
following:

- how many human clients the host waits to connect;
- how many peer addresses are placed in the start packet;
- which player number a joining instance receives;
- how many class-choice packets `Net::NewGame` exchanges;
- how many per-tic packets must exist before lockstep advances;
- how the `Client[]` command buffers are indexed; and
- how many ordinary player slots the playsim spawns and iterates.

Consequently, setting `numPlayers = humans + bots` without redesign would
make both the startup handshake and every tic wait for a network peer for each
bot. Creating fake UDP clients for bots would compound the error and make
offline play unnecessarily depend on networking.

The roster/peer split in section 6 is therefore milestone B1, not a later
optimization.

### 3.4 Gameplay rules must stop depending on transport mode

Several current code paths use `MODE_SinglePlayer` versus network mode as a
proxy for rules such as respawning, item persistence, pausing, menus, sound,
and saving. A one-human-plus-bots match can be a multiplayer deathmatch in
gameplay terms while having no remote network peer.

Introduce explicit semantic queries and audit their uses:

- `Session::IsDeathmatch()`
- `Session::IsMultiplayerGameplay()`
- `Session::AllowsRespawn()`
- `Session::RespawnsItems()`
- `Session::NoMonsters()`
- `Net::IsNetworked()`
- `Net::IsHost()`

Transport code should ask whether it is networked. Damage, death, inventory,
HUD, pause, and match-flow code should ask what rules the session uses.

The audit must include at least death/respawn in `a_playerpawn.cpp`, player
tick behavior in `wl_play.cpp`, weapon/key persistence in the inventory code,
automap pausing, multiplayer fades and positional sound, save/high-score/menu
gating, and all uses of `Net::InitVars.mode` outside transport code.

### 3.5 Human multiplayer prerequisites

Bots should not be used to conceal unfinished human deathmatch behavior. Before
bot combat is judged, the following human-only work must be stable:

- all eight real arenas load and have valid separated starts;
- player-versus-player damage and frag attribution are covered by tests;
- the intended match-end rule, frag/time limit, ties, and restart behavior are
  defined;
- the scoreboard can identify every occupied slot;
- disconnect and timeout behavior do not leave lockstep permanently blocked;
- the packet protocol has explicit compatibility/version validation; and
- player-owned plasma/projectile contact behaves correctly against other
  players.

The arena and roster foundations can be developed in parallel, but tuning a
bot around known-broken combat would bake workarounds into the AI.

### 3.6 Known adjacent defects to resolve or explicitly constrain

The source review identified several issues that are not themselves AI but can
invalidate bot behavior or determinism:

- Network mouse look currently changes only the local pawn pitch while the
  command packet does not carry pitch. Either synchronize pitch input or
  disable it in network deathmatch before any pitch-sensitive feature is
  claimed.
- The current `StartPacket` allocates/serializes `numPlayers - 1` trailing
  client entries, but `StartPacket::ByteSwap` iterates `numPlayers` entries.
  `CheckPacketType` also calls that swap after checking only the fixed header,
  before validating trailing length/count. This is an existing out-of-bounds
  startup-packet defect and must be fixed/tested before the handshake is
  extended.
- The current packet shape has no player-slot identifier; the sender's address
  implicitly identifies one slot. Bot bundles need explicit ownership.
- Flexible/trailing data in startup packets must be length-checked before a
  count controls reads.
- `--host` player counts must be parsed and validated before narrowing to a
  byte or indexing fixed arrays.
- Legacy demo recording is single-player and omits much of `TicCmd_t`; it is
  not a usable multiplayer-bot replay mechanism.
- The current checksum is valuable but does not include commands, bot state,
  inventory, frags, doors, or the complete simulation state.
- Network arenas include ordinary exit switches. Bot goal and use logic must
  never activate them in battle, and the battle rules should ideally suppress
  them at the gameplay layer.
- `player_t::Reborn` and related player paths call the global
  `CalcProjection(mo->radius)` for whichever slot is being processed. If player
  classes can have different radii, spawning/rebirthing a remote player or bot
  can overwrite local-console projection. Make projection explicitly
  console-camera-specific, or constrain v1 to equal-radius classes until that
  is fixed.
- `player_t::TakeDamage` has status-bar update/draw calls that are not all
  guarded by `GetPlayerNum() == ConsolePlayer`. Audit damage, pickup, chamber,
  face/message, and similar presentation calls so offscreen bot/remote events
  cannot alter the local HUD.

---

## 4. What to take from existing bot systems

### 4.1 Zandronum

Zandronum is the most immediately relevant source because its bots descend
from a Doom-family deathmatch bot system and it remains a working multiplayer
engine.

Useful architectural lessons:

- `CSkullBot` is attached to an ordinary player slot.
- The brain clears/builds a command each tick and transfers desired movement
  and buttons into the normal player command.
- The authoritative server runs the bot brain; clients know that the player is
  a bot but do not independently make its decisions.
- Bot traits are separated into axes such as accuracy, anticipation, evasion,
  intellect, reaction time, and perception.
- Events can be queued and exposed after a skill-dependent reaction delay.
- Its A* code builds runtime navigation nodes, distinguishes special traversal,
  tries direct routes, smooths paths only after traversal tests, limits search
  work, detects obstruction, and replans.
- Its console/debug facilities expose state, events, commands, paths, costs,
  obstructions, and timing.

Parts not to reproduce:

- Zandronum's custom bot bytecode VM and compiled behavior lumps add machinery
  without solving a Corridor 7 need; the original script toolchain is not a
  sensible dependency for a new implementation.
- Its full Doom geometry/path probing and per-path memory structures do not fit
  Corridor 7's compact tile map.
- Its aiming path can directly change actor angles. EC7Wolf's stricter fairness
  contract requires a turn command instead.
- Some sensory/item queries expose more global world state than a human should
  receive, and its hearing implementation is incomplete.
- Its highest skill settings include effectively perfect perception or aim.
  EC7Wolf must retain a fairness ceiling.

The pinned source references used in this review are collected in section 22.

### 4.2 Quake III Arena

Quake III supplies several particularly strong patterns:

- abstract bot actions are converted into a normal `usercmd_t`;
- high-level thinking runs less often than immediate movement/view updates;
- expensive bot thinks are staggered across frames;
- turning uses maximum angular speed, damping, and overreaction rather than a
  snap to the ideal angle;
- perception, long-term goals, nearby goals, navigation, battle movement,
  weapon choice, aim, and attack gating are distinct layers; and
- personality and skill are data, not altered player rules.

Its Area Awareness System is much larger and more three-dimensional than this
project needs. The separation of responsibilities is useful; the subsystem is
not a transplant candidate.

### 4.3 Quake II ACEBot

ACEBot demonstrates the same important concept: construct a `usercmd_t` and
run the ordinary client-think path. Its waypoint and utility ideas are useful
as history, but its aim is too exact for this requirement and its source carries
additional restrictions that make copying inappropriate. No ACEBot code should
enter EC7Wolf.

### 4.4 Provenance and licensing rule

The implementation should be original EC7Wolf code informed by these public
architectural ideas.

- Do not copy Zandronum's compiled bot scripts, chat/persona data, names, or
  other creative assets.
- Zandronum bot files retain file-level Skulltag/Zandronum notices and a
  four-condition license. The project describes it as GPL-compatible, but any
  copied or closely adapted code still needs a file-by-file notice and source-
  distribution audit.
- Quake III's released source is GPL-2.0-or-later; provenance must still be
  recorded for any adaptation.
- ACEBot's additional "All Rights Reserved" and sale restrictions make its
  source unsuitable for copying into this project.
- If any source is copied or closely translated despite the original-
  implementation recommendation, record the upstream repository, pinned
  commit, exact file and lines, retained notice, adaptation description, and
  distribution obligations in the same change. Update the project's copyright
  documentation before release.

---

## 5. Proposed subsystem architecture

The proposed layers are intentionally narrow:

```text
                         HOST / ARBITER ONLY

  start-of-tic world
          |
          v
  BotSensorAdapter ----> BotObservation + remembered contacts
          |                              |
          |                              v
          |                     BotDecision / utility
          |                              |
          |                              v
          +--------------------> BotNavigation
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
              +--------------------------+--------------------+
              | lockstep command history / network broadcast |
              +--------------------------+--------------------+
                                         |
                    ALL PEERS            v
                                ordinary APlayerPawn::Tick
```

### 5.1 Suggested source layout

Names may be adjusted to match project conventions, but responsibilities should
remain separate:

```text
src/g_session.h/.cpp       session rules, roster, slot/controller ownership
src/g_bot.h/.cpp           BotManager, lifecycle, brain state, command output
src/g_botperception.h/.cpp observations, hearing events, memory
src/g_botnav.h/.cpp        map graph, A*, route following, stuck recovery
src/g_botcombat.h/.cpp     target choice, weapon utility, aim/fire controller
src/g_botprofile.h/.cpp    profiles, validation, private PRNG setup
src/g_botdebug.h/.cpp      traces, metrics, developer overlays/commands
```

If fewer translation units are preferred initially, combine them without
combining their interfaces. New sources must be added to the explicit lists in
`src/CMakeLists.txt`.

### 5.2 Core object model

The following is conceptual, not a mandate for exact C++ spelling:

```cpp
enum class ControllerKind : uint8_t
{
    Empty,
    Human,
    Bot
};

struct PlayerSlotInfo
{
    ControllerKind kind;
    uint8_t slot;
    uint8_t ownerPeer;      // host for every Bot; invalid for Empty
    FName playerClass;
    FString displayName;
    uint16_t profileId;
    uint64_t botSeed;
};

struct MatchRoster
{
    uint8_t activeSlotCount;
    uint8_t peerCount;
    PlayerSlotInfo slots[MAXPLAYERS];
};
```

`ControllerKind` is canonical match data and therefore cannot say `LocalHuman`
or `RemoteHuman`: the same human is local on one peer and remote everywhere
else. Serialize `Human` plus `ownerPeer`; each process derives local/remote as
`ownerPeer == localPeerId`. Bot ownership is always the host in v1.

Version 1 should keep occupied slots contiguous even though each entry has an
explicit identity. That minimizes the many existing `[0, playerCount)` gameplay
loops. Empty holes and live roster mutation can be added later.

`BotState` belongs to `BotManager`, keyed by stable slot, not in the pawn's
gameplay statistics:

```text
identity/profile/private RNG streams
high-level state and committed goal
visible contacts and decaying memories
current route and typed transition state
aim observation history and motor state
weapon preference/cadence state
stuck/progress/recovery state
next scheduled sense/think/path updates
debug counters and last command
```

Targets that are players should be stored by slot, never raw pointer identity.
For non-player goals, prefer a stable map/spawn serial plus class and position.
Do not let a bot reference keep an actor alive through garbage collection. If
the engine needs a stable weak actor identity, add one deliberately and test
its serialization/invalidation semantics.

### 5.3 World-access boundary

Only `BotSensorAdapter` and the low-level local collision/navigation query may
read the game world. Decision, goal, combat, and aim code consume immutable
observation structures.

Allowed inputs:

- exact own pawn status, inventory, ammo, weapon, ready flags, and command;
- game rules, public scores, time/frag limit, and spawn/death state;
- static map geometry/potential topology, door and transporter locations, and
  learned pickup spawn locations;
- players presently inside bot FOV with gameplay LOS and visibility rules;
- gameplay-generated audible events within an appropriate hearing model;
- projectiles, hazards, and items presently perceived;
- remembered facts with timestamps and uncertainty; and
- short-range side-effect-free collision probes used only for locomotion.

Forbidden inputs:

- an unseen enemy's current coordinates, velocity, health, armor, inventory,
  weapon cooldown, command, queued future network command, or target;
- global item active/inactive state for an unseen pickup;
- current unseen door, forcefield, removable-wall, mine, laser, or other dynamic
  topology/hazard state;
- exact spawn choice before the ordinary engine spawns someone;
- future random values or weapon hit results;
- renderer visibility for `ConsolePlayer` or camera-dependent render state;
- pointer/order artifacts from global actor iteration; and
- calls that mutate actors, triggers, inventory, damage, or score.

Static map knowledge is considered fair for the initial "trained arena" bots,
just as experienced humans memorize a map. Dynamic state is not. A future
profile may deliberately start with partial map knowledge, but it is not needed
to satisfy fairness.

### 5.4 Update rates

Not every layer should do expensive work at 70 Hz.

| Layer | Initial cadence | Notes |
| --- | --- | --- |
| Command finalization and immediate collision steering | Every tic | Always emits one complete command |
| Aim motor integration | Every tic | Rate/acceleration limits require continuous integration |
| Immediate hazard/projectile response | Every 1–2 tics | Still subject to perception and reaction limits |
| Vision/perception refresh | Profile-dependent, roughly 7–35 Hz | Stagger across bots |
| Tactical state/utility evaluation | Roughly 5–10 Hz | Also on material events |
| New A* route | On goal/path invalidation | Incremental/budgeted when necessary |
| Item/long-term goal reconsideration | Roughly 2–5 Hz | Commitment prevents thrashing |
| Debug metric aggregation | 1–5 Hz | Trace raw events separately if enabled |

Schedule expensive updates by `(tic + slotOffset) % interval` so all bots do
not search on the same tic. A critical event may request reconsideration, but a
global per-tic budget still applies.

---

## 6. Session roster and network protocol

This is the largest non-AI prerequisite and must be implemented/tested as its
own milestone.

### 6.1 Separate counts and mappings

Replace the ambiguous concept with explicit values:

- `activeSlotCount`: all simulated humans and bots;
- `peerCount`: all connected game instances, including the host;
- `peerToHumanSlot[peer]`: the one human slot controlled by that peer in the
  current engine model;
- `slot.ownerPeer`: the peer authorized to submit the slot's command; and
- `slot.kind`: canonical human, bot, or empty kind; local/remote human is
  derived per process from ownership.

The host owns its local human slot and all bot slots. A remote peer owns only
its assigned human slot. Future split-screen or multi-seat clients can extend
the ownership mapping without altering player identity.

Prefer renaming `numPlayers` at the compiler level instead of leaving its old
name with two meanings. Every old use must be classified:

| Use category | New bound/query |
| --- | --- |
| Spawn, player thinkers, actors, scores, HUD, GC, class assignment | Active slots |
| Socket addresses, joins, acknowledgements, disconnects, reliable exchange | Peers |
| Per-tic command completeness | Required active-slot command mask |
| Local rendering/input | `ConsolePlayer`/local human slot |
| Bot brain iteration | Host-owned bot slots |

This audit should be mechanical and complete: search every `numPlayers`,
`Client[]`, `ConsolePlayer`, and transport-mode use, classify it in the change
description, and add a regression for the important result.

### 6.2 Host-authoritative bot commands

The recommended v1 model is:

1. The host runs the brain for every bot.
2. Each brain emits a final command for a future command sequence according to
   the match's input delay.
3. The host stores those commands in the same resend/history window as human
   input.
4. The host broadcasts a packet/bundle containing its owned slots: its human
   slot plus all bot slots.
5. Every peer waits until it has one valid command for every active slot for
   the tic being simulated.
6. Every peer copies those same commands into `control[slot]` and runs the
   ordinary playsim.

This treats bot decisions as external input. The private AI state does not have
to be bit-identical across machines because it does not exist on clients.
Only the resulting bounded command enters deterministic simulation.

The host is already trusted to author its own human input and match setup. A
malicious host could cheat regardless; the bot model does not expand trust in
a remote client.

### 6.3 Why not independently run each brain on every peer

A replicated-brain design is superficially attractive because it sends no bot
commands. It is not recommended for the first implementation.

It would require all of the following to remain identical across compilers,
architectures, builds, and future mods:

- perception iteration and tie-breaking;
- path-search ordering and incremental budgets;
- bot RNG state and every draw schedule;
- floating/fixed angle and utility calculations;
- stable identities for all dynamic actors;
- behavior-state transitions and event queues; and
- every future tuning/data change.

A divergence may remain invisible until a different bot command later changes
the world. It also makes demos dependent on re-running a historical AI version.
Host-authored commands cost modest bandwidth but sharply reduce that risk.

Keep replicated brains as an experimental optimization only after command
bandwidth is measured. If ever adopted, require byte-identical command traces
across supported platforms first; never silently mix authority models.

### 6.4 Packet shape

Do not extend the current address-implies-slot `TicCmdPacket` ad hoc. Introduce
an explicit, versioned command bundle. Conceptually:

```text
TicCmdBundle
    packet type
    protocol version
    session identifier
    command sequence
    owning peer identifier
    slot mask
    entry count
    repeated entries:
        slot identifier
        controlx / controly / controlstrafe
        supported gameplay button state
```

The exact encoding should remain compact. A slot mask with entries in ascending
slot order can avoid repeating slot IDs, but the decoder must still validate
that the count equals the bit count and every bit belongs to the sender.

Do not transmit `buttonheld` in the new protocol. Commands are installed in
sequence order, so each peer can derive it as the previous applied
`buttonstate` for that slot. This removes a redundant sender-controlled field
and guarantees identical edge semantics. Recordings may store the complete
installed `TicCmd_t` for convenience, but the canonical wire input contains the
present gameplay-button mask.

Required validation before storage:

- packet has the exact minimum/declared length;
- protocol and session IDs match;
- sequence is inside the accepted history/future window using wrap-safe
  comparisons;
- count and mask are internally consistent;
- each slot is active and owned by the claimed/sender peer;
- only the host packet may contain bot slots;
- axes are in the canonical integer range;
- unused/local UI button bits are clear;
- duplicate slot entries are rejected;
- duplicate packets are idempotent; and
- malformed input cannot index beyond `MAXPLAYERS` or history buffers.

One bundle per owning peer per sequence is preferable to one packet per bot.
At the current maximum of eleven slots, even a simple uncompressed command
format is modest compared with modern network capacity. Measure first; optimize
only if packet size or fragmentation warrants it.

### 6.5 Startup handshake and roster lock

The start protocol should follow this order:

1. Host chooses rules, arena, expected human peer count, slot count, bot slots,
   profiles, names/classes, and input delay.
2. Joining peers negotiate an explicit protocol/build/data compatibility
   version and are assigned reserved human slots.
3. Host validates `1 <= activeSlotCount <= MAXPLAYERS`, `1 <= peerCount <=
   activeSlotCount`, every ownership entry, unique names if required, class
   availability, and profile IDs.
4. Host chooses a session identifier, match seed, and per-bot seeds.
5. Host sends the complete immutable `MatchRoster` plus peer address/mapping,
   rules, map, class choices, seed, and delay.
6. Every peer validates exact packet length/counts and hashes the canonical
   roster/setup.
7. Every peer acknowledges the same roster hash.
8. Only then does map setup/spawning begin.

Bots do not participate in reliable startup acknowledgement. All ack/wait loops
iterate peers, not slots.

In v1, the roster is latched until the match or map ends. A disconnect follows
the existing timeout/end policy; it is not automatically replaced by a bot.

### 6.6 Input-delay semantics

If the agreed delay is `D`, a controller observes the current completed world
at sequence `T` and creates a command stamped for `T + D`. The initial window
uses the same neutral-command warm-up policy for humans and bots.

This means the configured network delay contributes to effective bot response
latency, just as the local human's physical input is delayed. Do not secretly
run bots after the delay buffer or give them a shorter path. Profile reaction
delay is additional cognitive/motor delay and should be calibrated with the
network delay visible in telemetry.

At the command-generation boundary:

```text
completed world T
  -> collect local human intent for T+D
  -> host senses/thinks all bots and builds commands for T+D
  -> emit owned-slot bundle for T+D
  -> drain/resend network packets
  -> gather all active-slot commands for current sequence
  -> install control[slot] for every slot
  -> advance ordinary playsim one tic
```

The exact calls may differ, but the temporal contract must be documented in
code and tested.

### 6.7 Offline bot matches

Offline skirmish must not create a fake client or require SDL_net traffic. It
uses the same session/roster and deathmatch rules with `peerCount == 1`, one
local human slot, and host-owned bot slots. Command delay may default to zero
offline while the controller still follows the same production/finalization
path.

This requirement is the reason rules must be independent from network mode.

### 6.8 Network failure policy

- Missing bot commands indicate a host logic failure, not a missing peer.
  Abort with slot/sequence diagnostics instead of waiting forever.
- Missing human commands follow the existing resend and timeout path.
- Remote peers may not synthesize a missing host bot command.
- Host disconnect ends the match in v1.
- A roster/protocol mismatch fails before spawning with a clear message.
- A bad bot profile ID or unavailable player class fails lobby validation;
  never fall back differently on different peers.
- Bot private state is not accepted from any remote packet.

---

## 7. Command production and safety boundary

### 7.1 Refactor command producers

Separate physical polling, AI, network transport, and canonical finalization:

```text
PollLocalHumanInput(slot, gameplayIntent, localUiIntent)
ProcessLocalUiIntent(localUiIntent)              // never serialized
BuildBotIntent(slot, observation, intent)       // host only
FinalizeOwnedCommand(intent, wireCmd)
ValidateGameplayCommand(slot, wireCmd)
QueueOwnedCommand(sequence, slot, wireCmd)
GatherOwnedCommands(sequence, wireCmds[])
InstallGameplayCommand(previousApplied, wireCmd, control[slot])
```

An intent should not expose actor mutation. It contains normalized movement,
desired turn, and requested gameplay actions. Canonical finalization and
installation together:

- clamps axes and yaw;
- clears forbidden buttons;
- converts one-shot action requests to a one-sequence button pulse;
- derives installed `buttonheld` from the previous applied button state;
- records command provenance in debug builds; and
- produces the sole structure accepted by network history/playsim.

Human input can initially retain its existing builder, but both human and bot
commands should pass through the same validation before transmission.

The present `TicCmd_t` mixes replicated gameplay with local automap/map/status/
menu input. Split those paths deliberately. Local UI intent is processed only
by the local instance before gameplay-command sanitization and is never placed
in a bundle. For v1, network deathmatch pause is disabled; offline skirmish may
pause the entire local session. A future network pause must be an explicit
host-authorized, reliably acknowledged session transition at a specified tic,
not a `bt_pause` bit accepted from any player.

### 7.2 Output whitelist

Initially permit only:

- yaw (`controlx`);
- forward/back (`controly`);
- strafe (`controlstrafe`);
- attack;
- use;
- weapon slots 1–8 or existing next/previous selection;
- reload when mine support is enabled; and
- zoom when visor support is enabled.

Explicitly clear:

- escape and pause;
- full automap and Corridor 7 map toggles;
- status-bar/UI controls;
- menu/navigation keys;
- any unsupported alternate attack; and
- pan/pitch until multiplayer has a synchronized canonical representation.

`bt_run` is a producer-local modifier in the current source: keyboard/joystick
polling converts it into axis magnitude before the pawn moves, while
`ControlMovement` chooses walk/run factors from `abs(axis) >= RUNMOVE`. Do not
serialize it in the new stable gameplay mask. A bot selects human-range walk or
run axis magnitudes; any presentation that needs a running state should derive
it from the finalized magnitude so always-run humans and bots agree.

### 7.3 Assertions and static review rules

In debug/test builds, assert that:

- a bot-owned slot's command has host provenance;
- no bot output axis exceeds its global or profile envelope;
- exactly one command is finalized per active slot per sequence;
- no AI function is called during actor/thinker iteration;
- decision code receives observations, not mutable `AActor *` handles;
- a use/weapon edge is followed by release as appropriate;
- a dead bot emits no movement/fire and only an eligible respawn action; and
- bot code never advances a gameplay RNG stream.

Code review should reject direct writes from `g_bot*` to pawn position, angle,
health, inventory, `ReadyWeapon`, `PendingWeapon`, state, or frag fields, and
direct calls to movement, trigger, pickup, fire, damage, die, or spawn methods.

### 7.4 Private random streams

Bot variation must not consume the playsim's weapon, damage, spawn, or actor AI
random streams. Give each bot separate fixed-width PRNG streams derived from:

```text
match bot seed + stable slot + profile ID + stream purpose
```

Use distinct purposes for at least goal tie-breaking, perception uncertainty,
aim motor noise, movement variation, and cosmetic timing. This avoids an extra
roaming choice changing the next aim error.

The host-only model means cross-machine bit identity is not necessary for live
play, but fixed integer algorithms and documented draw points are still highly
desirable for reproducible tests, command recordings, and bug reports. Do not
use wall clock time, `rand()`, pointer values, or renderer frame count.

---

## 8. Runtime world model and navigation

### 8.1 Corridor 7 is a favorable navigation problem

The eight real network arenas are 64 by 64 tile maps: `MAP51` through `MAP57`
and `MAP60`. Corridor 7's translated `GameMap` exposes per-cell sector, tile,
directional solidity, slide amounts, sound zones, triggers, pushwall state, and
Corridor-specific markers. This makes a compact runtime graph preferable to a
general Doom-style navigation mesh.

Do not construct the graph from raw commercial file numbers inside the bot.
Construct it after map translation from the live `GameMap` representation and
the same runtime actor definitions the player uses. The translation layer is
the authority for what a raw value means.

### 8.2 Arena coverage targets

A read-only audit of the shipped data found these bot-relevant cases. This is a
test matrix, not a hard-coded routing table:

| Arena | Navigation/combat cases that must be covered |
| --- | --- |
| `MAP51` | Blue locked door, electric wall cells, invisible laser barriers, masked/removable wall markers, broad weapon set |
| `MAP52` | Electric walls, several invulnerability pickups, masked-wall geometry |
| `MAP53` | Relatively simple geometry and sparse pickups; useful baseline |
| `MAP54` | Laser barriers, many energy charge packs, armor and weapon choices |
| `MAP55` | Electric walls and extensive masked-wall geometry |
| `MAP56` | Four transporter pairs and their field actors |
| `MAP57` | Three transporter pairs |
| `MAP60` | All eight transporter pairs, electric walls, and all major weapons |

The older claim that the eight arenas are a contiguous `MAP51`–`MAP58` block
is not correct for the shipped archive. `MAP58` and `MAP59` are unused boxes;
Network Level 8 is `MAP60`. Bot gates must use the same authoritative list as
the multiplayer menu/map definitions.

Many of `MAP51`–`MAP57` also contain ordinary exit switches. Until battle-mode
gameplay suppresses those switches, the bot's usable-special classifier must
blacklist level exits. It must not end a deathmatch because a generic roam
routine pressed every nearby switch.

### 8.3 Graph representation and knowledge separation

Keep three different concepts separate:

1. **Shared static potential graph:** map-learnable cells, portals, door/
   transporter locations, and possible transitions. It does not say that an
   unseen dynamic portal is open now and never contains hidden laser/mine
   locations.
2. **Physical traversal state/cache:** the host's actual collision truth used to
   keep pure collision queries correct. It may be invalidated by every world
   special, but tactical code cannot read it globally.
3. **Per-bot belief overlay:** that bot's perceived/remembered dynamic portal,
   obstacle, item, mine, and hazard state with timestamps/confidence. A bot's
   planner uses this overlay, never another bot's discoveries.

The short-range collision oracle may prevent a bot from issuing movement
through a physically blocked boundary it is presently touching/approaching,
analogous to a human feeling collision. That result may create a contact
observation for that bot. It must not become arbitrary-distance tactical
knowledge or update every bot's overlay.

Each base node should record:

- stable node ID;
- plane and cell coordinate;
- reachable standing position, normally a tile center or validated portal
  sample;
- sector/sound-zone identity;
- local clearance for the configured player radius;
- static, human-knowable hazard annotation (never an undiscovered hidden laser
  or mine);
- known pickup spawn annotations; and
- outgoing typed edge IDs in stable order.

Each edge should record:

- stable edge ID and source/destination node;
- traversal type;
- base distance cost;
- required approach/facing information;
- associated map trigger/portal identity where applicable;
- whether its state can change;
- expected traversal/wait time; and
- hazard/exposure annotations.

Initial traversal types:

```text
WalkCardinal
WalkDiagonal
UseDoor
UseSwitchOrField
Transporter
```

Reserve types for pushwalls/elevators only when an actual arena or supported
mod requires deliberate activation. A moving wall may still invalidate an
ordinary walk edge.

Use node IDs and ascending edge IDs as deterministic tie-breakers. Never break
ties by pointer value, hash-table iteration order, or actor-list order.

### 8.4 Walkability and clearance

The `C7Player` radius is 22 units in a 64-unit tile. A cell containing a sector
is not automatically walkable, and a cell containing a tile is not
automatically permanently blocked. Sliding doors, forcefields, pushwalls,
masked apertures, and solid scenery make the runtime boundary state important.

Create a side-effect-free traversal query, conceptually:

```cpp
TraversalResult QueryPlayerTraversal(
    const APlayerPawn &prototype,
    fixed_t fromX, fixed_t fromY,
    fixed_t toX, fixed_t toY,
    TraversalQueryFlags flags);
```

It must use the same dimensions and boundary rules as player collision but must
not move an actor, collect an item, fire a crossing trigger, make a sound, open
a door, or alter a thinker. Do not call mutating `TryMove` on a disposable actor
and hope every side effect is harmless. Extract/shared-test the pure collision
portion where necessary.

Graph construction should:

- test cardinal connections at player radius;
- add a diagonal only when the diagonal sweep is valid and it cannot cut the
  corner between two blocked cardinal boundaries;
- account for solid static actors;
- treat dynamic actors as a physical-query plus per-bot-belief/temporary-
  avoidance problem rather than permanently deleting potential topology;
- record a door/use edge instead of treating a closed but usable door as open;
- represent traversable damaging volumes with cost, not false solidity; and
- validate every smoothed shortcut with the same pure traversal query.

Write parity tests that compare the query with an ordinary scripted pawn
attempting the same move in an isolated map. A graph that predicts movement
differently from `ClipMove` is not acceptable.

### 8.5 Doors and usable transitions

Corridor 7 doors are directional, can be locked, open over time, wait, close,
and jam. Battle players receive all keys through ordinary deathmatch inventory,
so a bot in `MAP51` must open the blue door through the same possession and use
checks, not through an AI exception.

A `UseDoor` edge is a small state machine:

1. Navigate to a validated approach point on a permitted face.
2. Turn through the ordinary yaw controller until inside a configurable use
   facing tolerance.
3. Pulse `bt_use` for one command edge.
4. Observe whether the door began opening; do not infer success merely from
   the requested action.
5. Wait/strafe safely while the boundary remains collision-solid.
6. Cross only when the ordinary traversal query reports sufficient opening.
7. Time out and replan if the door is jammed, closes, is activated from the
   wrong side, or cannot be used.

The current collision path requires a sliding boundary to be fully open before
crossing. The bot must use that truth rather than a visual approximation.

Use-trigger selection must distinguish doors/fields from exit actions. The
brain is never allowed to call `Door_Open`, `ActivateTrigger`, or a line special
directly.

### 8.6 Forcefields, masked walls, removable walls, and pushwalls

The translation/runtime supports permanent masked openings, solid but visually
transparent markers, repeatable forcefield toggles, animated wall removal, and
pushwalls. Physical cache validity and bot knowledge must not be conflated.

Required behavior:

- graph build records the underlying portal and its possible transition;
- world-special changes invalidate the host's physical traversal cache without
  broadcasting that fact into every brain;
- vision, audible events, or near-field failed traversal update only the
  observing bot's belief overlay/generation;
- each route records the per-bot belief generation used to plan its dynamic
  edges;
- the local follower revalidates physical traversal before committing to the
  boundary, and only then supplies a local contact result if belief was stale;
- a perceived/locally encountered change triggers a bounded replan, not a
  position correction; and
- an occupant preventing a wall from closing is treated as a temporary state.

There is a current semantic mismatch among rendered visibility, gameplay LOS,
and projectile collision for some masked Corridor 7 walls. Bot perception and
attack feasibility must initially call the same gameplay queries that decide
human hits. Resolve the underlying mismatch in a focused gameplay regression;
do not let bot code invent a fourth interpretation.

### 8.7 Transporters

Transporters are directed traversal edges linking the translated source and
counterpart destination while preserving the game's arrival behavior.

The follower must:

- approach/cross the ordinary trigger through movement commands;
- never call teleport logic directly;
- expect the actual translated destination and centered-arrival behavior;
- model the 35-tic movement freeze as traversal time;
- emit no movement while frozen, although ordinary firing may remain legal;
- clear obsolete local steering after arrival; and
- replan from the actual arrival position.

Every pair in `MAP56`, `MAP57`, and `MAP60` needs an automated traversal test.
The planner must be able to choose a transporter when it lowers route cost, and
also avoid oscillating through a pair in both directions.

### 8.8 Hazards

The cost model must distinguish at least:

- electric wall IDs that are solid and damage a player pressing into them;
- nonsolid laser barriers that damage on overlap;
- mines/projectile splash learned through perception; and
- ordinary temporary combat exposure.

Laser barriers are only visibly identifiable in infrared mode. A bot without
the relevant visor state must not scan their hidden actor objects and route
around them from the start. It can discover a laser through contact/damage or a
fair sensory cue, remember the location, and then price it into later routes.

Hazard cost is contextual:

```text
expected damage
  x health/armor urgency
  x probability of contact
  + time exposed
  + self-trap risk
```

Invulnerability can make a dangerous shortcut reasonable. Low health can make
the same edge unacceptable. This only changes planning; actual damage remains
ordinary gameplay damage.

### 8.9 Items as graph annotations

At map load, record known spawn location, class/category, and stable identity
for pickups. Do not equate a spawn annotation with current availability.

The tactical layer may know a learned spawn location. It may consider the item
present only when:

- it is currently visible/perceived; or
- memory says it was present and no contrary observation exists; or
- a remembered pickup/respawn timer makes its return plausible.

Battle items respawn through ordinary inventory actor state, and map weapons
have multiplayer stay behavior. Item evaluation must use those real semantics.
An inactive unseen actor is not an omniscient goal.

### 8.10 A* and path costs

Use a conventional compact A* implementation with stable integer/fixed costs.
For these small maps, correctness and diagnostics matter more than exotic
optimization.

Suggested cost terms:

```text
base geometric distance
+ expected door/use/wait time
+ transporter freeze time
+ hazard risk
+ recent edge failure penalty
+ temporary congestion/avoidance penalty
+ tactical exposure penalty
+ excessive turn/reversal penalty
```

Requirements:

- an admissible base heuristic when optimality is required. Because a distant
  transporter can make Manhattan/Euclidean distance overestimate true cost,
  start with `h = 0` (Dijkstra) for every map; adopt only a proven
  transporter-aware lower bound later;
- stable node/edge tie-breaking;
- bounded expansions per bot/tic and a bounded total host budget;
- continuation state for incremental searches;
- a clear "no path" result;
- cancellation when goal or that bot's belief generation changes;
- separate workspace for route planning and cheap cost estimation;
- no fixed path length silently truncating a valid route; and
- counters for expansions, reopenings, time/budget, and failure reason.

Attempt a direct validated route first. After A* succeeds, smooth it by removing
intermediate nodes only when the actual player-radius traversal query accepts
the entire shortcut. Retain typed interaction nodes even if their positions
appear geometrically skippable.

### 8.11 Route following and local steering

The graph produces waypoints; the locomotor produces human-like commands.

Each tic it should:

- choose a short look-ahead target on the current path;
- calculate desired facing without writing actor angle;
- blend forward/back/strafe intent with combat intent;
- reduce forward input for turns too sharp to take cleanly;
- use short-range wall/collision feelers;
- preserve strafe direction for a commitment interval;
- exploit the engine's ordinary wall sliding instead of oscillating axes;
- advance a waypoint only after spatial/edge-specific completion criteria; and
- measure actual progress along the route.

To avoid robotic centerline movement, choose a seeded, slowly changing
within-clearance offset for broad corridors. Never apply random lateral noise
near tight doors, corners, hazards, or transporter triggers. Humanization must
not turn a good path into chronic wall scraping.

Nearby players do not currently create hard player-player collision. Local
avoidance may make movement look natural and reduce clumping, but it must not
pretend they are impassable topology.

### 8.12 Stuck detection and recovery

Track desired movement, actual displacement, distance-to-waypoint progress,
collision results where exposed, repeated use attempts, and route generation.

A provisional recovery ladder:

1. **Minor obstruction:** preserve goal; reduce forward input and strafe away
   for a short seeded interval.
2. **Corner oscillation:** back up, commit to one side, and retry the waypoint.
3. **Closed interaction:** face and pulse use again only after a sensible
   cooldown.
4. **Dynamic obstruction:** invalidate the local edge and replan.
5. **Route failure:** temporarily penalize the failed edge and choose another
   path to the same goal.
6. **Goal failure:** abandon the goal with a cooldown and select another.
7. **Emergency roam:** choose a visible reachable nearby point to recover a
   valid graph location.

At no stage may recovery teleport, noclip, set velocity/coordinates, ignore
collision, or invoke a trigger. Persistent failure should produce a trace with
map, seed, slot, position, path, last commands, and obstruction state.

---

## 9. Perception, hearing, and memory

### 9.1 Observation boundary

At each scheduled sense update, construct a `BotObservation` from a
start-of-tic snapshot. It should contain values, stable IDs, and timestamps,
not mutable actor pointers.

Suggested observation records:

```text
OwnState
VisiblePlayerObservation
VisibleProjectileObservation
VisibleItemObservation
VisibleHazardObservation
AudibleEventObservation
DamageCueObservation
PublicMatchState
```

All bots sense the same completed world before any of their current commands
are applied. Iterate candidate player slots in ascending stable slot order.
Give non-player entities stable spawn/runtime serials before relying on them in
ties or memory.

### 9.2 Vision

A player observation requires all applicable filters:

- active, alive, and targetable under current deathmatch rules;
- not the observing slot;
- inside the bot profile's current horizontal FOV;
- gameplay line of sight through `CheckLine` or its canonical successor;
- visibility rules for masked geometry, effects, or equipment;
- range/contrast limits if deliberately modeled; and
- perception update/reaction timing.

Do not use renderer-marked cells or `ConsolePlayer` camera state. Rendering may
not run on a headless host and describes the local camera, not each bot.

The bot may keep tracking a contact for a short grace interval when it crosses
the edge of FOV, but it must not refresh exact position through a wall. A
visible target record should include observed position, observed facing or
velocity only to the degree inferable from consecutive observations, sighting
tic, confidence, and visibility quality.

### 9.3 Reaction queue

Detection and action are separate. When a sensory event is created, put it in
a per-bot queue with a profile-dependent release tic. The decision layer only
sees it when released.

Events requiring reaction delay include:

- newly seen enemy;
- target reappearing or changing direction sharply;
- nearby projectile/hazard discovery;
- weapon fire heard behind the bot;
- damage cue;
- pickup appearing/disappearing; and
- door/path failure.

An already tracked target can be updated at an aim-tracking cadence without
paying full acquisition delay every time, but it still uses delayed observed
samples rather than the target's current hidden position.

### 9.4 Hearing event system

The existing global `madenoise` Boolean has no source, location, type, or
history and is insufficient. Add a deterministic gameplay event ring emitted
at semantic action points, not by querying the audio mixer.

An event should include:

```text
event sequence/tic
category (weapon, impact, door, use, pickup, footstep if supported, pain/death)
source slot or anonymous source
world position and sound zone
base loudness/radius
optional weapon family, only if the sound is human-recognizable
```

For each bot, the sensor applies distance, zone/door connectivity, occlusion or
attenuation, profile perception, and seeded position uncertainty. The released
observation gives an approximate bearing/region, not an exact unseen actor
coordinate.

Start with weapon, impact/explosion, door/use, pain, and death events. Add
footsteps only if a human can actually hear an equivalent sound in the game;
do not invent sensory data solely for AI convenience.

### 9.5 Damage cues

A bot knows that it lost health and may receive the directional/source cue the
human presentation reasonably provides. If the engine displays only a damage
flash and no exact attacker identity, do not hand the AI an exact unseen
attacker pointer merely because `killerobj` or a damage call contains one.

Recommended representation:

- exact damage amount/own resulting status;
- approximate bearing if direction is perceptible;
- exact source slot only when the attacker was already visible or the attack
  itself clearly identifies it; and
- a high-priority search/evade stimulus with uncertainty otherwise.

Document the final rule after reviewing the actual Corridor 7 damage feedback.

### 9.6 Items and dynamic world state

The bot may memorize static pickup spawns. It must not iterate all inventory
actors to learn which unseen pickup is currently active. Perceived pickup
records decay or become "unknown," not automatically "absent," after leaving
view.

When a bot sees a location empty, records a pickup event, or collects an item,
update memory and a probabilistic/known respawn window. Because ordinary battle
items and stay-in-world weapons differ, the memory model needs item category
semantics rather than one global timer.

### 9.7 Hidden lasers and equipment

Invisible laser actors in Corridor 7 require special treatment:

- without infrared, do not expose them through vision or static actor scans;
- contact/damage may create a remembered hazard at the experienced location;
- with the appropriate visor mode active, expose them through the ordinary
  vision path; and
- losing infrared does not erase learned memory, but memory has ordinary
  uncertainty/age.

The bot must activate/cycle visor mode only through the same zoom/equipment
command and consume ordinary charge.

### 9.8 Memory and uncertainty

For each known player/contact, store at most:

- stable slot;
- last seen position and tic;
- a short history of observed positions sufficient for perceived velocity;
- last heard approximate region and tic;
- last known heading/action category if visibly inferable;
- confidence and uncertainty radius; and
- whether the current fact is seen, heard, inferred, or stale.

Confidence decays with time and occlusion. Position prediction is capped and
uses only observed history. A bot may search the last-known location, sweep
likely exits based on map knowledge, or abandon the contact. It may not keep an
exact lock on a hidden player.

Memory quality is one skill/personality axis. Even the highest normal skill has
finite update/reaction time and prediction error.

---

## 10. Decision architecture

### 10.1 Use a hierarchical state machine plus utility

A small explicit state machine gives debuggable control flow; utility scoring
chooses among sensible goals without creating a brittle maze of conditionals.

Recommended top-level states:

```text
DeadWaitingToRespawn
SpawnOrient
Roam
SeekPickup
EngageEnemy
ChaseOrSearchLastContact
RetreatOrRecover
UseTraversal
Unstuck
```

States are not animations and do not bypass gameplay. They select an intent
that ultimately becomes a command.

Global interrupts should be few and ordered:

1. dead/respawn lifecycle;
2. immediate lethal hazard or self-damage avoidance;
3. newly perceived close threat;
4. invalid/stuck traversal;
5. normal state continuation/reconsideration.

### 10.2 Goal candidates

At a tactical update, construct only candidates justified by observations and
knowledge:

- attack a visible enemy;
- chase/search a recent visible or audible enemy contact;
- obtain needed health;
- obtain armor or invulnerability;
- obtain a useful weapon;
- obtain bullets, energy/capacity, mines, or visor charge;
- deny/contest a high-value known pickup when plausible;
- move to a tactically safer or more useful map region;
- leave a hazardous/dead-end region; or
- roam to a seeded reachable exploration point.

Do not create a goal for an unseen currently active actor merely because it is
in the global actor list.

### 10.3 Utility model

A suitable starting formula is:

```text
utility = need x category value x availability confidence
        - route time/cost
        - expected hazard/exposure
        - contest risk
        - stale-information penalty
        + personality bias
        + current-goal persistence
        + small seeded tie variation
```

Use integer/fixed terms with named debug output. Every selected goal trace must
show candidate scores and rejection reasons.

Examples:

- health value rises nonlinearly as health falls;
- ammo has little value when the bot cannot use its weapon family or is near
  capacity;
- a weapon already owned may be worthless if stay-in-world rules do not grant
  more ammo;
- invulnerability is valuable but not worth repeated lethal traversal;
- an enemy engagement is less attractive when badly hurt and a safe health
  route is credible;
- a stale remembered pickup is discounted; and
- a transporter shortcut includes its freeze/exposure cost.

### 10.4 Commitment and hysteresis

Without commitment, noisy utility makes a bot visibly indecisive. Each goal
gets:

- minimum commitment time unless invalid or interrupted;
- switch threshold over current-goal utility;
- cooldown after failure/abandonment;
- maximum pursuit/search time; and
- explicit completion/invalidity conditions.

Engagement target changes also require a material advantage, loss of the old
target, or immediate threat. Do not switch targets every sensing tick because
two distance scores alternate by one unit.

### 10.5 State behavior outline

**DeadWaitingToRespawn**

- Clear target/path/fire state.
- Observe ordinary `RespawnEligible` state; never force `PST_REBORN`.
- After a profile-dependent human delay, pulse use when eligible.
- Accept the engine's forced automatic timeout.

**SpawnOrient**

- Begin with no inherited exact enemy lock.
- Process newly available sights/sounds after reaction delay.
- Choose a short safe orientation/roam goal.
- Do not receive invulnerability unless gameplay supplies it.

**Roam / SeekPickup**

- Follow a committed route.
- Scan on normal perception cadence.
- Re-evaluate at goal completion, invalidity, a material threat, or scheduled
  think.

**EngageEnemy**

- Maintain a preferred range appropriate to usable weapons.
- Combine combat strafe, cover/line-of-fire movement, aiming, weapon choice,
  fire gating, and survival utility.
- Use only visible or delayed remembered target samples.

**ChaseOrSearchLastContact**

- Route to last seen/heard region.
- Check plausible exits/nearby nodes for a bounded time.
- Expand uncertainty rather than following the exact hidden actor.
- Abandon cleanly when confidence expires.

**RetreatOrRecover**

- Break LOS or route toward a known survival resource/safer node.
- Continue ordinary combat decisions when cornered.
- Do not know enemy health to decide that it can "finish" them.

**UseTraversal / Unstuck**

- Execute only typed interaction/recovery protocols from navigation.
- Return control to the interrupted state after success.

### 10.6 Decision fairness checks

For every decision input, ask:

1. Could an attentive human know this fact from the HUD, view, sound, or learned
   map?
2. Is its precision no better than the human presentation supports?
3. Is it delayed by the bot's perception/reaction model?
4. Does acting on it still require ordinary input and game rules?

If any answer is no, move the query behind the sensor boundary, degrade it, or
remove it.

---

## 11. Movement humanization

Movement should be competent enough not to look broken, but it should retain
human timing and commitment.

### 11.1 Motor model

Maintain motor state rather than independently choosing raw axes each tic:

- current and desired forward magnitude;
- current and desired strafe magnitude;
- current yaw rate and desired yaw rate;
- acceleration/deceleration limits;
- strafe side and commitment expiry;
- short movement hesitation/change timers; and
- locomotion mode: route, combat, avoid, use, frozen, dead.

Rate-limit changes to produce plausible acceleration and prevent left/right
button chatter. The ordinary game still determines actual speed from pawn
properties and command values.

### 11.2 Walking, running, and backwards movement

The planner chooses normalized intent; the profile/controller maps it to
ordinary command magnitudes. Initial behavior can run for long traversal and
combat, walk or slow for precise door/turn approaches, and backpedal only when
maintaining a target or escaping a local obstruction.

Never compensate a slower player class with larger commands beyond the human
range. The configured pawn class's own speed remains authoritative.

### 11.3 Turning

Calculate a desired bearing from route or aim, then pass it through:

- perception-delayed target bearing;
- profile maximum yaw speed;
- yaw acceleration/deceleration;
- damping near the desired angle;
- smooth correlated motor error;
- occasional bounded overshoot; and
- conversion to a clamped integer `controlx`.

Large turns should take visible time. The controller must never assign
`APlayerPawn::angle`, even when stuck, spawning, or using a door.

### 11.4 Combat movement

Combat locomotion selects among approach, hold range, circle/strafe, retreat,
break line of fire, and route-to-resource. Behavior should include:

- committed strafe intervals rather than frame-perfect mirroring;
- imperfect reversal timing;
- reduced movement precision while making a large aim correction;
- collision-aware changes near walls;
- avoidance of self-splash and armed mines based only on perceived/remembered
  hazards; and
- no perfect dodge triggered by an unseen shot or exact projectile trajectory.

Because player pawns currently pass through one another, avoid visibly running
through an opponent when practical but do not treat the opponent as a hard wall
or alter collision.

### 11.5 Movement mistakes

Human-like does not mean sabotaging the bot with arbitrary noise. Appropriate
mistakes include:

- taking a slightly longer valid route;
- overshooting a wide corner and correcting;
- hesitating before a newly discovered door;
- holding a strafe direction a little too long;
- failing to exploit the globally shortest pickup route; and
- losing route efficiency while fighting.

Inappropriate fake mistakes include repeatedly walking into a known wall,
oscillating at a doorway, ignoring a clearly visible lethal hazard, or random
axis jitter every tic. Those look like bugs, not human play.

---

## 12. Combat, aiming, weapons, and equipment

### 12.1 Target acquisition

Candidate targets come only from released visible observations or recent
memory. Filter dead/nonshootable slots and self. In free-for-all, every other
live player is an enemy.

Score targets using perceived values such as:

- immediate threat/action;
- angular and travel distance;
- visibility quality and recency;
- whether the target is attacking the bot;
- line-of-fire opportunity;
- current weapon suitability; and
- cost of abandoning the current target.

Do not score unseen exact health, armor, inventory, or frag opportunity.
Stable slot ID resolves exact ties.

### 12.2 Corridor 7 aiming reality

Corridor 7 combat here is effectively planar. Human yaw is driven through
`controlx`. Most hitscan weapons call `player_t::FindTarget`, which can acquire
the nearest shootable target inside an approximately ten-degree cone and then
uses normal LOS and weapon randomness.

This has an important tuning consequence: an aim error smaller than the
auto-target cone may still produce a hit. Bot inaccuracy cannot be implemented
only as tiny reticle noise while firing exclusively inside the cone. Lower
skills must sometimes fire early/late, track the wrong delayed bearing, or
remain outside the acquisition cone. The ordinary weapon code then decides the
actual hit and damage.

Never call `FindTarget` as an unrestricted perception oracle and never inspect
the next damage/random outcome.

### 12.3 Aim observation and prediction

Keep a time-stamped history of perceived target positions. The aimer chooses
one sample no newer than its tracking delay and estimates velocity only from
released observations.

For hitscan:

- aim toward delayed observed position;
- add motor bias/error and bounded tracking prediction; and
- gate fire using profile/weapon confidence and impatience.

For the plasma projectile:

- estimate travel lead from known projectile speed and perceived target
  velocity;
- add uncertainty proportional to range, target maneuvering, and observation
  age;
- reject or heavily penalize unsafe self-splash shots; and
- still fire only through ordinary weapon input.

Prediction must stop or broaden when the target disappears. No extrapolator may
refresh itself from the hidden current actor position.

### 12.4 Correlated aim error

Do not draw a new independent random angle each tic. Maintain an error state
that drifts toward a seeded bias and changes smoothly, for example with an
integer mean-reverting process:

```text
errorVelocity += restoring force toward current bias + bounded noise
errorVelocity = clamp(errorVelocity)
errorAngle += errorVelocity
occasionally choose a new bounded bias after a dwell interval
```

Scale the error envelope with:

- skill/profile;
- range and apparent target size;
- target angular velocity;
- observer movement/turning;
- time since acquisition;
- visibility/occlusion quality;
- weapon family; and
- recent firing/recovery cadence where appropriate.

Allow occasional overshoot and correction. Never permit the highest normal
profile to converge instantly to exact continuous tracking.

### 12.5 Fire gating and cadence

The fire controller considers:

- whether an allowed target observation/memory exists;
- current facing error and its trend;
- normal weapon-ready flags and usable ammo known from own inventory;
- line of fire from current perceived geometry;
- expected self-splash/mine risk;
- range suitability;
- acquisition/trigger reaction timer;
- burst commitment/release timer; and
- seeded hesitation/impatience.

It requests `bt_attack`; the weapon state machine decides when a shot actually
occurs. It must not force `attackheld`, psprite state, cooldown, or ammo.

Intentional imperfection includes occasionally pulling the trigger just outside
the ideal cone, holding a burst after the target starts leaving view, or
hesitating on a newly acquired target. It must remain bounded and measurable.

### 12.6 Weapon selection

Build an explicit Corridor 7 weapon descriptor table, initially in code or
validated data, containing facts the controller needs:

- inventory/weapon class;
- slot input;
- hitscan, melee, projectile, or special multi-target behavior;
- usable range band;
- ammo/energy/capacity costs available from gameplay definitions;
- cycle/burst characteristics;
- projectile speed and splash/self-risk where applicable;
- whether holding fire is useful;
- switch cost; and
- bot support maturity.

Weapon utility should combine perceived range, target motion, ammo economy,
self-risk, current readiness, and personality preference. Selection is a slot
button pulse followed by waiting for ordinary weapon-switch completion. The bot
must never assign `PendingWeapon` or `ReadyWeapon`.

Corridor 7 cases needing explicit tuning/tests:

- bayonet/security taser at melee range;
- M16 as starting baseline;
- M343 burst behavior;
- dual blaster energy/capacity consumption;
- shotgun close-range value and long recovery;
- plasma projectile leading and splash;
- assault cannon multi-roll behavior;
- disintegrator's exceptional energy cost and broad multi-target attack.

The disintegrator must not be treated as an ordinary single-target hitscan
weapon. Test it independently.

### 12.7 Mines

Mine use is optional for the first playable combat slice and should be enabled
only after ordinary gun behavior is solid.

When enabled, the bot:

- knows its own mine count;
- chooses a placement intent based on learned routes/choke points and current
  risk, not hidden enemy paths;
- faces/positions through ordinary movement;
- pulses the existing reload action;
- clears its own mine before arming as ordinary gameplay requires;
- remembers visible/placed mines with uncertainty; and
- prices blast risk according to the game's actual radius and through-wall
  behavior.

It may not spawn a mine actor directly. Tests must cover owner-clear timing,
shootable detonation, self-damage, opponent damage, memory, and ordinary ammo
consumption.

### 12.8 Visor

Visor support is also staged. A bot may choose a mode based on perceived
lighting/laser usefulness, but it must issue the same zoom/equipment action and
consume the same visor charge. It cannot simply turn on a perception flag.

Until implemented, bots should leave the visor in its normal state and remain
subject to the corresponding perception limitations.

### 12.9 Respawn behavior

On death, stop movement, aim, weapon, route, and fire intentions. Preserve only
profile/personality and match memory that a human could reasonably retain.

When `RespawnEligible` becomes true, wait a bounded profile/personality delay
and pulse use. The ordinary forced-respawn timeout is the final authority.
After `Reborn`, reacquire own pawn/inventory, clear obsolete sensory contacts,
and enter `SpawnOrient`. Do not choose or alter the spawn.

### 12.10 Combat bugs that must not be hidden in AI

The current source review found that player-owned projectile collision can skip
players in a way that makes plasma pass through an opponent. Fix and test the
gameplay path before using plasma performance to tune weapon utility.

Likewise, masked-wall sight/projectile inconsistencies and battle exit behavior
belong in gameplay rules. Bot code should consume the corrected canonical
result, not recognize maps and work around engine defects.

---

## 13. Skill, personality, and human-likeness

### 13.1 Separate skill axes

One menu difficulty can map to multiple internal traits, but do not collapse
the implementation into one accuracy number.

Suggested profile fields:

```text
reactionMinTics / reactionMaxTics
visionUpdateInterval
hearingAccuracy / hearingRangeScale
memoryHalfLife / searchPersistence
maxYawRate / maxYawAcceleration
aimErrorRange / aimErrorVelocity
trackingDelay / predictionQuality
triggerDelay / burstLength / releaseDelay
movementAcceleration / routeLookAhead
strafeCommitRange / reversalDelay
goalThinkInterval / goalSwitchThreshold
pathSearchBudget / tacticalLookAhead
riskTolerance / pickup category biases / weapon preferences
respawnDelayRange
```

Keep **skill** and **personality** conceptually separate. Skill governs quality
and motor/sensory limits. Personality can prefer aggression, resource control,
particular weapon families, risk, or roaming patterns without making one
profile objectively superhuman.

### 13.2 Provisional shipped skill levels

These values are starting hypotheses, not promises. They must be converted to
the engine's exact command/angle scale and tuned from recorded telemetry. All
reaction values are additional to the match's agreed input delay.

| Trait | Recruit | Marine | Veteran | Elite |
| --- | ---: | ---: | ---: | ---: |
| New-target reaction | 24–45 tics (343–643 ms) | 17–32 tics (243–457 ms) | 12–24 tics (171–343 ms) | 10–19 tics (143–271 ms) |
| Vision refresh | 7–10 Hz | 10–14 Hz | 14–20 Hz | 20–28 Hz |
| Max yaw rate | 140–210°/s | 190–260°/s | 240–310°/s | 280–350°/s |
| Max yaw acceleration | 600–900°/s² | 850–1,300°/s² | 1,200–1,800°/s² | 1,600–2,400°/s² |
| Static-target aim-error envelope | 8–16° | 5–11° | 2.5–7° | 1.5–5° |
| Tracking delay after acquisition | 10–22 tics | 7–16 tics | 4–11 tics | 3–8 tics |
| Tactical reconsideration | 4–6 Hz | 5–7 Hz | 6–9 Hz | 7–10 Hz |
| Search memory | 2–5 s | 4–8 s | 6–12 s | 8–15 s |
| Strafe commitment | 0.5–1.5 s | 0.6–1.6 s | 0.7–1.8 s | 0.7–2.0 s |
| Respawn hesitation after eligible | 18–55 tics | 12–40 tics | 8–28 tics | 6–22 tics |

Important qualifications:

- Degrees/second are easier to review than raw `controlx`, but final code must
  derive and test the exact conversion used by `ControlMovement`. At 70 Hz,
  `controlx * (ANGLE_1 / 20)` and the canonical ±100 range impose a hard
  350°/s ceiling; no profile may exceed it unless the same reviewed command
  range is deliberately changed for humans and bots together.
- Aim error expands with range, movement, occlusion, tracking age, and target
  angular velocity. The table is not a constant random cone.
- The hitscan auto-target cone means these values will not map linearly to hit
  percentage.
- Elite remains deliberately fallible. It has finite reaction, a nonzero error
  floor, bounded turn rate, imperfect prediction, and nonzero decision noise.
- The ranges should vary by stable bot personality/seed, not redraw completely
  every tic.

### 13.3 No statistical cheats

All profiles use the same:

- pawn class and configured class properties;
- command range;
- movement/collision;
- health and armor;
- damage and weapon spread;
- ammo/energy/capacity consumption;
- pickup and key rules;
- spawn and respawn rules;
- simulation tick rate; and
- network input-delay schedule.

Do not implement difficulty by multiplying outgoing damage, reducing incoming
damage, granting ammo, increasing speed, shortening weapon states, enlarging
LOS through walls, or reading hidden state.

### 13.4 Human-like performance is a distribution

Avoid a single target such as "50% accurate." Evaluate distributions by
weapon, range, movement state, target visibility, and skill:

- acquisition latency;
- target-switch latency;
- yaw velocity and acceleration;
- angular error at trigger time;
- shot/burst lengths and release delays;
- accuracy and damage per shot;
- movement-path efficiency;
- time spent stuck;
- resource choices and goal changes;
- exposure before retreat;
- search duration after loss; and
- kills/deaths/frags over many seeds.

A bot that misses 50% by alternately snapping perfectly and firing 90° away is
not human-like. The time series and circumstances matter.

### 13.5 Fairness ceiling

The highest normal profile must still satisfy:

- no event released on the same tic as a previously unknown stimulus;
- no instant 180° turn;
- no exact tracking of an occluded target;
- no zero-variance aim lock;
- no perfect projectile dodge on first possible tic;
- no knowledge of unseen item availability;
- no target choice from unseen opponent health;
- no 100% accuracy in a sufficiently large contested test; and
- no action outside the canonical command interface.

A developer-only `Perfect` profile may exist for isolated mechanics tests, but
it must be explicitly named, unavailable in ordinary menus/network lobbies,
and never used as evidence of shippable bot quality.

### 13.6 Calibration process

1. Add opt-in capture of human `TicCmd_t` streams and combat events in local
   test matches.
2. Derive broad, anonymized distributions for yaw speed/acceleration,
   forward/strafe commitment, reaction, trigger error, and burst cadence.
3. Tune motor limits to lie within plausible human percentiles rather than
   copying one player's quirks.
4. Run seeded bot duels and mixed human playtests.
5. Inspect traces for *why* misses, target switches, and route choices occur.
6. Adjust one trait family at a time and record the before/after metric set.
7. Keep deterministic regression scenarios separate from probabilistic balance
   benchmarks.

Human command captures must be opt-in, local by default, contain no personal
identifiers, and never be silently network-uploaded.

---

## 14. User interface, configuration, and administration

### 14.1 First-release lobby model

The smallest clear UI extends the host setup with:

- **Human players:** expected connected humans including host;
- **Bots:** number of host-owned AI slots;
- **Bot skill:** Recruit, Marine, Veteran, or Elite;
- existing arena/rules/class/match-limit fields; and
- a derived **Total slots** value validated against the supported limit.

Starting is allowed when:

- at least one local human exists in an interactive match;
- at least two total occupied slots exist;
- all expected remote humans have joined;
- human plus bot count is within the supported roster cap;
- every class/profile is valid; and
- all peers acknowledged the same locked roster.

Internally, construct the explicit per-slot roster even if the first UI assigns
humans first and bots afterward. A later advanced lobby can expose each row as
`Human`, `Open`, `Bot`, or `Closed`, with individual class/profile/name.

Joining clients see the host-authored roster and bot count/skill read-only.
They do not instantiate or configure brains.

### 14.2 Offline skirmish path

The multiplayer menu should allow "Host/Local" or an explicit "Skirmish" path
that creates a deathmatch roster with one local peer and no socket wait. Avoid
duplicating game setup or bot configuration in a separate single-player code
path; it is the same session with `peerCount == 1`.

### 14.3 Names and identity

Player identity belongs in the session roster because `player_t` currently has
no complete name/bot metadata model.

Requirements:

- stable display name for the duration of a match;
- stable slot and bot marker;
- valid selected player class and appearance/color if supported;
- duplicate-name disambiguation;
- safe length and character validation before network/display use; and
- no name used as a stable programmatic identity.

Ship original project-owned generic names or deterministic numbered names such
as `Bot 1`; do not copy Zandronum's persona names/data.

### 14.4 Profile data

Begin with validated built-in profiles so behavior work is not blocked on a new
parser. Keep the runtime representation data-oriented.

If mod/profile lumps are added later:

- define a versioned schema and documented units/ranges;
- reject unknown mandatory fields, invalid enums, duplicate IDs, NaN/overflow,
  and out-of-range values;
- hash canonical profile data into the match compatibility setup;
- never load executable code or native libraries from a profile;
- place absolute fairness clamps after profile parsing; and
- make missing profile IDs a startup error, not a per-peer fallback.

A `BOTINFO`-like format may eventually be useful, but a behavior VM is not a
prerequisite.

### 14.5 Console and command-line controls

Recommended controls:

```text
--bots <count>                 scripted/headless setup
--bot-skill <name-or-index>    profile mapping
--bot-seed <integer>           developer reproducibility override
bot_list                       display roster/controller/profile/state
bot_debug <slot|all>           select diagnostics
bot_fill                       lobby/match-boundary fill operation
bot_remove <slot|name|all>     lobby/match-boundary removal
```

Live `addbot`/`removebot` should initially refuse while playsim is active and
explain that roster changes occur at match boundaries. Do not pretend a local
console change is safe in lockstep.

Host-authoritative commands are host-only. A remote client's bot
administration request must either be rejected or sent through a separately
authorized future lobby protocol; it may not mutate its local roster.

### 14.6 Scoreboard and presentation

Every normal player presentation path should use roster identity:

- scoreboard row, name, frags, deaths if tracked, class/color;
- `[BOT]` label or icon;
- kill/death messages;
- end-of-match tally;
- join/lobby roster; and
- debug/admin listing.

Do not give bots a separate score table. The ordinary `player_t::frags` and
match result code remain authoritative.

Chat taunts are deferred. Silence is preferable to copied, repetitive, or
inappropriate text assets.

### 14.7 Limits

`MAXPLAYERS` is currently 11 while the Corridor 7 multiplayer menu has a
smaller human-facing range. Decide and document the supported total-slot cap
from actual gameplay/network/UI tests. The bot system must not introduce an
additional arbitrary cap and must test the chosen maximum.

The command-line and menu layers must validate counts before narrowing or
array indexing. Error messages should state human count, bot count, total, and
supported maximum.

---

## 15. Determinism, recording, saving, diagnostics, and performance

### 15.1 Determinism boundary

Host-only AI makes the boundary explicit:

- **Not part of replicated playsim:** bot memory, utility scores, open lists,
  aim-noise state, and private PRNG.
- **Replicated input:** finalized bot `TicCmd_t` for an explicit slot and
  sequence.
- **Replicated simulation:** ordinary pawns, actors, inventory, map specials,
  damage, score, and time.

Every peer must receive byte-equivalent canonical commands for every active
slot. A bot bug can make a bad decision, but it must not create a client/server
decision disagreement.

### 15.2 Command recording and replay

The legacy demo format is not adequate: it records only a subset of one local
player's input and multiplayer recording bypasses the normal network path.

Recommended policy:

- Leave legacy demos unchanged and explicitly unsupported for mixed bot
  multiplayer.
- Design a versioned multiplayer command recording only after the command
  bundle/roster protocol is stable.
- Record the canonical roster, rules, map/data hash, protocol version, match
  seed, input delay, and final command for every active slot/sequence.
- Replay recorded commands; do not re-run a historical AI implementation.
- Include periodic comprehensive state digests and clear truncation/error
  handling.

This creates a powerful bot bug reproducer without making replay depend on
private brain serialization.

### 15.3 Save games

Multiplayer saves are currently disabled. Keep offline bot-deathmatch saves
explicitly unsupported in the first release unless there is a strong product
requirement.

If later enabled, the archive must include:

- session roster/controller kinds;
- bot profile IDs and private RNG state;
- state machine and timers;
- perception/memory with stable identities;
- goal and path state or enough data for a documented safe rebuild;
- aim/motor state;
- world-event queue position; and
- version migration/validation.

Never serialize raw bot actor pointers or silently reset the brain on load in a
way that grants/loses knowledge unpredictably.

### 15.4 Structured bot trace

Add an opt-in host trace, preferably JSON Lines or another streamable stable
format. Each record should include only fields relevant to its type.

Event types should cover:

```text
roster/profile/seed initialization
sense update and released perception event
memory update/expiry
state transition
goal candidates, scores, selected/rejected goal
path request/result/cost/expansions/invalidation
typed traversal progress
target acquisition/loss/switch
ideal bearing, delayed bearing, aim error, yaw command
weapon candidates/choice/fire decision
stuck detection/recovery phase
final command and validation result
damage/death/respawn/frag observation
per-tic or periodic CPU/budget counters
```

Every record needs match/session ID, map, match seed, slot, command sequence,
and simulation tic as applicable. Traces should be off by default and must not
change timing-sensitive decision results or PRNG advancement.

Suggested capture switch:

```text
--capture-bots <path-or-prefix>
```

For automated gates, also support a compact canonical command/state digest that
is easy to compare across runs.

### 15.5 Developer overlays

Host/local developer visualization should be able to show, for one selected
bot:

- walkable nodes and typed/dynamic edges;
- current path, smoothed segments, and waypoint;
- local collision feelers;
- current high-level state and goal;
- top utility candidates;
- FOV, visible contacts, last-seen/heard regions, and confidence;
- ideal aim, delayed perceived aim, commanded aim, and error envelope;
- current weapon utility and fire gate reason;
- stuck/progress counters; and
- per-layer update/budget timing.

The overlay is diagnostic only. The bot must never read its results, render
visibility, camera, or screen coordinates.

### 15.6 Debug console output

Avoid an undifferentiated flood. Use categories and slot filters:

```text
bot_debug_state
bot_debug_sense
bot_debug_goal
bot_debug_path
bot_debug_move
bot_debug_aim
bot_debug_weapon
bot_debug_command
bot_debug_timing
```

State changes and failures should be available without per-tic output. A
one-line bot summary should state slot/name/profile, state, goal, target,
waypoint, health/weapon, last command, and stuck status.

### 15.7 Simulation digest

Extend test-only state comparison beyond actor positions. At minimum include:

- active roster hash and rules;
- command sequence and canonical commands by slot;
- complete relevant gameplay RNG state/hash;
- player state, health, frags, inventory/ammo, ready/pending weapon;
- actor identity/class/position/angle/health/flags/state;
- item active/respawn state;
- door, pushwall, forcefield, transporter-related mutable state;
- match timer/limit/result; and
- bot-command digest on the host.

The digest must have stable ordering and fixed-width encoding. It should report
the first divergent component, not only one opaque final checksum.

### 15.8 Performance budgets

Measure on a documented low-end supported system and optimized release build.
Initial engineering targets, subject to baseline measurement:

- command/motor update has fixed bounded work per bot/tic;
- vision scans iterate bounded stable candidates and are staggered;
- A* expansions are capped per bot and globally per tic;
- no allocations in the 70 Hz command hot path after map initialization;
- shared map graph memory is independent of bot count;
- per-bot state has a documented upper bound;
- 10 bots do not make the 70 Hz playsim miss its frame/tic budget in headless
  or normal rendering tests; and
- bot AI p95/p99 time and worst search expansions are captured in soak output.

Do not hide budget overruns by skipping required command output or using wall
clock-dependent behavior. Defer a tactical think or continue an incremental
search deterministically while immediate command generation remains complete.

### 15.9 Failure diagnostics

Fatal consistency failures must identify:

- session and protocol version;
- map and data hash;
- match/bot seed;
- peer and slot ownership;
- expected and received sequence/mask;
- profile ID;
- last good state digest; and
- trace location if enabled.

A nav/AI failure should degrade to a bounded safe roam/reselection behavior,
not corrupt network state. A malformed packet or ownership violation is a
network error and must be rejected, not passed to the bot.

---

## 16. Test and validation plan

Testing is part of the architecture. No milestone is complete merely because a
bot can be watched moving in one arena.

### 16.1 Test layers

Use five complementary layers:

1. **Pure unit tests:** roster validation, command finalization, math, PRNG,
   memory, utility, graph, A*, packet encoding/decoding.
2. **Synthetic gameplay fixtures:** small project-owned maps/scenarios that
   isolate doors, walls, LOS, pickups, hazards, transporters, and combat.
3. **Commercial-arena local gates:** run against the user's Corridor 7 files
   without committing or redistributing them.
4. **Multi-process network gates:** host/client command and world agreement
   under delay, loss, duplication, and reordering.
5. **Statistical/soak/playtest suites:** many seeds, long durations, maximum
   roster, performance, and human-likeness distributions.

Pure/synthetic tests should run without commercial data where feasible. Arena
integration gates may detect missing Corridor 7 files and report a deliberate
skip in environments that cannot legally contain them; they must run before a
local release is declared complete.

### 16.2 Roster and rule tests

Test every validation invariant:

- zero slots, one-slot deathmatch, more than `MAXPLAYERS`;
- zero peers, more peers than human slots, more peers than active slots;
- duplicate/missing slot IDs;
- empty hole when v1 requires contiguous slots;
- two peers owning one human slot;
- a remote peer owning a bot slot;
- bot owned by a non-host peer;
- invalid local/console slot;
- missing/invalid class or profile;
- duplicate/overlong/invalid display names;
- human plus bot count overflow before byte narrowing; and
- roster hash identical after encode/decode.

Gameplay semantic tests:

- one human plus bots is deathmatch even with no socket;
- it gets normal multiplayer respawning, items, damage, and no-monster rules;
- transport-only behavior remains off when `peerCount == 1`;
- save/pause/menu policy follows explicit session rules;
- spawning/rebirthing a remote or bot slot cannot change local-console
  projection, including an alternate-radius test once such a class is allowed;
- damaging/picking up/using a chamber as a remote or bot slot cannot update the
  local face, message, or status bar; and
- a single-player campaign remains unchanged.

### 16.3 Command finalization tests

For every axis/button:

- clamp values below/above range;
- convert desired yaw under profile rate and acceleration limits;
- derive held state from the prior applied button state exactly once;
- produce one-tic use and weapon-slot edges;
- hold/release automatic fire correctly;
- clear UI/pause/automap buttons;
- preserve local human automap/C7-map/status controls through the separate
  local-UI path without placing them in a network bundle;
- allow global pause in offline skirmish but reject/ignore it as a player
  command in network deathmatch;
- convert human/bot walk/run intent to the expected axis magnitudes and derive
  any run presentation from those magnitudes, not a replicated `bt_run` bit;
- emit neutral movement while dead/frozen;
- preserve ordinary command delay and sequence;
- reject duplicate commands and wrong ownership; and
- leave the command deterministic under a fixed seed/observation stream.

Add a test-only producer that emits a known command script through the bot
producer interface. This separates command/network plumbing from AI quality.

### 16.4 Human/bot rules parity test

Do this as two runs from the same complete reset snapshot, not two simultaneous
slots. Run A labels one fixed slot `Human`; run B restores world and every
gameplay RNG stream, labels that same slot `Bot`, and feeds the identical
finalized command sequence through the scripted producer. Simultaneous slots
would consume RNG/actor order differently and would not prove controller
parity. Compare the two runs for:

- displacement, angle, wall slide, collision, and trigger crossing;
- door use and waits;
- pickup results and inventory;
- selected/ready weapon state;
- ammo/energy consumption;
- firing states and projectiles under controlled RNG;
- received damage/death state;
- frag attribution; and
- respawn eligibility/path.

The only allowed difference is roster identity/controller metadata. This is the
most direct regression for the "same rules" contract.

Use simultaneous human/bot slots separately for network ownership and world-
digest consistency, not as the differential rules-parity oracle.

### 16.5 Protocol and packet tests

Unit/fuzz the startup roster and command-bundle decoder with:

- every truncation length;
- the current-start-packet regression: `numPlayers == N` has exactly `N - 1`
  trailing client entries, and decode validates that length before swapping any
  entry;
- oversized declared count;
- mask/count disagreement;
- slot IDs at and beyond bounds;
- unknown packet/protocol/session;
- old, current, too-far-future, duplicate, and wraparound sequences;
- sender-address/peer/slot ownership mismatch;
- remote attempt to command a bot;
- forbidden buttons and extreme axes;
- duplicate entries;
- reordered bundles;
- bit flips/random bytes; and
- maximum valid roster/bundle.

Decoder tests must run under address/undefined behavior sanitizers where the
toolchain supports them.

### 16.6 Network topology matrix

At minimum run:

| Case | Expected result |
| --- | --- |
| 1 local human + 1 bot, no socket | Starts, moves, fights, respawns |
| 1 local human + maximum supported bots | No fake peer wait; full command mask each tic |
| Host human + 1 bot + 1 remote human | Bot commands authored only by host; both peers agree |
| Host human + several bots + several remote humans | Correct owner mappings and command bundles |
| Interleaved human/bot slot IDs | Roster mapping, spawn, score, and command ownership remain correct |
| Headless bot-only developer match | Supports slot 0 bot without `ConsolePlayer` sensory/render dependence |
| Remote malicious bot-slot command | Rejected and diagnosed |
| Host disconnect | Match terminates cleanly; no client brain takeover |

Run mixed matches on direct loopback and through the existing userspace network
delay/loss harness. Preserve the current reference case of approximately 80 ms
round trip and 2% loss, then add burst loss, duplication, and reordering. Both
processes must report identical canonical commands and comprehensive world
digests for every completed tic.

### 16.7 Navigation unit tests

Build small graphs by hand and from synthetic maps. Cover:

- disconnected regions/no path;
- shortest path and stable equal-cost tie;
- diagonal corner-cut rejection;
- player-radius clearance;
- direct-path shortcut accepted/rejected by collision;
- typed interaction edge retained by smoothing;
- physical-cache invalidation versus per-bot belief-edge generation;
- transporter directed edge and traversal time;
- hazard costs changing route choice;
- incremental search budget/resume/cancel;
- goal changing during search;
- maximum path without silent truncation;
- multiple bots sharing immutable graph with separate workspaces; and
- deterministic trace for a fixed graph/request.

Parity-test the pure traversal query against real scripted pawn movement around
every boundary type.

### 16.8 Navigation integration tests

Required focused scenarios:

1. Approach the valid face of a closed door, turn, pulse use once, wait until
   collision permits traversal, and cross.
2. Use `MAP51`'s blue door with keys granted through ordinary battle inventory;
   verify no bot key bypass.
3. Attempt the wrong door face and recover without use spam.
4. Jam/close a door with an actor and require wait/replan.
5. Toggle a forcefield repeatedly: physical traversal changes immediately,
   the observing/nearby bot updates and replans, and an out-of-sight bot does
   not learn the new state until a fair observation/contact.
6. Change/remove/push a wall during an active route and require replan without
   teleport or direct position correction.
7. Exercise masked/open markers with separate movement, rendered visibility,
   gameplay LOS, and projectile assertions.
8. Traverse every transporter pair in `MAP56`, `MAP57`, and `MAP60`, including
   freeze, actual destination, and post-arrival replan.
9. Route around electric walls and contextually through/around laser barriers.
10. Place dynamic solid scenery or a temporary combat obstruction on a path
    and exercise the recovery ladder.
11. Run from every generated deathmatch spawn to several reachable goals.
12. Ensure no battle bot activates an exit switch.

For each of the eight arenas, a seeded roam test must visit multiple separated
regions, make continued progress, and avoid permanent stuck state. Coverage
should report visited graph nodes/edges and untraversed special edges rather
than merely "process exited zero."

### 16.9 Perception tests

Test exact facts available to the decision layer:

- enemy in FOV and clear LOS becomes an event only after configured delay;
- enemy behind bot is not visually acquired;
- turning naturally brings it into FOV;
- wall/masked boundary blocks/allows according to canonical gameplay LOS;
- occluded target position stops refreshing and memory uncertainty grows;
- target slot ties are stable;
- dead/nonshootable/self slots are excluded;
- renderer offscreen/headless state does not alter observations;
- `ConsolePlayer` camera and `MapSpot::visible` do not affect a bot;
- unseen active/inactive item state is not exposed;
- an unseen remote door/forcefield/wall toggle invalidates collision caches but
  does not update that bot's tactical observation/belief;
- visible empty pickup location updates memory;
- weapon/door sound yields delayed approximate hearing within range/zone;
- sound outside range/closed connectivity is absent or appropriately degraded;
- damage cue contains no more identity/precision than the chosen fairness rule;
- hidden laser is not visually observed without infrared;
- contact can create hazard memory; and
- infrared makes the laser visually observable through the normal equipment
  path.

Add a negative-test sensor implementation that deliberately places a hidden
enemy in the global world and asserts the serialized observation contains no
coordinate/actor identity leak.

### 16.10 Decision and memory tests

Use immutable synthetic observations to assert:

- critical health increases safe health utility;
- full ammo reduces matching ammo utility;
- unusable/unowned-weapon ammo is valued correctly;
- stale/uncertain pickup loses value;
- current-goal hysteresis prevents tiny-score thrash;
- large new threat interrupts a low-priority goal;
- target switch requires a material reason;
- lost contact enters bounded search then expires;
- no candidate appears for a fact absent from observations/static knowledge;
- failed path cools down the goal/edge;
- fixed profile/seed/observation sequence gives a fixed state/goal trace; and
- decision explanations contain each candidate term and rejection reason.

### 16.11 Movement and stuck tests

Assert:

- every output remains inside global/profile axis/yaw envelopes;
- 90° and 180° turns take nonzero bounded time;
- yaw speed and acceleration do not jump over profile limits;
- route follower slows/turns through a tight corner;
- broad corridor offsets remain inside clearance;
- combat strafe persists for its commitment interval;
- a blocked waypoint triggers the ordered recovery ladder;
- recovery never mutates position/angle/collision;
- a reachable obstruction scenario eventually resumes progress; and
- an unreachable scenario abandons cleanly with diagnostics.

### 16.12 Combat and inventory tests

For every supported weapon:

- acquire only a visible/released target;
- select via ordinary command and wait for switch;
- consume real ammo/energy/capacity;
- honor weapon-ready and refire behavior;
- preserve gameplay hit/miss/damage randomness;
- stop or switch on depletion;
- maintain profile turn/reaction/aim limits; and
- never call damage directly.

Special cases:

- hitscan shots both inside and outside the auto-target cone;
- shotgun range/recovery;
- plasma lead, wall impact, opponent collision, self-splash;
- disintegrator broad multi-target behavior and resource cost;
- mine placement, arming, owner clear, shootable explosion, self-risk;
- visor activation and charge; and
- inventory pickup/stay/respawn semantics.

Death cases must include opponent kill, suicide/self-splash, electric wall,
laser, and other environmental damage. Assert ordinary frag changes and
ordinary respawn timing.

### 16.13 Fairness invariants

Automated instrumentation and code review must prove:

- no bot-source direct write to pawn coordinates/angle/health/inventory/
  weapon/frag/state;
- no bot-source call to movement, trigger, pickup, damage, die, or spawn APIs;
- no forbidden buttons;
- no command-rate or range advantage;
- no dynamic world query outside the sensor/local-collision boundary;
- no unseen enemy/item/laser leak in observations;
- no gameplay RNG consumption by bot variation;
- no response before configured sensory/reaction delay;
- no profile changes pawn rules/statistics; and
- remote clients cannot author bot commands.

Static analysis/grep can assist but is not sufficient. Interface visibility,
const/value observations, runtime provenance assertions, and adversarial tests
provide stronger enforcement.

### 16.14 Statistical skill tests

Run hundreds or thousands of fixed-seed engagements per profile and report,
not merely pass/fail:

- reaction and target-switch latency distribution;
- yaw rate/acceleration percentiles;
- aim error at firing by weapon/range;
- trigger hesitation, burst, release distribution;
- accuracy/damage by weapon/range/movement;
- goal switches per minute;
- path efficiency and stuck time;
- resource pickups by need;
- deaths to self/hazards;
- frags/deaths versus fixed scripted opponents and other profiles; and
- CPU/search budget percentiles.

Hard gates should include:

- no normal skill has zero minimum reaction;
- no normal skill has perfect long-run contested accuracy;
- increasing skill generally improves appropriate median metrics without
  changing rules;
- every skill retains misses and imperfect decisions;
- configured motor/reaction bounds are never violated; and
- fixed scenario/seed results are reproducible.

Do not require strict monotonic win rate for every small sample; variance and
weapon/map matchups make that flaky. Use confidence intervals and sufficiently
large deterministic seed sets.

### 16.15 Soak, stress, and performance tests

Two standard durations:

- **Per-change soak:** at least 100,000 simulation tics across rotating arenas
  and seeds.
- **Release/nightly soak:** at least 1,000,000 simulation tics, maximum
  supported bots, map changes/restarts, and mixed weapons/specials.

Fail on:

- crash, assertion, sanitizer error, leak growth, or invalid memory access;
- network/world digest divergence;
- missing command/deadlock;
- bot permanently stuck beyond defined recovery limit;
- out-of-range/forbidden command;
- unbounded graph/search/event/memory growth;
- missed real-time/tic budget beyond the established threshold; or
- map/match transition retaining stale bot state.

Record high-water memory, per-layer timing, A* expansions, retries, path
failures, stuck recoveries, perception/event counts, and final result.

### 16.16 Suggested gates/scripts

Names are suggestions consistent with the current tool suite:

```text
tools/test_multiplayer_bots_roster.sh
tools/test_multiplayer_bots_commands.sh
tools/test_multiplayer_bots_offline.sh
tools/test_multiplayer_bots_loopback.sh
tools/test_multiplayer_bots_latency.sh
tools/test_multiplayer_bot_navigation.sh
tools/test_multiplayer_bot_perception.sh
tools/test_multiplayer_bot_combat.sh
tools/test_multiplayer_bot_fairness.sh
tools/test_multiplayer_bots_arenas.sh
tools/test_multiplayer_bots_soak.sh
```

Integrate fast deterministic gates into `tools/run_gates.sh`; keep long soak and
commercial-data gates clearly selectable. Every script must preserve logs on
failure, terminate all child processes, use independent local ports, and print
the exact reproduction command/seed.

### 16.17 Playtesting protocol

Automation cannot decide whether a bot feels human.

For each skill, run blind or minimally labeled mixed matches and ask testers to
record concrete observations:

- unfair information/instant response;
- robotic turning or pathing;
- believable misses versus obvious random sabotage;
- target persistence/switching;
- door/transporter competence;
- resource and weapon choices;
- camping/aggression balance;
- difficulty progression; and
- moments where trace reasoning contradicts what was visible/audible.

Pair each report with map, seed, profile, slot, approximate tic/time, and trace.
Do not tune solely from win/loss anecdotes.

---

## 17. Implementation milestones

Each milestone must end with a demonstrable vertical result and automated exit
gate. Do not start with aim tuning before the roster, command, and perception
boundaries exist.

### B0 — Freeze requirements and repair prerequisites

**Purpose:** establish reliable human deathmatch and lock the bot contracts.

Tasks:

- Review/approve this plan's fairness and authority decisions.
- Finish or explicitly sequence multiplayer arena, damage/frag, match-limit,
  scoreboard, protocol compatibility, and projectile fixes.
- Resolve or constrain network mouselook/pitch.
- Fix the existing `StartPacket` trailing-client off-by-one and ensure no
  byte-swap occurs before exact trailing length/count validation.
- Make projection and HUD presentation console-player-specific, or explicitly
  constrain v1 player classes to the same radius until projection is fixed.
- Record baseline loopback/latency/checksum and release performance.
- Add an architecture test or code comment documenting the command-only rule.
- Decide supported total slots and whether the first UI exposes individual
  slots or counts.

Exit:

- Human-only deathmatch tests for arenas, damage, frags, respawn, and match
  result pass.
- Valid and truncated legacy/new startup-packet tests prove that an `N`-player
  packet reads/swaps exactly `N - 1` trailing client entries and no more.
- Known adjacent defects are fixed or have explicit tracked blockers.
- Authority, roster, skill names, map knowledge, and initial feature subset are
  approved.

### B1 — Session rules and roster/peer split

**Purpose:** represent mixed controller ownership without any AI.

Tasks:

- Add `g_session` roster/rules model.
- Replace/rename ambiguous player counts and classify every loop.
- Add slot kind, peer ownership, class, name, profile placeholder, and seed.
- Separate gameplay rule predicates from transport mode.
- Version and validate startup roster handshake.
- Make class/start/spawn/score loops consume active slots.
- Make socket/ack/join/disconnect loops consume peers.
- Add offline deathmatch session with one local peer.

Exit:

- A roster can contain placeholder bot slots without waiting for fake peers.
- Offline one-human-plus-placeholder deathmatch reaches gameplay.
- Host/client agree on mixed roster hash and ordinary human commands.
- All B1 roster/rule/protocol tests pass under sanitizers.

### B2 — Multi-slot authoritative command transport

**Purpose:** carry host-owned commands for more than one slot.

Tasks:

- Refactor command producers/finalization.
- Introduce versioned command bundles and per-slot history/gather mask.
- Validate sender ownership, range, button whitelist, and sequence.
- Include host human plus placeholder bot commands in one bundle.
- Integrate input delay/resend for every owned slot.
- Add canonical per-slot command trace/digest.

Use a scripted `DummyBot` that alternates neutral movement or follows a fixed
known command tape. It has no world queries.

Exit:

- Offline and two-process mixed rosters execute scripted bot commands.
- All peers report byte-identical per-slot commands and world digests under
  delay/loss.
- A remote bot-slot command is rejected.
- No bot AI code exists beyond the scripted command producer.

### B3 — Bot manager, lifecycle, and basic locomotion

**Purpose:** create a real controller that remains an ordinary player.

Tasks:

- Add `BotManager`, per-slot state, private PRNG streams, update scheduling,
  command validation/provenance, and death/respawn lifecycle.
- Add base tile graph and side-effect-free traversal query.
- Implement stable integer A*, direct route, smoothing, basic follower, and
  progress/stuck diagnostics.
- Implement `SpawnOrient`, `Roam`, `UseDoor`, `Unstuck`, and ordinary respawn.
- Add graph/path/state overlays and trace.

Exit:

- A bot spawns, roams through simple map regions, uses a normal door, dies, and
  respawns through input.
- It never mutates actor state outside commands.
- Synthetic nav/parity tests and `MAP53` baseline roam pass.

### B4 — Complete arena traversal

**Purpose:** make movement robust before combat distracts from it.

Tasks:

- Add physical-cache invalidation plus per-bot perceived/believed portal state
  for doors/forcefields/walls/pushwalls.
- Add transporter typed edges, freeze handling, and post-arrival replan.
- Add hazard annotations/costs and local dynamic avoidance.
- Complete stuck recovery ladder and route failure cooldowns.
- Exercise all real arena starts/regions/specials.

Exit:

- All eight arena traversal tests pass over multiple seeds/spawns.
- Every transporter pair is exercised.
- No permanent stuck state in the navigation soak threshold.
- Battle exit switches are never activated.

### B5 — Perception, hearing, and memory

**Purpose:** build the fairness boundary before target selection.

Tasks:

- Add immutable observations and sensor-only world access.
- Add FOV/gameplay LOS player/item/projectile/hazard observations.
- Add stable entity identities where required.
- Add semantic sound event ring and per-bot hearing filters.
- Add reaction queue, contact/item/hazard memory, uncertainty, and expiry.
- Add infrared-gated laser perception and headless/offscreen tests.

Exit:

- A bot detects, loses, hears, searches for, and forgets a scripted player with
  exact expected timing.
- No through-wall/current-hidden-position or unseen-item leak exists in
  adversarial tests.
- Renderer/`ConsolePlayer` state has no effect.

### B6 — Goals and resource play

**Purpose:** make a noncombat bot navigate purposefully.

Tasks:

- Add utility candidates, need/value model, path-cost queries, commitment,
  hysteresis, and goal cooldown.
- Implement visible/remembered health, armor, invulnerability, weapon, ammo,
  energy/capacity, mine, and visor-charge goals.
- Respect inactive item and weapon-stay/respawn semantics.
- Add state/goal explanation trace.

Exit:

- Seeded scenarios select and collect the expected resource for explainable
  reasons.
- Goals do not thrash and do not use unseen current availability.
- Arena item-navigation soak makes progress without unbounded replans.

### B7 — Baseline deathmatch combat

**Purpose:** deliver the first genuinely playable bot opponent.

Tasks:

- Add target acquisition/switching from observations.
- Add delayed aim samples, bounded yaw motor, correlated error, and fire gate.
- Add combat strafe/range movement.
- Add weapon selection and support for bayonet, M16, M343, dual blaster,
  shotgun, plasma, assault cannon, and disintegrator.
- Add chase/search/retreat behavior.
- Keep mines/visor optional behind explicit support flags until validated.

Exit:

- Human versus bot and bot versus bot matches produce ordinary kills, frags,
  deaths, resource consumption, and respawns.
- Every weapon-specific deterministic mechanics test passes.
- Bot visibly misses and reacts within profile bounds.
- No fairness invariant fails.

### B8 — Special equipment and behavioral depth

**Purpose:** cover Corridor 7-specific tactical mechanics.

Tasks:

- Implement/test mines and self-risk.
- Implement/test visor decisions and hidden-laser visibility.
- Improve transporter/door combat behavior.
- Tune hazard/resource/weapon utility.
- Add personality biases without changing skill fairness.

Exit:

- Mine, visor, disintegrator, plasma, hazards, transporters, and doors all have
  focused passing tests.
- No equipment action bypasses normal input/inventory.

### B9 — Humanization and skill calibration

**Purpose:** turn functional controllers into credible fallible opponents.

Tasks:

- Implement the four profile mappings and fairness clamps.
- Calibrate reaction, perception, yaw, correlated error, cadence, strafe,
  commitment, route imperfection, and memory.
- Collect statistical reports and opt-in human baseline samples.
- Conduct mixed blind playtests and trace-backed tuning.
- Prevent an ordinary `Perfect`/zero-delay configuration.

Exit:

- Statistical bounds and reproducibility gates pass.
- Skill progression is perceptible without statistic cheats.
- Elite remains measurably fallible.
- Playtest reports find no repeatable wallhack, snap aim, or rules bypass.

### B10 — UI, presentation, administration, and recording

**Purpose:** make the feature understandable and supportable.

Tasks:

- Add human/bot/total/skill lobby controls and validation.
- Add offline skirmish route.
- Add roster identity, `[BOT]` scoreboard/kill/tally presentation.
- Add host-only list/fill/remove-at-boundary administration.
- Document command-line/debug/profile controls.
- Optionally add versioned final-command recording; otherwise document demo
  limitation explicitly.

Exit:

- Menu and command-line gates create identical validated rosters.
- Joining peers see the same locked bot presentation.
- Names/counts/errors display safely at minimum/maximum bounds.

### B11 — Hardening, soak, documentation, and release

**Purpose:** prove the whole feature under real conditions.

Tasks:

- Run protocol fuzz/sanitizers and maximum-roster stress.
- Run per-change and release-duration soak on all arenas.
- Run loopback latency/loss/reorder mixed matches.
- Measure/meet CPU and memory budgets.
- Audit licensing/provenance and all fairness interfaces.
- Update user/admin/mod documentation and known limitations.
- Ensure gates retain exact seeds/traces on failure.
- Build optimized release package through the project packaging script.
- Test startup from the packaged copy in its own directory.

Exit:

- The complete definition of done in section 20 is satisfied.
- `ECWolf/tools/package_corridor7_release.sh` refreshes
  `builds/release` as a self-contained package.
- `ECWolf/tools/test_corridor7_release_startup.sh builds/release` passes
  against that packaged copy.
- Commercial Corridor 7 files remain uncommitted and are not redistributed.

---

## 18. Concrete work breakdown and source audit

### 18.1 Dependency graph

```text
human deathmatch correctness / protocol baseline (B0)
                         |
                         v
session roster + peer/slot split (B1)
                         |
                         v
authoritative multi-slot commands (B2)
                         |
                         v
bot lifecycle + graph + locomotion (B3)
                 |                       |
                 v                       v
complete arena traversal (B4)     perception boundary (B5)
                 |                       |
                 +-----------+-----------+
                             v
                     resource goals (B6)
                             |
                             v
                     baseline combat (B7)
                             |
                             v
                equipment and depth (B8)
                             |
                             v
               humanization/calibration (B9)
                             |
                             v
                   UI/presentation (B10)
                             |
                             v
                 hardening/release (B11)
```

UI wire-up can begin once B1 stabilizes, diagnostics begin in B2/B3, and
performance measurement begins with the first graph. Their final acceptance
still occurs at the listed milestones.

### 18.2 Source-area checklist

The exact files may change, but this is the expected audit/touch surface.

| Area | Expected work | Constraint |
| --- | --- | --- |
| `src/g_session.*` (new) | Rules, roster, identities, slot/peer ownership, hashes | No transport implementation inside session rules |
| `src/wl_net.h/.cpp` | Versioned startup roster, peer mapping, command bundles/history, validation | Peer loops and active-slot masks must be explicit |
| `src/wl_play.h/.cpp` | Canonical command intent/finalization, bot hook, per-slot commands | Build all commands before thinker ticks; no AI during player iteration |
| `src/wl_main.cpp` | CLI validation, match/session initialization, class setup | Validate counts before narrowing/indexing |
| `src/wl_game.cpp` | Level/map lifecycle hooks and bot-manager reset | Keep normal map/spawn setup authoritative |
| `src/wl_agent.h/.cpp` | Semantic rule calls, stable player slot use, projection/HUD guards, pure traversal seam if appropriate | No bot-specific movement/damage/spawn path; projection follows console camera |
| `src/g_shared/a_playerpawn.cpp` | Session-rule respawn checks; command parity tests | Bot still reaches every action through `TicCmd_t` |
| Inventory/key code | Replace transport-mode gameplay assumptions | Preserve ordinary battle pickup/stay/respawn behavior |
| `src/gamemap.h/.cpp` | Runtime graph data access, stable transitions, physical-cache invalidation hooks | Bot graph consumes translated state; invalidation does not leak unseen changes |
| `src/gamemap_planes.cpp` | Stable map/spawn/transition identity if missing | Translation remains the authority |
| `src/lnspec.cpp` | Door/wall/transporter topology and semantic sound events | No bot-specific special activation |
| `src/wl_state.cpp` | Canonical LOS/collision query reuse | Do not reuse monster locomotion as bot movement |
| `src/actor.*` / thinker lifecycle | Stable non-pointer entity serial or invalidation seam if needed | Stable across a match/recording; no GC pinning leaks |
| `src/g_bot*` (new) | Manager, sensor, memory, state/utility, nav, combat, humanizer, debug | Read-only observations; command-only output |
| C7 weapon/action code | Semantic shot/explosion events and focused combat fixes | Ordinary weapon outcomes remain authoritative |
| `src/r_capture.cpp` | Command/bot/full-state trace/digest | Stable ordering; test-only behavior must not alter simulation |
| `src/wl_menu.cpp` | Human/bot counts/skill/skirmish/lobby validation | Host authoritative; join view read-only |
| Scoreboard/HUD/intermission | Roster names, bot marker, results | Use ordinary frags/result model |
| `src/CMakeLists.txt` | Add new sources/tests | Follow existing explicit source style |
| `wadsrc/static/...` | Optional later profile descriptors/documentation | Do not copy external personas/scripts/assets |
| `tools/` | Unit/scenario/network/arena/soak/package gates | Preserve seeds/traces; clean up child processes |
| `docs/` | User/admin/mod/design/provenance documentation | State unsupported saves/demos/live roster changes honestly |

### 18.3 Full transport-mode audit

Search and classify every occurrence of:

```text
Net::InitVars.mode
Net::InitVars.numPlayers
MODE_SinglePlayer / MODE_Host / MODE_Client
Client[
ConsolePlayer
players[
control[
```

For each relevant occurrence, record one classification in the implementing
change:

- transport peer concern;
- active gameplay slot concern;
- local human/view concern;
- session rules concern;
- legacy single-player-only concern; or
- intentionally unchanged with explanation.

This prevents an offline bot match from accidentally taking campaign death,
pause, item, sound, or save behavior because no remote socket exists.

### 18.4 Command-path audit

Trace every field of `TicCmd_t` from physical input and network decoding to
`APlayerPawn::Tick`. Decide:

- whether it is simulation-critical;
- whether it is currently transmitted;
- whether a bot may emit it;
- its canonical range/encoding;
- its held/edge semantics; and
- whether it is local UI only.

Resolve pitch/pan and `Button` enum/protocol-layout issues before freezing the
new bundle version. Prefer explicit serialized fields/bit masks over sending a
raw compiler-dependent struct or all of `NUMBUTTONS` without protocol meaning.

### 18.5 Gameplay special audit

For every special present in a real network arena, document:

- how a human activates/crosses it;
- map/runtime representation;
- collision and LOS effect while changing;
- associated sound/visual cue;
- bot graph edge or hazard type;
- allowed sensor knowledge;
- path invalidation event;
- failure/timeout behavior; and
- focused regression.

The initial list is doors/locks, masked apertures, forcefields, removable or
animated walls, pushwalls if present/supported, transporters, electric walls,
laser barriers, item respawns, mines, and exit switches.

### 18.6 Weapon audit template

For each player weapon, fill a reviewed descriptor/test row:

```text
class / slot / pickup behavior
attack button and ready/refire requirements
ammo types and costs
attack frame/cycle timing
hitscan cone or projectile speed
range/splash/multi-target semantics
self-damage and wall interaction
sound/perception event
selection utility inputs
aim/fire humanization parameters
focused mechanics and statistical test IDs
```

Derive mechanics from actor definitions/native actions and tests. Do not
duplicate damage or timing constants in AI unless there is a single shared
descriptor source or a validation that detects drift.

### 18.7 Ownership and lifecycle table

| Data | Owner | Lifetime | Networked/recorded |
| --- | --- | --- | --- |
| Match roster/rules | Session/host | Lobby lock through match | Sent and hashed; recorded |
| Peer/socket mapping | Net transport | Connection | Sent as needed; not gameplay save |
| Ordinary player/pawn | Playsim | Map/respawn lifecycle | Deterministic simulation |
| Shared static potential nav graph | Bot navigation | Loaded map | Host-only map-learnable data; no hidden dynamic facts |
| Physical traversal cache | Collision/navigation query | Loaded map, invalidated by world changes | Host-only correctness data; inaccessible to tactical planning |
| Per-bot belief overlay | Each `BotState` | Loaded map, updated by that bot's senses/contact | Host-only individual knowledge; never shared between bots |
| Bot profile/identity | Session + BotManager | Match | Profile ID/seed sent; full profile hashed |
| Bot sensory memory/state | BotManager | Match/map with explicit reset rules | Host-only; trace, not live network |
| Bot private PRNG | BotManager | Match | Host-only; trace/optional save |
| Final command history | Net/command layer | Resend/replay window | Sent; recorded |
| Sound gameplay event ring | World sensor service | Bounded recent tics | Host brain input; world effects already deterministic |
| Debug trace | Capture service | Opt-in file | Never affects live authority |

Define reset behavior explicitly:

- New match: create roster identities, seeds, profiles, empty memories.
- New map/round: rebuild the static graph/physical cache and each empty belief
  overlay, clear paths/contacts/events, and retain only identity/personality and
  match-level score as rules require.
- Death/respawn: clear immediate route/aim/fire; retain fair learned map and
  bounded opponent memory according to chosen policy.
- Disconnect/end: destroy all brain state and command ownership before menu.

### 18.8 Change/PR slicing

Keep reviewable invariants by slicing changes approximately as follows:

1. session/rule predicates with no behavior change;
2. roster type and count-loop migration;
3. startup protocol version/roster validation;
4. multi-slot command bundle with scripted producer;
5. offline placeholder bot lifecycle;
6. graph/pure traversal tests;
7. route follower/door/unstuck;
8. dynamic specials/transporters/hazards;
9. observation boundary and vision;
10. hearing/events/memory;
11. utility/resources;
12. aim/combat one weapon family at a time;
13. remaining weapons/equipment;
14. profiles/calibration;
15. UI/presentation/admin;
16. hardening/docs/release.

Each slice should compile and pass the prior gates. Avoid a single merge that
simultaneously rewrites netcode, movement, navigation, aim, and UI; failures
would be impossible to localize.

### 18.9 Review checklist for every bot change

- Does it preserve command-only actor interaction?
- Does it add or bypass a world-information path?
- Is every iteration/tie/order stable where reproducibility matters?
- Can a count/index/packet value exceed a fixed array?
- Does it consume a gameplay RNG stream?
- Does it depend on wall clock, renderer, local camera, or `ConsolePlayer`?
- Does it change human/campaign behavior unintentionally?
- Does it handle death, map change, roster destruction, and invalid targets?
- Is expensive work bounded and measured?
- Is the new decision visible in diagnostics?
- Is there a negative/adversarial test as well as a happy-path test?
- Are provenance/license implications documented?

---

## 19. Risk register

| Risk | Impact | Warning sign | Mitigation/gate |
| --- | --- | --- | --- |
| Player slots remain conflated with peers | Startup/tic deadlock | Host waits for a bot socket or ack | B1 compiler-level count split and mixed-roster tests |
| Host bot bundle diverges/misses sequence | Lockstep stall/desync | Missing active-slot bit | Per-sequence required mask, resend history, fatal host diagnostics |
| Bot reads hidden world state | Unfair wallhack/item control | Reactions through walls or to unseen pickup respawn | Immutable sensor boundary, adversarial leak tests, trace review |
| Direct actor mutation slips in | Bots break human rules | Snap turn, forced move/fire/damage | Narrow output API, provenance assertions, code/fairness audit |
| Navigation disagrees with real collision | Stuck/invalid shortcuts | Bot predicts open but pawn cannot cross | Side-effect-free shared query and differential parity tests |
| Dynamic special changes out of sight | Repeated wall/door failures or unfair instant replan | Old route persists forever, or every bot knows instantly | Invalidate only physical cache globally; update/replan per bot after perception/contact |
| Masked-wall semantics remain inconsistent | Bots shoot/see unlike visible world | LOS/render/projectile tests disagree | Fix canonical gameplay semantics; focused regressions before tuning |
| Transporter loops/freeze mishandled | Bot oscillates or fights movement state | Repeated pair traversal/no progress | Typed directed edges, arrival replan, cooldown, all-pair tests |
| Hidden laser actor scan | Unfair avoidance | Non-infrared bot never contacts known lasers | Equipment-gated sensor and negative tests |
| Aim looks superhuman | Poor/fraudulent experience | Instant turn, zero reaction, exact tracking | Motor/reaction floors, correlated error, statistical gates |
| Aim looks randomly broken | Unconvincing AI | White-noise jitter, absurd misses | Stateful motor process, context-scaled error, time-series metrics |
| Utility thrashes | Robotic indecision/CPU cost | Many goal switches/repaths per second | Commitment, hysteresis, cooldowns, traced candidate scores |
| Actor pointer identity is unstable | Wrong memory target/use-after-free/nondeterminism | Target changes on allocation order | Stable slot/entity serials and invalidation tests |
| Private AI RNG changes gameplay RNG | Behavior changes weapon/damage results | Adding debug choice alters combat roll | Separate named/fixed streams and gameplay RNG digest |
| Brain CPU spikes at maximum bots | Missed 70 Hz budget | All bots A* on same tic | Staggering, per-bot/global budgets, incremental search, p99 gate |
| Event/memory queues grow unbounded | Memory/CPU leak | Long soak growth | Fixed-capacity/rate-limited rings, expiry, high-water assertions |
| Remote client forges bot input | Cheat/desync | Bundle includes unowned bot slot | Session/peer/slot ownership validation and adversarial packets |
| Startup parser trusts lengths/counts | Security/memory fault | Truncated roster reads past packet | Exact decode validation, fuzzing, sanitizers |
| Profiles bypass fairness bounds | Superhuman/mod mismatch | Zero delay or excessive turn | Post-parse hard clamps, profile hash, lobby rejection |
| Bot data differs across peers | Presentation/protocol mismatch | Different class/name/profile hash | Host canonical roster and compatibility hash before spawn |
| Host departure loses brain authority | Frozen bot inputs | Clients wait for next host bundle | Explicit match termination; no implicit host migration |
| Legacy demo/save silently corrupts state | Bad replay/load | Bot disappears or decisions diverge | Explicitly disable or implement versioned full command/state format |
| Gameplay bugs get patched in AI | Permanent duplication/workarounds | Map/class-specific AI exceptions | Fix canonical player rule first; parity tests |
| External source copied carelessly | License/provenance failure | Notices/assets missing | Original implementation, pinned reference log, file-level audit |
| Commercial game data enters commit | Redistribution violation | MAP/GAMEDATA files in status/archive | Status/package audit; never stage or commit `CORR7CD` contents |
| Statistical gates become flaky | CI distrust | Small random sample crosses hard threshold | Fixed seed sets, confidence intervals, invariant gates separated from balance reports |
| Debug capture alters decisions/timing | Irreproducible observer effect | Trace-on command stream differs | No RNG/work-order changes, trace-on/off command equality test |
| Campaign/other ECWolf games regress | Broad engine regression | Rules or input change outside C7 deathmatch | Existing full gates plus explicit single-player/non-C7 regression runs |

### 19.1 Highest-risk decisions

The four risks to retire earliest are:

1. roster/peer separation without regressing existing lockstep;
2. multi-slot host command buffering/resend under real delay/loss;
3. collision-equivalent navigation around dynamic Corridor 7 specials; and
4. a perception API that is useful without exposing omniscient actor state.

If any of these proves infeasible, revise the architecture before extensive
combat behavior is built.

### 19.2 Host-authority fallback conditions

Host-authoritative commands are already the recommended primary design. If
bandwidth or packet behavior later creates a real measured problem, optimize in
this order:

1. compact button masks and fixed-width command fields;
2. bundle all host-owned slots per sequence;
3. delta/repeat encoding for unchanged commands with loss-safe history;
4. lower redundant resend volume without weakening recovery; and only then
5. evaluate replicated deterministic brains behind an explicit protocol mode.

Do not switch to replicated brains merely because their first prototype avoids
packet work. Network optimization is easier to validate than distributed AI
state determinism.

---

## 20. Definition of done

The feature is complete only when every applicable item below is true.

### 20.1 Functional

- [ ] A normal interactive session can start with one local human and at least
  one bot without a network connection.
- [ ] A network session can mix host human, remote humans, and host-owned bots.
- [ ] The roster can represent a bot in any slot; interactive `ConsolePlayer`
  reservation is a UI policy, not a data-model limitation.
- [ ] The maximum exposed roster configuration starts, plays, changes map/round,
  and terminates cleanly.
- [ ] Bots spawn, move, turn, use doors, traverse transporters, collect items,
  select/fire weapons, take/deal damage, die, earn/lose frags, and respawn
  through ordinary paths.
- [ ] Every supported weapon and enabled equipment item has focused behavior
  and tests.
- [ ] Bots never activate battle exit switches.
- [ ] Scoreboard/lobby/results clearly identify bots and use ordinary frags.

### 20.2 Rules parity and fairness

- [ ] The human/bot identical-command parity scenario has no gameplay
  difference attributable to controller kind.
- [ ] Bot source cannot directly mutate pawn/world gameplay state.
- [ ] Every bot action is represented by one canonical bounded command per tic.
- [ ] Difficulty changes no pawn, damage, inventory, collision, weapon, or
  timing rule.
- [ ] Perception exposes no current hidden enemy/item/hazard state.
- [ ] Highest normal skill has finite reaction, bounded turning, nonzero
  tracking/aim error, and measurable misses.
- [ ] Bot variation consumes no gameplay RNG stream.
- [ ] Network input delay applies equally to local human and bot commands.

### 20.3 Navigation and arena coverage

- [ ] Base graph and traversal query agree with actual player movement.
- [ ] Doors, locks, dynamic walls/fields, hazards, and transporters are modeled
  with ordinary interactions.
- [ ] Every transporter pair in the three transporter arenas passes.
- [ ] Every real network arena passes multi-seed spawn-to-goal/roam coverage.
- [ ] Stuck recovery never teleports/noclips and satisfies the soak threshold.
- [ ] Perceived/locally encountered dynamic topology changes update only that
  bot's belief and replan safely; unseen changes do not leak.

### 20.4 Combat quality

- [ ] Target acquisition, tracking, memory, and search use only released
  observations.
- [ ] Reaction, yaw, aim error, trigger, and movement distributions remain
  inside profile bounds.
- [ ] Weapon choice respects actual possession, resources, readiness, range,
  and self-risk.
- [ ] Plasma/player collision and masked-wall gameplay prerequisites are fixed
  or their unsupported state is explicit and blocks release claims.
- [ ] All normal skill levels are fallible and show sensible progression over
  the fixed statistical suite.
- [ ] Mixed human playtests find no reproducible unfair-information or snap-aim
  behavior.

### 20.5 Networking, security, and determinism

- [ ] Startup handshake carries and validates versioned roster/rules/profile
  identity with exact length/count checks.
- [ ] Peer count, active slots, owner mapping, and command-required masks are
  distinct and validated.
- [ ] Only the host can author bot-slot commands.
- [ ] Loopback mixed matches maintain identical commands/world digest under
  configured delay, loss, duplication, and reordering.
- [ ] Malformed/truncated/forged packets fail decoder fuzz/sanitizer tests.
- [ ] Host disconnect terminates cleanly without silent authority takeover.
- [ ] Fixed seed/recorded command runs are reproducible.

### 20.6 Reliability and performance

- [ ] Fast unit/scenario/network gates are in the ordinary gate runner.
- [ ] All eight commercial-data arena gates pass locally without committing the
  game files.
- [ ] 100,000-tic per-change and 1,000,000-tic release soaks pass.
- [ ] Maximum supported bots remain within documented CPU, search, memory, and
  70 Hz budgets.
- [ ] Bot queues/searches/state remain bounded and release all resources on map
  or match exit.
- [ ] Trace-on and trace-off produce identical canonical commands for the same
  seed/scenario.
- [ ] Existing Corridor 7 campaign, non-bot multiplayer, and relevant ECWolf
  gates remain green.

### 20.7 Product, documentation, and release

- [ ] Lobby/skirmish/CLI/admin controls validate and explain bot configuration.
- [ ] User documentation states scope, skill behavior, host authority, and
  limitations such as saves, demos, teams, and live roster changes.
- [ ] Developer documentation explains command, sensor, graph, profile, trace,
  and protocol formats.
- [ ] External-reference provenance and any copied/adapted notices have been
  audited; no external bot personas/scripts/assets are included.
- [ ] Commercial Corridor 7 files are absent from commits and redistribution.
- [ ] The optimized self-contained release package is rebuilt with
  `ECWolf/tools/package_corridor7_release.sh`.
- [ ] `ECWolf/tools/test_corridor7_release_startup.sh builds/release` succeeds
  from the packaged copy's own directory.

---

## 21. Decisions for review

This plan makes recommendations so implementation can proceed, but the
following product/architecture decisions should be explicitly accepted or
changed before their dependent milestone.

| Decision | Recommended answer | Decide by |
| --- | --- | --- |
| Brain authority | Host/arbiter alone; broadcast finalized bot commands | Before B1/B2 |
| Initial ruleset | Free-for-all Corridor 7 deathmatch only | Before B0 exit |
| Original team mode | Preserve architectural hooks; defer bot team tactics | Before B7 |
| Offline mode | Same deathmatch session/roster with one peer, no fake network | Before B1 |
| Slot layout | Explicit kind/owner per slot; contiguous occupied slots in v1 | Before B1 |
| Supported total count | Validate engine max 11; expose only the proven/menu-approved cap | Before B10 |
| Live add/remove/takeover | Match-boundary only in v1 | Before B1 protocol freeze |
| Host migration | End match on host loss in v1 | Before B2 |
| Bot map knowledge | Full static topology and pickup-spawn knowledge; dynamic state only by perception/memory | Before B5/B6 |
| Perception authority | Immutable sensor adapter; no tactical raw world access | Before B5 |
| Damage-direction information | Match actual human feedback; do not expose exact hidden attacker by convenience | Before B5 |
| Highest skill | Strong but finite/fallible; no ordinary perfect profile | Before B9 |
| Skill presentation | Four levels: Recruit, Marine, Veteran, Elite | Before B10 |
| Personas | Original built-in names/biases; no copied external data | Before B9/B10 |
| Bot profiles | Built-in validated data first; optional hashed lump format later | Before B3 |
| AI implementation | Explicit C++ states + utility; no VM/ML in v1 | Before B3 |
| Navigation | Runtime tile/portal graph with real collision validation | Before B3 |
| Hearing | Semantic gameplay event ring; only sounds humans can receive | Before B5 |
| Mines | Stage after baseline guns, then ship only with focused tests | Before B7/B8 |
| Visor/hidden lasers | Stage after baseline perception, then ordinary equipment command/charge | Before B5/B8 |
| Player classes | Bot inherits configured ordinary class; add no bot-only stats | Before alternate class ships |
| Mixed class radii | Make projection console-specific before exposing unequal radii; otherwise v1 requires equal radius | Before alternate class ships |
| Pitch/mouselook | Synchronize canonical input or disable in net deathmatch | Before B0 exit |
| Pause/local UI | UI controls stay local; network pause disabled in v1, offline skirmish pauses globally | Before B2 protocol freeze |
| Match end | Use completed human multiplayer frag/time/result rules; AI does not invent one | Before B7 |
| Save support | Unsupported for v1 offline/network bot deathmatch | Before B10 docs |
| Demo/replay | Legacy unsupported; optional v2 records final commands for every slot | Before B10 |
| Mods/custom maps | Support maps expressible by typed graph/query; fail/diagnose unknown traversal honestly | Before public mod claim |
| Dedicated server/bot-only | Data model and tests support it; public dedicated-server product is future work | Before B3 tests |

If review rejects host-authoritative commands, B2 must be rewritten around
replicated deterministic brains and must add bot state/RNG/event/path equality
to the network digest. That is a material architecture change, not a local
implementation choice.

### 21.1 Recommended first playable slice

For the shortest honest route to something useful:

1. Complete B0 human combat prerequisites.
2. Implement B1/B2 roster and host multi-slot command plumbing.
3. Use a scripted dummy to prove mixed offline/network slot behavior.
4. Implement B3 simple graph/door/roam and B5 vision/reaction for one target.
5. Add M16-only aim/fire through ordinary commands.
6. Play one human versus one visibly fallible bot on `MAP53`.

That slice is intentionally not called "bot support." It proves the entire
vertical authority/fairness path before expanding navigation, items, weapons,
and profiles.

### 21.2 Questions that can wait

These do not need answers before the first release architecture:

- learned navigation from human demonstrations;
- cooperative bots and monster objectives;
- team communication/formation tactics;
- chat/taunts/personality text;
- dynamic mid-match joins/takeovers;
- dedicated server administration;
- player-authored bot scripts;
- nav-cache files shipped per map;
- spectator camera following bots; and
- long-term adaptive difficulty.

---

## 22. Primary references and provenance notes

### 22.1 EC7Wolf source reviewed

- [`src/wl_play.h`](../src/wl_play.h) and
  [`src/wl_play.cpp`](../src/wl_play.cpp): `TicCmd_t`, local input,
  `PollControls`, play-loop timing.
- [`src/wl_net.h`](../src/wl_net.h) and
  [`src/wl_net.cpp`](../src/wl_net.cpp): current peer/player handshake,
  delayed lockstep, command packets, resend history.
- [`src/wl_agent.h`](../src/wl_agent.h) and
  [`src/wl_agent.cpp`](../src/wl_agent.cpp): `player_t`, movement/collision,
  targeting, damage/frags, spawn/reborn, Corridor 7 attacks/hazards.
- [`src/g_shared/a_playerpawn.cpp`](../src/g_shared/a_playerpawn.cpp): use,
  weapon input, death/respawn, battle inventory, mines/visor.
- [`src/gamemap.h`](../src/gamemap.h),
  [`src/gamemap.cpp`](../src/gamemap.cpp), and
  [`src/gamemap_planes.cpp`](../src/gamemap_planes.cpp): translated runtime map,
  player starts, C7 doors/markers/transporters.
- [`src/lnspec.cpp`](../src/lnspec.cpp): doors, dynamic walls, pushwalls,
  teleporters, exits.
- [`src/wl_state.cpp`](../src/wl_state.cpp): gameplay LOS and monster movement
  distinction.
- [`wadsrc/static/actors/corridor7/player.txt`](../wadsrc/static/actors/corridor7/player.txt):
  player, weapon, projectile, mine, ammo/item definitions.
- [`wadsrc/static/mapinfo/corridor7.txt`](../wadsrc/static/mapinfo/corridor7.txt):
  authoritative real network-level mapping.
- [`docs/multiplayer.md`](multiplayer.md): current human multiplayer plan and
  completed/in-progress foundations.

The commercial `CORR7CD` data was inspected locally only to identify arena test
cases. It is not reproduced by this document and must never be committed or
redistributed.

### 22.2 Zandronum, pinned review

Reviewed at commit
[`bdd0f7beb43d9786cc13502395f60aa84d34e28d`](https://github.com/TorrSamaho/zandronum/tree/bdd0f7beb43d9786cc13502395f60aa84d34e28d):

- [`bots.h`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/bots.h):
  bot/player association, profiles, scripts, events, runtime state.
- [`bots.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/bots.cpp):
  creation/removal, server-only ticking, reaction queues, aim, profiles,
  commands, diagnostics.
- [`botcommands.h`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/botcommands.h)
  and
  [`botcommands.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/botcommands.cpp):
  behavior VM operations for senses, goals, paths, movement, combat, and
  weapons.
- [`astar.h`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/astar.h)
  and
  [`astar.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/astar.cpp):
  runtime grid, A*, direct-route test, smoothing, obstruction/replanning.
- [`botpath.h`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/botpath.h)
  and
  [`botpath.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/botpath.cpp):
  collision/traversal flags and probes.
- [`p_user.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/p_user.cpp):
  ordinary player-think integration.
- [`sv_commands.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/sv_commands.cpp),
  [`cl_main.cpp`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/src/cl_main.cpp),
  and
  [`protocolspec/spec.players.txt`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/protocolspec/spec.players.txt):
  authoritative server and bot player identity on clients.
- [`wadsrc/static/botinfo.txt`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/wadsrc/static/botinfo.txt):
  profile/persona structure, reviewed for concepts only; no data should be
  copied.
- [`LICENSE.txt`](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/LICENSE.txt)
  and
  [repository license explanation](https://github.com/TorrSamaho/zandronum/blob/bdd0f7beb43d9786cc13502395f60aa84d34e28d/README.md):
  license/provenance obligations requiring file-level review.

### 22.3 Quake III Arena

Reviewed at id Software commit
[`dbe4ddb10315479fc00086f08e25d968b4b43c49`](https://github.com/id-Software/Quake-III-Arena/tree/dbe4ddb10315479fc00086f08e25d968b4b43c49):

- [`ai_main.c`](https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/game/ai_main.c):
  bot-input-to-user-command conversion, think scheduling, human-limited view
  changes.
- [`ai_dmnet.c`](https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/game/ai_dmnet.c):
  explicit deathmatch behavior states.
- [`ai_dmq3.c`](https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/game/ai_dmq3.c):
  perception, enemy selection, combat movement, weapon choice, aim/fire.
- [`be_ai_goal.c`](https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/botlib/be_ai_goal.c)
  and
  [`be_ai_move.c`](https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/botlib/be_ai_move.c):
  weighted goals and separated goal movement.
- Jan Paul van Waveren,
  [*The Quake III Arena Bot*](https://fabiensanglard.net/fd_proxy/quake3/The-Quake-III-Arena-Bot.pdf):
  primary architecture/thesis reference for layered behavior, input, traits,
  perception, aiming, and AI state networks.
- [`COPYING.txt`](https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/COPYING.txt):
  GPL-2.0-or-later terms for the released source.

### 22.4 Quake II ACEBot cautionary reference

The q2dos ACEBot mirror was reviewed only for historical concepts:

- [`acebot_ai.c`](https://github.com/maraakate/q2dos/blob/68f2f21ec6bf0f28c9fd52970e22991899bd00e2/acebot/acebot_ai.c):
  creation of an ordinary `usercmd_t`, goal selection.
- [`acebot_nodes.c`](https://github.com/maraakate/q2dos/blob/68f2f21ec6bf0f28c9fd52970e22991899bd00e2/acebot/acebot_nodes.c):
  waypoint/path concepts.
- [`acebot_movement.c`](https://github.com/maraakate/q2dos/blob/68f2f21ec6bf0f28c9fd52970e22991899bd00e2/acebot/acebot_movement.c):
  movement/aim behavior and evidence that inaccuracy was not a complete human
  motor model.

The ACEBot file headers carry additional restrictions. Copy no ACEBot code.

---

## Appendix A — State-transition summary

```text
                 pawn dies
       +-----------------------------+
       |                             v
   any live state             DeadWaitingToRespawn
                                     |
                            ordinary respawn succeeds
                                     v
                                SpawnOrient
                                     |
                        initial sense/goal completes
                                     v
              +-------------------- Roam <--------------------+
              |                      |                         |
       valuable resource       visible threat             search ends /
              v                      v                    recovery succeeds
          SeekPickup           EngageEnemy                    |
              |                /     |    \                    |
       threat |       LOS loss       | low survival            |
              +-------------> Chase  v                         |
                              /Search RetreatOrRecover --------+
                                 |
                         confidence expires
                                 +----------------------------> Roam

Any movement state may temporarily enter UseTraversal or Unstuck, then return
to its interrupted state or abandon/reselect the goal on failure.
```

State changes select intent only. Death, respawn, movement, use, inventory,
weapons, damage, and score remain ordinary gameplay operations.

---

## Appendix B — Bot bug report minimum

A useful bot defect report should include:

- EC7Wolf version/commit and build type;
- map and match rules;
- host/client/offline topology and input delay/network impairment;
- complete roster with bot slots/profiles;
- match and bot seed;
- slot exhibiting the problem;
- approximate simulation tic or recording time;
- expected versus observed behavior;
- command/world digest result;
- structured bot trace and relevant process logs; and
- screenshot/video only as supporting evidence, not the sole reproduction.

For navigation defects, also include current/failed node, physical cache
generation, and that bot's belief generation. For aim/perception defects,
include released observation, reaction
timer, delayed target sample, ideal/error/commanded bearing, and fire-gate
reason. For network defects, include expected/received sequence and slot masks.

---

## Appendix C — Compact implementation invariants

These are suitable for a prominent comment near the bot manager and for code
review templates:

1. A bot is a controller for an ordinary active player slot.
2. The host alone runs bot brains; all peers receive final bot commands.
3. A bot changes the game only by a validated `TicCmd_t`.
4. All bot commands are built from the same completed start-of-tic world.
5. Tactical code sees observations and memory, never unrestricted world state.
6. Movement/path tests are side-effect-free; actual movement remains ordinary
   player movement.
7. Bot variation uses private RNG streams and never gameplay RNG.
8. Skill changes information/motor/decision quality, never player rules.
9. Every expensive operation is bounded and every decision is traceable.
10. If a behavior cannot be implemented fairly through these interfaces, it is
    deferred rather than bypassed.
