"""Menu and desktop entries.

Reuses what the project already ships -- src/posix/engine.desktop.in and
src/posix/icon.svg, and the org.ec7wolf.EC7Wolf application id from the
AppStream metainfo -- rather than inventing a second identity for the same
program. Every file created is returned so the manifest can record it and the
uninstaller can take it away again.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .progress import Reporter

APP_ID = "org.ec7wolf.EC7Wolf"
APP_NAME = "EC7Wolf"
APP_COMMENT = "Corridor 7: Alien Invasion source port"


def _desktop_entry(exec_path: Path, icon: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Comment={APP_COMMENT}\n"
        f"Exec={exec_path}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Game;ActionGame;\n"
        "Keywords=Corridor 7;Wolfenstein;FPS;\n"
        f"StartupWMClass={APP_NAME}\n"
    )


def install_icon(repo_root: Path, reporter: Reporter) -> tuple[str, list[Path]]:
    """Put the icon where the desktop can find it. -> (icon name, files)."""
    source = repo_root / "src" / "posix" / "icon.svg"
    if not source.is_file():
        return (APP_NAME.lower(), [])

    target_dir = (Path.home() / ".local" / "share" / "icons" / "hicolor"
                  / "scalable" / "apps")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{APP_ID}.svg"
    shutil.copy2(source, target)
    reporter.detail(f"icon -> {target}")
    return (APP_ID, [target])


def create(destination: Path, launcher: Path, repo_root: Path,
           reporter: Reporter, menu: bool = True,
           desktop: bool = True) -> list[Path]:
    """Create the requested shortcuts, returning what was written."""
    if platform.system() == "Windows":
        return _create_windows(destination, launcher, reporter, menu, desktop)
    return _create_linux(destination, launcher, repo_root, reporter, menu, desktop)


def _create_linux(destination: Path, launcher: Path, repo_root: Path,
                  reporter: Reporter, menu: bool, desktop: bool) -> list[Path]:
    created: list[Path] = []
    icon_name, icon_files = install_icon(repo_root, reporter)
    created += icon_files

    entry = _desktop_entry(launcher, icon_name)

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
                           capture_output=True)

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
                        capture_output=True, timeout=10)
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
                                 capture_output=True, text=True, timeout=10)
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
    """Windows shortcuts. Fleshed out with the rest of the Windows work."""
    created: list[Path] = []
    icon = destination / "ec7wolf.exe"
    targets: list[Path] = []
    if menu:
        programs = Path(os.environ.get("APPDATA", Path.home())) / \
            "Microsoft" / "Windows" / "Start Menu" / "Programs"
        targets.append(programs / f"{APP_NAME}.lnk")
    if desktop:
        targets.append(Path.home() / "Desktop" / f"{APP_NAME}.lnk")

    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        script = (
            "$s = (New-Object -COM WScript.Shell).CreateShortcut('%s');"
            "$s.TargetPath='%s';$s.WorkingDirectory='%s';"
            "$s.IconLocation='%s';$s.Description='%s';$s.Save()"
            % (target, launcher, destination, icon, APP_COMMENT))
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, timeout=60, check=True)
            created.append(target)
            reporter.detail(f"shortcut -> {target}")
        except Exception as error:
            reporter.warn(f"could not create {target}: {error}")
    return created
