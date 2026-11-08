#!/bin/sh
# Compare the running probe's moving frames with the original executable's
# state records, rather than asserting another copy of the port's state table.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-probe.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$repo" "$work" <<'PY'
from dataclasses import replace
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

build,data,repo,work=map(Path,sys.argv[1:])
sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.planes import MapPlanes
exe=(data/'CORR7CD.EXE').read_bytes()
header=struct.unpack_from('<H',exe,8)[0]*16
base=header+(0x39ac-0x1000)*16
def original(start):
    result=[];offset=start
    for _ in range(6):
        _,shape,tics,_,_,_,_,nxt,_=struct.unpack_from('<9H',exe,base+offset)
        result.append((chr(65+(shape-239)//8),tics));offset=nxt
    assert offset==start,'original state loop did not close'
    return set(result)
path_expected=original(0x12);chase_expected=original(0xea)
assert not any(frame=='A' for frame,_ in path_expected|chase_expected)

lab=work/'lab';lab.mkdir()
for p in data.glob('*.CO7'):
    if p.name!='MAPTEMP.CO7':shutil.copy2(p,lab/p.name)
shutil.copy2(data/'CORR7CD.EXE',lab/'CORR7CD.EXE')
shutil.copy2(build/'ec7wolf.pk3',lab/'ec7wolf.pk3')
records=list(read_archive(data/'MAPTEMP.CO7').records)
walls,things=[1]*4096,[18]*4096
for x in range(1,63):walls[30*64+x]=walls[32*64+x]=256
things[30*64+4]=20;things[30*64+16]=118;things[32*64+10]=120
records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
(lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
trace=work/'actors.txt'
args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale',
      '--vid-renderer','software','--res','320','200','--tedlevel','MAP01',
      '--skill','3','--config',str(work/'cfg'),'--savedir',str(work/'save'),
      '--capture-rngseed','1','--capture-actors',str(trace),'--capture-maxtics','350']
with (work/'engine.log').open('w') as log:
    subprocess.run(args,cwd=lab,env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11'),
                   stdout=log,stderr=subprocess.STDOUT,timeout=45,check=True)
path_seen=set();chase_seen=set()
for line in trace.read_text().splitlines():
    if line.startswith('#'):continue
    row=line.split()
    if row[8]!='PROB':continue
    frame=(row[9],int(row[10]))
    if row[5]=='1':
        assert frame in path_expected,('patrol',frame,path_expected)
        path_seen.add(frame)
    elif row[6]=='1':
        assert frame in chase_expected,('chase',frame,chase_expected)
        chase_seen.add(frame)
assert path_seen==path_expected,('incomplete patrol observation',path_seen,path_expected)
assert {f for f,_ in chase_seen}==set('BCDE'),('incomplete chase observation',chase_seen)
print('PASS patrol frames and durations match CORR7CD.EXE:',sorted(path_seen))
print('PASS chase frames and durations match CORR7CD.EXE:',sorted(chase_seen))
PY
