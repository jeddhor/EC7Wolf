"""The health maximum and alien energy follow CORR7CD.EXE (GitHub #32, #34).

Usage: test_corridor7_health_energy.py BUILD_DIR DATA_DIR WORK_DIR

A one-corridor lab floor with pickups in the player's path, walked through the
ordinary pickup code, with the verbs trace reporting health, its maximum,
alien charge (energy) and its capacity (ecap) whenever one of them moves.

  #32  The Adrenaline Boost raises the maximum by 300 and heals 300 up to it
       (13fd9): 100/100 -> 400/400, a second -> 700/700. The next floor puts
       the maximum back to 100 and health with it (216ba).
  #34  An alien weapon resets capacity to 100 and gives no charge (13ec1);
       a duplicate is still picked up, and restores capacity spent by firing.
       A charge pack adds 100 capacity (140f6), and charge regenerates up to
       it. Charge starts building at the M-343, before any alien weapon.
"""
from dataclasses import replace
from pathlib import Path
import os, re, shutil, subprocess, sys, zipfile

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes

M343, DUAL_BLASTER, ADRENALINE, CHARGE_PACK = 29, 51, 80, 81
PLAYER_START, EMPTY, FLOOR = 22, 18, 256

lab = work / 'lab'; lab.mkdir(parents=True); (work / 'saves').mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE']:
    shutil.copyfile(p, lab / p.name)
source = list(read_archive(data / 'MAPTEMP.CO7').records)
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')


def fixture(pickups):
    """MAP01 and MAP02 become the same corridor; pickups go on MAP01 only."""
    records = source.copy()
    for level in (0, 1):
        walls, things = [1] * 4096, [EMPTY] * 4096
        for y in range(9, 12):
            for x in range(4, 40):
                walls[y * 64 + x] = FLOOR
        things[10 * 64 + 4] = PLAYER_START   # turned east by --capture-place
        if level == 0:
            for x, thing in pickups.items():
                things[10 * 64 + x] = thing
        records[level] = replace(records[level], planes=MapPlanes(
            64, 64, (tuple(walls), tuple(things), tuple([0] * 4096))))
    (lab / 'MAPTEMP.CO7').write_bytes(encode_archive(records))
    with zipfile.ZipFile(build / 'ec7wolf.pk3') as src, \
            zipfile.ZipFile(lab / 'ec7wolf.pk3', 'w') as dst:
        for info in src.infolist():
            b = src.read(info)
            if info.filename == 'mapinfo/corridor7.txt':
                b = re.sub(rb'(map "MAP01"[^\n]*\n\{)', rb'\1\n nointermission', b)
            dst.writestr(info, b)


def run(label, extra, tics):
    log = work / (label + '.log')
    # No mouse: under Xvfb the pointer can be warped as the window grabs it,
    # and that arrives as movement, which walks the player off the line.
    (work / (label + '.cfg')).write_text('MouseEnabled = 0;\n')
    args = [str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
            '--res', '320', '200', '--vid-renderer', 'software', '--tedlevel', 'MAP01',
            '--skill', '3', '--config', str(work / (label + '.cfg')),
            '--savedir', str(work / 'saves'), '--capture-rngseed', '1',
            '--capture-verbs', '--capture-maxtics', str(tics),
            '--capture-place', '1', '4.5', '10.5', '0', *extra]
    with log.open('w') as f:
        subprocess.run(args, cwd=lab, env=env, stdout=f, stderr=subprocess.STDOUT,
                       check=True, timeout=60)
    text = log.read_text()
    rows = [dict((k, int(v)) for k, v in re.findall(r'(\w+)=(-?\d+)', l))
            for l in text.splitlines() if l.startswith('verbs tic=')]
    assert rows, (label, text[-1500:])
    return text, rows


def show(rows, *keys):
    return [tuple(r[k] for k in ('tic',) + keys) for r in rows]


failed = False
def check(ok, what, detail):
    global failed
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        print('  ', detail, flush=True)
        failed = True


# --- #32: two boosts, then the next floor -------------------------------------
fixture({6: ADRENALINE, 8: ADRENALINE})
text, rows = run('adrenaline', ('--capture-forward', '5', '60',
                                '--capture-exitlevel', '120'), 200)
pairs = [(r['health'], r['maxhealth']) for r in rows]
check((400, 400) in pairs and (700, 700) in pairs,
      'each Adrenaline raises the maximum by 300 and heals up to it',
      show(rows, 'health', 'maxhealth'))
check('MAP02 - ' in text and pairs[-1] == (100, 100),
      'the next floor puts the maximum and health back to 100',
      show(rows, 'health', 'maxhealth'))

# --- #34: charge from the M-343; a dual blaster and a charge pack bring none ---
fixture({6: M343, 8: DUAL_BLASTER, 10: CHARGE_PACK})
_, rows = run('energy', ('--capture-forward', '5', '45'), 300)
first = next((r for r in rows if r['energy'] >= 0), None)
check(first is not None and first['energy'] <= 2,
      'charge starts from nothing once the M-343 is owned', first)
jumps = [(a['tic'], a['energy'], b['energy']) for a, b in zip(rows, rows[1:])
         if b['energy'] - a['energy'] > 2]
check(not jumps, 'no pickup adds charge; it only ever regenerates by two', jumps)
check(rows[-1]['ecap'] == 200, 'a charge pack adds 100 capacity', show(rows, 'x', 'ecap')[-3:])
check(rows[-1]['energy'] > 100, 'charge regenerates past 100 into the added capacity',
      show(rows, 'energy', 'ecap')[-3:])

# --- #34: a duplicate blaster restores the capacity firing spent ---------------
fixture({8: DUAL_BLASTER})
_, rows = run('duplicate', ('--capture-give', 'C7DualBlaster',
                            '--capture-hold-button', 'attack', '20', '60',
                            '--capture-forward', '120', '40'), 240)
before = [r for r in rows if r['tic'] < 120]
after = [r for r in rows if r['tic'] >= 120]
check(before and min(r['ecap'] for r in before) < 100,
      'firing the dual blaster spends capacity', show(before, 'energy', 'ecap')[-3:])
check(after and after[-1]['ecap'] == 100,
      'walking onto a second dual blaster puts capacity back to 100',
      show(after, 'x', 'ecap')[-3:])
check(all(b['energy'] - a['energy'] <= 2 for a, b in zip(rows, rows[1:])),
      'and gives no charge', show(rows, 'energy')[-6:])

sys.exit(1 if failed else 0)
