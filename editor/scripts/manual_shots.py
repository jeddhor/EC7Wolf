#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Render the manual's screenshots from the real editor.

Every picture in docs/ec7edit-manual.md is made here, by building the actual
MainWindow and grabbing it. Not mocked, not drawn by hand, not photographed
once and left to rot: a screenshot that was accurate in March is a lie by June,
and a manual illustrated with lies is worse than one with no pictures at all.
Running this again after a UI change regenerates the lot.

**No game data, ever.** These images are committed to a public repository, so
they must not contain one pixel of Corridor 7. That is not achieved by being
careful -- it is achieved by never configuring a data directory, which puts the
palette on its no-artwork path and draws every entry as a labelled tile. The
manual says so where a reader might otherwise wonder why their editor looks
richer than the pictures.

    manual_shots.py [OUTPUT_DIR]     (default: ../docs/images/manual)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITOR))

from PySide6.QtCore import QSettings, Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget        # noqa: E402

from ec7edit_core.campaign import Campaign, CampaignEntry, Route  # noqa: E402
from ec7edit_core.catalog import load_catalog                  # noqa: E402
from ec7edit_core.document import MapDocument, ProjectDocument  # noqa: E402
from ec7edit_core.names import NativeName                      # noqa: E402
from ec7edit_core.planes import MapPlanes                      # noqa: E402
from ec7edit_gui.application import build_application          # noqa: E402
from ec7edit_gui.main_window import MainWindow                 # noqa: E402
from ec7edit_gui.settings import Settings                      # noqa: E402

CATALOG = load_catalog(EDITOR / "resources" / "editor_catalog.json")

#: A window big enough to show the docks without the canvas becoming a stamp.
WINDOW = (1440, 900)

# Words this demonstration map is built from, all real Corridor 7 values --
# the point is to show the editor doing its actual job. The *pictures* of them
# come from the no-artwork path, so no artwork travels with them.
FLOOR = 256            # a floor cell carrying sound area 1
WALL = 1               # plain wall
DOOR = 251             # an ordinary door; the engine infers its axis
BLUE_DOOR = 252        # Door (BLUE lock)
BLUE_TERMINAL = 11     # the wall terminal that grants the BLUE access card
ELEVATOR = 63          # the switch that ends the floor
PLAYER = 19            # player start, facing north
ALIEN = 108            # Alioprobe
PATROL = 112           # Alioprobe (patrolling)


