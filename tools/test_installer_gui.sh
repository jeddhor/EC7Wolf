#!/bin/sh

# Regression test: the installer's window.
#
# A GUI is the one part of the installer that cannot be checked by running the
# library, so this drives the real wizard through Qt's offscreen platform: the
# pages are constructed, filled in and advanced exactly as a user would, and the
# assertions are about what the window would let them do next.
#
# The install itself is NOT run here -- test_installer.sh already does that end
# to end, and doing it twice would double the slowest gate in the suite for no
# extra coverage. What this adds is everything above the library: page order,
# validation, the thread that keeps the window alive during slow work, and the
# rule that matters most in an installer -- that Next stays disabled until the
# answer is one the installer can actually act on.
#
# Offscreen is not a convenience. A gate that opened windows would throw them
# onto the developer's screen mid-run, and would fail outright in CI.
#
# Usage: test_installer_gui.sh [DISC]

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/.." && pwd)

if ! python3 -c "import PySide6.QtWidgets" >/dev/null 2>&1; then
	printf 'SKIP: PySide6 is not installed\n'
	exit 77
fi

disc=${1:-${CORRIDOR7_DISC:-}}
if [ -z "$disc" ]; then
	for candidate in "$repo/../corr7/Corridor7.cue" "$repo/../corr7/corridor7.cue"; do
		[ -f "$candidate" ] && { disc=$candidate; break; }
	done
fi

work=$(mktemp -d /tmp/ec7wolf-gui.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

QT_QPA_PLATFORM=offscreen \
QT_LOGGING_RULES='*.debug=false;qt.qpa.*=false' \
python3 - "$repo" "$work" "$disc" <<'PY'
import sys, threading, time
from pathlib import Path

repo, work, disc = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(repo / "installer"))
sys.path.insert(0, str(repo / "tools"))

from PySide6.QtCore import qInstallMessageHandler

# Qt's offscreen plugin warns about propagateSizeHints on every window it makes.
# It is noise, and a gate log should read as though nothing went wrong when
# nothing did -- but everything else Qt says still gets through.
def _quiet(mode, context, message):
    if "propagateSizeHints" not in message:
        sys.stderr.write(message + "\n")

qInstallMessageHandler(_quiet)

from PySide6.QtWidgets import QApplication, QWizard
from PySide6.QtCore import QTimer, QEventLoop

from ec7install_gui.wizard import InstallerWizard
from ec7install_gui.worker import Bridge, GuiReporter

failures = []

def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)

def pump(seconds=0.05):
    QApplication.instance().processEvents(QEventLoop.AllEvents, int(seconds * 1000))

