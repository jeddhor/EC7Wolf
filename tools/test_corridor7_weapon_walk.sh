#!/bin/sh
# Compare rendered ready poses and placement with the unmodified original CD
# executable's lookup tables. Run all eight weapons in both renderers, plus
# running and the disabled-bob setting. Commercial data stays in a temp fixture.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
work=$(mktemp -d /tmp/ec7wolf-walk.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$work" <<'PY'
from pathlib import Path
import os,sys,struct,subprocess,zipfile,shutil
build,data,work=map(Path,sys.argv[1:])
exe=(data/'CORR7CD.EXE').read_bytes();base=struct.unpack_from('<H',exe,8)[0]*16+(0x4557-0x1000)*16
xs=struct.unpack_from('<16h',exe,base+0x2c1e);poses=struct.unpack_from('<16H',exe,base+0x2c3e)
print('CORR7CD.EXE horizontal offsets:',xs,flush=True)
print('CORR7CD.EXE ready-pose cycle:',poses,flush=True)
weapons=[('C7Bayonet',746),('C7Shotgun',786),('C7M16',754),('C7M343',762),('C7DualBlaster',770),('C7PlasmaRifle',778),('C7AssaultCannon',794),('C7Disintegrator',802)]
cases=[(r,w,b,1,65536) for r in ('software','opengl') for w,b in weapons]
cases += [('software','C7M16',754,0,65536),('software','C7M16',754,1,0)]
for renderer,weapon,b,alwaysrun,bob in cases:
    stem=work/f'{renderer}-{weapon}-{alwaysrun}-{bob}';cfg=stem.with_suffix('.cfg');cfg.write_text(f'AlwaysRun = {alwaysrun};\nMoveBob = {bob};\nVid_MaxFPS = 30;\n')
    lab=work/'lab';lab.mkdir(exist_ok=True)
    for f in data.iterdir():
      if f.is_file() and f.suffix.upper() in ('.CO7','.EXE') and not (lab/f.name).exists():shutil.copy2(f,lab/f.name)
    with zipfile.ZipFile(build/'ec7wolf.pk3') as src,zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
      for item in src.infolist():
        blob=src.read(item)
        if item.filename.endswith('corridor7/player.txt'):
          blob=blob.replace(b'player.startitem "C7Bayonet"',b'').replace(b'player.startitem "C7M16"',f'player.startitem "{weapon}"'.encode())
        dst.writestr(item,blob)
    args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','320','200','--vid-renderer',renderer,'--tedlevel','MAP01','--skill','2','--config',str(cfg),'--savedir',str(work/'save'),'--capture-viewmodel',str(stem.with_suffix('.trace')),'--capture-forward','20','100','--capture-maxtics','140']
    with stem.with_suffix('.log').open('w') as log:subprocess.run(args,cwd=lab,env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1'),stdout=log,stderr=subprocess.STDOUT,timeout=40,check=True)
    rows=[line.split() for line in stem.with_suffix('.trace').read_text().splitlines() if not line.startswith('#')]
    rows=[(int(r[1]),int(r[2][1:4])-b,int(r[3])) for r in rows if 30<int(r[0])<100]
    assert rows,stem
    if bob==0:
      assert {p for t,p,x in rows}=={7} and len({x for t,p,x in rows})==1,('bob disabled',rows)
      print('PASS disabled weapon bob stays stationary',flush=True)
      continue
    stride=1 if alwaysrun else 2
    good=[]
    for offset in range(16):
      if all(pose==poses[(t*stride+offset)%16] for t,pose,x in rows):good.append(offset)
    assert good,(stem,rows[:20])
    expected={poses[(i*stride+good[0])%16] for i in range(16)}
    assert {p for t,p,x in rows}==expected,(stem,rows)
    assert any(all(len({x-xs[(t*stride+off)%16] for t,p,x in rows if p==pose})==1 for pose in expected) for off in good),(stem,'x offsets')
    print('PASS',renderer,weapon,f'native poses and offsets, stride {stride}',flush=True)
PY
