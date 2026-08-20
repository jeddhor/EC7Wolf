"""The install itself: the ordered steps, and one progress bar over all of them.

A front end sets up an InstallPlan, calls run(), and shows whatever the reporter
is told. It does not need to know what the steps are or how long each takes --
which is the point, because the GUI and the CLI would otherwise each have their
own idea and they would drift.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import audio, build, install, shortcuts, verify
from .progress import Cancelled, Reporter

# Rough share of the wall clock each step takes, so one bar can move smoothly
# across very unequal work. Building dominates everything else by an order of
# magnitude when it happens at all.
WEIGHTS = {
    "engine": 60.0,
    "data": 4.0,
    "video": 6.0,
    "music": 26.0,
    "assemble": 2.0,
    "shortcuts": 1.0,
    "verify": 1.0,
}


class PlanError(Exception):
    pass


class InstallPlan:
    def __init__(self, repo_root: Path, source, destination: Path,
                 with_music: bool = True, with_video: bool = True,
                 menu_shortcut: bool = True, desktop_shortcut: bool = True,
                 build_dir: Path | None = None, engine: build.Engine | None = None,
                 jobs: int | None = None):
        self.repo_root = Path(repo_root)
        self.source = source
        self.destination = Path(destination)
        self.with_music = with_music
        self.with_video = with_video
        self.menu_shortcut = menu_shortcut
        self.desktop_shortcut = desktop_shortcut
        self.build_dir = Path(build_dir) if build_dir else \
            self.destination.parent / ".ec7wolf-build"
        self.engine = engine
        self.jobs = jobs

    # -- planning ----------------------------------------------------------

    def steps(self) -> list[str]:
        names = []
        if self.engine is None:
            names.append("engine")
        names.append("data")
        if self.with_video:
            names.append("video")
        if self.with_music:
            names.append("music")
        names += ["assemble", "shortcuts", "verify"]
        return names

    def required_space(self) -> int:
        need = install.estimate_size(self.with_music, self.with_video)
        if self.engine is None:
            need += 400 * 1024 * 1024   # a build tree is far larger than its output
        return need

    def check_space(self) -> str | None:
        free = install.free_space(self.destination)
        need = self.required_space()
        if free < need:
            return (f"{self.destination} has {free / 2**20:.0f} MB free but the "
                    f"install needs about {need / 2**20:.0f} MB")
        return None

    def missing_from_source(self) -> list[str]:
        available = set(self.source.list())
        return [n for n in install.REQUIRED_DATA if n not in available]

    # -- running -----------------------------------------------------------

    def run(self, reporter: Reporter) -> Path:
        names = self.steps()
        total = sum(WEIGHTS[n] for n in names)
        done = 0.0

        def scoped(name: str) -> Reporter:
            """A reporter whose 0..1 becomes this step's slice of the whole."""
            outer = reporter
            share = WEIGHTS[name] / total
            base = done / total

            class Scoped(Reporter):
                def step(self, n, d=""): outer.step(n, d)
                def detail(self, line): outer.detail(line)
                def warn(self, message): outer.warn(message)
                def cancelled(self): return outer.cancelled()
                def progress(self, fraction):
                    outer.progress(base + max(0.0, min(1.0, fraction)) * share)
            return Scoped()

        missing = self.missing_from_source()
        if missing:
            raise PlanError(
                "this source is missing " + ", ".join(missing) +
                ". Choose the Corridor 7 CD, or a BIN/CUE image of it.")

        staging = install.Staging(self.destination)
        try:
            engine = self.engine
            if engine is None:
                engine = build.build(self.repo_root, self.build_dir,
                                     scoped("engine"), self.jobs)
                done += WEIGHTS["engine"]
            reporter.progress(done / total)

            # --- the game's own files
            reporter.step("Copying the game files", self.source.describe())
            wanted = list(install.REQUIRED_DATA) + [
                n for n in install.OPTIONAL_DATA if n in self.source.list()]
            for index, name in enumerate(wanted):
                reporter.check_cancelled()
                reporter.detail(name)
                staging.write(name, self.source.read(name))
                scoped("data").progress((index + 1) / len(wanted))
            done += WEIGHTS["data"]
            reporter.progress(done / total)

            # --- the cinematics
            if self.with_video:
                reporter.step("Extracting the cinematics")
                available = self.source.list()
                found = 0
                for index, name in enumerate(install.CINEMATICS):
                    reporter.check_cancelled()
                    if name not in available:
                        reporter.warn(
                            f"{name} is not on this source; the cinematics only "
                            "exist on the CD, not in an installed folder")
                        continue
                    reporter.detail(name)
                    staging.write(f"video/{name}", self.source.read(name))
                    found += 1
                    scoped("video").progress((index + 1) / len(install.CINEMATICS))
                if found == 0:
                    reporter.warn("no cinematics were found; the game will "
                                  "simply not play them")
                done += WEIGHTS["video"]
                reporter.progress(done / total)

            # --- the soundtrack
            if self.with_music:
                reporter.step("Ripping the soundtrack")
                if not audio.can_rip(self.source):
                    reporter.warn(
                        "this source has no audio tracks, so the music cannot "
                        "be ripped; the game will use the AdLib soundtrack")
                else:
                    for path in audio.rip(self.source, staging.path / "cdaudio",
                                          scoped("music")):
                        staging.note(f"cdaudio/{path.name}")
                done += WEIGHTS["music"]
                reporter.progress(done / total)

            # --- the engine and the launcher
            reporter.step("Assembling the install", str(self.destination))
            staging.copy(engine.executable, engine.executable.name)
            staging.copy(engine.pk3, engine.pk3.name)
            if not sys.platform.startswith("win"):
                (staging.path / engine.executable.name).chmod(0o755)
            launcher_name = install.write_launcher(staging.path).name
            staging.note(launcher_name)
            done += WEIGHTS["assemble"]
            reporter.progress(done / total)

            destination = staging.commit(reporter)
        except Cancelled:
            staging.abandon()
            raise
        except Exception:
            staging.abandon()
            raise

        # Past this point the install exists; anything that fails is reported
        # but does not undo it, because a game that runs without a menu entry is
        # better than no game.
        launcher = destination / launcher_name
        created: list[Path] = []
        if self.menu_shortcut or self.desktop_shortcut:
            reporter.step("Creating shortcuts")
            try:
                created = shortcuts.create(
                    destination, launcher, self.repo_root, reporter,
                    menu=self.menu_shortcut, desktop=self.desktop_shortcut)
            except Exception as error:
                reporter.warn(f"could not create shortcuts: {error}")
        done += WEIGHTS["shortcuts"]
        reporter.progress(done / total)

        uninstaller = install.write_uninstaller(destination, created)
        reporter.detail(f"uninstaller -> {uninstaller}")

        install.write_manifest(destination, {
            "engine": engine.source,
            "source": self.source.describe(),
            "launcher": str(launcher),
            "shortcuts": [str(p) for p in created],
            "uninstaller": str(uninstaller),
            "music": self.with_music,
            "video": self.with_video,
        })

        reporter.step("Checking the install")
        problems = verify.verify(destination, expect_music=self.with_music,
                                 expect_video=self.with_video)
        fatal = [p for p in problems if p.fatal]
        for problem in problems:
            reporter.warn(str(problem))
        if fatal:
            raise PlanError(
                "the install finished but does not look right:\n  " +
                "\n  ".join(str(p) for p in fatal))
        done += WEIGHTS["verify"]
        reporter.progress(1.0)
        return destination
