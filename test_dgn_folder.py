"""Run with: python -m unittest discover -s . -p test_dgn_folder.py -v"""

import json
import os
from pathlib import Path
import struct
import tempfile
import tomllib
from typing import Any, cast
import unittest
from unittest.mock import patch
from copy import deepcopy
import zlib

import dgn_folder as tool
import dgn_fixture_catalog as fixtures
import xml.etree.ElementTree as ET
from test_support import becxml_document, editor_test_root, element_chunk, feature_streams, property_stream, tagged_count, user_linkage, xml_fragment


SAMPLE = Path(os.environ.get("DGN_EXPLORER_SAMPLE") or Path(__file__).with_name("sample.dgn"))


class RepresentationTests(unittest.TestCase):
    def test_nonfinite_native_numbers_remain_opaque_and_roundtrip(self):
        for variant, format in ((4, "f"), (5, "d")):
            for number in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(surface="property", variant=variant, number=number):
                    payload = struct.pack("<I" + format, variant, number)
                    self.assertIsNone(tool.property_value(payload, 1252))
                    raw = property_stream()[:48] + struct.pack("<4I", 16 + len(payload), 1, 2, 16) + payload
                    view = tool.properties_view(raw)
                    self.assertEqual(view["sections"][0]["properties"][0]["payload"]["kind"], "opaque-bytes")
                    self.assertEqual(tool.view_bytes(view), raw)
                    json.dumps(view, allow_nan=False)
        for element_type, raw in ((3, struct.pack("<4d", float("nan"), 0, 1, 1)),
                                  (4, struct.pack("<2I4d", 2, 0, 0, 0, float("inf"), 1)),
                                  (15, struct.pack("<5d", 1, 2, 0, float("-inf"), 0))):
            with self.subTest(surface="geometry", element_type=element_type):
                self.assertIsNone(tool.geometry_view(raw, element_type, False))
                chunk = element_chunk(element_type, raw, graphics=True)
                view = tool.element_chunks_view(chunk)
                json.dumps(view, allow_nan=False)
                self.assertEqual(tool.view_bytes(view), chunk)
        for offset in (16, 104, 112, 120, 128, 136, 144, 152):
            with self.subTest(surface="text", offset=offset):
                raw = bytearray(element_chunk(17, bytes(70), graphics=True))
                struct.pack_into("<d", raw, 12 + offset, float("nan"))
                view = tool.element_chunks_view(bytes(raw))
                json.dumps(view, allow_nan=False)
                self.assertEqual(tool.view_bytes(view), raw)
        raw = bytearray(element_chunk(3, struct.pack("<4d", 0, 0, 1, 1), graphics=True))
        struct.pack_into("<d", raw, 28, float("inf"))
        view = tool.element_chunks_view(bytes(raw))
        self.assertEqual(view["chunks"][0]["body"]["kind"], "opaque-bytes")
        json.dumps(view, allow_nan=False)
        self.assertEqual(tool.view_bytes(view), raw)
        core = bytearray(144)
        struct.pack_into("<d", core, 16, float("inf"))
        view = tool.record_core_view(bytes(core), 94, 0, True)
        self.assertIsNone(view)

    def test_uncompressed_design_header_encoding_preserves_framing_and_rejects_flags(self):
        store = tool.MemoryStore()
        store.view("payload.json", tool.binary_view(bytes(1576)))
        store.view("suffix.json", tool.binary_view(b""))
        entry = {
            "ole_path": ["Dgn~H"], "codec": "framed-raw", "file": "payload.json",
            "representation": "json-view", "prefix": "prefix.json", "prefix_representation": "json-view",
            "suffix": "suffix.json", "suffix_representation": "json-view",
        }
        for flags in (0, 4):
            prefix = struct.pack("<2H4I", flags, 4, 0, 0, 0, 0)
            store.view("prefix.json", tool.binary_view(prefix))
            with self.subTest(flags=flags):
                self.assertEqual(tool.encode_stream(store, entry, None, 16 * 1024), prefix + bytes(1576))
        for prefix in (b"", bytes(16), bytes(19), bytes(21),
                       *(struct.pack("<2H4I", flags, 4, 0, 0, 0, 0) for flags in (1, 2, 3, 7))):
            store.view("prefix.json", tool.binary_view(prefix))
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "Dgn~H framing"):
                tool.encode_stream(store, entry, None, 16 * 1024)

    def test_limited_reads_reject_files_growing_after_the_size_check(self):
        root = editor_test_root(self)
        source = root / "bounded-file"
        source.write_bytes(b"abcd")
        initial = source.stat()
        self.assertEqual(tool.read_limited(source, 4), b"abcd")
        with source.open("rb") as handle:
            with patch.object(Path, "open", return_value=handle), patch.object(handle, "read", wraps=handle.read) as reads:
                self.assertEqual(tool.read_limited(source, 128 * 1024 * 1024), b"abcd")
                self.assertEqual(reads.call_args_list[0].args, (5,))
                self.assertTrue(all(call.args[0] <= 65536 for call in reads.call_args_list))
        with self.assertRaises(ValueError):
            tool.read_limited(source, 3)
        source.write_bytes(b"abcdefgh")
        with patch.object(Path, "stat", return_value=initial), self.assertRaises(ValueError):
            tool.read_limited(source, 4)
        source.write_bytes(b"")
        self.assertEqual(tool.read_limited(source, 0), b"")

    def test_package_entry_points(self):
        metadata = tomllib.loads(Path(__file__).with_name("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["name"], "dgn-explorer")
        self.assertEqual(metadata["project"]["scripts"], {
            "dgn-explorer": "dgn_folder:main",
            "dgn-workspace": "dgn_folder:main",
        })
        self.assertTrue(callable(tool.main))

    def test_interaction_link_targets(self):
        url = ET.fromstring('<DgnLinkNode><NodeData><Handler>URLLink</Handler><Name>url</Name></NodeData><HandlerData><URLLink xmlns="BentleyDesignLinksPersistence.01.02"><URL>https://old.invalid/</URL></URLLink></HandlerData></DgnLinkNode>')
        self.assertEqual(fixtures.retarget_link_xml(url), "url")
        self.assertEqual(url.findtext("HandlerData/{*}URLLink/{*}URL"), fixtures.SAMPLE_URL)
        file = ET.fromstring('<DgnLinkNode><NodeData><Handler>FileLink</Handler></NodeData><HandlerData><FileLink xmlns="BentleyDesignLinksPersistence.01.00"><Moniker>&lt;MSDocMoniker&gt;&lt;FileName&gt;old.doc&lt;/FileName&gt;&lt;FullPath&gt;C:\\old.doc&lt;/FullPath&gt;&lt;/MSDocMoniker&gt;</Moniker></FileLink></HandlerData></DgnLinkNode>')
        self.assertEqual(fixtures.retarget_link_xml(file), "file_link")
        moniker = ET.fromstring(file.findtext("HandlerData/{*}FileLink/{*}Moniker", ""))
        self.assertEqual(moniker.findtext("FileName"), Path(fixtures.SAMPLE_FILE).name)
        self.assertEqual(moniker.findtext("FullPath"), fixtures.SAMPLE_FILE)
        command = url.find("HandlerData/{*}URLLink/{*}URL")
        assert command is not None
        command.text = "ustnkeyin:TEST"
        self.assertIsNone(fixtures.retarget_link_xml(url))
        self.assertEqual(command.text, "ustnkeyin:TEST")

    def test_placeholder_link_choices(self):
        choices = tool.field_choices()
        self.assertEqual(len(choices["link_types"]), 15)
        labels = [item["label"] for item in choices["link_types"]]
        self.assertEqual(len(set(labels)), 15)
        self.assertIn("File Link", labels)
        self.assertIn("URL or Key-in", labels)
        file_link = next(item for item in choices["link_types"] if item["label"] == "File Link")
        self.assertEqual(file_link["ancestor_key"], "File")
        self.assertEqual(file_link["classes"], ["FileLinkProperties"])

    def test_geometry_records(self):
        for dimensions in (2, 3):
            line = struct.pack("<" + "d" * (dimensions * 2), *range(dimensions * 2))
            view = tool.geometry_view(line, 3, dimensions == 3)
            assert view is not None
            self.assertEqual(tool.view_bytes(view), line)
            view["end"][0] = 123.5
            self.assertEqual(struct.unpack_from("<d", tool.view_bytes(view), dimensions * 8)[0], 123.5)
            points = [[float(index)] * dimensions for index in range(3)]
            raw = struct.pack("<2I", len(points), 0) + b"".join(struct.pack("<" + "d" * dimensions, *point) for point in points)
            view = tool.geometry_view(raw, 4, dimensions == 3)
            assert view is not None
            self.assertEqual(tool.view_bytes(view), raw)
            view["points"].append([4.0] * dimensions)
            self.assertEqual(struct.unpack_from("<I", tool.view_bytes(view))[0], 4)
        core = struct.pack("<7d", 0.1, 0.2, 10, 20, 0.3, 30, 40)
        view = tool.geometry_view(core, 16, False)
        assert view is not None
        self.assertEqual(tool.view_bytes(view), core)
        view["origin"] = [100.0, 200.0]
        self.assertEqual(struct.unpack_from("<2d", tool.view_bytes(view), 40), (100.0, 200.0))

    def test_string_linkage_resizing(self):
        value = b"\xff\xfe\x01\x00sample.dgn"
        payload = struct.pack("<2HI", 3, 0, len(value)) + value
        padded = payload + b"\0" * (-(4 + len(payload)) % 8)
        original = struct.pack("<2H", 0x1000 | ((len(padded) + 4) // 2 - 1), 0x56D2) + padded
        view = tool.linkages_view(original)
        self.assertEqual(tool.view_bytes(view), original)
        linkage = view["records"][0]["payload"]
        self.assertEqual(linkage["key_name"], "FileName")
        for text in ("edited.dgn", "x" * 700):
            linkage["string"]["text"] = text
            encoded = tool.view_bytes(view)
            decoded = tool.linkages_view(encoded)
            self.assertEqual(decoded["records"][0]["payload"]["string"]["text"], text)
            self.assertEqual(tool.view_bytes(decoded), encoded)
        linkage["key"] = 62
        with self.assertRaises(ValueError):
            tool.view_bytes(view)

    def test_fixed_feature_headers(self):
        original = struct.pack("<4IQ", 2, 1, 3, 4, 123456) + b"preserved-extra-data"
        view = tool.record_core_view(original, 100, 0, False)
        assert view is not None
        self.assertEqual(tool.view_bytes(view), original)
        view["fields"]["group_id"] = 99
        self.assertEqual(struct.unpack_from("<I", tool.view_bytes(view), 8)[0], 99)
        view["fields"]["component_count"] = 10
        with self.assertRaises(ValueError):
            tool.view_bytes(view)
        core = b"TEST COMMAND\0" + b"\0" * (476 - 13)
        view = tool.record_core_view(core, 66, 10, True)
        assert view is not None
        self.assertEqual(tool.view_bytes(view), core)
        view["command"] = "TEST EDITED"
        self.assertEqual(tool.view_bytes(view)[:12], b"TEST EDITED\0")

    def test_varichar_modes(self):
        samples = [b"\xff\xfe\x01\x00TEST ME", b"\xff\xfe" + "Wide text \u03a9".encode("utf-16-le"), b"ASCII glyph codes"]
        for raw in samples:
            view = tool.varichar_view(raw)
            self.assertEqual(tool.view_bytes(view), raw)
        view = tool.varichar_view(samples[0])
        view["text"] = "Edited \u03a9"
        self.assertEqual(tool.view_bytes(view), b"\xff\xfe" + view["text"].encode("utf-16-le"))
        view = tool.varichar_view(samples[2])
        view["text"] = "Unmapped \u03a9"
        with self.assertRaises(ValueError):
            tool.view_bytes(view)

    def test_text_encodings(self):
        samples = [b"hello\r\nworld", b'{"value": 3}', b"<root>hello</root>", "<root>hello</root>".encode("utf-16"), b"\xef\xbb\xbfhello", "plain wide string".encode("utf-16-le"), "plain wide string".encode("utf-16-be"), b"\xfe\xff" + "<root>\u03a9</root>".encode("utf-16-be")]
        for data in samples:
            with self.subTest(data=data):
                view = tool.text_view(data)
                self.assertIsNotNone(view)
                assert view is not None
                self.assertEqual(tool.view_bytes(view), data)

    def test_utf8_content_and_automatic_terminators(self):
        text = "<root>\u03a9</root>"
        raw = b"\xfe\xff" + text.encode("utf-16-be") + b"\0\0"
        view = tool.attribute_payload_view(raw, 1024)
        self.assertEqual(view["kind"], "terminated-text")
        self.assertEqual(tool.view_bytes(view), raw)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            tool.externalize_text(folder, "wide", view)
            path = next((folder / "content").rglob("*.xml"))
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))
            self.assertNotIn(b"\0", path.read_bytes())
            path.write_text("<root>changed \u03a9</root>", encoding="utf-8")
            tool.hydrate_text(folder, view, 1024)
            self.assertEqual(tool.view_bytes(view), b"\xfe\xff" + "<root>changed \u03a9</root>".encode("utf-16-be") + b"\0\0")

    def test_utf32_roundtrip_and_unicode_escapes(self):
        for encoding, bom in (("utf-32-le", b"\xff\xfe\0\0"), ("utf-32-be", b"\0\0\xfe\xff")):
            for prefix in (b"", bom):
                with self.subTest(encoding=encoding, bom=prefix):
                    raw = prefix + "<root>hello</root>".encode(encoding)
                    view = tool.text_view(raw)
                    assert view is not None
                    self.assertEqual(view["encoding"], encoding)
                    self.assertEqual(tool.view_bytes(view), raw)
                    view["text"] = json.loads('"changed \\u03a9 \\ud83d\\ude00"')
                    view["kind"] = "text"
                    self.assertEqual(tool.view_bytes(view), prefix + view["text"].encode(encoding))
                    terminated = tool.attribute_payload_view(raw + b"\0" * 4, 1024)
                    self.assertEqual(terminated["kind"], "terminated-text")
                    self.assertEqual(tool.view_bytes(terminated), raw + b"\0" * 4)
        self.assertIsNone(tool.text_view(b"\xff\xfe\0\0\x00\xd8\0\0"))

    def test_nested_compressed_xml_resizing(self):
        xml = b"<root>value</root>\0"
        raw = struct.pack("<2HI", 3, 0, len(xml)) + zlib.compress(xml, 1)
        view = tool.attribute_payload_view(raw, tool.DEFAULT_LIMIT)
        self.assertEqual(tool.view_bytes(view), raw)
        view["payload"]["payload"]["text"] = "<root>much longer edited value</root>"
        rebuilt = tool.view_bytes(view)
        actual = zlib.decompress(rebuilt[8:])
        self.assertEqual(actual, b"<root>much longer edited value</root>\0")
        self.assertEqual(struct.unpack_from("<I", rebuilt, 4)[0], len(actual))

    def test_chunk_length_recalculation(self):
        raw = struct.pack("<I2HI", 0, 66, 128, 6) + b"abcd"
        view = tool.element_chunks_view(raw)
        assert view is not None
        self.assertEqual(tool.view_bytes(view), raw)
        view["chunks"][0]["body"]["hex_rows"] = [b"abcdefgh".hex()]
        self.assertEqual(struct.unpack_from("<I", tool.view_bytes(view), 8)[0], 8)
        view["chunks"][0]["body"]["hex_rows"] = ["01"]
        with self.assertRaises(ValueError):
            tool.view_bytes(view)

    def test_uncompressed_block_framing(self):
        prefix = struct.pack("<4I", 1, 1, 0, 0)
        payload = struct.pack("<I2HI", 0, 66, 0, 6) + b"abcd"
        self.assertEqual(tool.decode_stream(["Dgn^Nm", "$1"], prefix + payload, 1024), ("framed-raw", payload, prefix, b""))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            view = tool.element_chunks_view(payload)
            assert view is not None
            tool.write_view(folder / "payload.json", view)
            tool.write_view(folder / "prefix.json", {"kind": "dgn-block-header", "num_entries": 1, "flags": 1, "reserved": [0, 0]})
            tool.write_view(folder / "suffix.json", tool.binary_view(b""))
            entry = {"ole_path": ["Dgn^Nm", "$1"], "file": "payload.json", "representation": "json-view", "prefix": "prefix.json", "prefix_representation": "json-view", "suffix": "suffix.json", "suffix_representation": "json-view", "codec": "framed-raw"}
            self.assertEqual(tool.encode_stream(folder, entry, prefix + payload, 1024), prefix + payload)

    def test_opaque_and_framing_views(self):
        for data in (b"", bytes(range(256))):
            self.assertEqual(tool.view_bytes(tool.binary_view(data)), data)
        view = {"kind": "dgn-block-header", "num_entries": 5, "flags": 3, "reserved": [0, 0]}
        self.assertEqual(tool.view_bytes(view), struct.pack("<4I", 5, 3, 0, 0))

    def test_workspace_paths_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bytes.json"
            tool.write_view(path, {"payload": tool.binary_view(bytes(range(256)))}, "escaped")
            saved = path.read_text(encoding="utf-8")
            self.assertIn("\\u0000", saved)
            self.assertIn("\\u00ff", saved)
            self.assertEqual(tool.view_bytes(json.loads(saved)["payload"]), bytes(range(256)))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("../escape", "C:/escape"):
                with self.assertRaises(ValueError):
                    tool.inside(root, relative)
            path = root / "legacy.bin"
            path.write_bytes(b"legacy binary workspace")
            self.assertEqual(tool.read_view(root, "legacy.bin", None, 1024), path.read_bytes())
        with self.assertRaises(ValueError):
            tool.inflate(zlib.compress(b"x" * 10000), 100)

    def test_escaped_byte_strings(self):
        for raw in (b"", bytes(range(256)), b'quoted "text" \\ \0\r\n', "wide \u03a9".encode("utf-16-le"), "wide \u03a9".encode("utf-32-be")):
            with self.subTest(raw=raw):
                view = tool.readable_bytes(tool.binary_view(raw))
                self.assertEqual(view["kind"], "byte-string")
                self.assertEqual(tool.view_bytes(view), raw)
                self.assertEqual(tool.binary_bytes(json.loads(json.dumps(view, ensure_ascii=True))), raw)
        view = tool.readable_bytes(tool.binary_view(bytes(range(256))))
        view["text"] = "\u03a9"
        with self.assertRaises(UnicodeEncodeError):
            tool.view_bytes(view)
        view["encoding"] = "unknown-codec"
        with self.assertRaises(ValueError):
            tool.view_bytes(view)

    def test_edit_contract_and_readonly_labels(self):
        raw = struct.pack("<I", 3)
        view = tool.record_core_view(raw, 12, 0, False)
        assert view is not None
        self.assertEqual(tool.editing_contract(view)["access"], "ro")
        raw = struct.pack("<4IQ", 2, 1, 3, 4, 123456)
        view = tool.record_core_view(raw, 100, 0, False)
        assert view is not None
        contract = tool.editing_contract(view)
        self.assertEqual(contract["access"], "rw")
        self.assertIn("/fields/group_id", contract["editable_fields"])
        self.assertIn("/fields/component_count", contract["read_only_fields"])
        self.assertIn("/original", contract["read_only_fields"])
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            tool.write_view(folder / "framing" / "empty.json", tool.readable_bytes(tool.binary_view(b"")))
            tool.write_view(folder / "objects" / "fixed.json", view)
            manifest = {"format": tool.FORMAT, "streams": [], "storages": []}
            tool.write_view(folder / "manifest.json", manifest)
            tool.label_workspace_files(folder, manifest)
            self.assertTrue((folder / "framing" / "empty.ro.json").exists())
            self.assertTrue((folder / "objects" / "fixed.rw.json").exists())
            self.assertEqual(json.loads((folder / "objects" / "fixed.rw.json").read_text())["editing"], contract)
            names = {path.relative_to(folder) for path in folder.rglob("*")}
            tool.label_workspace_files(folder, manifest)
            self.assertEqual(names, {path.relative_to(folder) for path in folder.rglob("*")})

    def test_readonly_framing_rejected(self):
        raw = zlib.compress(b"hello")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            tool.write_view(folder / "data.rw.json", tool.text_view(b"hello"))
            tool.write_view(folder / "prefix.ro.json", tool.binary_view(b""))
            tool.write_view(folder / "suffix.ro.json", tool.binary_view(b"extra"))
            entry = {"ole_path": ["plain"], "file": "data.rw.json", "representation": "json-view", "prefix": "prefix.ro.json", "suffix": "suffix.ro.json", "prefix_representation": "json-view", "suffix_representation": "json-view", "codec": "zlib"}
            with self.assertRaisesRegex(ValueError, "Read-only framing"):
                tool.encode_stream(folder, entry, raw, 1024)


class SpecificationFeatureTests(unittest.TestCase):
    def test_declared_catalogue_and_unknown_numbers(self):
        for number in (1, 2, 3, 33, 34, 35, 37, 38, 39, 87, 88, 94, 95, 96, 105, 110, 113, 182):
            self.assertIn(number, tool.ELEMENT_TYPES)
        for number in (20, 29, 40, 89, 104, 109, 114, 128):
            self.assertNotIn(number, tool.ELEMENT_TYPES)
        self.assertEqual(tool.ELEMENT_TYPES[26], "B-spline knots")
        self.assertEqual(tool.ELEMENT_TYPES[28], "B-spline weights")

    def test_framing_headers_and_index_are_passive_and_lossless(self):
        streams = feature_streams()
        cases = [(tool.design_header_view, bytes(1576) + b"tail"),
                 (tool.model_header_view, streams[("Dgn-Md", "#000001", "Dgn~Mh")] + b"model"),
                 (tool.model_index_view, streams[("Dgn^Ix", "Dgn~Mix")])]
        for decoder, raw in cases:
            with self.subTest(decoder=decoder.__name__):
                view = decoder(raw)
                self.assertIsNotNone(view)
                self.assertEqual(tool.view_bytes(view), raw)
                self.assertEqual(tool.view_bytes(tool.readable_bytes(view)), raw)
                self.assertEqual(tool.editing_contract(view)["editable_fields"], [])
        index = tool.model_index_view(cases[-1][1])
        self.assertEqual([item["name"] for item in index["items"]], ["Model 1", "Model 2"])
        index["items"][0]["name"] = "Changed"
        with self.assertRaises(ValueError):
            tool.view_bytes(index)
        self.assertIsNone(tool.design_header_view(bytes(1575)))
        self.assertIsNone(tool.model_header_view(bytes(4095)))
        self.assertIsNone(tool.model_index_view(bytes(16)))

    def test_model_index_bounds_versions_and_extensions(self):
        raw = feature_streams()[("Dgn^Ix", "Dgn~Mix")]
        extra = raw[:12] + struct.pack("<I", 4) + b"keep" + raw[16:]
        view = tool.model_index_view(extra)
        self.assertTrue(view["complete"])
        self.assertEqual(tool.view_bytes(view), extra)
        for malformed in (raw[:-1], raw[:8] + struct.pack("<I", 1000) + raw[12:],
                          raw[:32] + struct.pack("<H", 1) + raw[34:]):
            with self.subTest(malformed=malformed[:20]):
                view = tool.model_index_view(malformed)
                self.assertFalse(view["complete"])
                self.assertEqual(tool.view_bytes(view), malformed)
        unsupported = raw[:4] + struct.pack("<I", 3) + raw[8:]
        self.assertIn("Unsupported", tool.model_index_view(unsupported)["diagnostic"])

    def test_file_header_uncompressed_and_encrypted_dispatch(self):
        prefix = struct.pack("<2H4I", 0, 4, 1, 2, 3, 4)
        raw = prefix + bytes(1576)
        self.assertEqual(tool.decode_stream(["Dgn~H"], raw, 2000), ("framed-raw", bytes(1576), prefix, b""))
        for flags in (1, 2, 3):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                tool.decode_stream(["Dgn~H"], struct.pack("<H", flags) + raw[2:], 2000)
        encrypted = struct.pack("<4I", 1, 4, 0, 0) + b"encrypted"
        self.assertEqual(tool.decode_stream(["Dgn-Md", "#1", "Dgn^G", "$1"], encrypted, 2000), ("raw", encrypted, b"", b""))

    def test_every_feature_fixture_element_roundtrips_without_edits(self):
        raw = feature_streams()[("Dgn-Md", "#000001", "Dgn^G", "$2")][16:]
        view = tool.element_chunks_view(raw)
        self.assertEqual(tool.view_bytes(view), raw)
        self.assertEqual(tool.view_bytes(tool.readable_bytes(view)), raw)
        kinds = {chunk["body"].get("core", {}).get("kind") for chunk in view["chunks"]}
        self.assertTrue({"dgn-tag", "dgn-table-entry", "dgn-matrix", "dgn-store", "dgn-gcs"} <= kinds)
        for chunk in view["chunks"]:
            body = chunk["body"]
            if body.get("core", {}).get("kind") in tool.PASSIVE_KINDS:
                self.assertFalse(any(pointer.startswith("/core/") for pointer in tool.editing_contract(body)["editable_fields"]))

    def test_unknown_chunk_signature_is_not_a_live_element(self):
        raw = element_chunk(3, struct.pack("<4d", 0, 0, 1, 1), graphics=True)
        raw = struct.pack("<I", 0xABCD) + raw[4:]
        view = tool.element_chunks_view(raw)
        self.assertEqual(view["chunks"][0]["body"]["kind"], "opaque-bytes")
        self.assertEqual(tool.view_bytes(view), raw)

    def test_metadata_table_routing_and_font_replacements(self):
        for level, name in tool.TABLE_LEVELS.items():
            with self.subTest(level=level):
                raw = struct.pack("<2I", 1, 0)
                view = tool.table_record_view(raw, 95, level)
                self.assertEqual(view["table_name"], name)
                self.assertEqual(tool.view_bytes(view), raw)
                header = tool.table_record_view(raw, 96, level)
                self.assertEqual(tool.editing_contract(header)["editable_fields"], [])
        raw_name = "Font Ω".encode("utf-16-le")
        raw = struct.pack("<3IH", 7, 0, 3, len(raw_name)) + raw_name
        view = tool.table_record_view(raw, 95, 2)
        view["name"] = "Different 😀"
        encoded = tool.view_bytes(tool.readable_bytes(view))
        self.assertEqual(tool.table_record_view(encoded, 95, 2)["name"], "Different 😀")
        view["entry_id"] = 8
        with self.assertRaises(ValueError):
            tool.view_bytes(view)
        self.assertNotIn("parent_id", tool.table_record_view(bytes(8), 95, 9))
        self.assertNotIn("entry_id", tool.table_record_view(bytes(68), 95, 10))
        name = "Font\0\0".encode("utf-16-le")
        view = tool.table_record_view(struct.pack("<3IH", 1, 0, 2, len(name)) + name, 95, 2)
        self.assertEqual(view["terminator_count"], 2)
        view["name"] = "Changed"
        self.assertEqual(tool.view_bytes(view)[-4:], bytes(4))

    def test_tag_scalar_replacements_and_unknown_options(self):
        for data_type, format, before, after in ((2, "h", 42, -12), (3, "i", 123, 456), (4, "d", 1.5, 2.25)):
            core = bytearray(192)
            struct.pack_into("<H", core, 24, 3)
            struct.pack_into("<2H", core, 80, 5, data_type)
            value = struct.pack("<" + format, before)
            struct.pack_into("<2Hi", core, 184, len(value), 0, 1252)
            raw = bytes(core) + value + b"tail"
            view = tool.tag_view(raw)
            self.assertEqual(tool.view_bytes(view), raw)
            view["value"] = after
            encoded = tool.view_bytes(view)
            self.assertEqual(tool.tag_view(encoded)["value"], after)
            self.assertTrue(encoded.endswith(b"tail"))
            view["definition_id"] = 99
            with self.assertRaises(ValueError):
                tool.view_bytes(view)
        raw = bytearray(core)
        raw[179] = 1
        raw += value
        self.assertEqual(tool.editing_contract(tool.tag_view(bytes(raw)))["editable_fields"], [])

    def test_linkage_masks_symbology_dependency_and_building_labels(self):
        payloads = [(22227, struct.pack("<2H2I2H", 7, 1, 17, 2, 0xA55A, 0xFF01), "dgn-bitmask"),
                    (22288, struct.pack("<4H2IH", 7, 2, 1, 0, 3, 1, 0x39), "dgn-multistate-mask"),
                    (22241, struct.pack("<2Hi3I", 7, 3, -1, 2, 3, 4), "dgn-symbology")]
        for primary, payload, kind in payloads:
            raw = user_linkage(primary, payload)
            view = tool.linkages_view(raw)
            self.assertEqual(view["records"][0]["payload"]["kind"], kind)
            self.assertEqual(tool.view_bytes(tool.readable_bytes(view)), raw)
            expected = ["/records/0/primary_id", "/records/0/header_flags"]
            if primary == 22241:
                expected.append("/records/0/payload/weight")
            self.assertEqual(tool.editing_contract(view)["editable_fields"], expected)
        for root_type, size in ((0, 8), (1, 16), (2, 40), (3, 48), (4, 16), (5, 24), (6, 12), (7, 24), (8, 16)):
            with self.subTest(root_type=root_type):
                raw = user_linkage(22224, struct.pack("<4H", 5, 6, root_type << 10, 1) + bytes(size))
                view = tool.linkages_view(raw)
                self.assertEqual(view["records"][0]["payload"]["root_type"], root_type)
                self.assertEqual(tool.view_bytes(view), raw)
        for primary in (48640, 48750, 48800, 48903, 48979):
            raw = user_linkage(primary, b"opaque")
            self.assertNotEqual(tool.linkages_view(raw)["records"][0]["primary_name"], "Unknown")
            self.assertEqual(tool.view_bytes(tool.linkages_view(raw)), raw)

    def test_symbology_weight_and_nonfinite_dependency_fidelity(self):
        raw = user_linkage(22241, struct.pack("<2Hi3I", 1, 2, -1, 3, 4, 5))
        view = tool.linkages_view(raw)
        payload = view["records"][0]["payload"]
        payload["weight"] = 31
        edited = tool.view_bytes(view)
        self.assertEqual(tool.linkages_view(edited)["records"][0]["payload"]["weight"], 31)
        for invalid in (-1, 32, True, 1.5):
            payload["weight"] = invalid
            with self.subTest(weight=invalid), self.assertRaises(ValueError):
                tool.view_bytes(view)
        payload["weight"], payload["color"] = 3, 99
        with self.assertRaises(ValueError):
            tool.view_bytes(view)
        dependency = user_linkage(22224, struct.pack("<4HQd", 1, 2, 1 << 10, 1, 123, float("nan")))
        self.assertEqual(tool.view_bytes(tool.linkages_view(dependency)), dependency)
        self.assertEqual(tool.linkages_view(dependency)["records"][0]["payload"]["application_value"], 2)
        json.dumps(tool.linkages_view(dependency), allow_nan=False)

    def test_xml_fragment_cross_platform_counts_compression_and_edits(self):
        for compression in (1, 2):
            for inaccurate in (False, True):
                with self.subTest(compression=compression, inaccurate=inaccurate):
                    raw = xml_fragment("<DataGroup><Value>Ω 😀</Value></DataGroup>", compression=compression,
                                       inaccurate_counts=inaccurate, tail=b"\0\0")
                    view = tool.xml_fragment_view(raw, 4096)
                    self.assertEqual(view["schema_urn"], "urn:synthetic:schema")
                    self.assertEqual(tool.view_bytes(view), raw)
                    self.assertEqual(tool.view_bytes(tool.readable_bytes(view)), raw)
                    view["payload"]["text"] = "<DataGroup><Value>Changed Ω</Value></DataGroup>"
                    encoded = tool.view_bytes(tool.readable_bytes(view))
                    self.assertEqual(tool.xml_fragment_view(encoded)["payload"]["text"], view["payload"]["text"])
                    self.assertEqual(tool.view_bytes(tool.xml_fragment_view(encoded)), encoded)
                    view["schema_urn"] = "urn:changed"
                    with self.assertRaises(ValueError):
                        tool.view_bytes(view)

    def test_xml_fragment_invalid_extents_and_identity_replacements(self):
        raw = xml_fragment('<DataGroup catalogItem="Identity"><Value>Text</Value></DataGroup>')
        for invalid in (raw[:-3], struct.pack("<2i", 1, -1) + raw[8:], raw[:12] + struct.pack("<i", -1) + raw[16:]):
            self.assertIsNone(tool.xml_fragment_view(invalid))
        with self.assertRaises(ValueError):
            compressed = xml_fragment("<root>" + "x" * 10000 + "</root>", compression=2)
            tool.xml_fragment_view(compressed[:4] + struct.pack("<i", 100) + compressed[8:], 1000)
        view = tool.xml_fragment_view(raw)
        for changed in ('<DataGroup catalogItem="Changed"><Value>Text</Value></DataGroup>',
                        '<DataGroup catalogItem="Identity"><Other>Text</Other></DataGroup>'):
            view["payload"]["text"] = changed
            with self.assertRaises(ValueError):
                tool.view_bytes(view)
        view = tool.xml_fragment_view(xml_fragment("<root>Old</root>", tail=b"reserved"))
        view["payload"]["text"] = "<root>New</root>"
        self.assertTrue(tool.view_bytes(view).endswith(b"reserved"))
        view["payload"]["text"] = "<root>A longer value</root>"
        with self.assertRaises(ValueError):
            tool.view_bytes(view)

    def test_tagged_count_widths_and_rejection(self):
        for value in (0, 239, 240, 255, 256, 32767, 32768, 1_000_000):
            cursor = tool.BinaryCursor(tagged_count(value))
            self.assertEqual(cursor.count(), value)
            self.assertEqual(cursor.offset, len(cursor.data))
        for raw in (b"\xf0", b"\xf1", b"\xf2\xff\xff", b"\xf3\xff\xff\xff\xff", b"\xf4" + bytes(8)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                tool.BinaryCursor(raw).count()
        with self.assertRaises(ValueError):
            tool.BinaryCursor(b"\x40", 10).count()

    def test_becxml_string8_is_low_byte_unicode_and_string16_counts_units(self):
        for text, wide in (("café", False), ("Ω 😀", True), ("x" * 300, False)):
            raw = becxml_document(text, wide=wide)
            view = tool.becxml_view(raw)
            self.assertTrue(view["complete"], view.get("diagnostic"))
            self.assertEqual(view["strings"][1]["value"], text)
            self.assertEqual(tool.becxml_bytes(view), raw)
            self.assertEqual(tool.becxml_bytes(tool.readable_bytes(view)), raw)
            view["strings"][1]["value"] = "Changed"
            with self.assertRaises(ValueError):
                tool.becxml_bytes(view)

    def test_becxml_typed_values_arrays_attributes_and_unsupported_tokens(self):
        prefix = tool.BECXML_MAGIC + b"\1\0\0\3\0\0" + b"\x30\2\xfa\4Root\xfa\4attr"
        values = [b"\xf0\1", b"\xf1\xff", b"\xf2" + struct.pack("<h", -1),
                  b"\xf3" + struct.pack("<i", -2), b"\xf4" + struct.pack("<q", -3),
                  b"\xf5" + struct.pack("<2d", 1, 2), b"\xf6\2\x00\xff",
                  b"\xf7" + struct.pack("<d", 1.5), b"\xf8" + struct.pack("<q", 123),
                  b"\xf9" + struct.pack("<3d", 1, 2, 3), b"\xfa\4caf\xe9",
                  b"\xfb\1\xa9\x03", b"\xfc\1", b"\xfd\xf7\2" + struct.pack("<2d", 1, 2),
                  b"\xfe\xf2\2" + struct.pack("<2h", 0, -1)]
        raw = prefix + b"\3\0\5\1\x11\1\6" + b"".join(b"\x10" + value for value in values) + b"\4"
        view = tool.becxml_view(raw)
        self.assertTrue(view["complete"], view.get("diagnostic"))
        self.assertEqual(len([token for token in view["tokens"] if token["code"] == 0x10]), 15)
        self.assertEqual(tool.view_bytes(view), raw)
        for ending in (b"\x20", b"\x32", b"\x04", b"\x10\xf0\2", b"\x10\xfb\1\x00\xd8"):
            malformed = prefix + ending
            view = tool.becxml_view(malformed)
            self.assertFalse(view["complete"])
            self.assertEqual(tool.view_bytes(view), malformed)

    def test_ecxd_headers_and_external_ec_schema_prefix(self):
        for flags in (0, 1, 2, 31):
            raw = struct.pack("<3H2B", 1, 2, 3, flags, 0xAA)
            if flags & 1:
                raw += struct.pack("<2I", 5, 6)
            raw += b"opaque"
            view = tool.ecxd_view(raw)
            self.assertEqual(view["provider_id"], 3)
            self.assertEqual(tool.view_bytes(view), raw)
            view["schema_index"] = 4
            with self.assertRaises(ValueError):
                tool.view_bytes(view)
        self.assertIsNone(tool.ecxd_view(struct.pack("<3H2B", 1, 2, 3, 1, 0)))
        handler = 22271 << 16 | 1
        raw = struct.pack("<I", 0x01010000) + "Schema\0".encode("utf-16-le") + struct.pack("<2I", 1, 2) + becxml_document()
        view = tool.attribute_payload_view(raw, 4096, handler)
        self.assertEqual(view["schema_name"], "Schema")
        self.assertTrue(view["payload"]["complete"])
        self.assertEqual(tool.view_bytes(view), raw)

    def test_dgnstore_assembly_sequences_sizes_and_checksum(self):
        raw = feature_streams()[("Dgn-Md", "#000001", "Dgn^G", "$2")][16:]
        view = tool.element_chunks_view(raw)
        header = next(chunk for chunk in view["chunks"] if chunk["element_type"] == 39)
        assembly = header["body"]["store_assembly"]
        self.assertTrue(assembly["complete"])
        self.assertTrue(assembly["checksum_verified"])
        self.assertEqual(assembly["payload"]["payload"]["text"], "<DataGroup><Value>Original</Value></DataGroup>")
        for key in ("checksum", "total_size", "component_count"):
            modified = deepcopy(view["chunks"])
            target = next(chunk for chunk in modified if chunk["element_type"] == 39)
            target["body"]["core"][key] += 1
            self.assertFalse(tool.assembled_stores(modified)[0]["complete"])
        self.assertEqual(tool.dgn_store_checksum(b"\1\2\3\4"), 0x04030201)

    def test_matrices_preserve_unused_capacity_and_reject_bad_counts(self):
        for element_type, format in ((102, "i"), (103, "d")):
            raw = bytes(72) + struct.pack("<4I", 4, 3, 0x20, 0xAA) + struct.pack("<" + format * 4, 1, 2, 3, 999)
            view = tool.matrix_view(raw, element_type)
            self.assertEqual(view["values"], [1, 2, 3])
            self.assertEqual(tool.view_bytes(view), raw)
            view["values"][0] = 10
            with self.assertRaises(ValueError):
                tool.view_bytes(view)
            self.assertIsNone(tool.matrix_view(raw[:76] + struct.pack("<I", 5) + raw[80:], element_type))

    def test_gcs_signature_and_metadata_are_passive(self):
        raw = feature_streams()[("Dgn-Md", "#000001", "Dgn^G", "$2")][16:]
        view = tool.element_chunks_view(raw)
        record = next(chunk["body"] for chunk in view["chunks"] if chunk["body"].get("core", {}).get("kind") == "dgn-gcs")
        self.assertEqual(record["core"]["coordinate_system"], "WGS84")
        self.assertEqual(record["type_name"], "Geographic coordinate system")
        self.assertEqual(record["core"]["minor_version"], 4000)
        record["core"]["coordinate_system"] = "Changed"
        with self.assertRaises(ValueError):
            tool.view_bytes(record)


@unittest.skipUnless(SAMPLE.exists(), "User-provided sample DGN is unavailable")
class SampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dgn-folder-tests-")
        self.root = Path(self.temporary.name)
        self.folder = self.root / "unpacked"
        self.manifest = tool.extract(SAMPLE, self.folder, tool.DEFAULT_LIMIT)

    def tearDown(self):
        self.temporary.cleanup()

    def test_byte_identical_rebuild(self):
        output = self.root / "noop.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 0)
        self.assertEqual(output.read_bytes(), SAMPLE.read_bytes())
        self.assertGreater(len(list((self.folder / "content").rglob("*.xml"))), 0)

    def test_access_markers_and_complete_writable_index(self):
        self.assertTrue((self.folder / "manifest.rw.json").exists())
        guide = (self.folder / "WRITABLE.ro.md").read_text(encoding="utf-8")
        index = json.loads((self.folder / self.manifest["writable_index"]).read_text(encoding="utf-8"))
        listed = {item["file"] for item in index["files"]}
        actual = {path.relative_to(self.folder).as_posix() for path in self.folder.rglob("*") if path.is_file() and ".rw." in path.name}
        self.assertEqual(listed, actual)
        self.assertTrue(all((self.folder / filename).exists() for filename in listed))
        for filename in listed:
            self.assertIn(f"[{filename}]", guide)
        for key in ("objects_index", "field_choices", "object_choices"):
            self.assertTrue(self.manifest[key].endswith(".ro.json"))
            self.assertNotIn(self.manifest[key], listed)
        self.assertTrue(any(item.get("inline_object_pointers") for item in index["files"]))
        for path in self.folder.rglob("*.json"):
            self.assertTrue(path.name.endswith((".ro.json", ".rw.json")), path)
        inventory = json.loads((self.folder / self.manifest["objects_index"]).read_text(encoding="utf-8"))
        item = next(item for item in inventory["objects"] if item["kind"] == "dgn-text-element")
        self.assertIn(item["file"], listed)
        path = self.folder / item["file"]
        obj = json.loads(path.read_text(encoding="utf-8"))
        obj["string"]["text"] = "RW INDEX EDIT"
        tool.write_view(path, obj)
        output = self.root / "index-edited.dgn"
        self.assertGreater(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 0)
        result_folder = self.root / "index-reextracted"
        result = tool.extract(output, result_folder, tool.DEFAULT_LIMIT)
        objects = json.loads((result_folder / result["objects_index"]).read_text(encoding="utf-8"))["objects"]
        self.assertTrue(any(obj.get("text_preview") == "RW INDEX EDIT" for obj in objects))

    def test_legacy_unlabelled_workspace_rebuild(self):
        folder = self.root / "legacy"
        tool.extract(SAMPLE, folder, tool.DEFAULT_LIMIT, bytes_mode="hex", labels=False)
        legacy_manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        legacy_manifest["format"] = "dgn-folder-v1"
        tool.write_view(folder / "manifest.json", legacy_manifest)
        self.assertTrue((folder / "manifest.json").exists())
        self.assertTrue((folder / "objects" / "index.json").exists())
        output = self.root / "legacy-repacked.dgn"
        self.assertEqual(tool.rebuild(folder, output, tool.DEFAULT_LIMIT), 0)
        self.assertEqual(output.read_bytes(), SAMPLE.read_bytes())
        manifest = tool.load_manifest(folder)
        note = folder / "user-note.txt"
        note.write_text("Keep my note", encoding="utf-8")
        content = {path.read_bytes() for path in (folder / "content").rglob("*") if path.is_file()}
        tool.label_workspace_files(folder, manifest)
        names = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
        tool.label_workspace_files(folder, manifest)
        self.assertEqual(names, {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()})
        self.assertEqual(note.read_text(encoding="utf-8"), "Keep my note")
        self.assertEqual(content, {path.read_bytes() for path in (folder / "content").rglob("*") if path.is_file()})
        migrated = self.root / "migrated.dgn"
        self.assertEqual(tool.rebuild(folder, migrated, tool.DEFAULT_LIMIT), 0)
        self.assertEqual(migrated.read_bytes(), output.read_bytes())

    def test_passive_object_inventory(self):
        inventory = tool.inspect_dgn(SAMPLE, tool.DEFAULT_LIMIT)
        self.assertEqual(inventory["sha256"], tool.file_digest(SAMPLE))
        self.assertEqual(inventory["stream_count"], 19)
        self.assertEqual(inventory["model_count"], 1)
        self.assertEqual(inventory["unparsed_element_streams"], [])
        model_types = {item["type"]: item["count"] for item in inventory["model_element_types"]}
        self.assertEqual(model_types[17], 6)
        self.assertEqual(model_types[7], 1)
        self.assertIn(35, model_types)
        self.assertGreater(len(inventory["string_linkage_keys"]), 0)

    def screenshot_objects(self):
        inventory = json.loads((self.folder / self.manifest["objects_index"]).read_text(encoding="utf-8"))
        path = ["Dgn-Md", "#000000", "Dgn^G", "$1"]
        objects = [item for item in inventory["objects"] if item["ole_path"] == path]
        node_item = next(item for item in objects if item["kind"] == "dgn-text-node")
        runs = sorted((item for item in objects if item["kind"] == "dgn-text-element"), key=lambda item: item["chunk_index"])
        return node_item, runs

    def test_screenshot_items_visible_and_unchanged_repack(self):
        node_item, runs = self.screenshot_objects()
        expected = ["TEST ME", "Test ", "https://bntl.ee/", " fdfdfd", "xxxx", "Link Name"]
        self.assertEqual([item["text_preview"] for item in runs], expected)
        actual = [json.loads((self.folder / item["file"]).read_text(encoding="utf-8"))["string"]["text"] for item in runs]
        self.assertEqual(actual, expected)
        self.assertEqual([actual[0], "".join(actual[1:4]), actual[4], actual[5]], ["TEST ME", "Test https://bntl.ee/ fdfdfd", "xxxx", "Link Name"])
        node = json.loads((self.folder / node_item["file"]).read_text(encoding="utf-8"))
        self.assertEqual(node["component_count"], 6)
        self.assertEqual([item["chunk_index"] for item in runs], list(range(node_item["chunk_index"] + 1, node_item["chunk_index"] + 7)))
        output = self.root / "screenshot-unchanged.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 0)
        self.assertEqual(output.read_bytes(), SAMPLE.read_bytes())

    def test_screenshot_all_runs_edit_geometry_preserved(self):
        node_item, runs = self.screenshot_objects()
        expected = ["TEST EDITED", "Edited ", "https://example.invalid/", " trailing edited text", "yyyyyyyy", "Edited Link Name"]
        for item, text in zip(runs, expected):
            path = self.folder / item["file"]
            view = json.loads(path.read_text(encoding="utf-8"))
            view["string"]["text"] = text
            tool.write_view(path, view)
        output = self.root / "screenshot-edited.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        graph_path = runs[0]["ole_path"]
        with tool.ole_reader().OleFileIO(str(SAMPLE)) as before, tool.ole_reader().OleFileIO(str(output)) as after:
            self.assertEqual(before.listdir(), after.listdir())
            for names in before.listdir():
                if names != graph_path:
                    self.assertEqual(before.openstream(names).read(), after.openstream(names).read(), names)
            old_raw = before.openstream(graph_path).read()
            new_raw = after.openstream(graph_path).read()
        self.assertEqual(old_raw[:16], new_raw[:16])
        old_payload = zlib.decompress(old_raw[16:])
        new_payload = zlib.decompress(new_raw[16:])

        def records(data):
            result = []
            position = 0
            while position < len(data):
                words = struct.unpack_from("<I", data, position + 8)[0]
                end = position + 4 + words * 2
                self.assertGreater(end, position)
                self.assertLessEqual(end, len(data))
                result.append(data[position:end])
                position = end
            return result

        old_records = records(old_payload)
        new_records = records(new_payload)
        self.assertEqual(len(old_records), len(new_records))
        edited_indexes = {item["chunk_index"] for item in runs}
        for index, (old_record, new_record) in enumerate(zip(old_records, new_records)):
            if index not in edited_indexes:
                self.assertEqual(old_record, new_record, f"Geometry/node record {index}")
        for item, text in zip(runs, expected):
            old_record = old_records[item["chunk_index"]]
            new_record = new_records[item["chunk_index"]]
            self.assertEqual(struct.unpack_from("<H", new_record, 4)[0], 17)
            self.assertTrue(struct.unpack_from("<H", new_record, 6)[0] & 0x4000)
            byte_count = struct.unpack_from("<H", new_record, 114)[0]
            string = new_record[206:206 + byte_count]
            self.assertEqual(string[:4], b"\xff\xfe\x01\x00")
            self.assertEqual(string[4:].decode("latin-1"), text)
            old_attr_offset = 4 + struct.unpack_from("<I", old_record, 12)[0] * 2
            new_attr_offset = 4 + struct.unpack_from("<I", new_record, 12)[0] * 2
            self.assertEqual(old_record[old_attr_offset:], new_record[new_attr_offset:])
            self.assertEqual(old_record[16:114], new_record[16:114])
        second = self.root / "screenshot-reextracted"
        tool.extract(output, second, tool.DEFAULT_LIMIT)
        for item, text in zip(runs, expected):
            view = json.loads((second / item["file"]).read_text(encoding="utf-8"))
            self.assertEqual(view["string"]["text"], text)

    def test_text_object_edit_and_linkage_preservation(self):
        inventory = json.loads((self.folder / self.manifest["objects_index"]).read_text(encoding="utf-8"))
        text_objects = [item for item in inventory["objects"] if item["kind"] == "dgn-text-element"]
        self.assertEqual(len(text_objects), 156)
        item = next(item for item in text_objects if item["text_preview"] == "TEST ME")
        path = self.folder / item["file"]
        view = json.loads(path.read_text(encoding="utf-8"))
        old_body = tool.binary_bytes(view["original"])
        old_attr_offset = struct.unpack_from("<I", old_body)[0] * 2 - 8
        old_linkages = old_body[old_attr_offset:]
        expected = "Longer manually edited text box \u03a9"
        view["string"]["text"] = expected
        tool.write_view(path, view)
        output = self.root / "text.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        second = self.root / "second"
        tool.extract(output, second, tool.DEFAULT_LIMIT)
        edited = json.loads((second / item["file"]).read_text(encoding="utf-8"))
        self.assertEqual(edited["string"]["text"], expected)
        new_body = tool.binary_bytes(edited["original"])
        new_attr_offset = struct.unpack_from("<I", new_body)[0] * 2 - 8
        self.assertEqual(new_body[new_attr_offset:], old_linkages)

    def test_text_node_and_origin_edit(self):
        inventory = json.loads((self.folder / self.manifest["objects_index"]).read_text(encoding="utf-8"))
        item = next(item for item in inventory["objects"] if item["kind"] == "dgn-text-node")
        path = self.folder / item["file"]
        view = json.loads(path.read_text(encoding="utf-8"))
        view["line_spacing"] *= 1.1
        view["origin"][0] += 10
        tool.write_view(path, view)
        output = self.root / "node.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        second = self.root / "second"
        tool.extract(output, second, tool.DEFAULT_LIMIT)
        edited = json.loads((second / item["file"]).read_text(encoding="utf-8"))
        self.assertEqual(edited["origin"], view["origin"])
        self.assertEqual(edited["line_spacing"], view["line_spacing"])

    def test_xml_edit_and_invalid_xml(self):
        xml = next((self.folder / "content").rglob("*.xml"))
        original = xml.read_bytes()
        xml.write_bytes(b"<invalid>")
        with self.assertRaises(Exception):
            tool.rebuild(self.folder, self.root / "invalid.dgn", tool.DEFAULT_LIMIT)
        self.assertFalse((self.root / "invalid.dgn").exists())
        edited = original.replace(b">", b"><!--manual-edit-test-->", 1)
        xml.write_bytes(edited)
        output = self.root / "edited.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        second = self.root / "second"
        tool.extract(output, second, tool.DEFAULT_LIMIT)
        self.assertEqual((second / xml.relative_to(self.folder)).read_bytes(), edited)

    def test_property_edit_native_parser(self):
        import pythoncom
        import pywintypes

        entry = next(entry for entry in self.manifest["streams"] if entry["ole_path"] == ["\x05SummaryInformation"])
        path = self.folder / entry["file"]
        view = json.loads(path.read_text(encoding="utf-8"))
        title = next(prop for prop in view["sections"][0]["properties"] if prop["id"] == 2)
        expected = "Manually edited title with a longer value"
        title["payload"]["value"] = expected
        tool.write_view(path, view)
        output = self.root / "metadata.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        storage = property_sets = summary = None
        try:
            storage = pythoncom.StgOpenStorage(str(output), None, 16, None, 0)
            property_sets = cast(Any, storage).QueryInterface(pythoncom.IID_IPropertySetStorage)
            summary = property_sets.Open(pywintypes.IID("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"), 16)
            self.assertEqual(summary.ReadMultiple((2,))[0], expected)
        finally:
            summary = property_sets = storage = None

    def test_attribute_set_count_recalculation(self):
        entry = next(entry for entry in self.manifest["streams"] if entry["view_kind"] == "dgn-attribute-sets")
        path = self.folder / entry["file"]
        view = json.loads(path.read_text(encoding="utf-8"))
        view["sets"].pop()
        tool.write_view(path, view)
        output = self.root / "attribute-count.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        with tool.ole_reader().OleFileIO(str(output)) as ole:
            raw = ole.openstream(entry["ole_path"]).read()
            self.assertEqual(struct.unpack_from("<I", raw)[0], len(view["sets"]))

    def placeholder_field(self):
        inventory = json.loads((self.folder / self.manifest["objects_index"]).read_text(encoding="utf-8"))
        item = next(item for item in inventory["objects"] if item["kind"] == "dgn-text-field" and item["element_id"] == 110387)
        path = self.folder / item["file"]
        return item, path, json.loads(path.read_text(encoding="utf-8"))

    def test_placeholder_field_all_compatible_choices(self):
        item, path, baseline = self.placeholder_field()
        self.assertEqual(baseline["placeholder_link_type"], "URL or Key-in")
        self.assertEqual(baseline["dictionary"]["Access"], "NodeName")
        self.assertEqual(len(baseline["compatible_link_types"]), 9)
        original = tool.binary_bytes(baseline["original"])
        self.assertEqual(tool.text_field_bytes(baseline), original)
        for label in baseline["compatible_link_types"]:
            with self.subTest(label=label):
                view = json.loads(json.dumps(baseline))
                view["placeholder_link_type"] = label
                encoded = tool.text_field_bytes(view)
                self.assertEqual(struct.unpack_from("<I", encoded)[0], len(encoded))
                after = tool.text_field_view(encoded)
                assert after is not None
                self.assertIn(label, after["matching_link_types"])
                self.assertEqual(after["handler"], "PlaceHolderLinkProp")
                self.assertEqual(after["formatter_name"], baseline["formatter_name"])
                self.assertEqual(after["dictionary"]["Access"], "NodeName")
        view = json.loads(json.dumps(baseline))
        view["placeholder_link_type"] = "Word Bookmark"
        after = tool.text_field_view(tool.text_field_bytes(view))
        assert after is not None
        self.assertIsNone(after["placeholder_link_type"])
        self.assertEqual(after["matching_link_types"], ["Word Heading", "Word Bookmark", "PDF Bookmark"])

    def test_placeholder_field_file_link_rebuild(self):
        item, path, view = self.placeholder_field()
        view["placeholder_link_type"] = "File Link"
        view["dictionary"]["DisplayValue"] = "File link placeholder"
        tool.write_view(path, view)
        output = self.root / "file-link-placeholder.dgn"
        self.assertEqual(tool.rebuild(self.folder, output, tool.DEFAULT_LIMIT), 1)
        second = self.root / "field-reextracted"
        tool.extract(output, second, tool.DEFAULT_LIMIT)
        after = json.loads((second / item["file"]).read_text(encoding="utf-8"))
        self.assertEqual(after["placeholder_link_type"], "File Link")
        self.assertEqual(after["dictionary"]["DemoTargetLinkAncestorKey"], "File")
        self.assertEqual(after["dictionary"]["DisplayValue"], "File link placeholder")
        with tool.ole_reader().OleFileIO(str(SAMPLE)) as before, tool.ole_reader().OleFileIO(str(output)) as rebuilt:
            for names in before.listdir():
                if names != item["ole_path"]:
                    self.assertEqual(before.openstream(names).read(), rebuilt.openstream(names).read(), names)

    def test_placeholder_field_rejects_incompatible_conversions(self):
        item, path, baseline = self.placeholder_field()
        for label in ("DGN File", "Model", "Reference", "Saved View", "Drawing Boundary", "Named Boundary", "Unknown"):
            view = json.loads(json.dumps(baseline))
            view["placeholder_link_type"] = label
            with self.assertRaises(ValueError):
                tool.text_field_bytes(view)
        for key in ("handler", "field_type", "formatter_name"):
            view = json.loads(json.dumps(baseline))
            view[key] = "Unsupported change"
            with self.assertRaises(ValueError):
                tool.text_field_bytes(view)
        view = json.loads(json.dumps(baseline))
        view["dictionary"]["Access"] = "FullPath"
        with self.assertRaises(ValueError):
            tool.text_field_bytes(view)


if __name__ == "__main__":
    unittest.main()