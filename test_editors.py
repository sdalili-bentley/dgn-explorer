"""Reversible editor representations and passive, bounded payload-file workflows."""

import errno
from pathlib import Path
import unittest
from unittest.mock import patch

import dgn_folder
from dgn_explorer import codecs
from dgn_explorer.operations import execute, export_payload, load_payload
from dgn_explorer.workspace import Limits, Workspace, get_pointer
from test_support import STORAGE_AVAILABLE, create_workspace, editor_test_root


class EditorCodecTests(unittest.TestCase):
    VALUES = ("", "ASCII", "\0", "\0A\0", "A\0B", "\r\n\t\b\f\v\a", "café Ω 中文 😀",
              '"quoted" \\u0000 C:\\notes\\test', "\u2028\u2029", "".join(map(chr, range(128))))

    def test_all_formats_are_reversible_utf8_and_share_one_codec(self):
        self.assertIs(codecs.editor_encode, dgn_folder.editor_encode)
        self.assertIs(codecs.editor_decode, dgn_folder.editor_decode)
        for value in self.VALUES:
            data = value.encode("utf-8")
            for format in codecs.EDITOR_FORMATS:
                with self.subTest(value=repr(value), format=format):
                    shown = codecs.editor_encode(data, format)
                    self.assertEqual(codecs.editor_decode(shown, format), data)
                    self.assertEqual(codecs.editor_text(shown, format), value)
                    if format != "plain":
                        self.assertNotIn("\0", shown)
                        shown.encode("ascii")

    def test_escape_syntax_unicode_scalars_and_literal_backslashes(self):
        for shown, value in ((r"A\x00B\u0000", "A\0B\0"), (r"\r\n\t", "\r\n\t"),
                             (r"\ud83d\ude00", "😀"), (r"\U0001F600", "😀"),
                             (r"café\u03a9", "caféΩ"), (r"\\u0000", r"\u0000"),
                             (r"\'\"\/", "'\"/"), ("", "")):
            with self.subTest(shown=shown):
                self.assertEqual(codecs.editor_text(shown, "escaped"), value)

    def test_invalid_escapes_are_not_guessed_or_evaluated(self):
        for shown in ("\\", r"\x0", r"\xgg", r"\uZZZZ", r"\ud800", r"\udc00",
                      r"\ud800\u0041", r"\U00110000", r"\q", r"\0", r"\N{NULL}"):
            with self.subTest(shown=shown), self.assertRaises(ValueError):
                codecs.editor_text(shown, "escaped")

    def test_hex_accepts_spaced_continuous_and_wrapped_octets(self):
        for shown in ("001f48ff", "00 1F 48 FF", "00\t1f\r\n48 ff"):
            self.assertEqual(codecs.editor_decode(shown, "hex"), b"\0\x1fH\xff")
        for shown in ("0", "00 1", "zz", "0x00", "00-ff", "００", "00\u00a0ff"):
            with self.subTest(shown=shown), self.assertRaises(ValueError):
                codecs.editor_decode(shown, "hex")

    def test_base64_requires_standard_alphabet_padding_and_canonical_bits(self):
        self.assertEqual(codecs.editor_decode("AA==\r\n", "base64"), b"\0")
        self.assertEqual(codecs.editor_decode("AAEC /w==", "base64"), b"\0\1\2\xff")
        for shown in ("A", "AA", "AA=", "AA===", "AB==", "AAB=", "AA==QQ==",
                      "====", "_w==", "/w==!", "é", "AA==\u00a0"):
            with self.subTest(shown=shown), self.assertRaises(ValueError):
                codecs.editor_decode(shown, "base64")

    def test_binary_octets_are_reversible_but_cannot_be_staged_as_strings(self):
        data = bytes(range(256))
        for format in ("hex", "base64"):
            shown = codecs.editor_encode(data, format)
            self.assertEqual(codecs.editor_decode(shown, format), data)
            with self.assertRaisesRegex(ValueError, "valid UTF-8"):
                codecs.editor_text(shown, format)
        with self.assertRaises(UnicodeError):
            codecs.editor_encode(data, "plain")

    def test_decoded_size_limits_apply_to_every_representation(self):
        for format in codecs.EDITOR_FORMATS:
            for data in (b"A" * 16, b"\0" * 16):
                with self.subTest(format=format, data=data):
                    shown = codecs.editor_encode(data, format)
                    self.assertEqual(codecs.editor_decode(shown, format, 16), data)
                    with self.assertRaisesRegex(ValueError, "exceeds"):
                        codecs.editor_decode(codecs.editor_encode(data + b"A", format), format, 16)
        with self.assertRaises(ValueError):
            codecs.editor_encode(b"", "unknown")
        with self.assertRaises(ValueError):
            codecs.editor_decode("", "unknown")

    def test_plain_widget_safety_detects_controls_and_unicode_line_separators(self):
        for value in ("", "Text", "café 😀", "Line\nTab\t"):
            self.assertTrue(codecs.editor_plain_safe(value))
        for value in ("\0", "\r", "\x1f", "\x7f", "\u2028", "\u2029"):
            self.assertFalse(codecs.editor_plain_safe(value))


