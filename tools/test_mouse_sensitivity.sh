#!/bin/sh
# Equal relative displacement must survive sampling and command finalization,
# regardless of delivery rate, direction, and sensitivity (GitHub issue #1).
set -eu
build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
work=$(mktemp -d /tmp/ec7wolf-mouse.XXXXXX)
trap 'rm -rf "$work"' EXIT HUP INT TERM
xvfb-run -a python3 - "$build_dir" "$data_dir" "$work" <<'PY'
import os
from pathlib import Path
import subprocess
import sys

build, data, work = map(Path, sys.argv[1:])
env = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_VIDEODRIVER="x11")
for sensitivity in (0, 5, 20):
    for sign in (-1, 1):
        totals = []
        for label, ticks, delta in (("slow", 84, sign), ("fast", 1, sign*84)):
            stem = work / f"{sensitivity}-{sign}-{label}"
            cfg = stem.with_suffix('.cfg')
            cfg.write_text(f"MouseXAdjustment = {sensitivity};\n")
            trace = stem.with_suffix('.commands')
            args = [str(build/'ec7wolf'), '--data', 'CO7', '--nowait',
                    '--res', '320', '200', '--vid-renderer', 'software',
                    '--tedlevel', 'MAP01', '--skill', '2',
                    '--config', str(cfg), '--savedir', str(work/'save'),
                    '--capture-commands', str(trace), '--capture-maxtics', '100',
                    '--capture-mouse', '5', str(ticks), str(delta), '0']
            with stem.with_suffix('.log').open('w') as log:
                subprocess.run(args, cwd=data, env=env, stdout=log,
                               stderr=subprocess.STDOUT, timeout=45, check=True)
            rows = [line.split() for line in trace.read_text().splitlines()
                    if line.split() and line.split()[0].isdigit()]
            yaw = sum(int(row[2]) for row in rows if row[1] == '0')
            totals.append(yaw)
            assert all(abs(int(row[3])) <= 100 and abs(int(row[4])) <= 100
                       for row in rows), 'movement escaped its speed limit'
            assert f'MouseXAdjustment = {sensitivity};' in cfg.read_text()
        expected = sign * (84*20//(21-sensitivity))
        assert totals == [expected, expected], (sensitivity, sign, totals, expected)
        print(f'PASS sensitivity {sensitivity}, direction {sign:+}: '
              f'slow = fast = {expected} turn units', flush=True)
PY
