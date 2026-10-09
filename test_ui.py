"""Qt interaction tests, skipped explicitly until Qt dependencies are admitted."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_support import STORAGE_AVAILABLE

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox
    from dgn_explorer.desktop import ExplorerWindow, PropertyDelegate, WorkerController
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
        self.assertEqual(self.window.bytes_view.toPlainText(), "54 65 78 74")
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
                self.assertFalse(self.window.grab().isNull())


@unittest.skipUnless(QT_AVAILABLE and STORAGE_AVAILABLE, "Real Qt worker integration requires admitted Qt and Windows/pywin32")
class RealWorkerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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


if __name__ == "__main__":
    unittest.main()