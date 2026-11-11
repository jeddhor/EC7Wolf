#!/bin/sh
# Native map semantics: closed doors, stationary aliens, and animated markers.
set -eu
build=$(cd "$1" && pwd)
data=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-mapmarkers.XXXXXX)
if [ -z "${C7_KEEP_TEST_ARTIFACTS:-}" ]; then trap 'rm -rf "$work"' EXIT HUP INT TERM; else printf 'Artifacts: %s\n' "$work"; fi
xvfb-run -a python3 - "$build" "$data" "$repo" "$work" <<'PY'
from PIL import Image
from dataclasses import replace
from pathlib import Path
import os,shutil,subprocess,sys,zipfile
build,data,repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.planes import MapPlanes
lab=work/'lab';lab.mkdir();(work/'save').mkdir()
for p in [*data.glob('*.CO7'),data/'CORR7CD.EXE']:shutil.copyfile(p,lab/p.name)
records=list(read_archive(data/'MAPTEMP.CO7').records)
a,b=[1]*4096,[18]*4096
for y in range(7,14):
 for x in range(4,30):a[y*64+x]=256 if x<18 else 257
for y in range(7,14):a[y*64+17]=1
a[11*64+22]=259
a[10*64+17]=254;b[10*64+4]=22;b[10*64+14]=85;b[10*64+25]=116
records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(a),tuple(b),tuple([0]*4096))))
(lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
with zipfile.ZipFile(build/'ec7wolf.pk3') as src,zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
 for info in src.infolist():
  blob=src.read(info)
  if info.filename=='xlat/corridor7.txt':blob=blob.replace(b'{85, C7MinePack,',b'{85, C7ProximityMine,').replace(b'{116, C7ProbeEye,',b'{116, C7TestStill,')
  if info.filename=='actors/corridor7/monsters.txt':blob+=b'\nactor C7TestStill : C7ProbeEye { states { Spawn: PROB A -1 stop } }\n'
  dst.writestr(info,blob)
env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1')
for renderer in ('software','opengl'):
 images={}
 for plan,tic in ((False,10),(True,10),(True,12)):
  name=f'{renderer}-{plan}-{tic}';out=work/(name+'.png')
  args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--vid-renderer',renderer,'--res','320','200','--tedlevel','MAP01','--skill','3','--config',str(work/(name+'.cfg')),'--savedir',str(work/'save'),'--capture-rngseed','1','--capture-c7map','--capture-place','1','16.5','10.5','0','--capture-snapshot',str(out),str(tic),'--capture-maxtics',str(tic+2)]
  if plan:args+=['--capture-floorplan']
  with (work/(name+'.log')).open('w') as log:subprocess.run(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=40)
  images[plan,tic]=Image.open(out).convert('RGB')
 floor=(16,16,81)
 def pixel(im,x,y):return im.getpixel((256+x,y))
 bare,full,later=images[False,10],images[True,10],images[True,12]
 assert pixel(bare,20,10)==floor,'Closed door hid the room'
 assert pixel(bare,22,11)==pixel(full,22,11)==(142,142,142),'Native code-259 floor exposed the maze layout'
 assert pixel(bare,25,10)==floor,'Bare map revealed stationary alien'
 alien=pixel(full,25,10);mine=pixel(full,14,10)
 assert alien[0]>0 and alien[0]==alien[1] and alien[2]==0,alien
 assert mine[0]>0 and mine[1]==mine[2]==0,mine
 assert pixel(later,25,10)!=alien and pixel(later,14,10)!=mine,'Markers did not cycle'
 print('PASS code-259 map mask, closed-door room, stationary alien, flashing yellow aliens/red mines:',renderer,flush=True)
PY
