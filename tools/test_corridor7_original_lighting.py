"""Corridor 7's own shading, Lighting = Original (GitHub #57).

Usage: test_corridor7_original_lighting.py BUILD_DIR DATA_DIR WORK_DIR

Run under an Xvfb display of its own (the .sh wrapper provides one). Each run
renders one frame in software and, offscreen, the same frame on GL
(--capture-glframe), so both renderers are held to the same answers.

  Planes   On MAP01 the floor and ceiling are the original's screen-space
           pattern (CORR7CD.EXE 1cb7:0a17 with the four bytes of 18b8:1177):
           every pixel of the ceiling's top 40 rows and of the floor's bottom
           30 beside the weapon is the color the original writes there.
  #57      A lab holding floor 26's walls, at the reporter's (57,5): the count
           of texels brighter than red 60 in the view, which the original keeps
           low by shading walls in whole palette steps to black. DOSBox-X
           captures of the original give 1852 under infrared and 12464 in the
           normal view; Original lighting must stay near those, and the port's
           Enhanced lighting -- 10649 and 31096, the "sheen" #57 reported -- is
           run too, so the measure is known to tell them apart.
  Geometry The view is the original's 160 lines (320 here): its last row is
           drawn, not left black above the status bar.
"""
from pathlib import Path
import os, shutil, subprocess, sys

from PIL import Image

build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from dataclasses import replace
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.assets import load_palette, palette_rgb
from ec7edit_core.planes import MapPlanes

work.mkdir(parents=True, exist_ok=True)
palette = load_palette((data / 'CORR7CD.EXE').read_bytes())
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')

failed = False
def check(ok, what, detail=''):
    global failed
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        print('   ', detail, flush=True)
        failed = True


def make_lab(name, maptemp=None):
    lab = work / name
    lab.mkdir()
    for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE', build / 'ec7wolf.pk3']:
        shutil.copyfile(p, lab / p.name)
    if maptemp is not None:
        (lab / 'MAPTEMP.CO7').write_bytes(maptemp)
    return lab


def render(lab, label, lighting, extra=()):
    """One frame, software and GL, at 640x400. Returns (software, gl) images."""
    out = work / label
    out.mkdir()
    cfg = out / 'c.cfg'
    cfg.write_text('MouseEnabled = 0;\nC7Lighting = %d;\n' % lighting)
    sw, gl = out / 'software.png', out / 'gl.png'
    with (out / 'log.txt').open('w') as log:
        subprocess.run([str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
                        '--res', '640', '400', '--vid-renderer', 'software',
                        '--tedlevel', 'MAP01', '--skill', '3', '--config', str(cfg),
                        '--savedir', str(out), '--capture-rngseed', '1', *extra,
                        '--capture-frame', '450', '--capture-file', str(sw),
                        '--capture-glframe', str(gl), '--capture-maxframes', '480'],
                       cwd=lab, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    try:
        return Image.open(sw).convert('RGB'), Image.open(gl).convert('RGB')
    except Exception as e:
        return None, None


# --- the original's planes -------------------------------------------------
def plane_rows(c0, cmin, f0, fmax):
    """(even-group, odd-group) palette index per original row, top to bottom."""
    rows = []
    hi, lo, run = c0, c0 - 1, 0
    for _ in range(80):
        rows.append((lo, hi))
        run += 1
        hi, lo = lo, hi
        if cmin < hi and run > 2:
            run, hi, lo = 0, hi - 1, lo - 1
    hi, lo, run, counted = f0, f0 + 1, 0, 0
    for _ in range(80):
        rows.append((lo, hi))
        run += 1
        hi, lo = lo, hi
        if run > 2:
            counted += 1
            if counted > 45 and hi < fmax:
                run, hi, lo = 0, hi + 1, lo + 1
    return rows


def plane_mismatches(im, rows):
    bad = []
    def want(x, y):
        pair = rows[y // 2]
        return palette_rgb(palette, pair[(x // 8) & 1])
    for y in range(0, 80):                  # the ceiling's top 40 original rows
        for x in range(640):
            if im.getpixel((x, y)) != want(x, y):
                bad.append((x, y))
    for y in range(260, 320):               # the floor's bottom 30, beside the weapon
        for x in list(range(0, 220)) + list(range(420, 640)):
            if im.getpixel((x, y)) != want(x, y):
                bad.append((x, y))
    return bad


rows = plane_rows(38, 18, 184, 200)         # every floor but MAP20..MAP29
lab = make_lab('map01')
sw, gl = render(lab, 'map01-original', 1)
for name, im in (('software', sw), ('GL', gl)):
    bad = plane_mismatches(im, rows) if im else None
    check(bad == [], 'MAP01 floor and ceiling are the original\'s pattern (%s)' % name,
          'no frame' if bad is None else '%d pixels differ, first %s' % (len(bad), bad[:5]))
    row = [im.getpixel((x, 318)) for x in range(0, 200, 8)] if im else []
    check(im is not None and all(p != (0, 0, 0) for p in row),
          'the view\'s last row is drawn (%s)' % name, row[:6])

# --- #57: floor 26's walls at the reporter's position ------------------------
records = list(read_archive(data / 'MAPTEMP.CO7').records)
floor26 = records[25].planes
walls, things, plane2 = (list(p) for p in floor26.planes)
things = [v if 98 <= v <= 107 else 18 for v in things]  # wall markers only
things[5 * 64 + 57] = 22                                  # the player, (57,5)
records[0] = replace(records[0], planes=MapPlanes(
    floor26.width, floor26.height, (tuple(walls), tuple(things), tuple(plane2))))
lab26 = make_lab('floor26', encode_archive(records))


def bright(im):
    """Texels redder than 60 in the view, the weapon left out."""
    n = 0
    data_ = im.tobytes()
    for y in range(60, 300):
        for x in range(640):
            if 230 <= x <= 410 and y >= 170:
                continue
            if data_[(y * 640 + x) * 3] > 60:
                n += 1
    return n


DOS = {'infrared': 1852, 'normal': 12464}
for view, extra in (('infrared', ('--capture-visormode', '2')), ('normal', ())):
    sw, gl = render(lab26, '%s-original' % view, 1, extra)
    esw, _ = render(lab26, '%s-enhanced' % view, 0, extra)
    if not (sw and gl and esw):
        check(False, 'floor 26 frames rendered (%s)' % view, 'see %s' % work)
        continue
    counts = bright(sw), bright(gl), bright(esw)
    target = DOS[view]
    check(all(abs(c - target) <= target * 0.15 for c in counts[:2]),
          'floor 26 walls are shaded as the original shades them (%s)' % view,
          'software %d, GL %d, original %d' % (counts[0], counts[1], target))
    check(counts[2] > target * 2,
          'and Enhanced lighting is measurably not (%s)' % view,
          'enhanced %d, original %d' % (counts[2], target))

sys.exit(1 if failed else 0)
