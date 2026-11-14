#!/usr/bin/env python3
"""Build a Corridor 7 map for watching who an Intruder Alert wakes (GitHub #24).

The released alarm panel (CORR7CD.EXE 14bfd) makes one frame of the same noise
a gunshot makes, and SightPlayer (136e1) decides who reacts to it. This lab puts
one of each case the native rules distinguish where nothing but that noise can
reach it -- every alien faces away from the player and stands out of
automatic-sight range, so a wake-up in a run with no noise means the lab is
broken, not that the rule is:

  * NEAR: an ordinary Rodex in the player's room (area 256), two tiles behind
    the player. The noise reaches it under either rule.
  * DOOR: an ordinary Rodex in a second room (area 257) behind a closed door.
    The classic alarm does not reach it; the map-wide one does.
  * AMBUSH: a block of twenty-seven Rodexes standing on the ambush floor word
    278 in the player's room. They hear the noise, but an ambusher only ever draws
    for a delayed wake-up (25 in 256, then 32 to 8192 tics); none reacts at
    once.

The player starts at x=6 facing east, with the alarm terminal (wall ID 30)
directly ahead at x=7, so `--capture-use` raises the alarm.

Usage:
  make_corridor7_alarm_lab.py SOURCE OUT

SOURCE is a pristine MAPTEMP.CO7 and is only ever read. Pass a real path for
OUT, never a symlink into a game-data directory: this writes a complete archive.
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

PLAYER_EAST = 20    # plane-1 player start facing east
EMPTY = 18          # plane-1 filler
RODEX_WEST = 218    # plane-1 Rodex (216 + facing): standing, facing west
SOLID = 1           # plane-0 wall
TERMINAL = 30       # plane-0 intruder-alarm terminal (xlat trigger 30)
DOOR = 254          # plane-0 plain door
AREA_A = 256        # plane-0 floor: the player's sound area
AREA_B = 257        # plane-0 floor: the room behind the door
AMBUSH = 278        # plane-0 ambush floor ("modzone 278 fillzone ambush")

PLAYER = (6, 32)
NEAR = (4, 32)
DOOR_AT = (12, 32)
BEHIND_DOOR = (16, 32)
AMBUSHERS = [(x, y) for x in (1, 2, 3) for y in range(24, 41, 2)]


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} SOURCE OUT")
    source, out = Path(sys.argv[1]), Path(sys.argv[2])

    identity = SourceIdentity.probe(source)
    guard = OutputGuard.for_source(source)
    output = guard.check(out)

    archive = read_archive(source)
    records = list(archive.records)
    width, height = records[0].width, records[0].height

    walls = [SOLID] * (width * height)
    things = [EMPTY] * (width * height)
    meta = [0] * (width * height)

    def put(plane, xy, value):
        x, y = xy
        plane[y * width + x] = value

    # Room A: the player's, with the terminal standing in it.
    for y in range(24, 41):
        for x in range(1, 12):
            put(walls, (x, y), AREA_A)
    put(walls, (PLAYER[0] + 1, PLAYER[1]), TERMINAL)
    # Room B, sealed from A by the wall at x=12 except for one closed door.
    for y in range(30, 35):
        for x in range(13, 21):
            put(walls, (x, y), AREA_B)
    put(walls, DOOR_AT, DOOR)

    put(things, PLAYER, PLAYER_EAST)
    put(things, NEAR, RODEX_WEST)
    put(things, BEHIND_DOOR, RODEX_WEST)
    for xy in AMBUSHERS:
        put(walls, xy, AMBUSH)
        put(things, xy, RODEX_WEST)

    records[0] = replace(
        records[0],
        name=NativeName.from_text("Corr7 Alarm Lab"),
        planes=MapPlanes(width, height, (tuple(walls), tuple(things), tuple(meta))),
        source=None,
    )
    atomic_write(output, encode_archive(records), guard=guard)
    identity.verify_unchanged()
    print(f"wrote {output}: near {NEAR}, behind door {BEHIND_DOOR}, "
          f"{len(AMBUSHERS)} ambushers")


if __name__ == "__main__":
    main()
