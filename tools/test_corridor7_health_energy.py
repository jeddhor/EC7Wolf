"""Health, armor, alien energy and mines follow CORR7CD.EXE (GitHub #32, #34,
#38, #39, #40, #42, #55, #56).

Usage: test_corridor7_health_energy.py BUILD_DIR DATA_DIR WORK_DIR

A one-corridor lab floor with pickups in the player's path, walked through the
ordinary pickup code, with the verbs trace reporting health, its maximum,
alien charge (energy) and its capacity (ecap) whenever one of them moves.

  #32  The Adrenaline Boost raises the maximum by 300 and heals 300 up to it
       (13fd9): 100/100 -> 400/400, a second -> 700/700. The next floor puts
       the maximum back to 100 and health with it (216ba).
  #38  Body armor adds 200 and stops at 999 (13f7c), and a suit is taken
       even at 999.
  #34  An alien weapon resets capacity to 100 and gives no charge (13ec1);
       a duplicate is still picked up, and restores capacity spent by firing.
       A charge pack adds 100 capacity (140f6), and charge regenerates up to
       it. Charge starts building at the M-343, before any alien weapon.
  #39  Each charge pack is used up: ten in a row raise capacity 100 at a time
       to 999, and only the tenth, refused at 999, is left lying. The second
       pack used to run every tic without being taken, straight to 999.
  #40  With the optional Alien Weapon Capacity rule set to keep, an alien
       weapon leaves a capacity above 100 alone; by default it goes back to
       100, as in DOS.
  #42  A dropped mine lands under the player (2f28:1a28 copies the dropper's
       x and y), not 40/64 of a tile ahead -- facing a wall, that was inside it.
  #53  A health chamber with no aperture door still heals: DOS registers
       every wall-35 panel as a chamber (9a35) and closes a door only if there
       is one (2284e). Floor 16's corridor panels have none.
  #51  Floor 17's secret pushwall (13,2) stops after one tile against a lone
       block at (13,4) and plugs the way on; the optional Original Map Errors
       rule makes that block floor, so the wall slides two tiles and the
       player can step into (13,3). Played on the shipped floor 17.
  #55  A new floor sets capacity back to 100 but leaves the charge alone
       (216b4): charge above 100 survives the elevator.
  #56  A mine blast (23720) rolls 100..610 three times, a frame apart, and an
       alien that set it off takes each roll in full on top of its share.
  #49  Only a projectile sets a mine off from a distance: DOS tests every object
       against the mines (0xbfc2), and a plasma bolt is one while a hitscan
       shot is not. The M-16 leaves a mine alone; the Plasma Rifle does not.
"""
from dataclasses import replace
from pathlib import Path
import os, re, shutil, subprocess, sys, zipfile

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes

M343, DUAL_BLASTER, ADRENALINE, CHARGE_PACK, BODY_ARMOR = 29, 51, 80, 81, 82
PLAYER_START, EMPTY, FLOOR = 22, 18, 256

lab = work / 'lab'; lab.mkdir(parents=True); (work / 'saves').mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE']:
    shutil.copyfile(p, lab / p.name)
source = list(read_archive(data / 'MAPTEMP.CO7').records)
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')


def fixture(pickups, walls_at=None):
    """MAP01 and MAP02 become the same corridor; pickups go on MAP01 only.
    WALLS_AT maps (x, y) to a wall number on MAP01."""
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
            for (x, y), wall in (walls_at or {}).items():
                walls[y * 64 + x] = wall
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


def run(label, extra, tics, config='', place=('4.5', '10.5'), level='MAP01', angle='0',
        skill='3'):
    log = work / (label + '.log')
    # No mouse: under Xvfb the pointer can be warped as the window grabs it,
    # and that arrives as movement, which walks the player off the line.
    (work / (label + '.cfg')).write_text('MouseEnabled = 0;\n' + config)
    args = [str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
            '--res', '320', '200', '--vid-renderer', 'software', '--tedlevel', level,
            '--skill', skill, '--config', str(work / (label + '.cfg')),
            '--savedir', str(work / 'saves'), '--capture-rngseed', '1',
            '--capture-verbs', '--capture-maxtics', str(tics),
            '--capture-place', '1', *place, angle, *extra]
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

# --- #38: six suits of armor stop at 999, and every one is taken -------------
fixture({x: BODY_ARMOR for x in range(6, 12)})
_, rows = run('armor', ('--capture-forward', '5', '50'), 120)
levels = sorted({r['armor'] for r in rows})
check(levels == [0, 200, 400, 600, 800, 999],
      'body armor adds 200 a suit and stops at 999', levels)
check(rows[-1]['armor'] == 999 and rows[-1]['pickups'] - rows[0]['pickups'] == 6,
      'the sixth suit is taken at 999 without raising it',
      show(rows, 'x', 'armor', 'pickups')[-4:])

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

# --- #39: every charge pack is taken, 100 at a time, until 999 ----------------
fixture({x: CHARGE_PACK for x in range(6, 16)})
_, rows = run('packs', ('--capture-forward', '5', '60'), 140)
levels = sorted({r['ecap'] for r in rows})
check(levels == [100, 200, 300, 400, 500, 600, 700, 800, 900, 999],
      'each charge pack adds 100 capacity, stopping at 999', levels)
steps = [(a['tic'], a['ecap'], b['ecap']) for a, b in zip(rows, rows[1:])
         if b['ecap'] - a['ecap'] > 100]
check(not steps, 'no pack adds more than once', steps)
check(rows[-1]['pickups'] - rows[0]['pickups'] == 9,
      'nine packs are taken and the tenth, at 999, is left lying',
      show(rows, 'x', 'ecap', 'pickups')[-4:])

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

