# Map packs

Everything the editor exported before this was a *preview*: an override WAD
holding markers and PLANES and nothing else, so the engine played your map in a
stock slot, under the stock level's name, with the stock level's music and the
stock level's idea of where the exit goes. That is the right shape for testing
one map. It is the wrong shape for giving somebody three.

A pack is the other export. Same maps, plus a generated `MAPINFO` lump that
names them, orders them, and says what happens at each exit — and a manifest
that says what the file is and what the person receiving it needs.

## Making one

**File > Campaign** lists your maps and asks three things about each: what it
is called in game, where its exit goes, and whether it has a secret exit. The
first row is where a new game starts; *Move up* changes that. Everything is
checked as you type, and the panel at the bottom is the same list of problems
the command line prints — there is no second opinion in the dialog.

**File > Export a map pack…** writes two files: `yourpack.wad` and
`yourpack.txt`. The manifest is written whether you ask for it or not, because
a file that travels needs to say what it is.

From the command line:

    python3 -m ec7edit_core project-pack yours.ec7project --output pack.wad
    python3 -m ec7edit_core pack-audit pack.wad

`--strict` makes warnings block the build. `pack-audit` reads a pack back and
names everything in it, including a pack this editor did not write.

## What the engine does with it

Three facts about `G_ParseMapInfo` shape the whole design, and they are worth
knowing before you pick slot numbers.

**Later wins, and it wins completely.** The iwad's own mapinfo is parsed first,
then every lump named `MAPINFO` in load order. A `map` block does
`LevelInfo newMap = defaultMap; ...; existing = newMap` — an assignment, not a
merge. So a block for a slot the stock game defines does not adjust that level,
it *replaces* it, starting from whatever `defaultmap` held.

That is why a pack builds on **MAP61 and up** by default. Corridor 7 defines
MAP01–MAP60; above that line there is nothing to replace, so a pack cannot
regress a shipped level however wrong its metadata is. Using a stock slot is
allowed and warns (`C7E-PACK-005`), because replacing a stock level is a thing
someone may mean to do.

A slot above MAP60 exists in no archive. The engine finds a map by lump name
(`Wads.CheckNumForName` in `gamemap.cpp`), not by index into `MAPTEMP.CO7`, so
a marker that exists only in your pack is a level like any other.

**A campaign ends by naming it.** `next = "EndTitle"` is matched by name in
`wl_game.cpp` and runs the victory path — the fade, the SEQFOUR cinematic, the
tally, the victory page. It needs no intermission block, which matters here:
Corridor 7 defines exactly one (`DemoLoop`), so the `EndSequence, "..."` form
has nothing to point at in this game and is not offered.

**Strings escape three ways and no more.** `Scanner::Unescape` knows `\\`, `\"`
and `\n`. A level name is escaped for the first two, and anything that cannot
survive the round trip — a control byte, a character outside printable ASCII
the engine has no glyph for — is refused (`C7E-PACK-002`) rather than written
and hoped for. A level name is not a place to discover that a quote ended a
block early.

## Secret exits

Corridor 7 has no secret-exit tile. `Exit_Normal` sets `ex_secretlevel` only
when its `arg0` is 2, and no entry in `xlat/corridor7.txt` sets that.

What sets it is plane 1. `gamemap_planes.cpp` promotes the trigger on a wall-63
cell — the ordinary elevator switch — from `arg0 = 1` to `arg0 = 2` when the
otherwise-inert object value **99** sits on that same cell. That is the secret
elevator, and it is the only thing in the game that can take a `secretnext`
route.

So a campaign entry with a secret exit needs marker 99 on an elevator switch
somewhere in that map, and the editor says so (`C7E-PACK-008`) when it is
missing. The route is not wrong without it; it is simply unreachable.

## What a pack may contain

Two lumps per level — an empty `MAPxx` marker and the `PLANES` written from
your map — plus one `MAPINFO` and the manifest as a `PACKINFO` lump. Nothing
else. No textures, no sounds, no DECORATE, no palette. A pack cannot change how
the game behaves, only which levels it offers and the order they come in.

**A map imported from the retail archive cannot go in one** (`C7E-PACK-009`).
Its plane words are Corridor 7's, not yours, and a pack is made to be handed to
other people. Export a private full archive for that instead — that path exists
for exactly this and says out loud that its output is your own game data.

`audit_pack` answers "what is in this file" by reading the file, never by
remembering what was written to it. The CLI refuses to write a pack whose audit
it cannot account for, and so does the editor.

## The schema

Bounded on purpose. Per level: the slot, the name shown in game, the exit
route, an optional secret route, an optional music lump, an optional par time,
an optional floor number, and whether the tally screen appears. Per campaign: a
title and the episode's menu key. That is the whole surface.

Turning the tally off (`nointermission`) is worth knowing about: with it on,
the level change waits for a keypress, which is right for a normal campaign and
impossible for anything automated to watch.

## Gate

`ec7edit_e11` builds a three-map campaign in MAP61–63, drawn by the gate from
nothing, and plays it: the pack-only map loads under its generated name, the
engine reports resolving exactly the routes that were generated, the elevator
routes to `next`, the marker-99 elevator routes to `secretnext`, the bonus
floor returns, `EndTitle` ends the campaign -- reported by the engine's own
`campaign-end` event rather than inferred from the absence of a fourth level --
stock MAP01 still routes to MAP02 with the pack loaded, and the package
contains no plane word this gate did not write.
