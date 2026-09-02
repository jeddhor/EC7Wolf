# The EC7Wolf installer

A graphical installer for Windows and KDE that takes someone from "I own the
Corridor 7 CD" to "the game is in my menu", including compiling the engine if
they have not already.

## What it has to do

1. Use an engine the user already built, if there is one.
2. Otherwise scan for what building needs, name what is missing **and where to
   get it**, and build automatically once nothing is.
3. Show ordinary progress, with a detail pane that shows the compiler output
   live for anyone who wants to watch it.
4. Take the game data from a CD in a drive, or a BIN/CUE from the Steam/GOG
   release, or an existing installed folder.
5. Extract the data files, rip the music, extract the cinematics, and put them
   with the engine in a folder of the user's choosing.
6. Offer a desktop icon and a menu entry.

## What a good installer also has, which is therefore in scope

* A **license page**. The engine is GPL, and the vendored xBRZ makes the binary
  GPL-3; that is not optional decoration.
* An **ownership notice**. Nothing commercial is redistributed and the installer
  only ever copies from the user's own disc. Saying so is honest and it also
  tells the user why they are being asked for a CD.
* **Nothing is written until the user confirms.** A summary page listing every
  action, then a staging directory that is moved into place atomically — which
  is what `tools/package_corridor7_release.sh` already does, for the same
  reason. Canceling half way leaves nothing behind.
* **A disk-space check** before starting, because the cinematics alone are 27 MB
  and a build tree is far more.
* **A log file**, always written, shown on failure, with a button that opens the
  folder holding it. An installer that fails without saying why is worthless.
* **A verification pass**: every required file present, the executable the
  expected 250,776 bytes, each cinematic a valid FLC whose header length matches
  the file. The rip is the step most likely to go wrong quietly.
* **An uninstaller**, registered in Add/Remove Programs on Windows and removing
  the desktop entry on Linux.
* **Re-run detection** — upgrade, repair, or remove an existing install rather
  than stacking a second one.
* **An unattended mode** (`--silent` with an answer file), so this can be
  scripted.
* **No administrator rights.** The default target is under the user's home; the
  installer never needs to elevate.
* **Launch on finish**, as a checkbox.

Out of scope for now: translations, and any form of network download. The
installer never fetches anything; it tells the user where to go and waits.

## Two decisions worth arguing for

**Qt (PySide6), one codebase, both platforms.** KDE *is* Qt, so a Qt installer
is native there rather than merely tolerable, and Qt looks right on Windows too.
The alternative — Inno Setup or NSIS on Windows and something else on KDE —
means two implementations of the same logic, and the interesting logic here
(dependency scanning, disc extraction, a live build) is exactly the part that
must not diverge. On Windows the whole thing is frozen with PyInstaller into a
single `EC7Wolf-Setup.exe`, because telling a Windows user to install Python
first would be absurd. On Linux it runs from source and asks for the distro's
PySide6 package if it is missing.

**A headless core with a thin GUI on top.** Everything that does work —
scanning, extracting, ripping, building, installing, shortcut creation,
verification — lives in a package with no Qt import at all, driven through a
progress interface. The GUI is a face on it, and a command-line front end drives
the same code.

This is not architectural neatness for its own sake. It is what makes the
installer *gateable*: this project's rule is that anything that can break gets a
test, and a GUI is the one thing that cannot be tested headlessly. Putting the
correctness in a library means the gates can drive a complete install end to end
in CI, and what the GUI adds on top is layout.

## Phases

### Phase 1 — the core, and a CLI that can already do the job — **done**

`installer/ec7install/`, no Qt anywhere:

* `tools/c7disc.py` — a game-data source: a CD device, an ISO, a BIN/CUE, or a
  folder. Promotes the ISO9660 walker in `tools/extract_c7_video.py` into
  something that can list and extract *any* file, since it already does the hard
  part. It lives in `tools/` rather than inside the package because
  `extract_c7_video.py` uses it too, and one reader with one set of bugs is
  worth more than two.
* `deps.py` — dependency scan for building and for ripping, per platform, each
  missing item carrying a human remedy (the distro package, the download page).
* `build.py` — configure and build, streaming output line by line to a callback,
  cancelable.
* `install.py` — the layout, the staging directory, the atomic move, the
  manifest that the uninstaller later reads.
* `verify.py` — the post-install check.
* `plan.py` — the ordered steps, with progress weights, so a front end can show
  one bar without knowing what the steps are.
* `ec7wolf-install` — a CLI front end that performs a complete install.

