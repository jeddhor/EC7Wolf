"""An open force-field door is still open after a load (GitHub #58).

Usage: test_corridor7_saved_doors.py BUILD_DIR DATA_DIR WORK_DIR

A force-field door's plane-1 marker is its state: 106 while the barrier is up,
107 once the aperture is open, and shots and sight pass only 107. The marker
was not saved, so a load rebuilt it from the map: the door came back drawn
open and walkable (texture and solidity were saved) but stopping every shot,
and using it opened it again instead of closing it.

Lab: a one-tile corridor with a door (wall 49, marker 106), then an electric
fence (wall 6, marker 105), which passes shots but not aliens, then a
Mechanoid. The player opens the door and the game is saved; a second run
loads the save and fires down the corridor. The Mechanoid must be hit.
"""
from dataclasses import replace
from pathlib import Path
import os, re, shutil, subprocess, sys

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes

PLAYER_START, EMPTY, FLOOR, ALIEN = 22, 18, 256, 232
DOOR_WALL, DOOR_MARKER, FENCE_WALL, FENCE_MARKER = 49, 106, 6, 105
DOOR_X, FENCE_X, ALIEN_X = 8, 11, 15

lab = work / 'lab'; lab.mkdir(parents=True); (work / 'saves').mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE', build / 'ec7wolf.pk3']:
    shutil.copyfile(p, lab / p.name)
records = list(read_archive(data / 'MAPTEMP.CO7').records)
walls, things = [1] * 4096, [EMPTY] * 4096
for x in range(4, 20):
    walls[10 * 64 + x] = FLOOR
walls[10 * 64 + DOOR_X] = DOOR_WALL
things[10 * 64 + DOOR_X] = DOOR_MARKER
walls[10 * 64 + FENCE_X] = FENCE_WALL
things[10 * 64 + FENCE_X] = FENCE_MARKER
things[10 * 64 + 4] = PLAYER_START
things[10 * 64 + ALIEN_X] = ALIEN
records[0] = replace(records[0], planes=MapPlanes(
    64, 64, (tuple(walls), tuple(things), tuple([0] * 4096))))
(lab / 'MAPTEMP.CO7').write_bytes(encode_archive(records))
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')


def run(label, extra):
    (work / (label + '.cfg')).write_text('MouseEnabled = 0;\n')
    actors = work / (label + '.actors')
    args = [str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
            '--res', '320', '200', '--vid-renderer', 'software', '--tedlevel', 'MAP01',
            '--skill', '3', '--config', str(work / (label + '.cfg')),
            '--savedir', str(work / 'saves'), '--capture-rngseed', '1',
            '--capture-health', '100000', '--capture-actors', str(actors), *extra]
    log = work / (label + '.log')
    with log.open('w') as f:
        subprocess.run(args, cwd=lab, env=env, stdout=f, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    alien = [int(l.split()[7]) for l in actors.read_text().splitlines()[1:]
             if l.split()[1] == 'C7Mechanoid']
    return log.read_text(), alien


failed = False
def check(ok, what, detail):
    global failed
    print('  %s %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok:
        failed = True
        print('         %s' % (detail,))


print('The player opens the door and saves')
text, alien = run('open', ('--capture-place', '1', '7.5', '10.5', '0',
                           '--capture-use', '5', '2', '--capture-save', '120', 'door.ecs',
                           '--capture-maxtics', '160'))
check((work / 'saves' / 'door.ecs').exists(), 'the game was saved with the door open', text[-600:])
check(alien and alien[-1] == alien[0], 'nothing has shot the Mechanoid yet', alien[-3:])

print('\nThe save is loaded and the player fires down the corridor')
text, alien = run('shoot', ('--capture-load', '5', 'door.ecs',
                            '--capture-hold-button', 'attack', '0', '100000',
                            '--capture-maxtics', '400'))
check('loaded snapshot door.ecs' in text, 'the save loaded', text[-600:])
check(alien and min(alien) < alien[0],
      'shots pass the reloaded open door and hit the Mechanoid', (alien[:1], alien[-1:], len(alien)))

print('\n%s' % ('FAIL: see above.' if failed else
                'PASS: an open force-field door is still open after a load.'))
sys.exit(1 if failed else 0)
