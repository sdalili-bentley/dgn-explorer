"""Contextual inventory and typed edits over the existing folder format."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile
from typing import Any

from . import codecs


class ConflictError(ValueError):
    pass


class CancelledError(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    stream: int = 128 * 1024 * 1024
    aggregate: int = 2 * 1024 * 1024 * 1024
    operations: int = 100
    patch: int = 16 * 1024 * 1024
    records: int = 1_000_000
    depth: int = 64

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Limits must be positive integers")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf-8")


def parse_json(data: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite JSON number")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def confined(folder: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Invalid workspace reference")
    if PureWindowsPath(relative).drive or any(part in ("..", ".dgn-explorer") for part in Path(relative).parts):
        raise ValueError("Unsafe workspace reference")
    path = codecs.inside(folder, relative)
    candidate = folder / relative
    for parent in (candidate, *candidate.parents):
        if parent.exists() or parent.is_symlink():
            stat = parent.lstat()
            if parent.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("Links/reparse points are not supported")
        if parent == folder:
            break
    return path


def parts(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("Invalid JSON pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def escaped(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def get_pointer(value: Any, pointer: str) -> Any:
    for part in parts(pointer):
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("Invalid array index")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def replace_pointer(value: Any, pointer: str, replacement: Any) -> None:
    path = parts(pointer)
    parent = value
    for part in path[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    key = int(path[-1]) if isinstance(parent, list) else path[-1]
    parent[key] = deepcopy(replacement)


def compatible(original: Any, value: Any) -> bool:
    if isinstance(original, list):
        return isinstance(value, list) and len(original) == len(value) and all(compatible(before, after) for before, after in zip(original, value))
    if type(original) is float:
        return type(value) in (int, float) and math.isfinite(value)
    return type(original) is type(value) and not isinstance(value, (dict, list))


SUPPORTED = frozenset({
    "dgn-text-element", "dgn-text-node", "dgn-element", "dgn-geometry",
    "dgn-varichar", "dgn-text-field", "dgn-fixed-record", "dgn-string-linkage",
    "text", "xml", "json-text", "ole-property-value",
})
FROZEN = frozenset({
    "original", "original_identity", "identity", "element_id", "kind",
    "encoding", "bom_hex", "codepage", "variant_type", "text_file", "file",
    "signature", "reserved", "header_flags", "primary_id", "mode",
})


def capabilities(value: dict) -> tuple[str, ...]:
    result = []
    for pointer in codecs.editing_contract(value)["editable_fields"]:
        node = value
        permitted = False
        forbidden = False
        for part in parts(pointer):
            if isinstance(node, dict):
                kind = node.get("kind")
                forbidden |= part in FROZEN or kind in {"opaque-bytes", "byte-string", "dgn-startup-command"}
                permitted |= kind in SUPPORTED
                if kind == "dgn-string-linkage" and node.get("key") == 62:
                    forbidden = True
                node = node[part]
            else:
                node = node[int(part)]
        if permitted and not forbidden and not isinstance(node, dict):
            result.append(pointer)
    return tuple(result)


@dataclass(frozen=True)
class Binding:
    file: str
    pointer: str
    content: bool = False


@dataclass
class Record:
    locator: dict
    value: dict
    bindings: dict[str, Binding]
    stream_pointer: str
    editable: tuple[str, ...] = ()


def locator_key(locator: dict) -> str:
    return json.dumps(locator, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Workspace:
    def __init__(self, folder: Path, limits: Limits | None = None, cancel=None):
        from .transactions import ownership, recover

        folder = Path(folder).absolute()
        with ownership(folder):
            recover(folder, limits or Limits())
            self._open(folder, limits, cancel)

    def _open(self, folder: Path, limits: Limits | None = None, cancel=None):
        self.folder = Path(folder).absolute()
        self.limits = limits or Limits()
        self.cancel = cancel or (lambda: False)
        confined(self.folder, "original.dgn")
        self._baseline = tempfile.TemporaryDirectory(prefix="dgn-explorer-baseline-")
        self.files: dict[str, bytes] = {}
        self.streams: dict[tuple[str, ...], dict] = {}
        self.records: dict[str, Record] = {}
        self.pending: dict[str, bytes] = {}
        self.staged: dict[str, dict] = {}
        try:
            self.manifest_name = "manifest.rw.json" if (self.folder / "manifest.rw.json").exists() else "manifest.json"
            self.manifest = self._json(self.manifest_name)
            if self.manifest.get("format") not in ("dgn-folder-v1", codecs.FORMAT):
                raise ValueError("Unsupported workspace format")
            self.source_hash = codecs.file_digest(self.folder / "original.dgn")
            if self.source_hash != self.manifest["original_sha256"]:
                raise ValueError("Original DGN fingerprint mismatch")
            baseline = Path(self._baseline.name) / "baseline"
            self._preflight(self.folder / "original.dgn")
            baseline_manifest = codecs.extract(self.folder / "original.dgn", baseline, self.limits.stream, cancel=self.cancel)
            self._load(self.folder, self.manifest, self.records, self.streams)
            self.original_records: dict[str, Record] = {}
            self.original_streams: dict[tuple[str, ...], dict] = {}
            self._load(baseline, baseline_manifest, self.original_records, self.original_streams)
            if self.manifest["storages"] != baseline_manifest["storages"] or set(self.streams) != set(self.original_streams):
                raise ValueError("Stream/storage identities change")
            for key, record in self.records.items():
                original = self.original_records[key]
                record.editable = capabilities(original.value)
                if record.locator.get("property_id") == "1":
                    record.editable = ()
            self.validate_workspace()
            self.revision = self._revision()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._baseline.cleanup()

    def checkpoint(self):
        if self.cancel():
            raise CancelledError("Operation cancelled")

    def _preflight(self, source: Path):
        total = 0
        with codecs.ole_reader().OleFileIO(str(source)) as ole:
            for names in ole.listdir():
                self.checkpoint()
                if ole.get_size(names) > self.limits.stream:
                    raise ValueError("Stored stream limit exceeded")
                raw = ole.openstream(names).read()
                total += len(codecs.decode_stream(names, raw, self.limits.stream)[1])
                if total > self.limits.aggregate:
                    raise ValueError("Aggregate decoded limit exceeded")

    def _read(self, folder: Path, relative: str) -> bytes:
        self.checkpoint()
        data = codecs.read_limited(confined(folder, relative), self.limits.stream)
        if folder == self.folder:
            self.files[relative] = data
            if sum(len(value) for value in self.files.values()) > self.limits.aggregate:
                raise ValueError("Workspace input limit exceeded")
        return data

    def _json(self, relative: str) -> Any:
        return parse_json(self._read(self.folder, relative))

    def _materialize(self, folder, node, filename, pointer="", local="", bindings=None, trail=(), depth=0):
        self.checkpoint()
        if depth > self.limits.depth:
            raise ValueError("Reference/JSON depth exceeded")
        if isinstance(node, dict):
            if node.get("kind") == "opaque-bytes":
                node = codecs.readable_bytes(node)
            if node.get("kind") == "object-reference":
                target = node["file"]
                if Path(target).parts[0] not in {"data", "objects", "attributes", "fields"}:
                    raise ValueError("Object reference is outside record files")
                if target in trail:
                    raise ValueError("Cyclic object reference")
                child = parse_json(self._read(folder, target))
                return self._materialize(folder, child, target, pointer, "", bindings, (*trail, target), depth + 1)
            result = {}
            for key, value in node.items():
                if key in ("editing", "text_file"):
                    continue
                path = "/" + escaped(key)
                result[key] = self._materialize(folder, value, filename, pointer + path, local + path, bindings, trail, depth + 1)
            if "text_file" in node:
                if Path(node["text_file"]).parts[0] != "content":
                    raise ValueError("Text reference is outside content files")
                if "text" in node:
                    raise ValueError("Conflicting text representations")
                result["text"] = self._read(folder, node["text_file"]).decode("utf-8")
                bindings[pointer + "/text"] = Binding(node["text_file"], "", True)
            return result
        if isinstance(node, list):
            bindings[pointer] = Binding(filename, local)
            return [self._materialize(folder, value, filename, pointer + f"/{index}", local + f"/{index}", bindings, trail, depth + 1) for index, value in enumerate(node)]
        bindings[pointer] = Binding(filename, local)
        return node

    def _load(self, folder, manifest, records, streams):
        for entry in manifest["streams"]:
            self.checkpoint()
            names = tuple(entry["ole_path"])
            if names in streams:
                raise ValueError("Duplicate stream identity")
            if entry.get("representation") != "json-view":
                raise ValueError("Binary-only workspace requires re-extraction for the editor")
            bindings: dict[str, Binding] = {}
            template = parse_json(self._read(folder, entry["file"]))
            view = self._materialize(folder, template, entry["file"], bindings=bindings)
            streams[names] = view
            for framing in ("prefix", "suffix"):
                if framing in entry:
                    self._read(folder, entry[framing])
            selections = []
            if view["kind"] == "dgn-element-chunks":
                selections = [(dict(ole_path=list(names), chunk_index=index), f"/chunks/{index}/body", chunk["body"]) for index, chunk in enumerate(view["chunks"])]
            elif view["kind"] == "dgn-attribute-sets":
                for set_index, group in enumerate(view["sets"]):
                    for index, attribute in enumerate(group["attributes"]):
                        locator = dict(ole_path=list(names), set_index=set_index, element_id=str(group["element_id"]), handler_id=str(attribute["handler_id"]), attribute_id=str(attribute["attribute_id"]))
                        selections.append((locator, f"/sets/{set_index}/attributes/{index}/payload", attribute["payload"]))
            elif view["kind"] == "ole-properties":
                for section_index, section in enumerate(view["sections"]):
                    for index, prop in enumerate(section["properties"]):
                        selections.append((dict(ole_path=list(names), section_index=section_index, property_id=str(prop["id"])), f"/sections/{section_index}/properties/{index}/payload", prop["payload"]))
            else:
                selections = [(dict(ole_path=list(names)), "", view)]
            for locator, pointer, value in selections:
                selected = {path[len(pointer):]: binding for path, binding in bindings.items() if path.startswith(pointer + "/")}
                key = locator_key(locator)
                if key in records or len(records) >= self.limits.records:
                    raise ValueError("Duplicate record or record limit exceeded")
                records[key] = Record(locator, value, selected, pointer)

    def _revision(self) -> str:
        digest = hashlib.sha256(self.source_hash.encode("ascii"))
        for name, data in sorted(self.files.items()):
            digest.update(json_bytes([name, codecs.digest(data)]))
        return "sha256:" + digest.hexdigest()

    def check_revision(self):
        self.checkpoint()
        if codecs.file_digest(confined(self.folder, "original.dgn")) != self.source_hash:
            raise ConflictError("Original DGN changes during session")
        for name, data in self.files.items():
            if codecs.read_limited(confined(self.folder, name), self.limits.stream) != data:
                raise ConflictError("Workspace changes externally; reload required")

    def get_record(self, locator: dict) -> dict:
        record = self.records[locator_key(locator)]
        key = locator_key(locator)
        return {"record": deepcopy(record.locator), "value": deepcopy(self.staged.get(key, record.value)), "editable_fields": list(record.editable), "access": "rw" if record.editable else "ro"}

    def list_records(self, cursor=0, limit=200, text="", model="", kind="") -> dict:
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid pagination")
        if not all(isinstance(value, str) and len(value) <= 4096 for value in (text, model, kind)):
            raise ValueError("Invalid filter")
        matches = []
        for key, record in self.records.items():
            self.checkpoint()
            value = self.staged.get(key, record.value)
            if kind and value["kind"] != kind or model and model not in record.locator["ole_path"]:
                continue
            if text and text.casefold() not in json.dumps(value, ensure_ascii=False).casefold():
                continue
            if len(matches) >= cursor + limit + 1:
                break
            matches.append({"record": deepcopy(record.locator), "kind": value["kind"], "element_id": str(value.get("element_id", "")), "preview": str(value.get("string", {}).get("text", value.get("text", "")))[:240], "access": "rw" if record.editable else "ro"})
        page = matches[cursor:cursor + limit]
        return {"records": page, "next_cursor": cursor + limit if len(matches) > cursor + limit else None, "revision": self.revision}

    def validate_patch(self, patch: dict) -> dict:
        self.check_revision()
        if not isinstance(patch, dict) or set(patch) != {"schema", "workspace_revision", "operations"} or patch["schema"] != "dgn-explorer.patch-v1":
            raise ValueError("Invalid patch envelope")
        if len(json_bytes(patch)) > self.limits.patch:
            raise ValueError("Patch size limit exceeded")
        if patch["workspace_revision"] != self.revision:
            raise ConflictError("Patch revision mismatch")
        operations = patch["operations"]
        if not isinstance(operations, list) or len(operations) > self.limits.operations:
            raise ValueError("Patch operation limit exceeded")
        proposed = deepcopy(self.staged)
        seen = set()
        changes = []
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {"record", "pointer", "expected_value", "value"}:
                raise ValueError("Invalid replacement operation")
            key = locator_key(operation["record"])
            if key not in self.records:
                raise ValueError("Unknown contextual record")
            record = self.records[key]
            pointer = operation["pointer"]
            if pointer not in record.editable:
                raise ValueError("Unknown or read-only property")
            if (key, pointer) in seen:
                raise ValueError("Duplicate replacement operation")
            seen.add((key, pointer))
            value = proposed.setdefault(key, deepcopy(record.value))
            before = get_pointer(value, pointer)
            if not compatible(before, operation["expected_value"]) or before != operation["expected_value"]:
                raise ConflictError("Expected value mismatch")
            if not compatible(get_pointer(self.original_records[key].value, pointer), operation["value"]):
                raise ValueError("Replacement type/shape mismatch")
            if before == operation["value"]:
                continue
            replace_pointer(value, pointer, operation["value"])
            codecs.view_bytes(value)
            changes.append(deepcopy(operation))
        return {"changes": changes, "proposed": proposed}

    def stage_patch(self, patch: dict) -> dict:
        report = self.validate_patch(patch)
        replacements = dict(self.pending)
        documents = {}
        for operation in report["changes"]:
            record = self.records[locator_key(operation["record"])]
            binding = record.bindings[operation["pointer"]]
            if binding.content:
                replacements[binding.file] = operation["value"].encode("utf-8")
            else:
                document = documents.setdefault(binding.file, parse_json(replacements.get(binding.file, self.files[binding.file])))
                replace_pointer(document, binding.pointer, operation["value"])
        replacements.update({name: json_bytes(document) for name, document in documents.items()})
        previous_pending, previous_staged = self.pending, self.staged
        self.pending = {name: data for name, data in replacements.items() if data != self.files[name]}
        self.staged = report["proposed"]
        try:
            self.validate_workspace()
        except BaseException:
            self.pending, self.staged = previous_pending, previous_staged
            raise
        return {"changes": report["changes"], "dirty": bool(self.pending)}

    def discard(self):
        self.pending.clear()
        self.staged.clear()

    def save_workspace(self, fault=None) -> dict:
        from .transactions import ownership, publish

        with ownership(self.folder):
            count = publish(self, fault)
            self.close()
            self._open(self.folder, self.limits, self.cancel)
        return {"saved_files": count, "revision": self.revision}

    @contextmanager
    def snapshot(self):
        self.check_revision()
        with tempfile.TemporaryDirectory(prefix="dgn-explorer-snapshot-") as temporary:
            folder = Path(temporary) / "workspace"
            folder.mkdir(mode=0o700)
            shutil.copyfile(self.folder / "original.dgn", folder / "original.dgn")
            for name, data in self.files.items():
                self.checkpoint()
                path = confined(folder, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.pending.get(name, data))
            yield folder

    def pack_workspace(self, output: Path) -> dict:
        from .transactions import ownership

        output = Path(output).absolute()
        if output.exists() or output.is_symlink():
            raise ValueError("Output already exists")
        if output.resolve().is_relative_to(self.folder.resolve()):
            raise ValueError("Output must be outside the workspace")
        output.parent.mkdir(parents=True, exist_ok=True)
        with ownership(self.folder):
            self.check_revision()
            self.validate_workspace()
            with self.snapshot() as snapshot, tempfile.TemporaryDirectory(prefix=".dgn-output-", dir=output.parent) as temporary:
                provisional = Path(temporary) / "verified.dgn"
                count = codecs.rebuild(snapshot, provisional, self.limits.stream, cancel=self.cancel)
                self.check_revision()
                self.checkpoint()
                os.link(provisional, output)
        return {"changed_entries": count, "verified": True, "application_validation": "not performed"}

    def diff_workspace(self) -> dict:
        changes = []
        for key, record in self.records.items():
            value = self.staged.get(key, record.value)
            original = self.original_records[key].value
            for pointer in record.editable:
                before, after = get_pointer(original, pointer), get_pointer(value, pointer)
                if before != after:
                    changes.append(dict(record=deepcopy(record.locator), pointer=pointer, expected_value=deepcopy(before), value=deepcopy(after)))
        return {"changes": changes, "dirty": bool(self.pending), "revision": self.revision}

    def validate_workspace(self) -> dict:
        if set(self.records) != set(self.original_records):
            raise ValueError("Record identities change")
        adjusted = deepcopy(self.original_streams)
        total = 0
        for key, record in self.records.items():
            value = self.staged.get(key, record.value)
            original = self.original_records[key].value
            allowed = deepcopy(original)
            for pointer in record.editable:
                replacement = get_pointer(value, pointer)
                if not compatible(get_pointer(original, pointer), replacement):
                    raise ValueError("Saved property type/shape mismatch")
                replace_pointer(allowed, pointer, replacement)
            if allowed != value:
                raise ValueError("Read-only data or original snapshot changes")
            names = tuple(record.locator["ole_path"])
            if record.stream_pointer:
                replace_pointer(adjusted[names], record.stream_pointer, value)
            else:
                adjusted[names] = value
        current = deepcopy(self.streams)
        for key, value in self.staged.items():
            record = self.records[key]
            names = tuple(record.locator["ole_path"])
            if record.stream_pointer:
                replace_pointer(current[names], record.stream_pointer, value)
            else:
                current[names] = value
        if current != adjusted:
            raise ValueError("Stream structure changes")
        with codecs.ole_reader().OleFileIO(str(self.folder / "original.dgn")) as ole:
            for entry in self.manifest["streams"]:
                self.checkpoint()
                raw = ole.openstream(entry["ole_path"]).read()
                codec, payload, prefix, suffix = codecs.decode_stream(entry["ole_path"], raw, self.limits.stream)
                if entry["codec"] != codec or entry["raw_sha256"] != codecs.digest(raw) or entry["payload_sha256"] != codecs.digest(payload):
                    raise ValueError("Manifest stream fingerprint/codec mismatch")
                for field, expected in (("prefix", prefix), ("suffix", suffix)):
                    if field in entry:
                        actual = parse_json(self.files[entry[field]])
                        if codecs.view_bytes(actual) != expected:
                            raise ValueError("Framing changes are not supported by the editor")
                encoded = codecs.view_bytes(current[tuple(entry["ole_path"])])
                if len(encoded) > self.limits.stream:
                    raise ValueError("Encoded stream limit exceeded")
                total += len(encoded)
                if total > self.limits.aggregate:
                    raise ValueError("Aggregate encoded limit exceeded")
        return {"valid": True, "records": len(self.records), "decoded_bytes": total, "application_validation": "not performed"}


def open_workspace(folder: Path, limits: Limits | None = None, cancel=None) -> Workspace:
    return Workspace(folder, limits, cancel)