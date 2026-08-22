#!/usr/bin/env python3
"""Print the y of the highlighted row in a Corridor 7 menu screenshot.

The gates drive these menus by counting keystrokes, which is only correct while
every keystroke arrives. When one is dropped the cursor sits one row up and the
next Return presses the wrong thing -- on the rank ladder that silently starts a
single-player game, the host waits for a player who never comes, and the gate
fails twenty minutes later looking like a netcode bug. It cost one full suite
run before this existed.

So instead of counting, the gates look. The shell draws the row under the
cursor in yellow and every other row in white or grey, so the highlighted row
is the widest run of yellow pixels in the menu column. Prints -1 if there is
none, which is itself worth knowing: it means the screen being looked at is not
a menu.
"""

import sys

from PIL import Image


# The menu column, in the 1280x800 the gates run these captures at.
COLUMN = (780, 1230)
BAND = (150, 700)


def highlight_row(path):
    px = Image.open(path).convert("RGB").load()
    counts = {}
    for y in range(*BAND):
        n = sum(1 for x in range(*COLUMN)
                if px[x, y][0] > 180 and px[x, y][1] > 140 and px[x, y][2] < 90)
        if n:
            counts[y] = n

    if not counts:
        return -1

    runs = []
    for y in sorted(counts):
        if runs and y - runs[-1][-1] <= 3:
            runs[-1].append(y)
        else:
            runs.append([y])

    # The dim section label is yellow too, but it is one thin line of small
    # capitals; the highlighted row is a whole line of full-size text.
    best = max(runs, key=lambda r: max(counts[y] for y in r))
    if max(counts[y] for y in best) < 10:
        return -1
    return (best[0] + best[-1]) // 2


if __name__ == "__main__":
    print(highlight_row(sys.argv[1]))
