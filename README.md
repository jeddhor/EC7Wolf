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

## Building & running

This fork uses the standard ECWolf CMake build. Dependencies are the ECWolf set:
**SDL2, SDL2_mixer, SDL2_net, zlib, libjpeg** (bzip2 is bundled and built
internally if not found), plus **OpenGL** for the hardware renderer and
optionally **GTK3** for the native file dialog.

### Linux

**Install dependencies** (Debian/Ubuntu shown; adjust for your distro):
```sh
sudo apt install build-essential cmake ninja-build \
     libsdl2-dev libsdl2-mixer-dev libsdl2-net-dev \
     zlib1g-dev libjpeg-dev libbz2-dev libgtk-3-dev
```

**Configure & build:**
```sh
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

**Renderer options.** OpenGL is the default renderer and needs a GL 3.3 core
context; if one cannot be created the game demotes itself to the software
raycaster for that run and says so, without rewriting your config. Both are
built by default and either can be chosen in *Options → Video*, or pinned for
one run with `--vid-renderer software|opengl`.

| CMake option | Default | Effect |
| --- | --- | --- |
| `ECWOLF_RENDERER_OPENGL` | `ON` | Build the hardware renderer |
| `ECWOLF_RENDERER_SOFTWARE` | `ON` | Build the original raycaster |
| `ECWOLF_RENDERER_VULKAN` | `OFF` | Not implemented; reserved |

**To run the test suite** you also need `xvfb`, `x11-utils`, `imagemagick` and
`python3`; see [Testing & validation tools](#testing--validation-tools).

> 🛠 **Build gotcha:** the port's gameplay data (DECORATE actors, translations)
> lives in **`ec7wolf.pk3`**. Rebuilding just the binary does **not** rebuild the
> pk3 — after editing anything under `wadsrc/`, build the `pk3` target
> (`ninja -C build pk3` / `ninja -C build ec7wolf pk3`) or your data changes
> silently do nothing.

**Run** (point `--data` at the `CO7` folder you assembled):
```sh
./build/ec7wolf --data /path/to/CO7 --nowait
```
Or start straight into the first floor for testing:
```sh
./build/ec7wolf --data /path/to/CO7 --nowait --tedlevel MAP01 --skill 2
```

### Windows

1. Install **[CMake](https://cmake.org/)**, **[Ninja](https://ninja-build.org/)**,
   and either **Visual Studio** (Desktop C++ workload) or **MSYS2/MinGW-w64**.
2. Obtain the **SDL2**, **SDL2_mixer**, and **SDL2_net** development libraries
   (VC or MinGW variants to match your toolchain). zlib and libjpeg as well; a
   package manager such as **vcpkg** makes this painless:
   ```bat
   vcpkg install sdl2 sdl2-mixer sdl2-net zlib libjpeg-turbo bzip2
   ```
3. Configure & build (from a *Developer* prompt, adjusting the toolchain path if
   using vcpkg):
   ```bat
   cd ECWolf
   cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release ^
         -DCMAKE_TOOLCHAIN_FILE=C:\vcpkg\scripts\buildsystems\vcpkg.cmake
   cmake --build build
   ```
   (Or open the folder in Visual Studio, which reads the CMake project directly.)
4. Place `ec7wolf.exe`, `ec7wolf.pk3`, and the required **SDL2 `.dll`s** together,
   then run:
   ```bat
   ec7wolf.exe --data C:\path\to\CO7 --nowait
   ```

### Portable, drop-anywhere build (`docker.sh`)

A locally-built binary links against your distro's glibc, so a build from a very
recent distribution won't start on an older one (or on rolling distros with a
different libc build). To get a binary that runs on essentially any modern
desktop Linux, build it inside the bundled **Ubuntu 20.04** container:

```sh
./docker.sh
```

This produces a `release/` folder containing `ec7wolf` and `ec7wolf.pk3`, built
against an older glibc with the C++ runtime statically linked, and verifies the
result before finishing. See the top of [`docker.sh`](docker.sh) for details.

### One-command playable release

To bundle a build together with a copy of your legally-owned game data into a
single self-contained folder (feed it the `release/` folder from `docker.sh`, or
any build directory):

```sh
tools/package_corridor7_release.sh ./release \
    /path/to/CO7 /path/to/output/release-package
/path/to/output/release-package/run-corridor7.sh
```

The generated `run-corridor7.sh` launches the game and keeps its config and
saves inside the release folder.

> 🚫 **Never commit or redistribute a release folder** — it contains the
> commercial Corridor 7 data.

### Handy controls (matching the original)

| Input | Action |
| --- | --- |
| Arrows / WASD + mouse | Move & turn |
| Ctrl / mouse | Fire |
| Space | Open / use doors, computers, dispensers, chambers, pushwalls |
| 1–8 | Select weapon |
| M | Plant proximity mine |
| **Enter** | **Cycle visor: Normal → Night Vision → Infrared** |
| Tab | Toggle proximity map |
| Esc | Main menu |

---

## Testing & validation tools

The `tools/` directory carries the harnesses used to keep the port honest:

| Tool | Purpose |
| --- | --- |
| `../installer/ec7wolf-setup` | The graphical installer. Needs PySide6; everything it does, `ec7wolf-install` also does from a terminal. |
| `../installer/ec7wolf-install` | Install EC7Wolf: build the engine and take the game's content off your CD. `--check` reports what is missing. |
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
The final victory sequence is a reconstruction because the installation does not
contain the external cinematic files the executable references. Multiplayer, the
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
