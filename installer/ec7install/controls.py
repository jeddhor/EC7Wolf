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

#: The engine remembers which scheme was chosen here, because "restore
#: defaults" on the controls screen has to know which defaults are meant. The
#: values are ControlScheme::Style in src/wl_def.h.
STYLE_SETTING = "ControlStyle"
STYLE_MODERN = 0
STYLE_CLASSIC = 1

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


def record_style(destination: Path, classic: bool) -> Path:
    """Say which scheme this installation uses, without disturbing anything else.

    For the modern scheme there are no bindings to write -- they are the
    engine's own -- so all that is needed is the one line the game reads when
    somebody asks it to restore the defaults. It cannot be written the way the
    classic bindings are, into the staging tree, because `Staging.carry_over`
    skips any file that is already there: a file written that way replaces the
    player's configuration instead of joining it, and a reinstall would throw
    away every setting they had. Measured by
    tools/test_installer_lifecycle.sh, which is what caught it.

    So this runs on the finished install, and only when there is no
    configuration there at all. An existing one is left byte for byte as it
    was, which is what a reinstall promises and what
    tools/test_installer_lifecycle.sh checks: the player's file is theirs, and
    an installer that rewrites it to add a line is an installer that edits
    their settings behind their back.

    Nothing is lost by leaving it. A configuration that already exists either
    names a style already -- from the install that created it -- or does not,
    in which case the engine reads the modern default, which is the answer this
    would have written. And a player who asks for the original's controls gets
    controls.write_config instead, which deliberately replaces the file.
    """
    path = Path(destination) / CONFIG_NAME
    if path.exists():
        return path

    style = STYLE_CLASSIC if classic else STYLE_MODERN
    line = f"{STYLE_SETTING} = {style};"

    path.write_text("\n".join([
        "// Written by the EC7Wolf installer: the modern control scheme.",
        "// The bindings themselves are the engine's own defaults; this only",
        "// records which scheme Options -> Controls should restore.",
        "",
        line,
    ]) + "\n")
    return path


def write_config(destination: Path, scheme: dict = CLASSIC) -> Path:
    """Write a configuration holding just these bindings, and which set it is.

    Everything else is left out on purpose. The engine creates any setting the
    file does not have, so a short file means "these keys, and your usual
    defaults for the rest" -- and it stays correct when the engine gains a
    setting this installer has never heard of.

    The style is recorded alongside, because the bindings alone cannot answer
    the question the game later asks. A player who rebinds Forward to J has a
    configuration that matches neither scheme, and "restore defaults" still has
    to know which one they started from. Written for the modern scheme too,
    where there are no bindings to write at all: the whole file is then the one
    line saying which scheme this installation is.
    """
    classic = scheme is not MODERN
    path = Path(destination) / CONFIG_NAME
    lines = [
        "// Written by the EC7Wolf installer: "
        + ("the original's control scheme." if classic
           else "the modern control scheme."),
        "// Everything not listed here uses the engine's own default, and any",
        "// of it can be changed in Options -> Controls.",
        "",
        f"{STYLE_SETTING} = {STYLE_CLASSIC if classic else STYLE_MODERN};",
    ]
    # The modern scheme is the engine's own, so its bindings are left out
    # entirely: writing them would pin today's defaults into the file and stop
    # a later engine from improving them. The one line above is the whole
    # point of the file in that case.
    if classic:
        lines += [f"{key} = {value};"
                  for key, (value, _name) in sorted(scheme.items())]
    path.write_text("\n".join(lines) + "\n")
    return path
