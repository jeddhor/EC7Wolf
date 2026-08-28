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

WARNING: pass a real path for OUT, never a symlink into a game-data directory.
This writes a complete archive, and following a symlink would overwrite the
original maps.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "python"))

from corridor7_map import MapData, encode_archive, parse_archive  # noqa: E402

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
    if out.is_symlink():
        sys.exit(f"refusing to write through the symlink {out}")
    if length < 4:
        sys.exit("a corridor shorter than four tiles is not worth walking down")

    maps = list(parse_archive(source.read_bytes()))
    header = maps[0].header
    width, height = header.width, header.height
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

    maps[0] = MapData(
        replace(header, name="Corr7 MP Lab"),
        (tuple(walls), tuple(things), tuple(meta)),
    )
    out.write_bytes(encode_archive(tuple(maps)))
    print(f"wrote {out} (a {length}-tile corridor, players start together facing east)")


if __name__ == "__main__":
    main()
