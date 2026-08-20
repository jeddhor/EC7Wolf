#!/bin/sh

# Regression test: the Windows half of the installer, run under Wine.
#
# Every other platform's code gets exercised by the gates on the machine that
# runs them; the Windows path used to be the one part that was only reasoned
# about. Wine changes that. The installer's platform decision goes through
# identity.host_platform(), which EC7WOLF_INSTALL_PLATFORM can force, so the
# code takes every Windows branch for real -- writes EC7Wolf.cmd, asks a
# scripting host for .lnk files, writes the Add/Remove Programs keys -- and the
# Windows programs it shells out to are answered by Wine.
#
# One adapter is needed and is honest: cscript will not accept a POSIX path for
# the script file to run, and on Windows that argument is a Windows path
# already because Python's paths are. The shims below translate with winepath,
# which is exactly the difference between the costume and the real thing.
# Nothing else is faked: the .lnk files are written by Wine's own IShellLink,
# and read back here by parsing the shell-link format.
#
# The prefix is cached under ~/.cache, because building one costs 9 seconds and
# 1.2 GB and neither belongs in every run. EC7WOLF_WINEPREFIX overrides it, and
# deleting the directory is all it takes to start clean.
#
# Usage: test_installer_windows.sh [DISC]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)

if ! command -v wine >/dev/null 2>&1; then
	printf 'SKIP: wine is not installed\n'
	exit 0
fi
if ! command -v winepath >/dev/null 2>&1; then
	printf 'SKIP: winepath is not installed\n'
	exit 0
fi

disc=${1:-${CORRIDOR7_DISC:-}}
if [ -z "$disc" ]; then
	for candidate in "$repo/../corr7/Corridor7.cue" "$repo/../corr7/corridor7.cue"; do
		[ -f "$candidate" ] && { disc=$candidate; break; }
	done
fi