Exit gate: a headless end-to-end install from a disc image into a temp
directory, verified, gated, and runnable without game data present (the gate
skips what it cannot do, as the suite already does).

### Phase 2 — the Qt shell — **done**

`installer/ec7install_gui/`, and `installer/ec7wolf-setup` to start it. A
QWizard, because an installer *is* a wizard and Qt already knows how one behaves
— a commit page whose button reads *Install*, no way back once it is writing,
Next disabled until the page has an answer it can act on.

* `worker.py` — the thread boundary, and the only place the two threads meet.
  `Bridge` owns the signals, `GuiReporter` is a plain `Reporter` that emits
  them, `InstallThread` runs one plan and reports every outcome — including the
  exceptions — through a single signal.
* `pages.py` — `State` plus the nine pages. Pages read and write that one
  object rather than QWizard's field registry, so the summary and the plan are
  built from exactly the thing the pages set.
* `wizard.py` — assembly, the icon, and `reject()`: Cancel, Escape and the
  window's close button all arrive there, and an install in flight is handed to
  the worker instead of closing the window out from under it.

The reporter is deliberately not a QObject. Mixing Qt's metaclass into the
`Reporter` hierarchy buys nothing and can only cause trouble, so the Qt half
lives in a separate object it holds.

Progress is throttled at the reporter: a compile reports progress per file, and
forwarding every one of those posts thousands of events that all resolve to the
same pixel. Detail lines are not throttled — they are the point of the pane —
but the pane keeps only the last 4000, because a full build is tens of thousands
of lines and keeping them all costs more memory than the build.

**Gate:** `tools/test_installer_gui.sh`, in the data-free set. It drives the
real wizard on Qt's offscreen platform — no display needed, and nothing thrown
onto a developer's screen mid-run. It checks the thread crossing (100 detail
lines arrive in order, progress never goes backwards and is throttled), page
order, and each page's validation; then it runs two *actual* installs through
the window, one to completion and one canceled part way, because the worker,
the progress display and the Cancel button cannot be judged from a static page.

Two bugs it caught, both of which would have shipped:

* `OptionsPage.initializePage` set the music checkbox first, which emitted
  `toggled`, which wrote the whole state back from the video checkbox that had
  not been set yet — so the next line read the False it had just caused and
  silently unticked the cinematics. Fixed by reading every wanted value out of
  the state before touching a widget.
* `audio.rip` polled for cancellation only *between* tracks. Cancel is what
  makes that reachable, and the longest track on the disc is ten minutes, so the
  window could have sat on "Canceling…" for that long. It now polls inside the
  streaming loop, and the gate holds it to stopping within 30 seconds of being
  asked. Measured: 0.3.

Advancing pages in the gate clicks the button rather than calling
`QWizard.next()`, which is a slot and moves whether or not the page says it is
complete. Only the button respects `isComplete()`, so only the button proves the
guard is real.

### Phase 3 — KDE integration — **done**

The parts of an install that live *outside* its own folder, which are the parts
that fail quietly.

**One identity, in `identity.py`.** `org.ec7wolf.EC7Wolf` — the project's own
AppStream id, whose `<launchable>` in
`docs/org.ec7wolf.EC7Wolf.metainfo.xml` already names
`org.ec7wolf.EC7Wolf.desktop`. The desktop file's name, the icon's name, the
window's class and that metadata are one fact, and they are now written down
once. When two of them disagree the symptom is silent, which is exactly why
they were worth centralising.

**The window class was wrong, and measuring is the only way to know.** The
entry said `StartupWMClass=EC7Wolf`. Run under Xvfb and read back with `xprop`,
the engine actually announces:

    WM_CLASS(STRING) = "ec7wolf", "ec7wolf"

