"""HUD, visor and quicksave fixes (GitHub #41, #44, #45, #46).

Usage: test_corridor7_ui_fixes.py BUILD_DIR DATA_DIR WORK_DIR

Run under an Xvfb display of its own (the .sh wrapper provides one). Every
check polls for what it needs to see rather than sleeping a fixed time, so a
loaded machine costs seconds, not a failure.

  #41  Dying with the night-vision visor on must not carry its green DAC into
       the death page: once the screen has faded to black after the death, the
       first picture shown is not green.
  #44  The access card icons in the status bar colour-cycle (their artwork uses
       the rotating ramps 208-239), so the icon area changes from frame to frame.
  #46  With Red Access Card Icon on, the red card's icon cycles red: no pixel of
       it is in the blue ramp any more.
  #52  On the GL renderer with the full-screen view, the full automap's status
       bar is opaque: nothing of the 3D world shows through its SCORE box.
  #45  F8 writes the dedicated Quicksave slot (quicksav.ecs) without asking,
       and a second F8 rewrites it. With Confirm Quick Save on, a second F8
       asks first, so the file is left alone while the question is open.
"""
from pathlib import Path
import os, shutil, subprocess, sys, time

from PIL import Image

build, data, work = map(Path, sys.argv[1:])
work.mkdir(parents=True, exist_ok=True)
lab = work / 'lab'
lab.mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE']:
    shutil.copyfile(p, lab / p.name)
shutil.copyfile(build / 'ec7wolf.pk3', lab / 'ec7wolf.pk3')
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')