def demo_map(slot: int = 61, name: str = "Reception", *, flawed: bool = False) -> MapDocument:
    """A small, legal, readable floor that tells a story the manual can follow.

    You start in reception, go through a door into the operations room, read
    the terminal there for a blue card, and that opens the vault. The elevator
    out is in operations. Every word here is written by this file, which is
    what makes the pictures publishable.

    `flawed` leaves the terminal out. The map is then still a map -- it loads,
    it plays -- but the vault can never be opened, which is exactly the class
    of mistake the Problems dock exists to catch, and exactly what its
    screenshot should be showing.
    """
    w = h = 24
    walls = [WALL] * (w * h)
    objects = [0] * (w * h)

    def room(x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                walls[y * w + x] = FLOOR

    at = lambda x, y: y * w + x

    room(2, 2, 9, 11)              # reception
    room(13, 2, 20, 15)            # operations
    room(15, 18, 20, 21)           # the vault
    room(10, 6, 12, 6)             # the corridor between the first two
    room(17, 16, 17, 17)           # and down to the vault

    walls[at(10, 6)] = DOOR
    walls[at(17, 16)] = BLUE_DOOR
    if not flawed:
        walls[at(20, 4)] = BLUE_TERMINAL
    walls[at(13, 3)] = ELEVATOR

    objects[at(3, 3)] = PLAYER
    objects[at(16, 8)] = ALIEN
    objects[at(19, 12)] = PATROL
    objects[at(18, 20)] = ALIEN

    return MapDocument(
        uuid=f"manual-{slot}" + ("-flawed" if flawed else ""), slot=slot,
        native_name=NativeName.from_text(name),
        planes=MapPlanes(w, h, (tuple(walls), tuple(objects), tuple([0] * (w * h)))),
    )


def demo_project(*, flawed: bool = False) -> ProjectDocument:
    """The three-floor sample mission the whole manual is written around."""
    project = ProjectDocument.create("Sample Mission")
    for slot, name in ((61, "Reception"), (62, "Operations"), (63, "The Vault")):
        project = project.added(demo_map(slot, name, flawed=flawed))
    campaign = Campaign(title="Sample Mission", key="S", entries=(
        CampaignEntry(61, "Reception", next=Route(62), secret=Route(63)),
        CampaignEntry(62, "Operations", next=Route(None)),
        CampaignEntry(63, "The Vault", next=Route(62)),
    ))
    return project.with_campaign(campaign.to_json())


def quietly(window) -> None:
    """Close a window without it asking about unsaved work.

    Closing a dirty project puts up a modal "save first?" box, and on the
    offscreen platform that waits for an answer nobody can give -- the script
    simply stops, having written every picture up to that point, which is
    exactly how this was first noticed.
    """
    window.project = window.project.marked_saved(window.project.revision)
    window.pool.cancel_all()
    window.pool.wait(2000)
    window.close()
    QApplication.processEvents()


def grab(widget, path: Path) -> None:
    QApplication.processEvents()
    image = widget.grab().toImage()
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))
    print(f"  {path.name}  {image.width()}x{image.height()}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv[0]) if argv else EDITOR.parent / "docs" / "images" / "manual"

    application = build_application([])
    scratch = Path(os.environ.get("TMPDIR", "/tmp")) / "ec7edit-manual-shots"
    scratch.mkdir(parents=True, exist_ok=True)
    settings = Settings(QSettings(str(scratch / "settings.ini"), QSettings.IniFormat))
    settings.recovery_dir = scratch / "recovery"

    window = MainWindow(settings, catalog=CATALOG)
    window.resize(*WINDOW)
    window.project = demo_project()
    # Assigning the project is not the same as the editor being told about it.
    # Without this the Maps list photographs empty, which would have shipped a
    # manual whose first picture shows a feature apparently not working.
    window._refresh()
    window.show()
    QApplication.processEvents()

    # The whole window, with a map open. The first picture in the manual, and
    # the one every later section refers back to.
    tab = window.open_map(window.project.maps[0].uuid)
    tab.canvas.set_zoom(20)
    # A real validation pass, so the Problems dock shows the editor's actual
    # opinion of this map rather than an empty box.
    window.validate()
    QApplication.processEvents()
    grab(window, out / "window.png")

    # Each dock on its own, big enough to read.
    for object_name, filename in (
        ("maps-dock", "dock-maps.png"),
        ("palette-dock", "dock-palette.png"),
        ("inspector-dock", "dock-inspector.png"),
        ("test-log-dock", "dock-testlog.png"),
        ("snapshot-dock", "dock-snapshot.png"),
    ):
        dock = next((d for d in window.findChildren(QDockWidget)
                     if d.objectName() == object_name), None)
        if dock is None:
            print(f"  (no {object_name})")
            continue
        dock.setFloating(True)
        dock.resize(460, 520)
        QApplication.processEvents()
        grab(dock, out / filename)
        dock.setFloating(False)
        QApplication.processEvents()

    # The Problems dock, photographed against a map that HAS a problem. The
    # hero shot above is of a floor that validates clean, which is what a
    # manual's first picture should show; a panel documented with an empty box
    # teaches nothing about what it is for.
    broken = MainWindow(settings, catalog=CATALOG)
    broken.resize(*WINDOW)
    broken.project = demo_project(flawed=True)
    broken._refresh()
    broken.show()
    broken.open_map(broken.project.maps[0].uuid)
    broken.validate()
    QApplication.processEvents()
    problems = next((d for d in broken.findChildren(QDockWidget)
                     if d.objectName() == "problems-dock"), None)
    if problems is not None:
        problems.setFloating(True)
        problems.resize(760, 240)
        QApplication.processEvents()
        grab(problems, out / "dock-problems.png")
    quietly(broken)

    # The campaign editor, with a real campaign in it.
    from ec7edit_gui.campaign_dialog import CampaignDialog
    dialog = CampaignDialog(Campaign.from_json(window.project.campaign),
                            window.project.maps, window)
    dialog.resize(860, 460)
    dialog.show()
    QApplication.processEvents()
    grab(dialog, out / "campaign.png")
    dialog.close()

    # First-run setup, which is the first thing anybody sees. It takes a
    # Profile, not the Settings object -- passing the wrong one built a dialog
    # that never finished laying out and the script hung with no output.
    from ec7edit_gui.first_run import FirstRunDialog
    setup = FirstRunDialog(settings.profile, window)
    setup.resize(760, 460)
    setup.show()
    QApplication.processEvents()
    grab(setup, out / "first-run.png")
    setup.close()

    quietly(window)
    print(f"\nwrote to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
