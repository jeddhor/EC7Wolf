# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The main window: menus, docks, map tabs, and the state that ties them.

The window owns the project document and the undo history, and it is the only
place that replaces the document. Everything else asks it to run a command.
That is what keeps undo honest: there is one path by which a map changes, and
it goes through `History`.

Docks rather than a fixed layout, because the useful arrangement depends on the
screen and on the job. A layout that ends up wrong is recoverable from
View -> Reset layout, which matters more than it sounds: a window restored
off-screen from a previous monitor is otherwise unreachable.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QInputDialog,
    QMenu,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QComboBox,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ec7edit_core.archive import read_archive
from ec7edit_core.catalog import Catalog, load_catalog
from ec7edit_core.commands import History, add_maps
from ec7edit_core.discovery import Profile, data_fingerprint
from ec7edit_core.engine_runner import (
    Session,
    SessionState,
    build_launch_plan,
)
from ec7edit_core.rules import (
    assign_sound_areas as sound_area_writes,
    check_door,
    check_transporters,
    door_cells,
)
from ec7edit_core.transforms import copy_region, flip_clip, paste_writes, rotate_clip
from ec7edit_core.validation import (
    Profile,
    fix_label,
    fix_writes,
    profile_for_slot,
    summarise,
    validate_local,
    validate_map,
)
from ec7edit_core.document import MapDocument, ProjectDocument, SourceReference, utc_now
from ec7edit_core.errors import Ec7EditError, Severity
from ec7edit_core.paths import SourceIdentity
from ec7edit_core.prefabs import PREFABS, by_key as prefab_by_key
from ec7edit_core.project import (
    PROJECT_SUFFIX,
    RecoveryStore,
    SaveConflict,
    load_project,
    new_project,
    project_identity,
    save_project,
)

from .import_dialog import ImportDialog
from .inspector import Inspector
from .map_canvas import MapCanvas
from .palette_models import CatalogFilter, CatalogModel, EntryRole
from .settings import Settings
from .thumbnails import AssetSource, ThumbnailFactory
from .tools import Tool, ToolController
from .workers import WorkerPool

CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "editor_catalog.json"

#: Section 8.6's tabs. "Doors and Specials" holds the compound *tools* rather
#: than the raw words behind them: offering both was offering two things that
#: looked identical and were not, since painting a pushwall's marker straight
#: on to floor leaves a moving wall with no wall in it.
PALETTE_TABS = (
    ("Doors and Specials", "prefabs"),
    ("Walls", "walls"),
    ("Objects", "objects"),
    ("Enemies", "enemies"),
    ("Starts and Paths", "starts"),
    ("Zones", "zones"),
    ("Raw", "raw"),
)