failed = False
def check(ok, what, detail=''):
    global failed
    print(('PASS ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        print('  ', detail, flush=True)
        failed = True


class Game:
    def __init__(self, label, config='', extra=(), renderer='software'):
        self.dir = work / label
        self.dir.mkdir()
        (self.dir / 'saves').mkdir()
        cfg = self.dir / 'c.cfg'
        cfg.write_text('MouseEnabled = 0;\n' + config)
        self.log = self.dir / 'log.txt'
        self.proc = subprocess.Popen(
            # Line-buffered, so the log can be watched while the game runs.
            ['stdbuf', '-oL', '-eL', str(build / 'ec7wolf'), '--data', 'CO7', '--nowait', '--no-upscale',
             '--res', '640', '400', '--vid-renderer', renderer, '--tedlevel', 'MAP01',
             '--skill', '3', '--config', str(cfg), '--savedir', str(self.dir / 'saves'),
             *extra],
            cwd=lab, env=env, stdout=self.log.open('w'), stderr=subprocess.STDOUT)
        self.shots = 0

    def wait_for_log(self, text, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if text in self.log.read_text(errors='replace'):
                return True
            time.sleep(0.2)
        return False

    def shot(self):
        path = self.dir / ('s%03d.png' % self.shots)
        self.shots += 1
        subprocess.run(['import', '-window', 'root', str(path)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            return Image.open(path).convert('RGB')
        except Exception:
            return None

    def key(self, name):
        subprocess.run(['xdotool', 'key', name], check=False)

    def close(self):
        self.proc.kill()
        self.proc.wait()


def mean(im):
    small = im.resize((80, 50))
    px = list(small.getdata())
    n = len(px)
    return tuple(sum(p[c] for p in px) / n for c in range(3))


def is_green(rgb):
    r, g, b = rgb
    return g > 20 and g > 2 * r and g > 2 * b


# --- #41: the death page is not seen through the visor -----------------------
game = Game('visor', extra=('--capture-hold-button', 'zoom', '30', '1',
                            '--capture-kill-slot', '0', '150'))
seen_green = seen_black = False
page = None
end = time.time() + 90
if game.wait_for_log('MAP01 - '):
    while time.time() < end and page is None:
        im = game.shot()
        if im is None:
            continue
        m = mean(im)
        # The fade to black between the death and the page passes through
        # dim frames, which are neither green enough nor bright enough to
        # judge. A shot taken during it says nothing.
        if max(m) < 25:
            if seen_green:
                seen_black = True
        elif is_green(m):
            if seen_black:
                page = m
            seen_green = True
        elif seen_green:
            # The fade can fall between two shots on a loaded machine, so the
            # first bright picture after the green ones is the page whether or
            # not the dark was caught.
            page = m
        time.sleep(0.3)
game.close()
check(seen_green, 'night vision turned the view green before the death', seen_green)
check(page is not None and not is_green(page),
      'the death page after a visor death is not green', page)

# --- #44 and #46: the card icons cycle; the red one red on request ------------
CARD_BOX = (512, 352, 544, 384)        # the two 8x16 icons at (256,176), doubled
RED_ICON = (512, 352, 528, 384)        # the red card's, in the first slot


def card_frames(label, config):
    game = Game(label, config, ('--capture-give', 'C7Static001',
                                '--capture-give', 'C7Static002'))
    frames = []
    if game.wait_for_log('MAP01 - '):
        # Past the level's fade-in, so only the icons themselves can change.
        time.sleep(5)
        end = time.time() + 30
        while time.time() < end and len(frames) < 24:
            im = game.shot()
            if im is not None:
                frames.append(im)
            time.sleep(0.15)
    game.close()
    return frames


def blue_ramp_pixels(im, box):
    # The blue ramp is pure blue, (0, 0, n); the artwork's own navy is not.
    return sum(1 for r, g, b in im.crop(box).getdata() if b > 20 and r < 4 and g < 4)


frames = card_frames('cards', '')
distinct = {f.crop(CARD_BOX).tobytes() for f in frames}
check(len(distinct) >= 2, 'the access card icons colour-cycle in the status bar',
      '%d frames, %d distinct' % (len(frames), len(distinct)))
check(any(blue_ramp_pixels(f, RED_ICON) for f in frames),
      'by default the red card icon cycles blue, as in DOS',
      [blue_ramp_pixels(f, RED_ICON) for f in frames])

frames = card_frames('red-card', 'C7RedCardIcon = 1;\n')
check(frames and not any(blue_ramp_pixels(f, RED_ICON) for f in frames),
      'with Red Access Card Icon on, the red card icon has no blue ramp left',
      [blue_ramp_pixels(f, RED_ICON) for f in frames])

# --- #52: the automap's status bar is opaque on GL ----------------------------
SCORE_BOX = (60, 352, 172, 384)        # the SCORE digits, virtual (30,176)-(86,192)
game = Game('automap', 'ViewSize = 21;\n', ('--capture-hold-button', 'automap', '100', '1'),
            renderer='opengl')
foreign = None
if game.wait_for_log('Capture: ui action automap'):
    time.sleep(2)
    im = game.shot()
    if im is not None:
        foreign = sum(1 for r, g, b in im.crop(SCORE_BOX).getdata()
                      if r + g + b > 60 and not (g > r + 20 and g > b + 20))
game.close()
check(foreign == 0, 'the GL automap shows no 3D world through the SCORE box', foreign)

# --- #45: F8 quicksaves to its own slot without asking ------------------------
def stamp(path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def press_until(game, key, path, before, timeout=20):
    """Press KEY until PATH's stamp moves off BEFORE, re-sending a dropped key."""
    end = time.time() + timeout
    while time.time() < end:
        game.key(key)
        for _ in range(20):
            time.sleep(0.25)
            now = stamp(path)
            if now != before:
                return now
    return stamp(path)


for confirm in (0, 1):
    game = Game('quicksave-%d' % confirm, 'C7ConfirmQuickSave = %d;\n' % confirm)
    quick = game.dir / 'saves' / 'quicksav.ecs'
    first = second = None
    if game.wait_for_log('MAP01 - '):
        time.sleep(2)
        first = press_until(game, 'F8', quick, None)
        time.sleep(1.5)   # a different second, so the rewrite has a new stamp
        if confirm:
            game.key('F8')
            time.sleep(4)
            second = stamp(quick)
        else:
            second = press_until(game, 'F8', quick, first)
    game.close()
    if confirm:
        check(first is not None and second == first,
              'with Confirm Quick Save on, a second F8 waits for an answer', (first, second))
    else:
        check(first is not None, 'F8 writes quicksav.ecs without asking', first)
        check(first is not None and second not in (None, first),
              'and a second F8 rewrites it without asking', (first, second))

sys.exit(1 if failed else 0)
