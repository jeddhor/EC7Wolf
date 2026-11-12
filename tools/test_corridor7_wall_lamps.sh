#!/bin/sh
# Native static red/yellow wall indicators retain source brightness.
set -eu
build=$(cd "$1" && pwd)
data=$(cd "$2" && pwd)
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=$(mktemp -d /tmp/ec7wolf-wall-lamps.XXXXXX)
if [ -z "${C7_KEEP_TEST_ARTIFACTS:-}" ]; then trap 'rm -rf "$work"' EXIT HUP INT TERM; else printf 'Artifacts: %s\n' "$work"; fi
xvfb-run -a python3 - "$build" "$data" "$repo" "$work" <<'PY'
from dataclasses import replace
from pathlib import Path
from collections import Counter
from PIL import Image
import os,shutil,subprocess,sys
build,data,repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'editor'))
from ec7edit_core.archive import read_archive,encode_archive
from ec7edit_core.assets import load_palette,palette_rgb
lab=work/'lab';lab.mkdir();(work/'save').mkdir()
for p in [*data.glob('*.CO7'),data/'CORR7CD.EXE',build/'ec7wolf.pk3']:shutil.copyfile(p,lab/p.name)
records=list(read_archive(data/'MAPTEMP.CO7').records);source=records[3]
palette=load_palette((data/'CORR7CD.EXE').read_bytes())
env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='x11',LIBGL_ALWAYS_SOFTWARE='1')
for renderer in ('software','opengl'):
    for state,wall,colors in [('ready',111,range(250,254)),('spent',112,range(242,248))]:
        plane=list(source.planes.planes[0]);plane[53*64+26]=wall
        records[3]=replace(source,planes=source.planes.with_plane(0,tuple(plane)))
        (lab/'MAPTEMP.CO7').write_bytes(encode_archive(records))
        for x,visor in [(24.5,0),(22.5,0),(22.5,2)]:
            label=f'{renderer}-{state}-{x}-{visor}'
            cfg=work/(label+'.cfg');cfg.write_text('ViewSize = 21;\nC7MiniHUD = 1;\n')
            out=work/(label+'.png');ppm=out.with_suffix('.ppm')
            cmd=[str(build/'ec7wolf'),'--data','CO7','--nowait','--no-upscale','--res','640','400','--vid-renderer',renderer,'--tedlevel','MAP04','--skill','3','--config',str(cfg),'--savedir',str(work/'save'),'--capture-rngseed','1','--capture-place','1',str(x),'53.5','0','--capture-snapshot',str(out),'30','--capture-maxtics','35']
            if visor:cmd+=['--capture-visormode',str(visor)]
            if renderer=='opengl':cmd+=['--capture-glpresent',str(ppm)]
            with (work/(label+'.log')).open('w') as log:subprocess.run(cmd,cwd=lab,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
            image=Image.open(ppm if renderer=='opengl' else out).convert('RGB')
            counts=Counter(image.crop((0,35,640,230)).getdata())
            # These exact source colors remain visible at both distances in
            # DOS. Its shade mask at DS:2a1e is zero for indices 240..254.
            for color in colors:assert counts[palette_rgb(palette,color)]>0,(label,'dimmed lamp color',color)
            if x==22.5:
                # The neighboring white indicator is ordinary index 39, so
                # it and the housing must remain shaded rather than turning
                # the entire dispenser into a full-bright wall.
                white_box=(306,160,314,168) if state=='ready' else (290,160,298,168)
                assert max(max(v) for v in image.crop(white_box).getdata())<200,(label,'dispenser housing became full-bright')
        print('PASS native lamp colors at near/far distances and under infrared:',renderer,state,flush=True)
PY
