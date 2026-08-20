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

* A **licence page**. The engine is GPL, and the vendored xBRZ makes the binary
  GPL-3; that is not optional decoration.
* An **ownership notice**. Nothing commercial is redistributed and the installer
  only ever copies from the user's own disc. Saying so is honest and it also
  tells the user why they are being asked for a CD.
* **Nothing is written until the user confirms.** A summary page listing every
  action, then a staging directory that is moved into place atomically — which
  is what `tools/package_corridor7_release.sh` already does, for the same
  reason. Cancelling half way leaves nothing behind.
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
  cancellable.
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
the window, one to completion and one cancelled part way, because the worker,
the progress display and the Cancel button cannot be judged from a static page.

Two bugs it caught, both of which would have shipped:

* `OptionsPage.initializePage` set the music checkbox first, which emitted
  `toggled`, which wrote the whole state back from the video checkbox that had
  not been set yet — so the next line read the False it had just caused and
  silently unticked the cinematics. Fixed by reading every wanted value out of
  the state before touching a widget.
* `audio.rip` polled for cancellation only *between* tracks. Cancel is what
  makes that reachable, and the longest track on the disc is ten minutes, so the
  window could have sat on "Cancelling…" for that long. It now polls inside the
  streaming loop, and the gate holds it to stopping within 30 seconds of being
  asked. Measured: 0.3.

Advancing pages in the gate clicks the button rather than calling
`QWizard.next()`, which is a slot and moves whether or not the page says it is
complete. Only the button respects `isComplete()`, so only the button proves the
guard is real.

### Phase 3 — KDE integration

`.desktop` entry from the existing `src/posix/engine.desktop.in`, the existing
`src/posix/icon.svg`, menu and desktop icons, the uninstaller, and a launcher
that keeps config and saves with the install.

### Phase 4 — Windows

MSVC and MinGW detection, SDL2 acquisition guidance, `.lnk` shortcuts, Add/Remove
Programs registration, and the frozen `EC7Wolf-Setup.exe`.

### Phase 5 — hardening

Unattended mode, upgrade/repair/remove, resumability, the full gate set, and a
pass over every error message to make sure each one says what to do next.