# --- #40: the optional rule keeps a capacity above 100 -------------------------
fixture({6: M343, 8: CHARGE_PACK, 10: CHARGE_PACK, 12: DUAL_BLASTER})
for keep in (0, 1):
    text, rows = run('capacity-%d' % keep, ('--capture-forward', '5', '50'), 140,
                     'C7AlienWeaponCapacity = %d;\n' % keep)
    peak = max(r['ecap'] for r in rows)
    rule = 'keep' if keep else 'classic'
    check('Corridor 7 alien weapon capacity rule: ' + rule in text and peak == 300 and
          rows[-1]['ecap'] == (300 if keep else 100),
          ('with the keep rule an alien weapon leaves 300 capacity alone' if keep else
           'by default an alien weapon puts 300 capacity back to 100, as in DOS'),
          show(rows, 'x', 'ecap')[-4:])

# --- #55: charge above 100 survives the next floor ----------------------------
fixture({6: M343, 8: CHARGE_PACK, 10: CHARGE_PACK})
text, rows = run('floor-charge', ('--capture-forward', '5', '45', '--capture-exitlevel', '330'), 400)
before = [r for r in rows if r['tic'] < 330]
after = [r for r in rows if r['tic'] >= 330]
check(before and before[-1]['energy'] > 200 and 'MAP02 - ' in text and after and
      after[-1]['ecap'] == 100 and after[-1]['energy'] >= before[-1]['energy'] - 2,
      'the next floor puts capacity back to 100 and keeps the charge above it, as in DOS',
      (show(before, 'energy', 'ecap')[-1:], show(after, 'energy', 'ecap')[-2:]))

# --- #42: a mine lands under the player, even facing a wall --------------------
fixture({})
_, rows = run('mine', ('--capture-give', 'C7Mines', '--capture-hold-button', 'reload', '10', '1'),
              40, place=('39.5', '10.5'))
laid = [(r['minex'], r['miney']) for r in rows if r['minex'] >= 0]
check(laid and laid[-1] == (39, 10),
      'a mine dropped facing the end wall lands under the player, not in the wall', laid)

# --- #49: hitscan passes a mine by; a plasma bolt sets it off -----------------
fixture({})
for weapon in ('C7M16', 'C7PlasmaRifle'):
    extra = ('--capture-mine-at', '10', '10', '1',
             '--capture-hold-button', 'attack', '80', '60')
    if weapon != 'C7M16':
        extra = ('--capture-give', weapon, '--capture-select', weapon) + extra
    text, rows = run('shoot-' + weapon, extra, 400)
    there = [r['minex'] for r in rows if r['tic'] >= 60]
    if weapon == 'C7M16':
        check('mine placed at 10,10' in text and there and there[-1] == 10,
              'an M-16 burst down the corridor leaves the mine lying', show(rows, 'ammo', 'minex')[-3:])
    else:
        check('mine placed at 10,10' in text and there and there[-1] == -1,
              'a plasma bolt sets the mine off', show(rows, 'energy', 'minex')[-3:])

# --- #56: an alien walking onto a mine ----------------------------------------
SOLRAC = 214
fixture({14: SOLRAC})
actors = work / 'mine-blast.actors'
# The mine goes under the Solrac, which wakes to the shots and stands its
# ground; the mine arms as soon as its owner is far enough off.
text, rows = run('mine-blast', ('--capture-health', '100000', '--capture-mine-at', '14', '10', '1',
                                '--capture-hold-button', 'attack', '20', '4',
                                '--capture-actors', str(actors)), 400, skill='4')
health = []
for line in actors.read_text().splitlines()[1:]:
    f = line.split()
    if f[1] == 'C7Solrac' and (not health or health[-1][1] != int(f[7])):
        health.append((int(f[0]), int(f[7])))
# The M-16 burst that wakes it lands well before the mine can arm (tic 73).
drops = [(b[0], a[1] - b[1]) for a, b in zip(health, health[1:]) if b[1] < a[1] and b[0] > 73]
# Two tics apart: +0, +2 and +4.
blast = [d for d in drops if drops and d[0] - drops[0][0] <= 4]
check(len(blast) == 3 and sum(d for _, d in blast) >= 450,
      'a mine an alien walks onto hits it three times, a frame apart, for at least 450',
      health[:8])

# --- #53: a doorless health chamber heals -------------------------------------
fixture({}, {(40, 10): 35})
_, rows = run('chamber', ('--capture-health', '50', '--capture-use', '20', '2'), 160,
              place=('39.5', '10.5'))
check(rows[0]['health'] == 50 and rows[-1]['health'] == 100,
      'a health chamber with no door heals the player', show(rows, 'health', 'angle')[-3:])

# --- #51: floor 17's secret, classic and fixed ---------------------------------
for fix in (0, 1):
    text, rows = run('floor17-%d' % fix, ('--capture-use', '10', '2', '--capture-forward', '150', '200'),
                     400, 'C7MapFixes = %d;\n' % fix, place=('13.5', '1.5'), level='MAP17', angle='270')
    tile_y = rows[-1]['y'] // 64
    if fix:
        check('original map errors rule: fixed' in text and tile_y == 3,
              'with the map fix the floor 17 pushwall slides clear and the player reaches (13,3)',
              show(rows, 'x', 'y')[-2:])
    else:
        check('original map errors rule: classic' in text and tile_y == 2,
              'by default the floor 17 pushwall stops a tile short, as in DOS', show(rows, 'x', 'y')[-2:])

sys.exit(1 if failed else 0)
