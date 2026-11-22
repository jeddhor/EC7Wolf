"""A boss's voice is heard only from the player's area, as in DOS (GitHub #50).

Usage: test_corridor7_boss_sounds.py BUILD_DIR DATA_DIR WORK_DIR

CORR7CD.EXE's ambient action (18346), on the walk cycles of Tymok, Solrac,
the Eniram Boss, the Mechanoid and Otrebor, returns at once unless
areabyplayer[ob->areanumber]; only then does it roll one in seven. The port
rolled in A_Chase and played the sound wherever the alien stood, so Tymok on
floor 15 was heard across the whole floor.

Lab: a corridor (area 256) holds the player, a Tymok and a Solrac (hardest
skill, where both spawn), which hear the player fire and give chase. A second corridor (area 257) is sealed off. In the
control run the player stays put, and both bosses' voices are heard. In the
other, the player is moved into the sealed corridor once both are chasing; from
then on neither voice may be heard, though both keep chasing.
"""
from dataclasses import replace
from pathlib import Path
import os, re, shutil, subprocess, sys

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes

PLAYER_START, EMPTY, TYMOK, SOLRAC = 22, 18, 179, 214
AREA_A, AREA_B = 256, 257
MOVE_TIC, TICS = 210, 1800
VOICES = {'Tymok': 'c7/monster/active/class25', 'Solrac': 'c7/monster/active/class20'}

lab = work / 'lab'; lab.mkdir(parents=True); (work / 'saves').mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE', build / 'ec7wolf.pk3']:
    shutil.copyfile(p, lab / p.name)
records = list(read_archive(data / 'MAPTEMP.CO7').records)
walls, things = [1] * 4096, [EMPTY] * 4096
for y in range(9, 12):
    for x in range(4, 30):
        walls[y * 64 + x] = AREA_A
for y in range(40, 43):
    for x in range(4, 20):
        walls[y * 64 + x] = AREA_B
things[10 * 64 + 4] = PLAYER_START
things[9 * 64 + 24] = TYMOK
things[11 * 64 + 24] = SOLRAC
records[0] = replace(records[0], planes=MapPlanes(
    64, 64, (tuple(walls), tuple(things), tuple([0] * 4096))))
(lab / 'MAPTEMP.CO7').write_bytes(encode_archive(records))
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')


def run(label, place, extra=()):
    (work / (label + '.cfg')).write_text('MouseEnabled = 0;\n')
    actors = work / (label + '.actors')
    args = [str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
            '--res', '320', '200', '--vid-renderer', 'software', '--tedlevel', 'MAP01',
            '--skill', '4', '--config', str(work / (label + '.cfg')),
            '--savedir', str(work / 'saves'), '--capture-rngseed', '1',
            '--capture-health', '100000', '--capture-sounds', '--capture-actors-player',
            '--capture-actors', str(actors), '--capture-maxtics', str(TICS),
            '--capture-hold-button', 'attack', '20', '10', '--capture-place', *place, *extra]
    log = work / (label + '.log')
    with log.open('w') as f:
        subprocess.run(args, cwd=lab, env=env, stdout=f, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    sounds = [(m.group(1), int(m.group(2))) for m in re.finditer(
        r'^Capture: sound (\S+) tic (\d+)', log.read_text(), re.M)]
    # tic class tilex tiley dir pathing attack health ...
    moves = {}
    for line in actors.read_text().splitlines()[1:]:
        f = line.split()
        moves.setdefault(f[1], set()).add((f[2], f[3]))
    return sounds, moves


failed = False
def check(ok, what, detail):
    global failed
    print('  %s %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok:
        failed = True
        print('         %s' % (detail,))


print('Control: the player stays in the bosses\' area')
sounds, moves = run('control', ('1', '4.5', '10.5', '0'))
for boss, voice in VOICES.items():
    heard = [t for s, t in sounds if s == voice]
    check(len(moves.get('C7' + boss, ())) > 3, '%s gives chase' % boss,
          sorted(moves.get('C7' + boss, ())))
    check(len(heard) >= 3, '%s is heard (%d times)' % (boss, len(heard)), heard)

print('\nThe player is moved into a sealed area at tic %d' % MOVE_TIC)
# --capture-place only sets x and y; the pawn takes its new area when it next
# walks, so it takes a step.
sounds, moves = run('sealed', (str(MOVE_TIC), '6.5', '41.5', '0'),
                    ('--capture-forward', str(MOVE_TIC + 1), '4'))
for boss, voice in VOICES.items():
    before = [t for s, t in sounds if s == voice and t < MOVE_TIC]
    after = [t for s, t in sounds if s == voice and t > MOVE_TIC + 5]
    check(len(moves.get('C7' + boss, ())) > 3, '%s still gives chase' % boss,
          sorted(moves.get('C7' + boss, ())))
    check(not after, '%s is not heard from another area' % boss,
          'heard at tics %s (%d before the move)' % (after[:12], len(before)))

print('\n%s' % ('FAIL: see above.' if failed else
                'PASS: bosses are heard only from the player\'s area.'))
sys.exit(1 if failed else 0)
