#!/bin/sh
# End-to-end checks for the optional shotgun rule, saves/network authority,
# and actual numeric HUD content in software and live OpenGL presentation.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-enhancements.XXXXXX)
if [ -z "${C7_KEEP_TEST_ARTIFACTS:-}" ]; then trap 'rm -rf "$work"' EXIT HUP INT TERM; else printf 'Artifacts: %s\n' "$work"; fi
xvfb-run -a python3 - "$build_dir" "$data_dir" "$repo" "$work" <<'PY'
from PIL import Image,ImageChops
import struct
from pathlib import Path
from dataclasses import replace
import os,re,shutil,sys,subprocess,zipfile,time
build,data,repo,work=map(Path,sys.argv[1:]);lab=work/'lab';lab.mkdir();(work/'save').mkdir()
sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.planes import MapPlanes
for f in data.glob('*.CO7'):shutil.copy2(f,lab/f.name)
shutil.copy2(data/'CORR7CD.EXE',lab/'CORR7CD.EXE')
records=list(read_archive(data/'MAPTEMP.CO7').records)
env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1')
def fixture(dist=7,health=100,armor=0):
 walls,things=[1]*4096,[18]*4096
 for y in range(2,16):
  for x in range(2,30):walls[y*64+x]=256
 things[10*64+4]=22;things[10*64+4+dist]=108
 records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
 (lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
 with zipfile.ZipFile(build/'ec7wolf.pk3') as src,zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
  for info in src.infolist():
   blob=src.read(info)
   if info.filename=='actors/corridor7/player.txt':
    blob=blob.replace(b'player.startitem "C7Bayonet"',b'').replace(b'player.startitem "C7M16"',b'player.startitem "C7Shotgun"').replace(b'actor C7Player : PlayerPawn\n{',f'actor C7Player : PlayerPawn\n{{\n health {health}\n player.startitem "C7BodyArmor", {armor}\n player.startitem "C7Mines", 25'.encode())
    blob+=b'\nactor C7TestTarget { health 100000 +SHOOTABLE +ISMONSTER +ATTACKMODE states { Spawn: PROB A -1 stop } }\n'
   if info.filename=='xlat/corridor7.txt':blob=blob.replace(b'{108, C7OrganicEye,',b'{108, C7TestTarget,')
   dst.writestr(info,blob)
def run(label,setting=0,extra=(),tics=500,renderer='software',hud=''):
 cfg=work/(label+'.cfg');cfg.write_text((f'C7ShotgunPreset = {setting};\n' if setting is not None else 'C7EnhancedShotgun = 1;\n')+hud)
 args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','320','200','--vid-renderer',renderer,'--tedlevel','MAP01','--skill','3','--config',str(cfg),'--savedir',str(work/'save'),'--capture-rngseed','1','--capture-actors',str(work/(label+'.actors')),'--capture-checksum',str(work/(label+'.checksums')),'--capture-place','1','4.5','10.5','0','--capture-ammo','--capture-maxtics',str(tics),*extra]
 with (work/(label+'.log')).open('w') as log:subprocess.run(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
 rows=[l.split() for l in (work/(label+'.actors')).read_text().splitlines() if not l.startswith('#')]
 hp=[int(r[7]) for r in rows if r[1]=='C7TestTarget']
 hits=[a-b for a,b in zip(hp,hp[1:]) if b<a]
 return hits
baselines={}
for dist in (1,3,7):
    fixture(dist)
    classic=run(f'classic-{dist}',extra=('--capture-fire','20'))
    enhanced=run(f'enhanced-{dist}',1,('--capture-fire','20'))
    minimum100=run(f'minimum100-{dist}',2,('--capture-fire','20'))
    assert minimum100==[max(hit,100) for hit in classic],(dist,classic,minimum100)
    assert len(classic)>=6,(dist,classic)
    assert enhanced==[max(hit,50) for hit in classic],(dist,classic,enhanced)
    if dist==7:assert min(classic)<50,('sample did not exercise the floor',classic)
    baselines[dist]=classic
    print('PASS real hit sequences at distance',dist,flush=True)
fixture(7)
for saved in (0,1,2):
 run(f'save-rule-{saved}',saved,('--capture-save','10',f'rule{saved}.ecs'),tics=40)
 image=Image.open(work/'save'/f'rule{saved}.ecs');image.load()
 assert image.info['EC7Wolf Shotgun Minimum']==str((0,50,100)[saved])
 hits=run(f'load-rule-{saved}',0 if saved else 2,('--capture-load','10',f'rule{saved}.ecs','--capture-fire','20'))
 baseline=baselines[7]
 assert hits==[max(x,(0,50,100)[saved]) if saved else x for x in baseline],(saved,hits)
 print('PASS saved rule',saved,'overrides opposite current preference',flush=True)
b=(work/'save/rule1.ecs').read_bytes();out=bytearray(b[:8]);p=8
while p<len(b):
 n=struct.unpack_from('>I',b,p)[0];chunk=b[p:p+n+12];tag=b[p+4:p+8];payload=b[p+8:p+8+n]
 if not (tag==b'tEXt' and payload.split(b'\0')[0] in (b'EC7Wolf Enhanced Shotgun',b'EC7Wolf Shotgun Minimum')):out.extend(chunk)
 p+=n+12
(work/'save/legacy.ecs').write_bytes(out)
# A pre-preset enhanced save contains only the legacy boolean.
old=bytearray(b[:8]);p=8
while p<len(b):
 n=struct.unpack_from('>I',b,p)[0];chunk=b[p:p+n+12];tag=b[p+4:p+8];payload=b[p+8:p+8+n]
 if not (tag==b'tEXt' and payload.startswith(b'EC7Wolf Shotgun Minimum\0')):old.extend(chunk)
 p+=n+12
(work/'save/old-enhanced.ecs').write_bytes(old)
assert run('old-enhanced-save',0,('--capture-load','10','old-enhanced.ecs','--capture-fire','20'))==[max(x,50) for x in baselines[7]]
assert run('old-enhanced-config',None,('--capture-fire','20'))==[max(x,50) for x in baselines[7]]
print('PASS legacy enhanced saves and configurations retain Minimum 50',flush=True)
hits=run('load-legacy',1,('--capture-load','10','legacy.ecs','--capture-fire','20'))
assert min(hits)<50,hits
print('PASS legacy saves without the new metadata remain classic',flush=True)
for enabled in (0,1,2):
 logs=[];processes=[]
 port=5281+enabled*10
 for peer in (0,1):
  label=f'net-{enabled}-{peer}';cfg=work/(label+'.cfg');cfg.write_text(f'C7ShotgunPreset = {enabled if peer==0 else (enabled+1)%3};\nC7MiniHUD = {peer};\n')
  log=(work/(label+'.log')).open('w');logs.append(log)
  args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','320','200','--vid-renderer','software','--tedlevel','MAP01','--skill','3','--config',str(cfg),'--savedir',str(work/'save'),'--capture-rngseed','1','--capture-checksum',str(work/(label+'.crc')),'--capture-ammo','--capture-fire','30','--capture-maxtics','350']
  args+=['--host','2','--port',str(port)] if peer==0 else ['--port',str(port+1),'--join',f'127.0.0.1:{port}']
  processes.append(subprocess.Popen(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT));time.sleep(.4)
 try:
  for p in processes:assert p.wait(timeout=50)==0
 finally:
  for p in processes:
   if p.poll() is None:p.terminate();p.wait(timeout=5)
  for f in logs:f.close()
 for peer in (0,1):
  label=f'net-{enabled}-{peer}';text=(work/(label+'.log')).read_text()
  assert 'Corridor 7 shotgun rule: '+(f'enhanced (minimum {(0,50,100)[enabled]})' if enabled else 'classic') in text,text[-1000:]
 a=(work/f'net-{enabled}-0.crc').read_text();b=(work/f'net-{enabled}-1.crc').read_text();assert a==b,('peers disagree',enabled)
 print('PASS host rule',enabled,'overrides opposing client preference; all 350 world checksums match',flush=True)
fixture(7,100,400)
for renderer in ('software','opengl'):
 for size in (20,21):
  shots=[]
  for enabled in (0,1):
   label=f'final-{renderer}-{size}-{enabled}';extra=['--capture-give','C7Adrenaline','--capture-snapshot',str(work/(label+'.png')),'60']
   if renderer=='opengl':extra+=['--capture-glpresent',str(work/(label+'.ppm'))]
   run(label,extra=extra,tics=65,renderer=renderer,hud=f'ViewSize = {size};\nC7MiniHUD = {enabled};\nC7NumericHUD = {enabled};\n')
   image=Image.open(work/(label+('.ppm' if renderer=='opengl' else '.png'))).convert('RGB');shots.append(image.copy())
   if size==20 and enabled:
    patterns=['111101101101111','010110010010111','111001111100111','111001111001111','101101111001001','111100111001111','111100111101111','111001001001001','111101111101111','111101111001111']
    for x,y,number in [(97,171,'400'),(97,190,'400'),(200,171,'200'),(200,189,'25'),(149,192,'100')]:
     start=x+(25-(len(number)*4-1))//2
     for i,c in enumerate(number):
      pixels=list(image.crop((start+4*i,y+1,start+4*i+3,y+6)).getdata())
      observed=''.join('1' if r>200 and g>200 and b>200 else '0' for r,g,b in pixels)
      assert all(a=='1' for a,b in zip(observed,patterns[int(c)]) if b=='1'),(label,number,c,observed)
  diff=ImageChops.difference(shots[0],shots[1])
  assert diff.crop((0,170,320,200)).getbbox(),(renderer,size,'HUD toggle has no visible effect')
  # The world checksum, rather than frame-paced palette effects, proves that
  # a display preference does not alter the simulation.
  assert (work/f'final-{renderer}-{size}-0.checksums').read_bytes()==(work/f'final-{renderer}-{size}-1.checksums').read_bytes()
  print('PASS rendered HUD content and independent toggle',renderer,size,flush=True)
  cfg=(work/f'final-{renderer}-{size}-1.cfg').read_text()
  assert 'C7MiniHUD = 1;' in cfg and 'C7NumericHUD = 1;' in cfg
fixture(7,100,65535)
# Exercise all three inventory icons in the compact layout.
with zipfile.ZipFile(lab/'ec7wolf.pk3') as src:files=[(i,src.read(i)) for i in src.infolist()]
with zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
 for info,blob in files:
  if info.filename=='actors/corridor7/player.txt':blob=blob.replace(b'player.startitem "C7Shotgun"',b'player.startitem "C7Shotgun"\nplayer.startitem "C7Static001"\nplayer.startitem "C7Static002"\nplayer.startitem "C7FloorPlan"')
  dst.writestr(info,blob)
for renderer in ('software','opengl'):
 for held in (0,1,2):
  label=f'held-{renderer}-{held}';extra=['--capture-give','C7Adrenaline','--capture-snapshot',str(work/(label+'.png')),'60']
  if held==1:extra+=['--capture-hold-button','statusbar','20','100']
  if renderer=='opengl':extra+=['--capture-glpresent',str(work/(label+'.ppm'))]
  run(label,extra=extra,tics=65,renderer=renderer,hud=f'ViewSize = 21;\nC7MiniHUD = 1;\nC7NumericHUD = 1;\nC7MiniHUDStyle = {int(held==2)};\n')
  im=Image.open(work/(label+('.ppm' if renderer=='opengl' else '.png'))).convert('RGB')
  if held==1:
   for i,c in enumerate('65535'):
    pixels=list(im.crop((100+i*4,191,103+i*4,196)).getdata());bits=''.join('1' if r>200 and g>200 and b>200 else '0' for r,g,b in pixels)
    expect={'6':'111100111101111','5':'111100111001111','3':'111001111001111'}[c]
    assert all(a=='1' for a,b in zip(bits,expect) if b=='1'),(label,c,bits)
  if held==2:
   for box in ((208,181,224,196),(232,181,248,196),(256,181,312,196)):
    assert any(g>r and g>b and g>40 for r,g,b in im.crop(box).getdata()),(label,'missing classic readout',box)
   assert 'C7MiniHUDStyle = 1;' in (work/(label+'.cfg')).read_text()
  print(('PASS classic compact readouts' if held==2 else 'PASS full-screen held status' if held else 'CAPTURE all items at native armor maximum'),renderer,flush=True)
PY
