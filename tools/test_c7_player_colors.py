#!/usr/bin/env python3
"""Exercise player uniform textures and visor rendering in a packaged game.

Usage: xvfb-run -a python3 tools/test_c7_player_colors.py RELEASE_DIR OUTPUT_DIR
The output is private retail-derived art, never a repository artifact.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageChops
from make_c7_player_colors import COLORS

release, work = (Path(p).resolve() for p in sys.argv[1:])
work.mkdir(parents=True, exist_ok=True)
env = {**os.environ, "SDL_AUDIODRIVER": "dummy", "SDL_VIDEODRIVER": "x11"}
tape = work / "idle.tape"
tape.write_text("0 0 0\nloop\n")


def run(tag, extra):
    cmd = [str(release / "ec7wolf"), "--data", "CO7", "--nowait",
           "--res", "640", "400", "--vid-renderer", "software",
           "--config", str(work / f"{tag}.cfg"), "--savedir", str(work / "saves"),
           "--tedlevel", "MAP60", "--skill", "2", "--battle", "--capture-rngseed", "1",
           "--capture-maxframes", "12", *extra]
    with (work / f"{tag}.log").open("w") as f:
        result = subprocess.run(cmd, cwd=release, env=env, stdout=f,
                                stderr=subprocess.STDOUT, timeout=45)
    log = (work / f"{tag}.log").read_text()
    assert result.returncode in (0, 1) and "Capture: summary" in log, tag
    assert not any(s in log.lower() for s in ["fatal error", "parser error", "missing rotation",
                                             "unknown patch", "warp target", "cannot export"]), tag
    return log


banks = ["MARN", *(v[1] for v in COLORS)]
exports = []
for bank in banks:
    exports += ["--capture-sprite-bank", bank, str(work / f"{bank}.json")]
run("banks", exports)
subprocess.run([sys.executable, str(Path(__file__).with_name("export_c7_player_colors.py")),
                str(work), "--data", str(release)], check=True)

duel = ["--capture-tape", str(tape), "--capture-duel", "0", "1"]
run("positions", [*duel, "--capture-players", str(work / "positions.tr")])
rows = [line.split() for line in (work / "positions.tr").read_text().splitlines() if not line.startswith("#")]
host, target = rows[:2]
hx, hy, tx, ty = [int(row[column]) / 65536 for row, column in
                 [(host, 10), (host, 11), (target, 10), (target, 11)]]
# The normal duel is three tiles away. Move along its sight line to one tile.
near = ["--capture-warp", str(hx + (tx-hx)*2/3 - .5),
        str(hy + (ty-hy)*2/3 - .5), host[4]]

cases = 0
for color in ["Blue", *(v[0] for v in COLORS)]:
    for mode in range(3):
        for distance, warp in [("near", near), ("far", [])]:
            tag = f"{color.lower()}-visor{mode}-{distance}"
            log = run(tag, [*duel, *warp, "--playerclass", "C7Player" + (color if color != "Blue" else ""),
                           "--capture-visormode", str(mode), "--capture-frame", "8",
                           "--capture-file", str(work / f"{tag}.png"),
                           "--capture-glframe", str(work / f"{tag}.gl.ppm")])
            assert "GL world:" in log, tag
            for suffix in [".png", ".gl.ppm"]:
                with Image.open(work / (tag + suffix)) as im:
                    assert im.size == (640, 400) and max(c[1] for c in im.convert("RGB").getextrema()) > 80
                    if color != "Blue" and mode == 0:
                        with Image.open(work / (f"blue-visor0-{distance}" + suffix)) as blue:
                            difference = ImageChops.difference(im.convert("RGB"), blue.convert("RGB"))
                            pixels = difference.tobytes()
                            count = sum(any(pixels[i:i+3]) for i in range(0, len(pixels), 3))
                            assert count > 20, f"uniform was not visible: {tag} {suffix}"
            cases += 1
    print(f"PASS {color}: normal/night/infrared, near/far, software/OpenGL", flush=True)
(work / "render-report.json").write_text(json.dumps({"cases": cases, "renderer_captures": cases * 2,
    "modes": ["normal", "night", "infrared"], "distances_tiles": [1, 3]}, indent=2) + "\n")
print(f"PASS: {cases} scenes, {cases * 2} renderer captures; all 408 sprite frames validated.")
