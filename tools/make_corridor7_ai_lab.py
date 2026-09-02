#!/usr/bin/env python3
"""Build a one-corridor Corridor 7 map for observing a single alien's AI.

Enemy behavior is hard to test on a released floor: the aliens there are mixed
together, so a sound or a wake-up cannot be attributed to one class, and their
spacing is whatever the level designer wanted rather than whatever the test
needs. This writes a MAPTEMP whose first level is an empty east-west corridor
with the player at x=4 and the requested aliens at chosen x positions, so
"did this one alien react, and at what range" has an unambiguous answer.

The same construction drives the DOS-side DMA sound captures, where an empty
room is the difference between "this sample belongs to the Rodex" and "this
sample happened while a Rodex was on screen".

The floor is a sound area (256), the same word the shipped maps use most, and
not zero. Corridor 7's floor words are Wolf3D areas: the engine decides whether
a monster hears gunfire by asking CheckLink() whether the shooter's area
reaches the listener's, and CheckLink answers false the moment either side is
NULL. A lab floored with zeros is one where nothing can hear anything, which
would quietly make any hearing test unfalsifiable.

A placement is `OBJECT:X`, or `OBJECT:X:ROW` to put it ROW tiles north of the
player's row -- which is how an alien is placed out of the line of fire, so
that what reaches it can only have been the sound. The corridor is made just
tall enough for the placements given, so `OBJECT:X` alone still builds the
one-tile corridor it always did. `door:X` puts a plain door across it. A corridor with a door and nothing
else in it is what the renderer gates want: a door on screen with no sprite
drawn after it is the case where leftover door state reaches the view model.

Usage:
  make_corridor7_ai_lab.py SOURCE OUT (OBJECT|door):X [(OBJECT|door):X ...]

SOURCE is a pristine MAPTEMP.CO7. It is only ever read.

WARNING: pass a real path for OUT, never a symlink into a game-data directory.
This writes a complete archive, and following a symlink would overwrite the
original maps.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "editor"))

from ec7edit_core.archive import encode_archive, read_archive  # noqa: E402
from ec7edit_core.names import NativeName  # noqa: E402
from ec7edit_core.paths import OutputGuard, SourceIdentity, atomic_write  # noqa: E402
from ec7edit_core.planes import MapPlanes  # noqa: E402

PLAYER_START = 20   # plane-1 value for a player start facing east
EMPTY = 18          # plane-1 filler
SOLID = 1           # plane-0 wall
FLOOR = 256         # plane-0 open floor: a sound area, NOT zero -- see below
DOOR = 254          # plane-0 word for a plain door
PLAYER_X = 4
ROW = 32


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(f"usage: {sys.argv[0]} SOURCE OUT OBJECT:X [OBJECT:X ...]")

    source, out = Path(sys.argv[1]), Path(sys.argv[2])

    placements = []
    doors = []
    for spec in sys.argv[3:]:
        obj, _, rest = spec.partition(":")
        if not rest:
            sys.exit(f"bad placement {spec!r}, expected OBJECT:X[:ROW] or door:X")
        x, _, row = rest.partition(":")
        if obj == "door":
            doors.append(int(x))
        else:
            placements.append((int(obj), int(x), int(row) if row else 0))

    identity = SourceIdentity.probe(source)
    guard = OutputGuard.for_source(source)
    output = guard.check(out)

    archive = read_archive(source)
    records = list(archive.records)
    width, height = records[0].width, records[0].height

    things = [EMPTY] * (width * height)
    meta = [0] * (width * height)

    walls = [FLOOR] * (width * height)
    for x in range(width):
        walls[x] = walls[(height - 1) * width + x] = SOLID
    for y in range(height):
        walls[y * width] = walls[y * width + width - 1] = SOLID
    # As short a corridor as the placements allow: with everything on the
    # player's own row it is one tile tall, so an alien's line to the player is
    # never in doubt and a wake-up can only be explained by range.
    hall = max([row for _, _, row in placements] + [0])
    for x in range(1, width - 1):
        walls[(ROW - hall - 1) * width + x] = SOLID
        walls[(ROW + 1) * width + x] = SOLID

    # The corridor walls above and below mean the door's axis is inferred as
    # east-west, which is the way the player walks through it.
    for x in doors:
        if not 1 <= x < width - 1 or x == PLAYER_X:
            sys.exit(f"door x={x} is outside the corridor or on the player")
        walls[ROW * width + x] = DOOR

    things[ROW * width + PLAYER_X] = PLAYER_START
    for obj, x, row in placements:
        if not 1 <= x < width - 1 or (x == PLAYER_X and row == 0):
            sys.exit(f"placement x={x} is outside the corridor or on the player")
        things[(ROW - row) * width + x] = obj

    records[0] = replace(
        records[0],
        name=NativeName.from_text("Corr7 AI Lab"),
        planes=MapPlanes(width, height, (tuple(walls), tuple(things), tuple(meta))),
        source=None,
    )
    atomic_write(output, encode_archive(records), guard=guard)
    identity.verify_unchanged()
    placed = ", ".join([f"object {o} at {x - PLAYER_X} tiles"
                        + (f", {r} north" if r else "")
                        for o, x, r in placements]
                       + [f"a door at {x - PLAYER_X} tiles" for x in doors])
    print(f"wrote {output} ({placed or 'an empty corridor'})")


if __name__ == "__main__":
    main()
