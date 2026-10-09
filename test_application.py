"""Reusable application tests; optional real DGN checks live in test_dgn_folder."""

import ast
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlparse

import dgn_folder
from dgn_explorer import cli, codecs
from dgn_explorer.workspace import ConflictError, Limits, Workspace, parse_json
from test_support import STORAGE_AVAILABLE, create_workspace


class PackageTests(unittest.TestCase):
    def test_repository_documentation(self):
        root = Path(__file__).parent
        for document in [*root.glob("*.md"), *root.glob("skills/*/SKILL.md")]:
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                parsed = urlparse(target)
                if not parsed.scheme and parsed.path:
                    self.assertTrue((document.parent / unquote(parsed.path)).exists(), f"{document.name}: {target}")
        skill = (root / "skills" / "dgn-explorer" / "SKILL.md").read_text()
        self.assertTrue(skill.startswith("---\nname: dgn-explorer\n"))
        self.assertIn("description:", skill.split("---")[1])
        self.assertIn("explicit human consent", skill)

    def test_shared_codec_identity(self):
        self.assertIs(codecs.extract, dgn_folder.extract)
        self.assertIs(codecs.rebuild, dgn_folder.rebuild)

    def test_legacy_commands(self):
        for command in ("unpack", "extract", "pack", "rebuild", "inspect"):
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as result:
                    cli.main([command, "--help"])
                self.assertEqual(result.exception.code, 0)
                self.assertIn("usage:", output.getvalue())

    def test_legacy_entry_delegates(self):
        with patch("dgn_explorer.cli.main", return_value=7):
            self.assertEqual(dgn_folder.main(), 7)

    def test_no_qt_required(self):
        result = subprocess.run([sys.executable, "-c", "import sys; from dgn_explorer import cli; print('PySide6' in sys.modules)"], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

    def test_desktop_dependency_exposure_boundary(self):
        source = Path(__file__).parent / "dgn_explorer" / "desktop.py"
        nodes = list(ast.walk(ast.parse(source.read_text(encoding="utf-8"))))
        imports = {node.module for node in nodes if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imports & {"PySide6.QtPrintSupport", "PySide6.QtPdf", "PySide6.QtWebEngineCore", "PySide6.QtQuick"})
        imported_names = {alias.name for node in nodes if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        self.assertFalse(imported_names & {"QFontDatabase", "QPrinter", "QPdfWriter", "QImage", "QImageReader"})
        calls = {node.func.attr for node in nodes if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(calls & {"addApplicationFont", "addApplicationFontFromData", "setHtml", "print", "print_"})
        for view in ("content", "bytes_view", "changes"):
            with self.subTest(view=view):
                self.assertTrue(any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setPlainText"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == view
                    for node in nodes
                ))


@unittest.skipUnless(STORAGE_AVAILABLE, "Synthetic compound-file integration requires Windows/pywin32")
class ApplicationFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = create_workspace(self.root)
        self.session = Workspace(self.folder)
        self.addCleanup(self.session.close)

    def proposal(self, locator=None, pointer="/text", value="<root>Edited</root>"):
        locator = locator or {"ole_path": ["Notes"]}
        record = self.session.get_record(locator)
        from dgn_explorer.workspace import get_pointer

        return {"schema": "dgn-explorer.patch-v1", "workspace_revision": self.session.revision, "operations": [{"record": locator, "pointer": pointer, "expected_value": get_pointer(record["value"], pointer), "value": value}]}


class WorkspaceTests(ApplicationFixture):
    def test_contextual_ids_and_pagination(self):
        records = self.session.list_records(kind="dgn-text-element")["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["element_id"], records[1]["element_id"])
        self.assertNotEqual(records[0]["record"], records[1]["record"])
        first = self.session.list_records(limit=1)
        second = self.session.list_records(cursor=first["next_cursor"], limit=1)
        self.assertNotEqual(first["records"], second["records"])
        self.assertEqual(len(self.session.list_records(text="Original text")["records"]), 1)
        for cursor, limit in ((-1, 1), (0, 0), (0, 1001), (True, 1)):
            with self.subTest(cursor=cursor, limit=limit), self.assertRaises(ValueError):
                self.session.list_records(cursor=cursor, limit=limit)

    def test_stage_is_readonly_and_validates_codec(self):
        before = {path: path.read_bytes() for path in self.folder.rglob("*") if path.is_file()}
        proposal = self.proposal()
        self.session.validate_patch(proposal)
        self.assertFalse(self.session.pending)
        self.session.stage_patch(proposal)
        self.assertTrue(self.session.pending)
        self.assertEqual(self.session.get_record({"ole_path": ["Notes"]})["value"]["text"], "<root>Edited</root>")
        self.assertEqual(before, {path: path.read_bytes() for path in self.folder.rglob("*") if path.is_file()})
        self.assertEqual(len(self.session.diff_workspace()["changes"]), 1)
        self.session.discard()
        self.assertFalse(self.session.diff_workspace()["dirty"])
        with self.assertRaises(Exception):
            self.session.validate_patch(self.proposal(value="invalid XML"))

    def test_text_encoding_and_immutable_properties(self):
        locator = self.session.list_records(kind="dgn-text-element")["records"][0]["record"]
        self.session.stage_patch(self.proposal(locator, "/string/text", "Changed"))
        self.assertEqual(self.session.get_record(locator)["value"]["string"]["text"], "Changed")
        for pointer in ("/element_id", "/original/text", "/is_3d"):
            proposal = self.proposal(locator, "/string/text", "Changed")
            proposal["operations"][0]["pointer"] = pointer
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                self.session.validate_patch(proposal)
        self.assertEqual(self.session.get_record({"ole_path": ["Opaque"]})["editable_fields"], [])

    def test_invalid_envelopes_types_and_duplicates(self):
        for mutation in ("unknown", "revision", "duplicate", "expected", "type", "locator", "nan"):
            proposal = self.proposal()
            operation = proposal["operations"][0]
            if mutation == "unknown":
                proposal["extra"] = True
            elif mutation == "revision":
                proposal["workspace_revision"] = "sha256:incorrect"
            elif mutation == "duplicate":
                proposal["operations"].append(operation.copy())
            elif mutation == "expected":
                operation["expected_value"] = "incorrect"
            elif mutation == "type":
                operation["value"] = 4
            elif mutation == "locator":
                operation["record"]["unknown"] = True
            else:
                operation["value"] = float("nan")
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, KeyError)):
                self.session.validate_patch(proposal)

    def test_mutable_labels_do_not_grant_authority(self):
        record = self.session.records[next(key for key, record in self.session.records.items() if record.value["kind"] == "dgn-text-element")]
        filename = record.bindings["/element_id"].file
        path = self.folder / filename
        document = json.loads(path.read_bytes())
        document["editing"] = {"editable_fields": ["/element_id"]}
        path.write_bytes(json.dumps(document).encode())
        with Workspace(self.folder) as reopened:
            self.assertNotIn("/element_id", reopened.get_record(record.locator)["editable_fields"])
        document["element_id"] += 1
        path.write_bytes(json.dumps(document).encode())
        with self.assertRaises((ValueError, KeyError)):
            Workspace(self.folder)

    def test_external_change_and_original_conflict(self):
        filename = next(iter(self.session.files))
        path = self.folder / filename
        before = path.read_bytes()
        path.write_bytes(before + b" ")
        with self.assertRaises(ConflictError):
            self.session.validate_patch(self.proposal())
        path.write_bytes(before)
        original = self.folder / "original.dgn"
        original.write_bytes(original.read_bytes() + b"changed")
        with self.assertRaises(ConflictError):
            self.session.check_revision()

    def test_limits_and_strict_json(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                parse_json(data)
        with self.assertRaises(ValueError):
            Limits(stream=0)
        with self.assertRaisesRegex(ValueError, "limit"):
            Workspace(self.folder, Limits(aggregate=1))
        with self.assertRaisesRegex(Exception, "cancelled"):
            Workspace(self.folder, cancel=lambda: True)

    def test_save_reopen_and_noop_pack(self):
        original = (self.folder / "original.dgn").read_bytes()
        noop = self.root / "noop.dgn"
        self.assertEqual(self.session.pack_workspace(noop)["changed_entries"], 0)
        self.assertEqual(noop.read_bytes(), original)
        self.session.stage_patch(self.proposal())
        self.assertEqual(self.session.save_workspace()["saved_files"], 1)
        self.assertFalse(self.session.pending)
        with Workspace(self.folder) as reopened:
            self.assertEqual(reopened.get_record({"ole_path": ["Notes"]})["value"]["text"], "<root>Edited</root>")
        self.assertEqual((self.folder / "original.dgn").read_bytes(), original)

    def test_save_as_staged_and_no_overwrite(self):
        self.session.stage_patch(self.proposal())
        before = {name: (self.folder / name).read_bytes() for name in self.session.files}
        output = self.root / "edited.dgn"
        self.assertEqual(self.session.pack_workspace(output)["changed_entries"], 1)
        with codecs.ole_reader().OleFileIO(str(output)) as ole:
            self.assertEqual(ole.openstream("Notes").read(), b"<root>Edited</root>")
        self.assertEqual(before, {name: (self.folder / name).read_bytes() for name in self.session.files})
        self.assertTrue(self.session.pending)
        for destination in (output, self.folder / "output.dgn"):
            with self.assertRaises(ValueError):
                self.session.pack_workspace(destination)

    def test_writer_lock(self):
        from dgn_explorer.transactions import ownership

        with ownership(self.folder):
            with self.assertRaises(ConflictError):
                self.session.save_workspace()
            with self.assertRaises(ConflictError):
                Workspace(self.folder)

    def test_interrupted_batch_recovery(self):
        class Interrupted(BaseException):
            pass

        for boundary in ("prepared", "published:0", "published:1", "committed"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                folder = create_workspace(Path(temporary))
                with Workspace(folder) as session:
                    locator = session.list_records(kind="dgn-text-element")["records"][0]["record"]
                    proposal = {"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision, "operations": [
                        {"record": {"ole_path": ["Notes"]}, "pointer": "/text", "expected_value": "<root>Original text</root>", "value": "<root>Edited</root>"},
                        {"record": locator, "pointer": "/string/text", "expected_value": "Text", "value": "Changed"},
                    ]}
                    session.stage_patch(proposal)

                    def fault(stage):
                        if stage == boundary:
                            raise Interrupted()

                    with self.assertRaises(Interrupted):
                        session.save_workspace(fault=fault)
                with Workspace(folder) as recovered:
                    expected = "<root>Edited</root>" if boundary == "committed" else "<root>Original text</root>"
                    self.assertEqual(recovered.get_record({"ole_path": ["Notes"]})["value"]["text"], expected)
                    expected_text = "Changed" if boundary == "committed" else "Text"
                    self.assertEqual(recovered.get_record(locator)["value"]["string"]["text"], expected_text)
                    self.assertFalse((folder / ".dgn-explorer" / "transaction.json").exists())

    def test_failed_save_rolls_back_and_keeps_user_notes(self):
        note = self.folder / "my-notes.txt"
        note.write_text("Keep this", encoding="utf-8")
        self.session.stage_patch(self.proposal())

        def fault(stage):
            if stage.startswith("published"):
                raise OSError("Injected disk failure")

        with self.assertRaises(OSError):
            self.session.save_workspace(fault=fault)
        with Workspace(self.folder) as recovered:
            self.assertEqual(recovered.diff_workspace()["changes"], [])
        self.assertEqual(note.read_text(), "Keep this")

    def test_sidecar_ignored_by_legacy_packer(self):
        from dgn_explorer.transactions import atomic_write

        atomic_write(self.folder / ".dgn-explorer" / "session.json", b"{}")
        output = self.root / "legacy-sidecar.dgn"
        self.assertEqual(codecs.rebuild(self.folder, output, self.session.limits.stream), 0)
        self.assertEqual(output.read_bytes(), (self.folder / "original.dgn").read_bytes())

    def test_legacy_v1_and_hex_views(self):
        legacy = self.root / "legacy"
        with patch.object(dgn_folder, "label_workspace_files"):
            codecs.extract(self.root / "input.dgn", legacy, 1024 * 1024, "hex")
        manifest = json.loads((legacy / "manifest.json").read_bytes())
        manifest["format"] = "dgn-folder-v1"
        codecs.write_view(legacy / "manifest.json", manifest)
        with Workspace(legacy) as session:
            self.assertEqual(len(session.list_records()["records"]), 5)
            self.assertEqual(session.pack_workspace(self.root / "legacy.dgn")["changed_entries"], 0)

    def test_noop_patch_does_not_write(self):
        proposal = self.proposal(value="<root>Original text</root>")
        self.assertEqual(self.session.validate_patch(proposal)["changes"], [])
        self.session.stage_patch(proposal)
        self.assertFalse(self.session.pending)
        self.assertEqual(self.session.save_workspace()["saved_files"], 0)

    def test_codec_cancellation(self):
        with self.assertRaises(InterruptedError):
            codecs.extract(self.root / "input.dgn", self.root / "cancelled", 1024 * 1024, cancel=lambda: True)
        with self.assertRaises(InterruptedError):
            codecs.rebuild(self.folder, self.root / "cancelled.dgn", 1024 * 1024, cancel=lambda: True)
        self.assertFalse((self.root / "cancelled.dgn").exists())

    def test_path_snapshot_and_framing_rejections(self):
        from dgn_explorer.workspace import confined

        for relative in ("../escape", "/escape", "C:/escape", "objects/../../escape", ".dgn-explorer/pending.json"):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                confined(self.folder, relative)
        locator = self.session.list_records(kind="dgn-text-element")["records"][0]["record"]
        record = self.session.records[json.dumps(locator, sort_keys=True, separators=(",", ":"))]
        path = self.folder / record.bindings["/element_id"].file
        document = json.loads(path.read_bytes())
        document["original"]["text"] = "Changed snapshot"
        path.write_text(json.dumps(document))
        with self.assertRaises(ValueError):
            Workspace(self.folder)


class CommandTests(ApplicationFixture):
    def invoke(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            code = cli.main([*arguments, "--json"])
        return code, json.loads(output.getvalue()), errors.getvalue()

    def test_discovery_commands_and_json(self):
        for command, extra in (("list", []), ("search", ["--text", "Original"]), ("validate", []), ("diff", []), ("show", ["--record", '{"ole_path":["Notes"]}'])):
            with self.subTest(command=command):
                code, result, errors = self.invoke([command, str(self.folder), *extra])
                self.assertEqual(code, 0)
                self.assertEqual(result["protocol"], "dgn-explorer.result-v1")
                self.assertTrue(result["success"])
                self.assertEqual(errors, "")
            code, result, _ = self.invoke(["search", str(self.folder), "--text=--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["result"]["records"], [])

    def test_dry_run_apply_and_pack(self):
        patch_file = self.root / "patch.json"
        patch_file.write_text(json.dumps(self.proposal()))
        for mode, applied in (("--dry-run", False), ("--approve", True)):
            code, result, _ = self.invoke(["apply", str(self.folder), "--patch", str(patch_file), mode])
            self.assertEqual(code, 0)
            self.assertEqual(result["result"]["applied"], applied)
            with Workspace(self.folder) as reopened:
                self.assertEqual(bool(reopened.diff_workspace()["changes"]), applied)
        code, result, _ = self.invoke(["pack", str(self.folder), str(self.root / "cli.dgn")])
        self.assertEqual(code, 0)
        self.assertTrue(result["result"]["verified"])

    def test_errors_and_explicit_approval(self):
        code, result, _ = self.invoke(["show", str(self.folder), "--record", "invalid JSON"])
        self.assertEqual(code, 3)
        self.assertFalse(result["success"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            cli.main(["apply", str(self.folder), "--patch", "missing.json"])
        self.assertEqual(result.exception.code, 2)
        self.assertEqual(cli.error_details(ConflictError())[0], 4)
        self.assertEqual(cli.error_details(OSError())[0], 5)

    def test_worker_subprocess(self):
        from dgn_explorer.worker import PROTOCOL

        request = {"protocol": PROTOCOL, "request_id": "test", "operation": "show", "arguments": {"folder": str(self.folder), "record": {"ole_path": ["Notes"]}}}
        completed = subprocess.run([sys.executable, "-m", "dgn_explorer", "--worker"], input=json.dumps(request) + "\n", capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        messages = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([message["event"] for message in messages], ["progress", "completed"])
        self.assertEqual(messages[-1]["payload"]["value"]["text"], "<root>Original text</root>")

    def test_worker_exits_with_input_pipe_open(self):
        from dgn_explorer.worker import PROTOCOL

        request = {"protocol": PROTOCOL, "request_id": "open-pipe", "operation": "list", "arguments": {"folder": str(self.folder)}}
        process = subprocess.Popen([sys.executable, "-m", "dgn_explorer", "--worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert process.stdin is not None
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            process.wait(timeout=30)
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertEqual(json.loads(output.splitlines()[-1])["event"], "completed")
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def test_worker_validation_cancellation_and_limits(self):
        from dgn_explorer.worker import PROTOCOL, MESSAGE_LIMIT, run

        request = {"protocol": PROTOCOL, "request_id": "test", "operation": "open", "arguments": {"folder": str(self.folder)}}
        messages = []
        self.assertEqual(run(request, messages.append, cancel=lambda: True), 6)
        self.assertEqual(messages[-1]["event"], "failed")
        for mutation in ("extra", "protocol", "unknown_argument", "unknown_operation"):
            invalid = json.loads(json.dumps(request))
            if mutation == "extra":
                invalid["unknown"] = True
            elif mutation == "protocol":
                invalid["protocol"] = "unknown"
            elif mutation == "unknown_argument":
                invalid["arguments"]["unknown"] = True
            else:
                invalid["operation"] = "unknown"
            with self.subTest(mutation=mutation):
                self.assertEqual(run(invalid, messages.append), 3)
        oversized = subprocess.run([sys.executable, "-m", "dgn_explorer", "--worker"], input=b"x" * (MESSAGE_LIMIT + 2), capture_output=True, timeout=30)
        self.assertEqual(oversized.returncode, 3)

    def test_desktop_summary_and_recovery_journal(self):
        from dgn_explorer.operations import execute

        parameters = {"folder": str(self.folder), "record": {"ole_path": ["Notes"]}, "summary": True}
        result = execute("show", parameters)
        editable = next(field for field in result["fields"] if field["pointer"] == "/text")
        self.assertTrue(editable["editable"])
        self.assertEqual(editable["saved_value"], "<root>Original text</root>")
        self.assertNotIn("original", result)
        self.assertLess(len(result["bytes"]["hex"]), 4096 * 3)
        proposal = self.proposal()
        execute("journal", {"folder": str(self.folder), "patch": proposal})
        self.assertEqual(execute("open", {"folder": str(self.folder)})["recovery_patch"], proposal)
        execute("journal", {"folder": str(self.folder), "patch": None})
        self.assertIsNone(execute("open", {"folder": str(self.folder)})["recovery_patch"])

    def test_import_existing_destination_and_aggregate(self):
        from dgn_explorer.operations import import_dgn

        output = self.root / "imported"
        self.assertEqual(import_dgn(self.root / "input.dgn", output, Limits())["streams"], 5)
        with self.assertRaises(ValueError):
            import_dgn(self.root / "input.dgn", output, Limits())
        with self.assertRaises(ValueError):
            import_dgn(self.root / "input.dgn", self.root / "too-large", Limits(aggregate=1))
        self.assertFalse((self.root / "too-large").exists())


if __name__ == "__main__":
    unittest.main()