class PayloadFileTests(unittest.TestCase):
    def setUp(self):
        self.root = editor_test_root(self)

    def test_load_export_empty_unicode_and_all_binary_octets(self):
        for index, data in enumerate((b"", "café 😀\0\r\n".encode("utf-8"), bytes(range(256)))):
            with self.subTest(index=index):
                source = self.root / f"source-{index}"
                source.write_bytes(data)
                self.assertEqual(load_payload(source), data)
                output = self.root / f"export-{index}"
                result = export_payload(output, data)
                self.assertEqual(result["bytes"], len(data))
                self.assertEqual(output.read_bytes(), data)
                self.assertEqual(source.read_bytes(), data)

    def test_load_and_export_enforce_editor_and_smaller_stream_limits(self):
        for limit in (16, codecs.EDITOR_LIMIT):
            with self.subTest(limit=limit):
                source = self.root / f"limit-{limit}"
                source.write_bytes(b"x" * limit)
                limits = Limits(stream=limit)
                self.assertEqual(len(load_payload(source, limits)), limit)
                source.write_bytes(b"x" * (limit + 1))
                with self.assertRaisesRegex(ValueError, "editor limit"):
                    load_payload(source, limits)
                output = self.root / f"oversize-{limit}"
                with self.assertRaises(ValueError):
                    export_payload(output, source.read_bytes(), limits)
                self.assertFalse(output.exists())
        source = self.root / "hard-cap"
        source.write_bytes(b"x" * (codecs.EDITOR_LIMIT + 1))
        with self.assertRaises(ValueError):
            load_payload(source, Limits(stream=codecs.EDITOR_LIMIT * 2))

    def test_missing_unreadable_and_nonregular_files(self):
        with self.assertRaises(OSError):
            load_payload(self.root / "missing")
        source = self.root / "source"
        source.write_bytes(b"content")
        with patch.object(Path, "open", side_effect=PermissionError("denied")), self.assertRaises(PermissionError):
            load_payload(source)
        with patch("dgn_explorer.operations.S_ISREG", return_value=False), self.assertRaisesRegex(ValueError, "regular"):
            load_payload(source)

    def test_existing_input_and_workspace_destinations_are_never_overwritten(self):
        source = self.root / "source"
        source.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "already exists"):
            export_payload(source, b"replacement")
        self.assertEqual(source.read_bytes(), b"original")
        folder = self.root / "workspace"
        folder.mkdir()
        for output in (folder / "new.txt", folder / "child" / ".." / "new.txt"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "outside"):
                export_payload(output, b"data", workspace=folder)
            self.assertFalse((folder / "new.txt").exists())

    def test_publication_race_preserves_the_winning_file(self):
        output = self.root / "race"
        real_open = Path.open

        def racing_open(path, mode="r", *args, **kwargs):
            with real_open(path, "wb") as winner:
                winner.write(b"winner")
            return real_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", racing_open), self.assertRaises(FileExistsError):
            export_payload(output, b"loser")
        self.assertEqual(output.read_bytes(), b"winner")

    def test_write_failure_removes_only_partial_output(self):
        output = self.root / "partial"
        with patch("dgn_explorer.operations.os.fsync", side_effect=OSError(errno.ENOSPC, "full")), self.assertRaises(OSError):
            export_payload(output, b"draft")
        self.assertFalse(output.exists())
        with self.assertRaises(OSError):
            export_payload(self.root / "missing" / "output", b"draft")

    def test_cleanup_survives_close_errors_and_does_not_remove_replaced_outputs(self):
        real_open = Path.open
        for write_failure, replaced in ((True, False), (True, True), (False, False)):
            with self.subTest(replaced=replaced, write_failure=write_failure):
                output = self.root / f"close-error-{replaced}"

                class BrokenDestination:
                    def __init__(self, stream):
                        self.stream = stream

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        self.stream.close()

                    def fileno(self):
                        return self.stream.fileno()

                    def write(self, data):
                        if not write_failure:
                            return self.stream.write(data)
                        self.stream.write(b"partial")
                        self.stream.flush()
                        raise OSError(errno.ENOSPC, "write failure")

                    def flush(self):
                        self.stream.flush()

                    def close(self):
                        self.stream.close()
                        if replaced:
                            output.rename(self_root / "retained")
                            with real_open(output, "xb") as winner:
                                winner.write(b"winner")
                        raise OSError("close failure")

                self_root = self.root

                def broken_open(path, mode, *args, **kwargs):
                    return BrokenDestination(real_open(path, mode, *args, **kwargs))

                with patch.object(Path, "open", broken_open), self.assertRaises(OSError):
                    export_payload(output, b"draft")
                self.assertEqual(output.exists(), replaced)
                if replaced:
                    self.assertEqual(output.read_bytes(), b"winner")


