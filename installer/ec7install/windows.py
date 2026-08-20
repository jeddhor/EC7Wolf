"""The things only Windows has: .lnk shortcuts and Add/Remove Programs.

Two rules shape this module.

The first is that a .lnk is not written by hand. It is a binary shell-link
structure whose target is normally an item ID list -- a serialised walk of the
shell namespace -- and a hand-rolled one is the kind of thing that works on the
machine it was written on and fails silently elsewhere. Windows already has an
implementation, so this asks it to do the job.

The second is that the request goes through cscript rather than PowerShell.
Both can drive WScript.Shell, but cscript has shipped in every Windows since
2000, starts in a fraction of the time, and is not subject to PowerShell's
execution policy -- which is set to Restricted by default on client Windows and
is a normal reason for a working script to refuse to run. PowerShell remains as
a fallback for the locked-down case where WSH itself is disabled.

Everything here shells out to programs named by their bare names, so the gate
can answer them with Wine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .identity import (APP_COMMENT, APP_NAME, PUBLISHER, UNINSTALL_KEY,
                       is_windows)
from . import proc
from .progress import Reporter


class ShortcutError(Exception):
    pass


def _vbs_string(text: str) -> str:
    """A VBScript string literal. Doubling the quote is the whole escape."""
    return '"' + str(text).replace('"', '""') + '"'


def _run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=timeout, errors="replace", **proc.quiet())


def create_shortcut(path: Path, target: Path, arguments: str = "",
                    working_directory: Path | None = None,
                    icon: Path | None = None,
                    description: str = APP_COMMENT) -> Path:
    """Write one .lnk, using whichever scripting host the machine still has."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    last = "no scripting host was tried"
    for attempt in (_create_with_cscript, _create_with_powershell):
        error = attempt(path, target, arguments, working_directory, icon,
                        description)
        if error is None:
            return path
        last = error

    raise ShortcutError(
        f"could not create {path.name}: {last}. Windows Script Host and "
        "PowerShell were both unavailable or refused to run, which usually "
        "means a policy has disabled them.")


def _create_with_cscript(path, target, arguments, working_directory, icon,
                         description) -> str | None:
    cscript = shutil.which("cscript")
    if cscript is None:
        return "cscript was not found"

    lines = [
        'Set shell = CreateObject("WScript.Shell")',
        f"Set link = shell.CreateShortcut({_vbs_string(path)})",
        f"link.TargetPath = {_vbs_string(target)}",
        f"link.Description = {_vbs_string(description)}",
    ]
    if arguments:
        lines.append(f"link.Arguments = {_vbs_string(arguments)}")
    if working_directory:
        lines.append(f"link.WorkingDirectory = {_vbs_string(working_directory)}")
    if icon:
        lines.append(f"link.IconLocation = {_vbs_string(str(icon) + ',0')}")
    lines.append("link.Save")

    script = Path(tempfile.mkdtemp(prefix="ec7wolf-lnk-")) / "shortcut.vbs"
    script.write_text("\n".join(lines) + "\n", encoding="ascii", errors="replace")
    try:
        result = _run([cscript, "//nologo", str(script)])
        if result.returncode != 0:
            return (result.stderr or result.stdout or
                    f"cscript exited {result.returncode}").strip()
        if not path.exists():
            return "cscript reported success but wrote no file"
        return None
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    finally:
        shutil.rmtree(script.parent, ignore_errors=True)


def _create_with_powershell(path, target, arguments, working_directory, icon,
                            description) -> str | None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        return "PowerShell was not found"

    def quoted(value) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    script = [
        "$shell = New-Object -ComObject WScript.Shell",
        f"$link = $shell.CreateShortcut({quoted(path)})",
        f"$link.TargetPath = {quoted(target)}",
        f"$link.Description = {quoted(description)}",
    ]
    if arguments:
        script.append(f"$link.Arguments = {quoted(arguments)}")
    if working_directory:
        script.append(f"$link.WorkingDirectory = {quoted(working_directory)}")
    if icon:
        script.append(f"$link.IconLocation = {quoted(str(icon) + ',0')}")
    script.append("$link.Save()")

    try:
        result = _run([powershell, "-NoProfile", "-NonInteractive",
                       "-ExecutionPolicy", "Bypass", "-Command", "; ".join(script)])
        if result.returncode != 0:
            return (result.stderr or f"PowerShell exited {result.returncode}").strip()
        return None if path.exists() else "PowerShell wrote no file"
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)


# ---------------------------------------------------------------------------
# Add/Remove Programs
# ---------------------------------------------------------------------------
#
# Under HKEY_CURRENT_USER, not HKEY_LOCAL_MACHINE: this installs for one user
# into their own profile and never asks for elevation, and an entry in the
# machine-wide list would claim otherwise -- and could not be removed later by
# the same unprivileged uninstaller that has to remove it.

def _registry_values(destination: Path, uninstaller: Path,
                     version: str) -> dict[str, tuple[str, object]]:
    size_kb = 0
    try:
        size_kb = sum(f.stat().st_size for f in destination.rglob("*")
                      if f.is_file()) // 1024
    except OSError:
        pass

    icon = destination / "ec7wolf.exe"
    return {
        "DisplayName": ("REG_SZ", APP_NAME),
        "DisplayVersion": ("REG_SZ", version or "1.0"),
        "Publisher": ("REG_SZ", PUBLISHER),
        "InstallLocation": ("REG_SZ", str(destination)),
        "UninstallString": ("REG_SZ", f'"{uninstaller}"'),
        "QuietUninstallString": ("REG_SZ", f'"{uninstaller}" --yes'),
        "DisplayIcon": ("REG_SZ", str(icon)),
        "EstimatedSize": ("REG_DWORD", size_kb),
        "NoModify": ("REG_DWORD", 1),
        "NoRepair": ("REG_DWORD", 1),
    }


