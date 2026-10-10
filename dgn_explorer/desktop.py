"""Native Qt Widgets client; all DGN operations run in backend processes."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

from PySide6.QtCore import QEvent, QObject, QProcess, QSignalBlocker, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QStandardItem, QStandardItemModel, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QMenu, QSplitter, QStyle, QStyledItemDelegate, QTableView, QTabWidget, QToolBar,
    QTreeView, QVBoxLayout, QWidget,
)
from PySide6.QtXml import QDomImplementation

QDomImplementation.setInvalidDataPolicy(QDomImplementation.InvalidDataPolicy.ReturnNullNode)

from .worker import MESSAGE_LIMIT, PROTOCOL
from .workspace import json_bytes, locator_key, parse_json
from .transactions import atomic_write
from . import codecs
from .operations import export_payload, load_payload

ALERT_OPERATIONS = frozenset({"import", "open", "pack", "validate"})
FORMAT_LABELS = ("Plain Text", "Unicode Escaped (\\uXXXX)", "Hexadecimal", "Base64")


def property_text(value):
    return codecs.editor_encode(value.encode("utf-8"), "escaped") if isinstance(value, str) else json.dumps(value)


class DataEditor(QWidget):
    """Shared string editor with reversible representations and passive file actions."""

    changed = Signal()
    failed = Signal(str)

    def __init__(self, parent=None, workspace=None):
        super().__init__(parent)
        self.workspace = workspace
        self.format = "plain"
        self.updating = False
        self.readonly = False
        self.error = ""
        self.format_notice = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.selector = QComboBox()
        self.selector.addItems(FORMAT_LABELS)
        self.selector.setMinimumContentsLength(12)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setAccessibleName("Content representation")
        self.selector.setAccessibleDescription("Convert the current buffer without staging. Invalid input must be corrected before switching formats.")
        self.selector.setToolTip(self.selector.accessibleDescription())
        self.selector.currentIndexChanged.connect(self.switch_format)
        actions.addWidget(self.selector, 1)
        self.load_button = self.button("Load File…", "Load payload from file", "Load at most 64 KiB without executing content; replaces only this draft.", self.load_file)
        self.export_button = self.button("Export File…", "Export payload to file", "Save decoded payload bytes to a new file, never overwrite inputs.", self.export_file)
        self.copy_button = self.button("Copy…", "Copy payload as", "Copy a safe representation; Ctrl+C copies the selected displayed text.", None)
        for button, shortcut in ((self.load_button, "Alt+L"), (self.export_button, "Alt+X"), (self.copy_button, "Alt+C")):
            button.setShortcut(QKeySequence(shortcut))
            button.setToolTip(button.toolTip() + f" ({shortcut})")
            button.setAccessibleDescription(button.toolTip())
        self.copy_menu = QMenu(self.copy_button)
        self.copy_actions = {}
        for name, format in (("Copy as Escaped Text", "escaped"), ("Copy as Hex", "hex"), ("Copy as Base64", "base64")):
            action = self.copy_menu.addAction(name)
            action.setToolTip("Copy the whole decoded payload without clipboard null-byte clipping")
            action.triggered.connect(lambda checked=False, format=format: self.copy_as(format))
            self.copy_actions[format] = action
        self.copy_button.setMenu(self.copy_menu)
        for button in (self.load_button, self.export_button, self.copy_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.editor = QPlainTextEdit()
        self.editor.setAccessibleName("Record content")
        self.editor.setAccessibleDescription("UTF-8 string representations, never executed. Escape backslashes as \\\\ in escaped mode. Ctrl+A selects all; Ctrl+C copies the displayed representation.")
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setFixedPitch(True)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.textChanged.connect(self._changed)
        layout.addWidget(self.editor, 1)
        self.validation = QLabel()
        self.validation.setTextFormat(Qt.TextFormat.PlainText)
        self.validation.setWordWrap(True)
        self.validation.setAccessibleName("Content validation")
        self.validation.setAccessibleDescription("Live syntax and UTF-8 validation. Invalid input stays in the editor and cannot be staged.")
        layout.addWidget(self.validation)
        self._validate()

    def button(self, text, name, hint, slot):
        button = QPushButton(text)
        button.setAccessibleName(name)
        button.setAccessibleDescription(hint)
        button.setToolTip(hint)
        if slot:
            button.clicked.connect(slot)
        return button

    def bytes_value(self):
        return codecs.editor_decode(self.editor.toPlainText(), self.format)

    def value(self):
        return codecs.editor_text(self.editor.toPlainText(), self.format)

    def draft(self):
        return {"format": self.format, "buffer": self.editor.toPlainText(), "value": None if self.error else self.value()}

    def set_buffer(self, buffer, format):
        self.updating = True
        try:
            self.format = format
            with QSignalBlocker(self.selector):
                self.selector.setCurrentIndex(codecs.EDITOR_FORMATS.index(format))
            self.editor.setPlainText(buffer)
            self._validate()
        finally:
            self.updating = False

    def set_value(self, value, format=None):
        format = format or self.format
        self.format_notice = ""
        if format == "plain" and not codecs.editor_plain_safe(value):
            format = "escaped"
            self.format_notice = "Controls shown as escapes to preserve nulls and line endings."
        self.set_buffer(codecs.editor_encode(value.encode("utf-8"), format), format)

    def switch_format(self, index):
        target = codecs.EDITOR_FORMATS[index]
        if target == self.format:
            return
        try:
            data = self.bytes_value()
            text = codecs.editor_encode(data, target)
            if target == "plain" and not codecs.editor_plain_safe(text):
                target = "escaped"
                text = codecs.editor_encode(data, target)
                self.format_notice = "Controls shown as escapes to preserve nulls and line endings."
            else:
                self.format_notice = ""
            self.set_buffer(text, target)
            self.changed.emit()
        except (ValueError, UnicodeError) as error:
            with QSignalBlocker(self.selector):
                self.selector.setCurrentIndex(codecs.EDITOR_FORMATS.index(self.format))
            self.validation.setText(f"Cannot switch format: {error}")
            self.validation.setToolTip(self.validation.text())

    def _changed(self):
        if self.updating:
            return
        self.format_notice = ""
        self._validate()
        if self.format in ("plain", "escaped") and not self.error and not codecs.editor_plain_safe(self.editor.toPlainText()):
            self.set_value(self.value(), "escaped")
            self.format_notice = "Controls shown as escapes to preserve nulls and line endings."
            self._validate()
        self.changed.emit()

    def _validate(self):
        self.error = ""
        try:
            value = self.value()
            size = len(value.encode("utf-8"))
            summary = f"UTF-8 · {size:,} bytes · {len(value):,} characters"
        except (ValueError, UnicodeError) as error:
            self.error = str(error)
            summary = f"Invalid input — {self.error}"
        self.validation.setText(summary + (f" · {self.format_notice}" if self.format_notice else ""))
        self.validation.setToolTip(self.validation.text())
        self.editor.setProperty("invalidInput", bool(self.error))
        self.editor.setAccessibleDescription("Record content. " + self.validation.text() + " Ctrl+C copies the selected representation; content is never executed.")
        try:
            self.bytes_value()
            exportable = True
        except (ValueError, UnicodeError):
            exportable = False
        self.export_button.setEnabled(exportable)
        self.copy_button.setEnabled(exportable)
        for format, action in self.copy_actions.items():
            action.setEnabled(exportable and (format != "escaped" or not self.error))

    def set_readonly(self, readonly):
        self.readonly = readonly
        self.editor.setReadOnly(readonly)
        self.load_button.setEnabled(not readonly)

    def copy_as(self, format):
        try:
            QApplication.clipboard().setText(codecs.editor_encode(self.bytes_value(), format))
        except (ValueError, UnicodeError) as error:
            self.failed.emit(str(error))

    def load_file(self, path=None):
        if self.readonly:
            return
        if not path or isinstance(path, bool):
            path, _ = QFileDialog.getOpenFileName(self, "Load Payload", "", "All files (*)")
        if not path:
            return
        try:
            data = load_payload(Path(path))
            try:
                value = data.decode("utf-8")
                self.set_value(value)
            except UnicodeError:
                self.set_buffer(codecs.editor_encode(data, "hex"), "hex")
            self.changed.emit()
        except (OSError, ValueError) as error:
            self.failed.emit(str(error))

    def export_file(self, path=None):
        if not path or isinstance(path, bool):
            path, _ = QFileDialog.getSaveFileName(self, "Export Payload to New File", "", "All files (*)")
        if path:
            try:
                export_payload(Path(path), self.bytes_value(), workspace=self.workspace)
            except (OSError, ValueError) as error:
                self.failed.emit(str(error))


class PropertyEditorDialog(QDialog):
    def __init__(self, value, pointer, parent=None, workspace=None):
        super().__init__(parent)
        self.setWindowTitle("Edit String Property")
        self.setAccessibleName("Advanced property editor")
        self.setAccessibleDescription("Representations and file loading edit a draft. Stage Property validates without saving.")
        self.resize(680, 450)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        heading = QLabel(pointer)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        self.payload = DataEditor(self, workspace)
        self.payload.set_value(value, "escaped")
        self.payload.failed.connect(self.payload.validation.setText)
        layout.addWidget(self.payload)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.stage_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.stage_button.setText("Stage Property")
        self.stage_button.setAccessibleName("Stage property")
        self.stage_button.setAccessibleDescription("Propose the decoded string for backend validation. This does not save the workspace.")
        self.stage_button.setToolTip(self.stage_button.accessibleDescription())
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.payload.changed.connect(lambda: self.stage_button.setEnabled(not self.payload.error))
        self.stage_button.setEnabled(not self.payload.error)
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setAccessibleName("Cancel property draft")
        cancel.setAccessibleDescription("Close this dialog without proposing its draft. Escape also cancels.")
        cancel.setToolTip(cancel.accessibleDescription())
        layout.addWidget(self.buttons)
        QWidget.setTabOrder(self.payload.selector, self.payload.load_button)
        QWidget.setTabOrder(self.payload.load_button, self.payload.export_button)
        QWidget.setTabOrder(self.payload.export_button, self.payload.copy_button)
        QWidget.setTabOrder(self.payload.copy_button, self.payload.editor)
        QWidget.setTabOrder(self.payload.editor, self.stage_button)
        QWidget.setTabOrder(self.stage_button, cancel)

    def accept(self):
        if not self.payload.error:
            super().accept()


def hex_page(text: str, offset: int) -> str:
    """Format only the bounded backend byte page, with absolute offsets and ASCII."""
    data = bytes.fromhex(text)
    lines = []
    for position in range(0, len(data), 16):
        row = data[position:position + 16]
        octets = f"{row[:8].hex(' '):23}  {row[8:].hex(' '):23}"
        ascii_text = "".join(chr(value) if 32 <= value < 127 else "." for value in row)
        lines.append(f"{offset + position:08X}  {octets}  |{ascii_text}|")
    return "\n".join(lines)


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
        self.violated = False
        self.request = None
        self.program = None

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
        self.violated = False
        self.busyChanged.emit(True)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        if self.program is not None:
            self.process.start(self.program[0], list(self.program[1]))
        elif getattr(sys, "frozen", False):
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
        self._consume(bytes(self.process.readAllStandardOutput()))

    def _violation(self, message: str):
        self.violated = True
        self.terminal = ("failed", {"code": 3, "message": message})
        self.buffer.clear()
        self.process.kill()

    def _consume(self, data: bytes):
        """Parse newline-delimited protocol messages from arbitrarily fragmented output."""
        if self.violated:
            return
        self.buffer.extend(data)
        if len(self.buffer) > MESSAGE_LIMIT and b"\n" not in self.buffer:
            self._violation("Oversized worker output")
            return
        try:
            while b"\n" in self.buffer:
                line, _, tail = self.buffer.partition(b"\n")
                self.buffer = bytearray(tail)
                if len(line) > MESSAGE_LIMIT:
                    raise ValueError("Oversized worker message")
                message = parse_json(line)
                if not isinstance(message, dict) or set(message) != {"protocol", "request_id", "event", "payload"} or message["protocol"] != PROTOCOL or message["request_id"] != self.request["request_id"] or not isinstance(message["payload"], dict):
                    raise ValueError("Invalid worker message")
                if self.terminal is not None:
                    raise ValueError("Message after worker completion")
                if message["event"] == "progress":
                    self.progress.emit(str(message["payload"].get("stage", "Working")))
                elif message["event"] in ("completed", "failed"):
                    self.terminal = (message["event"], message["payload"])
                else:
                    raise ValueError("Unknown worker event")
            if len(self.buffer) > MESSAGE_LIMIT:
                raise ValueError("Oversized worker output")
        except Exception:
            self._violation("Invalid worker output")

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
        editor = QCheckBox(parent) if type(value) is bool else QLineEdit(parent)
        editor.setAccessibleName("Edit property value")
        editor.setAccessibleDescription("Strings use Unicode escapes: \\u0000 or \\x00 for null, \\\\ for a literal backslash. Enter proposes; Save Workspace commits. Advanced Edit offers formats and file loading.")
        editor.setToolTip(editor.accessibleDescription())
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(editor, QCheckBox):
            editor.setChecked(value)
        else:
            editor.setText(property_text(value))

    def setModelData(self, editor, model, index):
        before = index.data(Qt.ItemDataRole.UserRole)
        try:
            value = editor.isChecked() if isinstance(editor, QCheckBox) else codecs.editor_text(editor.text(), "escaped") if isinstance(before, str) else parse_json(editor.text().encode())
            model.setData(index, value, Qt.ItemDataRole.UserRole)
            model.setData(index, property_text(value), Qt.ItemDataRole.DisplayRole)
        except Exception as error:
            self.invalid.emit(f"Invalid typed value: {error}")


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
        self.controller.progress.connect(self._progress)
        self.controller.busyChanged.connect(self._busy)
        self.folder = None
        self.revision = None
        self.pending = []
        self.content_drafts = {}
        self.content_views = {}
        self.content_targets = {}
        self.has_content = False
        self.property_dialog = None
        self.selected = None
        self.displayed_locator = None
        self.fields = []
        self.next_cursor = None
        self.byte_offset = 0
        self.callback = None
        self.alert_failure = False
        self.error_dialog = None
        self.operation = None
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
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        self._action_hint(action)
        menu.addAction(action)
        toolbar.addAction(action)
        return action

    def _action_hint(self, action):
        hint = action.text().replace("&", "")
        shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        if shortcut:
            hint += f" ({shortcut})"
        action.setToolTip(hint)
        action.setStatusTip(hint)

    def _label(self, text, name):
        label = QLabel(text)
        label.setAccessibleName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def _inspector_font(self):
        font = QFont("monospace", self.font().pointSize())
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setFixedPitch(True)
        return font

    def _build(self):
        toolbar = QToolBar("File", self)
        toolbar.setObjectName("fileToolbar")
        toolbar.setAccessibleName("Workspace actions")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        menu = self.menuBar().addMenu("&File")
        self.open_action = self._action(menu, toolbar, "Open DGN", QStyle.StandardPixmap.SP_DialogOpenButton, self.open_dgn, QKeySequence.StandardKey.Open)
        self.workspace_action = self._action(menu, toolbar, "Open Workspace", QStyle.StandardPixmap.SP_DirOpenIcon, self.open_workspace_dialog)
        self.recent_menu = menu.addMenu("Recent Workspaces")
        toolbar.addSeparator()
        self.save_action = self._action(menu, toolbar, "Save Workspace", QStyle.StandardPixmap.SP_DialogSaveButton, self.save, QKeySequence.StandardKey.Save)
        self.pack_action = self._action(menu, toolbar, "Save As DGN", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_as, QKeySequence.StandardKey.SaveAs)
        edit = self.menuBar().addMenu("&Edit")
        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        toolbar.addSeparator()
        for action in (self.undo_action, self.redo_action):
            self._action_hint(action)
            edit.addAction(action)
            toolbar.addAction(action)
        toolbar.addSeparator()
        self.validate_action = self._action(edit, toolbar, "Validate", QStyle.StandardPixmap.SP_DialogApplyButton, self.validate)
        self.cancel_action = self._action(edit, toolbar, "Cancel Operation", QStyle.StandardPixmap.SP_DialogCancelButton, self.controller.cancel)
        self.force_action = self._action(edit, toolbar, "Stop Unresponsive Worker", QStyle.StandardPixmap.SP_BrowserStop, self.force_stop)
        self.find_action = QAction("Find Records", self)
        self.find_action.setShortcut(QKeySequence.StandardKey.Find)
        self.find_action.triggered.connect(self.focus_search)
        self._action_hint(self.find_action)
        edit.addAction(self.find_action)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        workspace_row = QHBoxLayout()
        self.workspace_label = self._label("Open a DGN or workspace to begin", "Current workspace")
        self.workspace_label.setObjectName("workspaceHeading")
        heading_font = self.workspace_label.font()
        heading_font.setPointSize(heading_font.pointSize() + 2)
        heading_font.setBold(True)
        self.workspace_label.setFont(heading_font)
        self.edit_state = self._label("No workspace", "Workspace edit state")
        workspace_row.addWidget(self.workspace_label, 1)
        workspace_row.addWidget(self.edit_state)
        layout.addLayout(workspace_row)
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Find records — enter a literal value and press Enter")
        self.search.setAccessibleName("Record search")
        self.search.setAccessibleDescription("Literal, case-insensitive search of current record values. Ctrl+F focuses search; Enter searches; clear and Enter shows all records.")
        self.search.setToolTip("Find records (Ctrl+F); press Enter to search")
        self.search.returnPressed.connect(lambda: self.load_page(0))
        search_row.addWidget(self.search)
        self.more = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown), "Load more")
        self.more.setAccessibleName("Load more records")
        self.more.setToolTip("Load the next page of records")
        self.more.clicked.connect(lambda: self.load_page(self.next_cursor or 0, append=True))
        search_row.addWidget(self.more)
        layout.addLayout(search_row)
        splitter = QSplitter()
        splitter.setObjectName("recordSplitter")
        splitter.setAccessibleName("Records and inspector divider")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)
        self.tree = QTreeView()
        self.tree.setMinimumWidth(160)
        self.tree.setAccessibleName("DGN records")
        self.tree.setAccessibleDescription("Select a contextual record to inspect it. Access indicates supported edits, not OS file permissions.")
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(["Model / Record", "Access"])
        self.tree.setModel(self.tree_model)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.selectionModel().currentChanged.connect(self.select_record)
        splitter.addWidget(self.tree)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Record views")
        self.tabs.setAccessibleDescription("Properties, multi-format content, paged bytes, and staged changes. Use Ctrl+Tab to switch views.")
        inspector = QWidget()
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(8)
        self.record_label = self._label("Select a record to inspect", "Selected record")
        inspector_layout.addWidget(self.record_label)
        self.table = QTableView()
        self.table.setAccessibleName("Record properties")
        self.table.setAccessibleDescription("Read-only values cannot be edited. Editable values propose typed changes; staged changes are not saved until Save Workspace.")
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.property_model = QStandardItemModel()
        self.property_model.setHorizontalHeaderLabels(["Property", "Value", "Access"])
        self.table.setModel(self.property_model)
        self.delegate = PropertyDelegate(self.table)
        self.delegate.invalid.connect(self.statusBar().showMessage)
        self.table.setItemDelegateForColumn(1, self.delegate)
        self.property_model.dataChanged.connect(self.property_changed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(self.table.fontMetrics().horizontalAdvance("Read-only") + 28)
        self.table.setColumnWidth(0, 210)
        property_panel = QWidget()
        property_layout = QVBoxLayout(property_panel)
        property_layout.setContentsMargins(0, 0, 0, 0)
        property_layout.addWidget(self.table, 1)
        property_actions = QHBoxLayout()
        property_hint = self._label("Strings use escapes · \\\\ = backslash · \\u0000 = null", "Property editing hint")
        property_actions.addWidget(property_hint, 1)
        self.property_button = QPushButton("Advanced Edit…")
        self.property_button.setAccessibleName("Advanced edit selected property")
        self.property_button.setAccessibleDescription("Edit the selected string using escaped text, hex or Base64, or load a file. Stage Property proposes changes without saving.")
        self.property_button.setToolTip(self.property_button.accessibleDescription())
        self.property_button.setShortcut(QKeySequence("Alt+P"))
        self.property_button.setToolTip(self.property_button.toolTip() + " (Alt+P)")
        self.property_button.clicked.connect(self.edit_property)
        property_actions.addWidget(self.property_button)
        property_layout.addLayout(property_actions)
        self.table.selectionModel().currentChanged.connect(lambda *args: self._property_controls())
        self.tabs.addTab(property_panel, "Properties")
        self.content_editor = DataEditor()
        self.content = self.content_editor.editor
        self.content.setFont(self._inspector_font())
        self.content_editor.set_readonly(True)
        self.content_editor.changed.connect(self._content_changed)
        self.content_editor.failed.connect(self.show_error)
        self.content_format = self.content_editor.selector
        self.content_load = self.content_editor.load_button
        self.content_export = self.content_editor.export_button
        self.content_copy = self.content_editor.copy_button
        self.content_validation = self.content_editor.validation
        self.content_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton), "Stage Content")
        self.content_button.setAccessibleName("Stage content")
        self.content_button.setToolTip("Validate and stage all content drafts; Save Workspace (Ctrl+S) commits edits")
        self.content_button.setAccessibleDescription(self.content_button.toolTip())
        self.content_button.setShortcut(QKeySequence("Alt+T"))
        self.content_button.setToolTip(self.content_button.toolTip() + " (Alt+T)")
        self.content_button.clicked.connect(self.stage_content)
        content_layout = self.content_editor.layout()
        self.content_target = QComboBox()
        self.content_target.setAccessibleName("Content field")
        self.content_target.setToolTip("Choose a string, name, description, XML or JSON field; drafts remain attached to their original fields")
        self.content_target.setAccessibleDescription(self.content_target.toolTip())
        self.content_target.currentIndexChanged.connect(self._select_content_field)
        content_layout.insertWidget(0, self.content_target)
        self.content_info = self._label("No content selected", "Content format and access")
        content_layout.insertWidget(1, self.content_info)
        content_actions = QHBoxLayout()
        content_actions.addStretch()
        content_actions.addWidget(self.content_button)
        content_layout.addLayout(content_actions)
        self.tabs.addTab(self.content_editor, "Content")
        byte_panel = QWidget()
        byte_layout = QVBoxLayout(byte_panel)
        byte_layout.setContentsMargins(10, 10, 10, 10)
        byte_controls = QHBoxLayout()
        self.byte_mode = QComboBox()
        self.byte_mode.addItems(["Hex", "Escaped bytes"])
        self.byte_mode.setAccessibleName("Byte display mode")
        self.byte_mode.setAccessibleDescription("Choose offset-formatted hexadecimal with ASCII or reversible escaped bytes.")
        self.byte_mode.setToolTip("Display the current 4 KiB page without changing document bytes")
        self.byte_mode.currentIndexChanged.connect(self.render_bytes)
        self.byte_previous = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack), "")
        self.byte_previous.setToolTip("Previous byte page")
        self.byte_previous.setAccessibleName("Previous byte page")
        self.byte_previous.setAccessibleDescription("Load the preceding 4 KiB byte page.")
        self.byte_previous.clicked.connect(lambda: self.load_bytes(max(0, self.byte_offset - 4096)))
        self.byte_next = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward), "")
        self.byte_next.setToolTip("Next byte page")
        self.byte_next.setAccessibleName("Next byte page")
        self.byte_next.setAccessibleDescription("Load the next 4 KiB byte page.")
        self.byte_next.clicked.connect(lambda: self.load_bytes(self.byte_offset + 4096))
        for control in (self.byte_mode, self.byte_previous, self.byte_next):
            byte_controls.addWidget(control)
        byte_controls.addStretch()
        self.byte_info = self._label("No byte page selected", "Byte page range")
        byte_controls.addWidget(self.byte_info)
        byte_layout.addLayout(byte_controls)
        self.bytes_view = QPlainTextEdit()
        self.bytes_view.setReadOnly(True)
        self.bytes_view.setAccessibleName("Record bytes")
        self.bytes_view.setAccessibleDescription("Read-only bounded page. Hex rows show absolute byte offsets, 16 bytes, and printable ASCII; dots represent other bytes.")
        self.bytes_view.setFont(self._inspector_font())
        self.bytes_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        byte_layout.addWidget(self.bytes_view)
        byte_actions = QHBoxLayout()
        byte_actions.addStretch()
        self.byte_export = QPushButton("Export Page…")
        self.byte_export.setAccessibleName("Export byte page to file")
        self.byte_export.setAccessibleDescription("Export only the current page of raw bytes, at most 4 KiB, to a new file outside the workspace.")
        self.byte_export.setToolTip(self.byte_export.accessibleDescription())
        self.byte_export.setShortcut(QKeySequence("Alt+B"))
        self.byte_export.setToolTip(self.byte_export.toolTip() + " (Alt+B)")
        self.byte_export.clicked.connect(self.export_byte_page)
        byte_actions.addWidget(self.byte_export)
        byte_layout.addLayout(byte_actions)
        self.byte_data = None
        self.tabs.addTab(byte_panel, "Bytes")
        self.changes = QPlainTextEdit()
        self.changes.setReadOnly(True)
        self.changes.setAccessibleName("Pending changes")
        self.changes.setAccessibleDescription("Read-only JSON preview of staged replacements. Content drafts must be staged first. Save Workspace commits staged changes.")
        self.changes.setFont(self._inspector_font())
        self.changes.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.changes, "Changes")
        inspector_layout.addWidget(self.tabs)
        splitter.addWidget(inspector)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([350, 700])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName("Backend operation progress")
        self.progress_bar.setAccessibleDescription("Indeterminate progress; work totals are unknown. Cancel Operation requests a safe cancellation.")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(160)
        self.progress_bar.hide()
        self.status_state = self._label("Ready", "Operation status")
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.status_state)
        self.statusBar().setAccessibleName("Application status")
        self.setStyleSheet("""
            QToolBar#fileToolbar { padding: 4px; spacing: 4px; border: none; }
            QToolBar#fileToolbar QToolButton { padding: 5px 7px; }
            QLabel#workspaceHeading { font-weight: 600; }
            QLineEdit { padding: 6px 8px; }
            QPushButton { padding: 5px 10px; }
            QHeaderView::section { padding: 6px 8px; }
            QTreeView::item, QTableView::item { padding: 4px; }
            QTabBar::tab { padding: 7px 12px; }
            QStatusBar { padding: 2px 6px; }
        """)
        for first, second in ((self.search, self.more), (self.more, self.tree), (self.tree, self.tabs),
                              (self.tabs, self.table), (self.table, self.property_button),
                              (self.property_button, self.content_target), (self.content_target, self.content_format),
                              (self.content_format, self.content_load),
                              (self.content_load, self.content_export), (self.content_export, self.content_copy),
                              (self.content_copy, self.content), (self.content, self.content_button),
                              (self.content_button, self.byte_mode), (self.byte_mode, self.byte_previous),
                              (self.byte_previous, self.byte_next), (self.byte_next, self.bytes_view),
                              (self.bytes_view, self.byte_export), (self.byte_export, self.changes)):
            QWidget.setTabOrder(first, second)
        self._update_title()

    def _progress(self, message):
        self.status_state.setText(message)
        self.statusBar().showMessage(message)

    def focus_search(self):
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.ApplicationPaletteChange, QEvent.Type.PaletteChange) and self.styleSheet() and not getattr(self, "_refreshing_style", False):
            # Qt caches palettes while polishing QSS, even when it only sets spacing.
            self._refreshing_style = True
            try:
                styling = self.styleSheet()
                self.setStyleSheet("")
                self.setStyleSheet(styling)
            finally:
                self._refreshing_style = False

    def request(self, operation, arguments, callback):
        self.operation = operation
        self.callback = callback
        self.alert_failure = operation in ALERT_OPERATIONS or operation == "apply" and arguments.get("approve") is True
        try:
            self.controller.start(operation, arguments)
        except Exception:
            self._failed({"message": "Backend request cannot start"})

    def _completed(self, result):
        self.status_state.setText("Ready")
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
                item.setText(property_text(value))
        self.populating = False
        message = error.get("message", "Operation failed")
        cancelled = error.get("code") == 6
        self.status_state.setText("Cancelled" if cancelled else "Error")
        self.statusBar().showMessage(message)
        if self.alert_failure and not cancelled:
            self.show_error(message)
        self.alert_failure = False
        self._busy(False)

    def show_error(self, message):
        """Window-modal, non-blocking alert so worker callbacks never nest event loops."""
        if self.error_dialog is not None:
            self.error_dialog.close()
        dialog = QMessageBox(QMessageBox.Icon.Warning, "DGN Explorer", message, QMessageBox.StandardButton.Ok, self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setAccessibleName("Operation failed")
        dialog.setAccessibleDescription("The operation did not complete. Review the error; unsaved edits remain available.")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.finished.connect(lambda result: setattr(self, "error_dialog", None))
        self.error_dialog = dialog
        dialog.open()

    def _busy(self, busy):
        self.progress_bar.setVisible(busy)
        if busy:
            self.status_state.setText(f"Working: {self.operation or 'operation'}")
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
        self.content_format.setEnabled(not busy and self.has_content)
        self.content_target.setEnabled(not busy and self.has_content)
        self.content_load.setEnabled(not busy and getattr(self, "content_field", None) is not None)
        self.content_export.setEnabled(not busy and self.has_content and self._payload_exportable())
        self.content_copy.setEnabled(self.content_export.isEnabled())
        self.content_button.setEnabled(self.content_button.isEnabled() and not self.content_editor.error and all(draft.get("value") is not None for draft in self.content_drafts.values()))
        self.content_editor.workspace = self.folder
        self._property_controls(busy)
        self.byte_mode.setEnabled(not busy and self.byte_data is not None)
        self.byte_previous.setEnabled(not busy and bool(self.byte_data) and self.byte_offset > 0)
        self.byte_next.setEnabled(not busy and bool(self.byte_data) and self.byte_data["next_offset"] is not None)
        self.byte_export.setEnabled(not busy and self.byte_data is not None)

    def _payload_exportable(self):
        try:
            self.content_editor.bytes_value()
            return True
        except (ValueError, UnicodeError):
            return False

    def _property_controls(self, busy=None):
        if busy is None:
            busy = self.controller.busy
        row = self.table.currentIndex().row()
        field = self.fields[row] if 0 <= row < len(self.fields) else None
        self.property_button.setEnabled(not busy and bool(field) and field["editable"] and isinstance(field["value"], str))

    def edit_property(self):
        row = self.table.currentIndex().row()
        if not 0 <= row < len(self.fields) or self.controller.busy:
            return
        field = deepcopy(self.fields[row])
        if not field["editable"] or not isinstance(field["value"], str):
            return
        dialog = PropertyEditorDialog(field["value"], field["pointer"], self, self.folder)
        self.property_dialog = dialog
        dialog.accepted.connect(lambda: self.propose(field, dialog.payload.value()))
        dialog.finished.connect(lambda result: setattr(self, "property_dialog", None))
        dialog.open()

    def export_byte_page(self, path=None):
        if self.byte_data is None:
            return
        if not path or isinstance(path, bool):
            path, _ = QFileDialog.getSaveFileName(self, "Export Byte Page to New File", "", "All files (*)")
        if path:
            try:
                export_payload(Path(path), bytes.fromhex(self.byte_data["hex"]), workspace=self.folder)
                self.statusBar().showMessage("Byte page exported; document inputs unchanged")
            except (OSError, ValueError) as error:
                self.show_error(str(error))

    def patch(self, operations=None):
        return {"schema": "dgn-explorer.patch-v1", "workspace_revision": self.revision, "operations": deepcopy(self.pending if operations is None else operations)}

    def _content_changed(self):
        field = getattr(self, "content_field", None)
        if self.populating or field is None or self.selected is None:
            return
        key = (locator_key(self.selected), field["pointer"])
        draft = self.content_editor.draft()
        self.content_views[key] = draft["format"]
        if not self.content_editor.error and draft["value"] == field["value"]:
            self.content_drafts.pop(key, None)
        else:
            self.content_drafts[key] = {"record": deepcopy(self.selected), "pointer": field["pointer"], "expected_value": field["saved_value"], **draft}
        self._update_title()
        self._busy(self.controller.busy)

    def _update_title(self):
        name = self.folder.name if self.folder else ""
        self.setWindowTitle(f"DGN Explorer - {name}{' *' if self.pending or self.content_drafts else ''}")
        self.workspace_label.setText(name or "Open a DGN or workspace to begin")
        self.workspace_label.setToolTip(str(self.folder) if self.folder else "Inputs are preserved; Save As creates a new DGN")
        parts = []
        if self.pending:
            parts.append(f"{len(self.pending)} staged")
        if self.content_drafts:
            parts.append(f"{len(self.content_drafts)} draft")
        state = " · ".join(parts) if parts else "Saved" if self.folder else "No workspace"
        self.edit_state.setText(state)
        self.edit_state.setAccessibleDescription(state + ". Drafts and staged edits are not saved. Save Workspace commits accepted edits.")
        self.tabs.setTabText(3, f"Changes ({len(self.pending)})" if self.pending else "Changes")
        self._content_status()

    def _content_status(self):
        field = getattr(self, "content_field", None)
        if not field:
            self.content_info.setText("Read-only · No supported text editor for this record")
            return
        key = (locator_key(self.selected), field["pointer"])
        state = "Draft — not staged" if key in self.content_drafts else "Staged — not saved" if field["value"] != field["saved_value"] else "Editable"
        metadata = [str(item["value"]) for item in self.fields if item["pointer"].endswith(("/encoding", "/codepage"))]
        bom = next((item["value"] for item in self.fields if item["pointer"].endswith("/bom_hex")), None)
        if bom is not None:
            metadata.append(f"BOM {bom or 'none'}")
        self.content_info.setText(" · ".join([state, FORMAT_LABELS[codecs.EDITOR_FORMATS.index(self.content_editor.format)], *metadata, "UTF-8 representation"]))
        self.content_info.setAccessibleDescription(self.content_info.text())

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
        self.content_views.clear()
        self.content_targets.clear()
        self.has_content = False
        self.selected = None
        self.displayed_locator = None
        self.content_field = None
        self.content_target.clear()
        self.fields = []
        self.byte_data = None
        self.byte_offset = 0
        self.search.clear()
        self.undo_stack.clear()
        self.property_model.setRowCount(0)
        self.content_editor.set_buffer("", "plain")
        self.content_editor.set_readonly(True)
        self.bytes_view.clear()
        self.changes.clear()
        self.record_label.setText("Select a record to inspect")
        self.record_label.setAccessibleDescription("")
        self.record_label.setToolTip("")
        self.byte_info.setText("No byte page selected")
        self.display_page(result)
        self._update_title()
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
            feature = record.get("feature", record["kind"])
            item = QStandardItem(f"{identity} [{suffix}] {feature}")
            item.setData(record["record"], Qt.ItemDataRole.UserRole)
            access = QStandardItem(record["access"])
            access.setText("Editable" if record["access"] == "rw" else "Read-only")
            access.setToolTip("Supported fields can be edited; other values remain read-only" if record["access"] == "rw" else "Unsupported or protected record; bytes are preserved")
            item.setToolTip(f"{record['kind']}\n{record.get('preview', '')}\nSelect this contextual record to inspect its identity and fields")
            item.setData(item.text(), Qt.ItemDataRole.AccessibleDescriptionRole)
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
        self.record_label.setText(" / ".join(self.selected["ole_path"]) + (f" · {result.get('feature', result['kind'])}" if result.get("kind") else ""))
        self.record_label.setToolTip("Selected contextual record; names are displayed as passive plain text")
        self.record_label.setAccessibleDescription(json.dumps(self.selected, ensure_ascii=True))
        self.property_model.setRowCount(0)
        self.fields = result["fields"]
        self.content_field = None
        for field in self.fields:
            label = QStandardItem(field["pointer"])
            value = field["value"]
            item = QStandardItem(property_text(value))
            item.setData(value, Qt.ItemDataRole.UserRole)
            label.setEditable(False)
            item.setEditable(field["editable"])
            staged = field["editable"] and value != field["saved_value"]
            access_text = "Staged" if staged else "Editable" if field["editable"] else "Read-only"
            access = QStandardItem(access_text)
            hint = "Staged — not saved; Save Workspace (Ctrl+S) commits edits" if staged else "Editable — double-click or press F2 to propose a typed value" if field["editable"] else "Read-only — identity, encoding, original snapshot, or unsupported value"
            for cell in (label, item, access):
                cell.setToolTip(hint)
                cell.setData(f"{field['pointer']}: {access_text}", Qt.ItemDataRole.AccessibleDescriptionRole)
            if staged:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            access.setEditable(False)
            self.property_model.appendRow([label, item, access])
        candidates = [field for field in self.fields if isinstance(field["value"], str)
                      and field["pointer"].endswith(("/text", "/name", "/description", "/value"))]
        preferred = ([field for field in candidates if field["editable"] and field["pointer"] in ("/core/name", "/core/value")]
                     or [field for field in candidates if field["editable"] and field["pointer"].endswith("/text")]
                     or [field for field in candidates if field["editable"]]
                     or [field for field in candidates if field["pointer"].endswith("/text")]
                     or candidates)
        target = self.content_targets.get(locator_key(self.selected))
        choice = next((field for field in candidates if field["pointer"] == target), preferred[-1] if preferred else None)
        self.content_target.clear()
        for field in candidates:
            self.content_target.addItem(field["pointer"] + (" — Editable" if field["editable"] else " — Read-only"), self.fields.index(field))
        if choice:
            self.content_target.setCurrentIndex(candidates.index(choice))
        self._show_content_field(choice)
        self.byte_data = result["bytes"]
        self.byte_offset = self.byte_data["offset"]
        self.render_bytes()
        self.populating = False
        self._update_title()
        self._busy(False)

    def _select_content_field(self, index):
        if self.populating or self.selected is None or index < 0:
            return
        field = self.fields[self.content_target.itemData(index)]
        self.content_targets[locator_key(self.selected)] = field["pointer"]
        self.populating = True
        self._show_content_field(field)
        self.populating = False
        self._update_title()
        self._busy(self.controller.busy)

    def _show_content_field(self, field):
        self.content_field = field if field and field["editable"] else None
        self.has_content = field is not None
        view_key = (locator_key(self.selected), self.content_field["pointer"]) if self.content_field else None
        format = self.content_views.get(view_key, "plain")
        self.content_editor.set_value(field["value"] if field else "", format)
        if self.content_field:
            draft = self.content_drafts.get(view_key)
            if draft:
                self.content_editor.set_buffer(draft.get("buffer", draft["value"]), draft.get("format", "plain"))
        self.content_editor.set_readonly(self.content_field is None)

    def render_bytes(self, *args):
        if self.byte_data:
            self.bytes_view.setPlainText(hex_page(self.byte_data["hex"], self.byte_offset) if self.byte_mode.currentIndex() == 0 else self.byte_data["escaped"])
            count = len(bytes.fromhex(self.byte_data["hex"]))
            start, size = self.byte_offset, self.byte_data["size"]
            self.byte_info.setText(f"0x{start:08X}–0x{start + count:08X} · {count:,} / {size:,} bytes · Read-only")
            self.byte_info.setToolTip("Range start is inclusive; end is exclusive. Each backend page is at most 4 KiB.")
            self._busy(self.controller.busy)

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
            try:
                value = codecs.editor_text(draft["buffer"], draft["format"]) if "buffer" in draft else draft["value"]
            except ValueError as error:
                self.show_error(f"Cannot stage {draft['pointer']}: {error}")
                return
            operation = next((item for item in proposed if item["record"] == draft["record"] and item["pointer"] == draft["pointer"]), None)
            if operation:
                operation["value"] = value
            else:
                proposed.append({key: deepcopy(draft[key]) for key in ("record", "pointer", "expected_value")})
                proposed[-1]["value"] = value
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