@unittest.skipUnless(STORAGE_AVAILABLE, "Workspace file integration requires Windows/pywin32")
class WorkspaceEditorTests(unittest.TestCase):
    def setUp(self):
        self.root = editor_test_root(self)
        self.folder = create_workspace(self.root, rich=True)
        self.title = {"ole_path": ["\x05SummaryInformation"], "section_index": 0, "property_id": "2"}
        self.original = (self.root / "input.dgn").read_bytes()

    def test_encoded_property_nulls_roundtrip_through_pack_and_reimport(self):
        with Workspace(self.folder) as session:
            before = get_pointer(session.get_record(self.title)["value"], "/value")
            for format in codecs.EDITOR_FORMATS:
                with self.subTest(format=format):
                    value = "café\0middle\r\n\tend"
                    decoded = codecs.editor_text(codecs.editor_encode(value.encode("utf-8"), format), format)
                    proposal = {"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision,
                                "operations": [{"record": self.title, "pointer": "/value", "expected_value": before, "value": decoded}]}
                    session.stage_patch(proposal)
                    output = self.root / f"{format}.dgn"
                    session.pack_workspace(output)
                    folder = self.root / f"reimport-{format}"
                    codecs.extract(output, folder, 1024 * 1024)
                    with Workspace(folder) as reimported:
                        self.assertEqual(get_pointer(reimported.get_record(self.title)["value"], "/value"), value)
                    session.discard()
        self.assertEqual((self.root / "input.dgn").read_bytes(), self.original)

    def test_file_import_is_a_draft_and_export_respects_staged_values(self):
        locator = {"ole_path": ["Notes"]}
        value = "<root>café 😀\r\n\t</root>"
        source = self.root / "payload.xml"
        source.write_bytes(value.encode("utf-8"))
        pristine = {path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob("*") if path.is_file() and ".dgn-explorer" not in path.parts}
        arguments = {"folder": str(self.folder), "record": locator, "pointer": "/text"}
        loaded = execute("load-field", {**arguments, "source": str(source)})
        self.assertEqual(loaded["value"], value)
        with Workspace(self.folder) as session:
            self.assertFalse(session.pending)
            original_value = session.get_record(locator)["value"]["text"]
            proposal = {"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision,
                        "operations": [{"record": locator, "pointer": "/text", "expected_value": original_value, "value": loaded["value"]}]}
        output = self.root / "export.xml"
        execute("export-field", {**arguments, "patch": proposal, "output": str(output)})
        self.assertEqual(output.read_bytes(), source.read_bytes())
        self.assertEqual(pristine, {path.relative_to(self.folder): path.read_bytes() for path in self.folder.rglob("*") if path.is_file() and ".dgn-explorer" not in path.parts})
        self.assertEqual((self.root / "input.dgn").read_bytes(), self.original)

    def test_workspace_file_restrictions_and_byte_page_export(self):
        args = {"folder": str(self.folder), "record": self.title, "pointer": "/value"}
        source = self.root / "binary"
        source.write_bytes(b"\xff\0")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            execute("load-field", {**args, "source": str(source)})
        for locator, pointer in (({"ole_path": ["Opaque"]}, "/kind"), (self.title, "/codepage")):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                execute("load-field", {"folder": str(self.folder), "record": locator, "pointer": pointer, "source": str(source)})
        with self.assertRaisesRegex(ValueError, "outside"):
            execute("export-field", {**args, "output": str(self.folder / "forbidden")})
        with self.assertRaises(ValueError):
            execute("export-field", {**args, "record": {"ole_path": ["\x05SummaryInformation"], "section_index": 0, "property_id": "14"}, "output": str(self.root / "number")})
        output = self.root / "page"
        execute("export-bytes", {"folder": str(self.folder), "record": {"ole_path": ["Opaque"]}, "offset": 32, "output": str(output)})
        self.assertEqual(output.read_bytes(), bytes(range(32, 256)))
        with self.assertRaises(ValueError):
            execute("export-bytes", {"folder": str(self.folder), "record": {"ole_path": ["Opaque"]}, "offset": -1, "output": str(self.root / "invalid")})

    def test_field_limit_counts_payload_bytes_not_expanded_json_escapes(self):
        from dgn_explorer.operations import record_summary

        with Workspace(self.folder) as session:
            before = session.get_record(self.title)["value"]["value"]
            for value in ("\0" * codecs.EDITOR_LIMIT, "x" * codecs.EDITOR_LIMIT, "é" * (codecs.EDITOR_LIMIT // 2)):
                with self.subTest(value=repr(value[:4])):
                    proposal = {"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision,
                                "operations": [{"record": self.title, "pointer": "/value", "expected_value": before, "value": value}]}
                    session.stage_patch(proposal)
                    field = next(field for field in record_summary(session, self.title)["fields"] if field["pointer"] == "/value")
                    self.assertTrue(field["editable"])
                    self.assertEqual(field["value"], value)
                    session.discard()
            proposal["operations"][0]["value"] = "x" * (codecs.EDITOR_LIMIT + 1)
            session.stage_patch(proposal)
            field = next(field for field in record_summary(session, self.title)["fields"] if field["pointer"] == "/value")
            self.assertFalse(field["editable"])
            self.assertIn("exceeds editor limit", field["value"])

    def test_worker_file_operations_use_same_limits_and_non_overwriting_exports(self):
        from dgn_explorer.worker import PROTOCOL, run

        source = self.root / "source"
        source.write_bytes(b"A\0B")
        output = self.root / "worker-output"
        for operation, arguments in (
            ("load-field", {"record": self.title, "pointer": "/value", "source": str(source)}),
            ("export-field", {"record": self.title, "pointer": "/value", "output": str(output)}),
            ("export-bytes", {"record": {"ole_path": ["Opaque"]}, "output": str(self.root / "worker-page"), "offset": 0}),
        ):
            with self.subTest(operation=operation):
                events = []
                request = {"protocol": PROTOCOL, "request_id": "editor", "operation": operation,
                           "arguments": {"folder": str(self.folder), **arguments}}
                self.assertEqual(run(request, events.append), 0)
                self.assertEqual(events[-1]["event"], "completed")
        events = []
        self.assertEqual(run(request, events.append), 3)
        self.assertEqual(events[-1]["event"], "failed")
        self.assertEqual(output.read_bytes(), b"Synthetic title")
        self.assertEqual((self.root / "worker-page").read_bytes(), bytes(range(256)))


@unittest.skipUnless(STORAGE_AVAILABLE, "Feature editor integration requires Windows/pywin32")
class SpecificationEditorTests(unittest.TestCase):
    def setUp(self):
        self.root = editor_test_root(self)
        self.folder = create_workspace(self.root, features=True)

    def test_new_font_and_xml_fields_support_every_editor_representation(self):
        with Workspace(self.folder) as session:
            records = [record for record in session.records.values() if "#000001" in record.locator["ole_path"]]
            font = next(record.locator for record in records if record.value.get("core", {}).get("table_level") == 2 and "name" in record.value["core"])
            xml = next(record.locator for record in records if record.value.get("identity", {}).get("handler_id") == 22243 << 16)
            for format in codecs.EDITOR_FORMATS:
                values = [(font, "/core/name", "Font Ω 😀"), (xml, "/payload/payload/text", "<DataGroup><Value>Ω 😀</Value></DataGroup>")]
                operations = []
                for locator, pointer, value in values:
                    encoded = codecs.editor_encode(value.encode("utf-8"), format)
                    operations.append({"record": locator, "pointer": pointer,
                                       "expected_value": get_pointer(session.get_record(locator)["value"], pointer),
                                       "value": codecs.editor_text(encoded, format)})
                session.stage_patch({"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision, "operations": operations})
                output = self.root / f"{format}.dgn"
                session.pack_workspace(output)
                folder = self.root / f"{format}-reimported"
                codecs.extract(output, folder, 1024 * 1024)
                with Workspace(folder) as reimported:
                    for locator, pointer, value in values:
                        self.assertEqual(get_pointer(reimported.get_record(locator)["value"], pointer), value)
                session.discard()

    def test_feature_file_drafts_and_readonly_binary_export(self):
        with Workspace(self.folder) as session:
            font = next(record for record in session.records.values() if record.value.get("core", {}).get("table_level") == 2 and "name" in record.value["core"])
            ecxd = next(record for record in session.records.values() if record.value.get("identity", {}).get("handler_id", 0) >> 16 == 0xECDA)
            source = self.root / "font.txt"
            source.write_bytes("Imported Font Ω".encode("utf-8"))
            loaded = session.load_field(font.locator, "/core/name", source)
            self.assertEqual(loaded["value"], "Imported Font Ω")
            self.assertFalse(session.pending)
            output = self.root / "ecxd.bin"
            execute("export-bytes", {"folder": str(self.folder), "record": ecxd.locator, "output": str(output)})
            self.assertEqual(output.read_bytes(), codecs.view_bytes(ecxd.value))
            with self.assertRaises(ValueError):
                session.load_field(ecxd.locator, "/payload/provider_id", source)


if __name__ == "__main__":
    unittest.main()
