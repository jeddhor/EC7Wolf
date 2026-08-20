#!/bin/sh

# Regression test: desktop integration.
#
# The parts of an install that live outside its own folder -- the menu entry,
# the icons, the window's identity, and the uninstaller that has to take all of
# it away again. These fail quietly. A wrong StartupWMClass costs nothing at
# install time and shows up weeks later as a grey cog in the task manager that
# will not group with its launcher, and a desktop entry whose Exec is unquoted
# works perfectly until someone installs into a path with a space in it.
#
# So this gate installs into "My Games/EC7Wolf" deliberately, and measures the
# window class with xprop rather than trusting the string in the file.
#
# HOME is redirected throughout: a test that scattered icons and menu entries
# across the developer's own desktop would be its own bug report.
#
# Usage: test_installer_kde.sh [DATA_DIR]
#   DATA_DIR  a playable install (engine + .CO7 files), for the window class
#             measurement; without it that half is reported as not run.

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)
data=${1:-$repo/../builds/release}

work=$(mktemp -d /tmp/ec7wolf-kde.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
mkdir -p "$work/home"

# --- everything that needs no display --------------------------------------

HOME="$work/home" XDG_DATA_HOME="$work/home/.local/share" \
python3 - "$repo" "$work" <<'PY' || exit 1
import shlex, subprocess, sys
from pathlib import Path

repo, work = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo / "installer"))

from ec7install import identity, install, shortcuts
from ec7install.progress import Reporter

failures = []

def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)

# A space in the path, on purpose: this is the case that breaks Exec lines.
destination = work / "My Games" / "EC7Wolf"
destination.mkdir(parents=True)
(destination / "ec7wolf").write_text("#!/bin/sh\nexit 0\n")
(destination / "ec7wolf").chmod(0o755)

print("\nthe launcher")
launcher = install.write_launcher(destination)
check(launcher.exists() and launcher.stat().st_mode & 0o111, "it is executable")
body = launcher.read_text()
check(subprocess.run(["sh", "-n", str(launcher)]).returncode == 0,
      "it is valid shell")
check(f"SDL_VIDEO_X11_WMCLASS={identity.WM_CLASS}" in body,
      "it sets the X11 window class")
check(f"SDL_VIDEO_WAYLAND_WMCLASS={identity.WM_CLASS}" in body,
      "it sets the Wayland app id")
check("--savedir" in body and "--config" in body,
      "and still keeps config and saves inside the install")

print("\nthe desktop entry")
created = shortcuts.create(destination, launcher, repo, Reporter(),
                           menu=True, desktop=False)
entries = [p for p in created if p.suffix == ".desktop"]
check(len(entries) == 1, "one menu entry was written")
entry = entries[0]
check(entry.name == f"{identity.APP_ID}.desktop",
      "named for the application id, which is what the metainfo declares")

fields, actions = {}, {}
section = None
for line in entry.read_text().splitlines():
    if line.startswith("["):
        section = line.strip("[]")
    elif "=" in line and section:
        key, value = line.split("=", 1)
        (fields if section == "Desktop Entry" else
         actions.setdefault(section, {}))[key] = value

check(fields.get("StartupWMClass") == identity.WM_CLASS,
      f"StartupWMClass is {identity.WM_CLASS}")
check(fields.get("Icon") == identity.APP_ID, "the icon is asked for by id")
check(fields.get("Categories", "").endswith(";"),
      "the categories list has its trailing semicolon")
check("ActionGame" in fields.get("Categories", ""), "and says it is a game")
check(fields.get("Comment") == identity.APP_COMMENT,
      "the comment came from the project's own engine.desktop.in")

# The whole point of the quoting: the path has a space in it.
argv = shlex.split(fields.get("Exec", ""))
check(len(argv) == 1, f"Exec is one argument despite the space (got {argv})")
check(argv and Path(argv[0]) == launcher, "and it is the launcher")
check(argv and Path(argv[0]).exists(), "which exists")

check(len(actions) == 2, f"two right-click actions were written ({list(actions)})")
for name, action in actions.items():
    argv = shlex.split(action.get("Exec", ""))
    check(bool(action.get("Name")), f"{name} has a name")
    check(len(argv) >= 1, f"{name} has a runnable Exec")
    target = Path(argv[0] if argv[0] != "xdg-open" else argv[1])
    check(target.exists(), f"{name} points at something that exists")

