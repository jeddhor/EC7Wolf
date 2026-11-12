#!/bin/sh
# Compact-meter transparency and native full-screen weapon geometry.
set -eu
build=$(cd "$1" && pwd)
data=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-compact-hud.XXXXXX)
if [ -z "${C7_KEEP_TEST_ARTIFACTS:-}" ]; then trap 'rm -rf "$work"' EXIT HUP INT TERM; else printf 'Artifacts: %s\n' "$work"; fi
xvfb-run -a python3 - "$build" "$data" "$repo" "$work" <<'PY'
from dataclasses import replace
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
import os, shutil, subprocess, sys, zipfile
build,data,repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.planes import MapPlanes
lab=work/'lab';lab.mkdir();(work/'save').mkdir()
for p in [*data.glob('*.CO7'),data/'CORR7CD.EXE']:shutil.copyfile(p,lab/p.name)
records=list(read_archive(data/'MAPTEMP.CO7').records)
walls,things=[1]*4096,[18]*4096
for y in range(5,16):
    for x in range(2,19):walls[y*64+x]=256
things[10*64+10]=21
records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
(lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1')
with zipfile.ZipFile(build/'ec7wolf.pk3') as src:files=[(i,src.read(i)) for i in src.infolist()]
def capture(renderer,weapon='C7M16',hud=True,res=(640,400),view=21,score=True):
    # A hidden-ready-frame control gives an independent weapon silhouette.
    with zipfile.ZipFile(lab/'ec7wolf.pk3','w') as dst:
        for info,blob in files:
            if info.filename=='actors/corridor7/player.txt':
                blob=blob.replace(b'player.startitem "C7Bayonet"',b'')
                blob=blob.replace(b'player.startitem "C7M16"',f'player.startitem "{weapon or "C7M16"}"'.encode())
                blob=blob.replace(b'\thealth 100\n',b'\thealth 50\n',1)
                blob=blob.replace(b'player.startitem "C7VisorCharge", 100',b'player.startitem "C7VisorCharge", 50',1)
                if weapon is None:blob=blob.replace(b'C761 A 1 A_WeaponReady',b'TNT1 A 1 A_WeaponReady')
            dst.writestr(info,blob)
    name=f'{renderer}-{weapon}-{int(hud)}-{res[0]}x{res[1]}-view{view}-score{int(score)}'
    cfg=work/(name+'.cfg');cfg.write_text(f'ViewSize = {view};\nC7MiniHUD = {int(hud)};\nC7MiniHUDStyle = 1;\nC7MiniHUDScore = {int(score)};\n')
    out=work/(name+'.png');ppm=work/(name+'.ppm')
    cmd=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res',*map(str,res),'--vid-renderer',renderer,'--tedlevel','MAP01','--skill','3','--config',str(cfg),'--savedir',str(work/'save'),'--capture-rngseed','1','--capture-place','1','10.5','10.5','180','--capture-snapshot',str(out),'30','--capture-maxtics','35']
    if renderer=='opengl':cmd+=['--capture-glpresent',str(ppm)]
    with (work/(name+'.log')).open('w') as log:subprocess.run(cmd,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
    return Image.open(ppm if renderer=='opengl' else out).convert('RGB')
# Measured with the unmodified retail executable in the same 640x400 view-21
# fixture, subtracting its weapon-hidden control. Rounding can differ by one
# native pixel between the original column scaler and the port's texture blit.
native_bounds={
    'C7Bayonet':(270,234,390,400),'C7Shotgun':(238,258,400,400),
    'C7M16':(254,240,404,400),'C7M343':(232,264,416,400),
    'C7DualBlaster':(226,264,416,400),'C7PlasmaRifle':(222,284,406,400),
    'C7AssaultCannon':(222,262,416,400),'C7Disintegrator':(222,264,416,400),
}
for renderer in ('software','opengl'):
    hidden=capture(renderer,None)
    for weapon,expected in native_bounds.items():
        image=capture(renderer,weapon)
        diff=ImageChops.difference(image,hidden)
        # Selecting an energy weapon also changes the compact ammo readout.
        ImageDraw.Draw(diff).rectangle((0,360,199,399),fill=(0,0,0))
        observed=diff.getbbox()
        assert observed and all(abs(a-b)<=2 for a,b in zip(observed,expected)),(renderer,weapon,expected,observed)
    print('PASS all eight full-screen weapon bounds match native DOS:',renderer,flush=True)
    hud=capture(renderer)
    # Measured DOS bottom interior row and bevel corner. The last numeral row
    # belongs inside the filled well, above the border, rather than on the floor.
    assert hud.getpixel((96,374))==(199,199,0),(renderer,'compact meter fill is one native row short')
    assert hud.getpixel((80,376))==(170,170,170),(renderer,'wrong lower-left bevel corner')
    # The source M16 hand uses this skin color. It must survive first-person
    # rendering at its native brightness, independently of the level light.
    assert sum(v==(170,93,56) for v in hud.crop((250,240,410,400)).getdata())>100,(renderer,'first-person hand was darkened')
    # Empty armor/mines and the unfilled halves of health/visor must expose
    # the scene. Exclude outlines, digits, and the filled part of each meter.
    for box in ((28,384,64,390),(92,384,128,390),(50,368,64,374),(178,368,192,374)):
        # The floor gradient is horizontally uniform apart from its ordered
        # dither. Sample its unobstructed neighboring 16-pixel period, keeping
        # that phase while avoiding the meters and the centered weapon.
        assert all(hud.getpixel((x,y))==hud.getpixel((208+x%16,y)) for y in range(box[1],box[3]) for x in range(box[0],box[2])),(renderer,'opaque meter well',box)
    for box in ((16,380,68,394),(80,380,132,394)):
        assert any(hud.getpixel((x,y))!=hud.getpixel((208+x%16,y)) for y in range(box[1],box[3]) for x in range(box[0],box[2])),(renderer,'meter border/digits absent',box)
    print('PASS empty/partial meters reveal the scene and retain borders:',renderer,flush=True)
    for res in ((320,200),(640,360)):
        hidden=capture(renderer,None,res=res);image=capture(renderer,res=res)
        bounds=ImageChops.difference(hidden,image).getbbox()
        # Height/anchor must track the full-screen view at native and wide
        # resolutions; the model remains centered rather than drifting left.
        expected_top=240*res[1]/400
        assert bounds and abs(bounds[1]-expected_top)<=2,(renderer,res,bounds)
        assert abs((bounds[0]+bounds[2])/2-res[0]/2)<=res[1]*.04,(renderer,res,'off-center',bounds)
    print('PASS native-resolution and widescreen weapon placement:',renderer,flush=True)
    full=capture(renderer,hud=False)
    standard=capture(renderer,view=20)
    assert not ImageChops.difference(full,standard).getbbox(),(renderer,'mini HUD off did not restore standard view and status bar')
    persisted=(work/f'{renderer}-C7M16-0-640x400-view21-score1.cfg').read_text()
    assert 'ViewSize = 20;' in persisted and 'C7MiniHUD = 0;' in persisted,(renderer,'HUD-off state did not persist')
    print('PASS disabled compact HUD restores and persists the full status-bar view:',renderer,flush=True)
    no_score=capture(renderer,score=False)
    assert ImageChops.difference(hud.crop((510,360,626,394)),no_score.crop((510,360,626,394))).getbbox(),(renderer,'score option has no visible effect')
    assert not ImageChops.difference(hud.crop((414,360,498,394)),no_score.crop((414,360,498,394))).getbbox(),(renderer,'hiding score changed floor/alien readouts')
    assert all(no_score.getpixel((x,y))==no_score.getpixel((208+x%16,y)) for y in range(360,394) for x in range(510,626)),(renderer,'hidden score left an opaque panel')
    persisted=(work/f'{renderer}-C7M16-1-640x400-view21-score0.cfg').read_text()
    assert 'C7MiniHUDScore = 0;' in persisted,(renderer,'score preference did not persist')
    print('PASS native meter interior, unshaded hand, and optional compact score:',renderer,flush=True)
PY
