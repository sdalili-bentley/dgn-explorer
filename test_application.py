"""Reusable application tests; optional real DGN checks live in test_dgn_folder."""

import ast
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlparse

import dgn_folder
from dgn_explorer import cli, codecs
from dgn_explorer.workspace import CancelledError, ConflictError, Limits, Workspace, parse_json
from test_support import STORAGE_AVAILABLE, create_workspace, shared_workspace, editor_test_root


class PackageTests(unittest.TestCase):
    def test_strict_json_rejects_numeric_overflow_and_nonfinite_constants(self):
        for number in ("NaN", "Infinity", "-Infinity", "1e309", "-1e9999"):
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, "Non-finite"):
                parse_json(('{"number":' + number + "}").encode())
        for number in ("0", "-0.0", "1e308", "-1.7976931348623157e308", "1e-9999"):
            with self.subTest(number=number):
                self.assertEqual(parse_json(('{"number":' + number + "}").encode())["number"], json.loads(number))

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
        for view in ("editor", "bytes_view", "changes"):
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
    def test_many_record_bindings_preserve_context_and_roundtrip(self):
        for count in (0, 1, 3, 24):
            with self.subTest(text_count=count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                folder = create_workspace(root, text_count=count)
                original = (root / "input.dgn").read_bytes()
                with Workspace(folder) as session:
                    records = session.list_records(kind="dgn-text-element", limit=100)["records"]
                    self.assertEqual(len(records), count * 2)
                    output = root / "unchanged.dgn"
                    self.assertEqual(session.pack_workspace(output)["changed_entries"], 0)
                    self.assertEqual(output.read_bytes(), original)
                    if not count:
                        continue
                    target = {"ole_path": ["Dgn-Md", "#000001", "Dgn^G", "$1"], "chunk_index": count - 1}
                    session.stage_patch({"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision, "operations": [
                        {"record": target, "pointer": "/string/text", "expected_value": "Text", "value": "Changed"},
                    ]})
                    edited = root / "edited.dgn"
                    self.assertEqual(session.pack_workspace(edited)["changed_entries"], 1)
                reimported = root / "reimported"
                codecs.extract(edited, reimported, 1024 * 1024)
                with Workspace(reimported) as session:
                    records = session.list_records(kind="dgn-text-element", limit=100)["records"]
                    self.assertEqual(len(records), count * 2)
                    for record in records:
                        value = session.get_record(record["record"])["value"]
                        expected = "Changed" if record["record"] == target else "Text"
                        self.assertEqual(value["string"]["text"], expected)
                        self.assertEqual(value["element_id"], 123 + record["record"]["chunk_index"])
                self.assertEqual((root / "input.dgn").read_bytes(), original)

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
        codecs.extract(self.root / "input.dgn", legacy, 1024 * 1024, "hex", labels=False)
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


def replacement(session, locator, pointer, value):
    from dgn_explorer.workspace import get_pointer

    current = session.get_record(locator)["value"]
    return {"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision, "operations": [
        {"record": locator, "pointer": pointer, "expected_value": get_pointer(current, pointer), "value": value},
    ]}


def run_child(source: str, *arguments, **options):
    return subprocess.run([sys.executable, "-c", source, *map(str, arguments)], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=120, **options)


def leftovers(root: Path, *prefixes: str) -> list[Path]:
    return [path for path in root.rglob("*") if path.name.startswith(prefixes)]


TITLE = {"ole_path": ["\x05SummaryInformation"], "section_index": 0, "property_id": "2"}
PAGES = {"ole_path": ["\x05SummaryInformation"], "section_index": 0, "property_id": "14"}
CODEPAGE = {"ole_path": ["\x05SummaryInformation"], "section_index": 0, "property_id": "1"}
XML_ATTRIBUTE = {"ole_path": ["Dgn-Md", "#000001", "Dgn^A", "$1"], "set_index": 0, "element_id": "123", "handler_id": "305419896", "attribute_id": "1"}
OPAQUE_ATTRIBUTE = {**XML_ATTRIBUTE, "attribute_id": "2"}