work=$(mktemp -d /tmp/ec7wolf-win.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

# --- the prefix ------------------------------------------------------------

prefix=${EC7WOLF_WINEPREFIX:-${XDG_CACHE_HOME:-$HOME/.cache}/ec7wolf-gate-wine}
mkdir -p "$(dirname "$prefix")"
export WINEPREFIX="$prefix"
export WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="

if [ ! -d "$prefix/drive_c" ]; then
	printf 'preparing a Wine prefix in %s (once; about 9s)\n' "$prefix"
	if ! wine cmd /c exit >"$work/wineboot.log" 2>&1; then
		printf 'SKIP: could not create a Wine prefix\n'
		grep -v dbus "$work/wineboot.log" | tail -3
		exit 0
	fi
fi

profile=$(ls -d "$prefix"/drive_c/users/*/ 2>/dev/null | grep -v Public | head -1)
if [ -z "$profile" ]; then
	printf 'SKIP: the Wine prefix has no user profile\n'
	exit 0
fi
profile=${profile%/}

# --- the shims -------------------------------------------------------------

mkdir -p "$work/bin"
for tool in cscript reg; do
	cat > "$work/bin/$tool" <<SHIM
#!/bin/sh
# Answer a Windows program name with Wine, translating POSIX path arguments to
# Windows paths -- which is what they would already be on Windows.
count=\$#
index=0
while [ \$index -lt \$count ]; do
	argument=\$1
	shift
	case "\$argument" in
		/*) [ -e "\$argument" ] && argument=\$(winepath -w "\$argument" 2>/dev/null || printf '%s' "\$argument") ;;
	esac
	set -- "\$@" "\$argument"
	index=\$((index + 1))
done
exec wine $tool "\$@"
SHIM
	chmod +x "$work/bin/$tool"
done

# --- a stand-in for the engine ---------------------------------------------
#
# The installer does not build the engine here: what is under test is what
# happens around it. A real Windows binary is still worth having, because it
# lets the generated launcher actually be run.

mingw=$(command -v x86_64-w64-mingw32-gcc || command -v i686-w64-mingw32-gcc || true)
mkdir -p "$work/engine"
if [ -n "$mingw" ]; then
	cat > "$work/engine/stub.c" <<'C'
#include <stdio.h>
int main(int argc, char **argv)
{
	int i;
	printf("EC7WOLF-STUB-RAN");
	for (i = 1; i < argc; i++)
		printf(" %s", argv[i]);
	printf("\n");
	return 0;
}
C
	"$mingw" -o "$work/engine/ec7wolf.exe" "$work/engine/stub.c" 2>/dev/null || mingw=""
fi
# A stub that imports a DLL of its own, so the "is every library here?" check
# has something real to find. The engine stub imports nothing but system DLLs,
# which is correct and therefore proves nothing.
if [ -n "$mingw" ]; then
	printf 'int helper(void) { return 1; }\n' > "$work/engine/helper.c"
	printf 'int helper(void);\nint main(void) { return helper(); }\n' \
		> "$work/engine/needy.c"
	( cd "$work/engine" && \
	  "$mingw" -shared -o helper.dll helper.c -Wl,--out-implib,libhelper.a && \
	  "$mingw" -o needy.exe needy.c -L. -lhelper ) 2>/dev/null || true
fi

if [ -z "$mingw" ] || [ ! -f "$work/engine/ec7wolf.exe" ]; then
	printf 'note: no MinGW cross-compiler; the launcher will not be run\n'
	printf 'placeholder' > "$work/engine/ec7wolf.exe"
	mingw=""
fi
printf 'placeholder pk3' > "$work/engine/ec7wolf.pk3"

export EC7WOLF_INSTALL_PLATFORM=windows
export PATH="$work/bin:$PATH"
export USERPROFILE="$profile"
export APPDATA="$profile/AppData/Roaming"
export LOCALAPPDATA="$profile/AppData/Local"

python3 - "$repo" "$work" "$disc" "$mingw" <<'PY'
import os, subprocess, sys, time
from pathlib import Path

repo, work = Path(sys.argv[1]), Path(sys.argv[2])
disc, mingw = sys.argv[3], sys.argv[4]
sys.path.insert(0, str(repo / "installer"))
sys.path.insert(0, str(repo / "tools"))

from ec7install import build, identity, install, shortcuts, windows
from ec7install.progress import Reporter

failures = []

def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)

def wine(*arguments, timeout=180):
    return subprocess.run(["wine", *arguments], capture_output=True, text=True,
                          timeout=timeout, errors="replace")

# ---------------------------------------------------------------------------
# Reading a .lnk back, since Wine's WScript.Shell can write one but not load one
# ---------------------------------------------------------------------------

def read_lnk(path: Path) -> dict:
    """Parse the parts of a shell link this installer sets. [MS-SHLLINK]"""
    import struct
    blob = path.read_bytes()
    if len(blob) < 0x4C or struct.unpack_from("<I", blob, 0)[0] != 0x4C:
        raise ValueError("not a shell link: bad header size")
    if blob[4:20] != bytes.fromhex("0114020000000000C000000000000046"):
        raise ValueError("not a shell link: bad class id")

    flags = struct.unpack_from("<I", blob, 0x14)[0]
    unicode_strings = bool(flags & 0x80)
    offset = 0x4C

    if flags & 0x01:                                  # HasLinkTargetIDList
        offset += 2 + struct.unpack_from("<H", blob, offset)[0]

    result = {"flags": flags, "target": None}
    if flags & 0x02:                                  # HasLinkInfo
        start = offset
        size, header_size = struct.unpack_from("<II", blob, start)
        base_offset = struct.unpack_from("<I", blob, start + 16)[0]
        if base_offset:
            end = blob.index(b"\x00", start + base_offset)
            result["target"] = blob[start + base_offset:end].decode(
                "mbcs" if os.name == "nt" else "latin-1")
        offset = start + size

    def string() -> str:
        nonlocal offset
        count = struct.unpack_from("<H", blob, offset)[0]
        offset += 2
        width = 2 if unicode_strings else 1
        raw = blob[offset:offset + count * width]
        offset += count * width
        text = raw.decode("utf-16-le" if unicode_strings else "latin-1")
        return text.rstrip("\x00")

    for bit, name in ((0x04, "description"), (0x08, "relative_path"),
                      (0x10, "working_directory"), (0x20, "arguments"),
                      (0x40, "icon")):
        result[name] = string() if flags & bit else None
    return result

# ---------------------------------------------------------------------------

engine = build.Engine(work / "engine" / "ec7wolf.exe",
                      work / "engine" / "ec7wolf.pk3", "stub for the gate")

print("\nwhere Windows puts things")
check(identity.host_platform() == "windows", "the Windows branch is in force")
check(identity.exe_name() == "ec7wolf.exe", "the engine is looked for as an .exe")
destination = install.default_destination()
check("AppData" in str(destination) and "Local" in str(destination),
      f"the default install goes under LOCALAPPDATA ({destination})")
check(str(windows.start_menu_directory()).endswith("Start Menu/Programs"),
      "the menu shortcut goes to the Start Menu")

print("\nthe launcher")
target = work / "install"
target.mkdir()
for name in ("ec7wolf.exe", "ec7wolf.pk3"):
    (target / name).write_bytes((work / "engine" / name).read_bytes())
launcher = install.write_launcher(target)
check(launcher.name == "EC7Wolf.cmd", "it is a .cmd, not a shell script")
body = launcher.read_text()
raw = launcher.read_bytes()
check(raw.count(b"\r\n") > 0 and raw.count(b"\n") == raw.count(b"\r\n"),
      "every line ends CRLF, which is what cmd wants")
check(b"\r\r\n" not in raw,
      "and none of them doubled, which text-mode writing would have done")
check("--data CO7" in body and "--savedir" in body,
      "and it keeps config and saves inside the install")

if mingw:
    ran = wine("cmd", "/c", str(launcher))
    check("EC7WOLF-STUB-RAN" in ran.stdout,
          f"cmd actually runs it and it reaches the engine ({ran.stdout.strip()[:60]})")
    check("--data CO7" in ran.stdout,
          "passing the arguments the engine needs through to it")
else:
    print("  ..     skipped running it: no MinGW cross-compiler")

print("\nan engine found in a folder brings its DLLs with it")
# What an unpacked release archive looks like: the engine, its pk3, and the
# libraries it loads at run time. Taking only the first two produced an install
# that could not start, which is how a user found this.
release = work / "unpacked-release"
release.mkdir(exist_ok=True)
for name in ("ec7wolf.exe", "ec7wolf.pk3"):
    (release / name).write_bytes((work / "engine" / name).read_bytes())
for name in ("SDL2.dll", "SDL2_mixer.dll", "SDL2_net.dll", "libepoxy-0.dll"):
    (release / name).write_bytes(b"pretend library")

found = build.find_existing(work / "nowhere", extra=[release])
check(found is not None, "the engine in the folder is found")
if found is not None:
    carried = sorted(Path(p).name for p in found.extra_files)
    check(carried == ["SDL2.dll", "SDL2_mixer.dll", "SDL2_net.dll",
                      "libepoxy-0.dll"],
          f"and carries every DLL beside it ({carried})")

print("\nan install missing a DLL is reported, not shipped")
from ec7install import verify
needy = work / "engine" / "needy.exe"
helper = work / "engine" / "helper.dll"
if needy.is_file() and helper.is_file():
    bare = work / "bare-install"
    bare.mkdir(exist_ok=True)
    (bare / "needy.exe").write_bytes(needy.read_bytes())
    check(verify._missing_libraries(bare) == ["helper.dll"],
          "a binary whose DLL is not beside it is flagged by name")

    (bare / "helper.dll").write_bytes(helper.read_bytes())
    check(verify._missing_libraries(bare) == [],
          "and is not flagged once the DLL is there")

    # The engine stub imports only system DLLs, so it must NOT be flagged --
    # a check that cannot tell those apart would fail every install.
    system_only = work / "system-only"
    system_only.mkdir(exist_ok=True)
    (system_only / "ec7wolf.exe").write_bytes(
        (work / "engine" / "ec7wolf.exe").read_bytes())
    check(verify._missing_libraries(system_only) == [],
          "a binary needing only Windows' own DLLs is left alone")
else:
    print("  ..     skipped: no MinGW to build a binary that imports a DLL")

print("\nthe shortcuts, made by Wine's own IShellLink")
created = shortcuts.create(target, launcher, repo, Reporter(),
                           menu=True, desktop=True)
links = [p for p in created if p.suffix == ".lnk"]
check(len(links) == 2, f"a Start Menu and a desktop shortcut ({len(links)})")
for link in links:
    check(link.exists() and link.stat().st_size > 100,
          f"{link.name} was written to {link.parent.name}")

if links:
    parsed = read_lnk(links[0])
    # PureWindowsPath, because the target is written the way Windows writes
    # paths and Path() here is a POSIX one, to which a backslash is just a
    # character in a filename.
    from pathlib import PureWindowsPath
    check(parsed["target"] is not None and
          PureWindowsPath(parsed["target"]).name == "EC7Wolf.cmd",
          f"its target is the launcher ({parsed['target']})")
    check(parsed["description"] == identity.APP_COMMENT,
          f"the description survived ({parsed['description']!r})")
    check(parsed["working_directory"] is not None and
          "install" in parsed["working_directory"],
          f"so did the working directory ({parsed['working_directory']!r})")
    check(parsed["flags"] & 0x01, "it carries a target id list, as Windows expects")

print("\nAdd/Remove Programs")
# The shortcut paths are handed to the uninstaller the way Windows would hand
# them over -- as Windows paths. Here they arrive as POSIX ones because Python
# is running on Linux, and cmd's del cannot do anything with those. Translating
# them is the same adapter the cscript shim applies, and it means the del lines
# below are tested for real rather than merely written.
def to_windows(path: Path) -> Path:
    converted = subprocess.run(["winepath", "-w", str(path)],
                               capture_output=True, text=True, timeout=60)
    return Path(converted.stdout.strip() or str(path))

uninstaller = install.write_uninstaller(target, [to_windows(p) for p in created])
check(uninstaller.name == "Uninstall.cmd", "an Uninstall.cmd was written")
check("--yes" in uninstaller.read_text(),
      "which honours --yes, as QuietUninstallString promises")

registered = windows.register_uninstall(target, uninstaller, "1.5pre-test",
                                        Reporter())
check(registered, "the registry entry was written")
listing = wine("reg", "query", "HKCU\\" + identity.UNINSTALL_KEY)
check(listing.returncode == 0, "and Windows can read it back")
for value in ("DisplayName", "UninstallString", "QuietUninstallString",
              "InstallLocation", "Publisher", "DisplayVersion", "NoModify"):
    check(value in listing.stdout, f"  {value} is set")
check("EC7Wolf" in listing.stdout, "under the name a user would recognise")
check("1.5pre-test" in listing.stdout, "with the version read out of the binary")

print("\nuninstalling")
removal = wine("cmd", "/c", str(uninstaller), "--yes")
check(removal.returncode == 0, f"Uninstall.cmd ran ({removal.stdout.strip()[:60]})")

deadline = time.time() + 20
while time.time() < deadline and target.exists():
    time.sleep(0.5)

check(not any(link.exists() for link in links), "the shortcuts are gone")
gone = wine("reg", "query", "HKCU\\" + identity.UNINSTALL_KEY)
check(gone.returncode != 0, "the Add/Remove Programs entry is gone")
check(not target.exists(),
      "and so is the install folder" +
      ("" if not target.exists() else
       f" (still holds {[p.name for p in target.iterdir()]})"))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
PY
