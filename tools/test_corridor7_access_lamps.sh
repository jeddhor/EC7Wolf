#!/bin/sh
# Retail map words 24/25 are type-0 decorations, not collectible access cards.
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-access.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$repo" "$work" <<'PY'
from dataclasses import replace
from pathlib import Path
import os,re,shutil,struct,subprocess,sys,zipfile
build,data,repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.planes import MapPlanes
exe=(data/'CORR7CD.EXE').read_bytes();header=struct.unpack_from('<H',exe,8)[0]*16
base=header+(0x4557-0x1000)*16+0x1908
assert [struct.unpack_from('<HH',exe,base+i*4) for i in (1,2)]==[(2,0),(3,0)]
lab=work/'lab';lab.mkdir();(work/'save').mkdir()
for f in data.glob('*.CO7'):shutil.copy2(f,lab/f.name)
shutil.copy2(data/'CORR7CD.EXE',lab/'CORR7CD.EXE')
shutil.copy2(build/'ec7wolf.pk3',lab/'ec7wolf.pk3')
records=list(read_archive(data/'MAPTEMP.CO7').records)
def run(name,extra=(),renderer='software',want='--',level='MAP01'):
    log=work/(name+'.log');trace=work/(name+'.players')
    args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','320','200',
          '--vid-renderer',renderer,'--tedlevel',level,'--skill','3','--config',str(work/(name+'.cfg')),
          '--savedir',str(work/'save'),'--capture-players',str(trace),'--capture-rngseed','1',
          '--capture-snapshot',str(work/(name+'.png')),'150','--capture-place','1','4.5','10.5','0',*extra]
    with log.open('w') as out:subprocess.run(args,cwd=lab,env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1'),stdout=out,stderr=subprocess.STDOUT,check=True,timeout=45)
    text=log.read_text();found=re.search(r'player \((\d+),(\d+)\) cards (\S+)',text)
    assert found and found[3]==want,(name,text[-1200:]);return int(found[1]),int(found[2])
for renderer in ('software','opengl'):
    pos=run('retail-'+renderer,('--capture-place','1','51.5','27.5','180','--capture-forward','20','100'),renderer,level='MAP05')
    assert pos[0]<43,('did not cross the retail markers',pos)
    print('PASS retail MAP05 walking over red lamps grants no access:',renderer,flush=True)

walls,things=[1]*4096,[18]*4096
for x in range(3,31):walls[10*64+x]=256
things[10*64+4]=19;things[10*64+8]=24;things[10*64+12]=25
records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
(lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
with zipfile.ZipFile(build/'ec7wolf.pk3') as src,zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
    for info in src.infolist():
        blob=src.read(info)
        if info.filename=='xlat/corridor7.txt':blob=blob.replace(b'{24, C7RedCeilingLamp,',b'{24, C7Static001,').replace(b'{25, C7BlueCeilingLamp,',b'{25, C7Static002,')
        dst.writestr(info,blob)
# Save before crossing either old collectible. The supplied bug save uses the
# same actor classes; this synthetic snapshot is distributable without data.
run('old-save',('--capture-save','10','legacy.ecs'))
shutil.copy2(build/'ec7wolf.pk3',lab/'ec7wolf.pk3')
pos=run('migrated',('--capture-load','10','legacy.ecs','--capture-forward','20','100'))
assert pos[0]>12,pos
print('PASS old saved red/blue actors become non-pickup lamps',flush=True)
run('owned-save',('--capture-give','C7Static001','--capture-save','10','owned.ecs'),want='R-')
run('owned-load',('--capture-load','10','owned.ecs'),want='R-')
print('PASS migration preserves owned access tokens',flush=True)
for wall,want in ((9,'R-'),(11,'-B')):
    w=list(walls);w[10*64+5]=wall
    records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(w),tuple(things),tuple([0]*4096))))
    (lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
    run(f'terminal-{wall}',('--capture-use','20','15'),want=want)
print('PASS real red and blue wall terminals still grant access',flush=True)
PY
