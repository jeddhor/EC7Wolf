"""Exercise the approved November campaign fixes through ordinary engine paths."""
from dataclasses import replace
from pathlib import Path
import os, re, shutil, subprocess, sys, zipfile
build, data, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
from ec7edit_core.archive import read_archive, encode_archive
from ec7edit_core.planes import MapPlanes
lab = work / 'lab'; lab.mkdir(); (work / 'saves').mkdir()
for p in [*data.glob('*.CO7'), data / 'CORR7CD.EXE']: shutil.copyfile(p, lab / p.name)
source = list(read_archive(data / 'MAPTEMP.CO7').records)
env = dict(os.environ, SDL_AUDIODRIVER='dummy', SDL_VIDEODRIVER='x11')
def fixture(pickups=False, health=100, probe=False):
    records = source.copy()
    for level in (0, 1):
        walls, things = [1]*4096, [18]*4096
        for y in range(9, 12):
            for x in range(4, 30): walls[y*64+x] = 256
        things[10*64+4] = 22
        if level == 0 and pickups:
            for x in (6,8,10): things[10*64+x] = 79
            for x in (7,9): things[10*64+x] = 52
        if level == 0 and probe: things[10*64+25] = 116
        records[level] = replace(records[level], planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
    (lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
    with zipfile.ZipFile(build/'ec7wolf.pk3') as src, zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
        for info in src.infolist():
            b = src.read(info)
            if info.filename=='actors/corridor7/player.txt':
                b = b.replace(b'actor C7Player : PlayerPawn\n{',f'actor C7Player : PlayerPawn\n{{\n health {health}'.encode())
                b = b.replace(b'player.startitem "C7Bullets", 100',b'player.startitem "C7Bullets", 200')
            if info.filename=='mapinfo/corridor7.txt': b = re.sub(rb'(map "MAP01"[^\n]*\n\{)',rb'\1\n nointermission',b)
            dst.writestr(info,b)
def run(label, extra=(), skill=3, tics=150):
    log=work/(label+'.log'); actors=work/(label+'.actors')
    args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','320','200','--vid-renderer','software','--tedlevel','MAP01','--skill',str(skill),'--config',str(work/(label+'.cfg')),'--savedir',str(work/'saves'),'--capture-rngseed','1','--capture-verbs','--capture-actors',str(actors),'--capture-maxtics',str(tics),*extra]
    with log.open('w') as f: subprocess.run(args,cwd=lab,env=env,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=45)
    text=log.read_text(); rows=[dict((k,int(v)) for k,v in re.findall(r'(\w+)=(-?\d+)',l)) for l in text.splitlines() if l.startswith('verbs tic=')]
    assert rows,(label,text[-1000:])
    return text,rows,actors.read_text()
for skill in (1,3):
    fixture(pickups=True)
    _,rows,_=run(f'packs-{skill}',('--capture-place','1','4.5','10.5','0','--capture-forward','10','90','--capture-save','110','capacity.ecs'),skill)
    assert {200,700,999} <= {r['capacity'] for r in rows},rows
    assert all(r['ammo']==200 for r in rows),rows
    assert rows[-1]['packs']==rows[-1]['plans']==0 and rows[-1]['plan']==1,rows[-1]
    _,loaded,_=run(f'loaded-{skill}',('--capture-load','10','capacity.ecs'),skill,tics=40)
    assert loaded[-1]['capacity']==999 and loaded[-1]['ammo']==200 and loaded[-1]['packs']==loaded[-1]['plans']==0,loaded
    text,travel,_=run(f'capacity-travel-{skill}',('--capture-load','10','capacity.ecs','--capture-exitlevel','40'),skill)
    assert 'MAP02 - ' in text and travel[-1]['capacity']==999 and travel[-1]['ammo']==200,travel
    print('PASS full-ammo capacity upgrades, surplus pack, duplicate plans and save/load, rank',skill,flush=True)
fixture()
text,rows,_=run('boost-travel',('--capture-give','C7Adrenaline','--capture-save','10','boost.ecs','--capture-load','40','boost.ecs','--capture-exitlevel','80'))
assert 'MAP02 - ' in text and any(r['health']==400 for r in rows) and rows[-1]['health']==100,rows
_,loaded,_=run('boost-load',('--capture-load','10','boost.ecs'),tics=50)
assert loaded[-1]['health']==400,loaded
for hp in (63,100,101):
    fixture()
    text,rows,_=run(f'health-{hp}',('--capture-health',str(hp),'--capture-exitlevel','30'))
    assert 'MAP02 - ' in text and rows[0]['health']==hp and rows[-1]['health']==min(100,hp),rows
print('PASS boosted same-floor save/load; travel caps excess without healing wounds',flush=True)
fixture(probe=True)
for skill,want in enumerate((25,50,100,150,200),1):
    _,_,actors=run(f'rank-{skill}',skill=skill,tics=5)
    hp=[int(l.split()[7]) for l in actors.splitlines() if not l.startswith('#') and l.split()[1]=='C7ProbeEye']
    assert hp and set(hp)=={want},(skill,want,hp)
print('PASS five native health rows; President uses 200 HP for Animated Probe',flush=True)