class MapTab(QWidget):
    """One open map: a scrollable canvas."""

    def __init__(self, document: MapDocument, catalog: Catalog | None, parent=None) -> None:
        super().__init__(parent)
        self.canvas = MapCanvas(document, catalog, self)
        area = QScrollArea(self)
        area.setWidget(self.canvas)
        area.setAlignment(Qt.AlignCenter)
        area.setAccessibleName(f"Map {document.name}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)
        self.map_uuid = document.uuid


class MainWindow(QMainWindow):
    """EC7Edit's window."""

    project_changed = Signal()

    def __init__(self, settings: Settings | None = None, *, catalog: Catalog | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EC7Edit")
        self.setObjectName("ec7edit-main")
        self.resize(1180, 760)

        self.settings = settings or Settings()
        self.catalog = catalog if catalog is not None else self._load_catalog()
        self.project: ProjectDocument = new_project()
        self.history = History()
        self.project_path: Path | None = None
        self._identity: tuple | None = None

        self.pool = WorkerPool(self)
        self.thumbnails = ThumbnailFactory()
        #: The last validation result, and the project revision it
        #: describes -- so the panel can say when it has gone stale
        #: instead of quietly showing an answer about an older map.
        self._problems: list = []
        self._problems_revision: int = -1
        #: The playtest, if one has been run. One at a time, deliberately: two
        #: engines sharing a session directory would overwrite each other's
        #: config and saves.
        self.session = None
        self.process = None
        self._session_lines: list = []
        self._session_log_path = None
        #: Whatever a read left mid-line, kept for the next one.
        self._session_tail = ""
        self._session_counter = 0
        #: Coalesces the full pass: every edit restarts it, so the expensive
        #: rules run once after a stroke rather than once per cell of it.
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(400)
        self._validate_timer.timeout.connect(lambda: self.validate())
        self.recovery = RecoveryStore(settings.recovery_dir)
        #: Autosave is a safety net, not a save: it writes a recovery copy into
        #: the application's own directory and never clears the dirty flag,
        #: because telling somebody their work is saved when it is somewhere
        #: they have never heard of would be a lie.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)
        self._autosave_timer.timeout.connect(lambda: self.autosave())
        self._autosave_timer.start()

        self.tools = ToolController(self)
        self.tools.command_ready.connect(self.run_command)
        self.tools.refused.connect(self._on_prefab_refused)
        self.tools.picked.connect(self._on_picked)
        self.tools.message.connect(lambda text: self.statusBar().showMessage(text, 3000))

        self._build_menus()
        self._build_tools()
        self._build_docks()
        self._build_central()
        self.setStatusBar(QStatusBar(self))
        self._cell_label = QLabel("", self)
        self._cell_label.setAccessibleName("Cursor position")
        self.statusBar().addPermanentWidget(self._cell_label)

        self._restore_layout()
        self.open_assets(self.settings.profile)
        self._refresh()

    # -- construction -----------------------------------------------------

    def _load_catalog(self) -> Catalog | None:
        try:
            return load_catalog(CATALOG_PATH)
        except (OSError, ValueError):
            return None

    def _action(self, text, slot, shortcut=None, *, tip="", name="") -> QAction:
        action = QAction(text, self)
        action.setStatusTip(tip or text)
        action.setToolTip(tip or text)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setObjectName(name or text.lower().replace("&", "").replace(" ", "-"))
        # QAction.triggered carries a `checked` bool, and PySide6 passes it to
        # any slot whose signature can take it. Every command here reads its
        # first parameter as "the caller already knows the answer" --
        # open_project(path), new_map(name), import_map(archive_path) -- so the
        # menu was handing them False. open_project treated that as an empty
        # path, which is what a cancelled file dialog looks like, and returned
        # without ever showing one. Drop the argument: nothing here is
        # checkable, so nothing wants it.
        action.triggered.connect(lambda _checked=False, call=slot: call())
        return action

    #: How many recent projects the File menu offers. Settings keeps more than
    #: this; a menu is for the ones you are actually moving between.
    RECENT_SHOWN = 6

    def _rebuild_recent_menu(self) -> None:
        """Refill Open Recent from settings.

        Rebuilt on every open rather than once at startup: the list changes
        whenever a project is opened or saved, and a menu built at startup goes
        stale the first time it is used.
        """
        self.recent_menu.clear()
        entries = list(self.settings.recent_projects)[:self.RECENT_SHOWN]
        if not entries:
            empty = self.recent_menu.addAction("No recent projects")
            empty.setEnabled(False)
            return
        for index, path in enumerate(entries, start=1):
            name = Path(path).name
            # &1..&9 so the keyboard reaches them, and the full path in the tip
            # because two projects may well share a file name.
            action = self.recent_menu.addAction(f"&{index}  {name}")
            action.setObjectName(f"recent-{index}")
            action.setStatusTip(path)
            action.setToolTip(path)
            action.triggered.connect(
                lambda _checked=False, chosen=path: self.open_recent(chosen)
            )
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear the list")
        clear.setObjectName("recent-clear")
        clear.triggered.connect(lambda _checked=False: self.clear_recent())

    def open_recent(self, path: str) -> None:
        """Open a remembered project, forgetting it if it is no longer there.

        A recent list that keeps offering a file somebody has moved or deleted
        is worse than a short one, so a miss drops the entry rather than only
        complaining about it.
        """
        if not Path(path).exists():
            self.settings.forget_project(path)
            self._error("That project is gone",
                        f"{path}\n\nIt has been removed from the recent list.")
            return
        self.open_project(path)

    def clear_recent(self) -> None:
        for path in list(self.settings.recent_projects):
            self.settings.forget_project(path)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.action_new = self._action("&New project", self.new_project, QKeySequence.New)
        self.action_open = self._action("&Open project…", self.open_project, QKeySequence.Open)
        self.action_new_map = self._action("New &map…", self.new_map, "Ctrl+M",
                                           tip="Add an empty map to this project")
        self.action_import = self._action("&Import map from archive…", self.import_map, "Ctrl+I")
        self.action_save = self._action("&Save", self.save_project, QKeySequence.Save)
        self.action_save_as = self._action("Save &As…", self.save_project_as, "Ctrl+Shift+S")
        self.action_save_copy = self._action(
            "Save a &Copy…", self.save_copy,
            tip="Write a copy elsewhere and keep editing this one")
        self.action_export = self._action("&Export preview WAD…", self.export_preview, "Ctrl+E")
        self.action_export_archive = self._action(
            "Export a full archive… (&private)", self.export_archive,
            tip="A complete MAPTEMP.CO7 built on the game's own; not shareable")
        self.action_quit = self._action("&Quit", self.close, QKeySequence.Quit)
        for action in (self.action_new, self.action_open):
            file_menu.addAction(action)
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.setObjectName("open-recent-menu")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._rebuild_recent_menu()
        for action in (self.action_new_map, self.action_import):
            file_menu.addAction(action)
        file_menu.addSeparator()
        for action in (self.action_save, self.action_save_as, self.action_save_copy,
                       self.action_export, self.action_export_archive):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.action_undo = self._action("&Undo", self.undo, QKeySequence.Undo)
        self.action_redo = self._action("&Redo", self.redo, QKeySequence.Redo)
        self.action_copy = self._action("&Copy", self.copy_selection, QKeySequence.Copy)
        self.action_paste = self._action("&Paste", self.paste_clipboard, QKeySequence.Paste)
        self.action_rotate_sel = self._action(
            "Rotate selection", self.rotate_clipboard, "Ctrl+Shift+R",
            tip="Turn the copied area a quarter turn, facings included")
        self.action_flip_h = self._action("Flip selection across", self.flip_clipboard_h)
        self.action_flip_v = self._action("Flip selection down", self.flip_clipboard_v)
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        for action in (self.action_copy, self.action_paste, self.action_rotate_sel,
                       self.action_flip_h, self.action_flip_v):
            edit_menu.addAction(action)

        view_menu = self.menuBar().addMenu("&View")
        self.action_zoom_in = self._action("Zoom &in", self.zoom_in, QKeySequence.ZoomIn)
        self.action_zoom_out = self._action("Zoom &out", self.zoom_out, QKeySequence.ZoomOut)
        self.action_grid = self._action("Show &grid", self.toggle_grid, "Ctrl+G")
        self.action_grid.setCheckable(True)
        self.action_grid.setChecked(True)
        self.action_reset_layout = self._action("&Reset layout", self.reset_layout)
        for action in (self.action_zoom_in, self.action_zoom_out, self.action_grid):
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.action_reset_layout)

        self.tools_menu = self.menuBar().addMenu("&Tools")
        self.action_test = self._action(
            "&Test in EC7Wolf", self.playtest, "F5",
            tip="Export the open map and launch the engine on it",
        )
        self.action_validate = self._action("&Check this map", self.validate, "F8")
        self.action_stop_test = self._action(
            "S&top the playtest", self.stop_session, "Shift+F5",
            tip="Close the running engine")
        self.action_stop_test.setEnabled(False)
        self.action_statistics = self._action("Map &statistics", self.show_statistics)
        self.action_sound_areas = self._action(
            "Give the floor sound &areas", self.assign_sound_areas,
            tip="Repair floor cells that have no sound area, so aliens can hear",
        )
        self.action_setup = self._action("&Setup…", self.run_setup, tip="Engine, data, workspace")
        self.tools_menu.addAction(self.action_test)
        self.tools_menu.addAction(self.action_stop_test)
        self.tools_menu.addAction(self.action_validate)
        self.tools_menu.addAction(self.action_statistics)
        self.tools_menu.addAction(self.action_sound_areas)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction(self.action_setup)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("&About EC7Edit", self.about))

        bar = self.addToolBar("Main")
        bar.setObjectName("main-toolbar")
        bar.setMovable(True)
        for action in (self.action_new, self.action_open, self.action_save,
                       self.action_export, self.action_undo, self.action_redo,
                       self.action_test):
            bar.addAction(action)

    def _build_tools(self) -> None:
        """One exclusive action per tool, with its single-key shortcut."""
        bar = self.addToolBar("Tools")
        bar.setObjectName("tools-toolbar")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool in Tool:
            action = QAction(tool.label, self)
            action.setCheckable(True)
            action.setObjectName(f"tool-{tool.value}")
            action.setShortcut(QKeySequence(tool.shortcut))
            action.setStatusTip(f"{tool.label} ({tool.shortcut})")
            action.triggered.connect(lambda _checked, chosen=tool: self.select_tool(chosen))
            group.addAction(action)
            bar.addAction(action)
            self.tool_actions[tool] = action
        self.tool_actions[Tool.BRUSH].setChecked(True)

        # Only a structure with a footprint that actually has an orientation can
        # be turned. Every wall unit is a single word usable from whichever side
        # has floor, so none of them do -- and a button that can never do
        # anything is worse than no button. It reappears on its own if a
        # multi-cell structure is ever added.
        self.action_rotate = self._action(
            "&Turn structure", self.tools.rotate_prefab, "Ctrl+R",
            tip="Turn the selected structure a quarter turn clockwise",
        )
        self.action_rotate.setVisible(False)
        bar.addAction(self.action_rotate)

        self.filled_box = QCheckBox("Filled", self)
        self.filled_box.setAccessibleName("Filled rectangle")
        self.filled_box.toggled.connect(
            lambda checked: setattr(self.tools, "filled_rectangle", checked)
        )
        bar.addWidget(self.filled_box)

    def select_tool(self, tool: Tool) -> None:
        if tool is not Tool.PREFAB:
            self.tools.prefab = None
        if tool is not Tool.TRANSPORTER:
            self.tools.cancel_pending()
        self.tools.set_tool(tool)
        action = self.tool_actions.get(tool)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _build_docks(self) -> None:
        self.map_list = QListWidget(self)
        self.map_list.setAccessibleName("Maps in this project")
        self.map_list.currentRowChanged.connect(self._on_map_selected)
        self.map_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.map_list.customContextMenuRequested.connect(self._map_context_menu)
        # A new project has no maps, so the list is empty -- and an empty list
        # is exactly where "how do I start one?" gets asked. The button is
        # always there; the context menu covers the right-click reflex, on a
        # row or on the blank space below the last one.
        self.new_map_button = QPushButton("New map…", self)
        self.new_map_button.setAccessibleName("New map")
        self.new_map_button.setToolTip("Add an empty 64x64 map to this project (Ctrl+M)")
        self.new_map_button.clicked.connect(lambda: self.new_map())

        maps_panel = QWidget(self)
        maps_layout = QVBoxLayout(maps_panel)
        maps_layout.setContentsMargins(0, 0, 0, 0)
        maps_layout.setSpacing(2)
        maps_layout.addWidget(self.map_list)
        maps_layout.addWidget(self.new_map_button)

        maps_dock = QDockWidget("Maps", self)
        maps_dock.setObjectName("maps-dock")
        maps_dock.setWidget(maps_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, maps_dock)
        self.maps_dock = maps_dock

        palette = QWidget(self)
        layout = QVBoxLayout(palette)
        layout.setContentsMargins(4, 4, 4, 4)
        self.search = QLineEdit(palette)
        self.search.setPlaceholderText("Search by name, class or raw value")
        self.search.setAccessibleName("Palette search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh_palette)
        layout.addWidget(self.search)

        self.used_only = QCheckBox("Only what this map uses", palette)
        self.used_only.setAccessibleName("Filter to values used in this map")
        self.used_only.setToolTip(
            "Show only the entries the open map already has, which is how you find "
            "the wall you are looking at rather than the one you are looking for."
        )
        self.used_only.toggled.connect(lambda _: self._refresh_palette())
        layout.addWidget(self.used_only)

        self.palette_tabs = QTabWidget(palette)
        self.palette_tabs.setAccessibleName("Palette")
        self.palette_models: dict[str, CatalogModel] = {}

        # Structures are not catalogue entries -- they are compound tools, and
        # they get a plain list because what matters is the name and what it
        # needs, not a picture of one word out of several.
        self.prefab_list = QListWidget(self)
        self.prefab_list.setAccessibleName("Doors and specials palette")
        # Both signals: `currentItemChanged` catches keyboard navigation, and
        # `itemClicked` catches clicking the row that is already current --
        # which is exactly what you do coming back from the Walls tab to the
        # structure you were using, and which would otherwise re-arm nothing.
        self.prefab_list.currentItemChanged.connect(
            lambda current, _previous: self._on_prefab_chosen(current, _previous))
        self.prefab_list.itemClicked.connect(
            lambda item: self._on_prefab_chosen(item, None))
        self.palette_tabs.addTab(self.prefab_list, "Doors and Specials")

        for title, category in PALETTE_TABS[1:]:
            view = QListView(self.palette_tabs)
            view.setViewMode(QListView.IconMode)
            view.setResizeMode(QListView.Adjust)
            view.setIconSize(QSize(48, 48))
            view.setSpacing(4)
            view.setUniformItemSizes(True)
            view.setAccessibleName(f"{title} palette")
            model = CatalogModel(factory=self.thumbnails, pool=self.pool, parent=self)
            view.setModel(model)
            view.clicked.connect(self._on_palette_clicked)
            self.palette_models[category] = model
            self.palette_tabs.addTab(view, title)
        self._refresh_prefabs()
        self._refresh_prefabs()
        self.palette_tabs.currentChanged.connect(lambda _: self._refresh_palette())
        layout.addWidget(self.palette_tabs, 1)

        self.selection_label = QLabel("Nothing selected", palette)
        self.selection_label.setWordWrap(True)
        self.selection_label.setAccessibleName("Selected palette item")
        layout.addWidget(self.selection_label)

        palette_dock = QDockWidget("Palette", self)
        palette_dock.setObjectName("palette-dock")
        palette_dock.setWidget(palette)
        self.addDockWidget(Qt.RightDockWidgetArea, palette_dock)
        self.palette_dock = palette_dock

        self.inspector = Inspector(self.catalog, self.thumbnails, self)
        self.inspector.change_requested.connect(self._on_inspector_change)
        inspector_dock = QDockWidget("Inspector", self)
        inspector_dock.setObjectName("inspector-dock")
        inspector_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, inspector_dock)
        self.inspector_dock = inspector_dock

        self.problems = QListWidget(self)
        self.problems.setAccessibleName("Problems")
        self.problems.itemActivated.connect(self._on_problem_activated)
        self.problems.currentItemChanged.connect(self._on_problem_selected)

        # Warnings outnumber errors on any real map, and the plan's rule is
        # that a panel nobody can scan is a panel nobody reads. The filter is
        # a floor, not a set of checkboxes: "errors only" is the question
        # people actually ask.
        self.problem_filter = QComboBox(self)
        self.problem_filter.setAccessibleName("Show problems")
        self.problem_filter.addItem("Everything", Severity.INFORMATION)
        self.problem_filter.addItem("Warnings and errors", Severity.WARNING)
        self.problem_filter.addItem("Errors only", Severity.ERROR)
        self.problem_filter.setCurrentIndex(1)
        self.problem_filter.currentIndexChanged.connect(self._repaint_problems)

        self.problem_fix = QPushButton("Fix this", self)
        self.problem_fix.setAccessibleName("Fix the selected problem")
        self.problem_fix.setEnabled(False)
        self.problem_fix.clicked.connect(lambda _checked=False: self.apply_fix())

        self.problem_status = QLabel("", self)
        self.problem_status.setAccessibleName("Problem summary")

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 2, 4, 2)
        controls.addWidget(self.problem_filter)
        controls.addWidget(self.problem_fix)
        controls.addWidget(self.problem_status, 1)

        problems_panel = QWidget(self)
        problems_layout = QVBoxLayout(problems_panel)
        problems_layout.setContentsMargins(0, 0, 0, 0)
        problems_layout.setSpacing(2)
        problems_layout.addLayout(controls)
        problems_layout.addWidget(self.problems)

        self.test_log = QListWidget(self)
        self.test_log.setAccessibleName("Test log")
        self.test_log_status = QLabel("No playtest has been run yet", self)
        self.test_log_status.setAccessibleName("Playtest state")
        test_panel = QWidget(self)
        test_layout = QVBoxLayout(test_panel)
        test_layout.setContentsMargins(4, 2, 4, 2)
        test_layout.setSpacing(2)
        test_layout.addWidget(self.test_log_status)
        test_layout.addWidget(self.test_log)
        test_dock = QDockWidget("Test Log", self)
        test_dock.setObjectName("test-log-dock")
        test_dock.setWidget(test_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, test_dock)
        self.test_log_dock = test_dock

        problems_dock = QDockWidget("Problems", self)
        problems_dock.setObjectName("problems-dock")
        problems_dock.setWidget(problems_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, problems_dock)
        self.problems_dock = problems_dock

    def _build_central(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("map-tabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setAccessibleName("Open maps")
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    # -- assets -----------------------------------------------------------

    def open_assets(self, profile: Profile) -> bool:
        """Open the user's game data for thumbnails. Absent data is not fatal."""
        if not profile.data_dir:
            return False
        try:
            self.thumbnails.source = AssetSource.open(
                profile.data_dir, fingerprint=profile.data_fingerprint
            )
        except (OSError, Ec7EditError, ValueError) as error:
            self.thumbnails.source = None
            self._note_problem(f"Game data unavailable: {error}")
            return False
        self._apply_wall_colours()
        return True

    def _apply_wall_colours(self) -> None:
        """Average colours for the canvas's texture layer, computed once."""
        if not self.thumbnails.available or self.catalog is None:
            return
        colours = {}
        for entry in self.catalog.in_category("walls"):
            colours[entry.value] = self.thumbnails.swatch(entry)
        for index in range(self.tabs.count()):
            self.tabs.widget(index).canvas.set_wall_colours(colours)

    # -- project ----------------------------------------------------------

    def set_project(self, project: ProjectDocument, path: Path | None = None) -> None:
        self.project = project
        self.project_path = path
        self._identity = project_identity(path) if path else None
        self.history.clear()
        self.tabs.clear()
        self._refresh()

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.set_project(new_project())
        self.statusBar().showMessage("New project", 4000)

    def open_project(self, path: str | None = None) -> None:
        if not self._confirm_discard():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open project", self._start_directory(),
                f"EC7Edit projects (*{PROJECT_SUFFIX})",
            )
        if not path:
            return
        try:
            project = load_project(path)
        except (OSError, Ec7EditError) as error:
            self._error("Could not open that project", str(error))
            return
        self.set_project(project, Path(path))
        self.settings.remember_project(path)
        self.statusBar().showMessage(f"Opened {Path(path).name}", 4000)

    def new_map(self, name: str | None = None, slot: int | None = None,
                width: int = 64, height: int = 64) -> MapDocument | None:
        """Add an empty map to the project and open it.

        Corridor 7's floors are 64x64 and the engine will not load anything
        bigger than 181, so the size is offered but rarely changed. The slot
        defaults to the first one this project is not already using -- two maps
        exporting to MAP01 would silently shadow each other.
        """
        used = {document.slot for document in self.project.maps}
        if slot is None:
            slot = next((n for n in range(1, 101) if n not in used), None)
            if slot is None:
                self._error("No free slot", "This project already fills MAP01 to MAP100.")
                return None

        if name is None:
            from PySide6.QtWidgets import QInputDialog

            name, accepted = QInputDialog.getText(
                self, "New map", f"Name for {f'MAP{slot:02d}'}:", text=f"MAP {slot}"
            )
            if not accepted:
                return None

        try:
            document = MapDocument.new_room(slot=slot, name=name or f"MAP {slot}",
                                            width=width, height=height)
        except Ec7EditError as error:
            self._error("Could not create that map", str(error))
            return None

        self.project = self.project.added(document)
        self._refresh()
        self.open_map(document.uuid)
        self.statusBar().showMessage(
            f"Added {document.lump_name} ({width}x{height})", 4000
        )
        return document

    def import_map(self, archive_path: str | None = None, number: int | None = None) -> None:
        if archive_path is None:
            archive_path, _ = QFileDialog.getOpenFileName(
                self, "Import from a Corridor 7 archive",
                self.settings.profile.data_dir or self._start_directory(),
                "Corridor 7 archives (MAPTEMP.CO7 *.CO7 *.c7map);;All files (*)",
            )
        if not archive_path:
            return
        try:
            identity = SourceIdentity.probe(archive_path)
            archive = read_archive(archive_path)
        except (OSError, Ec7EditError) as error:
            self._error("Could not read that archive", str(error))
            return

        if number is not None:
            wanted = [number]
        else:
            # Sixty maps in an archive and the old code took the first one.
            dialog = ImportDialog(archive, str(archive_path), self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            wanted = dialog.chosen()
        if not wanted:
            return

        # One command, whether it is one map or sixty: an import that lands as
        # sixty separate undo steps is one nobody can back out of.
        try:
            records = [archive.by_number(n) for n in wanted]
        except Ec7EditError as error:
            self._error("No such map", str(error))
            return

        documents = [
            MapDocument.from_record(
                record,
                source=SourceReference(
                    display_path=str(archive_path), sha256=identity.digest,
                    map_number=record.number, imported_at=utc_now(),
                ),
            )
            for record in records
        ]
        self.run_command(add_maps(documents, index=len(self.project.maps), label=(
            f"Import {len(documents)} maps" if len(documents) > 1
            else f"Import {records[0].name.text or records[0].lump_name}")))
        self.open_map(documents[0].uuid)
        identity.verify_unchanged()
        self.statusBar().showMessage(
            f"Imported {len(documents)} map(s) from {Path(archive_path).name}", 4000)

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_project_as()
        try:
            revision = save_project(self.project, self.project_path,
                                    expect_identity=self._identity)
        except SaveConflict:
            # Somebody -- another copy of the editor, a sync client, the user
            # in a text editor -- changed the file since it was opened. The one
            # thing that must not happen is a silent overwrite, so this asks,
            # and the default is the answer that loses nothing.
            answer = QMessageBox.question(
                self, "The file changed underneath this project",
                f"{self.project_path.name} has been modified since it was opened.\n\n"
                "Overwrite it with what is in the editor, or save this copy "
                "somewhere else?",
                QMessageBox.StandardButton.SaveAll | QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.SaveAll,
            )
            if answer == QMessageBox.StandardButton.Save:
                self._identity = project_identity(self.project_path)
                return self.save_project()
            if answer == QMessageBox.StandardButton.SaveAll:
                return self.save_project_as()
            return False
        except Exception as error:
            self._error("Could not save", str(error))
            return False
        self.project = self.project.marked_saved(revision)
        self._identity = project_identity(self.project_path)
        self.recovery.discard(self.project.uuid)
        self.settings.remember_project(self.project_path)
        self._refresh()
        self.statusBar().showMessage(f"Saved {self.project_path.name}", 4000)
        return True

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", self._start_directory(),
            f"EC7Edit projects (*{PROJECT_SUFFIX})",
        )
        if not path:
            return False
        if not path.endswith(PROJECT_SUFFIX):
            path += PROJECT_SUFFIX
        self.project_path = Path(path)
        self._identity = None
        return self.save_project()

    def autosave(self) -> bool:
        """Write a recovery copy if there is anything to recover."""
        if not self.project.dirty:
            return False
        try:
            self.recovery.autosave(self.project,
                                   str(self.project_path or ""))
        except Exception:
            # A failed autosave must never interrupt editing, and must never
            # be the thing that loses the work it was protecting.
            return False
        return True

    def offer_recovery(self) -> int:
        """At startup, offer back anything a previous run did not finish saving.

        Only work that was *ahead* of its last save is worth offering: a
        recovery copy whose revision matches what is on disk is a copy of a
        file the user already has.
        """
        try:
            records = [r for r in self.recovery.list_recoveries()
                       if r.autosaved_revision > r.saved_revision]
        except Exception:
            return 0
        if not records:
            return 0
        newest = max(records, key=lambda r: r.timestamp)
        where = Path(newest.original_path).name if newest.original_path else "an unsaved project"
        answer = QMessageBox.question(
            self, "Unsaved work from a previous session",
            f"EC7Edit has a recovery copy of {where} from {newest.timestamp}, "
            "with changes that were never saved.\n\nOpen it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            # Discarded deliberately: an offer that comes back every launch is
            # one people learn to dismiss without reading.
            self.recovery.discard(newest.project_uuid)
            return 0
        try:
            self.set_project(self.recovery.load(newest.project_uuid),
                             Path(newest.original_path) if newest.original_path else None)
        except Exception as error:
            self._error("Could not open the recovery copy", str(error))
            return 0
        self.statusBar().showMessage(
            "Recovered unsaved work — this project has not been saved yet", 10_000)
        return 1

    def save_copy(self) -> bool:
        """Write the project somewhere else and carry on editing this one.

        Save As moves where the project lives; this does not. It is what you
        want before trying something -- a snapshot you can go back to -- and
        the distinction matters because Save As silently changes what the next
        Ctrl+S overwrites.
        """
        path, _ = QFileDialog.getSaveFileName(
            self, "Save a copy", self._start_directory(),
            f"EC7Edit projects (*{PROJECT_SUFFIX})",
        )
        if not path:
            return False
        if not path.endswith(PROJECT_SUFFIX):
            path += PROJECT_SUFFIX
        if self.project_path is not None and Path(path) == self.project_path:
            self._error("That is this project",
                        "A copy has to go somewhere else. Use Save to write "
                        "this one.")
            return False
        try:
            save_project(self.project, Path(path))
        except Exception as error:
            self._error("Could not write the copy", str(error))
            return False
        # Deliberately not touched: project_path, the dirty flag, the identity.
        # The copy is a copy.
        self.settings.remember_project(path)
        self.statusBar().showMessage(f"Wrote a copy to {Path(path).name}", 4000)
        return True

    def preflight(self, maps) -> list:
        """Every error in the maps about to leave the editor.

        The plan's rule is that an export-blocking invariant has a diagnostic
        and the diagnostic blocks the export: a WAD the engine refuses to load,
        or loads into an unplayable floor, is worse than a refusal here,
        because it fails somewhere with no idea what is wrong. Warnings do not
        block -- an unfinished map is a normal thing to want to look at.
        """
        if self.catalog is None:
            return []
        blocking = []
        for document in maps:
            for problem in validate_map(document, self.catalog,
                                        profile=self._map_profile(document)):
                if problem.severity is Severity.ERROR:
                    blocking.append((document, problem))
        return blocking

    def _preflight_refused(self, blocking, what: str) -> bool:
        """Report a refused export. True when the caller must stop."""
        if not blocking:
            return False
        lines = [f"{document.lump_name} {document.name}: {problem.message}"
                 for document, problem in blocking[:6]]
        if len(blocking) > 6:
            lines.append(f"...and {len(blocking) - 6} more")
        self._error(f"{what} has errors",
                    "This will not play correctly, so it has not been written:\n\n"
                    + "\n".join(lines)
                    + "\n\nThe Problems panel lists them all; some can be fixed "
                      "with one click.")
        return True

    def export_preview(self, only: str | None = None) -> None:
        if not self.project.maps:
            self._error("Nothing to export", "This project has no maps yet.")
            return
        chosen = [d for d in self.project.maps if only is None or d.uuid == only]
        if self._preflight_refused(self.preflight(chosen), "This export"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export preview WAD", self._start_directory(), "WAD files (*.wad)"
        )
        if not path:
            return
        from ec7edit_core.paths import OutputGuard, atomic_write
        from ec7edit_core.wad import build_preview_wad

        try:
            blob = build_preview_wad([(d.lump_name, d.to_record()) for d in chosen])
            guard = OutputGuard()
            if self.settings.profile.data_dir:
                guard = OutputGuard(protected_roots=(Path(self.settings.profile.data_dir),))
            written = atomic_write(path, blob, guard=guard)
        except (OSError, Ec7EditError) as error:
            self._error("Could not export", str(error))
            return
        self.statusBar().showMessage(f"Exported {written.name} ({len(blob)} bytes)", 6000)

    def export_archive(self) -> bool:
        """Write a complete MAPTEMP.CO7: your maps in their slots, the rest
        of the game's untouched.

        Explicitly private, and the editor says so before it writes anything.
        The output is a copy of a retail archive with some floors swapped, so
        it is the user's own game data and it is not shareable -- unlike a
        preview WAD, which holds only what they made. Nothing about this is
        automatic: it is a separate command, it names its output, and it
        refuses to write anywhere near the data it read.
        """
        if not self.project.maps:
            self._error("Nothing to export", "This project has no maps yet.")
            return False
        if self._preflight_refused(self.preflight(self.project.maps),
                                   "This archive"):
            return False

        source, _ = QFileDialog.getOpenFileName(
            self, "The archive to build on",
            self.settings.profile.data_dir or self._start_directory(),
            "Corridor 7 archives (MAPTEMP.CO7 *.CO7);;All files (*)")
        if not source:
            return False

        if QMessageBox.warning(
            self, "This output contains the game's own maps",
            f"The file this writes is a copy of {Path(source).name} with "
            f"{len(self.project.maps)} map(s) replaced. Every floor you did not "
            "edit is copied from it unchanged.\n\n"
            "That makes the result your own game data: keep it to yourself. "
            "To share a map, export a preview WAD instead -- that holds only "
            "what you made.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return False

        try:
            identity = SourceIdentity.probe(source)
            archive = read_archive(source)
        except (OSError, Ec7EditError) as error:
            self._error("Could not read that archive", str(error))
            return False

        # A map imported from a different copy of the game is a map whose slot
        # may mean something else here. Worth saying; not worth refusing.
        strangers = {d.lump_name for d in self.project.maps
                     if d.source is not None and d.source.sha256
                     and d.source.sha256 != identity.digest}
        if strangers and QMessageBox.question(
            self, "These maps came from a different archive",
            f"{', '.join(sorted(strangers))} were imported from an archive with "
            "different contents. Their slots may not mean the same thing "
            "here.\n\nGo ahead anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return False

        path, _ = QFileDialog.getSaveFileName(
            self, "Write the archive", self._start_directory(),
            "Corridor 7 archives (*.CO7);;All files (*)")
        if not path:
            return False

        from ec7edit_core.archive import replace_records
        from ec7edit_core.paths import OutputGuard, atomic_write

        try:
            replacements = {d.slot: d.to_record() for d in self.project.maps}
            blob = replace_records(archive, replacements)
            guard = OutputGuard.for_source(source)
            written = atomic_write(path, blob, guard=guard)
            identity.verify_unchanged()
            # Read it back before claiming it worked: an archive that does not
            # parse is worse than no archive, because it is discovered by the
            # engine hours later.
            check = read_archive(written)
        except (OSError, Ec7EditError) as error:
            self._error("Could not write the archive", str(error))
            return False

        self._export_report(written, len(blob), archive, check, replacements)
        return True

    def _export_report(self, written, size, before, after, replacements) -> None:
        """What the export changed, said once, in the panel and the status bar.

        The plan calls this the minimal diff summary: not a byte report, just
        enough to answer "did that do what I meant" without opening the file.
        """
        replaced = sorted(replacements)
        untouched = len(before.records) - len(replaced)
        lines = [
            f"Wrote {written.name} — {size:,} bytes, {len(after.records)} maps.",
            f"Replaced: {', '.join(f'MAP{n:02d}' for n in replaced)}.",
            f"Copied unchanged: {untouched} map(s).",
        ]
        self.problems.clear()
        for line in lines:
            item = QListWidgetItem(line)
            item.setToolTip("Export report")
            self.problems.addItem(item)
        self._problems = []
        self._problems_revision = self.project.revision
        self.problem_status.setText(lines[0])
        self.statusBar().showMessage(lines[0], 8000)

    # -- maps -------------------------------------------------------------

    def open_map(self, uuid: str) -> MapTab:
        for index in range(self.tabs.count()):
            if self.tabs.widget(index).map_uuid == uuid:
                self.tabs.setCurrentIndex(index)
                return self.tabs.widget(index)
        document = self.project.map_by_uuid(uuid)
        tab = MapTab(document, self.catalog, self)
        tab.canvas.hovered.connect(self._on_hover)
        tab.canvas.pressed.connect(self._on_press)
        tab.canvas.dragged.connect(self.tools.drag)
        tab.canvas.released.connect(self.tools.release)
        index = self.tabs.addTab(tab, f"{document.lump_name} {document.name}")
        self.tabs.setCurrentIndex(index)
        self._apply_wall_colours()
        return tab

    @property
    def current_tab(self) -> MapTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, MapTab) else None

    def _close_tab(self, index: int) -> None:
        self.tabs.removeTab(index)

    def _on_tab_changed(self, index: int) -> None:
        tab = self.current_tab
        if tab is not None:
            self.tools.set_document(self.project.map_by_uuid(tab.map_uuid))
        self._refresh_title()

    def _on_press(self, x: int, y: int, button: int) -> None:
        tab = self.current_tab
        if tab is None:
            return
        document = self.project.map_by_uuid(tab.map_uuid)
        self.tools.set_document(document)
        self.tools.press(x, y, button)
        self.inspector.show_cell(self.project.map_by_uuid(tab.map_uuid), x, y)

    def _on_picked(self, plane: int, value: int) -> None:
        """The eyedropper selects the catalogue entry it found."""
        if self.catalog is None:
            return
        entry = self.catalog.for_value(plane, value)
        if entry is None:
            return
        self.selected_entry = entry
        self.tools.set_entry(entry)
        self.selection_label.setText(f"<b>{entry.name}</b> — raw {entry.value}")

    def _on_inspector_change(self, plane: int, x: int, y: int, value: int) -> None:
        tab = self.current_tab
        if tab is None:
            return
        document = self.project.map_by_uuid(tab.map_uuid)
        from ec7edit_core.commands import write_words

        self.run_command(write_words(document, [(plane, x, y, value)], label="Change property"))
        self.inspector.show_cell(self.project.map_by_uuid(tab.map_uuid), x, y)

    def _on_problem_activated(self, item) -> None:
        """Jump the inspector to the cell a diagnostic names."""
        cell = item.data(Qt.UserRole)
        tab = self.current_tab
        if cell and tab is not None:
            self.inspector.show_cell(self.project.map_by_uuid(tab.map_uuid), *cell)

    # -- the maps list ------------------------------------------------------

    def _map_context_menu(self, point) -> None:
        """Right-click on a map. Everything acts on the map you clicked, not on
        whichever one happens to be open.

        Below the last row -- and in an empty project, anywhere -- there is no
        map to act on, so the menu is just the one thing worth offering there.
        """
        item = self.map_list.itemAt(point)
        row = self.map_list.row(item) if item is not None else -1
        menu = self.build_map_menu(row)
        if menu is not None:
            menu.exec(self.map_list.mapToGlobal(point))

    def build_map_menu(self, row: int) -> "QMenu | None":
        """The menu for one row, built but not shown.

        Separate from showing it so a test can read the actions off it. A test
        that has to open a modal to find out what is in a menu is a test that
        hangs on the offscreen platform.
        """
        menu = QMenu(self)
        menu.setObjectName("map-context-menu")

        if not 0 <= row < len(self.project.maps):
            # No row under the pointer: the only thing that makes sense here is
            # starting one. Returning None instead would leave a right-click in
            # an empty project doing nothing at all, which is where somebody
            # with no maps yet is most likely to try it.
            action = menu.addAction("&New map…")
            action.setObjectName("new-map")
            action.triggered.connect(lambda: self.new_map())
            return menu

        document = self.project.maps[row]
        actions = [
            ("&New map…", lambda: self.new_map()),
            (None, None),
            ("&Open", lambda: self.open_map(document.uuid)),
            ("&Rename…", lambda: self.rename_map(document.uuid)),
            ("Change &slot…", lambda: self.change_slot(document.uuid)),
            ("D&uplicate", lambda: self.duplicate_map(document.uuid)),
            (None, None),
            ("&Check this map", lambda: (self.open_map(document.uuid), self.validate())),
            ("&Test in EC7Wolf", lambda: (self.open_map(document.uuid), self.playtest())),
            ("&Export this map…", lambda: self.export_preview(only=document.uuid)),
            (None, None),
            ("&Delete", lambda: self.delete_map(document.uuid)),
        ]
        for title, slot in actions:
            if title is None:
                menu.addSeparator()
                continue
            action = menu.addAction(title)
            action.setObjectName(title.lower().replace("&", "").replace("…", "")
                                 .replace(" ", "-"))
            action.triggered.connect(slot)
        return menu

    def rename_map(self, uuid: str, name: str | None = None) -> bool:
        """Rename a map. This replaces the whole 16-byte field, deliberately."""
        document = self.project.map_by_uuid(uuid)
        if name is None:
            name, accepted = QInputDialog.getText(
                self, "Rename map", "Name (15 characters, plain ASCII):",
                text=document.name,
            )
            if not accepted:
                return False
        from ec7edit_core.commands import rename_map as rename_command

        try:
            command = rename_command(document, name)
        except Ec7EditError as error:
            self._error("That name will not fit", str(error))
            return False
        self.run_command(command)
        self._refresh()
        return True

    def change_slot(self, uuid: str, slot: int | None = None) -> bool:
        """Change which MAPxx a map exports as."""
        document = self.project.map_by_uuid(uuid)
        if slot is None:
            slot, accepted = QInputDialog.getInt(
                self, "Change slot", "Export as MAP:", document.slot, 1, 100)
            if not accepted:
                return False
        taken = {other.slot: other for other in self.project.maps if other.uuid != uuid}
        if slot in taken:
            self._error(
                "That slot is taken",
                f"MAP{slot:02d} is already {taken[slot].name!r}. Two maps in one slot "
                "would shadow each other in the export.",
            )
            return False
        from ec7edit_core.commands import set_slot

        self.run_command(set_slot(document, slot))
        self._refresh()
        return True

    def duplicate_map(self, uuid: str) -> bool:
        """Copy a map into the next free slot, with its own identity."""
        from dataclasses import replace as _replace

        from ec7edit_core.commands import add_map
        from ec7edit_core.document import new_uuid

        document = self.project.map_by_uuid(uuid)
        used = {other.slot for other in self.project.maps}
        slot = next((n for n in range(1, 101) if n not in used), None)
        if slot is None:
            self._error("No free slot", "This project already fills MAP01 to MAP100.")
            return False

        copy = _replace(document, uuid=new_uuid(), slot=slot, source=document.source)
        self.run_command(add_map(copy, self.project.index_of(uuid) + 1,
                                 label=f"Duplicate {document.name}"))
        self._refresh()
        self.open_map(copy.uuid)
        return True

    def delete_map(self, uuid: str, *, confirm: bool = True) -> bool:
        """Remove a map. Undoable, which is why it is a command and not a pop."""
        document = self.project.map_by_uuid(uuid)
        if confirm:
            answer = QMessageBox.question(
                self, "Delete map",
                f"Delete {document.lump_name} {document.name!r} from this project?\n\n"
                "Undo will bring it back.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False

        from ec7edit_core.commands import remove_map

        self.run_command(remove_map(self.project, uuid))
        self._refresh()
        self.statusBar().showMessage(f"Deleted {document.lump_name}", 4000)
        return True

    def _on_map_selected(self, row: int) -> None:
        if 0 <= row < len(self.project.maps):
            self.open_map(self.project.maps[row].uuid)

    def _on_hover(self, x: int, y: int) -> None:
        tab = self.current_tab
        if tab is None or x < 0:
            self._cell_label.setText("")
            return
        document = self.project.map_by_uuid(tab.map_uuid)
        words = [document.cell(plane, x, y) for plane in range(3)]
        self._cell_label.setText(f"({x}, {y})  {words[0]} / {words[1]} / {words[2]}")

    # -- palette ----------------------------------------------------------

    def _refresh_palette(self) -> None:
        if self.catalog is None:
            return
        index = self.palette_tabs.currentIndex()
        if index < 0:
            return
        _, category = PALETTE_TABS[index]
        if category == "prefabs":
            self._refresh_prefabs()
            return
        entries = CatalogFilter(self.catalog).entries(
            category=category, query=self.search.text()
        )
        if self.used_only.isChecked():
            used = self.used_values()
            entries = [entry for entry in entries
                       if any((entry.plane, value) in used for value in entry.values)]
        self.palette_models[category].set_entries(entries)

    def _refresh_prefabs(self) -> None:
        """Rebuild the compound-tool list, honouring the search box."""
        query = self.search.text().strip().lower()
        self.prefab_list.clear()
        for prefab in PREFABS:
            haystack = " ".join((prefab.name, prefab.description, prefab.key,
                                 str(prefab.writes[0].value))).lower()
            if query and query not in haystack:
                continue
            item = QListWidgetItem(prefab.name + ("  (Advanced)" if prefab.advanced else ""))
            item.setToolTip(f"{prefab.description}\n\nSource: {prefab.evidence}")
            item.setData(Qt.UserRole, prefab.key)
            self.prefab_list.addItem(item)

    def _on_prefab_chosen(self, current, _previous) -> None:
        if current is None:
            return
        prefab = prefab_by_key(current.data(Qt.UserRole))
        if prefab is None:
            return
        self.tools.cancel_pending()
        self.tools.set_prefab(prefab)
        self.action_rotate.setVisible(prefab.rotatable)
        self.select_tool(Tool.PREFAB)
        needs = "; ".join(check.why for check in prefab.preconditions) or "nothing in particular"
        self.selection_label.setText(
            f"<b>{prefab.name}</b><br>{prefab.description}<br><i>Needs: {needs}</i>"
        )

    def _on_prefab_refused(self, problems) -> None:
        self.problems.clear()
        for problem in problems:
            item = QListWidgetItem(f"{problem.severity.name.lower()}: {problem.message}"
                                   + (f"  [{problem.where}]" if problem.where else ""))
            item.setToolTip(problem.code)
            self.problems.addItem(item)

    #: Tools that act on whatever is armed rather than on the palette entry.
    #: Picking something from a palette has to take you out of these, or the
    #: next click still does the old thing.
    _ARMED_TOOLS = (Tool.POINTER, Tool.EYEDROPPER, Tool.PREFAB, Tool.TRANSPORTER)

    def _on_palette_clicked(self, index) -> None:
        entry = index.data(EntryRole)
        if entry is None:
            return
        self.selected_entry = entry
        self.tools.set_entry(entry)

        # Choosing a wall means you want to paint a wall. A structure left
        # armed from the Structures tab, or half a transporter waiting for its
        # second click, would otherwise swallow the click and place the old
        # thing -- with the palette showing the new one as selected.
        self.tools.set_prefab(None)
        self.tools.cancel_pending()
        self.action_rotate.setVisible(False)
        if self.tools.tool in self._ARMED_TOOLS:
            self.select_tool(Tool.BRUSH)

        self.selection_label.setText(
            f"<b>{entry.name}</b> — raw {entry.value} on plane {entry.plane}"
            + (f"<br>{entry.description}" if entry.description else "")
        )

    selected_entry = None

    # -- view -------------------------------------------------------------

    def zoom_in(self) -> None:
        if self.current_tab:
            self.current_tab.canvas.zoom_in()

    def zoom_out(self) -> None:
        if self.current_tab:
            self.current_tab.canvas.zoom_out()

    def toggle_grid(self) -> None:
        for index in range(self.tabs.count()):
            self.tabs.widget(index).canvas.set_show_grid(self.action_grid.isChecked())

    def reset_layout(self) -> None:
        """Put the docks back. The escape hatch for a window restored off-screen."""
        self.settings.reset_layout()
        for dock, area in (
            (self.maps_dock, Qt.LeftDockWidgetArea),
            (self.palette_dock, Qt.RightDockWidgetArea),
            (self.inspector_dock, Qt.RightDockWidgetArea),
            (self.problems_dock, Qt.BottomDockWidgetArea),
        ):
            dock.setFloating(False)
            dock.show()
            self.addDockWidget(area, dock)
        self.resize(1180, 760)
        self.statusBar().showMessage("Layout reset", 4000)

    # -- editing ----------------------------------------------------------

    def run_command(self, command) -> None:
        """The one path by which a map changes."""
        self.project = self.history.do(self.project, command)
        self.pool.set_revision(self.project.revision)
        # Orphans first: a command can now remove a map, so a tab may be
        # pointing at something that is no longer in the project, and both the
        # canvas sync and the tool below would ask for it by id.
        self._close_orphan_tabs()
        self._sync_canvases()
        tab = self.current_tab
        if tab is None:
            self.tools.set_document(None)
        else:
            # The controller holds a snapshot, and an immutable document means
            # the old one would keep reporting the words from before this edit.
            self.tools.set_document(self.project.map_by_uuid(tab.map_uuid))
        self._refresh_title()
        # Continuous validation: the cheap rules on every edit, the whole set
        # when the hand stops. Painting a wall must not pay for a reachability
        # flood, and a panel that only updates on F8 is a panel describing a
        # map that no longer exists.
        self._revalidate_soon()
        self.project_changed.emit()

    def _revalidate_soon(self) -> None:
        if self.catalog is None or self.current_tab is None:
            return
        self.validate(quick=True)
        self._validate_timer.start()

    def undo(self) -> None:
        self.project = self.history.undo(self.project)
        self._close_orphan_tabs()
        self._sync_canvases()
        self._refresh()

    def redo(self) -> None:
        self.project = self.history.redo(self.project)
        self._close_orphan_tabs()
        self._sync_canvases()
        self._refresh()

    def _close_orphan_tabs(self) -> None:
        """Shut tabs whose map is no longer in the project.

        A command can now add or remove a map, so undo and redo can leave a tab
        pointing at something that is not there.
        """
        alive = {document.uuid for document in self.project.maps}
        for index in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(index).map_uuid not in alive:
                self.tabs.removeTab(index)

    # -- clipboard ----------------------------------------------------------

    clipboard = None

    def copy_selection(self) -> bool:
        """Copy the pointer selection. All three planes, always.

        Copying only what is visible would silently drop the zone under the
        floor and whatever plane 2 holds, and the paste would look right until
        somebody played it.
        """
        tab = self.current_tab
        selection = self.tools.selection
        if tab is None or selection.empty:
            self.statusBar().showMessage("Select an area first, with the Select tool", 4000)
            return False
        document = self.project.map_by_uuid(tab.map_uuid)
        try:
            self.clipboard = copy_region(
                document, selection.x, selection.y, selection.width, selection.height
            )
        except ValueError as error:
            self._error("Could not copy", str(error))
            return False
        self.statusBar().showMessage(
            f"Copied {self.clipboard.width}x{self.clipboard.height} cells", 4000)
        return True

    def paste_clipboard(self) -> bool:
        """Paste at the selection's corner, as one undo step."""
        tab = self.current_tab
        if tab is None or self.clipboard is None:
            self.statusBar().showMessage("Nothing copied yet", 4000)
            return False
        document = self.project.map_by_uuid(tab.map_uuid)
        selection = self.tools.selection
        writes = paste_writes(document, self.clipboard, selection.x, selection.y)
        if not writes:
            self.statusBar().showMessage("That paste would land outside the map", 4000)
            return False
        from ec7edit_core.commands import write_words

        self.run_command(write_words(document, writes, label="Paste"))
        self.statusBar().showMessage(f"Pasted at ({selection.x}, {selection.y})", 4000)
        return True

    def rotate_clipboard(self) -> bool:
        """Turn what was copied, rewriting facings through the catalogue."""
        if self.clipboard is None:
            self.statusBar().showMessage("Nothing copied yet", 4000)
            return False
        self.clipboard = rotate_clip(self.clipboard, 1, self.catalog)
        self.statusBar().showMessage(
            f"Turned; now {self.clipboard.width}x{self.clipboard.height}", 4000)
        return True

    def flip_clipboard_h(self) -> bool:
        return self._flip("horizontal")

    def flip_clipboard_v(self) -> bool:
        return self._flip("vertical")

    def _flip(self, axis: str) -> bool:
        if self.clipboard is None:
            self.statusBar().showMessage("Nothing copied yet", 4000)
            return False
        self.clipboard = flip_clip(self.clipboard, axis, self.catalog)
        self.statusBar().showMessage(f"Flipped {axis}", 4000)
        return True

    # -- statistics ---------------------------------------------------------

    def map_statistics(self) -> dict:
        """What is actually on the open map, counted by what it means."""
        tab = self.current_tab
        if tab is None or self.catalog is None:
            return {}
        document = self.project.map_by_uuid(tab.map_uuid)
        from collections import Counter

        from .tools import EMPTY_OBJECT

        counts = Counter()
        for plane in (0, 1):
            for value in document.planes.planes[plane]:
                if plane == 1 and value in (0, EMPTY_OBJECT):
                    continue
                entry = self.catalog.for_value(plane, value)
                counts[entry.category if entry else "unknown"] += 1
        floor = sum(1 for v in document.planes.planes[0] if v == 0 or 256 <= v <= 300)
        return {
            "cells": document.planes.cell_count,
            "floor": floor,
            "walls": counts.get("walls", 0),
            "specials": counts.get("specials", 0),
            "objects": counts.get("objects", 0),
            "enemies": counts.get("enemies", 0),
            "starts": counts.get("starts", 0),
            "unknown": counts.get("unknown", 0),
        }

    def show_statistics(self) -> None:
        stats = self.map_statistics()
        if not stats:
            self.statusBar().showMessage("Open a map first", 4000)
            return
        QMessageBox.information(
            self, "Map statistics",
            "\n".join(f"{name.title():10} {count}" for name, count in stats.items()),
        )

    def used_values(self) -> set:
        """Every `(plane, value)` the open map actually uses, for the filter."""
        tab = self.current_tab
        if tab is None:
            return set()
        document = self.project.map_by_uuid(tab.map_uuid)
        used = set()
        for plane in (0, 1):
            used |= {(plane, value) for value in set(document.planes.planes[plane])}
        return used

    # -- validation and playtest -------------------------------------------

    def assign_sound_areas(self) -> int:
        """Repair a floor whose cells carry no sound area.

        Offered as a command because there is no other reasonable way to do it
        by hand: the fill tool reaches one connected region per click, and a
        map with rooms behind doors has as many regions as it has rooms. It is
        also a repair nobody should have to make -- the editor floored new maps
        with word 0 until 2026-08-31, and every map made before that has this.
        """
        tab = self.current_tab
        if tab is None:
            return 0
        from ec7edit_core.commands import write_words

        document = self.project.map_by_uuid(tab.map_uuid)
        writes = sound_area_writes(document)
        if not writes:
            self.statusBar().showMessage(
                "Every floor cell already has a sound area", 4000)
            return 0
        areas = sorted({value for *_, value in writes})
        self.run_command(write_words(document, writes,
                                     label="Give the floor sound areas"))
        self.statusBar().showMessage(
            f"Gave {len(writes)} floor cell(s) "
            f"{'an area' if len(areas) == 1 else f'{len(areas)} areas'} "
            f"({', '.join(str(a) for a in areas)})", 6000)
        self.validate()
        return len(writes)

    def _next_session_id(self) -> str:
        """A short id, unique within this run of the editor.

        The engine echoes it on every event, which is what lets the reader tell
        this launch's output from another's -- and from anything the map under
        test decided to print. A counter is enough: two editors are two
        workspaces, and a stale directory from a previous run is not a session
        anything is still listening to.
        """
        self._session_counter += 1
        return f"ec7edit-{self._session_counter:04d}"

    def _map_profile(self, document) -> "Profile":
        """Which rules apply to this map, from the slot it is exported to."""
        return profile_for_slot(document.slot)

    def validate(self, *, quick: bool = False) -> list:
        """Check the open map and fill the Problems panel.

        `quick` runs only the rules whose answer is local to the cells that
        changed and keeps the previous answer for the rest. That is what runs
        while somebody is painting; the full pass runs when they stop, and on
        anything that has to be right, such as an export.
        """
        tab = self.current_tab
        if tab is None or self.catalog is None:
            self.problems.clear()
            self._problems = []
            self._problems_revision = -1
            return []
        document = self.project.map_by_uuid(tab.map_uuid)
        profile = self._map_profile(document)
        if quick:
            problems = validate_local(document, self.catalog, profile=profile,
                                      previous=self._problems)
        else:
            problems = validate_map(document, self.catalog, profile=profile)
            problems.extend(check_transporters(document))
            for x, y in door_cells(document, self.catalog):
                problems.extend(check_door(document, x, y))
        self._problems = problems
        self._problems_revision = self.project.revision
        self._repaint_problems()
        self.statusBar().showMessage(summarise(problems), 6000)
        return problems

    def _repaint_problems(self) -> None:
        """Refill the list from the last result, honouring the severity floor."""
        floor = self.problem_filter.currentData()
        self.problems.clear()
        shown = 0
        for problem in self._problems:
            if floor is not None and problem.severity < floor:
                continue
            shown += 1
            item = QListWidgetItem(f"{problem.severity.name.lower()}: {problem.message}"
                                   + (f"  [{problem.where}]" if problem.where else ""))
            item.setToolTip(f"{problem.code}\n{problem.message}")
            item.setData(Qt.UserRole, problem.cell)
            item.setData(Qt.UserRole + 1, problem.fix)
            self.problems.addItem(item)
        hidden = len(self._problems) - shown
        stale = self._problems_revision != self.project.revision
        parts = [summarise(self._problems)]
        if hidden:
            parts.append(f"{hidden} hidden by the filter")
        if stale:
            # Said rather than silently shown: a panel describing a map that
            # has since changed is worse than an empty one, because it looks
            # current.
            parts.append("from an earlier edit — press F8 to recheck")
        self.problem_status.setText("  ·  ".join(parts))
        self._on_problem_selected(self.problems.currentItem(), None)

    def _on_problem_selected(self, current, _previous) -> None:
        fix = current.data(Qt.UserRole + 1) if current is not None else ""
        self.problem_fix.setEnabled(bool(fix))
        self.problem_fix.setText(fix_label(fix) if fix else "Fix this")

    def apply_fix(self) -> int:
        """Apply the selected problem's repair, as one undoable command."""
        from ec7edit_core.commands import write_words

        item = self.problems.currentItem()
        tab = self.current_tab
        if item is None or tab is None:
            return 0
        fix = item.data(Qt.UserRole + 1)
        if not fix:
            return 0
        document = self.project.map_by_uuid(tab.map_uuid)
        writes = fix_writes(fix, document)
        if not writes:
            return 0
        self.run_command(write_words(document, writes, label=fix_label(fix)))
        self.validate()
        return len(writes)

    def playtest(self) -> bool:
        """Export the open map and start the engine on it.

        Exports to the workspace, never beside the game data: the export is a
        file this editor wrote, and it has no business landing among files it
        must not touch.
        """
        tab = self.current_tab
        if tab is None:
            self._error("Nothing to test", "Open a map first.")
            return False
        profile = self.settings.profile
        if not profile.engine_path or not profile.data_dir:
            self._error("No engine configured",
                        "Tools -> Setup, and choose an EC7Wolf executable and your game data.")
            return False

        document = self.project.map_by_uuid(tab.map_uuid)

        # Check before launching. The engine's answer to a map with no player
        # start is to print "No player 1 start!" and exit, which from the
        # outside is indistinguishable from a crash -- the window appears and
        # vanishes. Better to say what is wrong while the editor still has the
        # user's attention.
        blocking = [problem for problem in self.validate()
                    if problem.severity is Severity.ERROR]
        if blocking:
            self._error(
                "This map will not load yet",
                blocking[0].message
                + (f"\n\nAt {blocking[0].where}." if blocking[0].where else "")
                + (f"\n\nand {len(blocking) - 1} more; see the Problems panel."
                   if len(blocking) > 1 else ""),
            )
            return False

        # One directory per session, holding the export, the engine's config,
        # its saves and the log. Never the player's own: a playtest that wrote
        # into those would change the game somebody else plays here.
        workspace = Path(profile.workspace_dir or Path.home()) / ".ec7edit-playtest"
        session = self._next_session_id()
        session_dir = workspace / session
        target = session_dir / f"{document.lump_name.lower()}-preview.wad"

        import hashlib

        from ec7edit_core.paths import OutputGuard, atomic_write
        from ec7edit_core.wad import build_preview_wad

        try:
            blob = build_preview_wad([(document.lump_name, document.to_record())])
            guard = OutputGuard(protected_roots=(Path(profile.data_dir),))
            atomic_write(target, blob, guard=guard)
            plan = build_launch_plan(
                executable=profile.engine_path,
                data_dir=profile.data_dir,
                preview_wad=target,
                marker=document.lump_name,
                session=session,
                session_dir=session_dir,
                # What was tested, so the log can be matched back to it. A log
                # that does not say which version of the map it describes is a
                # log you cannot trust a week later.
                export_digest=hashlib.sha256(blob).hexdigest(),
                revision=self.project.revision,
            )
        except (OSError, Ec7EditError) as error:
            self._error("Could not start a playtest", str(error))
            return False

        return self.start_session(plan, document.lump_name)

    # -- the playtest session ---------------------------------------------

    def start_session(self, plan, label: str) -> bool:
        """Run a launch plan under a QProcess and watch what it says.

        QProcess rather than subprocess because the editor has to stay usable
        while the game runs: output arrives on a signal, on the GUI thread,
        with nobody blocked on a pipe. The old code handed the process a file
        and forgot about it, which meant the editor could not tell a playtest
        that worked from one that never found the map -- and left the engine
        running when the editor closed.
        """
        if self.session is not None and self.session.running:
            self._error("A playtest is already running",
                        "Stop it first, or let it finish.")
            return False

        self.session = Session(plan)
        self._session_log_path = (plan.session_dir / "playtest.log"
                                  if plan.session_dir else None)
        self._session_lines = []

        process = QProcess(self)
        process.setProgram(str(plan.executable))
        process.setArguments(list(plan.arguments))
        process.setWorkingDirectory(str(plan.cwd))
        # One channel: the engine reports some failures on stderr -- "No player
        # 1 start!" among them -- and reading only stdout would lose exactly
        # the messages a playtest exists to surface.
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._on_session_output)
        process.finished.connect(
            lambda code, _status: self._on_session_finished(code))
        process.errorOccurred.connect(self._on_session_error)

        self.process = process
        self.session.started()
        self._refresh_session_ui()
        process.start()
        if not process.waitForStarted(5000):
            self.session.finished(-1)
            self._error("The engine did not start",
                        f"{plan.executable}\n\n{process.errorString()}")
            self._refresh_session_ui()
            return False
        self.statusBar().showMessage(f"Testing {label} in EC7Wolf", 6000)
        return True

    def _on_session_output(self) -> None:
        if self.process is None or self.session is None:
            return
        # Whole lines only. A read can land mid-line, and half of an event is
        # not an event -- the tail is kept for the next read rather than
        # parsed as if it were complete.
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        self._session_tail += text
        *lines, self._session_tail = self._session_tail.split("\n")
        for line in lines:
            self.session.feed(line)
            self._session_lines.append(line)
        if lines:
            self._refresh_session_ui()

    def _on_session_error(self, _error) -> None:
        if self.process is not None:
            self._note_problem(f"Playtest: {self.process.errorString()}")

    def _on_session_finished(self, code: int) -> None:
        if self.session is None:
            return
        if self._session_tail:
            self.session.feed(self._session_tail)
            self._session_lines.append(self._session_tail)
            self._session_tail = ""
        self._session_counter = 0
        self.session.finished(code)
        self._write_session_log()
        self._refresh_session_ui()
        if self.session.state is SessionState.FAILED:
            # Said in the Test Log, not in a modal. This arrives on a signal
            # from a process ending, which can be at any moment -- including
            # while the user is mid-gesture in the editor -- and a dialog that
            # steals focus then is worse than a panel that is already showing
            # the answer. The dock raises itself so it cannot be missed.
            self._note_problem(f"Playtest failed: {self.session.describe()}")
            self.test_log_dock.show()
            self.test_log_dock.raise_()
            self.statusBar().showMessage(
                f"Playtest failed: {self.session.describe()}", 12000)

    def _write_session_log(self) -> None:
        """Keep the log beside the session, tagged with what was tested."""
        if self._session_log_path is None or self.session is None:
            return
        try:
            self._session_log_path.parent.mkdir(parents=True, exist_ok=True)
            header = [
                f"# session {self.session.plan.session}",
                f"# revision {self.session.plan.revision}",
                f"# export {self.session.plan.export_digest}",
                f"# {self.session.plan.described()}",
                "",
            ]
            self._session_log_path.write_text(
                "\n".join(header + self._session_lines) + "\n", encoding="utf-8")
        except OSError:
            pass  # a log we could not write must not break the run it describes

    def stop_session(self) -> bool:
        """Ask the engine to close, and make sure it does."""
        if self.process is None or self.session is None or not self.session.running:
            return False
        self.session.stopping()
        self._refresh_session_ui()
        self.process.terminate()
        if not self.process.waitForFinished(3000):
            # It did not go. A playtest left running is a window the user
            # cannot get rid of and a process the next launch will refuse to
            # start alongside.
            self.process.kill()
            self.process.waitForFinished(2000)
        return True

    def reconcile_orphan(self) -> bool:
        """At shutdown: never leave a playtest running without an editor.

        The engine is a child of this process. Closing the editor and leaving
        it behind means a window nobody owns, still writing to a session
        directory the editor may reuse.
        """
        if self.process is None:
            return False
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return False
        self.stop_session()
        return True

    def _refresh_session_ui(self) -> None:
        running = self.session is not None and self.session.running
        self.action_stop_test.setEnabled(running)
        if self.session is None:
            self.test_log_status.setText("No playtest has been run yet")
            return
        self.test_log_status.setText(
            f"{self.session.state.value}: {self.session.describe()}")
        self.test_log.clear()
        for line in self._session_lines[-400:]:
            self.test_log.addItem(line)
        self.test_log.scrollToBottom()

    def _sync_canvases(self) -> None:
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            try:
                tab.canvas.set_document(self.project.map_by_uuid(tab.map_uuid))
            except Ec7EditError:
                pass  # the map was removed; the tab closes on the next refresh

    # -- setup ------------------------------------------------------------

    def run_setup(self) -> bool:
        """Show first-run setup. Returns whether a profile was saved.

        `QDialog.DialogCode.Accepted`, not `dialog.Accepted`: in PySide6 the
        enum lives on the class, and reading it off an instance raises. That
        is easy to write and impossible to see until the dialog closes.
        """
        from PySide6.QtWidgets import QDialog

        from .first_run import FirstRunDialog

        dialog = FirstRunDialog(self.settings.profile, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        profile = dialog.profile()
        self.settings.profile = profile
        self.settings.sync()
        self.thumbnails.clear()
        self.open_assets(profile)
        self._refresh_palette()
        self.statusBar().showMessage("Setup saved", 4000)
        return True

    # -- housekeeping -----------------------------------------------------

    def _refresh(self) -> None:
        self.map_list.clear()
        for document in self.project.maps:
            item = QListWidgetItem(f"{document.lump_name}  {document.name}")
            item.setToolTip(f"{document.width}x{document.height}")
            self.map_list.addItem(item)
        self._refresh_palette()
        self._refresh_title()

    def _refresh_title(self) -> None:
        name = self.project_path.name if self.project_path else "Untitled"
        marker = " •" if self.project.dirty else ""
        self.setWindowTitle(f"{name}{marker} — EC7Edit")
        self.action_undo.setEnabled(self.history.can_undo)
        self.action_redo.setEnabled(self.history.can_redo)
        self.action_undo.setText(f"&Undo {self.history.undo_label}".rstrip())
        self.action_redo.setText(f"&Redo {self.history.redo_label}".rstrip())

    def _note_problem(self, message: str) -> None:
        self.problems.addItem(message)

    def _error(self, title: str, detail: str) -> None:
        self._note_problem(f"{title}: {detail}")
        QMessageBox.warning(self, title, detail)

    def _start_directory(self) -> str:
        profile = self.settings.profile
        return profile.workspace_dir or str(Path.home())

    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes",
            "This project has unsaved changes. Save before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    def _restore_layout(self) -> None:
        geometry, state = self.settings.layout()
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.save_layout(self.saveGeometry(), self.saveState())
        self.settings.sync()
        self.pool.cancel_all()
        self.pool.wait(2000)
        # Never leave a playtest running without an editor: the engine is a
        # child of this process, and closing without it means a window nobody
        # owns, still writing into a session directory the next launch reuses.
        self.reconcile_orphan()
        event.accept()

    def about(self) -> None:
        from ec7edit_core import __version__

        QMessageBox.about(
            self, "About EC7Edit",
            f"<b>EC7Edit {__version__}</b><br>"
            "A level editor for Corridor 7: Alien Invasion.<br><br>"
            "Corridor 7 and its data belong to their rights holders and are not "
            "included here. The editor reads your own copy and leaves it alone.",
        )
