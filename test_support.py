"""Synthetic compound-file fixtures shared by service, CLI and UI tests."""

from pathlib import Path
import importlib.util
import struct
import sys
import zlib

from dgn_explorer import codecs

STORAGE_AVAILABLE = sys.platform == "win32" and importlib.util.find_spec("pythoncom") is not None


def create_dgn(path: Path) -> None:
    import pythoncom
    from win32com import storagecon

    pythoncom.CoInitialize()
    mode = storagecon.STGM_READWRITE | storagecon.STGM_SHARE_EXCLUSIVE
    root = pythoncom.StgCreateDocfile(str(path), mode | storagecon.STGM_CREATE, 0)
    chains = []
    try:
        streams = {
            ("Dgn~H",): struct.pack("<2H4I", 0, 4, 0, 0, 0, 0) + zlib.compress(b"preserved header"),
            ("Notes",): b"<root>Original text</root>",
            ("Opaque",): bytes(range(256)),
        }
        body = bytearray(166)
        struct.pack_into("<I", body, 0, (len(body) + 8) // 2)
        struct.pack_into("<Q", body, 8, 123)
        struct.pack_into("<H", body, 102, 4)
        body[162:] = b"Text"
        chunk = struct.pack("<I2HI", 0, 17, 0x1000, (len(body) + 8) // 2) + body
        for model in ("#000001", "#000002"):
            streams[("Dgn-Md", model, "Dgn^G", "$1")] = struct.pack("<4I", 1, 1, 0, 0) + chunk
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


def create_workspace(root: Path) -> Path:
    source = root / "input.dgn"
    create_dgn(source)
    folder = root / "workspace"
    codecs.extract(source, folder, 1024 * 1024)
    return folder