@unittest.skipUnless(STORAGE_AVAILABLE, "Synthetic compound-file integration requires Windows/pywin32")
class RecordFamilyTests(unittest.TestCase):
    """OLE property and XAttribute records through the shared service."""

    def test_nonfinite_original_property_opens_readonly_and_preserves_bytes(self):
        import struct
        from test_support import property_stream

        payload = struct.pack("<Id", 5, float("nan"))
        raw = property_stream()[:48] + struct.pack("<4I", 16 + len(payload), 1, 2, 16) + payload
        root = self.root / "nonfinite"
        root.mkdir()
        with patch("test_support.property_stream", return_value=raw):
            folder = create_workspace(root, rich=True)
        original = (folder / "original.dgn").read_bytes()
        with Workspace(folder) as session:
            self.assertEqual(session.get_record(TITLE)["editable_fields"], [])
            session.pack_workspace(root / "noop.dgn")
            session.stage_patch(replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Edited</root>"))
            session.pack_workspace(root / "edited.dgn")
        self.assertEqual((root / "noop.dgn").read_bytes(), original)
        reimported = root / "reimported"
        codecs.extract(root / "edited.dgn", reimported, 1024 * 1024)
        with Workspace(reimported) as session:
            self.assertEqual(session.get_record(TITLE)["editable_fields"], [])
            self.assertEqual(codecs.view_bytes(session.get_record(TITLE)["value"]), payload)
        self.assertEqual((folder / "original.dgn").read_bytes(), original)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = create_workspace(self.root, rich=True)

    def test_capabilities_are_derived_from_trusted_original(self):
        with Workspace(self.folder) as session:
            for locator, editable in ((TITLE, ["/value"]), (PAGES, ["/value"]), (CODEPAGE, []), (XML_ATTRIBUTE, ["/payload/text"]), (OPAQUE_ATTRIBUTE, [])):
                with self.subTest(locator=locator):
                    record = session.get_record(locator)
                    self.assertEqual(record["editable_fields"], editable)
                    self.assertEqual(record["access"], "rw" if editable else "ro")
            for locator, pointer in ((CODEPAGE, "/value"), (OPAQUE_ATTRIBUTE, "/payload/text"), (XML_ATTRIBUTE, "/identity/element_id"), (TITLE, "/codepage")):
                with self.subTest(readonly=pointer), self.assertRaisesRegex(ValueError, "read-only"):
                    proposal = replacement(session, XML_ATTRIBUTE, "/payload/text", "<attr>x</attr>")
                    proposal["operations"][0].update(record=locator, pointer=pointer)
                    session.validate_patch(proposal)

    def test_property_and_attribute_edits_roundtrip(self):
        original = (self.root / "input.dgn").read_bytes()
        output = self.root / "edited.dgn"
        with Workspace(self.folder) as session:
            for locator, pointer, value in ((TITLE, "/value", "Edited title"), (PAGES, "/value", 42), (XML_ATTRIBUTE, "/payload/text", "<attr kind=\"edited\">Changed &amp; kept</attr>")):
                session.stage_patch(replacement(session, locator, pointer, value))
            self.assertEqual(len(session.diff_workspace()["changes"]), 3)
            self.assertEqual(session.pack_workspace(output)["changed_entries"], 2)
        reimported = self.root / "reimported"
        codecs.extract(output, reimported, 1024 * 1024)
        with Workspace(reimported) as session:
            self.assertEqual(session.get_record(TITLE)["value"]["value"], "Edited title")
            self.assertEqual(session.get_record(PAGES)["value"]["value"], 42)
            self.assertEqual(session.get_record(XML_ATTRIBUTE)["value"]["payload"]["text"], "<attr kind=\"edited\">Changed &amp; kept</attr>")
            self.assertEqual(session.get_record(CODEPAGE)["value"]["value"], 1252)
            self.assertEqual(session.get_record(OPAQUE_ATTRIBUTE)["value"]["payload"], Workspace(self.folder).get_record(OPAQUE_ATTRIBUTE)["value"]["payload"])
            second = {**XML_ATTRIBUTE, "ole_path": ["Dgn-Md", "#000002", "Dgn^A", "$1"]}
            self.assertEqual(session.get_record(second)["value"]["payload"]["text"], "<attr>Value</attr>")
        self.assertEqual((self.root / "input.dgn").read_bytes(), original)

    def test_changed_contextual_identities_are_invalid_input_not_internal_errors(self):
        targets = []
        for path in (self.folder / "data").rglob("*.json"):
            value = json.loads(path.read_bytes())
            if value["kind"] == "ole-properties":
                targets.append((path, value, "property"))
            elif value["kind"] == "dgn-attribute-sets":
                targets.append((path, value, "attribute"))
        self.assertEqual(len(targets), 3)
        for path, original, family in targets:
            for mutation in ("replace", "remove"):
                with self.subTest(family=family, mutation=mutation):
                    value = deepcopy(original)
                    records = value["sections"][0]["properties"] if family == "property" else value["sets"][0]["attributes"]
                    if mutation == "remove":
                        records.pop()
                    else:
                        records[0]["id" if family == "property" else "attribute_id"] += 100
                    before = path.read_bytes()
                    try:
                        path.write_text(json.dumps(value), encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, "Record identities change"):
                            Workspace(self.folder)
                        with contextlib.redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(cli.main(["--json", "validate", str(self.folder)]), 3)
                        self.assertEqual(json.loads(output.getvalue())["errors"][0]["code"], 3)
                    finally:
                        path.write_bytes(before)

    def test_memory_labeling_matches_disk_relabeling(self):
        source = self.root / "input.dgn"
        legacy = self.root / "legacy"
        manifest = codecs.extract(source, legacy, 1024 * 1024, labels=False)
        self.assertTrue((legacy / "manifest.json").exists())
        dgn_folder.label_workspace_files(legacy, manifest)

        def contents(folder):
            result = {}
            for path in folder.rglob("*"):
                if path.is_file() and ".dgn-explorer" not in path.parts:
                    data = path.read_bytes()
                    result[path.relative_to(folder).as_posix()] = json.loads(data) if path.suffix == ".json" else data.replace(b"\r\n", b"\n")
            return result

        self.assertEqual(contents(self.folder), contents(legacy))
        self.assertEqual({path.relative_to(self.folder) for path in self.folder.rglob("*") if path.is_dir() and ".dgn-explorer" not in path.parts},
                         {path.relative_to(legacy) for path in legacy.rglob("*") if path.is_dir()})
        with self.assertRaisesRegex(ValueError, "Access-marker destination"):
            dgn_folder.label_files({"content/a.txt": b"new", "content/a.rw.txt": b"old"}, {"streams": []})
        with self.assertRaises(InterruptedError):
            codecs.extract(source, self.root / "cancelled", 1024 * 1024, cancel=lambda: True)

    def test_unencodable_replacements_are_invalid_input(self):
        cases = (
            (PAGES, "/value", 2 ** 40, "out of range"),
            (PAGES, "/value", -2 ** 31 - 1, "out of range"),
            (TITLE, "/value", "\u03a9 not cp1252", "codec"),
            (XML_ATTRIBUTE, "/payload/text", "<attr>unclosed", "not well-formed"),
            (TITLE, "/value", 7, "type/shape"),
            (PAGES, "/value", 1.5, "type/shape"),
            (PAGES, "/value", True, "type/shape"),
        )
        with Workspace(self.folder) as session:
            before = {name: data for name, data in session.files.items()}
            for locator, pointer, value, message in cases:
                proposal = replacement(session, locator, pointer, value)
                with self.subTest(value=value):
                    with self.assertRaisesRegex(ValueError, message):
                        session.stage_patch(proposal)
                    self.assertFalse(session.pending)
                    self.assertEqual(session.staged, {})
                    patch_file = self.root / "patch.json"
                    patch_file.write_text(json.dumps(proposal))
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        code = cli.main(["--json", "apply", str(self.folder), "--patch", str(patch_file), "--dry-run"])
                    self.assertEqual(code, 3, output.getvalue())
                    self.assertEqual(json.loads(output.getvalue())["errors"][0]["code"], 3)
            self.assertEqual(before, {name: (self.folder / name).read_bytes() for name in before})


@unittest.skipUnless(STORAGE_AVAILABLE, "Synthetic compound-file integration requires Windows/pywin32")
class SpecificationWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = editor_test_root(self)
        self.folder = create_workspace(self.root, features=True)
        self.session = Workspace(self.folder)
        self.addCleanup(self.session.close)

    def record(self, predicate, model="#000001"):
        return next(record for record in self.session.records.values()
                    if model in record.locator["ole_path"] and predicate(record.value))

    def test_new_features_inventory_search_and_contextual_identity(self):
        from dgn_explorer.workspace import ElementLocator
        records = self.session.list_records(limit=1000)["records"]
        features = {record["feature"] for record in records}
        self.assertTrue({"Fonts", "Levels", "ColorBooks", "Shared cell definition", "Mesh",
                         "Geographic coordinate system", "ExtendedColors", "SolarLightMap",
                         "Background Map JSON", "dgn-ecxd", "dgn-ecx-instance"} <= features)
        for query in ("Synthetic Font", "WGS84", "DataGroup", "café", "Feature description"):
            with self.subTest(query=query):
                results = self.session.list_records(text=query, limit=1000)["records"]
                self.assertGreaterEqual(len(results), 2)
        self.assertEqual(len(self.session.list_records(kind="dgn-tag", limit=1000)["records"]), 8)
        first = self.record(lambda value: value.get("element_id") == 2000)
        locator = ElementLocator.from_record(first)
        self.assertEqual(locator.element_id, 2000)
        self.assertEqual(locator.model, ("Dgn-Md", "#000001"))
        other = self.record(lambda value: value.get("element_id") == 2000, "#000002")
        self.assertNotEqual(locator, ElementLocator.from_record(other))
        applications = self.session.get_record(first.locator)["registered_applications"]
        self.assertEqual(applications, [{"application_id": "4660", "name": "BBES", "electrical": True}])
        inventory = codecs.inspect_dgn(self.root / "input.dgn", 1024 * 1024)
        self.assertEqual(inventory["model_count"], 2)
        self.assertIn("Fonts", {table["name"] for table in inventory["metadata_tables"]})
        self.assertIn(22244, {link["primary_id"] for link in inventory["linkage_ids"]})
        self.assertTrue(all("major" in handler and "minor" in handler for handler in inventory["attribute_handlers"]))

    def test_no_edit_roundtrip_all_feature_streams_and_v1_hex(self):
        original = (self.root / "input.dgn").read_bytes()
        output = self.root / "unchanged.dgn"
        self.assertEqual(self.session.pack_workspace(output)["changed_entries"], 0)
        self.assertEqual(output.read_bytes(), original)
        for mode in ("hex", "escaped"):
            folder = self.root / mode
            codecs.extract(self.root / "input.dgn", folder, 1024 * 1024, bytes_mode=mode)
            path = folder / "manifest.rw.json"
            manifest = parse_json(path.read_bytes())
            manifest["format"] = "dgn-folder-v1"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with Workspace(folder) as session:
                output = self.root / f"{mode}.dgn"
                self.assertEqual(session.pack_workspace(output)["changed_entries"], 0)
                self.assertEqual(output.read_bytes(), original)

    def test_previous_opaque_views_remain_readable_without_granting_new_edits(self):
        files = {name: data for name, data in self.session.files.items()}

        def downgrade(node):
            if isinstance(node, list):
                return [downgrade(child) for child in node]
            if not isinstance(node, dict):
                return node
            kind = node.get("kind")
            new_kinds = {"dgn-tag", "dgn-table-header", "dgn-table-entry", "dgn-matrix", "dgn-store",
                         "dgn-native-core", "dgn-gcs", "dgn-xml-fragment", "dgn-becxml", "dgn-ecxd",
                         "dgn-ecx-instance", "dgn-model-index", "dgn-design-header", "dgn-dependency",
                         "dgn-bitmask", "dgn-multistate-mask", "dgn-symbology", "dgn-xml-linkage", "dgn-xdata", "dgn-tflabel"}
            if kind in new_kinds:
                return codecs.readable_bytes({"kind": "opaque-bytes", "hex_rows": [codecs.view_bytes(node).hex()]})
            if kind == "dgn-manifest":
                raw = codecs.view_bytes(node)
                return codecs.text_view(raw)
            if kind == "dgn-model-header":
                raw = codecs.view_bytes(node)
                return {"kind": kind, "num_pointer_blocks": node["num_pointer_blocks"],
                        "major_version": node["major_version"], "minor_version": node["minor_version"],
                        "remaining": codecs.readable_bytes({"kind": "opaque-bytes", "hex_rows": [raw[12:].hex()]})}
            result = {key: downgrade(child) for key, child in node.items()
                      if key not in ("editing", "text_file", "primary_name", "format_name", "schema_name", "store_assembly")}
            if kind == "dgn-element":
                result["type_name"] = codecs.ELEMENT_TYPES.get(result["element_type"], "Unknown")
            return result

        for name, data in files.items():
            if name.endswith(".json") and name.split("/")[0] in ("data", "objects", "attributes", "fields"):
                view = parse_json(data)
                codecs.hydrate_text(codecs.MemoryStore(files), view, 1024 * 1024)
                (self.folder / name).write_text(json.dumps(downgrade(view)), encoding="utf-8")
        with Workspace(self.folder) as session:
            font = next(record for record in session.records.values() if record.value.get("element_type") == 95 and record.value.get("level_id") == 2)
            self.assertNotIn("/core/name", font.editable)
            app = next(record for record in session.records.values() if record.value.get("element_type") == 95 and record.value.get("level_id") == 10)
            self.assertEqual(app.editable, ())
            output = self.root / "legacy-unchanged.dgn"
            self.assertEqual(session.pack_workspace(output)["changed_entries"], 0)
            self.assertEqual(output.read_bytes(), (self.root / "input.dgn").read_bytes())
            session.stage_patch(replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Legacy edit</root>"))
            self.assertEqual(session.pack_workspace(self.root / "legacy-edited.dgn")["changed_entries"], 1)

    def test_previous_uncompressed_file_header_framing_remains_lossless(self):
        root = self.root / "uncompressed"
        root.mkdir()
        folder = create_workspace(root, features=True, uncompressed_header=True)
        path = folder / "manifest.rw.json"
        manifest = parse_json(path.read_bytes())
        entry = next(entry for entry in manifest["streams"] if entry["ole_path"] == ["Dgn~H"])
        prefix = codecs.view_bytes(parse_json((folder / entry["prefix"]).read_bytes()))
        payload = codecs.view_bytes(parse_json((folder / entry["file"]).read_bytes()))
        (folder / entry["file"]).write_text(json.dumps(codecs.readable_bytes({"kind": "opaque-bytes", "hex_rows": [(prefix + payload).hex()]})))
        entry["codec"] = "raw"
        entry["payload_sha256"] = entry["raw_sha256"]
        for field in ("prefix", "suffix"):
            for key in (field, field + "_sha256", field + "_representation"):
                entry.pop(key, None)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with Workspace(folder) as session:
            self.assertEqual(session.get_record({"ole_path": ["Dgn~H"]})["editable_fields"], [])
            output = root / "unchanged.dgn"
            self.assertEqual(session.pack_workspace(output)["changed_entries"], 0)
            self.assertEqual(output.read_bytes(), (root / "input.dgn").read_bytes())

    def test_current_uncompressed_design_header_noop_and_edited_pack(self):
        root = self.root / "current-uncompressed"
        root.mkdir()
        folder = create_workspace(root, features=True, uncompressed_header=True)
        original = (folder / "original.dgn").read_bytes()
        with Workspace(folder) as session:
            header = session.get_record({"ole_path": ["Dgn~H"]})["value"]
            self.assertEqual(header["kind"], "dgn-design-header")
            session.pack_workspace(root / "noop.dgn")
            session.stage_patch(replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Edited</root>"))
            session.pack_workspace(root / "edited.dgn")
        self.assertEqual((root / "noop.dgn").read_bytes(), original)
        imported = root / "reimported"
        codecs.extract(root / "edited.dgn", imported, 1024 * 1024)
        with Workspace(imported) as session:
            self.assertEqual(session.get_record({"ole_path": ["Dgn~H"]})["value"], header)
            self.assertEqual(session.get_record({"ole_path": ["Notes"]})["value"]["text"], "<root>Edited</root>")
        self.assertEqual((folder / "original.dgn").read_bytes(), original)

    def test_typed_feature_replacements_save_pack_and_reimport(self):
        font = self.record(lambda value: value.get("core", {}).get("table_level") == 2 and "name" in value["core"])
        tag = self.record(lambda value: value.get("core", {}).get("kind") == "dgn-tag" and isinstance(value["core"].get("value"), str))
        number = self.record(lambda value: value.get("core", {}).get("kind") == "dgn-tag" and value["core"].get("data_type") == 2)
        shape = self.record(lambda value: value.get("element_type") == 6)
        links = self.record(lambda value: value.get("element_id") == 2000)
        attribute = self.record(lambda value: value.get("identity", {}).get("handler_id") == 22281 << 16)
        changes = [
            (font.locator, "/core/name", "Edited Font Ω 😀"),
            (tag.locator, "/core/value", "A longer tag"),
            (number.locator, "/core/value", -42),
            (shape.locator, "/core/points", [[0., 0.], [2., 0.], [1., 1.], [0., 0.]]),
            (links.locator, "/linkages/records/0/payload/string/text", "Edited description"),
            (links.locator, "/linkages/records/8/payload/records/2/value", 460),
            (links.locator, "/linkages/records/4/payload/weight", 3),
            (links.locator, "/linkages/records/6/payload/payload/payload/text", "<DataGroup><Value>Edited Ω</Value></DataGroup>"),
            (attribute.locator, "/payload/payload/text", '<ExtendedColors><Entry Color="2"/></ExtendedColors>'),
        ]
        operations = [replacement(self.session, locator, pointer, value)["operations"][0] for locator, pointer, value in changes]
        original = (self.root / "input.dgn").read_bytes()
        self.session.stage_patch({"schema": "dgn-explorer.patch-v1", "workspace_revision": self.session.revision, "operations": operations})
        self.assertEqual(len(self.session.diff_workspace()["changes"]), len(changes))
        self.session.save_workspace()
        output = self.root / "edited.dgn"
        self.assertEqual(self.session.pack_workspace(output)["changed_entries"], 2)
        self.assertEqual((self.root / "input.dgn").read_bytes(), original)
        self.assertEqual((self.folder / "original.dgn").read_bytes(), original)
        reimported = self.root / "reimported"
        codecs.extract(output, reimported, 1024 * 1024)
        from dgn_explorer.workspace import get_pointer
        with Workspace(reimported) as session:
            self.assertTrue(session.validate_workspace()["valid"])
            for locator, pointer, value in changes:
                with self.subTest(pointer=pointer):
                    self.assertEqual(get_pointer(session.get_record(locator)["value"], pointer), value)
            other = {**font.locator, "ole_path": ["Dgn-Md", "#000002", "Dgn^G", "$2"]}
            self.assertEqual(session.get_record(other)["value"]["core"]["name"], "Synthetic Font")
            second_output = self.root / "edited-noop.dgn"
            self.assertEqual(session.pack_workspace(second_output)["changed_entries"], 0)
            self.assertEqual(second_output.read_bytes(), output.read_bytes())

    def test_passive_features_and_unsafe_replacements_reject_without_staging(self):
        for kind in ("dgn-matrix", "dgn-store", "dgn-gcs", "dgn-native-core"):
            record = self.record(lambda value: value.get("core", {}).get("kind") == kind)
            self.assertFalse(any(pointer.startswith("/core/") for pointer in record.editable))
            self.assertNotIn("/element_type", record.editable)
        for major in (0xECDA, 22271, 0xEC34):
            record = self.record(lambda value: value.get("identity", {}).get("handler_id", 0) >> 16 == major)
            self.assertEqual(record.editable, ())
        app = self.record(lambda value: value.get("core", {}).get("table_level") == 10)
        self.assertEqual(app.editable, ())
        for record in self.session.records.values():
            if record.value.get("element_type") in (95, 96):
                self.assertNotIn("/level_id", record.editable)
        links = self.record(lambda value: value.get("element_id") == 2000)
        number = self.record(lambda value: value.get("core", {}).get("kind") == "dgn-tag" and value["core"].get("data_type") == 2)
        invalid = [(number.locator, "/core/value", 2 ** 20),
                   (links.locator, "/linkages/records/1/payload/string/text", "{invalid"),
                   (links.locator, "/linkages/records/8/payload/records/0/value", 999),
                   (links.locator, "/linkages/records/6/payload/payload/payload/text", "<DataGroup><Value>unclosed")]
        before = dict(self.session.files)
        for locator, pointer, value in invalid:
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                self.session.stage_patch(replacement(self.session, locator, pointer, value))
            self.assertFalse(self.session.pending)
        self.assertEqual(self.session.files, before)

    def test_new_feature_cli_list_show_search_apply_diff_validate_pack(self):
        def invoke(*arguments):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = cli.main(["--json", *map(str, arguments)])
            self.assertEqual(code, 0, output.getvalue())
            return json.loads(output.getvalue())["result"]

        listed = invoke("list", self.folder, "--limit", "1000")["records"]
        self.assertIn("Fonts", {record["feature"] for record in listed})
        self.assertEqual(len(invoke("list", self.folder, "--kind", "dgn-tag", "--limit", "1000")["records"]), 8)
        font = self.record(lambda value: value.get("core", {}).get("table_level") == 2 and "name" in value["core"])
        shown = invoke("show", self.folder, "--record", json.dumps(font.locator))
        self.assertEqual(shown["feature"], "Fonts")
        self.assertIn("/core/name", shown["editable_fields"])
        self.assertGreaterEqual(len(invoke("search", self.folder, "--text", "Synthetic Font")["records"]), 2)
        proposal = replacement(self.session, font.locator, "/core/name", "CLI Font")
        path = self.root / "patch.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        self.assertTrue(invoke("apply", self.folder, "--patch", path, "--dry-run")["changes"])
        invoke("apply", self.folder, "--patch", path, "--approve")
        self.assertTrue(invoke("diff", self.folder)["changes"])
        self.assertTrue(invoke("validate", self.folder)["valid"])
        output = self.root / "cli-edited.dgn"
        self.assertEqual(invoke("pack", self.folder, output)["changed_entries"], 1)


@unittest.skipUnless(STORAGE_AVAILABLE, "Synthetic compound-file integration requires Windows/pywin32")
class ScaleTests(unittest.TestCase):
    """Large synthetic workspaces: memory baseline, incremental validation and paging."""

    COUNT = 400

    @classmethod
    def setUpClass(cls):
        cls.folder = shared_workspace(text_count=cls.COUNT)

    def test_baseline_is_extracted_in_memory_without_disk_writes(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("open must not extract the baseline to disk")

        with patch.object(codecs, "extract", side_effect=forbidden), patch.object(dgn_folder, "extract", side_effect=forbidden), \
                patch.object(tempfile, "mkdtemp", side_effect=forbidden), Workspace(self.folder) as session:
            self.assertEqual(len(session.records), self.COUNT * 2 + 3)

    def test_memory_baseline_matches_disk_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            disk = Path(temporary) / "disk"
            manifest = codecs.extract(self.folder / "original.dgn", disk, 1024 * 1024, labels=False)
            memory_manifest, files = codecs.extract_memory(self.folder / "original.dgn", 1024 * 1024)
            self.assertEqual(memory_manifest, json.loads(json.dumps(manifest)))
            on_disk = {path.relative_to(disk).as_posix() for path in disk.rglob("*") if path.is_file()} - {"original.dgn", "manifest.json"}
            self.assertEqual(set(files), on_disk)
            for name, data in files.items():
                expected = (disk / name).read_bytes()
                self.assertEqual(json.loads(data) if name.endswith(".json") else data, json.loads(expected) if name.endswith(".json") else expected, name)
        with self.assertRaisesRegex(ValueError, "Aggregate"):
            codecs.extract_memory(self.folder / "original.dgn", 1024 * 1024, aggregate=1)
        with self.assertRaises(InterruptedError):
            codecs.extract_memory(self.folder / "original.dgn", 1024 * 1024, cancel=lambda: True)

    def test_staging_encodes_only_changed_streams(self):
        from dgn_explorer import workspace as service

        with Workspace(self.folder) as session:
            locator = {"ole_path": ["Dgn-Md", "#000002", "Dgn^G", "$1"], "chunk_index": self.COUNT - 1}
            with patch.object(service.codecs, "view_bytes", side_effect=codecs.view_bytes) as encoder:
                session.stage_patch(replacement(session, locator, "/string/text", "Last"))
                session.stage_patch(replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Edited</root>"))
                report = session.validate_workspace()
            # One record dry-run plus one owning-stream encode per staging; unchanged streams use cached sizes.
            self.assertLessEqual(encoder.call_count, 7)
            self.assertEqual(report["records"], self.COUNT * 2 + 3)
            self.assertEqual(session.get_record(locator)["value"]["string"]["text"], "Last")
            self.assertEqual(len(session.diff_workspace()["changes"]), 2)

    def test_pagination_is_complete_stable_and_bounded(self):
        with Workspace(self.folder) as session:
            expected = self.COUNT * 2 + 3
            seen, cursor, pages = [], 0, 0
            while cursor is not None:
                page = session.list_records(cursor=cursor, limit=97)
                self.assertLessEqual(len(page["records"]), 97)
                seen.extend(json.dumps(item["record"], sort_keys=True) for item in page["records"])
                cursor, pages = page["next_cursor"], pages + 1
            self.assertEqual(len(seen), expected)
            self.assertEqual(len(set(seen)), expected)
            self.assertEqual(pages, -(-expected // 97))
            model = session.list_records(model="#000002", kind="dgn-text-element", limit=1000)
            self.assertEqual(len(model["records"]), self.COUNT)
            self.assertIsNone(model["next_cursor"])
            self.assertEqual(session.list_records(cursor=expected + 10)["records"], [])
            self.assertEqual(len(session.list_records(limit=1000)["records"]), expected)

    def test_open_stays_within_generous_budget(self):
        started = time.perf_counter()
        with Workspace(self.folder):
            pass
        # Regression guard for the former quadratic open; measured values are recorded in TESTING.md.
        self.assertLess(time.perf_counter() - started, 60)

    def test_benchmark_script_reports_operations_and_never_overwrites(self):
        import benchmark_workspace

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(benchmark_workspace.main(["--text-count", "1", "--output", str(output)]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report, json.loads(printed.getvalue()))
            self.assertEqual(report["records"], 5)
            self.assertEqual(set(report["operations"]), {"open", "search_absent", "validate", "stage_and_validate", "pack_staged", "import"})
            for name, measured in report["operations"].items():
                self.assertGreater(measured["checkpoints"], 0, name)
                self.assertLessEqual(measured["max_checkpoint_gap_seconds"], measured["seconds"], name)
            self.assertIn("peak_python_mib", report["operations"]["open"])
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                benchmark_workspace.main(["--text-count", "0", "--output", str(output)])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            with patch.object(benchmark_workspace, "benchmark", return_value={"operations": {}}), \
                    patch.object(Path, "exists", return_value=False), contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(FileExistsError):
                # An output created after the early check is still never overwritten.
                benchmark_workspace.main(["--text-count", "0", "--output", str(output)])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                benchmark_workspace.main(["--text-count", "-1"])


class SearchTests(unittest.TestCase):
    def test_literal_search_semantics(self):
        from dgn_explorer.workspace import searchable

        node = {"kind": "xml", "text": "Quote \"x\" back\\slash \u03a9mega", "number": 42, "flag": True, "original": {"text": "snapshot only"}, "original_identity": {"id": 999}, "items": [{"deep": "Nested"}]}
        for needle, found in (("\"x\"", True), ("back\\slash", True), ("\u03c9mega", True), ("42", True), ("nested", True), ("snapshot", False), ("999", False), ("true", False), ("\"text\":", False), ("{", False)):
            with self.subTest(needle=needle):
                self.assertEqual(searchable(node, needle.casefold()), found)


class SearchWorkspaceTests(ApplicationFixture):
    def setUp(self):
        super().setUp()
        self.special = self.root / "special"
        self.special.mkdir()
        self.special_folder = create_workspace(self.special, notes_text="Quote &quot;x&quot; back\\slash \u03a9mega 4242")

    def test_search_matches_literal_values_only(self):
        with Workspace(self.special_folder) as session:
            for needle, count in (("back\\slash", 1), ("\u03c9MEGA", 1), ("4242", 1), ("&quot;x", 1), ('"kind":', 0), ("xml\"", 0)):
                with self.subTest(needle=needle):
                    self.assertEqual(len(session.list_records(text=needle)["records"]), count)
            session.stage_patch(replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Zebra</root>"))
            self.assertEqual(len(session.list_records(text="zebra")["records"]), 1)
            self.assertEqual(len(session.list_records(text="4242")["records"]), 0)
            for invalid in ("x" * 4097, 5, None):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "filter"):
                    session.list_records(text=invalid)

    def test_unknown_locators_are_invalid_input(self):
        for locator in ({"ole_path": ["Missing"]}, {"ole_path": ["Notes"], "chunk_index": 0}, {"ole_path": "Notes"}):
            with self.subTest(locator=locator), self.assertRaisesRegex(ValueError, "Unknown contextual record"):
                self.session.get_record(locator)

    def test_limit_boundaries(self):
        with self.assertRaisesRegex(ValueError, "record limit"):
            Workspace(self.folder, Limits(records=4))
        with Workspace(self.folder, Limits(records=5)) as session:
            self.assertEqual(len(session.records), 5)
        with self.assertRaisesRegex(ValueError, "depth"):
            Workspace(self.folder, Limits(depth=1))
        with self.assertRaisesRegex(ValueError, "limit|exceeds"):
            Workspace(self.folder, Limits(stream=200))
        locator = self.session.list_records(kind="dgn-text-element")["records"][0]["record"]
        two = replacement(self.session, locator, "/string/text", "Changed")
        two["operations"].append(replacement(self.session, {"ole_path": ["Notes"]}, "/text", "<root>Two</root>")["operations"][0])
        with Workspace(self.folder, Limits(operations=1)) as session, self.assertRaisesRegex(ValueError, "operation limit"):
            session.validate_patch(two)
        with Workspace(self.folder, Limits(operations=2)) as session:
            self.assertEqual(len(session.validate_patch(two)["changes"]), 2)
        size = len(json.dumps(two, indent=2).encode()) + 1
        with Workspace(self.folder, Limits(patch=size - 1)) as session, self.assertRaisesRegex(ValueError, "Patch size"):
            session.validate_patch(two)
        for invalid in ({"stream": -1}, {"records": 0}, {"depth": 1.5}, {"operations": True}):
            with self.subTest(limits=invalid), self.assertRaises(ValueError):
                Limits(**invalid)


@unittest.skipUnless(STORAGE_AVAILABLE, "Synthetic compound-file integration requires Windows/pywin32")
class TransactionFaultTests(unittest.TestCase):
    """Process death, locks, disk-full and tampered journals around multi-file saves."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = create_workspace(self.root)

    def two_file_patch(self, session):
        locator = session.list_records(kind="dgn-text-element")["records"][0]["record"]
        proposal = replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Edited</root>")
        proposal["operations"].append(replacement(session, locator, "/string/text", "Changed")["operations"][0])
        return proposal, locator

    def state(self, locator):
        with Workspace(self.folder) as session:
            return session.get_record({"ole_path": ["Notes"]})["value"]["text"], session.get_record(locator)["value"]["string"]["text"]

    def journal(self) -> Path:
        return self.folder / ".dgn-explorer" / "transaction.json"

    def test_process_killed_at_each_boundary_recovers_on_reopen(self):
        script = (
            "import json, os, sys\nfrom pathlib import Path\nfrom dgn_explorer.workspace import Workspace\n"
            "folder, boundary, proposal = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])\n"
            "with Workspace(folder) as session:\n"
            "    session.stage_patch(proposal)\n"
            "    def fault(stage):\n"
            "        if stage == boundary:\n"
            "            os._exit(9)\n"
            "    session.save_workspace(fault=fault)\n"
        )
        pristine = {path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob("*") if path.is_file() and ".dgn-explorer" not in path.parts}
        for boundary in ("prepared", "published:0", "published:1", "committed", "never"):
            with self.subTest(boundary=boundary):
                for relative, data in pristine.items():
                    (self.folder / relative).write_bytes(data)
                with Workspace(self.folder) as session:
                    proposal, locator = self.two_file_patch(session)
                completed = run_child(script, self.folder, boundary, json.dumps(proposal))
                self.assertEqual(completed.returncode, 0 if boundary == "never" else 9, completed.stderr)
                self.assertEqual(self.journal().exists(), boundary != "never")
                saved = boundary in ("committed", "never")
                self.assertEqual(self.state(locator), ("<root>Edited</root>", "Changed") if saved else ("<root>Original text</root>", "Text"))
                self.assertFalse(self.journal().exists())
                self.assertEqual(leftovers(self.folder, ".dgn-save-"), [])

    def test_lock_is_exclusive_across_processes_and_released_on_death(self):
        script = (
            "import sys\nfrom pathlib import Path\nfrom dgn_explorer.transactions import ownership\n"
            "with ownership(Path(sys.argv[1])):\n    print('locked', flush=True)\n    sys.stdin.readline()\n"
        )
        with Workspace(self.folder) as session:
            proposal, _ = self.two_file_patch(session)
            session.stage_patch(proposal)
            patch_file = self.root / "patch.json"
            patch_file.write_text(json.dumps(proposal))
            holder = subprocess.Popen([sys.executable, "-c", script, str(self.folder)], cwd=Path(__file__).parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                with self.assertRaisesRegex(ConflictError, "owned"):
                    Workspace(self.folder)
                with self.assertRaisesRegex(ConflictError, "owned"):
                    session.save_workspace()
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cli.main(["--json", "apply", str(self.folder), "--patch", str(patch_file), "--approve"]), 4)
                self.assertEqual(json.loads(output.getvalue())["errors"][0]["code"], 4)
            finally:
                holder.kill()
                holder.communicate(timeout=30)
            self.assertEqual(session.save_workspace()["saved_files"], 2)

    def test_disk_full_during_publication_rolls_back(self):
        import errno
        import os
        from dgn_explorer import transactions

        with Workspace(self.folder) as session:
            proposal, locator = self.two_file_patch(session)
            session.stage_patch(proposal)
            before = dict(session.files)
            real_fsync, calls = os.fsync, []

            def fsync(descriptor):
                calls.append(descriptor)
                if len(calls) == 2:
                    raise OSError(errno.ENOSPC, "No space left on device")
                return real_fsync(descriptor)

            with patch.object(transactions.os, "fsync", side_effect=fsync), self.assertRaises(OSError) as raised:
                session.save_workspace()
            self.assertEqual(raised.exception.errno, errno.ENOSPC)
            self.assertEqual(cli.error_details(raised.exception)[0], 5)
            self.assertEqual(before, {name: (self.folder / name).read_bytes() for name in before})
            self.assertTrue(session.pending)
        self.assertFalse(self.journal().exists())
        self.assertEqual(leftovers(self.folder, ".dgn-save-"), [])
        self.assertEqual(self.state(locator), ("<root>Original text</root>", "Text"))

    def test_failed_rollback_retains_journal_until_reopen(self):
        from dgn_explorer import transactions

        with Workspace(self.folder) as session:
            proposal, locator = self.two_file_patch(session)
            session.stage_patch(proposal)

            def fault(stage):
                if stage == "published:0":
                    raise OSError("Injected write failure")

            with patch.object(transactions, "recover", side_effect=OSError("rollback denied")), self.assertRaises(OSError) as raised:
                session.save_workspace(fault=fault)
            self.assertIn("Rollback is incomplete", "\n".join(getattr(raised.exception, "__notes__", [])))
            self.assertTrue(self.journal().exists())
        self.assertEqual(self.state(locator), ("<root>Original text</root>", "Text"))
        self.assertFalse(self.journal().exists())

    def test_tampered_journals_are_rejected_and_retained(self):
        class Interrupted(BaseException):
            pass

        with Workspace(self.folder) as session:
            proposal, locator = self.two_file_patch(session)
            session.stage_patch(proposal)
            target = sorted(session.pending)[0]

            def fault(stage):
                raise Interrupted()

            with self.assertRaises(Interrupted):
                session.save_workspace(fault=fault)
        prepared = json.loads(self.journal().read_bytes())
        target_bytes = (self.folder / target).read_bytes()
        (self.folder / "my-notes.txt").write_text("user file")

        def mutate(name):
            transaction = json.loads(json.dumps(prepared))
            item = transaction["files"][0]
            if name == "schema":
                transaction["schema"] = "dgn-explorer.transaction-v0"
            elif name == "state":
                transaction["state"] = "publishing"
            elif name == "extra":
                transaction["extra"] = True
            elif name == "unreachable":
                item["file"] = "my-notes.txt"
            elif name == "escape":
                item["file"] = "../outside.json"
            elif name == "duplicate":
                transaction["files"].append(dict(item))
            elif name == "base64":
                item["before"] = "!!not base64!!"
            elif name == "source":
                transaction["source_sha256"] = "0" * 64
            elif name == "incomplete":
                transaction["state"] = "committed"
            return json.dumps(transaction).encode()

        cases = {name: mutate(name) for name in ("schema", "state", "extra", "unreachable", "escape", "duplicate", "base64", "source", "incomplete")}
        cases["syntax"] = b"{not json"
        cases["changed"] = json.dumps(prepared).encode()
        for name, data in cases.items():
            with self.subTest(journal=name):
                self.journal().write_bytes(data)
                if name == "changed":
                    (self.folder / target).write_bytes(target_bytes + b" ")
                with self.assertRaises(ValueError):
                    Workspace(self.folder)
                self.assertEqual(self.journal().read_bytes(), data)
                (self.folder / target).write_bytes(target_bytes)
        self.assertEqual((self.folder / "my-notes.txt").read_text(), "user file")
        self.journal().write_bytes(json.dumps(prepared).encode())
        self.assertEqual(self.state(locator), ("<root>Original text</root>", "Text"))

    def test_recovery_cannot_promote_protected_files_to_write_targets(self):
        import base64

        with Workspace(self.folder) as session:
            manifest_name = session.manifest_name
            stream_file = session.manifest["streams"][0]["file"]
            source_hash = session.source_hash
        view_path = self.folder / stream_file
        original_view = view_path.read_bytes()
        for target in ("original.dgn", manifest_name, "my-notes.txt"):
            with self.subTest(target=target):
                path = self.folder / target
                if not path.exists():
                    path.write_bytes(b"Retained user notes")
                before = path.read_bytes()
                view = parse_json(original_view)
                view["text_file"] = target
                view_path.write_bytes(json.dumps(view).encode())
                transaction = {
                    "schema": "dgn-explorer.transaction-v1", "state": "prepared",
                    "source_sha256": source_hash,
                    "files": [{"file": target, "before": base64.b64encode(b"replacement").decode(),
                               "after_sha256": codecs.digest(before)}],
                }
                journal_bytes = json.dumps(transaction).encode()
                self.journal().write_bytes(journal_bytes)
                try:
                    with self.assertRaises(ValueError):
                        Workspace(self.folder)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(self.journal().read_bytes(), journal_bytes)
                finally:
                    path.write_bytes(before)
                    view_path.write_bytes(original_view)
                    self.journal().unlink(missing_ok=True)

    def test_external_change_or_removal_before_save_is_a_conflict(self):
        for action in ("modify", "remove", "original"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temporary:
                folder = create_workspace(Path(temporary))
                with Workspace(folder) as session:
                    session.stage_patch(replacement(session, {"ole_path": ["Notes"]}, "/text", "<root>Edited</root>"))
                    target = next(iter(session.pending))
                    other = next(name for name in session.files if name != target and name.startswith("objects/"))
                    if action == "modify":
                        (folder / other).write_bytes((folder / other).read_bytes() + b" ")
                    elif action == "remove":
                        (folder / other).unlink()
                    else:
                        (folder / "original.dgn").write_bytes(b"replaced")
                    before = (folder / target).read_bytes()
                    with self.assertRaises(ConflictError):
                        session.save_workspace()
                    with self.assertRaises(ConflictError):
                        session.pack_workspace(Path(temporary) / "out.dgn")
                    self.assertEqual((folder / target).read_bytes(), before)
                    self.assertFalse((folder / ".dgn-explorer" / "transaction.json").exists())
                    self.assertFalse((Path(temporary) / "out.dgn").exists())


class OutputSafetyTests(ApplicationFixture):
    def test_extraction_views_are_derived_from_the_retained_snapshot(self):
        from test_support import create_dgn

        alternate = self.root / "alternate.dgn"
        create_dgn(alternate, notes_text="Captured snapshot")
        real_copy = dgn_folder.shutil.copyfile

        def captured_copy(source, destination, *args, **kwargs):
            return real_copy(alternate, destination, *args, **kwargs)

        folder = self.root / "captured"
        with patch.object(dgn_folder.shutil, "copyfile", side_effect=captured_copy):
            codecs.extract(self.root / "input.dgn", folder, 1024 * 1024)
        self.assertEqual((folder / "original.dgn").read_bytes(), alternate.read_bytes())
        with Workspace(folder) as session:
            self.assertEqual(session.get_record({"ole_path": ["Notes"]})["value"]["text"],
                             "<root>Captured snapshot</root>")
            output = self.root / "captured-noop.dgn"
            session.pack_workspace(output)
        self.assertEqual(output.read_bytes(), alternate.read_bytes())
        self.assertEqual((self.root / "input.dgn").read_bytes(), (self.folder / "original.dgn").read_bytes())
    """Output races, disk exhaustion and links/path escapes (T21)."""

    def test_pack_rebuilds_from_memory_snapshot(self):
        self.session.stage_patch(self.proposal())
        calls = []
        rebuild = codecs.rebuild

        def recording(folder, output, limit, cancel=None, store=None):
            calls.append((sorted(path.name for path in Path(folder).iterdir()), store))
            return rebuild(folder, output, limit, cancel=cancel, store=store)

        with patch.object(codecs, "rebuild", side_effect=recording):
            self.session.pack_workspace(self.root / "memory.dgn")
        (names, store), = calls
        self.assertEqual(names, ["original.dgn"])
        self.assertIsInstance(store, codecs.MemoryStore)
        self.assertEqual(set(store.files), set(self.session.files))
        folder_copy = self.root / "folder-copy"
        import shutil

        shutil.copytree(self.folder, folder_copy, ignore=shutil.ignore_patterns(".dgn-explorer"))
        for name, data in self.session.pending.items():
            (folder_copy / name).write_bytes(data)
        self.assertEqual(codecs.rebuild(folder_copy, self.root / "folder.dgn", 1024 * 1024), 1)
        with codecs.ole_reader().OleFileIO(str(self.root / "memory.dgn")) as memory, codecs.ole_reader().OleFileIO(str(self.root / "folder.dgn")) as disk:
            self.assertEqual(memory.listdir(), disk.listdir())
            for names in memory.listdir():
                self.assertEqual(memory.openstream(names).read(), disk.openstream(names).read())
        memory_store = codecs.MemoryStore({"objects/a.json": b"{}"})
        with self.assertRaises(FileNotFoundError):
            memory_store.read("objects/missing.json", 10)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            memory_store.read("objects/a.json", 1)
        for unsafe in ("../a.json", "C:/a.json", "/a.json", ""):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                memory_store.read(unsafe, 10)

    def test_pack_output_race_preserves_racing_file(self):
        output = self.root / "raced.dgn"
        rebuild = codecs.rebuild

        def racing(*args, **kwargs):
            result = rebuild(*args, **kwargs)
            output.write_bytes(b"racing writer")
            return result

        with patch.object(codecs, "rebuild", side_effect=racing), self.assertRaises(FileExistsError):
            self.session.pack_workspace(output)
        self.assertEqual(output.read_bytes(), b"racing writer")
        self.assertEqual(leftovers(self.root, ".dgn-output-"), [])

    def test_insufficient_disk_is_reported_before_writing(self):
        import errno
        import shutil
        from types import SimpleNamespace
        from dgn_explorer.operations import import_dgn

        full = SimpleNamespace(total=1, used=1, free=0)
        with patch.object(shutil, "disk_usage", return_value=full):
            with self.assertRaises(OSError) as raised:
                self.session.pack_workspace(self.root / "full.dgn")
            self.assertEqual(raised.exception.errno, errno.ENOSPC)
            with self.assertRaises(OSError) as raised:
                import_dgn(self.root / "input.dgn", self.root / "full-import", Limits())
            self.assertEqual(raised.exception.errno, errno.ENOSPC)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["--json", "pack", str(self.folder), str(self.root / "cli-full.dgn")]), 5)
            self.assertEqual(json.loads(output.getvalue())["errors"][0]["code"], 5)
        for name in ("full.dgn", "full-import", "cli-full.dgn"):
            self.assertFalse((self.root / name).exists())
        self.assertEqual(leftovers(self.root, ".dgn-output-", ".dgn-import-"), [])

    def test_import_destination_race_and_invalid_sources(self):
        from dgn_explorer.operations import import_dgn

        destination = self.root / "raced"
        extract = codecs.extract

        def racing(*args, **kwargs):
            result = extract(*args, **kwargs)
            destination.mkdir()
            return result

        with patch.object(codecs, "extract", side_effect=racing), self.assertRaisesRegex(ValueError, "appears"):
            import_dgn(self.root / "input.dgn", destination, Limits())
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual(leftovers(self.root, ".dgn-import-"), [])
        text = self.root / "not.dgn"
        text.write_bytes(b"plain text, not a compound file")
        with self.assertRaisesRegex(ValueError, "Not a DGN"):
            import_dgn(text, self.root / "from-text", Limits())
        with self.assertRaises(FileNotFoundError):
            import_dgn(self.root / "missing.dgn", self.root / "from-missing", Limits())
        self.assertFalse((self.root / "from-text").exists())

    def junction(self, link: Path, target: Path):
        completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        if completed.returncode:
            self.skipTest("Directory junctions are unavailable: " + completed.stderr.strip())

    @unittest.skipUnless(sys.platform == "win32", "Directory junctions are Windows-specific")
    def test_junctions_are_rejected(self):
        import shutil

        outside = self.root / "outside"
        shutil.move(self.folder / "objects", outside)
        self.junction(self.folder / "objects", outside)
        with self.assertRaisesRegex(ValueError, "Links/reparse|escapes"):
            Workspace(self.folder)
        (self.folder / "objects").rmdir()
        shutil.move(outside, self.folder / "objects")
        shutil.rmtree(self.folder / ".dgn-explorer")
        session_target = self.root / "session-target"
        session_target.mkdir()
        self.junction(self.folder / ".dgn-explorer", session_target)
        with self.assertRaisesRegex(ValueError, "Linked session directory"):
            Workspace(self.folder)
        self.assertEqual(list(session_target.iterdir()), [])

    def test_manifest_references_cannot_escape(self):
        manifest_path = self.folder / "manifest.rw.json"
        pristine = manifest_path.read_bytes()
        (self.root / "outside.json").write_text("{}")
        for target in ("../outside.json", "C:/Windows/win.ini", "objects/../../outside.json", ".dgn-explorer/writer.lock", "objects\\index.json", "", 5):
            with self.subTest(target=target):
                manifest = json.loads(pristine)
                manifest["streams"][0]["file"] = target
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    Workspace(self.folder)
        manifest_path.write_bytes(pristine)
        Workspace(self.folder).close()


class CommandProtocolTests(ApplicationFixture):
    def invoke(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            code = cli.main(["--json", *map(str, arguments)])
        return code, json.loads(output.getvalue()), errors.getvalue()

    def test_json_usage_errors_use_versioned_envelope(self):
        folder = str(self.folder)
        for arguments in ([], ["unknown", folder], ["list"], ["list", folder, "--limit", "0"], ["list", folder, "--limit", "1001"],
                          ["search", folder, "--text", "x", "--cursor", "-1"], ["search", folder], ["show", folder],
                          ["--max-mib", "0", "list", folder], ["--aggregate-mib", "x", "list", folder], ["apply", folder, "--patch", "p.json"],
                          ["apply", folder, "--patch", "p.json", "--dry-run", "--approve"], ["unpack", "--bytes-mode", "raw", "a", "b"]):
            with self.subTest(arguments=arguments):
                code, result, errors = self.invoke(*arguments)
                self.assertEqual(code, 2)
                self.assertEqual((result["protocol"], result["operation"], result["success"]), ("dgn-explorer.result-v1", None, False))
                self.assertEqual(result["errors"][0]["code"], 2)
                self.assertTrue(result["errors"][0]["message"].startswith("Usage error:"))
                self.assertEqual(errors, "")

    def test_human_usage_and_execution_errors_use_stderr(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit) as raised:
            cli.main(["list", str(self.folder), "--limit", "0"])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("usage:", errors.getvalue())
        self.assertIn("--limit: must be between 1 and 1000", errors.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            code = cli.main(["show", str(self.folder), "--record", '{"ole_path":["Missing"]}'])
        self.assertEqual(code, 3)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Unknown contextual record", errors.getvalue())

    def test_exit_code_matrix(self):
        stale = self.proposal()
        stale["workspace_revision"] = "sha256:" + "0" * 64
        invalid_xml = self.proposal(value="<root>unclosed")
        files = {}
        for name, content in (("stale", stale), ("invalid_xml", invalid_xml), ("valid", self.proposal())):
            files[name] = self.root / f"{name}.json"
            files[name].write_text(json.dumps(content))
        existing = self.root / "existing.dgn"
        existing.write_bytes(b"keep")
        inspect_output = self.root / "inspect.json"
        inspect_output.write_text("keep")
        cases = (
            (0, ["validate", self.folder]),
            (3, ["show", self.folder, "--record", '{"ole_path":["Missing"]}']),
            (3, ["show", self.folder, "--record", "[1,"]),
            (4, ["apply", self.folder, "--patch", files["stale"], "--dry-run"]),
            (3, ["apply", self.folder, "--patch", files["invalid_xml"], "--dry-run"]),
            (5, ["apply", self.folder, "--patch", self.root / "missing.json", "--dry-run"]),
            (3, ["pack", self.folder, existing]),
            (3, ["pack", self.folder, self.folder / "inside.dgn"]),
            (5, ["inspect", self.root / "input.dgn", "--output", inspect_output]),
            (3, ["unpack", self.root / "input.dgn", self.folder]),
            (5, ["list", self.root / "no-workspace"]),
            (0, ["pack", self.folder, self.root / "packed.dgn", "--patch", files["valid"]]),
        )
        for expected, arguments in cases:
            with self.subTest(arguments=[str(argument) for argument in arguments]):
                code, result, _ = self.invoke(*arguments)
                self.assertEqual(code, expected, result)
                self.assertEqual(result["success"], expected == 0)
                if expected:
                    self.assertEqual(result["errors"][0]["code"], expected)
        self.assertEqual(existing.read_bytes(), b"keep")
        self.assertEqual(inspect_output.read_text(), "keep")
        self.assertFalse((self.root / "no-workspace").exists())
        with Workspace(self.folder) as reopened:
            self.assertEqual(reopened.diff_workspace()["changes"], [])

    def test_oversized_patch_file_is_rejected_before_parsing(self):
        patch_file = self.root / "large.json"
        patch_file.write_bytes(b" " * (Limits().patch + 1))
        code, result, _ = self.invoke("apply", self.folder, "--patch", patch_file, "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("size limit", result["errors"][0]["message"])

    def test_filtered_cli_pagination(self):
        (self.root / "three").mkdir()
        folder = create_workspace(self.root / "three", text_count=3)
        code, first, _ = self.invoke("list", folder, "--kind", "dgn-text-element", "--limit", "4")
        self.assertEqual((code, len(first["result"]["records"]), first["result"]["next_cursor"]), (0, 4, 4))
        code, second, _ = self.invoke("list", folder, "--kind", "dgn-text-element", "--limit", "4", "--cursor", "4")
        self.assertEqual((len(second["result"]["records"]), second["result"]["next_cursor"]), (2, None))
        self.assertFalse({json.dumps(item["record"]) for item in first["result"]["records"]} & {json.dumps(item["record"]) for item in second["result"]["records"]})
        code, model, _ = self.invoke("search", folder, "--text", "Text", "--model", "#000002", "--kind", "dgn-text-element")
        self.assertEqual(len(model["result"]["records"]), 3)
        self.assertTrue(all(item["record"]["ole_path"][1] == "#000002" for item in model["result"]["records"]))
        code, beyond, _ = self.invoke("list", folder, "--cursor", "1000")
        self.assertEqual((code, beyond["result"]["records"], beyond["result"]["next_cursor"]), (0, [], None))

    def test_documented_commands_parse(self):
        root = Path(__file__).parent
        commands = []
        for document in (root / "README.md", root / "skills" / "dgn-explorer" / "SKILL.md"):
            text = document.read_text(encoding="utf-8")
            commands += re.findall(r"^dgn-explorer (.+)$", text, re.MULTILINE) + re.findall(r"`dgn-explorer ([^`]+)`", text)
        self.assertGreaterEqual(len(commands), 10)
        parser = cli.build_parser()
        for command in commands:
            with self.subTest(command=command):
                arguments = command.replace("LOCATOR_JSON", '{"ole_path":["Notes"]}').split()
                if "..." in arguments:
                    continue
                parsed = parser.parse_args(arguments)
                self.assertIn(parsed.command, {"unpack", "extract", "pack", "rebuild", "inspect", "list", "show", "search", "validate", "diff", "apply"})


@unittest.skipUnless(STORAGE_AVAILABLE, "Synthetic compound-file integration requires Windows/pywin32")
class WorkerLatencyTests(unittest.TestCase):
    """Cooperative cancellation: checkpoint gaps and real subprocess cancellation."""

    COUNT = 400
    BUDGET = 2.0

    @classmethod
    def setUpClass(cls):
        cls.folder = shared_workspace(text_count=cls.COUNT)

    def test_checkpoint_gaps_are_bounded_for_each_operation(self):
        from dgn_explorer.operations import execute

        locator = {"ole_path": ["Dgn-Md", "#000001", "Dgn^G", "$1"], "chunk_index": 0}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            operations = (
                ("import", {"source": str(self.folder.parent / "input.dgn"), "folder": str(root / "imported")}),
                ("open", {"folder": str(self.folder)}),
                ("search", {"folder": str(self.folder), "text": "no such text"}),
                ("validate", {"folder": str(self.folder)}),
                ("show", {"folder": str(self.folder), "record": locator, "summary": True}),
                ("pack", {"folder": str(self.folder), "output": str(root / "packed.dgn")}),
            )
            for operation, arguments in operations:
                with self.subTest(operation=operation):
                    polls = []

                    def poll():
                        polls.append(time.perf_counter())
                        return False

                    started = time.perf_counter()
                    execute(operation, arguments, Limits(), poll)
                    timeline = [started, *polls, time.perf_counter()]
                    gap = max(later - earlier for earlier, later in zip(timeline, timeline[1:]))
                    self.assertGreater(len(polls), 3)
                    self.assertLess(gap, self.BUDGET, f"{operation} cancellation gap {gap:.3f}s")
                    trigger = len(polls) // 2

                    def cancel_midway(count=[0]):
                        count[0] += 1
                        return count[0] > trigger

                    with self.assertRaises((CancelledError, InterruptedError)):
                        execute(operation, {**arguments, **({"folder": str(root / "cancelled-import")} if operation == "import" else {}), **({"output": str(root / "cancelled.dgn")} if operation == "pack" else {})}, Limits(), cancel_midway)
            self.assertFalse((root / "cancelled.dgn").exists())
            self.assertFalse((root / "cancelled-import").exists())
            self.assertEqual(leftovers(root, ".dgn-output-", ".dgn-import-"), [])

    def test_real_worker_cancellation_latency(self):
        from dgn_explorer.worker import PROTOCOL

        request = {"protocol": PROTOCOL, "request_id": "cancel-me", "operation": "validate", "arguments": {"folder": str(self.folder)}}
        process = subprocess.Popen([sys.executable, "-m", "dgn_explorer", "--worker"], cwd=Path(__file__).parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdin.write((json.dumps(request) + "\n").encode())
            process.stdin.flush()
            self.assertEqual(json.loads(process.stdout.readline())["event"], "progress")
            started = time.perf_counter()
            process.stdin.write((json.dumps({"protocol": PROTOCOL, "request_id": "cancel-me", "event": "cancel"}) + "\n").encode())
            process.stdin.flush()
            output, errors = process.communicate(timeout=60)
            latency = time.perf_counter() - started
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        final = json.loads(output.decode().splitlines()[-1])
        self.assertEqual(process.returncode, 6, errors)
        self.assertEqual((final["event"], final["payload"]["code"]), ("failed", 6))
        self.assertLess(latency, self.BUDGET + 3, f"cancel latency {latency:.3f}s")

    def test_malformed_cancel_signal_cancels_conservatively(self):
        from dgn_explorer.worker import PROTOCOL

        request = {"protocol": PROTOCOL, "request_id": "garbled", "operation": "validate", "arguments": {"folder": str(self.folder)}}
        completed = subprocess.run([sys.executable, "-m", "dgn_explorer", "--worker"], cwd=Path(__file__).parent, input=(json.dumps(request) + "\n{garbled\n").encode(), capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, 6, completed.stderr)
        self.assertEqual(json.loads(completed.stdout.decode().splitlines()[-1])["payload"]["code"], 6)


if __name__ == "__main__":
    unittest.main()