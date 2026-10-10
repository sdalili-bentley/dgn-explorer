"""Synthetic compound-file fixtures shared by service, CLI and UI tests."""

import atexit
from pathlib import Path
import importlib.util
import shutil
import struct
import sys
import tempfile
import uuid
import zlib

from dgn_explorer import codecs

STORAGE_AVAILABLE = sys.platform == "win32" and importlib.util.find_spec("pythoncom") is not None


def editor_test_root(testcase) -> Path:
    """Keep reusable payload-test artifacts inside the ignored project build tree."""
    root = Path(__file__).parent / "build" / f"editor-tests-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    testcase.addCleanup(shutil.rmtree, root)
    return root


SUMMARY_FORMAT = "f29f85e0-4ff9-1068-ab91-08002b27b3d9"
ATTRIBUTE_HANDLER = 0x12345678


def element_chunk(element_type: int, core: bytes, *, element_id: int = 1000,
                  level: int = 0, graphics: bool = False, links: bytes = b"") -> bytes:
    header = bytearray(96 if graphics else 24)
    if len(core) % 2:
        core += b"\0"
    struct.pack_into("<IIQd", header, 0, (len(header) + len(core) + 8) // 2, level, element_id, 0.0)
    body = header + core + links
    return struct.pack("<I2HI", 0, element_type, 0x1000 if graphics else 0, (len(body) + 8) // 2) + body


def user_linkage(primary: int, payload: bytes) -> bytes:
    payload += b"\0" * (-len(payload) % 2)
    original = struct.pack("<2H", 0x1003, primary) + bytes(4)
    return codecs.view_bytes({"kind": "dgn-linkage", "primary_id": primary,
                             "header_flags": 0x1000,
                             "original": {"kind": "opaque-bytes", "hex_rows": [original.hex()]},
                             "payload": {"kind": "opaque-bytes", "hex_rows": [payload.hex()]}})


def string_linkage(key: int, text: str) -> bytes:
    value = b"\xff\xfe" + text.encode("utf-16-le")
    return user_linkage(22226, struct.pack("<2HI", key, 0, len(value)) + value)


def xml_fragment(text: str = "<DataGroup><Value>Original</Value></DataGroup>",
                 schema: str = "urn:synthetic:schema", compression: int = 1,
                 *, inaccurate_counts: bool = False, tail: bytes = b"") -> bytes:
    schema_bytes, text_bytes = schema.encode("utf-16-le") + b"\0\0", text.encode("utf-16-le") + b"\0\0"
    schema_count = len(schema) + 1 if inaccurate_counts else len(schema_bytes)
    text_count = len(text) + 1 if inaccurate_counts else len(text_bytes)
    declared = 12 + schema_count + text_count
    body = struct.pack("<Ii", declared, schema_count) + schema_bytes + struct.pack("<i", text_count) + text_bytes + tail
    return struct.pack("<2i", compression, declared + 8) + (zlib.compress(body) if compression == 2 else body)


def tagged_count(value: int) -> bytes:
    if value < 240:
        return bytes([value])
    if value <= 255:
        return b"\xf1" + struct.pack("<B", value)
    if value <= 32767:
        return b"\xf2" + struct.pack("<h", value)
    return b"\xf3" + struct.pack("<i", value)


def becxml_document(text: str = "Original", *, wide: bool = False) -> bytes:
    raw = text.encode("utf-16-le" if wide else "latin-1")
    strings = [b"\xfa\x04Root", (b"\xfb" if wide else b"\xfa") + tagged_count(len(raw) // (2 if wide else 1)) + raw]
    return codecs.BECXML_MAGIC + b"\1\0\0\3\0\0" + b"\x30\2" + b"".join(strings) + b"\2\0\x11\1\4"


def feature_streams(*, uncompressed_header: bool = False) -> dict[tuple[str, ...], bytes]:
    chunks = []

    def add(element_type, core, *, level=0, graphics=False, links=b"", identity=None):
        chunks.append(element_chunk(element_type, core, element_id=identity or 1000 + len(chunks),
                                    level=level, graphics=graphics, links=links))

    point_core = struct.pack("<2I6d", 3, 0, 0, 0, 1, 1, 2, 2)
    add(1, b"library\0")
    add(2, struct.pack("<I2H10d", 0, 0, 0, *range(10)), graphics=True)
    add(3, struct.pack("<4d", 0, 0, 1, 1), graphics=True)
    for element_type in (4, 11, 13, 21, 22):
        add(element_type, point_core, graphics=True)
    add(6, struct.pack("<2I8d", 4, 0, 0, 0, 1, 0, 1, 1, 0, 0), graphics=True)
    for element_type in (5, 7, 18, 19, 33, 35, 36, 87, 88, 90, 91, 99, 108, 110, 111, 112, 113):
        add(element_type, bytes(16), graphics=element_type in (7, 18, 19, 33, 35, 36))
    for element_type in (12, 14, 92, 93, 97, 98, 106, 107):
        add(element_type, bytes(8))
    add(15, struct.pack("<5d", 5, 3, 0, 0, 0), graphics=True)
    add(16, struct.pack("<7d", 0, 1, 5, 3, 0, 0, 0), graphics=True)
    add(23, bytes(104), graphics=True)
    add(24, struct.pack("<10I", 0, 0, 3, 5, 0, 0, 3, 5, 0, 0), graphics=True)
    add(25, struct.pack("<2I6d", 1, 3, 0, 0, 1, 0, 1, 1))
    add(26, struct.pack("<4d", 0, 0, 1, 1))
    add(27, struct.pack("<4I", 0, 0, 3, 5), graphics=True)
    add(28, struct.pack("<3d", 1, 1, 1))
    add(34, bytes(128), graphics=True)
    for data_type, value in ((1, b"Tag\0"), (2, struct.pack("<h", 42)),
                             (3, struct.pack("<i", 123)), (4, struct.pack("<d", 1.5))):
        core = bytearray(192)
        struct.pack_into("<H", core, 24, 3)
        struct.pack_into("<2H", core, 80, 5, data_type)
        struct.pack_into("<2Hi", core, 184, len(value), 0, 1252)
        add(37, bytes(core) + value, graphics=True)
    fragment = xml_fragment()
    pieces = (fragment[:50], fragment[50:100], fragment[100:])
    add(39, struct.pack("<7I", 2, 0, int.from_bytes(b"XMLf", "big"), 123,
                        codecs.dgn_store_checksum(fragment), len(fragment), len(pieces[0])) + pieces[0])
    for sequence, piece in enumerate(pieces[1:], 1):
        add(38, struct.pack("<2I", len(piece), sequence) + piece)
    gcs = bytearray(860)
    struct.pack_into("<2H2i", gcs, 0, 182, 0x1000, 856, 2)
    struct.pack_into("<i", gcs, 584, 4000)
    gcs[148:154] = b"WGS84\0"
    add(66, bytes(gcs), level=20)
    add(94, bytes(144), graphics=True)
    add(100, struct.pack("<4IQ", 0, 1, 2, 3, 0))
    for level in codecs.TABLE_LEVELS:
        add(96, struct.pack("<I", 1), level=level)
        if level == 2:
            name = "Synthetic Font".encode("utf-16-le")
            core = struct.pack("<3IH", 1, 0, 7, len(name)) + name
        elif level == 10:
            core = bytes(68)
        else:
            core = struct.pack("<2I", 1, 0) + bytes(8)
        add(95, core, level=level, links=string_linkage(1, "BBES" if level == 10 else codecs.TABLE_LEVELS[level]),
            identity=0x1234 if level == 10 else None)
    matrix = bytearray(96)
    struct.pack_into("<5I", matrix, 76, 3, 1, 5, 0, 0)
    add(101, bytes(matrix))
    for element_type, format in ((102, "i"), (103, "d")):
        add(element_type, bytes(72) + struct.pack("<4I", 4, 3, 0x20, 0) + struct.pack("<" + format * 4, 1, 2, 3, 999))
    add(105, struct.pack("<2I", 0, 1), graphics=True)
    links = [
        string_linkage(2, "Feature description"),
        string_linkage(89, '{"providerName":"Synthetic","transparency":0.2}'),
        user_linkage(22227, struct.pack("<2H2I2H", 1, 1, 17, 2, 0xA55A, 0xFF01)),
        user_linkage(22288, struct.pack("<4H2IH", 1, 2, 0, 0, 3, 1, 0x39)),
        user_linkage(22241, struct.pack("<2Hi3I", 1, 0, -1, 2, 3, 1)),
        user_linkage(22224, struct.pack("<4HQ", 1, 2, 0, 1, 1000)),
        user_linkage(22243, struct.pack("<4HI", 1, 2, 3, 0, len(fragment)) + fragment),
        user_linkage(48642, b"opaque building data"),
    ]
    xdata = b"".join(struct.pack("<hHI", code, len(value), 0) + value for code, value in
                     ((1001, (0x1234).to_bytes(8, "big")), (1000, b"Voltage"), (1071, struct.pack("<i", 230))))
    links.append(user_linkage(22244, struct.pack("<I", len(xdata)) + xdata))
    for version in (5, 6, 7):
        label = bytearray({5: 61, 6: 73, 7: 75}[version])
        label[6] = version
        label[7:14], label[16:21] = b"Family\0", b"Part\0"
        links.append(user_linkage(20343, bytes(label)))
    add(3, struct.pack("<4d", 0, 0, 1, 1), graphics=True, links=b"".join(links), identity=2000)
    streams = {
        ("Dgn~H",): struct.pack("<2H4I", 0 if uncompressed_header else 1, 4, 0, 0, 0, 0) + (bytes(1576) if uncompressed_header else zlib.compress(bytes(1576))),
        ("Dgn~Mf",): b"synthetic immutable identity",
    }
    items = []
    for model_id in (1, 2):
        name, description, mask = f"Model {model_id}".encode("utf-16-le"), b"D\0e\0s\0c\0", b"\xAA\x01"
        items.append(struct.pack("<2HId6H4s", 0, 0, model_id, 0., 32 + len(name) + len(description) + len(mask),
                                 len(name), len(description), 0, len(mask), 0, b"pad!") + name + description + mask)
        model = f"#{model_id:06x}"
        streams[("Dgn-Md", model, "Dgn~Mh")] = struct.pack("<3I", 2, 8, 5) + bytes(4084)
        streams[("Dgn-Md", model, "Dgn^G", "$2")] = struct.pack("<4I", len(chunks), 1, 0, 0) + b"".join(chunks)
        payloads = [
            (22281 << 16, '<ExtendedColors><Entry Color="1"/></ExtendedColors>'.encode("utf-16-le")),
            (22649 << 16 | 1, '<SolarLightMap><File>passive.png</File></SolarLightMap>'.encode("utf-16-le")),
            (22226 << 16 | 89, '{"providerName":"Synthetic","groundBias":1}'.encode("utf-16-le")),
            (0xEC34 << 16, xml_fragment('<ECSchema schemaName="Synthetic" version="1.0"/>')),
            (22243 << 16, xml_fragment(compression=2)),
            (22271 << 16 | 1, struct.pack("<I", 0x01010000) + "Synthetic\0".encode("utf-16-le") + struct.pack("<2I", 1, 0) + becxml_document("café")),
            (0xECDA << 16, struct.pack("<3H2B2I", 1, 2, 3, 1, 0xAA, 5, 6) + b"opaque instance"),
        ]
        records = bytearray()
        for attribute_id, (handler, payload) in enumerate(payloads):
            if handler >> 16 in (22281, 22649):
                payload = struct.pack("<2HI", 3, 0, len(payload)) + zlib.compress(payload)
            records.extend(struct.pack("<4I", handler, attribute_id, len(payload), 0) + payload)
        records.extend(bytes(4))
        group = struct.pack("<4IQI", 0xA11B, len(records), 0xAA, 0, 2000, len(payloads)) + records
        streams[("Dgn-Md", model, "Dgn^GA", "$2")] = struct.pack("<4I", 1, 1, 0, 0) + group
    streams[("Dgn^Ix", "Dgn~Mix")] = struct.pack("<4I", 0xAA00BA11, 2, 2, 0) + b"".join(items)
    return streams


def property_stream(title: str = "Synthetic title", pages: int = 1) -> bytes:
    """OLE SummaryInformation with CodePage, Title and PageCount properties."""
    encoded = title.encode("cp1252") + b"\0"
    values = [
        (1, struct.pack("<Ih", 2, 1252)),
        (2, struct.pack("<2I", 30, len(encoded)) + encoded),
        (14, struct.pack("<Ii", 3, pages)),
    ]
    offset = 8 + 8 * len(values)
    table, payloads = bytearray(), bytearray()
    for prop_id, value in values:
        padded = value + b"\0" * (-len(value) % 4)
        table.extend(struct.pack("<2I", prop_id, offset))
        payloads.extend(padded)
        offset += len(padded)
    section = struct.pack("<2I", offset, len(values)) + table + payloads
    header = b"\xfe\xff\0\0" + struct.pack("<I", 0x00020006) + bytes(16)
    return header + struct.pack("<I", 1) + uuid.UUID(SUMMARY_FORMAT).bytes_le + struct.pack("<I", 48) + section


def attribute_stream(element_id: int = 123, xml: str = "<attr>Value</attr>") -> bytes:
    """Framed DGN attribute set with one XML and one opaque attribute."""
    records = bytearray()
    for attribute_id, payload in ((1, xml.encode("utf-8")), (2, bytes([0, 1, 2, 255]))):
        records.extend(struct.pack("<4I", ATTRIBUTE_HANDLER, attribute_id, len(payload), 0) + payload)
    records.extend(struct.pack("<I", 0))
    body = struct.pack("<4IQI", 0xA11B, len(records), 1, 0, element_id, 2) + records
    return struct.pack("<4I", 1, 1, 0, 0) + body


def create_dgn(path: Path, *, text_count: int = 1, notes_text: str = "Original text", rich: bool = False, features: bool = False, uncompressed_header: bool = False) -> None:
    import pythoncom
    from win32com import storagecon

    pythoncom.CoInitialize()
    mode = storagecon.STGM_READWRITE | storagecon.STGM_SHARE_EXCLUSIVE
    root = pythoncom.StgCreateDocfile(str(path), mode | storagecon.STGM_CREATE, 0)
    chains = []
    try:
        streams = {
            ("Dgn~H",): struct.pack("<2H4I", 0, 4, 0, 0, 0, 0) + zlib.compress(b"preserved header"),
            ("Notes",): f"<root>{notes_text}</root>".encode("utf-8"),
            ("Opaque",): bytes(range(256)),
        }
        body = bytearray(166)
        struct.pack_into("<I", body, 0, (len(body) + 8) // 2)
        struct.pack_into("<Q", body, 8, 123)
        struct.pack_into("<H", body, 102, 4)
        body[162:] = b"Text"
        chunks = []
        for index in range(text_count):
            struct.pack_into("<Q", body, 8, 123 + index)
            chunks.append(struct.pack("<I2HI", 0, 17, 0x1000, (len(body) + 8) // 2) + body)
        for model in ("#000001", "#000002"):
            streams[("Dgn-Md", model, "Dgn^G", "$1")] = struct.pack("<4I", text_count, 1, 0, 0) + b"".join(chunks)
            if rich:
                streams[("Dgn-Md", model, "Dgn^A", "$1")] = attribute_stream()
        if rich:
            streams[("\x05SummaryInformation",)] = property_stream()
        if features:
            streams.update(feature_streams(uncompressed_header=uncompressed_header))
        storages = {(): root}
        for names, raw in streams.items():
            for length in range(1, len(names)):
                parent = names[:length]
                if parent not in storages:
                    storages[parent] = storages[parent[:-1]].CreateStorage(parent[-1], mode, 0, 0)
                    chains.append(storages[parent])
            stream = storages[names[:-1]].CreateStream(names[-1], mode, 0, 0)
            stream.Write(raw)
            stream.Commit(0)
            stream = None
        for storage in reversed(chains):
            storage.Commit(0)
        root.Commit(0)
    finally:
        stream = storage = None
        storages.clear()
        chains.clear()
        root = None
        pythoncom.CoUninitialize()


def create_workspace(root: Path, *, text_count: int = 1, notes_text: str = "Original text", rich: bool = False, features: bool = False, uncompressed_header: bool = False) -> Path:
    source = root / "input.dgn"
    create_dgn(source, text_count=text_count, notes_text=notes_text, rich=rich, features=features, uncompressed_header=uncompressed_header)
    folder = root / "workspace"
    codecs.extract(source, folder, 1024 * 1024)
    return folder


_SHARED: dict[tuple, Path] = {}


def shared_workspace(**options) -> Path:
    """Create a fixture once per test process; callers must treat it as read-only."""
    key = tuple(sorted(options.items()))
    if key not in _SHARED:
        temporary = tempfile.TemporaryDirectory(prefix="dgn-shared-")
        atexit.register(temporary.cleanup)
        _SHARED[key] = create_workspace(Path(temporary.name), **options)
    return _SHARED[key]
