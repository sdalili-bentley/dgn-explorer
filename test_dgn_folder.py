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
import zlib

import dgn_folder as tool
import dgn_fixture_catalog as fixtures
import xml.etree.ElementTree as ET


SAMPLE = Path(os.environ.get("DGN_EXPLORER_SAMPLE") or Path(__file__).with_name("sample.dgn"))


class RepresentationTests(unittest.TestCase):
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
        with patch.object(tool, "label_workspace_files"):
            tool.extract(SAMPLE, folder, tool.DEFAULT_LIMIT, bytes_mode="hex")
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