```
   ▄████▄   ▒█████   ██▀███   ██▀███   ██▓▓█████▄  ▒█████   ██▀███      ▄▄▄▄▄▄
  ▒██▀ ▀█  ▒██▒  ██▒▓██ ▒ ██▒▓██ ▒ ██▒▓██▒▒██▀ ██▌▒██▒  ██▒▓██ ▒ ██▒       ▒██
  ▒▓█    ▄ ▒██░  ██▒▓██ ░▄█ ▒▓██ ░▄█ ▒▒██▒░██   █▌▒██░  ██▒▓██ ░▄█ ▒       ░██░
  ▒▓▓▄ ▄██▒▒██   ██░▒██▀▀█▄  ▒██▀▀█▄  ░██░░▓█▄   ▌▒██   ██░▒██▀▀█▄        ▓██▒
  ▒ ▓███▀ ░░ ████▓▒░░██▓ ▒██▒░██▓ ▒██▒░██░░▒████▓ ░ ████▓▒░░██▓ ▒██▒      ██▒▒
              A L I E N   I N V A S I O N   —   the EC7Wolf source port
```

# EC7Wolf — Corridor 7: Alien Invasion

**EC7Wolf is a vibecoded, sourceless source port of the 1994 Capstone FPS
*Corridor 7: Alien Invasion*, built on a fork of the ECWolf engine.**