validate = subprocess.run(["desktop-file-validate", str(entry)],
                          capture_output=True, text=True)
check(validate.returncode == 0,
      "desktop-file-validate is happy" +
      (f": {validate.stdout}{validate.stderr}" if validate.returncode else ""))

print("\nthe icons")
icons = [p for p in created if p.suffix in (".svg", ".png")]
check(len(icons) >= 2, f"icons were installed ({len(icons)})")
check(any(p.suffix == ".svg" for p in icons), "including the scalable one")
hicolor = Path.home() / ".local" / "share" / "icons" / "hicolor"
check(all(str(p).startswith(str(hicolor)) for p in icons),
      "all of them under the user's own hicolor theme")
check(all(p.stem == identity.APP_ID for p in icons),
      "all named for the application id")
check(all(p.exists() and p.stat().st_size > 0 for p in icons),
      "and none of them empty")

print("\nthe uninstaller")
uninstaller = install.write_uninstaller(destination, created)
check(uninstaller.exists(), "it was written into the install")
check(subprocess.run(["sh", "-n", str(uninstaller)]).returncode == 0,
      "it is valid shell")

saves = destination / "saves"
saves.mkdir(exist_ok=True)
(saves / "SAVE0.ec7").write_text("x")

refused = subprocess.run([str(uninstaller)], input="n\n",
                         capture_output=True, text=True)
check(refused.returncode != 0, "answering no leaves it alone")
check(destination.exists(), "and the install is still there")
check("saved game file in" in refused.stdout,
      "it warns that saved games are inside, with the right plural")

removed = subprocess.run([str(uninstaller), "--yes"],
                         capture_output=True, text=True)
check(removed.returncode == 0, f"--yes removes it ({removed.stderr.strip()})")
check(not destination.exists(), "the install is gone")
check(not any(p.exists() for p in created),
      "and so are the menu entry and the icons")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
PY

# --- what the window actually calls itself ---------------------------------
#
# The string in the desktop file is only right if the running game agrees with
# it, and nothing but a running game can say.

echo
echo "the window class, measured"

if [ ! -x "$data/ec7wolf" ]; then
	printf '  SKIP  no playable install at %s\n' "$data"
	exit 0
fi
for tool in Xvfb xdotool xprop; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		printf '  SKIP  %s is missing\n' "$tool"
		exit 0
	fi
done

. "$here/xvfb_common.sh"
wanted=$(python3 -c "import sys; sys.path.insert(0, '$repo/installer'); \
from ec7install import identity; print(identity.WM_CLASS)")

display=:129
xvfb_start "$display" "$work/xvfb.log" 640x480x24 || exit 1
trap 'kill ${game:-0} 2>/dev/null; xvfb_stop; rm -rf "$work"' EXIT INT TERM

DISPLAY=$display SDL_VIDEODRIVER=x11 \
	SDL_VIDEO_X11_WMCLASS="$wanted" \
	HOME="$work/home" \
	"$data/ec7wolf" --data CO7 --config "$work/home/probe.cfg" \
	>"$work/game.log" 2>&1 &
game=$!

window=
i=0
while [ $i -lt 150 ]; do
	window=$(DISPLAY=$display xdotool search --onlyvisible --name . 2>/dev/null | head -1 || true)
	[ -n "$window" ] && break
	kill -0 "$game" 2>/dev/null || break
	i=$((i + 1))
	sleep 0.2
done

if [ -z "$window" ]; then
	printf '  FAIL  the game never opened a window\n'
	tail -5 "$work/game.log" || true
	exit 1
fi

class=$(DISPLAY=$display xprop -id "$window" WM_CLASS 2>/dev/null || true)
kill "$game" 2>/dev/null || true

printf '  %s\n' "$class"
if printf '%s' "$class" | grep -q "\"$wanted\", \"$wanted\""; then
	printf '  ok   the window announces itself as %s, matching StartupWMClass\n' "$wanted"
	exit 0
fi
printf '  FAIL  the window class is not %s, so the taskbar will not pair it\n' "$wanted"
printf '        with the desktop entry\n'
exit 1
