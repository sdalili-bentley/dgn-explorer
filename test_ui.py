"""Qt interaction tests, skipped explicitly until Qt dependencies are admitted."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_support import STORAGE_AVAILABLE
from test_support import editor_test_root
from dgn_explorer import codecs

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QFont, QFontInfo, QKeySequence, QPalette, QStandardItem, QStandardItemModel
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QSplitter, QToolBar
    from dgn_explorer.desktop import ExplorerWindow, PropertyDelegate, WorkerController, hex_page
    from test_support import create_workspace

    class FakeController(QObject):
        completed = Signal(dict)
        failed = Signal(dict)
        progress = Signal(str)
        busyChanged = Signal(bool)

        def __init__(self):
            super().__init__()
            self.requests = []
            self.busy = False

        def start(self, operation, arguments):
            self.requests.append((operation, deepcopy(arguments)))
            self.busy = True
            self.busyChanged.emit(True)

        def finish(self, result):
            self.busy = False
            self.busyChanged.emit(False)
            self.completed.emit(result)

        def cancel(self):
            self.progress.emit("Cancelling")

        def terminate(self):
            self.busy = False
            self.busyChanged.emit(False)
            self.failed.emit({"message": "Worker stopped"})


@unittest.skipUnless(QT_AVAILABLE, "Policy-admitted Qt dependencies are not installed")
class UITests(unittest.TestCase):
    def test_matching_binding_and_native_runtime(self):
        from importlib.metadata import version
        from PySide6.QtCore import qVersion

        self.assertEqual(qVersion(), "6.11.2")
        self.assertEqual(version("PySide6-Essentials"), qVersion())
        self.assertEqual(version("shiboken6"), qVersion())

    def test_xml_invalid_nodes_are_rejected(self):
        from PySide6.QtXml import QDomDocument, QDomImplementation

        self.assertEqual(
            QDomImplementation.invalidDataPolicy(),
            QDomImplementation.InvalidDataPolicy.ReturnNullNode,
        )
        document = QDomDocument()
        self.assertTrue(document.createComment("bad--comment").isNull())
        self.assertTrue(document.createCDATASection("bad]]>section").isNull())
        self.assertTrue(document.createProcessingInstruction("marker", "bad?>instruction").isNull())
        self.assertFalse(document.createComment("valid comment").isNull())

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.controller = FakeController()
        self.window = ExplorerWindow(self.controller, data_root=Path(self.temporary.name))
        self.window.show()
        self.addCleanup(self.clean_window)
        self.window.folder = Path("workspace")
        self.window.revision = "sha256:test"
        self.window.selected = {"ole_path": ["Notes"]}
        self.record = {"record": self.window.selected, "fields": [
            {"pointer": "/text", "value": "Original", "saved_value": "Original", "editable": True},
            {"pointer": "/kind", "value": "text", "saved_value": "text", "editable": False}],
            "bytes": {"offset": 0, "size": 8, "hex": "54 65 78 74", "escaped": '"Text"', "next_offset": None}}
        self.window.display_record(self.record)

    def clean_window(self):
        self.window.closing = True
        self.controller.busy = False
        self.window.close()
        self.window.deleteLater()

    def test_readonly_and_content(self):
        self.assertTrue(self.window.property_model.item(0, 1).isEditable())
        self.assertFalse(self.window.property_model.item(1, 1).isEditable())
        self.assertEqual(self.window.content.toPlainText(), "Original")
        self.assertFalse(self.window.content.isReadOnly())

    def test_content_format_switching_is_reversible_without_creating_drafts(self):
        for index, format in enumerate(codecs.EDITOR_FORMATS):
            with self.subTest(format=format):
                self.window.content_format.setCurrentIndex(index)
                self.assertEqual(self.window.content.toPlainText(), codecs.editor_encode(b"Original", format))
                self.assertEqual(self.window.content_editor.value(), "Original")
                self.assertFalse(self.window.content_drafts)
                self.assertFalse(self.window.pending)
                self.assertFalse(self.controller.requests)
                self.assertIn("8 bytes", self.window.content_validation.text())
                self.assertIn("8 characters", self.window.content_validation.text())
        self.window.display_record(self.record)
        self.assertEqual(self.window.content_editor.format, "base64")

    def test_editing_and_staging_each_content_representation(self):
        for index, format in enumerate(codecs.EDITOR_FORMATS):
            with self.subTest(format=format):
                value = "café 😀" if format == "plain" else "A\0B\r\ncafé 😀"
                self.window.display_record(self.record)
                self.window.content_format.setCurrentIndex(index)
                self.window.content.setPlainText(codecs.editor_encode(value.encode("utf-8"), format))
                self.assertIn("Draft — not staged", self.window.content_info.text())
                self.assertTrue(self.window.content_button.isEnabled())
                QTest.mouseClick(self.window.content_button, Qt.MouseButton.LeftButton)
                operation, arguments = self.controller.requests[-1]
                self.assertEqual(operation, "apply")
                self.assertEqual(arguments["patch"]["operations"][0]["value"], value)
                self.assertEqual(set(arguments["patch"]["operations"][0]), {"record", "pointer", "expected_value", "value"})
                self.assertNotIn("approve", arguments)
                self.controller.terminate()
                self.window.content_drafts.clear()

    def test_nonprintable_strings_and_plain_switch_preserve_nulls_and_line_endings(self):
        for value in ("A\0B\r\nC", "A\u2028B\u2029C", "\x1f\x7f😀", ""):
            with self.subTest(value=repr(value)):
                record = deepcopy(self.record)
                record["fields"][0]["value"] = record["fields"][0]["saved_value"] = value
                self.window.content_views.clear()
                self.window.display_record(record)
                self.assertEqual(self.window.content_editor.value(), value)
                self.assertNotIn("\0", self.window.content.toPlainText())
                if value:
                    self.assertEqual(self.window.content_editor.format, "escaped")
                    self.window.content_format.setCurrentIndex(2)
                    self.window.content_format.setCurrentIndex(0)
                    self.assertEqual(self.window.content_editor.format, "escaped")
                    self.assertEqual(self.window.content_format.currentIndex(), 1)
                    self.assertEqual(self.window.content_editor.value(), value)
                    self.assertIn("preserve nulls", self.window.content_validation.text())
                self.assertFalse(self.window.content_drafts)

    def test_pasted_plain_nulls_automatically_use_safe_escape_representation(self):
        for index in (0, 1):
            with self.subTest(index=index):
                self.window.content_format.setCurrentIndex(index)
                self.window.content.setPlainText("A\0B")
                self.assertEqual(self.window.content_editor.format, "escaped")
                self.assertEqual(self.window.content.toPlainText(), r"A\u0000B")
                self.assertEqual(self.window.content_editor.value(), "A\0B")
                self.assertEqual(next(iter(self.window.content_drafts.values()))["value"], "A\0B")

    def test_invalid_format_input_is_retained_validated_and_blocks_save(self):
        from unittest.mock import patch

        for index, invalid in ((1, r"\xG0"), (2, "00 zz"), (3, "not base64!")):
            with self.subTest(index=index):
                self.window.content_drafts.clear()
                self.window.content_views.clear()
                self.window.display_record(self.record)
                self.window.content_format.setCurrentIndex(index)
                self.window.content.setPlainText(invalid)
                self.assertIn("Invalid input", self.window.content_validation.text())
                self.assertTrue(self.window.content.property("invalidInput"))
                self.assertFalse(self.window.content_button.isEnabled())
                self.assertFalse(self.window.content_export.isEnabled())
                self.window.content_format.setCurrentIndex(0)
                self.assertEqual(self.window.content_format.currentIndex(), index)
                self.assertEqual(self.window.content.toPlainText(), invalid)
                self.assertIn("Cannot switch", self.window.content_validation.text())
                with patch.object(self.window, "show_error") as alert:
                    before = len(self.controller.requests)
                    self.window.save()
                    self.assertEqual(len(self.controller.requests), before)
                    alert.assert_called_once()
                other = deepcopy(self.record)
                other["record"] = {"ole_path": ["Other"]}
                self.window.display_record(other)
                self.window.content.setPlainText("Second draft")
                self.window.display_record(self.record)
                self.assertEqual(self.window.content.toPlainText(), invalid)
                self.assertEqual(self.window.content_format.currentIndex(), index)
                self.assertIn("Invalid input", self.window.content_validation.text())
                shown = codecs.editor_encode("Fixed\0value".encode(), codecs.EDITOR_FORMATS[index])
                self.window.content.setPlainText(shown)
                self.assertFalse(self.window.content_editor.error)
                self.assertTrue(self.window.content_button.isEnabled())

    def test_copy_helpers_use_whole_payload_and_keep_drafts_unchanged(self):
        value = "A\0é😀\r\n"
        self.window.content_format.setCurrentIndex(1)
        self.window.content.setPlainText(codecs.editor_encode(value.encode(), "escaped"))
        drafts = deepcopy(self.window.content_drafts)
        for format in ("escaped", "hex", "base64"):
            with self.subTest(format=format):
                self.window.content_editor.copy_actions[format].trigger()
                self.assertEqual(self.app.clipboard().text(), codecs.editor_encode(value.encode(), format))
                self.assertNotIn("\0", self.app.clipboard().text())
                self.assertEqual(self.window.content_drafts, drafts)

    def test_property_delegate_escape_roundtrip_and_invalid_input(self):
        model = QStandardItemModel(1, 1)
        index = model.index(0, 0)
        original = "A\0B\r\n😀\\path"
        model.setData(index, original, Qt.ItemDataRole.UserRole)
        editor = self.window.delegate.createEditor(self.window, None, index)
        self.addCleanup(editor.deleteLater)
        self.window.delegate.setEditorData(editor, index)
        self.assertNotIn("\0", editor.text())
        self.assertIn(r"\u0000", editor.text())
        self.window.delegate.setModelData(editor, model, index)
        self.assertEqual(index.data(Qt.ItemDataRole.UserRole), original)
        editor.setText(r"Edit\x00\u0000\t\\literal")
        self.window.delegate.setModelData(editor, model, index)
        self.assertEqual(index.data(Qt.ItemDataRole.UserRole), "Edit\0\0\t\\literal")
        self.assertNotIn("\0", index.data(Qt.ItemDataRole.DisplayRole))
        spy = QSignalSpy(self.window.delegate.invalid)
        editor.setText(r"\uZZZZ")
        self.window.delegate.setModelData(editor, model, index)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(index.data(Qt.ItemDataRole.UserRole), "Edit\0\0\t\\literal")

    def test_advanced_property_dialog_formats_load_stage_and_cancel(self):
        root = editor_test_root(self)
        source = root / "property"
        source.write_bytes(b"A\0B\r\n")
        self.window.table.setCurrentIndex(self.window.property_model.index(0, 1))
        self.assertTrue(self.window.property_button.isEnabled())
        self.window.edit_property()
        dialog = self.window.property_dialog
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.payload.format, "escaped")
        dialog.payload.load_file(str(source))
        dialog.payload.selector.setCurrentIndex(2)
        self.assertEqual(dialog.payload.editor.toPlainText(), "41 00 42 0d 0a")
        dialog.payload.editor.setPlainText("bad hex")
        self.assertFalse(dialog.stage_button.isEnabled())
        dialog.accept()
        self.assertTrue(dialog.isVisible())
        dialog.payload.editor.setPlainText("41 00 42")
        QTest.mouseClick(dialog.stage_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.controller.requests[-1][1]["patch"]["operations"][0]["value"], "A\0B")
        self.controller.terminate()
        self.window.edit_property()
        dialog = self.window.property_dialog
        dialog.payload.editor.setPlainText("Cancelled")
        before = len(self.controller.requests)
        dialog.reject()
        self.assertEqual(len(self.controller.requests), before)
        self.window.table.setCurrentIndex(self.window.property_model.index(1, 1))
        self.assertFalse(self.window.property_button.isEnabled())

    def test_content_file_load_export_and_stage_preserve_exact_payload(self):
        from unittest.mock import patch

        root = editor_test_root(self)
        value = "A\0B\r\ncafé 😀"
        source, output = root / "payload", root / "export"
        source.write_bytes(value.encode())
        with patch("dgn_explorer.desktop.QFileDialog.getOpenFileName", return_value=(str(source), "")):
            QTest.mouseClick(self.window.content_load, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.content_editor.format, "escaped")
        self.assertEqual(self.window.content_editor.value(), value)
        self.assertFalse(self.controller.requests)
        with patch("dgn_explorer.desktop.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            QTest.mouseClick(self.window.content_export, Qt.MouseButton.LeftButton)
        self.assertEqual(output.read_bytes(), source.read_bytes())
        self.assertEqual(source.read_bytes(), value.encode())
        QTest.mouseClick(self.window.content_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.controller.requests[-1][1]["patch"]["operations"][0]["value"], value)

    def test_binary_file_load_is_inspectable_exportable_but_not_stageable(self):
        root = editor_test_root(self)
        source = root / "binary"
        source.write_bytes(bytes(range(256)))
        self.window.content_editor.load_file(str(source))
        self.assertEqual(self.window.content_editor.format, "hex")
        self.assertIn("valid UTF-8", self.window.content_validation.text())
        self.assertFalse(self.window.content_button.isEnabled())
        self.assertTrue(self.window.content_export.isEnabled())
        self.window.content_format.setCurrentIndex(3)
        self.assertEqual(self.window.content_editor.bytes_value(), bytes(range(256)))
        output = root / "binary-export"
        self.window.content_editor.export_file(str(output))
        self.assertEqual(output.read_bytes(), source.read_bytes())
        self.assertFalse(self.controller.requests)

    def test_file_errors_and_cancel_preserve_buffer_and_report_nonblocking_alerts(self):
        from unittest.mock import patch

        root = editor_test_root(self)
        large = root / "oversize"
        large.write_bytes(b"x" * (codecs.EDITOR_LIMIT + 1))
        self.window.content.setPlainText("Retain draft")
        for source in (large, root / "missing"):
            with self.subTest(source=source):
                self.window.content_editor.load_file(str(source))
                self.assertIsNotNone(self.window.error_dialog)
                self.assertEqual(self.window.content.toPlainText(), "Retain draft")
                self.window.error_dialog.close()
        existing = root / "existing"
        existing.write_bytes(b"original")
        self.window.content_editor.export_file(str(existing))
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertIsNotNone(self.window.error_dialog)
        self.window.error_dialog.close()
        for method in ("getOpenFileName", "getSaveFileName"):
            with patch(f"dgn_explorer.desktop.QFileDialog.{method}", return_value=("", "")):
                self.window.content_editor.load_file() if method == "getOpenFileName" else self.window.content_editor.export_file()
        self.assertEqual(self.window.content.toPlainText(), "Retain draft")

    def test_export_byte_page_writes_raw_octets_not_formatted_offsets(self):
        from unittest.mock import patch

        root = editor_test_root(self)
        self.window.byte_data = {"offset": 4096, "size": 4100, "hex": "00 1f 48 ff", "escaped": '"page"', "next_offset": None}
        self.window.byte_offset = 4096
        self.window.render_bytes()
        output = root / "page"
        with patch("dgn_explorer.desktop.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            QTest.mouseClick(self.window.byte_export, Qt.MouseButton.LeftButton)
        self.assertEqual(output.read_bytes(), b"\0\x1fH\xff")
        self.assertIn("0x00001000", self.window.byte_info.text())

    def test_representation_controls_accessibility_tab_navigation_and_busy_states(self):
        controls = (self.window.property_button, self.window.content_format, self.window.content_load,
                    self.window.content_export, self.window.content_copy, self.window.byte_export)
        for control in controls:
            with self.subTest(control=control.accessibleName()):
                self.assertTrue(control.accessibleName())
                self.assertTrue(control.accessibleDescription())
                self.assertTrue(control.toolTip())
        self.assertTrue(self.window.content_validation.accessibleName())
        for before, after in ((self.window.content_format, self.window.content_load),
                              (self.window.content_load, self.window.content_export),
                              (self.window.content_export, self.window.content_copy),
                              (self.window.content_copy, self.window.content)):
            self.assertLess(self.focus_distance(before, after), 5)
        self.window.load_bytes(0)
        for control in controls:
            self.assertFalse(control.isEnabled())
        self.controller.terminate()
        readonly = deepcopy(self.record)
        readonly["fields"][0]["editable"] = False
        self.window.display_record(readonly)
        self.assertFalse(self.window.content_load.isEnabled())
        self.assertTrue(self.window.content_export.isEnabled())
        self.assertTrue(self.window.content_format.isEnabled())

    def test_search_keyboard_request(self):
        self.window.search.setFocus()
        QTest.keyClicks(self.window.search, "needle")
        QTest.keyClick(self.window.search, Qt.Key.Key_Return)
        operation, arguments = self.controller.requests[-1]
        self.assertEqual(operation, "search")
        self.assertEqual(arguments["text"], "needle")
        self.assertEqual(arguments["limit"], 200)

    def test_content_click_stages_not_saves(self):
        self.window.content.setPlainText("Edited")
        QTest.mouseClick(self.window.content_button, Qt.MouseButton.LeftButton)
        operation, arguments = self.controller.requests[-1]
        self.assertEqual(operation, "apply")
        self.assertNotIn("approve", arguments)
        self.assertEqual(arguments["patch"]["operations"][0]["value"], "Edited")

    def test_undo_redo_and_journal(self):
        self.window.propose(self.record["fields"][0], "Edited")
        self.controller.finish({"applied": False})
        self.assertEqual(self.window.pending[0]["value"], "Edited")
        self.assertEqual(self.controller.requests[-1][0], "journal")
        self.controller.finish({"journaled": True})
        self.controller.finish(self.record)
        self.window.undo_stack.undo()
        self.assertEqual(self.window.pending, [])
        self.controller.finish({"journaled": False})
        self.controller.finish(self.record)
        self.window.undo_stack.redo()
        self.assertEqual(self.window.pending[0]["value"], "Edited")

    def test_failure_and_busy_controls(self):
        self.window.load_bytes(0)
        self.assertFalse(self.window.table.isEnabled())
        self.assertTrue(self.window.cancel_action.isEnabled())
        self.controller.terminate()
        self.assertTrue(self.window.table.isEnabled())
        self.assertIn("stopped", self.window.statusBar().currentMessage())

    def test_byte_modes_and_paging(self):
        self.assertEqual(self.window.bytes_view.toPlainText(), hex_page("54 65 78 74", 0))
        self.window.byte_mode.setCurrentIndex(1)
        self.assertEqual(self.window.bytes_view.toPlainText(), '"Text"')
        self.assertFalse(self.window.byte_next.isEnabled())

    def test_open_dgn_uses_private_workspace_without_second_dialog(self):
        from unittest.mock import patch

        with patch("dgn_explorer.desktop.QFileDialog.getOpenFileName", return_value=("input.dgn", "")), patch("dgn_explorer.desktop.QFileDialog.getSaveFileName") as destination_dialog:
            self.window.open_dgn()
        destination_dialog.assert_not_called()
        operation, arguments = self.controller.requests[-1]
        self.assertEqual(operation, "import")
        destination = Path(arguments["folder"])
        self.assertTrue(destination.is_relative_to(self.window.data_root / "workspaces"))
        self.assertFalse(destination.exists())

    def test_recent_workspaces_persist_without_removing_workspace(self):
        folder = Path(self.temporary.name) / "workspace"
        folder.mkdir()
        self.window._opened(folder, {"revision": "sha256:test", "records": [], "next_cursor": None})
        values = json.loads((self.window.data_root / "recent-workspaces.json").read_bytes())
        self.assertEqual(values, [str(folder.absolute())])
        self.assertEqual(len(self.window.recent_menu.actions()), 1)
        self.assertTrue(folder.is_dir())

    def test_byte_navigation_is_disabled_while_busy(self):
        self.window.byte_data["next_offset"] = 4096
        self.window.render_bytes()
        self.window.load_bytes(0)
        self.assertFalse(self.window.byte_next.isEnabled())
        self.assertFalse(self.window.byte_mode.isEnabled())

    def test_typed_delegates(self):
        delegate = PropertyDelegate()
        model = QStandardItemModel(1, 1)
        index = model.index(0, 0)
        for value in (True, 3, 1.5, [1, 2], "Text"):
            with self.subTest(value=value):
                model.setData(index, value, Qt.ItemDataRole.UserRole)
                editor = delegate.createEditor(self.window, None, index)
                delegate.setEditorData(editor, index)
                self.assertIsInstance(editor, QCheckBox if type(value) is bool else QLineEdit)
                delegate.setModelData(editor, model, index)
                self.assertEqual(index.data(Qt.ItemDataRole.UserRole), value)
                editor.deleteLater()

    def test_invalid_typed_value(self):
        model = QStandardItemModel(1, 1)
        index = model.index(0, 0)
        model.setData(index, 3, Qt.ItemDataRole.UserRole)
        spy = QSignalSpy(self.window.delegate.invalid)
        editor = self.window.delegate.createEditor(self.window, None, index)
        editor.setText("NaN")
        self.window.delegate.setModelData(editor, model, index)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(index.data(Qt.ItemDataRole.UserRole), 3)

    def test_rejected_property_restores_accepted_value(self):
        item = self.window.property_model.item(0, 1)
        item.setData("Rejected", Qt.ItemDataRole.UserRole)
        item.setText("Rejected")
        self.assertEqual(self.controller.requests[-1][0], "apply")
        self.controller.terminate()
        self.assertEqual(item.text(), "Original")
        self.assertEqual(item.data(Qt.ItemDataRole.UserRole), "Original")
        self.assertEqual(self.window.pending, [])

    def test_unstaged_content_survives_reload_and_navigation(self):
        self.window.content.setPlainText("First draft")
        self.window.display_record(self.record)
        self.assertEqual(self.window.content.toPlainText(), "First draft")
        other = deepcopy(self.record)
        other["record"] = {"ole_path": ["Other"]}
        self.window.display_record(other)
        self.window.content.setPlainText("Second draft")
        self.window.display_record(self.record)
        self.assertEqual(self.window.content.toPlainText(), "First draft")
        self.assertEqual(len(self.window.content_drafts), 2)
        self.assertTrue(self.window.windowTitle().endswith("*"))

    def test_failed_record_load_preserves_displayed_identity(self):
        self.window.selected = {"ole_path": ["Other"]}
        self.window.load_bytes(0)
        self.controller.terminate()
        self.assertEqual(self.window.selected, self.record["record"])

    def test_cancel_close(self):
        from unittest.mock import patch

        self.window.pending = [{"value": "Edited"}]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.window.close()
        self.assertTrue(self.window.isVisible())

    def test_draft_close_cancel_and_rejected_save_preserve_content(self):
        from unittest.mock import patch

        self.window.content.setPlainText("Draft")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.window.close()
        self.assertTrue(self.window.isVisible())
        self.window.save()
        self.assertNotIn("approve", self.controller.requests[-1][1])
        self.controller.terminate()
        self.assertEqual(self.window.content.toPlainText(), "Draft")
        self.assertEqual(len(self.window.content_drafts), 1)

    def test_save_waits_for_draft_validation_and_journal(self):
        self.window.content.setPlainText("Edited")
        self.window.save()
        self.controller.finish({"applied": False})
        self.assertEqual(self.controller.requests[-1][0], "journal")
        self.controller.finish({"journaled": True})
        self.assertTrue(self.controller.requests[-1][1]["approve"])
        self.controller.finish({"revision": "sha256:saved", "applied": True})
        self.assertEqual(self.window.pending, [])
        self.assertEqual(self.window.content_drafts, {})
        self.assertEqual(self.window.revision, "sha256:saved")

    def test_switch_discard_waits_for_journal_and_restores_view(self):
        from unittest.mock import Mock, patch

        self.window.content.setPlainText("Draft")
        continuation = Mock()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.resolve_pending(continuation)
        continuation.assert_not_called()
        self.controller.finish({"journaled": False})
        self.controller.finish(self.record)
        continuation.assert_called_once()
        self.assertEqual(self.window.content.toPlainText(), "Original")

    def test_switch_save_waits_for_commit(self):
        from unittest.mock import Mock, patch

        self.window.content.setPlainText("Edited")
        continuation = Mock()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.window.resolve_pending(continuation)
        self.controller.finish({"applied": False})
        self.controller.finish({"journaled": True})
        continuation.assert_not_called()
        self.controller.finish({"revision": "sha256:saved", "applied": True})
        continuation.assert_called_once()

    def test_layout_at_window_sizes(self):
        for width, height in ((800, 600), (1200, 800)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                QApplication.processEvents()
                self.assertGreater(self.window.table.width(), 200)
                self.assertGreater(self.window.tree.width(), 100)
                self.assertLess(self.window.workspace_label.height(), self.window.workspace_label.fontMetrics().height() * 3)
                self.assertGreaterEqual(self.window.table.columnWidth(2), self.window.table.fontMetrics().horizontalAdvance("Read-only") + 28)
                self.assertFalse(self.window.grab().isNull())

    def test_record_browser_remains_usable_when_splitter_is_compressed(self):
        splitter = self.window.findChild(QSplitter, "recordSplitter")
        for width, height in ((520, 400), (640, 480), (1100, 720)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                splitter.setSizes([0, 10000])
                QApplication.processEvents()
                self.assertGreaterEqual(self.window.tree.width(), 160)
                self.assertGreater(self.window.table.width(), 200)
                self.assertLessEqual(self.window.minimumSizeHint().width(), self.window.width())
                splitter.setSizes([350, 700])
                QApplication.processEvents()
                self.assertGreaterEqual(self.window.tree.width(), 160)

    def test_explicit_failures_alert_and_background_failures_do_not(self):
        cases = (
            ("validate", self.window.validate, True),
            ("pack", lambda: self.window.save_as(str(Path(self.temporary.name) / "out.dgn")), True),
            ("save", self.window.save, True),
            ("show", lambda: self.window.load_bytes(0), False),
            ("search", lambda: self.window.load_page(0), False),
        )
        for name, action, alerts in cases:
            with self.subTest(operation=name):
                action()
                self.controller.terminate()
                dialog = self.window.error_dialog
                self.assertEqual(dialog is not None, alerts)
                self.assertIn("stopped", self.window.statusBar().currentMessage())
                self.assertTrue(self.window.table.isEnabled())
                if dialog is not None:
                    self.assertTrue(dialog.isVisible())
                    self.assertEqual(dialog.accessibleName(), "Operation failed")
                    self.assertEqual(dialog.text(), "Worker stopped")
                    self.assertEqual(dialog.textFormat(), Qt.TextFormat.PlainText)
                    self.assertTrue(dialog.accessibleDescription())
                    self.assertTrue(dialog.windowModality() != Qt.WindowModality.NonModal)
                    dialog.close()
                    QApplication.processEvents()
                    self.assertIsNone(self.window.error_dialog)
        self.window.validate()
        self.controller.terminate()
        first = self.window.error_dialog
        self.window.validate()
        self.controller.terminate()
        self.assertIsNot(self.window.error_dialog, first)
        self.window.error_dialog.close()
        message = '<b>Invalid</b> <a href="file:target">passive error</a>'
        self.window.show_error(message)
        self.assertEqual(self.window.error_dialog.text(), message)
        self.assertEqual(self.window.error_dialog.textFormat(), Qt.TextFormat.PlainText)
        self.window.error_dialog.close()

    def test_controls_have_accessible_names_tooltips_and_shortcuts(self):
        window = self.window
        for widget in (window.search, window.more, window.tree, window.tabs, window.table, window.content, window.content_button,
                       window.byte_mode, window.byte_previous, window.byte_next, window.bytes_view, window.changes):
            with self.subTest(widget=widget.objectName() or type(widget).__name__):
                self.assertTrue(widget.accessibleName())
        for button in (window.more, window.byte_previous, window.byte_next):
            self.assertTrue(button.toolTip())
        for action in (window.open_action, window.workspace_action, window.save_action, window.pack_action, window.validate_action, window.cancel_action, window.force_action):
            self.assertTrue(action.toolTip())
            self.assertFalse(action.icon().isNull())
        shortcuts = {action: action.shortcut() for action in (window.open_action, window.save_action, window.pack_action, window.undo_action, window.redo_action, window.find_action)}
        for action, shortcut in shortcuts.items():
            with self.subTest(action=action.text()):
                self.assertFalse(shortcut.isEmpty())
        self.assertEqual(len({shortcut.toString() for shortcut in shortcuts.values()}), len(shortcuts))
        self.assertEqual([window.tabs.tabText(index) for index in range(window.tabs.count())], ["Properties", "Content", "Bytes", "Changes"])

    def test_find_shortcut_focuses_search_and_tab_order(self):
        self.window.search.setText("previous")
        self.window.tree.setFocus()
        self.window.find_action.trigger()
        self.assertIs(self.window.focusWidget(), self.window.search)
        self.assertEqual(self.window.search.selectedText(), "previous")
        self.window.next_cursor = 200
        self.window._busy(False)
        chain, widget = [], self.window.search
        for _ in range(40):
            widget = widget.nextInFocusChain()
            if widget in (self.window.more, self.window.tree, self.window.tabs) and widget not in chain:
                chain.append(widget)
        self.assertEqual(chain, [self.window.more, self.window.tree, self.window.tabs])
        self.assertLess(self.focus_distance(self.window.search, self.window.more), self.focus_distance(self.window.search, self.window.tree))

    def focus_distance(self, start, target):
        widget, distance = start, 0
        while widget is not target and distance < 200:
            widget, distance = widget.nextInFocusChain(), distance + 1
        return distance

    def test_property_keyboard_editing_proposes_typed_value(self):
        index = self.window.property_model.index(0, 1)
        self.window.table.setCurrentIndex(index)
        self.window.table.edit(index)
        editor = self.window.table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.selectAll()
        QTest.keyClicks(editor, "Keyboard")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QApplication.processEvents()
        operation, arguments = self.controller.requests[-1]
        self.assertEqual(operation, "apply")
        self.assertEqual(arguments["patch"]["operations"][0]["value"], "Keyboard")
        self.assertNotIn("approve", arguments)

    def test_inspector_headers_and_monospace_fonts(self):
        record = deepcopy(self.record)
        record["kind"] = "xml"
        record["fields"] += [
            {"pointer": "/encoding", "value": "utf-16-le", "saved_value": "utf-16-le", "editable": False},
            {"pointer": "/bom_hex", "value": "fffe", "saved_value": "fffe", "editable": False},
        ]
        self.window.display_record(record)
        self.assertEqual(self.window.record_label.text(), "Notes · xml")
        self.assertIn("utf-16-le", self.window.content_info.text())
        self.assertIn("BOM fffe", self.window.content_info.text())
        self.assertIn("Editable", self.window.content_info.text())
        for editor in (self.window.content, self.window.bytes_view, self.window.changes):
            with self.subTest(editor=editor.accessibleName()):
                self.assertEqual(editor.font().styleHint(), QFont.StyleHint.TypeWriter)
                self.assertTrue(QFontInfo(editor.font()).fixedPitch())
                self.assertEqual(editor.lineWrapMode(), editor.LineWrapMode.NoWrap)
                self.assertTrue(editor.accessibleDescription())

    def test_edit_states_are_textual_and_staged_values_are_emphasized(self):
        self.window.content.setPlainText("Draft")
        self.assertEqual(self.window.edit_state.text(), "1 draft")
        self.assertIn("Draft — not staged", self.window.content_info.text())
        self.assertEqual(self.window.property_model.item(1, 2).text(), "Read-only")
        staged = deepcopy(self.record)
        staged["fields"][0]["value"] = "Staged"
        self.window.content_drafts.clear()
        self.window.pending = [{"record": self.window.selected, "pointer": "/text", "expected_value": "Original", "value": "Staged"}]
        self.window.display_record(staged)
        self.assertEqual(self.window.edit_state.text(), "1 staged")
        self.assertEqual(self.window.tabs.tabText(3), "Changes (1)")
        self.assertIn("Staged — not saved", self.window.content_info.text())
        self.assertEqual(self.window.property_model.item(0, 2).text(), "Staged")
        self.assertTrue(self.window.property_model.item(0, 1).font().bold())
        self.assertIn("not saved", self.window.property_model.item(0, 1).toolTip())
        self.assertTrue(self.window.property_model.item(0, 1).data(Qt.ItemDataRole.AccessibleDescriptionRole))
        self.window.pending.clear()
        self.window.display_record(self.record)
        self.assertEqual(self.window.edit_state.text(), "Saved")
        self.assertFalse(self.window.property_model.item(0, 1).font().bold())

    def test_readonly_text_is_visible_without_enabling_editing(self):
        record = deepcopy(self.record)
        record["fields"][0]["editable"] = False
        record["fields"][0]["value"] = "<root>Read only</root>"
        self.window.display_record(record)
        self.assertEqual(self.window.content.toPlainText(), "<root>Read only</root>")
        self.assertTrue(self.window.content.isReadOnly())
        self.assertFalse(self.window.content_button.isEnabled())
        self.assertIn("Read-only", self.window.content_info.text())
        self.assertFalse(self.window.content_drafts)

    def test_byte_headers_absolute_offsets_empty_pages_and_busy_render(self):
        for offset, octets, size in ((4096, "00 41 ff", 4099), (0, "", 0), (4096, "", 4096)):
            with self.subTest(offset=offset, octets=octets):
                self.window.byte_data = {"offset": offset, "size": size, "hex": octets, "escaped": '"page"', "next_offset": None}
                self.window.byte_offset = offset
                self.window.render_bytes()
                self.assertEqual(self.window.bytes_view.toPlainText(), hex_page(octets, offset))
                self.assertIn(f"0x{offset:08X}", self.window.byte_info.text())
                self.assertIn(f"/ {size:,} bytes", self.window.byte_info.text())
                self.assertEqual(self.window.byte_previous.isEnabled(), offset > 0)
                self.assertFalse(self.window.byte_next.isEnabled())
        self.window.load_bytes(0)
        self.window.render_bytes()
        self.assertFalse(self.window.byte_previous.isEnabled())
        self.assertFalse(self.window.byte_next.isEnabled())
        self.assertFalse(self.window.byte_mode.isEnabled())

    def test_workspace_switch_resets_old_inspector_and_search_state(self):
        self.window.search.setText("old query")
        self.window.content.setPlainText("Draft")
        self.window.byte_offset = 4096
        folder = Path(self.temporary.name) / "other"
        folder.mkdir()
        self.window._opened(folder, {"revision": "sha256:other", "records": [], "next_cursor": None})
        self.assertEqual(self.window.search.text(), "")
        self.assertEqual(self.window.fields, [])
        self.assertIsNone(self.window.byte_data)
        self.assertIsNone(self.window.selected)
        self.assertEqual(self.window.byte_offset, 0)
        for control in (self.window.byte_previous, self.window.byte_next, self.window.byte_mode, self.window.content_button):
            self.assertFalse(control.isEnabled())
        for editor in (self.window.bytes_view, self.window.content, self.window.changes):
            self.assertEqual(editor.toPlainText(), "")
        self.assertEqual(self.window.record_label.text(), "Select a record to inspect")
        self.assertEqual(self.window.byte_info.text(), "No byte page selected")
        self.assertEqual(self.window.edit_state.text(), "Saved")
        self.assertEqual(self.window.workspace_label.text(), "other")
        self.assertFalse(self.window.content_drafts)

    def test_progress_and_cancel_are_visible_without_error_dialog(self):
        self.window.validate()
        self.assertTrue(self.window.progress_bar.isVisible())
        self.assertEqual((self.window.progress_bar.minimum(), self.window.progress_bar.maximum()), (0, 0))
        self.controller.progress.emit("Reading streams")
        self.assertEqual(self.window.status_state.text(), "Reading streams")
        self.assertEqual(self.window.statusBar().currentMessage(), "Reading streams")
        self.controller.busy = False
        self.controller.busyChanged.emit(False)
        self.controller.failed.emit({"code": 6, "message": "Operation cancelled"})
        self.assertFalse(self.window.progress_bar.isVisible())
        self.assertEqual(self.window.status_state.text(), "Cancelled")
        self.assertIsNone(self.window.error_dialog)
        self.window.validate()
        self.controller.finish({"records": 2})
        self.assertEqual(self.window.status_state.text(), "Ready")
        self.assertFalse(self.window.progress_bar.isVisible())
        self.window.validate()
        self.controller.terminate()
        self.assertEqual(self.window.status_state.text(), "Error")

    def test_native_palette_and_high_contrast_are_not_overridden(self):
        previous = QPalette(self.app.palette())
        self.addCleanup(self.app.setPalette, previous)
        palette = QPalette(self.app.palette())
        for role, color in ((QPalette.ColorRole.Base, "#000000"), (QPalette.ColorRole.AlternateBase, "#000000"),
                            (QPalette.ColorRole.Text, "#ffffff"),
                            (QPalette.ColorRole.Highlight, "#ffff00"), (QPalette.ColorRole.HighlightedText, "#000000")):
            palette.setColor(role, color)
        self.app.setPalette(palette)
        QApplication.processEvents()
        for widget in (self.window.tree, self.window.table, self.window.search, self.window.content, self.window.bytes_view):
            with self.subTest(widget=widget.accessibleName()):
                for role in (QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase, QPalette.ColorRole.Text,
                             QPalette.ColorRole.Highlight, QPalette.ColorRole.HighlightedText):
                    self.assertEqual(widget.palette().color(role), palette.color(role))
        self.assertNotIn("color:", self.window.styleSheet())
        splitter = self.window.findChild(QSplitter)
        self.assertFalse(splitter.childrenCollapsible())
        toolbar = self.window.findChild(QToolBar)
        self.assertFalse(toolbar.isMovable())
        self.assertEqual(toolbar.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.assertFalse(self.window.tree.rootIsDecorated())
        self.assertTrue(self.window.tree.uniformRowHeights())
        self.assertTrue(self.window.table.verticalHeader().isHidden())

    def test_expanded_accessibility_and_shortcut_hints(self):
        for widget in (self.window.search, self.window.tree, self.window.tabs, self.window.table, self.window.content,
                       self.window.content_button, self.window.byte_mode, self.window.byte_previous,
                       self.window.byte_next, self.window.bytes_view, self.window.changes, self.window.progress_bar):
            with self.subTest(widget=widget.accessibleName()):
                self.assertTrue(widget.accessibleDescription())
        for action in (self.window.open_action, self.window.save_action, self.window.pack_action,
                       self.window.undo_action, self.window.redo_action, self.window.find_action):
            self.assertIn(action.shortcut().toString(QKeySequence.SequenceFormat.NativeText), action.toolTip())
            self.assertEqual(action.toolTip(), action.statusTip())
        for before, after in ((self.window.byte_mode, self.window.byte_previous),
                              (self.window.byte_previous, self.window.byte_next), (self.window.byte_next, self.window.bytes_view)):
            self.assertLess(self.focus_distance(before, after), 5)
        self.window.property_model.setData(self.window.property_model.index(0, 1), 42, Qt.ItemDataRole.UserRole)
        editor = self.window.delegate.createEditor(self.window, None, self.window.property_model.index(0, 1))
        self.addCleanup(editor.deleteLater)
        self.assertTrue(editor.accessibleName())
        self.assertTrue(editor.accessibleDescription())
        locator = {"ole_path": ['<img src="file:target">']}
        record = deepcopy(self.record)
        record["record"] = locator
        self.window.display_record(record)
        self.assertEqual(self.window.record_label.text(), locator["ole_path"][0])
        self.assertEqual(self.window.record_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertNotIn("<img", self.window.record_label.toolTip())
        self.assertIn("<img", self.window.record_label.accessibleDescription())
        self.window.display_page({"records": [{"record": locator, "kind": "text", "access": "rw"}], "next_cursor": None})
        self.assertNotIn("<img", self.window.tree_model.item(0, 0).toolTip())
        self.assertIn("<img", self.window.tree_model.item(0, 0).data(Qt.ItemDataRole.AccessibleDescriptionRole))


    def test_rich_feature_labels_are_plain_and_access_is_explicit(self):
        locator = {"ole_path": ["Dgn-Md", "#000001", "Dgn^G", "$2"], "chunk_index": 1}
        self.window.display_page({"records": [{"record": locator, "kind": "dgn-element", "feature": "Fonts",
                                              "preview": "<passive name>", "access": "rw"}], "next_cursor": None})
        self.assertIn("Fonts", self.window.tree_model.item(0, 0).text())
        self.assertIn("dgn-element", self.window.tree_model.item(0, 0).toolTip())
        self.assertEqual(self.window.tree_model.item(0, 1).text(), "Editable")
        record = deepcopy(self.record)
        record.update({"record": locator, "kind": "dgn-element", "feature": "Fonts"})
        record["fields"] = [{"pointer": "/core/name", "value": "Synthetic Font", "saved_value": "Synthetic Font", "editable": True}]
        self.window.display_record(record)
        self.assertIn("Fonts", self.window.record_label.text())
        self.assertEqual(self.window.content_field["pointer"], "/core/name")
        self.assertFalse(self.window.content.isReadOnly())
        self.assertEqual(self.window.content.toPlainText(), "Synthetic Font")

    def test_multiple_structured_content_fields_keep_separate_invalid_drafts(self):
        record = deepcopy(self.record)
        record["fields"] = [
            {"pointer": "/core/name", "value": "Font", "saved_value": "Font", "editable": True},
            {"pointer": "/xml/text", "value": "<DataGroup><Value>Old</Value></DataGroup>",
             "saved_value": "<DataGroup><Value>Old</Value></DataGroup>", "editable": True},
            {"pointer": "/json/text", "value": '{"value":1}', "saved_value": '{"value":1}', "editable": True},
            {"pointer": "/becxml/strings/1/value", "value": "café", "saved_value": "café", "editable": False},
        ]
        self.window.display_record(record)
        target = self.window.content_target
        self.assertEqual(target.count(), 4)
        self.assertTrue(target.accessibleName())
        self.assertTrue(target.accessibleDescription())
        target.setCurrentIndex(1)
        self.window.content.setPlainText("<DataGroup><Value>Changed</Value></DataGroup>")
        target.setCurrentIndex(0)
        self.window.content_format.setCurrentIndex(2)
        self.window.content.setPlainText("GG")
        self.assertTrue(self.window.content_editor.error)
        target.setCurrentIndex(2)
        self.window.content.setPlainText('{"value":2}')
        target.setCurrentIndex(3)
        self.assertTrue(self.window.content.isReadOnly())
        self.assertEqual(self.window.content_editor.value(), "café")
        self.assertEqual(len(self.window.content_drafts), 3)
        target.setCurrentIndex(0)
        self.assertEqual(self.window.content.toPlainText(), "GG")
        self.assertTrue(self.window.content_editor.error)
        self.window.stage_content()
        self.assertFalse(self.controller.requests)
        self.window.content.setPlainText("466f6e74204e6577")
        self.window.stage_content()
        changes = self.controller.requests[-1][1]["patch"]["operations"]
        self.assertEqual({operation["pointer"] for operation in changes}, {"/core/name", "/xml/text", "/json/text"})


@unittest.skipUnless(QT_AVAILABLE, "Policy-admitted Qt dependencies are not installed")
class HexPageTests(unittest.TestCase):
    def test_offsets_ascii_and_partial_rows(self):
        for size in (0, 1, 8, 16, 17, 4096):
            with self.subTest(size=size):
                data = (bytes(range(256)) * 16)[:size]
                lines = hex_page(data.hex(" "), 4096).splitlines()
                self.assertEqual(len(lines), (size + 15) // 16)
                for index, line in enumerate(lines):
                    self.assertTrue(line.startswith(f"{4096 + index * 16:08X}  "))
                    row = data[index * 16:index * 16 + 16]
                    self.assertEqual(line.split("|")[0][10:].split(), row.hex(" ").split())
                    self.assertEqual(line.split("|", 1)[1][:-1], "".join(chr(value) if 32 <= value < 127 else "." for value in row))

    def test_hex_view_keeps_markup_and_control_bytes_passive(self):
        data = b'<script>\r\n\x1b\x00\x7f\xff\\'
        text = hex_page(data.hex(), 0)
        self.assertIn("|<script>......\\|", text)
        self.assertNotIn("\r", text)
        self.assertNotIn("\x1b", text)


@unittest.skipUnless(QT_AVAILABLE, "Policy-admitted Qt dependencies are not installed")
class ControllerProtocolTests(unittest.TestCase):
    """WorkerController parsing, protocol violations and process-exit handling."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = WorkerController()
        self.addCleanup(self.controller.deleteLater)
        self.controller.request = {"request_id": "r1"}
        self.completed, self.failed, self.progress = [], [], []
        self.controller.completed.connect(self.completed.append)
        self.controller.failed.connect(self.failed.append)
        self.controller.progress.connect(self.progress.append)

    def message(self, event, payload, **changes):
        from dgn_explorer.worker import PROTOCOL

        return (json.dumps({"protocol": PROTOCOL, "request_id": "r1", "event": event, "payload": payload, **changes}) + "\n").encode()

    def finish(self, code=0, status=None):
        from PySide6.QtCore import QProcess

        self.controller._finished(code, status or QProcess.ExitStatus.NormalExit)

    def test_fragmented_output_is_reassembled(self):
        data = self.message("progress", {"stage": "starting"}) + self.message("completed", {"value": "\u03a9 ok"})
        for index in range(len(data)):
            self.controller._consume(data[index:index + 1])
        self.assertEqual(self.progress, ["starting"])
        self.assertFalse(self.controller.violated)
        self.finish()
        self.assertEqual(self.completed, [{"value": "\u03a9 ok"}])
        self.assertEqual(self.failed, [])

    def test_protocol_violations_fail_closed(self):
        from dgn_explorer.worker import MESSAGE_LIMIT, PROTOCOL

        violations = {
            "syntax": b"{not json}\n",
            "array": b"[]\n",
            "request": self.message("completed", {}, request_id="other"),
            "protocol": self.message("completed", {}, protocol="other"),
            "extra": self.message("completed", {}, extra=True),
            "payload": (json.dumps({"protocol": PROTOCOL, "request_id": "r1", "event": "completed", "payload": []}) + "\n").encode(),
            "event": self.message("unknown", {}),
            "after_terminal": self.message("completed", {}) + self.message("progress", {}),
            "duplicate_key": b'{"protocol":"x","protocol":"y"}\n',
            "oversized": b"x" * (MESSAGE_LIMIT + 1),
            "oversized_trailing_fragment": self.message("progress", {}) + b"x" * (MESSAGE_LIMIT + 1),
        }
        for name, data in violations.items():
            with self.subTest(violation=name):
                self.setUp()
                self.controller._consume(data)
                self.assertTrue(self.controller.violated)
                self.controller._consume(self.message("completed", {}))
                self.finish()
                self.assertEqual(self.completed, [])
                self.assertEqual(self.failed[-1]["code"], 3)

    def test_incomplete_or_abnormal_exits_fail(self):
        from PySide6.QtCore import QProcess

        cases = {
            "no_result": (b"", 0, QProcess.ExitStatus.NormalExit, 7),
            "nonzero": (self.message("completed", {}), 1, QProcess.ExitStatus.NormalExit, 7),
            "crash": (self.message("completed", {}), 0, QProcess.ExitStatus.CrashExit, 7),
            "trailing_partial": (self.message("completed", {}) + b'{"partial', 0, QProcess.ExitStatus.NormalExit, 7),
            "reported_failure": (self.message("failed", {"code": 4, "message": "Conflict"}), 4, QProcess.ExitStatus.NormalExit, 4),
        }
        for name, (data, code, status, expected) in cases.items():
            with self.subTest(case=name):
                self.setUp()
                self.controller._consume(data)
                self.finish(code, status)
                self.assertEqual(self.completed, [])
                self.assertEqual(self.failed[-1]["code"], expected)


