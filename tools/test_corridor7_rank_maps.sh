#!/bin/sh
# The two easy ranks receive a real floor-plan token on every campaign floor.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
work=$(mktemp -d /tmp/ec7wolf-rankmaps.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$work" <<'PY'
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

build,data,work=map(Path,sys.argv[1:])
lab=work/'lab';lab.mkdir();(work/'save').mkdir()
for p in data.glob('*.CO7'):shutil.copy2(p,lab/p.name)
shutil.copy2(data/'CORR7CD.EXE',lab/'CORR7CD.EXE')
# Skip only the presentation pause, retaining the ordinary elevator/travel and
# inventory-stripping code. This makes transition assertions unattended.
with zipfile.ZipFile(build/'ec7wolf.pk3') as src,zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
    for info in src.infolist():
        b=src.read(info.filename)
        if info.filename=='mapinfo/corridor7.txt':
            b=re.sub(rb'(map "MAP(?:01|41)"[^\n]*\n\{)',rb'\1\n\tnointermission',b)
        dst.writestr(info,b)
env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11')

def run(skill,level,label,extra=()):
    path=work/(label+'.log')
    args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale',
          '--vid-renderer','software','--res','320','200','--tedlevel',level,
          '--skill',str(skill),'--config',str(work/(label+'.cfg')),
          '--savedir',str(work/'save'),'--capture-rngseed','1','--capture-verbs',
          '--capture-maxtics','160',*extra]
    with path.open('w') as log:
        subprocess.run(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=45,check=True)
    text=path.read_text()
    rows=[dict((k,int(v)) for k,v in re.findall(r'(\w+)=(-?\d+)',s))
          for s in text.splitlines() if s.startswith('verbs tic=')]
    assert rows,(label,'no observations')
    return text,rows

for skill in range(1,6):
    want=int(skill<=2)
    for level in ('MAP01','MAP02','MAP41'):
        _,rows=run(skill,level,f'{skill}-{level}',
                   ('--capture-save','10','rank.ec7','--capture-load','40','rank.ec7'))
        assert all(r['plan']==want and r['fullmap']==want for r in rows),(skill,level,rows)
    # A collected map is stripped on travel; the rank rule then grants the
    # destination's own plan only for Corporal and Lieutenant.
    text,rows=run(skill,'MAP01',f'{skill}-travel',
                  ('--capture-give','C7FloorPlan','--capture-exitlevel','30'))
    assert 'MAP02 - ' in text,(skill,'no real level transition')
    assert rows[0]['plan']==1 and rows[-1]['plan']==want,(skill,'travel entitlement',rows)
    print(f'PASS rank {skill}: three fresh floors, save/load, and per-floor travel rule',flush=True)
PY
