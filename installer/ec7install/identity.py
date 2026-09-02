"""What this program is called, in the several places that have to agree.

These five strings are one fact wearing different hats, and the moment two of
them disagree the symptom is silent: a window that will not pair with its
launcher, a task manager showing a gray cog, an icon the menu cannot find. They
live here so that no module can change one without seeing the rest.

The value is the project's own AppStream id, from
docs/org.ec7wolf.EC7Wolf.metainfo.xml, whose <launchable> already names
org.ec7wolf.EC7Wolf.desktop -- so the desktop file the installer writes, the
window class the launcher forces, and the metadata the project ships all say
the same thing.
"""

from __future__ import annotations

import os
import platform

APP_ID = "org.ec7wolf.EC7Wolf"
APP_NAME = "EC7Wolf"
APP_COMMENT = "Corridor 7: Alien Invasion source port"
ENGINE_BINARY = "ec7wolf"

# What the window announces itself as, once the launcher has told SDL. Verified
# with xprop against a running engine rather than assumed: SDL takes the class
# from argv[0] unless SDL_VIDEO_X11_WMCLASS says otherwise, which would make it
# "ec7wolf" and match nothing.
WM_CLASS = APP_ID


# What Add/Remove Programs shows, and who it says put it there.
PUBLISHER = "EC7Wolf contributors"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\EC7Wolf"


def host_platform() -> str:
    """"windows", "macos" or "linux" -- the rules to install by.

    One function rather than platform.system() scattered through eight modules,
    because the Windows path deserves to be exercised somewhere other than
    Windows. EC7WOLF_INSTALL_PLATFORM overrides it, which is how the gate runs
    the whole Windows install under Wine on a Linux machine: the code takes
    every Windows branch for real, and the tools it shells out to -- cscript,
    reg -- are answered by Wine.

    The override exists for that test and nothing else. Installing is not
    something to do in a costume, so nothing in the installer sets it.
    """
    override = os.environ.get("EC7WOLF_INSTALL_PLATFORM", "").strip().lower()
    if override in ("windows", "macos", "linux"):
        return override

    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    return "linux"


def is_windows() -> bool:
    return host_platform() == "windows"


def exe_name() -> str:
    return ENGINE_BINARY + ".exe" if is_windows() else ENGINE_BINARY


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a checkout."""
    import sys
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundled_root():
    """Where the files that travel with the installer are, frozen or not.

    A frozen setup.exe unpacks its data to a temporary directory, and that
    directory is the closest thing it has to a source tree: the license, the
    icons and engine.desktop.in are all in there, laid out at the same relative
    paths so nothing else has to know the difference.
    """
    import sys
    from pathlib import Path
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent
