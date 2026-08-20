"""What this program is called, in the several places that have to agree.

These five strings are one fact wearing different hats, and the moment two of
them disagree the symptom is silent: a window that will not pair with its
launcher, a task manager showing a grey cog, an icon the menu cannot find. They
live here so that no module can change one without seeing the rest.

The value is the project's own AppStream id, from
docs/org.ec7wolf.EC7Wolf.metainfo.xml, whose <launchable> already names
org.ec7wolf.EC7Wolf.desktop -- so the desktop file the installer writes, the
window class the launcher forces, and the metadata the project ships all say
the same thing.
"""

from __future__ import annotations

APP_ID = "org.ec7wolf.EC7Wolf"
APP_NAME = "EC7Wolf"
APP_COMMENT = "Corridor 7: Alien Invasion source port"
ENGINE_BINARY = "ec7wolf"

# What the window announces itself as, once the launcher has told SDL. Verified
# with xprop against a running engine rather than assumed: SDL takes the class
# from argv[0] unless SDL_VIDEO_X11_WMCLASS says otherwise, which would make it
# "ec7wolf" and match nothing.
WM_CLASS = APP_ID