> ⚠️ **This is not stock ECWolf.** This fork exists for exactly one purpose: to
> make **Corridor 7: Alien Invasion** run natively on a modern machine, reading
> the original commercial game files, reproducing the original mechanics as
> faithfully as the surviving evidence allows. The engine has been surgically
> altered throughout for Corridor 7. Other Wolf-family games (Wolfenstein 3D,
> Spear of Destiny, Blake Stone, …) **may still launch, but they are not the
> target of this fork and are not guaranteed to behave correctly.** If you want
> a general-purpose Wolf3D port, use [upstream ECWolf](https://maniacsvault.net/ecwolf/).

> ### 🎮 The controls are modern by default
>
> **W A S D** to move · **E** to open doors and use machinery · arrow keys turn
> · **Ctrl** fires · **Shift** runs
>
> This is *not* what Corridor 7 shipped with in 1994. If you want the original
> scheme — **arrow keys to move, Space to open** — the installer offers it as a
> tick-box, or change any key in *Options → Controls*. See
> [Controls](#controls) below.

---

## What it looks like

| | |
| --- | --- |
| ![The main menu](docs/images/menu-main.png) | ![In the first floor](docs/images/gameplay.png) |
| **The menu**, rebuilt as a splash-art shell with TrueType text, over the original's own artwork. | **The game**, drawn by the OpenGL renderer: the floor objective banner, the original HUD, the original palette. |

<sub>Regenerate these with `tools/capture_screenshots.sh BUILD_DIR DATA_DIR` —
they are produced from a pinned map, seed and frame, so they can be refreshed
rather than left to go stale.</sub>

---

## Why does this exist?

Corridor 7 has spent thirty years as one of the great *almost-ported* DOS
shooters. Here's the situation this project walked into:

- **There is no public Corridor 7 source code.** Capstone/IntraCorp never
  released it. What *does* survive publicly is the 1996 **Corridor 8** prototype
  source — a *successor* codebase that still carries `CORR7*.C` filenames but is
  explicitly **not** Corridor 7 and cannot be treated as its source.
- **ECWolf "support" was promised, but never shipped.** For years the plan was
  that ECWolf would eventually add Corridor 7 the way it added Blake Stone. The
  engine's Corridor 7 disassembly was reportedly *mapped* — but the annotated
  source was never made public, and playable support never actually landed. The
  game stayed stranded in DOSBox.
- **So I did it myself — with generative AI.** This entire port is a
  *vibecoding* effort: reverse-engineering the executable's behavior, reading
  map planes and asset containers, comparing pixel-for-pixel against DOSBox
  captures, and reconstructing the missing mechanics one at a time, in
  collaboration with a coding AI. Where the executable didn't yield an
  unambiguous constant, the behavior is an **evidence-based reconstruction**,
  documented honestly as such (see *Known deviations* below).

The result is a single native binary that boots your legally-owned Corridor 7
CD data straight into the 40-floor campaign, all six bonus floors, and final
victory — no DOSBox, no emulation layer, real 8-bit ray casting.

---

## Credits — where credit is due

This project stands entirely on the shoulders of three bodies of work. **None of
the underlying games or engines are mine**, and the commercial Corridor 7 assets
are **not** included here.

### Corridor 7: Alien Invasion © 1994 Capstone Software / IntraCorp
The game itself — story, art, sound, level design, alien menagerie — is the
creation of the Capstone/IntraCorp team:

| Role | Credit |
| --- | --- |
| Executive Producer | Leigh Rothschild |
| Producer | David Turner |
| Director | Amy Smith Boylan |
| Programmers | Les Bird, Jeff Schulz, Rafael Paiz, Joe Abbati |
| Artists | Ruben Cabrera, Carlos Ibarra, Scott Nixon |
| Level Design | Les Bird, Scott Nixon, Richard Henning |
| Music & Sound | Joe Abbati |
| Quality Assurance | James Wheeler, Katie Gangi |

*(A fun bit of trivia the design docs confirm: many alien names are reversed
staff names — SOLRAC/Carlos, TTOCS/Scott, EITAK/Katie, SEMAJ/James,
TENAJ/Janet, NERRAW/Warren.)*

### The Wolfenstein 3D engine © id Software
Corridor 7 is built on a heavily-modified license of id Software's Wolfenstein
3D engine. The original engine architecture — the 8-bit ray caster, the map/actor
plane model, the VSWAP concept — is id's.

### ECWolf © Braden "Blzut3" Obrzut and contributors
This is a **fork of [ECWolf](https://maniacsvault.net/ecwolf/)**, itself derived
from **Wolf4SDL**. ECWolf's SDL2 port, ZDoom-style data formats, high-resolution
software renderer, save system, and multi-game IWAD framework are the foundation
everything here is bolted onto. ECWolf is licensed under the GPL; see
[`docs/license-gpl.txt`](docs/license-gpl.txt) and [`docs/copyright`](docs/copyright).

**This fork is a hobbyist preservation/compatibility effort and is not
affiliated with or endorsed by Capstone, id Software, or the ECWolf project.**

---

## About Corridor 7 (the game)

> *In 2012, Dr. Donald Fox returns from Mars with an ageless metallic object
> recovered near a face-like formation. The government moves it to Delta Base, an
> underground Nevada weapons complex. Gamma testing turns it into a gateway;
> armed aliens pour through, killing the staff and converting both the facility
> and its atmosphere. A lone special-forces Marine is sent down to descend
> Corridor 7, restore contact, and destroy the object.*

Corridor 7 (1994) is a first-person shooter that looks like Wolfenstein but
plays with a whole extra layer of systems grafted on:

- **40 floors of campaign** (Delta Base floors 1–30, then a teleporter-linked
  alien world 31–40 on the CD release) **plus six hidden bonus floors**, ending
  in a multi-stage guardian boss and a final vortex.
- **A "secure the floor" objective** — the exit isn't just an elevator. Each
  rank must kill a percentage of the floor's aliens (Corporal 10%, Lieutenant
  75%, Captain/Major 100%) before it will let you leave. The HUD's
  **aliens-remaining** counter *is* the win condition.
- **A three-mode visor** — Normal, Night Vision, and **Infrared**, drawing from
  a battery. Infrared is not a gimmick: it's how you see **cloaked Enirams**,
  **invisible laser barriers**, and which security terminals are safe.
- **A proximity map that doubles as a motion detector** — moving aliens show as
  blue dots, armed mines as red, revealing threats through walls once you find
  the Floor Plan.
- **Eight weapons across two ammo economies** — human weapons (Taser, Assault
  Shotgun, M-24 C.A.W., M-343 Tribarrel) draw from a shared 200-round pool;
  alien weapons (Dual Blaster, Plasma Rifle, Assault Cannon, Disintegrator) draw
  from a separate 999-unit energy pool. Plus **proximity mines** you plant and
  back away from.
- **A living, interactive base** — wall-mounted health/ammo dispensers, health
  chambers that seal you in and heal you, security computers that issue
  per-floor access cards or trip alarms, four-frame animated conversion
  machinery, glass and see-through walls, sliding/rising/force-field doors, and
  hazards like **electrified walls** and the infamous **infrared-only laser
  barriers**.
- **A bestiary of 16 aliens** (CD) — from 25-HP Alioprobe sentries to the
  cloaking Eniram, the furniture-mimicking Bandor, and a five-stage final
  guardian (**Tebazile → Eniram Boss → Tymok → Solrac → Tebazile**).

### Technical profile (original DOS release)

| | |
| --- | --- |
| Year / Publisher | 1994 · Capstone Software / IntraCorp |
| Engine | Modified licensed Wolfenstein 3D engine |
| Retail executable | `CORR7CD.EXE` (CD, 250,776 bytes) / `C7.EXE` (floppy) |
| Map container | `MAPTEMP.CO7` — **RLEW-compressed** planes (no Carmack layer) |
| Map header | **embedded in the executable** (CD offset `0x30D50`), *not* a `MAPHEAD` file |
| Walls & sprites | `GFXTILES.CO7` — **single** wall images with **runtime shading** (not Wolf3D's light/dark pairs) |
| Digital sound | `AUDIOMUS.CO7` — PCM at **~9009 Hz** (Wolf3D used ~7042 Hz) |
| Music / SFX | `AUDIOT`/`AUDIOHED` family — 34 AdLib/IMF music chunks |
| UI / fonts / screens | `VGAGRAPH` / `VGADICT` / `VGAHEAD` family |
| Map grid | 64×64 tiles, three parallel planes (wall/floor, object/actor, editor) |
| Min spec | 386-25, 590 KB free conventional RAM, 2 MB RAM, VGA, MS-DOS 5.0+ |

Much of this is *why* the port needed engine surgery rather than a data mod:
Corridor 7 stores its map header **inside the .EXE**, ships **single** wall
images instead of paired light/dark pages, hard-codes its **digital-sound page
metadata** in the executable, and adds entire subsystems (glass, animated walls,
force-field doors, visor vision, a motion-detector map) that stock Wolf3D simply
does not have.

---

## What this fork changed in the engine

Everything below is implemented directly in the engine/data of this fork
specifically to reproduce Corridor 7's mechanics. Original ECWolf/Wolf3D
behavior for other games was preserved wherever possible; these are the deltas.

### Asset loading & file formats
- **Self-contained TED5/`MAPTEMP.CO7` map loader** for all 60 archived maps,
  reading the **executable-embedded map header** (CD offset `0x30D50`) and
  RLEW-only plane decompression, with strict 64×64 validation. *(`gamemap.cpp`,
  `gamemap_planes.cpp`, `filesys.h`, `wl_iwad.cpp`)*
- **`GFXTILES.CO7` walls & sprites** exposed as zero-based wall pages
  (`map wall ID − 1`) across the full solid-wall range, including
  marker-104/105 masked overrides and Corridor 7's wall/plane depth ramps.
  *(`resourcefiles/file_vswap.cpp`, `textures/wolfrawtexture.cpp`,
  `textures/wolfshapetexture.cpp`)*
- **Executable palette extraction** — the six-bit VGA palette is read from the
  original executable at runtime and expanded exactly; nothing commercial is
  embedded or redistributed. *(`v_palette.cpp`, `v_palette.h`)*
- **`AUDIOMUS.CO7` digital sound** at the game's native ~9009 Hz, plus the 34
  AdLib music chunks and `VGAGRAPH`-family fonts/screens/HUD art. *(`sndinfo.txt`,
  resource loaders)*

### Rendering
- **Single-image walls with runtime shading** instead of Wolf3D light/dark
  pairs. *(`textures/wolfrawtexture.cpp`, `textures/flattexture.cpp`)*
- **Glass and see-through walls** — masked-wall rendering with correct
  transparency, freshly-traced collision geometry behind transparent pixels,
  and compositing of adjacent glass panes at true depth. *(`wl_draw.cpp`,
  `r_sprites.cpp`)*
- **Animated walls & force fields** — all four native 208..239 wall/force-field
  palette cycles and four-frame in-place force-field/animated-wall openings.
  *(`v_palette.cpp`, `wl_draw.cpp`)*
- **Index-255→0 normalization** so transparent-wall and door pixels stay
  collision-safe.

### Map translation, doors & triggers
- **Full plane-1 object dispatch table** — statics, pickups,
  difficulty/direction actor variants, bosses, and ignored markers. *(`xlat/corridor7.txt`,
  `lnspec.cpp`)*
- **Four sliding door types with automatic orientation**, non-sliding
  rising/inside-out/force-field doors, red/blue **per-floor access cards**,
  one-shot secret and utility **pushwalls** with correct restricted-secret
  scoring (`0x62` counts, `0x65` doesn't), **four-frame retracting barriers**,
  paired intralevel **teleporters**, floor exits, marker-99 bonus elevators, and
  the level-30/40 **exit vortex**. *(`gamemap.cpp`, `lnspec.cpp`)*

### Actors & gameplay
- **A Corridor 7 player and the full eight-weapon arsenal** (including the
  Ithaca/Assault Shotgun secondary animation), proximity mines, all weapon
  pickups, and the two-pool ammo/energy economy. *(`actors/corridor7/player.txt`,
  `wl_act2.cpp`)*
- **The 16-alien bestiary** with per-rank health tables, distinct
  directional/attack/pain/death sprite families, **cloaking (Eniram)** and
  **camouflage/morph (Bandor)** transformations, audible projectiles, bosses,
  alien-energy regeneration/capacity, and persistent mines.
  *(`actors/corridor7/monsters.txt`, `actors/corridor7/statics.txt`,
  `wl_state.cpp`, `wl_act2.cpp`)*
- **Non-wasteful pickup rules** for health and ammunition, matching the
  original's refusal to over-fill. *(`g_shared/a_inventory.cpp`)*

### Vision, HUD & hazards
- **Three visor modes** — Normal / Night Vision / Infrared — implemented as
  whole-screen palette swaps with a draining charge, plus **infrared-revealed
  cloaked enemies and laser barriers**. *(`wl_play.cpp`, `v_palette.cpp`,
  `r_sprites.cpp`)*
- **The infrared "invisible laser barrier"** (strategy-guide hazard, map objects
  28/84): floor-to-ceiling laser statics beside the yellow health-unit doors,
  **invisible in normal/night vision**, drawn only under infrared as **animated
  bright dashed energy**, that **never block movement** but zap the player 10
  points through the rank/armor path on a cooldown as you pass through — exactly
  as the retail executable's `2f28:06d3` routine does.
  *(`r_sprites.cpp`, `wl_agent.cpp`, `actors/corridor7/statics.txt`)*
- **Electrified walls (IDs 6/14)** — solid, visible in every visor, dealing a
  flat 2 points ~twice per second on contact with the DAC shock flash.
  *(`wl_agent.cpp`)*
- **The original status bar** — segmented color gauges, number placement,
  aliens-remaining counter, M-16 start selection, and native first-person weapon
  scaling. *(`g_wolf/wolf_sbar.cpp`)*

### Interactive machinery
- **Stateful access/alarm computers, health & ammo dispensers, the reusable
  visor charger, and health chambers** that turn you toward the exit, seal the
  door, consume stored power, heal, and report remaining charge. *(`lnspec.cpp`,
  `wl_state.cpp`)*

### Menus, progression & presentation
- **The original graphical main menu** — the full-screen VGA menu picture with
  painted-in entries, the 24×8 blinking arrow cursor at the original
  coordinates, correct entry wiring, and **DMA-capture-verified menu sounds**
  (cursor move = sample 9, back = 33, quit prompt = 31, activate silent).
  *(`wl_menu.cpp`, `m_classes.cpp`)*
- **Full-screen picture pages** (status report, high-score, death report) drawn
  in the same stretched 320×200 mapping as the artwork, verified against DOSBox
  screenshots. *(`wl_inter.cpp`)*
- **Rank/difficulty & campaign flow** — five rank choices (including randomized
  President placement), the 10/75/100/100% alien objective gate, body armor,
  MAP01→MAP40 progression and victory, six routed bonus maps, per-floor hit/miss
  awards, loading/death/high-score pages, and the rare non-counting
  C718–C725 red-skull taunt. *(`wl_game.cpp`, `wl_inter.cpp`)*
- **The campaign music selector**, including its randomized late/bonus-floor
  behavior, exposing all 34 AdLib chunks directly. *(`wl_inter.cpp`)*

## Documentation

| Document | What it is |
| --- | --- |
| [`docs/corridor7.md`](docs/corridor7.md) | The exhaustive feature list, every reconstruction and how it was established, and the honest list of deviations. |
| [`docs/corridor7-technical-strategy-compendium.pdf`](docs/corridor7-technical-strategy-compendium.pdf) | Evidence-graded research dossier on the original game: mechanics, weapons and actors, map format and object codes, asset containers, executable offsets, and what changed from stock Wolfenstein 3D. Every claim carries an evidence grade, so a confirmed retail behaviour is never mixed up with an inference. It is the reference this port was built against. |
| [`docs/renderer/`](docs/renderer/) | The renderer redesign, one document per phase — baseline and harness through the OpenGL cutover, hardening and optimization. |
| [`docs/corridor7-video.md`](docs/corridor7-video.md) | The CD cinematics: what is on the disc, the FLIC format they are in, and how extraction and playback work. |
| [`docs/ci.md`](docs/ci.md) | The gate suite and what CI can and cannot run. |

---

## Getting the game data (required)

**This repository contains *no* Corridor 7 game data.** You must own a legal copy
of Corridor 7: Alien Invasion (the CD release / a Steam or GOG package wraps the
same DOS files). From your installation, copy these files into a single
directory — call it `CO7`:

```
CORR7CD.EXE     ← main executable (contains the map header & palette)   REQUIRED
MAPTEMP.CO7     ← RLEW-compressed map planes                            REQUIRED
GFXTILES.CO7    ← walls & sprites                                       REQUIRED
VGADICT.CO7     ← Huffman dictionary for VGAGRAPH                       REQUIRED
VGAHEAD.CO7     ← VGAGRAPH offset table                                 REQUIRED
VGAGRAPH.CO7    ← screens, fonts, menu & HUD art                        REQUIRED
AUDIOHED.CO7    ← audio offset table                                    REQUIRED
AUDIOT.CO7      ← AdLib music & sound container                         REQUIRED
AUDIOMUS.CO7    ← digitized (PCM) sound effects                          optional*
```

\* The game starts and plays without `AUDIOMUS.CO7`, falling back to the AdLib
effects in `AUDIOT.CO7` — but it holds the 100 digitized sounds that make up
most of what Corridor 7 actually sounds like, so copy it.

That is the whole list. **Everything else in a Corridor 7 installation is
ignored** — you do not need to copy any of it:

```
GFXINFOV.CO7    ← unused by the port
SETUP.EXE       ← the DOS sound/input configurator
CORR7.BAT       ← the DOS launcher
CONFIG.DAT      ← DOS settings; the port keeps its own config
CONFIGD.DAT     ← as above
AUTOSAVE.DAT    ← DOS save state; not a supported save format
README.1ST      ← documentation
README.txt      ← documentation
*.SAV / saved games from the DOS release
```

`CORR7CD.EXE` is on the required list because the game's palette is embedded in
it — the port reads it out at runtime as the `C7PAL` lump, and the IWAD is not
recognised without it. It is never redistributed, and neither is anything else
in the list above.

> **The recognized CD executable is exactly 250,776 bytes.** Budget/"Play Now"
> and cracked builds can move the embedded offsets — if the game won't load,
> verify you have the genuine retail CD `CORR7CD.EXE`.

### Three optional extras

Both live beside the data files, and the game says on startup whether it found
them.

**The CD soundtrack.** The disc's music is redbook audio and is in none of the
files above. Rip your own disc into a `cdaudio` subdirectory:

```sh
tools/make_cdaudio.py Corridor7.cue /path/to/CO7/cdaudio
```

The game plays tracks 3, 5, 7 and 9 — the four pieces of music. Without the
directory it uses the AdLib soundtrack.

**Upscaled art.** A neural-network upscale of the game's own graphics, built
from your own files:

```sh
tools/make_c7_upscaled_pk3.py --dir /path/to/CO7
```

That writes `c7_assets_upscaled.pk3` beside the data, and *Advanced Graphics →
Upscaled Assets* switches between the two copies without a restart. The original
art is still required either way.

**The CD cinematics.** Three animations that the DOS installer leaves on the
disc — the Capstone logo, the opening cinematic and the ending:

```sh
tools/extract_c7_video.py Corridor7.cue /path/to/CO7/video
```

The first two play at startup before the title, the third on final victory, and
any key skips one.

All three are described in full in [`docs/corridor7.md`](docs/corridor7.md).

---

## Installing and running

There are six ways to end up with a working game. They differ only in how much
you do by hand and how much the installer does for you — **all of them need
your own copy of Corridor 7**, which nothing here provides.

| If you want… | Use |
| --- | --- |
| the shortest path, on Windows | **[1 · The graphical installer](#1--the-graphical-installer)** (`EC7Wolf-Setup.exe`) |
| the shortest path, on Linux | **[2 · Precompiled binaries](#2--precompiled-binaries)**, or route 1 if you would rather click |
| a scripted or unattended install | **[3 · The installer from a terminal](#3--the-installer-from-a-terminal)** |
| everything built from source, automatically | **[4 · The installer, compiling for you](#4--the-installer-compiling-for-you)** |
| to compile it yourself, by hand | **[5 · Building by hand](#5--building-by-hand)** |
| a binary that runs on any Linux, old or new | **[6 · The portable Docker build](#6--the-portable-docker-build)** |

Every route ends at the same place: a folder holding `ec7wolf`, `ec7wolf.pk3`,
your game data, and a launcher that keeps configuration and saved games beside
them.

---

### 1 · The graphical installer

The installer builds or collects the engine, takes the game's data, soundtrack
and cinematics off your CD, and puts the lot in one folder. It never needs
administrator rights and writes nothing outside the folder you choose.

#### On Windows

1. Download **`EC7Wolf-Setup.exe`** from the
   [releases page](https://github.com/jeddhor/EC7Wolf/releases). It is one file
   with Python and Qt inside it; nothing needs installing first.
2. Run it. Windows SmartScreen will warn about an unsigned executable — *More
   info* → *Run anyway*, or check the SHA-256 against the release notes first.
3. Work through the pages below.

#### On Linux

The installer is a Python program and needs **PySide6**:

```sh
sudo apt install python3-pyside6.qtwidgets     # Debian, Ubuntu, KDE neon
sudo dnf install python3-pyside6               # Fedora
sudo pacman -S pyside6                         # Arch
pip install PySide6                            # anywhere else
```

Then, from a source checkout or the installer-only download:

```sh
installer/ec7wolf-setup
```

If PySide6 is missing it says so and points you at the terminal installer,
which needs nothing but Python.

#### What the pages ask

<table>
<tr><td width="50%"><img src="docs/images/installer-welcome.png" alt="Welcome page"></td>
<td><b>Welcome.</b> States plainly that you need your own copy of the game, and
that the CD-ROM release is the one to use — it is the only one carrying the
soundtrack and the cinematics.</td></tr>

<tr><td><img src="docs/images/installer-source.png" alt="Source page"></td>
<td><b>Your copy of Corridor 7.</b> A CD in a drive, a BIN/CUE or ISO image (what
GOG and Steam ship), or a folder of files you already extracted. It reads
whatever you point it at and reports what it found: all eight required files, how
many audio tracks, how many cinematics. <b>Next stays disabled until the source
can actually furnish an install</b>, and it names any file that is missing.</td></tr>

<tr><td><img src="docs/images/installer-engine.png" alt="Engine page"></td>
<td><b>The engine.</b> If you already built one it says so and uses it. If not,
it checks for what compiling needs and lists anything missing <i>with the command
to install it on your system</i>. On Windows it goes further — see route 4. Tick
<i>Show details</i> on the next page to watch the compile.</td></tr>

<tr><td><img src="docs/images/installer-destination.png" alt="Destination page"></td>
<td><b>Where to install.</b> Defaults to <code>~/.local/share/ec7wolf</code>
(Linux), <code>%LOCALAPPDATA%\EC7Wolf</code> (Windows) or
<code>~/Applications/EC7Wolf</code> (macOS). Shows the space needed against the
space free, warns if something is already installed there, and refuses a folder
you cannot write to.</td></tr>

<tr><td><img src="docs/images/installer-options.png" alt="Options page"></td>
<td><b>Options.</b> Whether to rip the CD soundtrack and extract the cinematics —
each is offered only if your source actually has it — whether to add a menu
entry and a desktop icon, and <b>which control scheme to set up</b>. It states
plainly that the defaults are modern (W A S D, E to use) and offers the
original's arrows-and-Space scheme as a tick-box.</td></tr>

<tr><td><img src="docs/images/installer-summary.png" alt="Summary page"></td>
<td><b>Ready to install.</b> Everything that is about to happen, on one page.
<b>Nothing has been written yet.</b> The button says <i>Install</i>, and there is
no way back afterwards — which is why this page exists.</td></tr>
</table>

While it runs you get a progress bar, the current step, and a *Show details*
pane carrying every line, including the compiler's. **Cancel** stops it and
undoes what it wrote — including part way through the soundtrack rip, which
stops within a second rather than at the end of a ten-minute track.

#### If you already have an install

Point the installer at the same folder and it offers two things: **reinstall**
(writes everything again, keeping your saved games and settings) or **remove**.
There is deliberately no separate "upgrade" or "repair" — this installer always
writes everything, so those would be the same action under three names.

---

### 2 · Precompiled binaries

From the [releases page](https://github.com/jeddhor/EC7Wolf/releases):

| Artifact | What is inside | What to run |
| --- | --- | --- |
| `EC7Wolf-Setup.exe` | the whole installer, frozen into one file | itself — **this is the Windows download** |
| `…-windows-x64-full.zip` | the engine, its DLLs, and `EC7Wolf-Setup.exe` | `EC7Wolf-Setup.exe` |
| `…-windows-x64.zip` | the engine and its DLLs | `EC7Wolf.cmd` |
| `…-linux-x64-full.tar.gz`<br>`…-linux-arm64-full.tar.gz` | the engine and the installer | `./installer/ec7wolf-setup` |
| `…-linux-x64.tar.gz`<br>`…-linux-arm64.tar.gz` | the engine | `./run-ec7wolf.sh` |
| `…-installer.zip` | the installer as Python, no engine — see route 4 | `installer/ec7wolf-setup` |
| `…-source.tar.gz` | the complete source | see route 5 |

Every archive carries an `INSTALL.txt` at the top saying what it holds and what
to run.

These carry the engine and nothing of the game. Unpack, then either run the
installer from the `-full` archive to bring in your data, or place your eight
`.CO7` files beside the binary yourself:

```sh
tar xf EC7Wolf-1.0-beta114-linux-x64.tar.gz
cd EC7Wolf-1.0-beta114-linux-x64
cp /path/to/your/CO7/*.CO7 /path/to/your/CO7/CORR7CD.EXE .
./run-ec7wolf.sh
```

On Windows, unzip, copy the same files in beside `ec7wolf.exe`, and run
`EC7Wolf.cmd`. The SDL and libepoxy DLLs are already in the archive.

> **Linux binaries and glibc.** The release binaries are built on the CI
> runner's distribution. If yours is older you may see a `GLIBC_2.xx not found`
> error — use route 6, which builds against Ubuntu 20.04 and runs essentially
> anywhere.

---

### 3 · The installer from a terminal

`installer/ec7wolf-install` does everything the graphical one does, needs
nothing but Python 3.9+, and is what the automated tests drive.

```sh
# What is present and what is missing, changing nothing:
installer/ec7wolf-install --check

# A complete install:
installer/ec7wolf-install --source /path/to/Corridor7.cue

# Everything spelled out:
installer/ec7wolf-install \
    --source /dev/sr0 \
    --dest ~/games/ec7wolf \
    --engine ~/Downloads/EC7Wolf-1.0-beta114-linux-x64 \
    --jobs 8 \
    --verbose
```

| Option | Effect |
| --- | --- |
| `--source PATH` | the CD drive (`/dev/sr0`, `D:\`), a `.cue`, an `.iso`, or a folder |
| `--dest DIR` | where to install |
| `--engine DIR` | use a prebuilt engine from that folder instead of compiling |
| `--check` | report readiness and stop |
| `--force-build` | compile even though a built engine was found |
| `--build-dir DIR`, `--jobs N` | where and how hard to compile |
| `--no-music`, `--no-video` | skip the soundtrack or the cinematics |
| `--no-menu-shortcut`, `--no-desktop-shortcut` | skip the shortcuts |
| `--uninstall DIR` | remove an install and everything it registered |
| `--verbose`, `--log FILE` | every line on screen; the log is always written |

**Unattended**, for deployment — no window, answers on the command line, result
in the exit code:

```sh
installer/ec7wolf-setup --unattended --source /path/to/Corridor7.cue \
                        --dest /opt/ec7wolf --no-shortcuts
echo $?      # 0 installed · 1 bad arguments · 2 unusable source · 3 failed
```

On Windows, `EC7Wolf-Setup.exe /S` means the same thing.

---

### 4 · The installer, compiling for you

Download **`EC7Wolf-<version>-installer.zip`** — a few hundred kilobytes — and
run it. With no engine beside it and no source tree around it, it offers to
**download the source and build it**, and then obtains every build dependency
it can:

| Dependency | What the installer does |
| --- | --- |
| **The engine's source** | downloads the release's source archive |
| **SDL2, SDL2_mixer, SDL2_net** | uses the system's; on Windows fetches upstream's official VC packages; anywhere else builds them from source |
| **libepoxy** (the OpenGL loader) | uses the system's; builds it from source with meson if there is none |
| **The compiler** | Windows: finds Visual Studio itself and borrows its build environment, so no "Developer PowerShell" is needed. Elsewhere: your system compiler |
| **FFmpeg** | needed only to encode the CD soundtrack; without it the game uses the AdLib music |

Meson, when it is needed, goes into a virtual environment inside the
installer's own cache — nothing is added to your Python. Everything downloaded
or built lives in `.ec7wolf-cache` beside the install, and deleting that folder
undoes all of it.

What it cannot supply is a C++ compiler and CMake. If those are missing it
names them and gives the exact command for your system.

---

### 5 · Building by hand

The standard ECWolf CMake build. Dependencies: **SDL2, SDL2_mixer, SDL2_net,
zlib, libjpeg** (bzip2 is bundled and built internally if not found),
**libepoxy** and **OpenGL** for the hardware renderer, and optionally **GTK3**
for the native file dialog.

#### Linux

```sh
sudo apt install build-essential cmake ninja-build \
     libsdl2-dev libsdl2-mixer-dev libsdl2-net-dev \
     zlib1g-dev libjpeg-dev libbz2-dev libepoxy-dev libgtk-3-dev

cd ECWolf
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
cmake --build build     # yes, twice -- see below
```

This produces `build/ec7wolf` and `build/ec7wolf.pk3`.

> 🛠 **Build twice for a correct version string.** `gitinfo.h` is regenerated
> *after* `gitinfo.cpp` compiles, so a single pass embeds the previous commit's
> revision. Only the reported version is affected, but every packaging script
> and the CI workflow build twice for this reason.

> 🛠 **The pk3 is not the binary.** The port's gameplay data (DECORATE actors,
> translations) lives in **`ec7wolf.pk3`**. Rebuilding just the binary does not
> rebuild it — after editing anything under `wadsrc/`, build the `pk3` target
> (`ninja -C build pk3`) or your data changes silently do nothing.

> 🛠 **No libepoxy, no OpenGL.** Without it CMake prints a warning, drops the GL
> backend and builds a software-only game. It is a warning, not an error, so it
> is easy to miss — check for `ECWOLF_RENDERER_OPENGL` in the configure output
> if the renderer is not what you expected.

#### Windows

1. Install **[CMake](https://cmake.org/)** and **Visual Studio** with the
   *Desktop development with C++* workload (or MSYS2/MinGW-w64).
2. Obtain **SDL2**, **SDL2_mixer**, **SDL2_net** and **libepoxy**. The repository
   carries a `vcpkg.json`, so from the `ECWolf` directory:
   ```bat
   cd ECWolf
   vcpkg install
   ```
   No package names: `vcpkg install` with no arguments reads the manifest. This
   matters, because **the `vcpkg` that comes with Visual Studio only works this
   way.** Naming packages on the command line is *classic mode*, and the copy on
   a Developer PowerShell's PATH does not have it — it answers:

   > error: Could not locate a manifest (vcpkg.json) above the current working
   > directory. This vcpkg distribution does not have a classic mode instance.

   which means "you are in the wrong directory, or you wanted the manifest".
   Run it from `ECWolf`, where the manifest is.

   If you have your own bootstrapped clone of vcpkg, classic mode still works
   and the manifest is ignored:
   ```bat
   vcpkg install sdl2 sdl2-mixer sdl2-net libepoxy zlib bzip2 libjpeg-turbo
   ```

   Or take upstream's *VC development* zips and pass `-DSDL2_DIR=…\cmake` and
   friends, which is what the installer does.
3. Build **from a Developer PowerShell**, so `cl.exe` and Ninja are on the PATH:
   ```bat
   cd ECWolf
   cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release ^
         -DCMAKE_TOOLCHAIN_FILE=C:\vcpkg\scripts\buildsystems\vcpkg.cmake
   cmake --build build
   cmake --build build
   ```
   With the manifest, CMake installs the dependencies itself at configure time,
   so step 2 is optional — it is there so you can see the downloads happen
   before a build that looks like it has hung.

   The toolchain path is wherever your vcpkg lives. For the copy bundled with
   Visual Studio, ask it:
   ```bat
   where vcpkg
   ```
   and use the `scripts\buildsystems\vcpkg.cmake` beside it.
4. Put `ec7wolf.exe`, `ec7wolf.pk3` and the SDL and libepoxy **DLLs** together
   with your game data, then run it.

> 🛠 **No libepoxy, no OpenGL — on Windows too.** This list used to leave it
> out, which produced a build that worked and had quietly lost the hardware
> renderer. CMake says so, once, in the configure output:
> `ECWOLF_RENDERER_OPENGL requested but OpenGL/libepoxy not found`. If the game
> reports the software renderer at startup and you expected otherwise, that
> line is why.

> ⚠️ **If CMake is older than your Visual Studio** it will not have a generator
> for it — CMake 3.31 knows nothing of Visual Studio 2026 — and will quietly
> fall back to NMake Makefiles and then fail. Either update CMake, or build from
> a Developer PowerShell where Ninja and `cl.exe` are already on the PATH. (The
> installer detects this case and handles it; a hand build does not.)

#### Renderer options

OpenGL is the default and needs a GL 3.3 core context; if one cannot be created
the game demotes itself to the software raycaster for that run and says so,
without rewriting your config. Both are built by default and either can be
chosen in *Options → Video*, or pinned for one run with
`--vid-renderer software|opengl`.

| CMake option | Default | Effect |
| --- | --- | --- |
| `ECWOLF_RENDERER_OPENGL` | `ON` | Build the hardware renderer (needs libepoxy) |
| `ECWOLF_RENDERER_SOFTWARE` | `ON` | Build the original raycaster |
| `ECWOLF_RENDERER_VULKAN` | `OFF` | Not implemented; reserved |

---

### 6 · The portable Docker build

A locally-built binary links against your distro's glibc, so a build from a very
recent distribution will not start on an older one. To get a binary that runs on
essentially any modern desktop Linux, build it inside the bundled **Ubuntu
20.04** container:

```sh
./docker.sh
```

This produces a `release/` folder containing `ec7wolf` and `ec7wolf.pk3`, built
against an older glibc with the C++ runtime statically linked, and verifies the
result before finishing. See the top of [`docker.sh`](docker.sh) for details.

To bundle that with your legally-owned data into one self-contained folder:

```sh
tools/package_corridor7_release.sh ./release \
    /path/to/CO7 /path/to/output/release-package
/path/to/output/release-package/run-corridor7.sh
```

> 🚫 **Never commit or redistribute a release folder** — it contains the
> commercial Corridor 7 data.

---

### Running it

Any install made by the installer contains a launcher that keeps configuration
and saved games beside the game rather than in your home directory:

```sh
~/.local/share/ec7wolf/run-ec7wolf.sh          # Linux
%LOCALAPPDATA%\EC7Wolf\EC7Wolf.cmd             # Windows
```

Running the binary directly works too, as long as you say where the data is:

```sh
./ec7wolf --data /path/to/CO7 --nowait
./ec7wolf --data /path/to/CO7 --nowait --tedlevel MAP01 --skill 2   # straight in
```

`--data` takes the **file extension** of the game data (`CO7`), not a directory
— the engine looks in the current directory and the usual search paths. The
launcher runs `--data CO7` from inside the install folder for exactly this
reason.

| Where things go | Installed by the installer | Run by hand |
| --- | --- | --- |
| Configuration | `<install>/ec7wolf.cfg` | your usual config directory |
| Saved games | `<install>/saves/` | your usual save directory |
| Downloads and build caches | `.ec7wolf-cache` beside the install | — |
| The install log | `ec7wolf-install.log` beside the install | — |

### Uninstalling

Every install carries its own uninstaller, so removing it needs nothing else:

```sh
~/.local/share/ec7wolf/uninstall.sh            # Linux; --yes to skip the question
%LOCALAPPDATA%\EC7Wolf\Uninstall.cmd           # Windows
```

It lists what it will remove, warns you if saved games are inside, and takes the
menu entry, the desktop icon and (on Windows) the Add/Remove Programs entry with
it. On Windows it also appears in *Settings → Apps* like any other program.
`installer/ec7wolf-install --uninstall DIR` does the same from a terminal.

### When it goes wrong

| Symptom | Cause |
| --- | --- |
| *"This source is missing MAPTEMP.CO7…"* | you pointed it at the wrong folder or a non-game disc; the CD-ROM release is what it wants |
| The soundtrack is silent, the game is not | no FFmpeg when you installed, so the CD music was skipped; install FFmpeg and reinstall |
| No cinematics | your source is a folder rather than the disc — the FLIC files exist only on the CD |
| *"missing SDL2.dll"* on Windows | the DLLs did not travel with the binary; use an installer-made folder or copy them alongside |
| `GLIBC_2.xx not found` on Linux | the binary was built on a newer distribution than yours; use route 6 |
| The game looks blurry or too smooth | the upscaled asset pack and xBRZ filtering are on; *Options → Video* |
| It says it is using the software renderer | no GL 3.3 context, or the build had no libepoxy |

Every install writes `ec7wolf-install.log` beside the install folder, whatever
happens. It has the full detail, including the compiler's own messages.

### Controls

**The defaults are modern, not the original's.** This catches people out, so it
is worth saying twice: out of the box you move with **W A S D** and open things
with **E**. Corridor 7 in 1994 moved with the **arrow keys** and opened things
with **Space**.

| Action | Modern (default) | The original's |
| --- | --- | --- |
| Move forward / back | **W** / **S** | **Up** / **Down** arrow |
| Turn left / right | Left / Right arrow | Left / Right arrow |
| Sidestep | **A** / **D** | hold **Alt** and turn (A / D also work) |
| **Open, use, push** | **E** | **Space** |
| Fire | Ctrl, or the mouse | Ctrl |
| Run | Shift | Shift |

**To get the original's scheme:** tick *Use the original's controls* on the
installer's Options page, or run `ec7wolf-install --classic-controls`. Either
writes a configuration with those bindings before you first start the game.
Nothing is locked in — every key can be rebound in *Options → Controls*.

Everything else is the same either way:

| Input | Action |
| --- | --- |
| 1–8 | Select weapon |
| M | Plant proximity mine |
| **Enter** | **Cycle visor: Normal → Night Vision → Infrared** |
| Tab | Corridor 7's inset proximity map |
| F1 | Full-screen automap |
| Esc | Main menu |

---

## Testing & validation tools

The `tools/` directory carries the harnesses used to keep the port honest:

| Tool | Purpose |
| --- | --- |
| `../installer/ec7wolf-setup` | The graphical installer. Needs PySide6; everything it does, `ec7wolf-install` also does from a terminal. `--unattended --source … --dest …` installs with no window; `--remove DIR` takes one away. |
| `../installer/windows/build_setup.py` | Freeze the graphical installer into a single `EC7Wolf-Setup.exe`. Needs a Windows Python (Wine will do). |
| `../installer/ec7wolf-install` | Install EC7Wolf: build the engine and take the game's content off your CD. `--check` reports what is missing. |
| `uninstall.sh` | Written into each install: removes it, its menu entry and its icons. `--yes` to skip the question. |
| `c7disc.py` | Read Corridor 7's files off a disc, an image, or a folder. |
| `extract_c7_video.py` | Pull the three CD cinematics off a disc image into `video/`. |
| `make_cdaudio.py` | Rip the CD soundtrack into `cdaudio/`. |
| `run_gates.sh` | **Runs the whole suite.** One line per gate, tails whatever failed, non-zero on any failure. This is what CI runs too. |
| `test_corridor7_definitions.py` | Static checks that C7 mechanics stay wired correctly (e.g. the laser barrier remains non-solid, visor-gated, and 10-damage). |
| `test_corridor7.sh` | Repeatable development smoke test. |
| `validate_corridor7_maps.sh` | Load-check campaign / bonus / archive maps. |
| `test_corridor7_release_startup.sh` | Verify a packaged release boots title → menu → MAP01. |

```sh
tools/run_gates.sh                 # everything
tools/run_gates.sh gl_ laser       # substring match: just those gates
tools/run_gates.sh --list
```

Most gates drive the real game and so need the commercial data files, which
means a hosted CI runner cannot execute them. See [docs/ci.md](docs/ci.md) for
how that is split and how to register a runner that can.

---

## Known deviations (honesty section)

This is a **source-port compatibility reconstruction, not a cycle-accurate DOS
reimplementation.** Enemy health, weapon costs, music routing, map dispatch, and
campaign rules are reproduced from evidence; several movement, attack,
pain-chance, damage, and frame-timing constants remain **evidence-based
reconstructions** where the retail executable did not yield an unambiguous value.
The victory *page* after the ending is the port's own rendering rather than a
reproduction of the original's — but the **ending cinematic itself now plays**,
from `SEQFOUR.CO7` on the CD, which this once listed as missing. Multiplayer, the
network protocol, original demos, and non-CD executable editions are **not**
supported — this port targets the **250,776-byte CD/Steam executable family**.

Full detail, including which specific values are reconstructed, lives in
[`docs/corridor7.md`](docs/corridor7.md).

---

## Licensing

- The **engine** (this ECWolf fork) is distributed under the **GPL** — see
  [`docs/license-gpl.txt`](docs/license-gpl.txt), [`docs/license-id.txt`](docs/license-id.txt),
  and [`docs/copyright`](docs/copyright).
- **Corridor 7: Alien Invasion** and all of its data (maps, art, sound, music,
  the executable and its palette) remain the **property of their respective
  rights holders** and are **not** included, embedded, or redistributed here.
  You must supply them from your own legally-owned copy.

---

*Made with stubbornness, a strategy guide, a DOSBox debugger, and a lot of
vibecoding — because a great weird game deserved to run again.* 👾