def register_uninstall(destination: Path, uninstaller: Path, version: str,
                       reporter: Reporter) -> bool:
    """Put this install in Add/Remove Programs. False if it could not."""
    if not is_windows():
        return False
    values = _registry_values(destination, uninstaller, version)

    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg is not None:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
                for name, (kind, value) in values.items():
                    winreg.SetValueEx(
                        key, name, 0,
                        winreg.REG_DWORD if kind == "REG_DWORD" else winreg.REG_SZ,
                        value)
            reporter.detail(f"registered in Add/Remove Programs ({UNINSTALL_KEY})")
            return True
        except OSError as error:
            reporter.warn(
                f"could not register in Add/Remove Programs: {error}. The game "
                "is installed and works; it just will not be listed there, so "
                "remove it with Uninstall.cmd in the install folder.")
            return False

    # No winreg means this is not really Windows -- the gate, under Wine. reg.exe
    # is the same registry by a different door, and is also the honest fallback
    # on a Windows Python built without winreg.
    reg = shutil.which("reg")
    if reg is None:
        return False
    for name, (kind, value) in values.items():
        result = _run([reg, "add", "HKCU\\" + UNINSTALL_KEY, "/v", name,
                       "/t", kind, "/d", str(value), "/f"])
        if result.returncode != 0:
            reporter.warn(
                f"could not write {name} to the registry: "
                f"{(result.stderr or result.stdout).strip()}. The game is "
                "installed; it will not appear in Add/Remove Programs, so "
                "remove it with Uninstall.cmd in the install folder.")
            return False
    reporter.detail(f"registered in Add/Remove Programs ({UNINSTALL_KEY})")
    return True


def unregister_uninstall() -> bool:
    """Take the Add/Remove Programs entry away again."""
    if not is_windows():
        return False
    try:
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        except FileNotFoundError:
            pass
        return True
    except ImportError:
        pass

    reg = shutil.which("reg")
    if reg is None:
        return False
    _run([reg, "delete", "HKCU\\" + UNINSTALL_KEY, "/f"])
    return True


# DLLs Windows itself provides. Everything else has to be in the folder.
SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "comctl32.dll", "comdlg32.dll", "winmm.dll",
    "ws2_32.dll", "wsock32.dll", "imm32.dll", "version.dll", "setupapi.dll",
    "shlwapi.dll", "opengl32.dll", "dwmapi.dll", "uxtheme.dll", "msvcrt.dll",
    "rpcrt4.dll", "crypt32.dll", "bcrypt.dll", "iphlpapi.dll", "dbghelp.dll",
    "psapi.dll", "userenv.dll", "secur32.dll", "hid.dll", "cfgmgr32.dll",
    "msimg32.dll", "gdiplus.dll", "wintrust.dll", "ntdll.dll",
}


def imported_dlls(executable: Path) -> list[str]:
    """The DLLs a PE binary imports, read out of its import table.

    Parsed rather than grepped: the file is full of strings that look like DLL
    names and are not imports, and the question here is specifically what the
    loader will go looking for.
    """
    import struct
    blob = executable.read_bytes()
    if blob[:2] != b"MZ":
        return []                     # not a PE; nothing to check
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[pe:pe + 4] != b"PE\0\0":
        return []
    sections = struct.unpack_from("<H", blob, pe + 6)[0]
    optional_size = struct.unpack_from("<H", blob, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", blob, optional)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    import_rva, _size = struct.unpack_from("<II", blob, directories + 8)
    if not import_rva:
        return []

    table = []
    section_start = optional + optional_size
    for index in range(sections):
        entry = section_start + index * 40
        virtual = struct.unpack_from("<I", blob, entry + 12)[0]
        raw_size = struct.unpack_from("<I", blob, entry + 16)[0]
        raw_ptr = struct.unpack_from("<I", blob, entry + 20)[0]
        table.append((virtual, raw_size, raw_ptr))

    def offset(rva: int) -> int | None:
        for virtual, raw_size, raw_ptr in table:
            if virtual <= rva < virtual + raw_size:
                return raw_ptr + (rva - virtual)
        return None

    names, cursor = [], offset(import_rva)
    if cursor is None:
        return []
    while True:
        descriptor = blob[cursor:cursor + 20]
        if len(descriptor) < 20 or descriptor == b"\0" * 20:
            break
        name_rva = struct.unpack_from("<I", descriptor, 12)[0]
        at = offset(name_rva)
        if at is not None:
            end = blob.index(b"\0", at)
            names.append(blob[at:end].decode("ascii", "replace"))
        cursor += 20
    return names


def start_menu_directory() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_directory() -> Path:
    profile = os.environ.get("USERPROFILE")
    return (Path(profile) if profile else Path.home()) / "Desktop"


def exe_for_icon() -> str:
    """The file whose icon the shortcuts should wear."""
    return "ec7wolf.exe"