SDL takes the class from `argv[0]` unless told otherwise, so it matched neither
the old string nor the desktop file. A task manager that cannot pair a window
with its entry falls back to a gray cog and refuses to group the two — at no
cost on install day. The launcher now exports `SDL_VIDEO_X11_WMCLASS` and
`SDL_VIDEO_WAYLAND_WMCLASS` (the Wayland one matters on Plasma 6, where the app
id is matched against the desktop file's name), and the measurement is a gate.

**The entry is derived from `src/posix/engine.desktop.in`**, as the module's
docstring always claimed but the code did not do — name, comment and categories
come from the file the ECWolf packaging uses, so an installed EC7Wolf and a
packaged one cannot drift. Two things are corrected on the way through:
`Categories=Game` gains the trailing semicolon the spec requires, and `Exec` is
quoted. That last one is not decoration — the default path has no spaces, but
installing into `~/My Games/EC7Wolf` would otherwise produce an entry that
launches nothing at all, because the desktop reads `Exec` as a command line and
splits on whitespace. The gate installs into a path with a space for exactly
this reason.

Also: right-click actions (*Play fullscreen*, *Open the install folder*), both
using flags checked against `--help` rather than invented; and the icon
installed to the user's own hicolor theme as the scalable SVG plus the five
raster sizes the project already ships.

**An uninstaller that lives in the install.** The CLI could already uninstall,
but only from a checkout of the source tree, and someone who installed a game a
year ago has no reason to still have one. `uninstall.sh` sits in the install
folder with the shortcut list baked in — the plan knows exactly what it
created, and a shell script that has to parse JSON to decide what to delete is
a script waiting to delete the wrong thing. It names everything it will remove,
warns when saved games are inside it, and does nothing without a yes or
`--yes`.

**Gate:** `tools/test_installer_kde.sh`, in the data-free set. 38 checks over
the launcher, the entry, the icons and the uninstaller; then, when a playable
install is present, it starts the engine under Xvfb and reads `WM_CLASS` back
with `xprop`, because the string in the desktop file is only right if the
running game agrees with it, and nothing but a running game can say.

### Phase 4 — Windows — **done**

The Windows path used to be the one part of the installer that was only
reasoned about. It is now run, in full, by a gate — under Wine.

**How the Windows code gets exercised on Linux.** Every platform decision goes
through `identity.host_platform()`, which `EC7WOLF_INSTALL_PLATFORM` can force.
The gate forces `windows` and the code takes every Windows branch for real: it
writes `EC7Wolf.cmd`, asks a scripting host for `.lnk` files, writes the
Add/Remove Programs values. The Windows programs it shells out to — `cscript`,
`reg` — are answered by Wine. One adapter is needed and is honest: `cscript`
will not accept a POSIX path for the script file to run, and on Windows that
argument is a Windows path already, because Python's paths are. The shim
translates it with `winepath`. Nothing else is faked — the `.lnk` files are
written by Wine's own `IShellLink` and read back by parsing the shell-link
format, and the registry is Wine's real registry.

**A .lnk is not written by hand.** It is a binary structure whose target is
normally a serialised walk of the shell namespace, and a hand-rolled one works
on the machine it was written on and fails quietly elsewhere. Windows has an
implementation; this asks it. The request goes through `cscript` rather than
PowerShell: both drive `WScript.Shell`, but cscript has shipped since Windows
2000, starts far faster, and is not subject to PowerShell's execution policy —
which is `Restricted` by default on client Windows and is an ordinary reason
for a working script to refuse to run. PowerShell stays as the fallback for the
locked-down case where WSH itself is off. (Wine has no PowerShell at all, which
is how the fallback ordering got tested.)

**Compiler detection was wrong before it was tested.** The scan looked for
`cl.exe` on the `PATH` — where it never is, outside a Developer Command Prompt.
A machine with a perfectly good Visual Studio would have been told to install
the compiler it already had. It now asks `vswhere.exe`, which Microsoft puts at
a fixed path on every machine with VS 2017 or later, and accepts MinGW too.
The remedies lead with `winget` one-liners.

**Multi-config generators.** A Visual Studio generator ignores
`CMAKE_BUILD_TYPE`, defaults to a 32-bit build, and puts its output in
`Release\` rather than the build root. All three are now handled; with Ninja
present, none of them apply and nothing changes.

**Add/Remove Programs** under `HKEY_CURRENT_USER`, not `HKEY_LOCAL_MACHINE`:
this installs into one user's profile and never elevates, and a machine-wide
entry would both claim otherwise and be unremovable by the same unprivileged
uninstaller that has to remove it. `winreg` where it exists, `reg.exe`
otherwise — which is what lets Wine exercise it.

**The frozen `EC7Wolf-Setup.exe`.** `installer/windows/ec7wolf-setup.spec` and
`build_setup.py`. One file, because a setup program that arrives as a folder of
DLLs is not one anyone keeps hold of. A frozen installer carries the wizard but
not the engine's source, so it looks for `ec7wolf.exe` beside itself and, when
there is nothing to compile and nothing to run, says exactly that instead of
sending the user off to install CMake for no reason.

**What Wine can and cannot do.** It runs the installer's Windows logic
completely, and that is where the value is. It cannot run the *wizard*:
`Qt6Core.dll` imports `icuuc.dll`, which Windows 10 and 11 provide in System32
and which Wine does not implement, so PySide6 will not load in a Wine prefix at
all — frozen or not. That was worth pinning down rather than guessing, because
the symptom (`ImportError: DLL load failed while importing QtCore`) looks
exactly like a bad PyInstaller spec. `build_setup.py` recognizes it and says so.
The frozen executable is therefore checked on a real `windows-latest` runner in
CI, which builds it and runs `EC7Wolf-Setup.exe --selftest`: the self-test
constructs every page offscreen and reports by exit code, because a windowed
executable has no console and anything it prints may go nowhere.

**Gate:** `tools/test_installer_windows.sh`, in the data-free set, skipped
where Wine is absent. It checks where Windows puts things, runs the generated
`EC7Wolf.cmd` under `cmd` and confirms the arguments reach the engine, creates
both shortcuts and parses them back, reads the registry values through Windows
itself, then runs `Uninstall.cmd --yes` and confirms the shortcuts, the
registry entry and the folder are all gone. The Wine prefix is cached under
`~/.cache/ec7wolf-gate-wine`, because building one costs 9 seconds and 1.2 GB
and neither belongs in every run.

Two bugs it caught:

* `EC7Wolf.cmd` and `Uninstall.cmd` were written with `write_text`, which opens
  in text mode — on Windows, the only place those files are ever used, every
  `\n` becomes `\r\n`, so the `\r\n` pairs already in the string would have
  been written as `\r\r\n`. It looked correct on Linux, where nothing is
  translated. They are written with `write_bytes` now.
* The registry advertised a `QuietUninstallString` of `"Uninstall.cmd" --yes`,
  and `Uninstall.cmd` ignored its arguments entirely — so anything that used
  the quiet path would have sat waiting for a keypress nobody was there to
  give. It honors `--yes` and `/S` now.

### Phase 5 — hardening — **done**

**It was deleting saved games.** `Staging.commit` renamed the existing install
aside and then `shutil.rmtree`'d it — saves and settings with it — while the
destination page told the user, in as many words, that saved games would be
kept. Nothing had caught it because nothing had ever installed twice. The
launcher deliberately keeps config and saves *inside* the install folder, which
is exactly what put them in the path of replacing it.

`Staging.carry_over` now copies `saves/` and `ec7wolf.cfg` into the staging
tree *before* anything is moved or deleted, so a failure at that point costs
nothing: the old install is still standing. If the copy fails it refuses to go
on, because quietly losing someone's saved games is worse than stopping.

**Reinstall or remove, and deliberately not a third thing.** A wizard that
finds an install where one would go now says so and offers two actions.
Conventional installers offer Upgrade, Repair and Modify as well — here all
three would do the same work, because this installer always writes everything,
and three buttons with one behavior is theater. The page is skipped entirely
when there is nothing installed, and choosing *Remove* goes straight to the
summary: no disc to pick, no engine to find, no options to set. `RemovalPlan`
wears the same `run(reporter) -> Path` shape as `InstallPlan`, so the worker
thread, the progress bar, Cancel and the finish page all work on it unchanged.

**Unattended.** `ec7wolf-setup --unattended --source … --dest …`, and
`--remove DIR`, with no window at all; `/S` is accepted as the alias Windows
deployment tools reach for first. Results come back as exit codes (1 the
arguments do not describe an install, 2 the source is unusable, 3 the install
failed) because a frozen Windows executable is windowed and has no console to
print to. The log is written whatever happens.

**Resuming.** The compile already resumed — CMake's build tree outlives a
failure — so the gap was the soundtrack, the longest step after it. Tracks are
now encoded into a cache under a `.part` name and renamed only once FFmpeg has
finished, so a file that exists is a file that is complete and a later run
copies it rather than spending another minute on it. The cache is deleted after
a *successful* install: it exists to make the next attempt cheaper, not to
leave 40 MB of ogg files in someone's home directory forever. Writing to a
`.part` name also turned up a bug of its own — FFmpeg picks its muxer from the
file extension, so the container is now named explicitly with `-f ogg`.

**Every message that a user can read** was reviewed against one question: does
it say what to do next? Ten did not. "CMake is not installed" now carries the
command for this distribution; "could not create shortcuts" now says the game
is installed and where to start it; the uninstaller's refusal now names the
manifest it looked for and why it would rather stop than delete the wrong
folder.

**Gate:** `tools/test_installer_lifecycle.sh`. Everything before it covered
installing onto a clean machine; this covers the rest of the life — installing
again over the top and checking the saves byte for byte, a reinstall that fails
part way and must not take them with it, an interrupted rip resumed, removal,
removal refused on a directory the installer did not create, and the unattended
front end driven as a deployment tool would drive it.
