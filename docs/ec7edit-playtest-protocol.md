# The editor playtest protocol

How EC7Edit launches EC7Wolf on the map you are drawing, and how it knows what
happened. Milestone E9 of [the editor plan](corridor7-level-editor.md).

## Why there is a protocol at all

One failure makes an exit code useless. A preview WAD the engine cannot read is
**not fatal**: `FWadCollection::AddFile` prints `Could not stat` and returns, so
the engine carries on, loads the *shipped* map of that number, plays it, and
exits 0. A window appears, a screenshot looks right, the process ends cleanly —
and the map under test was never opened.

Everything below exists so the editor can tell that apart from success.

## The capability probe

```
$ ec7wolf --editor-capabilities
engine=EC7Wolf
version=1.0-beta191
editor-protocol=2
events=hello,data-selection,preview-load,map-entry,campaign-end,fatal,session-result
options=--editor-protocol,--editor-session,--data,--file,--tedlevel,--skill,...
renderers=software,opengl
```

Answers with **no game data, no config and no display**, because the editor asks
what a build supports before it knows whether the data it has is usable. It runs
before anything is initialised and exits.

## The event stream

Add `--editor-protocol 2 --editor-session NONCE` and the engine writes lines of

```
EC7EDIT <nonce> <event> key=value key=value
```

to stdout, each assembled in full and written once, then flushed — the parent
reads them *while the game is running*, and a report that arrives at exit is no
use for "did it get into the map".

| Event | When | Fields |
| --- | --- | --- |
| `hello` | the option was accepted | `engine`, `version` |
| `data-selection` | the base game data was chosen | `extension`, `directory` |
| `preview-load` | each resource reached the loader | `path`, `loaded=yes\|no`, `lumps` |
| `map-entry` | a floor was entered | `marker`, `name`, `mapname`, `spawnfilter`, `next`, `secretnext` |
| `campaign-end` | the campaign reached its ending | `via=EndTitle\|EndSequence:NAME` |
| `fatal` | the engine is about to die | `message` |
| `session-result` | last line, always | `outcome=quit\|exit\|error\|fatal` |

`name` is the MAPINFO display name and `mapname` is the one stored in the map
record itself. Both, because only the second distinguishes the editor's map from
the shipped map of that number: MAPINFO names MAP01 "Corridor 7 Level 1"
whichever file the data came from, so a reader checking the display name cannot
tell it played the wrong floor.

`next` and `secretnext` are what MAPINFO resolved for the level, reported as
`-` when there is none. They arrived with **protocol 2**, for map packs: a
generated campaign's routing has to be checkable against what the engine read,
not against the text that was written, because those are the same thing only if
the generator is right — which is the claim under test. The version match stays
exact in both directions; a reader that ignores keys it does not know is a
reader that silently accepts a protocol it cannot check.

`campaign-end` is sent before the fade, and it is the only way to tell a
finished campaign from a hung one: what follows is the victory page, which
waits for a keypress. Nothing a test can send reaches that page --
`--capture-maxtics` and `--capture-maxframes` are both checked inside the play
loop, and the page is not in it -- so a run that finished the game and a run
that stopped responding look identical from outside. They are not the same
thing, and the editor's Test Log says which one happened.

`loaded=no` is the whole point: it is reported from inside the loader, which is
the only place that knows, and it is what turns the silent failure above into a
sentence the editor can show.

### The nonce is not decoration

The engine prints plenty of other lines, and **the map under test is user
content that can print**. A reader matching `EC7EDIT ` alone could be handed a
forged `map-entry` by the very map it is testing. The editor matches on the
nonce it generated for this launch and discards everything else.

The nonce is also *claimed* during argument parsing, so it never reaches the wad
loader — otherwise the engine would echo it back inside `Could not stat <NONCE>`
and a gate grepping for the nonce would satisfy itself.

## Arguments are consumed, not merely read

This fork has **seven independent argv scanners that never communicate**, and
only the last one, `CheckParameters`, has a catch-all — `else files.Push(argv[i])`
— with no `-` guard. Anything an earlier scanner read but did not *claim* was
handed to the wad loader as a filename.

That was live: `--vid-renderer` and its value, `--no-upscale`, `--gl-debug`,
`--gl-profile`, `--vis-diff` and **fifteen of the thirty-three `--capture-*`
options** each printed a `Could not stat` line on every run that used them. The
capture list was kept twice by hand and had drifted.

It is now kept once. `Capture::ParseArgs` records the argv indices it consumed
and `CheckParameters` asks; the editor link does the same. A gate asserts the
misparse count is **zero**, which E10 depends on.

## What the editor does with it

`ec7edit_core.engine_runner` holds a `Session` state machine driven entirely by
lines, so the whole thing is testable without a process:

```
IDLE → STARTING → LOADING → PLAYING → FINISHED
                     ↓          ↓
                   FAILED ←─────┘
```

`FINISHED` requires **both** that the editor's own WAD reported `loaded=yes` and
that a `map-entry` arrived. Anything else is `FAILED`, with a sentence saying how
far it got: the engine never answered, or it died before loading the map, or it
loaded the map and died in it, or it read the shipped map instead of yours.

Each launch gets its own session directory holding the export, the engine's
config, its saves and the log — never the player's own, because a playtest must
not rewrite the settings or saved games of somebody who also plays this game.
The log is headed with the session id, the project revision and the SHA-256 of
the exported WAD, so it can be matched to what it describes.

The engine runs under `QProcess`, so the editor stays usable while it does, and
closing the editor stops it: it is a child process, and leaving it behind means
a window nobody owns still writing into a directory the next launch reuses.

## Gate

`ec7edit_e9` asserts all of the above against the real engine, including that a
missing preview WAD is reported while the engine still exits 0 — the failure
this protocol exists for.
