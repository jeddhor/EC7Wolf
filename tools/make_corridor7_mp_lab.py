#!/usr/bin/env python3
"""Build a Corridor 7 map for watching what the *other* player looks like.

Everything about a player that only the *other* machines can see -- the walk
cycle, the sprite's rotations, how tall the thing looks standing on the floor --
is untestable on a released arena, because the arenas are the one place
deliberately designed to keep players apart. GameMap::GenerateDeathmatchStarts
picks open floor and then spawns each player at the candidate farthest from
everyone else, so on a real arena the two of them begin at opposite ends of the
map and a tester spends their time navigating instead of looking.

This builds an east-west corridor with a single player start at the west end,
facing east, and is meant to be played *cooperative* rather than battle: the
deathmatch spawner is the thing being avoided, and in cooperative the map's own
start is used. Both players therefore begin on the same tile facing the same
way, so one can walk east down the corridor while the other stands still and
watches it recede -- centred, in the open, at a distance of your choosing.

A square room was tried first and is worse: every wall of an empty room looks
identical, so there is no way to tell from a screenshot which way you are
facing, and finding the other player means sweeping blindly and hoping.

Usage:
  make_corridor7_mp_lab.py SOURCE OUT [LENGTH]

SOURCE is a pristine MAPTEMP.CO7, only ever read. LENGTH is the corridor's
interior length in tiles, default 24.

SOURCE is never opened for writing, and OUT is refused if it resolves to the
source, to a hard or symbolic link aliasing it, or to anywhere in the source's
directory. The write is atomic and read back, and the source's digest is
checked again afterwards.
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
ROW = 32            # the corridor's row, as in the AI lab
PLAYER_X = 2


def main() -> None:
    if not 3 <= len(sys.argv) <= 4:
        sys.exit(f"usage: {sys.argv[0]} SOURCE OUT [LENGTH]")

    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    length = int(sys.argv[3]) if len(sys.argv) == 4 else 24
    if length < 4:
        sys.exit("a corridor shorter than four tiles is not worth walking down")

    identity = SourceIdentity.probe(source)
    guard = OutputGuard.for_source(source)
    output = guard.check(out)

    archive = read_archive(source)
    records = list(archive.records)
    width, height = records[0].width, records[0].height
    if PLAYER_X + length + 1 > width or ROW + 1 >= height:
        sys.exit(f"a {length}-tile corridor does not fit in {width}x{height}")

    # Solid everywhere, then cut the corridor out of it. Filling first means
    # every tile off the corridor is wall rather than the original level's
    # geometry, so nothing can spawn, make a noise, or be wandered into.
    walls = [SOLID] * (width * height)
    things = [EMPTY] * (width * height)
    meta = [0] * (width * height)

    for x in range(PLAYER_X, PLAYER_X + length):
        walls[ROW * width + x] = 0
    things[ROW * width + PLAYER_X] = PLAYER_START

    records[0] = replace(
        records[0],
        name=NativeName.from_text("Corr7 MP Lab"),
        planes=MapPlanes(width, height, (tuple(walls), tuple(things), tuple(meta))),
        source=None,
    )
    atomic_write(output, encode_archive(records), guard=guard)
    identity.verify_unchanged()
    print(f"wrote {output} (a {length}-tile corridor, players start together facing east)")


if __name__ == "__main__":
    main()
