#!/bin/sh
# Native-glass corner faces, first-cell visibility, and sprite depth ordering.
set -eu
build=$(cd "$1" && pwd)
data=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-glass.XXXXXX)
if [ -z "${C7_KEEP_TEST_ARTIFACTS:-}" ]; then trap 'rm -rf "$work"' EXIT HUP INT TERM; else printf 'Artifacts: %s\n' "$work"; fi
xvfb-run -a python3 - "$build" "$data" "$repo" "$work" <<'PY'
from dataclasses import replace
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter
import os, shutil, subprocess, sys
build,data,repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.planes import MapPlanes
lab=work/'lab';lab.mkdir();(work/'save').mkdir()
for p in [*data.glob('*.CO7'),data/'CORR7CD.EXE',build/'ec7wolf.pk3']:shutil.copyfile(p,lab/p.name)
records=list(read_archive(data/'MAPTEMP.CO7').records)
env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1')
def capture(renderer,panes,sprite,filtered=False):
    walls,things=[1]*4096,[18]*4096
    for y in range(5,16):
        for x in range(2,18):walls[y*64+x]=256
    things[10*64+10]=21
    if panes!='none':walls[10*64+8]=57;things[10*64+8]=104
    if panes in ('adjacent','distant'):
        x=7 if panes=='adjacent' else 4
        walls[10*64+x]=57;things[10*64+x]=104
    if sprite!='none':things[10*64+(9 if sprite=='front' else 6)]=82
    records[0]=replace(records[0],planes=MapPlanes(64,64,(tuple(walls),tuple(things),tuple([0]*4096))))
    (lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
    label=f'{renderer}-{panes}-{sprite}-{int(filtered)}';cfg=work/(label+'.cfg')
    cfg.write_text(f'ViewSize = 20;\nVid_GLMSAA = {4 if filtered else 0};\nVid_GLFilter = {1 if filtered else 0};\n')
    out=work/(label+'.png');ppm=work/(label+'.ppm')
    args=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','320','200','--vid-renderer',renderer,'--tedlevel','MAP01','--skill','3','--config',str(cfg),'--savedir',str(work/'save'),'--capture-rngseed','1','--capture-place','1','10.5','10.5','180','--capture-snapshot',str(out),'20','--capture-maxtics','25']
    if renderer=='opengl':args+=['--capture-glpresent',str(ppm)]
    with (work/(label+'.log')).open('w') as log:subprocess.run(args,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
    return Image.open(ppm if renderer=='opengl' else out).convert('RGB').crop((0,20,320,155))
for renderer,filtered in [('software',False),('opengl',False),('opengl',True)]:
    images={}
    for sprite in ('none','front','back'):
        for panes in ('single','adjacent','distant'):
            images[panes,sprite]=capture(renderer,panes,sprite,filtered)
        for other in ('adjacent','distant'):
            assert not ImageChops.difference(images['single',sprite],images[other,sprite]).getbbox(),(renderer,filtered,sprite,other,'rear glass changed nearest cell')
    naked=capture(renderer,'none','none',filtered)
    front=capture(renderer,'none','front',filtered)
    mask=ImageChops.difference(naked,front).convert('L').point(lambda p:255 if p else 0)
    # Filtered cutout edges mix with the background, which legitimately changes
    # when glass is added behind them. Check the fully covered sprite interior.
    if filtered:mask=mask.filter(ImageFilter.MinFilter(7))
    assert mask.getbbox(),(renderer,'front sprite absent from control')
    wrong=ImageChops.difference(front,images['single','front'])
    assert not ImageChops.multiply(wrong.convert('L'),mask).getbbox(),(renderer,filtered,'glass obscured foreground sprite')
    assert ImageChops.difference(images['single','none'],images['single','back']).getbbox(),(renderer,filtered,'background sprite invisible through glass')
    print('PASS foreground corner, adjacent/distant glass, sprites in front/behind:',renderer,'filtered MSAA' if filtered else 'nearest',flush=True)
PY
