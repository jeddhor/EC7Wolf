"""Shots and sight pass Corridor 7's marker-105 screens, as in DOS (GitHub #31).

Usage: test_corridor7_sight_screens.py BUILD_DIR DATA_DIR WORK_DIR

CORR7CD.EXE's CheckLine (Ghidra 1ef0:1b83) lets a line through a solid cell
when plane 1 holds 105 or 107: the electric fences, the girder trusses and some
glass. The same routine serves the player's guns and every alien's sight and
shots. A lab corridor is cut by a row of fence cells (wall 6, marker 105) with
an Animated Probe beyond it; the player holds the trigger. Through the fence
the Probe is hit and shoots back. The control row is marker-104 glass (wall 57),
which the original's line stops: nothing is hit either way.
"""
from dataclasses import replace
from pathlib import Path
import os, re, shutil, subprocess, sys

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes

PLAYER_START, EMPTY, FLOOR, PROBE = 22, 18, 256, 116
SCREEN_X, PROBE_X = 9, 12

lab = work / 'lab'; lab.mkdir(parents=True); (work / 'saves').mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE', build / 'ec7wolf.pk3']:
    shutil.copyfile(p, lab / p.name)
source = list(read_archive(data / 'MAPTEMP.CO7').records)
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')


def fixture(wall, marker):
    records = source.copy()
    walls, things = [1] * 4096, [EMPTY] * 4096
    for y in range(9, 12):
        for x in range(4, 20):
            walls[y * 64 + x] = FLOOR
        walls[y * 64 + SCREEN_X] = wall
        things[y * 64 + SCREEN_X] = marker
    things[10 * 64 + 4] = PLAYER_START
    things[10 * 64 + PROBE_X] = PROBE
    records[0] = replace(records[0], planes=MapPlanes(
        64, 64, (tuple(walls), tuple(things), tuple([0] * 4096))))
    (lab / 'MAPTEMP.CO7').write_bytes(encode_archive(records))


def run(label, angle, fire_tics):
    actors = work / (label + '.actors')
    (work / (label + '.cfg')).write_text('MouseEnabled = 0;\n')
    args = [str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
            '--res', '320', '200', '--vid-renderer', 'software', '--tedlevel', 'MAP01',
            '--skill', '3', '--config', str(work / (label + '.cfg')),
            '--savedir', str(work / 'saves'), '--capture-rngseed', '1',
            '--capture-place', '1', '4.5', '10.5', str(angle),
            '--capture-health', '10000', '--capture-actors-player',
            '--capture-actors', str(actors),
            '--capture-hold-button', 'attack', '10', str(fire_tics), '--capture-maxtics', '420']
    with (work / (label + '.log')).open('w') as f:
        subprocess.run(args, cwd=lab, env=env, stdout=f, stderr=subprocess.STDOUT,
                       check=True, timeout=90)
    # tic class tilex tiley dir pathing attack health ...; the alien drops out
    # of the trace once it is dead.
    probe, player = [], []
    global awake
    awake = False
    for line in actors.read_text().splitlines():
        f = line.split()
        if len(f) < 8 or f[0] == '#':
            continue
        (player if f[1] == 'Player' else probe).append(int(f[7]))
        awake = awake or (f[1] != 'Player' and f[6] == '1')
    return probe, player


failed = False
def check(ok, what, detail):
    global failed
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        print('  ', detail, flush=True)
        failed = True


# Facing the Probe and firing: the player's shots. Facing away and firing a
# moment: the noise wakes the Probe (one sound area -- a screen cell is not a
# door), and whether it then shoots is its own line of sight.
fixture(6, 105)
probe, _ = run('fence-shoot', 0, 400)
check(probe and min(probe) < max(probe),
      'the player shoots a Probe through an electric fence (marker 105)', probe[:3] + probe[-3:])
probe, player = run('fence-woken', 180, 10)
check(min(player) < 10000,
      'a woken Probe shoots the player through the fence', (min(player), max(player)))

fixture(57, 104)
probe, _ = run('glass-shoot', 0, 400)
check(probe and min(probe) == max(probe),
      'marker-104 glass stops the player\'s shots', probe[:3] + probe[-3:])
probe, player = run('glass-woken', 180, 10)
check(awake and min(player) == 10000,
      'and the Probe\'s, though it is awake', (awake, min(player), max(player)))

sys.exit(1 if failed else 0)
