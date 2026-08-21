# Multiplayer

Corridor 7's CD release shipped multiplayer, and this port has never exposed
it. ECWolf, which this forks, has a working network implementation that has
never been reachable from the Corridor 7 menu. Both halves exist; nothing joins
them, and one of them cannot survive the internet in its present form.

This is the plan to fix that.

---

## What is already true

Established by reading the code and running it, not assumed:

| | |
| --- | --- |
| **ECWolf has netcode** | `src/wl_net.cpp`, 1031 lines: UDP, host and client, cooperative and battle modes, an arbiter, acked reliable packets, per-player classes |
| **It is reachable only by flag** | `--host <players>`, `--join <address>`, `--port` — no menu path at all |
| **The arenas exist and load** | `MAP51`–`MAP58`, already translated and named "Corridor 7 Network Level 1–8" in `mapinfo/corridor7.txt`. MAP51, 55 and 58 load and render; the HUD reads level 51 and **ALIENS 0**, as a deathmatch map should |
| **The menu has the pieces** | `LabelMenuItem` renders as a section heading — small dim capitals over a hairline — which is exactly the separator this needs, and the Corridor 7 shell already draws it. `TextInputMenuItem` exists for an address field. `MenuSwitcherMenuItem` opens a submenu |
| **There is a determinism harness** | `--capture-checksum` and the `corridor7_determinism` gate. Lockstep multiplayer is only correct while every machine simulates identically, so this is not a nicety — it is the instrument the whole feature is tested with |

## What the original did

From the Technical & Strategy Compendium, §9.5 and §9.1:

* Eight network arenas, internal levels **51–58**. (The CD manual claims ten;
  MapEdit and the warp table say eight, and the namespace agrees with eight.)
* IPX networking and modem play at 9600 baud or better.
* Players choose **Marine or alien classes**, with different health, speed and
  damage.
* **Team mode**: players controlling the same character cannot damage one
  another, and their kills aggregate.
* **Starting positions are assigned randomly** from the placed starts.

## Scope

Internet only. No IPX, no modem, no serial — they solve a 1994 problem, and
nothing that runs this port has the hardware.

Everything else in §9.5 is in scope, because it is what the game was.

---

## The problem that shapes the plan

`Net::PollControls` runs once per tic and calls `ExchangePacket`, which blocks:

```c
while(numAcked != InitVars.numPlayers || numReceived != InitVars.numPlayers)
```

It does not continue until every player's command for **this** tic has arrived
and been acknowledged. That is lockstep, and `TICRATE` is **70**, so it needs a
complete round trip every **14.3 ms**.

On a LAN that is free. Over the internet it is not survivable: at 30 ms
round-trip the game cannot exceed about 33 tics per second, so *everyone* plays
at half speed, and one lost packet stalls every player until it is resent.

So the first work is not the menu. It is making the transport tolerate the
internet, and there is a standard answer that suits this engine well:

**Input delay.** Send each command for a tic some fixed number of tics in the
future, and simulate tic *T* from commands that arrived while tics *T-n*
through *T-1* were being drawn. The round trip then has a whole window to
complete in rather than one tic, and the cost is that your own input takes *n*
tics to appear — 4 tics is 57 ms, 8 tics is 114 ms, which is the trade every
lockstep game of this era made and is imperceptible next to the alternative.

It suits this engine because the simulation is already deterministic and
already has a checksum harness to prove it. The alternative — client/server
with prediction and reconciliation — is a rewrite of the playsim's
relationship to input, and would be a different project.

---

## Milestones

Each milestone ends with something demonstrable and a gate that keeps it
working. No milestone depends on hardware nobody has.

### M0 — Prove the ground

Two instances on loopback, driven headlessly, playing the same arena.

* A gate that starts a host and a client on `127.0.0.1`, plays a fixed number
  of tics with scripted input, and compares each side's determinism checksum.
* Establishes the harness everything else is judged by: **if the checksums
  diverge, the game has desynced**, and that is the only failure that matters
  in lockstep.

*Exit:* `test_multiplayer_loopback.sh` runs two engines, plays, and both report
the same checksum. Any desync fails the gate with the tic it happened on.

### M1 — Survive the internet

Input delay, and the handling that a lossy link demands.

* A configurable delay window, defaulting to something sane and settable in the
  setup menu for people on bad links.
