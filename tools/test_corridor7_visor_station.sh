#!/bin/sh
# Retail MAP02's fan is a one-use +100 battery; numbered panels are scenery.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-visor-station.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$repo" "$work" <<'PY'
from dataclasses import replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

build, data, repo, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(repo/'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes
lab = work/'lab'; lab.mkdir()
(work/'save').mkdir()
for p in data.glob('*.CO7'): shutil.copy2(p,lab/p.name)
shutil.copy2(data/'CORR7CD.EXE',lab/'CORR7CD.EXE')
shutil.copy2(build/'ec7wolf.pk3',lab/'ec7wolf.pk3')
source = read_archive(data/'MAPTEMP.CO7')
env = dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11')

def run(label, level, place, use, extra=()):
    logpath = work/(label+'.log')
    args = [str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale',
            '--vid-renderer','software','--res','320','200','--tedlevel',level,
            '--skill','3','--config',str(work/(label+'.cfg')),
            '--savedir',str(work/'save'),'--capture-rngseed','1',
            '--capture-place','10',*map(str,place),'--capture-verbs',
            '--capture-use',str(use),'6','--capture-use',str(use+70),'6',
            '--capture-maxtics',str(use+100),*extra]
    with logpath.open('w') as log:
        subprocess.run(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,
                       timeout=45,check=True)
    rows = [dict((k,int(v)) for k,v in re.findall(r'(\w+)=(-?\d+)',s))
            for s in logpath.read_text().splitlines() if s.startswith('verbs tic=')]
    assert rows, (label,'no observations')
    return rows

for label, use, extra in [('full',20,()),('partly-drained',180,('--capture-visormode','1'))]:
    rows = run(label,'MAP02',(57.5,55.5,90),use,extra)
    jumps = [b['charge']-a['charge'] for a,b in zip(rows,rows[1:])
             if b['charge']>a['charge']]
    assert jumps == [100], (label,'station must add exactly one battery',jumps)
    assert any(r['charge']>100 for r in rows), (label,'original permits overcharge')
    print('PASS retail MAP02',label,'adds 100 exactly once',flush=True)

rows=run('spent-roundtrip','MAP02',(57.5,55.5,90),20,
         ('--capture-save','40','spent.ec7','--capture-load','70','spent.ec7'))
assert max(r['charge'] for r in rows)==200, 'loading revived a spent battery'
assert (work/'save'/'spent.ec7').is_file(), 'no save was written'
print('PASS spent station survives a real save/load',flush=True)

# Author a save with beta273's actual trigger mapping, then load it with the
# corrected map translator. Everything else, including serialization, is real.
with zipfile.ZipFile(build/'ec7wolf.pk3') as src, zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
    for info in src.infolist():
        content=src.read(info.filename)
        if info.filename=='xlat/corridor7.txt':
            content,count=re.subn(rb'trigger\s+93\s*\{',b'trigger 110\n\t{',content,count=1)
            assert count==1
        dst.writestr(info,content)
run('legacy-mapping','MAP02',(57.5,55.5,90),20,
    ('--capture-save','12','legacy.ec7'))
shutil.copy2(build/'ec7wolf.pk3',lab/'ec7wolf.pk3')
rows=run('legacy-upgraded','MAP02',(57.5,55.5,90),20,
         ('--capture-load','12','legacy.ec7'))
assert max(r['charge'] for r in rows)==200, 'old save lost the corrected trigger'
print('PASS old-save trigger mapping is repaired on load',flush=True)

# A numbered panel reachable from the same use distance, without other devices.
walls, things = [1]*4096, [18]*4096
for x in range(1,63): walls[32*64+x]=256
walls[32*64+7]=110;things[32*64+6]=20
records=list(source.records)
records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
(lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
rows=run('numbered-panel','MAP01',(6.5,32.5,0),20)
assert all(r['charge']==100 for r in rows), 'wall 110 still dispenses batteries'
print('PASS wall 110 never charges the visor',flush=True)
PY
