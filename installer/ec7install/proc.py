"""Starting child processes without throwing windows at the user.

On Windows, every process a windowed program starts gets its own console
window unless it is told not to. The installer starts a great many -- FFmpeg
once per CD track, CMake, the compiler, meson, cscript -- so ripping a
soundtrack meant eight black boxes flashing across the screen in front of a
wizard that was trying to look composed.

CREATE_NO_WINDOW is the whole fix. It is collected here because it has to be
passed at every single call site to be worth anything, and one missed call is
one flash.
"""

from __future__ import annotations

import os
import sys

# 0x08000000. Named explicitly rather than taken from subprocess, which only
# defines it on Windows.
CREATE_NO_WINDOW = 0x08000000


def on_windows() -> bool:
    """The real platform, not the one identity.host_platform() may be playing.

    Deliberately not identity.is_windows(): the gates force that to "windows"
    while running on Linux, and creationflags is a Windows-only argument that
    fails outright anywhere else.
    """
    return os.name == "nt" or sys.platform.startswith("win")


def quiet() -> dict:
    """Keyword arguments that keep a child process off the screen."""
    if not on_windows():
        return {}
    return {"creationflags": CREATE_NO_WINDOW}
