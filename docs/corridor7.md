# Corridor 7 support (experimental)

This branch can detect the supplied Steam/CD installation of **Corridor 7:
Alien Invasion**, read its original files directly, and enter its maps. ECWolf
does not include commercial Corridor 7 data; you must provide your own files.

Place these files together in a game-data directory and point ECWolf at it:

- `CORR7CD.EXE`
- `MAPTEMP.CO7`
- `GFXTILES.CO7`
- `VGADICT.CO7`, `VGAHEAD.CO7`, `VGAGRAPH.CO7`
- `AUDIOHED.CO7`, `AUDIOT.CO7`

For a direct development launch from that directory:

```sh
ecwolf --data CO7 --nowait --tedlevel MAP01 --skill 2
```

From the supplied development workspace, the repeatable build/detection/map
smoke test is:

```sh
tools/test_corridor7.sh /path/to/ecwolf-build /path/to/CORR7CD
```

The currently recognized edition uses the 250,776-byte `CORR7CD.EXE`; its
external palette is read at runtime and is never embedded in ECWolf.

## Current limitations

Map loading, the ordinary wall set, the gameplay palette, player spawn, and
movement work. Special/masked walls use safe fallbacks except for the verified
level-1 “A” wall appearance. Static objects, enemies, doors, keys, exits,
weapons, Corridor 7’s HUD/menus, sound ID mapping, music, objectives, and level
progression are not implemented yet. Unknown non-empty object IDs are logged
with map coordinates.
