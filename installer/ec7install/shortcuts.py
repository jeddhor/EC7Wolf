"""Menu and desktop entries.

Reuses what the project already ships -- src/posix/engine.desktop.in and
src/posix/icon.svg, and the org.ec7wolf.EC7Wolf application id from the
AppStream metainfo -- rather than inventing a second identity for the same
program. Every file created is returned so the manifest can record it and the
uninstaller can take it away again.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import windows
from . import proc
from .identity import (APP_COMMENT, APP_ID, APP_NAME, ENGINE_BINARY,
                       is_windows)
from .progress import Reporter



def _quote(path) -> str:
    """Quote a path for an Exec= line, per the desktop entry spec.

    Not decoration: the default install path has no spaces, but a user who
    installs into "~/My Games/EC7Wolf" gets an entry that silently launches
    nothing at all, because the desktop reads Exec as a command line and splits
    it on whitespace.
    """
    text = str(path)
    for character in ("\\", '"', "$", "`"):
        text = text.replace(character, "\\" + character)
    return '"' + text.replace("%", "%%") + '"'


def _template(repo_root: Path) -> dict:
    """The project's own engine.desktop.in, read rather than reinvented.

    It carries the name, comment and categories the ECWolf packaging already
    uses; duplicating them here would mean an installed EC7Wolf and a packaged
    one drifting apart for no reason. Everything it cannot know -- where this
    particular install went -- is filled in by the caller.
    """
    fields = {"Version": "1.0", "Type": "Application", "Name": APP_NAME,
              "Comment": APP_COMMENT, "Categories": "Game"}
    path = repo_root / "src" / "posix" / "engine.desktop.in"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fields

    substitutions = {"@PRODUCT_NAME@": APP_NAME,
                     "@PRODUCT_IDENTIFIER@": APP_ID,
                     "@ENGINE_BINARY_NAME@": ENGINE_BINARY}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("[", "#")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        for placeholder, replacement in substitutions.items():
            value = value.replace(placeholder, replacement)
        fields[key.strip()] = value.strip()
    return fields


def _desktop_entry(exec_path: Path, icon: str, destination: Path,
                   repo_root: Path) -> str:
    fields = _template(repo_root)

    categories = fields.get("Categories", "Game")
    if not categories.endswith(";"):
        # The spec makes the trailing semicolon part of the list syntax, and
        # desktop-file-validate says so; the template predates that check.
        categories += ";"
    if "ActionGame" not in categories:
        categories += "ActionGame;"

    fields.update({
        "Exec": _quote(exec_path),
        "Icon": icon,
        "Categories": categories,
        "Terminal": "false",
        "StartupNotify": "true",
        # Measured, not guessed: this is what the window really announces once
        # the launcher has set SDL's WM class, and it is what a Plasma or GNOME
        # task manager matches to pair the window with this entry. Getting it
        # wrong costs the taskbar icon and the grouping, silently.
        "StartupWMClass": APP_ID,
        "Keywords": "Corridor 7;Alien Invasion;Wolfenstein;FPS;shooter;",
        "Actions": "Fullscreen;Folder;",
    })

    order = ["Version", "Type", "Name", "Comment", "Exec", "Icon", "Terminal",
             "Categories", "Keywords", "StartupNotify", "StartupWMClass",
             "Actions"]
    lines = ["[Desktop Entry]"]
    lines += [f"{key}={fields[key]}" for key in order if key in fields]
    lines += [f"{key}={value}" for key, value in sorted(fields.items())
              if key not in order]

    # Right-click actions on the launcher, which Plasma and GNOME both show.
    lines += ["", "[Desktop Action Fullscreen]",
              "Name=Play fullscreen",
              f"Exec={_quote(exec_path)} --fullscreen",
              "", "[Desktop Action Folder]",
              "Name=Open the install folder",
              f"Exec=xdg-open {_quote(destination)}"]
    return "\n".join(lines) + "\n"


# The raster sizes the project already ships, for the panels and task managers
# that would rather not rasterise an SVG themselves. Named by hicolor's
# directory, so the mapping is the whole of the knowledge needed.
RASTER_ICONS = {
    "16x16": "icon_16x16.png",
    "32x32": "icon_32x32.png",
    "128x128": "icon_128x128.png",
    "256x256": "icon_256x256.png",
    "512x512": "icon_512x512.png",
}


def install_icon(repo_root: Path, reporter: Reporter) -> tuple[str, list[Path]]:
    """Put the icon where the desktop can find it. -> (icon name, files).

    Into the user's own hicolor theme, under the application id, which is the
    name the desktop entry then asks for. Nothing here needs root, and nothing
    here is shared with a packaged EC7Wolf installed system-wide.
    """
    icons = Path.home() / ".local" / "share" / "icons" / "hicolor"
    written: list[Path] = []

    scalable = repo_root / "src" / "posix" / "icon.svg"
    if scalable.is_file():
        target_dir = icons / "scalable" / "apps"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{APP_ID}.svg"
        shutil.copy2(scalable, target)
        written.append(target)
        reporter.detail(f"icon -> {target}")

    iconset = repo_root / "src" / "macosx" / "icon.iconset"
    for size, name in RASTER_ICONS.items():
        source = iconset / name
        if not source.is_file():
            continue
        target_dir = icons / size / "apps"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{APP_ID}.png"
        shutil.copy2(source, target)
        written.append(target)

    if not written:
        return (APP_NAME.lower(), [])

    # GTK panels read a cache; KDE reads the directory. Refreshing it is
    # harmless where it is not needed and invisible where it is.
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(["gtk-update-icon-cache", "-q", "-t", "-f", str(icons)],
                       capture_output=True, **proc.quiet())
    return (APP_ID, written)


def create(destination: Path, launcher: Path, repo_root: Path,
           reporter: Reporter, menu: bool = True,
           desktop: bool = True) -> list[Path]:
    """Create the requested shortcuts, returning what was written."""
    if is_windows():
        return _create_windows(destination, launcher, reporter, menu, desktop)
    return _create_linux(destination, launcher, repo_root, reporter, menu, desktop)


def _create_linux(destination: Path, launcher: Path, repo_root: Path,
                  reporter: Reporter, menu: bool, desktop: bool) -> list[Path]:
    created: list[Path] = []
    icon_name, icon_files = install_icon(repo_root, reporter)
    created += icon_files

    entry = _desktop_entry(launcher, icon_name, destination, repo_root)

    if menu:
        applications = Path.home() / ".local" / "share" / "applications"
        applications.mkdir(parents=True, exist_ok=True)
        path = applications / f"{APP_ID}.desktop"
        path.write_text(entry)
        path.chmod(0o755)
        created.append(path)
        reporter.detail(f"menu entry -> {path}")
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(applications)],
                           capture_output=True, **proc.quiet())

    if desktop:
        desktop_dir = _desktop_directory()
        if desktop_dir is not None:
            path = desktop_dir / f"{APP_ID}.desktop"
            path.write_text(entry)
            # KDE and GNOME both refuse to launch an entry that is not
            # executable, and KDE additionally wants it marked trusted; the
            # executable bit is the part that is portable.
            path.chmod(0o755)
            try:
                if shutil.which("gio"):
                    subprocess.run(
                        ["gio", "set", str(path), "metadata::trusted", "true"],
                        capture_output=True, timeout=10, **proc.quiet())
            except Exception:
                pass
            created.append(path)
            reporter.detail(f"desktop icon -> {path}")
        else:
            reporter.warn("could not find your Desktop folder; "
                          "the desktop icon was skipped")
    return created


def _desktop_directory() -> Path | None:
    """The user's Desktop, asking the desktop itself before guessing."""
    if shutil.which("xdg-user-dir"):
        try:
            out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                 capture_output=True, text=True, timeout=10,
                                 **proc.quiet())
            candidate = Path(out.stdout.strip())
            # xdg-user-dir answers with $HOME when it has no Desktop configured,
            # and scattering a .desktop file into the home directory is not what
            # anyone asked for.
            if candidate.is_dir() and candidate != Path.home():
                return candidate
        except Exception:
            pass
    fallback = Path.home() / "Desktop"
    return fallback if fallback.is_dir() else None


def _create_windows(destination: Path, launcher: Path, reporter: Reporter,
                    menu: bool, desktop: bool) -> list[Path]:
    """Start menu and desktop .lnk files, made by the shell itself."""
    created: list[Path] = []
    icon = destination / windows.exe_for_icon()

    targets: list[Path] = []
    if menu:
        targets.append(windows.start_menu_directory() / f"{APP_NAME}.lnk")
    if desktop:
        targets.append(windows.desktop_directory() / f"{APP_NAME}.lnk")

    for target in targets:
        try:
            windows.create_shortcut(
                target, launcher, working_directory=destination,
                icon=icon if icon.exists() else None,
                description=APP_COMMENT)
            created.append(target)
            reporter.detail(f"shortcut -> {target}")
        except Exception as error:                        # noqa: BLE001
            reporter.warn(f"could not create {target.name}: {error}. The "
                          "game is installed; only the shortcut is missing.")
    return created