def wait_for(predicate, timeout=90.0, what="condition"):
    """Spin the event loop until a background task has reported back."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        pump()
        time.sleep(0.01)
    print(f"  FAIL timed out after {timeout:.0f}s waiting for {what}")
    failures.append(f"timeout: {what}")
    return False

# The self-test below makes its own QApplication and Qt permits exactly one,
# so it runs first and this one is taken afterwards.
from ec7install_gui.wizard import selftest as _selftest
_selftest_result = _selftest(repo)
app = QApplication.instance() or QApplication([])

# --- the reporter's thread crossing --------------------------------------
#
# Everything the window shows during an install arrives this way, so if the
# marshalling drops or reorders messages the progress display is fiction.
print("\nreporter marshalling")
bridge = Bridge()
seen = []
bridge.stepped.connect(lambda name, detail: seen.append(("step", name)))
bridge.detailed.connect(lambda line: seen.append(("detail", line)))
bridge.progressed.connect(lambda f: seen.append(("progress", round(f, 3))))
bridge.warned.connect(lambda m: seen.append(("warn", m)))

cancel = threading.Event()
reporter = GuiReporter(bridge, cancel)

def emit_from_worker():
    reporter.step("Compiling", "1 of 2")
    for index in range(100):
        reporter.detail(f"line {index}")
        reporter.progress(index / 100)
    reporter.warn("a warning")

worker = threading.Thread(target=emit_from_worker)
worker.start()
wait_for(lambda: not worker.is_alive(), 20, "the worker thread")
worker.join()
for _ in range(50):
    pump()

check(seen and seen[0] == ("step", "Compiling"), "the step arrives first")
details = [value for kind, value in seen if kind == "detail"]
check(details == [f"line {i}" for i in range(100)],
      f"all 100 detail lines arrive in order (got {len(details)})")
check(("warn", "a warning") in seen, "the warning arrives")
progress = [value for kind, value in seen if kind == "progress"]
check(progress == sorted(progress), "progress never goes backwards")
check(len(progress) <= 100, f"progress is throttled, not one event per line ({len(progress)})")

check(reporter.cancelled() is False, "the reporter is not cancelled")
cancel.set()
check(reporter.cancelled() is True, "setting the event cancels the reporter")

# --- the wizard ----------------------------------------------------------
print("\nthe self-test a frozen build is checked with")
check(_selftest_result == 0,
      f"it passes against the real source tree (exit {_selftest_result})")

print("\npage order")
wizard = InstallerWizard(repo)
wizard.show()
pump()

expected = ["welcome", "mode", "license", "source", "engine", "destination",
            "options", "summary", "progress", "finish"]
check(list(wizard.ids) == expected, "the pages are in the right order")

def next_button():
    return wizard.button(QWizard.WizardButton.NextButton)

def commit_button():
    return wizard.button(QWizard.WizardButton.CommitButton)

def advance(expect):
    """Click the button a user would click, rather than calling next().

    QWizard.next() is a slot: it moves whether or not the page says it is
    complete. Only the button respects that, so driving the button is the only
    way this test can tell that the page would actually let someone through.
    """
    for button in (QWizard.WizardButton.CommitButton,
                   QWizard.WizardButton.NextButton):
        widget = wizard.button(button)
        if widget.isVisible() and widget.isEnabled():
            widget.click()
            break
    pump()
    check(wizard.currentId() == wizard.ids[expect],
          f"advanced to the {expect} page")

print("\nlicence must be accepted")
advance("license")
page = wizard.currentPage()
check(not page.isComplete(), "Next is refused before the licence is accepted")
check(len(page.text.toPlainText()) > 1000, "the licence text is actually shown")
page.accepted.setChecked(True)
pump()
check(page.isComplete(), "accepting the licence releases Next")

print("\nsource validation")
advance("source")
source_page = wizard.currentPage()
check(not source_page.isComplete(), "an unset source is refused")

empty = work / "not-the-game"
empty.mkdir(parents=True, exist_ok=True)
source_page.folderRadio.setChecked(True)
source_page.folderEdit.setText(str(empty))
source_page.rescan()
wait_for(lambda: source_page.task is not None and source_page.task.isFinished(),
         30, "the empty folder to be probed")
for _ in range(50):
    pump()
check(not source_page.isComplete(), "a folder without the game data is refused")
check("MAPTEMP.CO7" in source_page.result.toPlainText(),
      "and it says which files are missing")

if not disc or not Path(disc).exists():
    print("\nSKIP: no Corridor 7 disc; stopping after the pages that need none")
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)

source_page.imageRadio.setChecked(True)
source_page.imageEdit.setText(disc)
source_page.rescan()
wait_for(lambda: source_page.isComplete(), 120, "the disc to be probed")
check(source_page.isComplete(), "the real disc is accepted")
check(wizard.state.source is not None, "the source is handed to the state")
check(wizard.state.probe["tracks"] > 0, "its audio tracks were found")
check(len(wizard.state.probe["cinematics"]) == 3, "its three cinematics were found")

print("\nthe engine")
advance("engine")
engine_page = wizard.currentPage()
check(not engine_page.isComplete(), "Next waits while the scan runs")
wait_for(lambda: engine_page.ready or engine_page.recheck.isEnabled(), 120,
         "the engine scan")
for _ in range(20):
    pump()
text = engine_page.report.toPlainText()
if wizard.state.engine is not None:
    check(engine_page.isComplete(), "an existing build satisfies the page")
    check("already built" in text, "and the page says so")
else:
    report = wizard.state.build_report
    check(report is not None, "a dependency report was produced")
    check(engine_page.isComplete() == report.satisfied,
          "Next is allowed exactly when the dependencies are satisfied")
    if not report.satisfied:
        for requirement in report.blocking:
            check(bool(requirement.remedy),
                  f"the missing {requirement.key} comes with a remedy")
check(wizard.state.rip_report is not None, "the ripping tools were checked too")

# What the page is for: on a machine with no build tools it has to say so and
# refuse to go on. Emptying PATH is the only honest way to reach that state on a
# developer machine that has everything.
print("\nmissing build tools stop the installer")
import os
saved_path = os.environ.get("PATH", "")
os.environ["PATH"] = "/nonexistent"
engine_page.forceBuild.setChecked(True)
wait_for(lambda: engine_page.recheck.isEnabled(), 120, "the rescan with an empty PATH")
for _ in range(20):
    pump()
starved = wizard.state.build_report
check(starved is not None and not starved.satisfied,
      "with nothing on PATH the scan reports missing tools")
if starved is not None and not starved.satisfied:
    check(not engine_page.isComplete(), "the page refuses to continue")
    check(not next_button().isEnabled(), "and the Next button is disabled")
    where = wizard.currentId()
    next_button().click()
    pump()
    check(wizard.currentId() == where, "clicking Next does nothing")
    check(all(r.remedy for r in starved.blocking),
          "every missing tool comes with a command to install it")
    shown = engine_page.report.toPlainText()
    check(all(r.label in shown for r in starved.blocking),
          "and every one of them is named on the page")

os.environ["PATH"] = saved_path
engine_page.forceBuild.setChecked(False)
wait_for(lambda: engine_page.isComplete(), 120, "the page to recover once PATH is back")
check(engine_page.isComplete(), "restoring PATH lets the installer go on")

if not engine_page.isComplete():
    print("\nSKIP: no engine and unsatisfied dependencies; cannot go further")
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)

print("\nthe destination")
advance("destination")
destination_page = wizard.currentPage()
check(destination_page.isComplete(), "the default destination is usable")
default = Path(destination_page.edit.text())
check("/snap/" not in str(default) and "/.cache/" not in str(default),
      f"the default is not inside a sandbox ({default})")

destination_page.edit.setText("/proc/nowhere/ec7wolf")
pump()
check(not destination_page.isComplete(), "an unwritable destination is refused")
check("permission" in destination_page.notes.toPlainText().lower(),
      "and it says why")

target = work / "install"
destination_page.edit.setText(str(target))
pump()
check(destination_page.isComplete(), "a writable destination is accepted")
check(wizard.state.destination == target, "the destination reaches the state")

print("\noptions")
advance("options")
options_page = wizard.currentPage()
check(options_page.music.isEnabled() and options_page.music.isChecked(),
      "the soundtrack is offered, and on by default, for a disc that has one")
check(options_page.video.isEnabled() and options_page.video.isChecked(),
      "so are the cinematics")
options_page.desktop.setChecked(False)
pump()
check(wizard.state.desktop_shortcut is False, "unticking reaches the state")

print("\nsummary")
advance("summary")
summary_page = wizard.currentPage()
check(summary_page.isCommitPage(), "the summary is the commit page")
check(commit_button().text() == "Install", "its button reads Install")
shown = summary_page.summary.toPlainText()
check(str(target) in shown, "the summary names the destination")
check("applications menu" in shown and "desktop" not in shown.split("Log")[0],
      "the summary reflects the shortcut choices")
check(wizard.state.log_path is not None and
      str(wizard.state.log_path) in shown, "the summary names the log file")
check(not (target.exists()), "nothing has been written yet")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
PY

# --- the progress page, for real -------------------------------------------
#
# Everything above stops short of writing anything. This half runs two actual
# installs through the window, because the worker thread, the progress display
# and the Cancel button cannot be judged from a static page: what matters about
# them is what they do while work is in flight.
#
# HOME is redirected so the shortcuts land in the throwaway tree instead of on
# the developer's real desktop.

if [ -z "$disc" ] || [ ! -f "$disc" ]; then
	printf '\nSKIP: no Corridor 7 disc, so the install half cannot run\n'
	exit 0
fi

HOME="$work/home" \
XDG_DATA_HOME="$work/home/.local/share" \
QT_QPA_PLATFORM=offscreen \
QT_LOGGING_RULES='*.debug=false;qt.qpa.*=false' \
python3 - "$repo" "$work" "$disc" <<'PY'
import sys, time
from pathlib import Path

repo, work, disc = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(repo / "installer"))
sys.path.insert(0, str(repo / "tools"))
(work / "home").mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import qInstallMessageHandler

# Qt's offscreen plugin warns about propagateSizeHints on every window it makes.
# It is noise, and a gate log should read as though nothing went wrong when
# nothing did -- but everything else Qt says still gets through.
def _quiet(mode, context, message):
    if "propagateSizeHints" not in message:
        sys.stderr.write(message + "\n")

qInstallMessageHandler(_quiet)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop

from c7disc import GameSource
from ec7install import build
from ec7install_gui.wizard import InstallerWizard
from ec7install_gui.pages import probe_source

failures = []

def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)

def pump(rounds=5):
    for _ in range(rounds):
        QApplication.instance().processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.005)

def wait_for(predicate, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        pump()
    print(f"  FAIL timed out after {timeout:.0f}s waiting for {what}")
    failures.append(f"timeout: {what}")
    return False

app = QApplication([])
engine = build.find_existing(repo)
if engine is None:
    print("\nSKIP: no engine is built, so an install would have to compile one")
    sys.exit(0)

probe = probe_source(Path(disc))

def start(target, music, video):
    """A wizard taken straight to the summary, then told to install."""
    wizard = InstallerWizard(repo)
    wizard.show()
    state = wizard.state
    state.source, state.probe = probe["source"], probe
    state.source_path = Path(disc)
    state.engine = engine
    state.destination = target
    state.with_music, state.with_video = music, video
    state.menu_shortcut, state.desktop_shortcut = True, False
    wizard.setStartId(wizard.ids["summary"])
    wizard.restart()
    pump()
    wizard.next()
    pump()
    return wizard

# --- an install that runs to the end --------------------------------------
print("\ninstalling through the window")
target = work / "gui-install"
wizard = start(target, music=False, video=True)
page = wizard.progress_page
check(wizard.currentId() == wizard.ids["progress"], "Install moves to the progress page")
check(not page.isComplete(), "the progress page holds Next while it works")

# Toggled here, while the page is still the visible one: a widget on a page the
# wizard has already left reports itself hidden whatever its own flag says.
page.toggle.setChecked(True)
pump()
check(page.details.isVisible(), "Show details reveals the pane")
check(page.toggle.text() == "Hide details", "and the button changes to match")

wait_for(lambda: bool(wizard.state.outcome), 300, "the install to finish")
pump(40)

check(wizard.state.outcome == "ok",
      f"the install succeeded (outcome={wizard.state.outcome!r} "
      f"{wizard.state.message})")
check(page.bar.value() == page.bar.maximum(), "the bar reached the end")
check(page.details.toPlainText().count("\n") > 5,
      "the detail pane collected the running commentary")

check(wizard.currentId() == wizard.ids["finish"], "it moved on to the finish page")
finish = wizard.page_named("finish")
shown = finish.text.toPlainText()
check(str(target) in shown, "the finish page names the install")
check(finish.launch.isVisible(), "and offers to start the game")
check((target / "ec7wolf").exists(), "the engine is in place")
check((target / "MAPTEMP.CO7").exists(), "so is the game data")
check((target / "video" / "SEQONE.CO7").exists(), "so are the cinematics")
check(not (target / "cdaudio").exists(), "and no music, which was not asked for")

# --- an install that is stopped part way ----------------------------------
print("\ncancelling part way through")
cancelled_target = work / "gui-cancelled"
wizard2 = start(cancelled_target, music=True, video=True)
page2 = wizard2.progress_page

started = time.time()
wait_for(lambda: "Ripping" in page2.stepLabel.text(), 300, "the soundtrack rip to start")
check(page2.request_cancel(), "Cancel reaches the worker while it is running")
asked = time.time()
wait_for(lambda: bool(wizard2.state.outcome), 60, "the worker to unwind")
pump(40)

check(wizard2.state.outcome == "cancelled",
      f"the outcome is cancelled (got {wizard2.state.outcome!r})")
check(asked and time.time() - asked < 30,
      f"it stopped promptly ({time.time() - asked:.1f}s after asking)")
check(not cancelled_target.exists(),
      "nothing was left behind at the destination")
leftovers = [p.name for p in cancelled_target.parent.glob(".*staging*")]
check(not leftovers, f"and no staging directory was left ({leftovers})")
check(wizard2.currentId() == wizard2.ids["finish"], "it moved on to the finish page")
check("cancelled" in wizard2.page_named("finish").text.toPlainText().lower(),
      "which says so")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
PY