@unittest.skipUnless(QT_AVAILABLE, "Policy-admitted Qt dependencies are not installed")
class ProcessFailureTests(unittest.TestCase):
    """Real child processes that crash, misbehave or cannot start."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_program(self, program):
        import sys

        controller = WorkerController()
        self.addCleanup(controller.deleteLater)
        controller.program = (program[0], program[1]) if program[0] != "python" else (sys.executable, program[1])
        failed, completed = QSignalSpy(controller.failed), QSignalSpy(controller.completed)
        busy = []
        controller.busyChanged.connect(busy.append)
        controller.start("open", {"folder": "unused"})
        self.assertTrue(failed.count() or failed.wait(30000))
        self.assertEqual(completed.count(), 0)
        self.assertEqual(busy[-1], False)
        QTest.qWait(50)
        self.assertFalse(controller.busy)
        return failed.at(0)[0]

    def test_crash_after_partial_output(self):
        script = "import os, sys; sys.stdin.readline(); sys.stdout.write('{\"partial'); sys.stdout.flush(); os._exit(3)"
        self.assertEqual(self.run_program(("python", ["-c", script]))["code"], 7)

    def test_invalid_output_kills_worker(self):
        script = "import sys, time; sys.stdin.readline(); print('not protocol', flush=True); time.sleep(60)"
        self.assertEqual(self.run_program(("python", ["-c", script]))["code"], 3)

    def test_backend_that_cannot_start(self):
        missing = str(Path(tempfile.gettempdir()) / "dgn-explorer-missing" / "missing-worker.exe")
        self.assertEqual(self.run_program((missing, []))["code"], 5)


def wait_until(predicate, timeout=60.0):
    import time

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        QTest.qWait(25)
    return True


@unittest.skipUnless(QT_AVAILABLE and STORAGE_AVAILABLE, "Real Qt worker integration requires admitted Qt and Windows/pywin32")
class RealWorkerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def editor_window(self, root, folder):
        window = ExplorerWindow(data_root=root / "data")
        self.addCleanup(window.deleteLater)

        def close():
            window.closing = True
            window.controller.terminate()
            wait_until(lambda: not window.controller.busy, 5)
            window.close()

        self.addCleanup(close)
        window.show()
        window.open_workspace(folder)
        self.assertTrue(wait_until(lambda: window.revision is not None and not window.controller.busy))
        return window

    def choose_editor_record(self, window, locator):
        row = next(row for row in range(window.tree_model.rowCount()) if window.tree_model.item(row, 0).data(Qt.ItemDataRole.UserRole) == locator)
        window.tree.setCurrentIndex(window.tree_model.index(row, 0))
        self.assertTrue(wait_until(lambda: window.displayed_locator == locator and not window.controller.busy))

    def test_real_property_file_nulls_save_export_and_dgn_reimport(self):
        from dgn_explorer.workspace import Workspace

        root = editor_test_root(self)
        folder = create_workspace(root, rich=True)
        original = (root / "input.dgn").read_bytes()
        title = {"ole_path": ["\x05SummaryInformation"], "section_index": 0, "property_id": "2"}
        window = self.editor_window(root, folder)
        self.choose_editor_record(window, title)
        row = next(row for row, field in enumerate(window.fields) if field["pointer"] == "/value")
        window.table.setCurrentIndex(window.property_model.index(row, 1))
        window.edit_property()
        dialog = window.property_dialog
        value = "café\0middle\r\n\tend"
        source = root / "title"
        source.write_bytes(value.encode("utf-8"))
        dialog.payload.load_file(str(source))
        for index in (2, 3, 1):
            dialog.payload.selector.setCurrentIndex(index)
            self.assertEqual(dialog.payload.value(), value)
        QTest.mouseClick(dialog.stage_button, Qt.MouseButton.LeftButton)
        self.assertTrue(wait_until(lambda: len(window.pending) == 1 and not window.controller.busy))
        self.assertEqual(window.pending[0]["value"], value)
        self.assertFalse(window.content_drafts)
        revision = window.revision
        window.save()
        self.assertTrue(wait_until(lambda: window.revision != revision and not window.controller.busy))
        self.assertFalse(window.pending)
        with Workspace(folder) as session:
            self.assertEqual(session.get_record(title)["value"]["value"], value)
        row = next(row for row, field in enumerate(window.fields) if field["pointer"] == "/value")
        window.table.setCurrentIndex(window.property_model.index(row, 1))
        window.edit_property()
        output = root / "title-export"
        window.property_dialog.payload.export_file(str(output))
        self.assertEqual(output.read_bytes(), source.read_bytes())
        window.property_dialog.reject()
        dgn = root / "edited.dgn"
        window.save_as(str(dgn))
        self.assertTrue(wait_until(lambda: dgn.exists() and not window.controller.busy))
        reimported = root / "reimported"
        codecs.extract(dgn, reimported, 1024 * 1024)
        with Workspace(reimported) as session:
            self.assertEqual(session.get_record(title)["value"]["value"], value)
        self.assertEqual((root / "input.dgn").read_bytes(), original)

    def test_real_new_metadata_tag_xml_json_edit_save_pack_and_reimport(self):
        from dgn_explorer.workspace import Workspace, get_pointer

        root = editor_test_root(self)
        folder = create_workspace(root, features=True)
        original = (root / "input.dgn").read_bytes()
        with Workspace(folder) as session:
            records = [record for record in session.records.values() if "#000001" in record.locator["ole_path"]]
            font = next(record.locator for record in records if record.value.get("core", {}).get("table_level") == 2 and "name" in record.value["core"])
            tag = next(record.locator for record in records if record.value.get("core", {}).get("kind") == "dgn-tag" and record.value["core"].get("data_type") == 1)
            json_record = next(record.locator for record in records if record.value.get("identity", {}).get("handler_id") == 22226 << 16 | 89)
            xml_record = next(record.locator for record in records if record.value.get("identity", {}).get("handler_id") == 22243 << 16)
            becxml = next(record.locator for record in records if record.value.get("identity", {}).get("handler_id", 0) >> 16 == 22271)
        changes = [(font, "/core/name", "GUI Font Ω"), (tag, "/core/value", "GUI Tag"),
                   (json_record, "/payload/text", '{"providerName":"GUI","groundBias":2}'),
                   (xml_record, "/payload/payload/text", "<DataGroup><Value>GUI Ω</Value></DataGroup>")]
        window = self.editor_window(root, folder)
        self.assertIn("Fonts", " ".join(window.tree_model.item(row, 0).text() for row in range(window.tree_model.rowCount())))
        for count, (locator, pointer, value) in enumerate(changes, 1):
            self.choose_editor_record(window, locator)
            self.assertEqual(window.content_field["pointer"], pointer)
            window.content.setPlainText(value)
            window.stage_content()
            self.assertTrue(wait_until(lambda: len(window.pending) == count and not window.controller.busy))
        self.choose_editor_record(window, becxml)
        self.assertTrue(window.content.isReadOnly())
        self.assertFalse(window.content_button.isEnabled())
        revision = window.revision
        window.save()
        self.assertTrue(wait_until(lambda: window.revision != revision and not window.controller.busy))
        output = root / "gui-features.dgn"
        window.save_as(str(output))
        self.assertTrue(wait_until(lambda: output.exists() and not window.controller.busy))
        reimported = root / "reimported"
        codecs.extract(output, reimported, 1024 * 1024)
        with Workspace(reimported) as session:
            for locator, pointer, value in changes:
                self.assertEqual(get_pointer(session.get_record(locator)["value"], pointer), value)
        self.assertEqual((root / "input.dgn").read_bytes(), original)

    def test_real_content_file_all_representations_stage_save_and_export(self):
        from dgn_explorer.workspace import Workspace

        root = editor_test_root(self)
        folder = create_workspace(root)
        original = (root / "input.dgn").read_bytes()
        window = self.editor_window(root, folder)
        self.choose_editor_record(window, {"ole_path": ["Notes"]})
        value = "<root>café 😀\n\t</root>"
        source = root / "content.xml"
        source.write_bytes(value.encode("utf-8"))
        window.content_editor.load_file(str(source))
        for index in (1, 2, 3, 0):
            window.content_format.setCurrentIndex(index)
            self.assertEqual(window.content_editor.value(), value)
        window.stage_content()
        self.assertTrue(wait_until(lambda: len(window.pending) == 1 and not window.content_drafts and not window.controller.busy))
        self.assertEqual(window.pending[0]["value"], value)
        revision = window.revision
        window.save()
        self.assertTrue(wait_until(lambda: window.revision != revision and not window.controller.busy))
        with Workspace(folder) as session:
            self.assertEqual(session.get_record({"ole_path": ["Notes"]})["value"]["text"], value)
        output = root / "export.xml"
        window.content_editor.export_file(str(output))
        self.assertEqual(output.read_bytes(), source.read_bytes())
        self.assertEqual((root / "input.dgn").read_bytes(), original)

    def test_real_controller_open_and_show(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = create_workspace(Path(temporary))
            controller = WorkerController()
            completed, failed = QSignalSpy(controller.completed), QSignalSpy(controller.failed)
            controller.start("open", {"folder": str(folder)})
            self.assertTrue(completed.wait(30000))
            self.assertEqual(failed.count(), 0)
            self.assertIn("revision", completed.at(0)[0])
            completed = QSignalSpy(controller.completed)
            controller.start("show", {"folder": str(folder), "record": {"ole_path": ["Notes"]}, "summary": True})
            self.assertTrue(completed.wait(30000))
            fields = {field["pointer"]: field for field in completed.at(0)[0]["fields"]}
            self.assertEqual(fields["/encoding"]["value"], "utf-8")

    def test_real_worker_cancellation_latency(self):
        import time
        from test_support import shared_workspace

        controller = WorkerController()
        self.addCleanup(controller.deleteLater)
        failed, progress = QSignalSpy(controller.failed), QSignalSpy(controller.progress)
        controller.start("validate", {"folder": str(shared_workspace(text_count=400))})
        self.assertTrue(progress.wait(30000))
        started = time.perf_counter()
        controller.cancel()
        self.assertTrue(failed.wait(30000))
        latency = time.perf_counter() - started
        self.assertEqual(failed.at(0)[0]["code"], 6)
        self.assertLess(latency, 5.0, f"GUI cancel latency {latency:.3f}s")
        self.assertTrue(wait_until(lambda: not controller.busy, 5))

    def test_large_workspace_paging_with_more_button(self):
        from test_support import shared_workspace

        with tempfile.TemporaryDirectory() as temporary:
            window = ExplorerWindow(data_root=Path(temporary))
            self.addCleanup(window.deleteLater)
            window.show()
            window.open_workspace(shared_workspace(text_count=400))
            self.assertTrue(wait_until(lambda: window.tree_model.rowCount() == 200 and not window.controller.busy))
            self.assertTrue(window.more.isEnabled())
            for expected in (400, 600, 800, 803):
                QTest.mouseClick(window.more, Qt.MouseButton.LeftButton)
                self.assertTrue(wait_until(lambda: window.tree_model.rowCount() == expected and not window.controller.busy), expected)
            self.assertFalse(window.more.isEnabled())
            identities = {json.dumps(window.tree_model.item(row, 0).data(Qt.ItemDataRole.UserRole), sort_keys=True) for row in range(window.tree_model.rowCount())}
            self.assertEqual(len(identities), 803)
            window.closing = True
            window.close()

    def test_gui_and_cli_report_the_same_validation_failure(self):
        import contextlib
        import io
        from dgn_explorer import cli

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = create_workspace(root)
            window = ExplorerWindow(data_root=root / "data")
            self.addCleanup(window.deleteLater)
            window.show()
            window.open_workspace(folder)
            self.assertTrue(wait_until(lambda: window.revision is not None and not window.controller.busy))
            row = next(row for row in range(window.tree_model.rowCount()) if window.tree_model.item(row, 0).data(Qt.ItemDataRole.UserRole) == {"ole_path": ["Notes"]})
            window.tree.setCurrentIndex(window.tree_model.index(row, 0))
            self.assertTrue(wait_until(lambda: window.displayed_locator == {"ole_path": ["Notes"]} and not window.controller.busy))
            field = window.content_field
            invalid = "<root>unclosed"
            window.propose(field, invalid)
            self.assertTrue(wait_until(lambda: not window.controller.busy))
            gui_message = window.statusBar().currentMessage()
            self.assertEqual(window.pending, [])
            patch_file = root / "patch.json"
            patch_file.write_text(json.dumps(window.patch([{"record": {"ole_path": ["Notes"]}, "pointer": field["pointer"], "expected_value": field["saved_value"], "value": invalid}])))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["--json", "apply", str(folder), "--patch", str(patch_file), "--dry-run"]), 3)
            self.assertEqual(gui_message, json.loads(output.getvalue())["errors"][0]["message"])
            self.assertIn("not well-formed", gui_message)
            window.closing = True
            window.close()


@unittest.skipUnless(QT_AVAILABLE, "Policy-admitted Qt dependencies are not installed")
class ScalingTests(unittest.TestCase):
    """Layouts at common Windows scale factors, each in a fresh Qt process."""

    SCRIPT = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from dgn_explorer.desktop import ExplorerWindow\n"
        "app = QApplication([])\n"
        "window = ExplorerWindow(data_root=Path(sys.argv[1]))\n"
        "window.show()\n"
        "result = {'ratio': window.devicePixelRatioF(), 'sizes': []}\n"
        "for width, height in ((640, 480), (800, 600), (1100, 720)):\n"
        "    window.resize(width, height)\n"
        "    app.processEvents()\n"
        "    image = window.grab()\n"
        "    result['sizes'].append({'table': window.table.width(), 'tree': window.tree.width(), 'search': window.search.width(), 'image': [image.width(), image.height()], 'hint': [window.minimumSizeHint().width(), window.minimumSizeHint().height()], 'window': [window.width(), window.height()]})\n"
        "print(json.dumps(result))\n"
    )

    def test_layout_at_scale_factors(self):
        import os
        import subprocess
        import sys

        for factor in ("1.25", "1.5", "2"):
            with self.subTest(scale=factor), tempfile.TemporaryDirectory() as temporary:
                environment = {**os.environ, "QT_SCALE_FACTOR": factor, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "windows")}
                completed = subprocess.run([sys.executable, "-c", self.SCRIPT, temporary], cwd=Path(__file__).parent, env=environment, capture_output=True, text=True, timeout=120)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout.strip().splitlines()[-1])
                self.assertAlmostEqual(result["ratio"], float(factor), delta=0.3)
                for size in result["sizes"]:
                    self.assertGreater(size["table"], 200)
                    self.assertGreater(size["tree"], 100)
                    self.assertGreater(size["search"], 100)
                    self.assertGreater(size["image"][0], 0)
                    self.assertLessEqual(size["hint"][0], size["window"][0])


if __name__ == "__main__":
    unittest.main()