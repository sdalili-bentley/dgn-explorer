"""Synthetic frozen-application verification; never opens customer documents."""

import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QEventLoop, QTimer, Qt, qVersion

from .desktop import ExplorerWindow, WorkerController
from .workspace import Workspace


def wait_for(controller, predicate):
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    failures = []

    def completed(result):
        if predicate():
            loop.quit()

    def failed(error):
        failures.append(error.get("message", "Worker fails"))
        loop.quit()

    controller.completed.connect(completed)
    controller.failed.connect(failed)
    try:
        if not predicate():
            timeout.start(30000)
            loop.exec()
    finally:
        timeout.stop()
        controller.completed.disconnect(completed)
        controller.failed.disconnect(failed)
    if failures:
        raise RuntimeError(failures[0])
    if not predicate():
        raise TimeoutError("Packaged worker does not complete the expected transition")


def verify_gui(app, report):
    from test_support import create_workspace

    report = Path(report).absolute()
    report.parent.mkdir(parents=True, exist_ok=True)
    result = {"success": False, "frozen": bool(getattr(sys, "frozen", False)), "qt": qVersion()}
    try:
        with tempfile.TemporaryDirectory(prefix="dgn-portable-gui-") as temporary:
            root = Path(temporary)
            folder = create_workspace(root)
            original_bytes = (folder / "original.dgn").read_bytes()
            controller = WorkerController()
            window = ExplorerWindow(controller, data_root=root / "preferences")
            window.show()
            try:
                window.open_workspace(folder)
                wait_for(controller, lambda: window.revision is not None and not controller.busy)
                for row in range(window.tree_model.rowCount()):
                    item = window.tree_model.item(row, 0)
                    if item.data(Qt.ItemDataRole.UserRole) == {"ole_path": ["Notes"]}:
                        window.tree.setCurrentIndex(item.index())
                        break
                wait_for(controller, lambda: getattr(window, "content_field", None) is not None and not controller.busy)
                original_revision = window.revision
                edited = "<root>Portable marker</root>"
                window.content.setPlainText(edited)
                window.save()
                wait_for(controller, lambda: window.revision != original_revision and not controller.busy and not window.pending)
                with Workspace(folder) as saved:
                    if saved.get_record({"ole_path": ["Notes"]})["value"]["text"] != edited:
                        raise AssertionError("GUI save does not persist the edited text")
                output = root / "edited.dgn"
                window.save_as(str(output))
                wait_for(controller, lambda: output.exists() and not controller.busy)
                reimported = root / "reimported"
                window.request("import", {"source": str(output), "folder": str(reimported)}, lambda result: None)
                wait_for(controller, lambda: reimported.exists() and not controller.busy)
                with Workspace(reimported) as packed:
                    if packed.get_record({"ole_path": ["Notes"]})["value"]["text"] != edited:
                        raise AssertionError("GUI exported DGN does not reimport with the saved text")
                if (folder / "original.dgn").read_bytes() != original_bytes:
                    raise AssertionError("GUI workflow modifies the original DGN")
                app.processEvents()
                image = window.grab().toImage()
                colors = {image.pixelColor(column, row).rgba() for column in range(0, image.width(), 50) for row in range(0, image.height(), 50)}
                if image.isNull() or len(colors) < 2 or not image.save(str(report.with_suffix(".png"))):
                    raise AssertionError("Packaged GUI screenshot is blank or unavailable")
                result.update(success=True, records=window.tree_model.rowCount(), save=True, save_as=True, edited_output_reimported=True, original_preserved=True, screenshot=True)
            finally:
                window.closing = True
                if controller.busy:
                    controller.terminate()
                    controller.process.waitForFinished(30000)
                window.close()
                app.processEvents()
    except Exception as error:
        result["error"] = str(error)
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["success"] else 1