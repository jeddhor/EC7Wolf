"""Which keys the game starts with.

EC7Wolf's defaults are the modern ones -- WASD to move, E to use -- which is
what almost everyone expects from a first-person shooter now and is not what
Corridor 7 shipped with in 1994. Someone coming back to the game after thirty
years reaches for the arrow keys and the space bar, finds neither works, and
concludes something is broken.

So the installer says which scheme it is about to set up, and offers the other
one. This writes a configuration file with the original's bindings; the engine
fills in everything else from its own defaults the first time it runs, because
a setting that is absent from the file is simply created.

The values are SDL 1.2 keysyms, which is what the engine's configuration
format stores -- read out of a config the engine itself wrote, not looked up in
a table somewhere and hoped. tools/test_installer_controls.sh checks that the
engine still agrees.
"""

from __future__ import annotations

from pathlib import Path

CONFIG_NAME = "ec7wolf.cfg"

# What the engine does if nobody says otherwise.
MODERN = {
    "Keyboard_Forward": (119, "W"),
    "Keyboard_Backward": (115, "S"),
    "Keyboard_Strafe_Left": (97, "A"),
    "Keyboard_Strafe_Right": (100, "D"),
    "Keyboard_Turn_Left": (276, "Left arrow"),
    "Keyboard_Turn_Right": (275, "Right arrow"),
    "Keyboard_Use": (101, "E"),
    "Keyboard_Attack": (306, "Ctrl"),
    "Keyboard_Strafe": (308, "Alt"),
    "Keyboard_Run": (304, "Shift"),
}

# What Corridor 7 shipped with. Turn, attack, strafe and run are already these
# values; only movement and use actually move.
CLASSIC = {
    "Keyboard_Forward": (273, "Up arrow"),
    "Keyboard_Backward": (274, "Down arrow"),
    "Keyboard_Turn_Left": (276, "Left arrow"),
    "Keyboard_Turn_Right": (275, "Right arrow"),
    "Keyboard_Use": (32, "Space"),
    "Keyboard_Attack": (306, "Ctrl"),
    "Keyboard_Strafe": (308, "Alt"),
    "Keyboard_Run": (304, "Shift"),
    # A and D are left on strafe. The original had no key for it -- you held
    # Alt and turned -- but adding one takes nothing away, and removing a
    # binding that conflicts with nothing would only make the scheme worse.
    "Keyboard_Strafe_Left": (97, "A"),
    "Keyboard_Strafe_Right": (100, "D"),
}


def describe(scheme: dict) -> str:
    """One line per binding, for a page or a terminal."""
    order = ("Keyboard_Forward", "Keyboard_Backward", "Keyboard_Turn_Left",
             "Keyboard_Turn_Right", "Keyboard_Strafe_Left",
             "Keyboard_Strafe_Right", "Keyboard_Use", "Keyboard_Attack",
             "Keyboard_Run", "Keyboard_Strafe")
    pretty = {"Keyboard_Forward": "Move forward",
              "Keyboard_Backward": "Move back",
              "Keyboard_Turn_Left": "Turn left",
              "Keyboard_Turn_Right": "Turn right",
              "Keyboard_Strafe_Left": "Sidestep left",
              "Keyboard_Strafe_Right": "Sidestep right",
              "Keyboard_Use": "Open / use",
              "Keyboard_Attack": "Fire",
              "Keyboard_Run": "Run",
              "Keyboard_Strafe": "Sidestep (held)"}
    return "\n".join(f"{pretty[key]}: {scheme[key][1]}"
                     for key in order if key in scheme)


def write_config(destination: Path, scheme: dict = CLASSIC) -> Path:
    """Write a configuration holding just these bindings.

    Everything else is left out on purpose. The engine creates any setting the
    file does not have, so a short file means "these keys, and your usual
    defaults for the rest" -- and it stays correct when the engine gains a
    setting this installer has never heard of.
    """
    path = Path(destination) / CONFIG_NAME
    lines = [
        "// Written by the EC7Wolf installer: the original's control scheme.",
        "// Everything not listed here uses the engine's own default, and any",
        "// of it can be changed in Options -> Controls.",
        "",
    ]
    lines += [f"{key} = {value};" for key, (value, _name) in sorted(scheme.items())]
    path.write_text("\n".join(lines) + "\n")
    return path
