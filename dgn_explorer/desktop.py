"""Native Qt Widgets client; all DGN operations run in backend processes."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

from PySide6.QtCore import QObject, QProcess, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QStyle, QStyledItemDelegate, QTableView, QTabWidget, QToolBar,
    QTreeView, QVBoxLayout, QWidget,
)
from PySide6.QtXml import QDomImplementation

QDomImplementation.setInvalidDataPolicy(QDomImplementation.InvalidDataPolicy.ReturnNullNode)

from .worker import MESSAGE_LIMIT, PROTOCOL
from .workspace import json_bytes, locator_key, parse_json
from .transactions import atomic_write


class WorkerController(QObject):
    completed = Signal(dict)
    failed = Signal(dict)
    progress = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(self._started)
        self.buffer = bytearray()
        self.terminal = None
        self.request = None

    @property
    def busy(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(self, operation: str, arguments: dict):
        if self.busy:
            raise RuntimeError("Worker already running")
        self.request = {"protocol": PROTOCOL, "request_id": uuid.uuid4().hex, "operation": operation, "arguments": arguments}
        raw = json.dumps(self.request, ensure_ascii=True, allow_nan=False).encode() + b"\n"
        if len(raw) > MESSAGE_LIMIT:
            raise ValueError("Worker request exceeds limit")
        self.buffer.clear()
        self.terminal = None
        self.busyChanged.emit(True)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        if getattr(sys, "frozen", False):
            backend = Path(sys.executable).with_name("dgn-explorer.exe")
            self.process.start(str(backend), ["--worker"])
        else:
            self.process.start(sys.executable, ["-m", "dgn_explorer", "--worker"])

    def _started(self):
        self.process.write(json.dumps(self.request, ensure_ascii=True, allow_nan=False).encode() + b"\n")

    def cancel(self):
        if self.busy:
            self.process.write(json.dumps({"protocol": PROTOCOL, "request_id": self.request["request_id"], "event": "cancel"}).encode() + b"\n")
            self.progress.emit("Cancelling")

    def terminate(self):
        if self.busy:
            self.process.kill()

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > MESSAGE_LIMIT and b"\n" not in self.buffer:
            self.terminal = ("failed", {"code": 3, "message": "Oversized worker output"})
            self.process.kill()
            return
        try:
            while b"\n" in self.buffer:
                line, _, tail = self.buffer.partition(b"\n")
                self.buffer = bytearray(tail)
                if len(line) > MESSAGE_LIMIT:
                    raise ValueError("Oversized worker message")
                message = parse_json(line)
                if set(message) != {"protocol", "request_id", "event", "payload"} or message["protocol"] != PROTOCOL or message["request_id"] != self.request["request_id"]:
                    raise ValueError("Invalid worker message")
                if self.terminal is not None:
                    raise ValueError("Message after worker completion")
                if message["event"] == "progress":
                    self.progress.emit(str(message["payload"].get("stage", "Working")))
                elif message["event"] in ("completed", "failed"):
                    self.terminal = (message["event"], message["payload"])
                else:
                    raise ValueError("Unknown worker event")
        except Exception:
            self.terminal = ("failed", {"code": 3, "message": "Invalid worker output"})
            self.process.kill()

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.busyChanged.emit(False)
            self.failed.emit({"code": 5, "message": "Backend cannot start"})

    def _finished(self, code, status):
        self._read()
        self.busyChanged.emit(False)
        if self.terminal and self.terminal[0] == "completed" and code == 0 and not self.buffer and status == QProcess.ExitStatus.NormalExit:
            self.completed.emit(self.terminal[1])
        else:
            self.failed.emit(self.terminal[1] if self.terminal and self.terminal[0] == "failed" else {"code": 7, "message": "Backend exits without a complete result"})


class PropertyDelegate(QStyledItemDelegate):
    invalid = Signal(str)

    def createEditor(self, parent, option, index):
        value = index.data(Qt.ItemDataRole.UserRole)
        if type(value) is bool:
            return QCheckBox(parent)
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(editor, QCheckBox):
            editor.setChecked(value)
        else:
            editor.setText(value if isinstance(value, str) else json.dumps(value, allow_nan=False))

    def setModelData(self, editor, model, index):
        before = index.data(Qt.ItemDataRole.UserRole)
        try:
            value = editor.isChecked() if isinstance(editor, QCheckBox) else editor.text() if isinstance(before, str) else parse_json(editor.text().encode())
            model.setData(index, value, Qt.ItemDataRole.UserRole)
            model.setData(index, value if isinstance(value, str) else json.dumps(value), Qt.ItemDataRole.DisplayRole)
        except Exception:
            self.invalid.emit("Invalid typed value")


class PatchCommand(QUndoCommand):
    def __init__(self, window, before, after):
        super().__init__("Edit property")
        self.window, self.before, self.after = window, deepcopy(before), deepcopy(after)

    def redo(self):
        self.window.set_pending(self.after)

    def undo(self):
        self.window.set_pending(self.before)


class ExplorerWindow(QMainWindow):
    def __init__(self, controller=None, data_root=None):
        super().__init__()
        self.setWindowTitle("DGN Explorer")
        self.resize(1100, 720)
        self.controller = controller or WorkerController(self)
        self.controller.completed.connect(self._completed)
        self.controller.failed.connect(self._failed)
        self.controller.progress.connect(self.statusBar().showMessage)
        self.controller.busyChanged.connect(self._busy)
        self.folder = None
        self.revision = None
        self.pending = []
        self.content_drafts = {}
        self.selected = None
        self.displayed_locator = None
        self.fields = []
        self.next_cursor = None
        self.byte_offset = 0
        self.callback = None
        self.after_journal = None
        self.closing = False
        self.populating = False
        self.data_root = Path(data_root) if data_root else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        self.recent_folders = []
        try:
            recent = self.data_root / "recent-workspaces.json"
            if recent.is_file() and recent.stat().st_size <= 65536:
                values = parse_json(recent.read_bytes())
                if isinstance(values, list) and all(isinstance(value, str) for value in values):
                    self.recent_folders = values[:10]
        except (OSError, ValueError):
            pass
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self._build()
        self._refresh_recent()
        self._busy(False)

    def _action(self, menu, toolbar, text, icon, slot, shortcut=None):
        action = QAction(self.style().standardIcon(icon), text, self)
        action.setToolTip(text)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        toolbar.addAction(action)
        return action

    def _build(self):
        toolbar = QToolBar("File", self)
        self.addToolBar(toolbar)
        menu = self.menuBar().addMenu("&File")
        self.open_action = self._action(menu, toolbar, "Open DGN", QStyle.StandardPixmap.SP_DialogOpenButton, self.open_dgn, QKeySequence.StandardKey.Open)
        self.workspace_action = self._action(menu, toolbar, "Open Workspace", QStyle.StandardPixmap.SP_DirOpenIcon, self.open_workspace_dialog)
        self.recent_menu = menu.addMenu("Recent Workspaces")
        self.save_action = self._action(menu, toolbar, "Save Workspace", QStyle.StandardPixmap.SP_DialogSaveButton, self.save, QKeySequence.StandardKey.Save)
        self.pack_action = self._action(menu, toolbar, "Save As DGN", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_as, QKeySequence.StandardKey.SaveAs)
        edit = self.menuBar().addMenu("&Edit")
        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        for action in (self.undo_action, self.redo_action):
            edit.addAction(action)
            toolbar.addAction(action)
        self.validate_action = self._action(edit, toolbar, "Validate", QStyle.StandardPixmap.SP_DialogApplyButton, self.validate)
        self.cancel_action = self._action(edit, toolbar, "Cancel Operation", QStyle.StandardPixmap.SP_DialogCancelButton, self.controller.cancel)
        self.force_action = self._action(edit, toolbar, "Stop Unresponsive Worker", QStyle.StandardPixmap.SP_BrowserStop, self.force_stop)
        central = QWidget()
        layout = QVBoxLayout(central)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search records")
        self.search.setAccessibleName("Record search")
        self.search.returnPressed.connect(lambda: self.load_page(0))
        search_row.addWidget(self.search)
        self.more = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown), "More")
        self.more.clicked.connect(lambda: self.load_page(self.next_cursor or 0, append=True))
        search_row.addWidget(self.more)
        layout.addLayout(search_row)
        splitter = QSplitter()
        self.tree = QTreeView()
        self.tree.setAccessibleName("DGN records")
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(["Model / Record", "Access"])
        self.tree.setModel(self.tree_model)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.selectionModel().currentChanged.connect(self.select_record)
        splitter.addWidget(self.tree)
        self.tabs = QTabWidget()
        self.table = QTableView()
        self.table.setAccessibleName("Record properties")
        self.property_model = QStandardItemModel()
        self.property_model.setHorizontalHeaderLabels(["Property", "Value", "Access"])
        self.table.setModel(self.property_model)
        self.delegate = PropertyDelegate(self.table)
        self.delegate.invalid.connect(self.statusBar().showMessage)
        self.table.setItemDelegateForColumn(1, self.delegate)
        self.property_model.dataChanged.connect(self.property_changed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.table, "Properties")
        self.content = QPlainTextEdit()
        self.content.setAccessibleName("Record content")
        self.content.setReadOnly(True)
        self.content.textChanged.connect(self._content_changed)
        self.content_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton), "Stage Content")
        self.content_button.clicked.connect(self.stage_content)
        panel = QWidget()
        content_layout = QVBoxLayout(panel)
        content_layout.addWidget(self.content)
        content_layout.addWidget(self.content_button)
        self.tabs.addTab(panel, "Content")
        byte_panel = QWidget()
        byte_layout = QVBoxLayout(byte_panel)
        byte_controls = QHBoxLayout()
        self.byte_mode = QComboBox()
        self.byte_mode.addItems(["Hex", "Escaped bytes"])
        self.byte_mode.currentIndexChanged.connect(self.render_bytes)
        self.byte_previous = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack), "")
        self.byte_previous.setToolTip("Previous byte page")
        self.byte_previous.clicked.connect(lambda: self.load_bytes(max(0, self.byte_offset - 4096)))
        self.byte_next = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward), "")
        self.byte_next.setToolTip("Next byte page")
        self.byte_next.clicked.connect(lambda: self.load_bytes(self.byte_offset + 4096))
        for control in (self.byte_mode, self.byte_previous, self.byte_next):
            byte_controls.addWidget(control)
        byte_layout.addLayout(byte_controls)
        self.bytes_view = QPlainTextEdit()
        self.bytes_view.setReadOnly(True)
        self.bytes_view.setAccessibleName("Record bytes")
        byte_layout.addWidget(self.bytes_view)
        self.byte_data = None
        self.tabs.addTab(byte_panel, "Bytes")
        self.changes = QPlainTextEdit()
        self.changes.setReadOnly(True)
        self.changes.setAccessibleName("Pending changes")
        self.tabs.addTab(self.changes, "Changes")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)
        self.setCentralWidget(central)

    def request(self, operation, arguments, callback):
        self.callback = callback
        try:
            self.controller.start(operation, arguments)
        except Exception:
            self._failed({"message": "Backend request cannot start"})

    def _completed(self, result):
        callback, self.callback = self.callback, None
        if callback:
            callback(result)

    def _failed(self, error):
        self.callback = None
        self.after_journal = None
        if self.displayed_locator is not None:
            self.selected = deepcopy(self.displayed_locator)
        self.populating = True
        for row, field in enumerate(self.fields):
            item = self.property_model.item(row, 1)
            if item is not None:
                value = field["value"]
                item.setData(value, Qt.ItemDataRole.UserRole)
                item.setText(value if isinstance(value, str) else json.dumps(value))
        self.populating = False
        self.statusBar().showMessage(error.get("message", "Operation failed"))
        self._busy(False)

    def _busy(self, busy):
        for control in (self.tree, self.table, self.search, self.more, self.content, self.content_button):
            control.setEnabled(not busy)
        self.open_action.setEnabled(not busy)
        self.workspace_action.setEnabled(not busy)
        self.recent_menu.setEnabled(not busy and bool(self.recent_folders))
        for action in (self.save_action, self.pack_action, self.validate_action):
            action.setEnabled(not busy and self.folder is not None)
        self.undo_action.setEnabled(not busy and self.undo_stack.canUndo())
        self.redo_action.setEnabled(not busy and self.undo_stack.canRedo())
        self.cancel_action.setEnabled(busy)
        self.force_action.setEnabled(busy)
        self.more.setEnabled(not busy and self.next_cursor is not None)
        self.content_button.setEnabled(not busy and hasattr(self, "content_field") and self.content_field is not None)
        self.byte_mode.setEnabled(not busy and self.byte_data is not None)
        self.byte_previous.setEnabled(not busy and bool(self.byte_data) and self.byte_offset > 0)
        self.byte_next.setEnabled(not busy and bool(self.byte_data) and self.byte_data["next_offset"] is not None)

    def patch(self, operations=None):
        return {"schema": "dgn-explorer.patch-v1", "workspace_revision": self.revision, "operations": deepcopy(self.pending if operations is None else operations)}

    def _content_changed(self):
        field = getattr(self, "content_field", None)
        if self.populating or field is None or self.selected is None:
            return
        key = (locator_key(self.selected), field["pointer"])
        value = self.content.toPlainText()
        if value == field["value"]:
            self.content_drafts.pop(key, None)
        else:
            self.content_drafts[key] = {"record": deepcopy(self.selected), "pointer": field["pointer"], "expected_value": field["saved_value"], "value": value}
        self._update_title()

    def _update_title(self):
        name = self.folder.name if self.folder else ""
        self.setWindowTitle(f"DGN Explorer - {name}{' *' if self.pending or self.content_drafts else ''}")

    def parameters(self, **extra):
        result = {"folder": str(self.folder), **extra}
        if self.pending:
            result["patch"] = self.patch()
        return result

    def open_workspace(self, folder):
        self.request("open", {"folder": str(folder)}, lambda result: self._opened(folder, result))

    def _refresh_recent(self):
        self.recent_menu.clear()
        for folder in self.recent_folders:
            action = self.recent_menu.addAction(Path(folder).name)
            action.setToolTip(folder)
            action.triggered.connect(lambda checked=False, folder=folder: self.resolve_pending(lambda: self.open_workspace(folder)))
        self.recent_menu.setEnabled(bool(self.recent_folders))

    def _remember_workspace(self):
        folder = str(self.folder.absolute())
        self.recent_folders = [folder, *[item for item in self.recent_folders if item != folder]][:10]
        self._refresh_recent()
        try:
            self.data_root.mkdir(parents=True, exist_ok=True)
            atomic_write(self.data_root / "recent-workspaces.json", json_bytes(self.recent_folders))
        except OSError:
            self.statusBar().showMessage("Workspace open; recent-workspace list cannot be saved")

    def _opened(self, folder, result):
        self.folder, self.revision = Path(folder), result["revision"]
        self.pending.clear()
        self.content_drafts.clear()
        self.selected = None
        self.displayed_locator = None
        self.content_field = None
        self.undo_stack.clear()
        self.property_model.setRowCount(0)
        self.content.clear()
        self.bytes_view.clear()
        self.changes.clear()
        self.display_page(result)
        self.setWindowTitle(f"DGN Explorer - {self.folder.name}")
        self.statusBar().showMessage(str(self.folder))
        self._remember_workspace()
        self._busy(False)
        recovery = result.get("recovery_patch")
        if recovery and QMessageBox.question(self, "Recover edits", "Restore pending edits from this workspace?") == QMessageBox.StandardButton.Yes:
            self.request("apply", {"folder": str(self.folder), "patch": recovery}, lambda result: self.undo_stack.push(PatchCommand(self, [], recovery["operations"])))

    def open_workspace_dialog(self):
        self.resolve_pending(self._choose_workspace)

    def _choose_workspace(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Workspace")
        if folder:
            self.open_workspace(folder)

    def open_dgn(self):
        self.resolve_pending(self._choose_dgn)

    def _choose_dgn(self):
        source, _ = QFileDialog.getOpenFileName(self, "Open DGN", "", "DGN files (*.dgn)")
        if not source:
            return
        destination = self.data_root / "workspaces" / f"{Path(source).stem[:40]}-{uuid.uuid4().hex}"
        self.request("import", {"source": source, "folder": str(destination)}, lambda result: self.open_workspace(destination))

    def load_page(self, cursor, append=False):
        if self.folder:
            self.request("search" if self.search.text() else "list", self.parameters(cursor=cursor, limit=200, text=self.search.text()), lambda result: self.display_page(result, append))

    def display_page(self, result, append=False):
        if not append:
            self.tree_model.setRowCount(0)
        for record in result["records"]:
            identity = "/".join(record["record"]["ole_path"])
            suffix = record["record"].get("chunk_index", record["record"].get("attribute_id", record["record"].get("property_id", "")))
            item = QStandardItem(f"{identity} [{suffix}] {record['kind']}")
            item.setData(record["record"], Qt.ItemDataRole.UserRole)
            access = QStandardItem(record["access"])
            self.tree_model.appendRow([item, access])
        self.next_cursor = result["next_cursor"]
        self._busy(False)

    def select_record(self, index, previous=None):
        locator = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        if locator:
            self.selected = locator
            self.load_bytes(0)

    def load_bytes(self, offset):
        if self.selected and self.folder:
            self.request("show", self.parameters(record=self.selected, summary=True, offset=offset), self.display_record)

    def display_record(self, result):
        self.populating = True
        self.selected = deepcopy(result["record"])
        self.displayed_locator = deepcopy(self.selected)
        self.property_model.setRowCount(0)
        self.fields = result["fields"]
        self.content_field = None
        for field in self.fields:
            label = QStandardItem(field["pointer"])
            value = field["value"]
            item = QStandardItem(value if isinstance(value, str) else json.dumps(value))
            item.setData(value, Qt.ItemDataRole.UserRole)
            label.setEditable(False)
            item.setEditable(field["editable"])
            access = QStandardItem("rw" if field["editable"] else "ro")
            access.setEditable(False)
            self.property_model.appendRow([label, item, access])
            if field["editable"] and field["pointer"].endswith("/text") and isinstance(value, str):
                self.content_field = field
        self.content.setPlainText(self.content_field["value"] if self.content_field else "")
        if self.content_field:
            draft = self.content_drafts.get((locator_key(self.selected), self.content_field["pointer"]))
            if draft:
                self.content.setPlainText(draft["value"])
        self.content.setReadOnly(self.content_field is None)
        self.byte_data = result["bytes"]
        self.byte_offset = self.byte_data["offset"]
        self.render_bytes()
        self.populating = False
        self._update_title()
        self._busy(False)

    def render_bytes(self, *args):
        if self.byte_data:
            self.bytes_view.setPlainText(self.byte_data["hex"] if self.byte_mode.currentIndex() == 0 else self.byte_data["escaped"])
            self.byte_previous.setEnabled(self.byte_offset > 0)
            self.byte_next.setEnabled(self.byte_data["next_offset"] is not None)

    def property_changed(self, top, bottom, roles):
        if self.populating or top.column() != 1 or Qt.ItemDataRole.DisplayRole not in roles:
            return
        field = self.fields[top.row()]
        self.propose(field, top.data(Qt.ItemDataRole.UserRole))

    def stage_content(self):
        self.stage_drafts()

    def stage_drafts(self, callback=None):
        if not self.content_drafts:
            if callback:
                callback()
            return
        proposed = deepcopy(self.pending)
        for draft in self.content_drafts.values():
            operation = next((item for item in proposed if item["record"] == draft["record"] and item["pointer"] == draft["pointer"]), None)
            if operation:
                operation["value"] = draft["value"]
            else:
                proposed.append(deepcopy(draft))
        proposed = [item for item in proposed if item["expected_value"] != item["value"]]
        self.request("apply", {"folder": str(self.folder), "patch": self.patch(proposed)}, lambda result: self._accepted(proposed, callback, clear_drafts=True))

    def _accepted(self, proposed, callback=None, clear_drafts=False):
        if clear_drafts:
            self.content_drafts.clear()
        self.after_journal = callback
        self.undo_stack.push(PatchCommand(self, self.pending, proposed))

    def propose(self, field, value):
        if not field["editable"]:
            return
        proposed = deepcopy(self.pending)
        operation = next((item for item in proposed if item["record"] == self.selected and item["pointer"] == field["pointer"]), None)
        if operation:
            operation["value"] = value
        else:
            proposed.append({"record": deepcopy(self.selected), "pointer": field["pointer"], "expected_value": field["saved_value"], "value": value})
        proposed = [item for item in proposed if item["expected_value"] != item["value"]]
        self.request("apply", {"folder": str(self.folder), "patch": self.patch(proposed)}, lambda result: self._accepted(proposed))

    def set_pending(self, operations):
        self.pending = deepcopy(operations)
        self.changes.setPlainText(json.dumps(self.pending, ensure_ascii=True, indent=2))
        self._update_title()
        self.request("journal", {"folder": str(self.folder), "patch": self.patch() if self.pending else None}, self._journaled)

    def _journaled(self, result):
        callback, self.after_journal = self.after_journal, None
        if callback:
            callback()
        elif self.selected:
            self.load_bytes(self.byte_offset)
        else:
            self._busy(False)

    def save(self, *args, callback=None):
        if self.content_drafts:
            self.stage_drafts(lambda: self.save(callback=callback))
            return
        if self.folder:
            self.request("apply", {"folder": str(self.folder), "patch": self.patch(), "approve": True}, lambda result: self._saved(result, callback))

    def _saved(self, result, callback):
        self.pending.clear()
        self.content_drafts.clear()
        self.revision = result["revision"]
        self.undo_stack.clear()
        self.changes.clear()
        self._update_title()
        self.statusBar().showMessage("Workspace saved")
        if callback:
            callback()
        elif self.selected:
            self.load_bytes(self.byte_offset)

    def save_as(self, output=None):
        if isinstance(output, bool):
            output = None
        if self.content_drafts:
            self.stage_drafts(lambda: self.save_as(output))
            return
        if output is None:
            output, _ = QFileDialog.getSaveFileName(self, "Save As DGN", "", "DGN files (*.dgn)")
        if output:
            self.request("pack", self.parameters(output=output), lambda result: self.statusBar().showMessage("Container verified; application validation remains required"))

    def validate(self):
        self.request("validate", self.parameters(), lambda result: self.statusBar().showMessage(f"Validated {result['records']} records; application validation not performed"))

    def force_stop(self):
        if QMessageBox.question(self, "Stop worker", "Stop the worker now? An interrupted save recovers on reopen.") == QMessageBox.StandardButton.Yes:
            self.controller.terminate()

    def resolve_pending(self, callback):
        if not self.pending and not self.content_drafts:
            callback()
            return
        choice = QMessageBox.question(self, "Pending edits", "Save pending workspace edits?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Save:
            self.save(callback=callback)
        elif choice == QMessageBox.StandardButton.Discard:
            self.request("journal", {"folder": str(self.folder), "patch": None}, lambda result: self._discarded(callback))

    def _discarded(self, callback):
        self.pending.clear()
        self.content_drafts.clear()
        self.undo_stack.clear()
        self.changes.clear()
        self._update_title()
        if self.selected:
            self.request("show", self.parameters(record=self.selected, summary=True, offset=self.byte_offset), lambda result: self._discard_loaded(result, callback))
        else:
            callback()

    def _discard_loaded(self, result, callback):
        self.display_record(result)
        callback()

    def closeEvent(self, event):
        if self.controller.busy:
            event.ignore()
            self.statusBar().showMessage("Cancel or finish the current operation before closing")
            return
        if self.closing or not (self.pending or self.content_drafts):
            event.accept()
            return
        event.ignore()
        self.resolve_pending(self._close_clean)

    def _close_clean(self):
        self.closing = True
        self.close()


def launch() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("DGN Explorer")
    app.setOrganizationName("DGN Explorer")
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from .portable import verify_gui

        return verify_gui(app, Path(sys.argv[2]))
    window = ExplorerWindow()
    window.show()
    return app.exec()