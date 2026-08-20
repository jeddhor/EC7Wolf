# PyInstaller spec for EC7Wolf-Setup.exe.
#
# One file, because a setup program that arrives as a folder of DLLs is not one
# anybody will trust or keep hold of. The cost is a few seconds of unpacking to
# a temporary directory on each run, which for something run once is the right
# trade.
#
# Build it on Windows, or under Wine, with:
#
#     pyinstaller --clean --noconfirm installer/windows/ec7wolf-setup.spec
#
# and see installer/windows/build_setup.py, which does that and checks the
# result rather than assuming it.

import os
from pathlib import Path

# SPECPATH is set by PyInstaller; __file__ is not defined while a spec runs.
here = Path(SPECPATH).resolve()
repo = here.parent.parent

analysis = Analysis(
    [str(repo / "installer" / "ec7wolf-setup")],
    pathex=[str(repo / "installer"), str(repo / "tools")],
    binaries=[],
    datas=[
        # The licence is shown on a page of the wizard, so it has to travel
        # with it -- there is no source tree beside a frozen installer.
        (str(repo / "docs" / "license-gpl.txt"), "docs"),
        (str(repo / "docs" / "org.ec7wolf.EC7Wolf.metainfo.xml"), "docs"),
        (str(repo / "src" / "macosx" / "icon.iconset" / "icon_256x256.png"),
         "src/macosx/icon.iconset"),
        (str(repo / "src" / "posix" / "icon.svg"), "src/posix"),
        (str(repo / "src" / "posix" / "engine.desktop.in"), "src/posix"),
    ],
    hiddenimports=["c7disc", "ec7install", "ec7install_gui"],
    hookspath=[],
    runtime_hooks=[],
    # Qt is huge and most of it is unused: this installer draws widgets and
    # nothing else. Dropping the parts that cannot be reached takes the exe
    # from unreasonable to merely large.
    excludes=[
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtNetwork",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
        "tkinter", "unittest", "pydoc_data",
    ],
    noarchive=False,
)

# PyInstaller 6 dropped the cipher argument and the second positional one.
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="EC7Wolf-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A windowed build: no console flashing up behind the wizard. The CLI
    # installer stays a separate, console, script for anyone who wants one.
    console=False,
    disable_windowed_traceback=False,
    icon=str(repo / "src" / "win32" / "icon.ico")
         if (repo / "src" / "win32" / "icon.ico").is_file() else None,
    version=None,
)
