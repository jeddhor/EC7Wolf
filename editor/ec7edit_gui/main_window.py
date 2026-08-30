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
    QInputDialog,
    QMenu,
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
from ec7edit_core.rules import check_door, check_transporters, door_cells
from ec7edit_core.transforms import copy_region, flip_clip, paste_writes, rotate_clip
from ec7edit_core.validation import summarise, validate_map
from ec7edit_core.document import MapDocument, ProjectDocument, SourceReference, utc_now
from ec7edit_core.errors import Ec7EditError, Severity
from ec7edit_core.paths import SourceIdentity
from ec7edit_core.prefabs import PREFABS, by_key as prefab_by_key
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
        self.recovery = RecoveryStore(Path.home() / ".local" / "share" / "ec7edit" / "recovery")

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
        action.triggered.connect(slot)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.action_new = self._action("&New project", self.new_project, QKeySequence.New)
        self.action_open = self._action("&Open project…", self.open_project, QKeySequence.Open)
        self.action_new_map = self._action("New &map…", self.new_map, "Ctrl+M",
                                           tip="Add an empty map to this project")
        self.action_import = self._action("&Import map from archive…", self.import_map, "Ctrl+I")
        self.action_save = self._action("&Save", self.save_project, QKeySequence.Save)
        self.action_save_as = self._action("Save &As…", self.save_project_as, "Ctrl+Shift+S")
        self.action_export = self._action("&Export preview WAD…", self.export_preview, "Ctrl+E")
        self.action_quit = self._action("&Quit", self.close, QKeySequence.Quit)
        for action in (self.action_new, self.action_open, self.action_new_map,
                       self.action_import):
            file_menu.addAction(action)
        file_menu.addSeparator()
        for action in (self.action_save, self.action_save_as, self.action_export):
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
        self.action_statistics = self._action("Map &statistics", self.show_statistics)
        self.action_setup = self._action("&Setup…", self.run_setup, tip="Engine, data, workspace")
        self.tools_menu.addAction(self.action_test)
        self.tools_menu.addAction(self.action_validate)
        self.tools_menu.addAction(self.action_statistics)
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

        self.action_rotate = self._action(
            "&Turn structure", self.tools.rotate_prefab, "Ctrl+R",
            tip="Turn the selected structure a quarter turn clockwise",
        )
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

    def export_preview(self, only: str | None = None) -> None:
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
            chosen = [d for d in self.project.maps if only is None or d.uuid == only]
            blob = build_preview_wad([(d.lump_name, d.to_record()) for d in chosen])
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

    # -- the maps list ------------------------------------------------------

    def _map_context_menu(self, point) -> None:
        """Right-click on a map. Everything acts on the map you clicked, not on
        whichever one happens to be open."""
        item = self.map_list.itemAt(point)
        if item is None:
            return
        menu = self.build_map_menu(self.map_list.row(item))
        if menu is not None:
            menu.exec(self.map_list.mapToGlobal(point))

    def build_map_menu(self, row: int) -> "QMenu | None":
        """The menu for one row, built but not shown.

        Separate from showing it so a test can read the actions off it. A test
        that has to open a modal to find out what is in a menu is a test that
        hangs on the offscreen platform.
        """
        if not 0 <= row < len(self.project.maps):
            return None
        document = self.project.maps[row]

        menu = QMenu(self)
        menu.setObjectName("map-context-menu")
        actions = [
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
        self.project_changed.emit()

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

    def validate(self) -> list:
        """Check the open map and fill the Problems panel."""
        tab = self.current_tab
        self.problems.clear()
        if tab is None or self.catalog is None:
            return []
        document = self.project.map_by_uuid(tab.map_uuid)
        problems = validate_map(document, self.catalog)
        problems.extend(check_transporters(document))
        for x, y in door_cells(document, self.catalog):
            problems.extend(check_door(document, x, y))
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

        # Keep what the engine says. When it refuses a map it explains itself
        # on stdout and then exits, and without this that explanation goes
        # nowhere the user will ever look.
        log = workspace / "playtest.log"
        try:
            with open(log, "w", encoding="utf-8") as stream:
                subprocess.Popen(plan.argv, cwd=str(plan.cwd),
                                 stdout=stream, stderr=subprocess.STDOUT)
        except OSError as error:
            self._error("The engine did not start", str(error))
            return False
        self._note_problem(f"Engine output: {log}")
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
