# Snapshot, and the decision not to build a second renderer

How EC7Edit shows you what a tile actually looks like in EC7Wolf, and why it
does it by asking the engine rather than by drawing the world itself. Milestone
E10 of [the editor plan](corridor7-level-editor.md).

## The argument

The tempting thing is an approximate 3D view inside the editor: pan around the
map, see the walls. The reason not to is that it would be **a second authority
on what Corridor 7 looks like**. The engine already decides how a wall is
shaded, which side of a door faces you, what a masked pane does at an angle,
and what the visor palette does to all of it. A Python renderer would agree
with that until it did not, and the first time they disagreed the editor would
be quietly wrong — about the one thing somebody opened it to check.

So the picture comes from the engine. The editor asks it to stand on a tile,
face an angle, draw one frame, and exit.

## What makes it usable

**Anchored to a simulation tic, not a frame.** How many frames pass in a tic
depends on how fast the machine draws, so "frame 30" is a different moment on a
busy box than an idle one. `--capture-snapshot PATH TIC` shoots the first frame
at or after a *tic*, which is the same moment everywhere. That is what makes
the same request give byte-identical output.

**The camera is checked before the engine is asked, and again by the engine.**
A tile outside the map, or one with a wall in it, produces a picture of nothing
— and the engine would draw it without complaining. The editor refuses it
against the document; the engine refuses it against the map that actually
loaded, which is not the same check: the map the engine got is the one that
matters.

`--capture-warp` is now strictly parsed, too. `atof` answers 0 for `banana` and
returns a NaN for `nan`, and a camera at NaN moved the player somewhere no
arithmetic recovers from, silently.

**The software profile is sealed.** `--vid-renderer software`, a fixed
resolution, `--no-upscale`. Not offered as a choice: the PNG path is only a
true picture of the world under software. With OpenGL live the GPU owns the
world and the 8-bit framebuffer this reads holds just the 2D overlay — which is
how a parity gate in this project once passed while comparing a black frame. A
GL snapshot is a different contract (its own PPM capture) and is not what this
writes.

**A blank frame is a failure, not a result.** Every snapshot is checked for
having a world in it before it is shown or cached. Nothing is cached on
failure: a flat frame kept under a cache key would be handed back for ever.

**The cache is keyed by everything that could change the picture** — the engine
binary, its pk3, the game data fingerprint, the exported map, the render
profile, the camera and the tic. A key that left any of those out would return
a stale image after exactly the change somebody took the snapshot to see. The
cache lives in the workspace, is derived and disposable, and never enters a
project file: a snapshot is a picture of the user's own game data.

## Using it

Pick the **Camera** tool (K), click a floor tile, then **Take a snapshot** (F7).
*Turn 90°* re-aims without moving. The panel says which camera the picture is
from, and adds "edited since" once the map has changed under it — the picture is
kept rather than thrown away, because an out-of-date snapshot is still useful as
long as nobody is told it is current.

## The interactive-preview decision: no-go

Section 16.8 gates a live in-editor 3D view behind eight criteria. It is closed,
deliberately, and no prototype code was written to be removed later.

The criterion it fails is the last and least negotiable: *no engine/runtime
semantics are moved into the approximate renderer as a new authority*. Corridor
7's appearance is not separable from engine behavior — a door's axis is
inferred from surrounding floor at load time, the visor palette is a DAC ramp
the renderer animates, laser-barrier statics are gated on an inventory token,
and floor and ceiling shading comes from a per-band screen-space rule rather
than distance. An approximate renderer either reimplements those, and becomes a
second authority, or omits them, and shows a map that is not this game.

Snapshot answers the question the preview was for — "what does this actually
look like?" — with the engine's own answer, at the cost of a click instead of a
pan. That is a scope decision, not a shortfall.

## Gate

`ec7edit_e10` asserts all of the above against the real engine: a real frame
with a world in it, byte-identical repeats, a turned camera giving a different
picture, all three invalid-camera refusals, zero options misread as filenames,
a cache key that moves with its inputs, and the retail archive unchanged.
