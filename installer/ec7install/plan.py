"""The install itself: the ordered steps, and one progress bar over all of them.

A front end sets up an InstallPlan, calls run(), and shows whatever the reporter
is told. It does not need to know what the steps are or how long each takes --
which is the point, because the GUI and the CLI would otherwise each have their
own idea and they would drift.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import audio, build, controls, install, shortcuts, verify, windows
from . import source as source_code
from .progress import Canceled, Reporter

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


class RemovalPlan:
    """Uninstalling, wearing the same shape as InstallPlan.

    The progress page runs whatever it is given and reports what comes back, so
    giving removal the same run(reporter) -> Path signature means the thread,
    the progress bar, the cancel button and the finish page all work on it
    unchanged.
    """

    def __init__(self, destination: Path):
        self.destination = Path(destination)

    def steps(self) -> list[str]:
        return ["remove"]

    def run(self, reporter: Reporter) -> Path:
        reporter.step("Removing EC7Wolf", str(self.destination))
        reporter.progress(0.0)
        install.uninstall(self.destination, reporter)
        reporter.progress(1.0)
        return self.destination


class InstallPlan:
    def __init__(self, repo_root: Path, source, destination: Path,
                 with_music: bool = True, with_video: bool = True,
                 menu_shortcut: bool = True, desktop_shortcut: bool = True,
                 classic_controls: bool = False, refresh_media: bool = False,
                 build_dir: Path | None = None, engine: build.Engine | None = None,
                 jobs: int | None = None):
        self.repo_root = Path(repo_root)
        self.source = source
        self.destination = Path(destination)
        self.with_music = with_music
        self.with_video = with_video
        self.menu_shortcut = menu_shortcut
        self.desktop_shortcut = desktop_shortcut
        self.classic_controls = classic_controls
        # Rip and extract even when the folder already holds good copies. For
        # the case the reuse cannot detect: media that is intact but wrong,
        # such as a soundtrack ripped from a different pressing.
        self.refresh_media = refresh_media
        self.build_dir = Path(build_dir) if build_dir else \
            self.destination.parent / ".ec7wolf-build"
        # Encoded music, kept only while it is worth keeping: a failed or
        # canceled run leaves it behind so the next attempt does not spend
        # another minute on tracks it has already encoded, and a successful one
        # takes it away again rather than leaving 40 MB of it in someone's home
        # directory forever.
        self.cache_dir = self.destination.parent / ".ec7wolf-cache"
        self.engine = engine
        self.jobs = jobs

    # -- planning ----------------------------------------------------------

    def _reuse_media(self, staging, reporter) -> tuple[set[str], set[str]]:
        """Adopt the CD media an existing install already holds.

        Returns the relative paths taken, so the steps that would otherwise
        produce them can skip the ones already in hand.

        Each file is checked before it is trusted, with the same tests the
        verifier applies afterward -- a cinematic has to have a FLIC header
        that agrees with its size, a track has to be big enough to be music.
        A truncated file from an interrupted run is worth less than nothing:
        it would be adopted, pass through the install, and fail at the point
        where the player pressed New Mission.
        """
        video: set[str] = set()
        music: set[str] = set()
        if self.refresh_media or not self.destination.is_dir():
            return video, music

        if self.with_video:
            for name in install.CINEMATICS:
                existing = self.destination / "video" / name
                if not existing.is_file() or verify.flic_problem(existing):
                    continue
                if staging.adopt(f"video/{name}", reporter):
                    video.add(f"video/{name}")

        if self.with_music:
            source_dir = self.destination / "cdaudio"
            if source_dir.is_dir():
                for existing in sorted(source_dir.glob("track*.ogg")):
                    # The same floor the verifier uses: anything smaller than
                    # this is a stub, not a song.
                    if existing.stat().st_size < 4096:
                        continue
                    if staging.adopt(f"cdaudio/{existing.name}", reporter):
                        music.add(f"cdaudio/{existing.name}")

        if video or music:
            parts = []
            if video:
                parts.append(f"{len(video)} cinematic(s)")
            if music:
                parts.append(f"{len(music)} soundtrack file(s)")
            reporter.step("Keeping the CD media already installed",
                          ", ".join(parts))
        return video, music

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
                def canceled(self): return outer.canceled()
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
                tree = self.repo_root
                if not (tree / "CMakeLists.txt").is_file():
                    # The installer arrived on its own. Fetch what it needs to
                    # build, into the same cache everything else uses.
                    tree = source_code.ensure(
                        self.cache_dir / "source", scoped("engine"))
                engine = build.build(tree, self.build_dir,
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
            # Anything the folder being replaced already has, and that is
            # still good, is taken rather than made again. Both of these come
            # off the disc identically every time, so on an upgrade this turns
            # the two slowest steps after the compile into a file copy.
            reused_video, reused_music = self._reuse_media(staging, reporter)

            if self.with_video:
                reporter.step("Extracting the cinematics")
                available = self.source.list()
                found = 0
                for index, name in enumerate(install.CINEMATICS):
                    reporter.check_cancelled()
                    if f"video/{name}" in reused_video:
                        found += 1
                        scoped("video").progress((index + 1) / len(install.CINEMATICS))
                        continue
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
                                          scoped("music"),
                                          cache=self.cache_dir / "cdaudio"):
                        staging.note(f"cdaudio/{path.name}")
                done += WEIGHTS["music"]
                reporter.progress(done / total)

            # --- the engine and the launcher
            reporter.step("Assembling the install", str(self.destination))
            staging.copy(engine.executable, engine.executable.name)
            staging.copy(engine.pk3, engine.pk3.name)
            for extra in getattr(engine, "extra_files", []):
                if Path(extra).is_file():
                    reporter.detail(Path(extra).name)
                    staging.copy(Path(extra), Path(extra).name)
            if not install.is_windows():
                (staging.path / engine.executable.name).chmod(0o755)
            launcher_name = install.write_launcher(staging.path).name
            staging.note(launcher_name)

            # Written into the staging tree rather than the finished install,
            # so that Staging.carry_over -- which brings an existing config
            # forward on a reinstall -- leaves it alone. Someone who has just
            # asked for the original's controls means it more than their old
            # file does.
            if self.classic_controls:
                controls.write_config(staging.path, controls.CLASSIC)
                staging.note(controls.CONFIG_NAME)
                reporter.detail("controls: the original's scheme "
                                "(arrows, Space to use)")
            done += WEIGHTS["assemble"]
            reporter.progress(done / total)

            destination = staging.commit(reporter)
        except Canceled:
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
                reporter.warn(
                    f"could not create shortcuts: {error}. The game is "
                    f"installed and works -- start it with {launcher}.")
        done += WEIGHTS["shortcuts"]
        reporter.progress(done / total)

        uninstaller = install.write_uninstaller(destination, created)
        reporter.detail(f"uninstaller -> {uninstaller}")
        windows.register_uninstall(destination, uninstaller,
                                   engine.version(), reporter)

        install.write_manifest(destination, {
            "engine": engine.source,
            "source": self.source.describe(),
            "launcher": str(launcher),
            "shortcuts": [str(p) for p in created],
            "uninstaller": str(uninstaller),
            "music": self.with_music,
            "video": self.with_video,
        })

        # The install is made; the working files have done their job.
        shutil.rmtree(self.cache_dir, ignore_errors=True)

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