* Commands buffered ahead rather than exchanged synchronously; `ExchangePacket`
  stops being a barrier for the current tic.
* A player who stops responding is timed out and reported, rather than freezing
  everyone for ever.
* Version and data handshake at join: two players with different builds or
  different game data must be told so, not desync fifty tics later.

*Exit:* the loopback gate again, under **simulated latency and loss** — `tc
netem` on the loopback interface, 80 ms round trip and 2% loss — still in sync
and still running at full tic rate.

### M2 — The way in

The menu, which is what makes the feature exist for a player.

* *New Game* gains a section separator after the difficulty rows and a
  **Multiplayer** entry beneath it — `LabelMenuItem` already draws exactly
  that in the Corridor 7 shell.
* Multiplayer opens its own screen: host or join, **address**, port, arena,
  mode, class.
* Address entry needs `TextInputMenuItem` to work inside the Corridor 7 menu
  shell. The shell draws a right-aligned value for every item, but the editing
  path draws itself, and has never been run there — **this is the one piece of
  M2 that may need real work rather than assembly.**

*Exit:* a gate drives the menu headlessly — down to Multiplayer, into the
screen, type an address, back out — and asserts the entered address reaches
`Net::InitVars`. Screenshots for the README.

### M3 — Arenas

* The eight arenas offered by name in the setup screen.
* **Random starts** from the placed spawn points, per §9.5. Requires finding
  what marks a start in these maps' plane 1 and whether the existing
  translation already carries them.
* Enough spawns for the player count, or an honest refusal.

*Exit:* a gate loads all eight, counts the starts in each, and asserts two
players entering the same arena are placed apart.

### M4 — The rules

* Battle mode: ECWolf's `GM_Battle` already implies friendly fire, item
  respawn and no monsters.
* **Team mode** as the original had it: players on the same character cannot
  damage one another and their kills aggregate.
* Frags, and a match end condition.

*Exit:* a gate scripts two players into a fight and asserts the frag counters,
the friendly-fire rule in both modes, and that a match ends when it should.

### M5 — Marine and alien

The original let you *be* the alien, and that is the most distinctive thing in
this whole feature.

* An alien player class with its own health, speed and damage, from §9.5 and
  from whatever the executable yields.
* Class chosen in the setup screen; `Net::NewGame` already carries a class name
  per player, so the plumbing is there.
* The alien needs a view model, a HUD that makes sense for it, and its own
  sounds.

*Exit:* a gate starts a two-player match with one of each class and asserts
each has the right pawn, health and speed. Screenshots of both.

### M6 — Presentation

* A scoreboard, and frags on the HUD where Corridor 7 has room for them.
* End-of-match tally in the original's visual language.
* The join screen saying something useful while it waits, rather than
  appearing to hang.

*Exit:* screenshot gates for the scoreboard and the tally; the join screen
shows progress under a deliberately slow connection.

### M7 — Hardening

* Malformed and hostile packets rejected rather than trusted — this is a socket
  open to the internet, and the current code reads structures straight off it.
* NAT and firewall reality: what port to forward, and what to tell someone
  whose connection never completes.
* Documentation, the README section, and the full gate set.

*Exit:* a gate that fires malformed, truncated and oversized packets at a host
and requires it to survive them; the whole suite green.

---

## What is not in this plan

* **IPX, modem, serial.** Out of scope by intent.
* **Matchmaking, a server browser, a master server.** You type an address, as
  asked. Everything here would support a browser later; none of it needs one.
* **More than the engine's `MAXPLAYERS` of 11.** No reason to raise it.

## Risks, honestly

| Risk | Why it matters | What reduces it |
| --- | --- | --- |
| Lockstep over the internet | The entire feature is unplayable without M1 | M1 is first, and its gate is latency and loss, not loopback |
| Desync | Silent, and fatal; two players simply diverge | The determinism harness already exists and every milestone's gate uses it |
| Text entry in the Corridor 7 shell | The one part of M2 that is not assembly | Fall back to the engine's own menu style for that one field if it proves stubborn |
| Alien class fidelity | §9.5 gives characteristics, not numbers | Treat as an evidence-based reconstruction and say so, as the port does elsewhere |
| Nobody to test with | Two machines and a person at each | Every gate is two local instances; a real session between two houses is the acceptance test, not the development loop |
