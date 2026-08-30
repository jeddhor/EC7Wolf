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

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ec7edit_core.archive import read_archive
from ec7edit_core.catalog import Catalog, load_catalog
from ec7edit_core.commands import History
from ec7edit_core.discovery import Profile, data_fingerprint
from ec7edit_core.engine_runner import build_launch_plan
from ec7edit_core.validation import summarise, validate_map
from ec7edit_core.document import MapDocument, ProjectDocument, SourceReference, utc_now
from ec7edit_core.errors import Ec7EditError
from ec7edit_core.paths import SourceIdentity
from ec7edit_core.project import (
    PROJECT_SUFFIX,
    RecoveryStore,
    load_project,
    new_project,
    project_identity,
    save_project,
)

from .inspector import Inspector
from .map_canvas import MapCanvas
from .palette_models import CatalogFilter, CatalogModel, EntryRole
from .settings import Settings
from .thumbnails import AssetSource, ThumbnailFactory
from .tools import Tool, ToolController
from .workers import WorkerPool

CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "editor_catalog.json"

PALETTE_TABS = (
    ("Walls", "walls"),
    ("Doors and Specials", "specials"),
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
        self.recovery = RecoveryStore(Path.home() / ".local" / "share" / "ec7edit" / "recovery")

        self.tools = ToolController(self)
        self.tools.command_ready.connect(self.run_command)
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
        action.triggered.connect(slot)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.action_new = self._action("&New project", self.new_project, QKeySequence.New)
        self.action_open = self._action("&Open project…", self.open_project, QKeySequence.Open)
        self.action_import = self._action("&Import map from archive…", self.import_map, "Ctrl+I")
        self.action_save = self._action("&Save", self.save_project, QKeySequence.Save)
        self.action_save_as = self._action("Save &As…", self.save_project_as, "Ctrl+Shift+S")
        self.action_export = self._action("&Export preview WAD…", self.export_preview, "Ctrl+E")
        self.action_quit = self._action("&Quit", self.close, QKeySequence.Quit)
        for action in (self.action_new, self.action_open, self.action_import):
            file_menu.addAction(action)
        file_menu.addSeparator()
        for action in (self.action_save, self.action_save_as, self.action_export):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.action_undo = self._action("&Undo", self.undo, QKeySequence.Undo)
        self.action_redo = self._action("&Redo", self.redo, QKeySequence.Redo)
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)

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
        self.action_setup = self._action("&Setup…", self.run_setup, tip="Engine, data, workspace")
        self.tools_menu.addAction(self.action_test)
        self.tools_menu.addAction(self.action_validate)
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

        self.filled_box = QCheckBox("Filled", self)
        self.filled_box.setAccessibleName("Filled rectangle")
        self.filled_box.toggled.connect(
            lambda checked: setattr(self.tools, "filled_rectangle", checked)
        )
        bar.addWidget(self.filled_box)

    def select_tool(self, tool: Tool) -> None:
        self.tools.set_tool(tool)
        action = self.tool_actions.get(tool)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _build_docks(self) -> None:
        self.map_list = QListWidget(self)
        self.map_list.setAccessibleName("Maps in this project")
        self.map_list.currentRowChanged.connect(self._on_map_selected)
        maps_dock = QDockWidget("Maps", self)
        maps_dock.setObjectName("maps-dock")
        maps_dock.setWidget(self.map_list)
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

        self.palette_tabs = QTabWidget(palette)
        self.palette_tabs.setAccessibleName("Palette")
        self.palette_models: dict[str, CatalogModel] = {}
        for title, category in PALETTE_TABS:
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

        self.inspector = Inspector(self.catalog, self)
        self.inspector.change_requested.connect(self._on_inspector_change)
        inspector_dock = QDockWidget("Inspector", self)
        inspector_dock.setObjectName("inspector-dock")
        inspector_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, inspector_dock)
        self.inspector_dock = inspector_dock

        self.problems = QListWidget(self)
        self.problems.setAccessibleName("Problems")
        self.problems.itemActivated.connect(self._on_problem_activated)
        problems_dock = QDockWidget("Problems", self)
        problems_dock.setObjectName("problems-dock")
        problems_dock.setWidget(self.problems)
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

        chosen = number if number is not None else 1
        try:
            record = archive.by_number(chosen)
        except Ec7EditError as error:
            self._error("No such map", str(error))
            return

        document = MapDocument.from_record(
            record,
            source=SourceReference(
                display_path=str(archive_path), sha256=identity.digest,
                map_number=chosen, imported_at=utc_now(),
            ),
        )
        self.project = self.project.added(document)
        self._refresh()
        self.open_map(document.uuid)
        identity.verify_unchanged()
        self.statusBar().showMessage(f"Imported {record.name.text}", 4000)

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_project_as()
        try:
            revision = save_project(self.project, self.project_path,
                                    expect_identity=self._identity)
        except Exception as error:
            self._error("Could not save", str(error))
            return False
        self.project = self.project.marked_saved(revision)
        self._identity = project_identity(self.project_path)
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

    def export_preview(self) -> None:
        if not self.project.maps:
            self._error("Nothing to export", "This project has no maps yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export preview WAD", self._start_directory(), "WAD files (*.wad)"
        )
        if not path:
            return
        from ec7edit_core.paths import OutputGuard, atomic_write
        from ec7edit_core.wad import build_preview_wad

        try:
            blob = build_preview_wad(
                [(d.lump_name, d.to_record()) for d in self.project.maps]
            )
            guard = OutputGuard()
            if self.settings.profile.data_dir:
                guard = OutputGuard(protected_roots=(Path(self.settings.profile.data_dir),))
            written = atomic_write(path, blob, guard=guard)
        except (OSError, Ec7EditError) as error:
            self._error("Could not export", str(error))
            return
        self.statusBar().showMessage(f"Exported {written.name} ({len(blob)} bytes)", 6000)

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
        entries = CatalogFilter(self.catalog).entries(
            category=category, query=self.search.text()
        )
        self.palette_models[category].set_entries(entries)

    def _on_palette_clicked(self, index) -> None:
        entry = index.data(EntryRole)
        if entry is None:
            return
        self.selected_entry = entry
        self.tools.set_entry(entry)
        if self.tools.tool in (Tool.POINTER, Tool.EYEDROPPER):
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
        self._sync_canvases()
        tab = self.current_tab
        if tab is not None:
            # The controller holds a snapshot, and an immutable document means
            # the old one would keep reporting the words from before this edit.
            self.tools.set_document(self.project.map_by_uuid(tab.map_uuid))
        self._refresh_title()
        self.project_changed.emit()

    def undo(self) -> None:
        self.project = self.history.undo(self.project)
        self._sync_canvases()
        self._refresh()

    def redo(self) -> None:
        self.project = self.history.redo(self.project)
        self._sync_canvases()
        self._refresh()

    # -- validation and playtest -------------------------------------------

    def validate(self) -> list:
        """Check the open map and fill the Problems panel."""
        tab = self.current_tab
        self.problems.clear()
        if tab is None or self.catalog is None:
            return []
        document = self.project.map_by_uuid(tab.map_uuid)
        problems = validate_map(document, self.catalog)
        for problem in problems:
            item = QListWidgetItem(f"{problem.severity.name.lower()}: {problem.message}"
                                   + (f"  [{problem.where}]" if problem.where else ""))
            item.setToolTip(problem.code)
            if problem.where.startswith("cell ("):
                numbers = problem.where[6:-1].split(",")
                item.setData(Qt.UserRole, (int(numbers[0]), int(numbers[1])))
            self.problems.addItem(item)
        self.statusBar().showMessage(summarise(problems), 6000)
        return problems

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
        workspace = Path(profile.workspace_dir or Path.home()) / ".ec7edit-playtest"
        target = workspace / f"{document.lump_name.lower()}-preview.wad"

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
            )
        except (OSError, Ec7EditError) as error:
            self._error("Could not start a playtest", str(error))
            return False

        self._note_problem(f"Playtest: {plan.described()}")
        import subprocess

        try:
            subprocess.Popen(plan.argv, cwd=str(plan.cwd))
        except OSError as error:
            self._error("The engine did not start", str(error))
            return False
        self.statusBar().showMessage(f"Testing {document.lump_name} in EC7Wolf", 6000)
        return True

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
