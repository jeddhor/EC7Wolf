#!/bin/sh
# Open animated apertures retain a render tile, but must pass shots and aliens.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-aperture.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$repo" "$work" <<'PY'
from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys

build, data, repo, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(repo/'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes
from ec7edit_core.names import NativeName
source = read_archive(data/'MAPTEMP.CO7')
lab = work/'lab'
lab.mkdir()
for p in data.glob('*.CO7'):
    if p.name != 'MAPTEMP.CO7': shutil.copy2(p, lab/p.name)
shutil.copy2(data/'CORR7CD.EXE', lab/'CORR7CD.EXE')
shutil.copy2(build/'ec7wolf.pk3', lab/'ec7wolf.pk3')
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')

def run(wall, direction, mode):
    # Distance along a straight corridor, rotated through all four headings.
    def pos(x):
        return ((x,32), (32,63-x), (63-x,32), (32,x))[direction]
    walls, things, meta = [1]*4096, [18]*4096, [0]*4096
    for x in range(1,63):
        xx, yy = pos(x); walls[yy*64+xx] = 256
    dx, dy = pos(7); px, py = pos(6); ex, ey = pos(10)
    walls[dy*64+dx] = wall
    things[dy*64+dx] = 106
    things[py*64+px] = (20,19,22,21)[direction]
    things[ey*64+ex] = (118,119,116,117)[direction]
    records = list(source.records)
    records[0] = replace(records[0], name=NativeName.from_text('Aperture Test'),
                         planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple(meta))))
    (lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
    tag = f'{wall}-{direction}-{mode}'
    trace = work/(tag+'.actors')
    args = [str(build/'ec7wolf'), '--data','CO7','--nowait','--no-upscale',
            '--vid-renderer','software','--res','320','200', '--tedlevel','MAP01',
            '--skill','2','--config',str(work/(tag+'.cfg')),
            '--savedir',str(work/'save'), '--capture-rngseed','1',
            '--capture-actors',str(trace),'--capture-maxtics','350']
    if mode != 'closed': args += ['--capture-use','20','6']
    if mode == 'shoot': args += ['--capture-fire','100']
    with (work/(tag+'.log')).open('w') as log:
        subprocess.run(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,
                       timeout=45,check=True)
    rows = [s.split() for s in trace.read_text().splitlines() if not s.startswith('#')]
    assert rows, (tag,'no monster was spawned')
    if mode == 'shoot':
        assert int(rows[-1][0]) < 340, (tag,'shots did not kill the visible probe')
    else:
        along = [int(row[2]) if direction == 0 else 63-int(row[3]) if direction == 1
                 else 63-int(row[2]) if direction == 2 else int(row[3]) for row in rows]
        if mode == 'walk':
            assert min(along) <= 7, (tag,'alien never crossed the aperture',min(along))
        else:
            assert min(along) >= 8 and int(rows[-1][7]) == 50, (tag,'closed wall leaked')
    print('PASS',tag,flush=True)

for direction in range(4):
    for mode in ('closed','shoot','walk'):
        run(73,direction,mode)
for wall in (53,81,229):
    run(wall,0,'shoot')
    run(wall,0,'walk')
PY
