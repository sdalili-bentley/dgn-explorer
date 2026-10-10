"""Contextual inventory and typed edits over the existing folder format."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import errno
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
from stat import S_ISLNK
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

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON number")
        return result

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


class PathChecks:
    """Directories verified as non-links during one workspace load."""

    def __init__(self):
        self.root: str | None = None
        self.directories: set[Path] = set()


def confined(folder: Path, relative: str, verified: PathChecks | None = None) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Invalid workspace reference")
    if PureWindowsPath(relative).drive or any(part in ("..", ".dgn-explorer") for part in Path(relative).parts):
        raise ValueError("Unsafe workspace reference")
    candidate = folder / relative
    if verified is None:
        path = codecs.inside(folder, relative)
    else:
        if verified.root is None:
            verified.root = os.path.normcase(os.path.realpath(folder))
        path = Path(os.path.realpath(candidate))
        if not os.path.normcase(str(path)).startswith(verified.root.rstrip(os.sep) + os.sep):
            raise ValueError("Workspace path escapes folder")
    checked = []
    parent = candidate
    while True:
        if verified is not None and parent in verified.directories:
            break
        try:
            stat = parent.lstat()
        except FileNotFoundError:
            stat = None
        if stat is not None:
            if S_ISLNK(stat.st_mode) or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("Links/reparse points are not supported")
            if parent != candidate:
                checked.append(parent)
        if parent == folder or parent.parent == parent:
            break
        parent = parent.parent
    if verified is not None:
        verified.directories.update(checked)
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
    "dgn-table-entry", "dgn-xdata", "dgn-tag", "dgn-symbology",
})
FROZEN = frozenset({
    "original", "original_identity", "identity", "element_id", "element_type", "kind",
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


def searchable(node: Any, needle: str) -> bool:
    """Literal case-insensitive match against current scalar values, not JSON syntax or snapshots."""
    pending = [node]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            pending.extend(value for key, value in node.items() if key not in ("original", "original_identity"))
        elif isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, str):
            if needle in node.casefold():
                return True
        elif type(node) in (int, float) and needle in str(node):
            return True
    return False


def contains_kind(node: Any, kind: str) -> bool:
    pending = [node]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if node.get("kind") == kind:
                return True
            pending.extend(child for key, child in node.items() if key not in ("original", "original_identity"))
        elif isinstance(node, list):
            pending.extend(node)
    return False


def encoded(value: Any) -> bytes:
    """Encode a record or stream view, reporting codec range/syntax failures as invalid input."""
    import struct

    try:
        return codecs.view_bytes(value)
    except (struct.error, OverflowError) as error:
        raise ValueError("Replacement value is out of range for its encoding") from error
    except SyntaxError as error:
        raise ValueError("Replacement text is not well-formed") from error
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError(f"Replacement cannot be encoded: {type(error).__name__}") from error


def original_representation(current: Any, original: Any) -> Any:
    """Project newly recognized bytes into an older, strictly equivalent view."""
    if current == original:
        return original
    if isinstance(current, dict) and isinstance(original, dict):
        old_kind, kind = current.get("kind"), original.get("kind")
        if old_kind in ("opaque-bytes", "byte-string") and kind not in ("opaque-bytes", "byte-string"):
            raw = encoded(original)
            expected = codecs.readable_bytes({"kind": "opaque-bytes", "hex_rows": [raw.hex()]})
            if codecs.readable_bytes(current) == expected:
                return expected
            return original
        if old_kind == "dgn-model-header" and "remaining" in current and "original" in original:
            raw = encoded(original)
            return {"kind": "dgn-model-header", "num_pointer_blocks": original["num_pointer_blocks"],
                    "major_version": original["major_version"], "minor_version": original["minor_version"],
                    "remaining": codecs.readable_bytes({"kind": "opaque-bytes", "hex_rows": [raw[12:].hex()]})}
        if old_kind in ("text", "xml", "json-text") and old_kind != kind:
            expected = codecs.text_view(encoded(original))
            if expected is not None and old_kind == expected["kind"]:
                return expected
            return original
        if old_kind != kind:
            return original
        projected = deepcopy(original)
        for key in ("format_name", "schema_name", "primary_name", "store_assembly"):
            if key not in current:
                projected.pop(key, None)
        if "type_name" in current and "element_type" in original and current["type_name"] in ("Unknown", codecs.ELEMENT_TYPES.get(original["element_type"])):
            projected["type_name"] = current["type_name"]
        for key in current.keys() & projected.keys():
            if key != "type_name":
                projected[key] = original_representation(current[key], projected[key])
        return projected
    if isinstance(current, list) and isinstance(original, list) and len(current) == len(original):
        return [original_representation(before, value) for before, value in zip(current, original)]
    return original


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


@dataclass(frozen=True)
class ElementLocator:
    model: tuple[str, ...]
    element_list: str
    block: str
    element_id: int

    @classmethod
    def from_record(cls, record: Record):
        names = record.locator["ole_path"]
        if len(names) < 4 or names[0] not in ("Dgn-Md", "Dgn-Nd") or "element_id" not in record.value:
            return None
        return cls(tuple(names[:2]), names[-2], names[-1], record.value["element_id"])


def record_description(value: dict) -> tuple[str, str]:
    core = value.get("core", {})
    payload = value.get("payload", value)
    feature = core.get("table_name", value.get("type_name", payload.get("format_name", value.get("format_name", payload.get("kind", value["kind"])))))
    preview = ""
    pending = [value]
    while pending and not preview:
        node = pending.pop()
        if isinstance(node, dict):
            preview = next((node[key] for key in ("text", "name", "part", "family") if isinstance(node.get(key), str) and node[key]), "")
            pending.extend(child for key, child in reversed(list(node.items())) if key not in ("original", "original_identity", "tail", "raw"))
        elif isinstance(node, list):
            pending.extend(reversed(node))
    return str(feature), preview[:240]


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
        self.files: dict[str, bytes] = {}
        self._input_total = 0
        self._verified = PathChecks()
        self.streams: dict[tuple[str, ...], dict] = {}
        self.records: dict[str, Record] = {}
        self.pending: dict[str, bytes] = {}
        self.staged: dict[str, dict] = {}
        self._encoded_sizes: dict[tuple[str, ...], int] = {}
        self.manifest_name = "manifest.rw.json" if (self.folder / "manifest.rw.json").exists() else "manifest.json"
        self.manifest = self._json(self.manifest_name)
        if not isinstance(self.manifest, dict) or self.manifest.get("format") not in ("dgn-folder-v1", codecs.FORMAT):
            raise ValueError("Unsupported workspace format")
        self.source_hash = codecs.file_digest(self.folder / "original.dgn")
        if self.source_hash != self.manifest["original_sha256"]:
            raise ValueError("Original DGN fingerprint mismatch")
        baseline_manifest, baseline = codecs.extract_memory(self.folder / "original.dgn", self.limits.stream, cancel=self.cancel, aggregate=self.limits.aggregate)
        if baseline_manifest["original_sha256"] != self.source_hash:
            raise ConflictError("Original DGN changes during session")
        current_entries = {tuple(entry["ole_path"]): entry for entry in self.manifest["streams"]}
        for entry in baseline_manifest["streams"]:
            current = current_entries.get(tuple(entry["ole_path"]), {})
            if entry["ole_path"] == ["Dgn~H"] and entry["codec"] == "framed-raw" and current.get("codec") == "raw":
                view = parse_json(baseline[entry["file"]])
                payload = encoded(view)
                for field in ("prefix", "suffix"):
                    if field in entry:
                        framing = encoded(parse_json(baseline[entry[field]]))
                        payload = framing + payload if field == "prefix" else payload + framing
                        for key in (field, field + "_representation", field + "_sha256"):
                            entry.pop(key, None)
                entry["codec"] = "raw"
                entry["payload_sha256"] = codecs.digest(payload)
                baseline[entry["file"]] = json_bytes(codecs.readable_bytes({"kind": "opaque-bytes", "hex_rows": [payload.hex()]}))
        self._load(self.folder, self.manifest, self.records, self.streams)
        self.original_records: dict[str, Record] = {}
        self.original_streams: dict[tuple[str, ...], dict] = {}
        self._load(baseline, baseline_manifest, self.original_records, self.original_streams)
        del baseline
        self.original_entries = {tuple(entry["ole_path"]): entry for entry in baseline_manifest["streams"]}
        if self.manifest["storages"] != baseline_manifest["storages"] or set(self.streams) != set(self.original_streams):
            raise ValueError("Stream/storage identities change")
        if set(self.records) != set(self.original_records):
            raise ValueError("Record identities change")
        for key, record in self.records.items():
            original = self.original_records[key]
            admitted = capabilities(original.value)
            original.value = original_representation(record.value, original.value)
            record.editable = tuple(pointer for pointer in capabilities(original.value) if pointer in admitted)
            if record.locator.get("property_id") == "1":
                record.editable = ()
            if original.value.get("element_type") in (95, 96):
                record.editable = tuple(pointer for pointer in record.editable if pointer != "/level_id")
                if original.value.get("level_id") == 10:
                    record.editable = ()
        self.registered_apps: dict[int, str | None] = {}
        for record in self.original_records.values():
            if record.value.get("element_type") != 95 or record.value.get("level_id") != 10:
                continue
            links = record.value.get("linkages", {}).get("records", [])
            name = next((link["payload"].get("string", {}).get("text") for link in links
                         if link["payload"].get("kind") == "dgn-string-linkage" and link["payload"]["key"] == 1), None)
            if isinstance(name, str):
                identity = record.value["element_id"]
                previous = self.registered_apps.get(identity, name)
                self.registered_apps[identity] = name if previous == name else None
        self._validate_baseline()
        self.validate_workspace()
        self.revision = self._revision()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        """Sessions hold no temporary files; retained for the context-manager API."""

    def checkpoint(self):
        if self.cancel():
            raise CancelledError("Operation cancelled")

    def _read(self, folder: Path | dict, relative: str) -> bytes:
        self.checkpoint()
        if isinstance(folder, dict):
            if not isinstance(relative, str) or relative not in folder:
                raise ValueError("Missing baseline reference")
            data = folder[relative]
            if len(data) > self.limits.stream:
                raise ValueError("Baseline file exceeds stream limit")
            return data
        data = codecs.read_limited(confined(folder, relative, self._verified), self.limits.stream)
        if folder == self.folder:
            previous = self.files.get(relative)
            self.files[relative] = data
            self._input_total += len(data) - (len(previous) if previous is not None else 0)
            if self._input_total > self.limits.aggregate:
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
            binding_groups = {pointer: {} for locator, pointer, value in selections}
            for path, binding in bindings.items():
                self.checkpoint()
                parent = path
                while "/" in parent:
                    parent = parent.rpartition("/")[0]
                    if parent in binding_groups:
                        binding_groups[parent][path[len(parent):]] = binding
                        break
            for locator, pointer, value in selections:
                selected = binding_groups[pointer]
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
        try:
            source_hash = codecs.file_digest(confined(self.folder, "original.dgn"))
        except FileNotFoundError as error:
            raise ConflictError("Original DGN is removed during session") from error
        if source_hash != self.source_hash:
            raise ConflictError("Original DGN changes during session")
        checks = PathChecks()
        for name, data in self.files.items():
            self.checkpoint()
            path = confined(self.folder, name, checks)
            try:
                if path.stat().st_size != len(data) or path.read_bytes() != data:
                    raise ConflictError("Workspace changes externally; reload required")
            except FileNotFoundError as error:
                raise ConflictError("Workspace file is removed externally; reload required") from error

    def get_record(self, locator: dict) -> dict:
        key = locator_key(locator)
        if key not in self.records:
            raise ValueError("Unknown contextual record")
        record = self.records[key]
        value = self.staged.get(key, record.value)
        applications = []
        pending = [value]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if node.get("kind") == "dgn-xdata":
                    for group in node["records"]:
                        if group["group"] == 1001 and "value" in group:
                            name = self.registered_apps.get(group["value"])
                            applications.append({"application_id": str(group["value"]), "name": name,
                                                 "electrical": name in ("BBES", "ELCO")})
                pending.extend(child for name, child in node.items() if name not in ("original", "original_identity"))
            elif isinstance(node, list):
                pending.extend(node)
        return {"record": deepcopy(record.locator), "value": deepcopy(value), "feature": record_description(value)[0],
                "registered_applications": applications, "editable_fields": list(record.editable), "access": "rw" if record.editable else "ro"}

    def load_field(self, locator: dict, pointer: str, source: Path) -> dict:
        """Load a string draft without staging or changing workspace files."""
        from .operations import load_payload

        record = self.get_record(locator)
        if pointer not in record["editable_fields"] or not isinstance(get_pointer(record["value"], pointer), str):
            raise ValueError("File loading requires an editable string field")
        payload = load_payload(source, self.limits)
        value = codecs.editor_text(payload.hex(), "hex", min(self.limits.stream, codecs.EDITOR_LIMIT))
        return {"value": value, "bytes": len(payload), "revision": self.revision}

    def export_field(self, locator: dict, pointer: str, output: Path) -> dict:
        from .operations import export_payload

        value = get_pointer(self.get_record(locator)["value"], pointer)
        if not isinstance(value, str):
            raise ValueError("File export requires a string field")
        return export_payload(output, value.encode("utf-8"), self.limits, self.folder)

    def list_records(self, cursor=0, limit=200, text="", model="", kind="") -> dict:
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid pagination")
        if not all(isinstance(value, str) and len(value) <= 4096 for value in (text, model, kind)):
            raise ValueError("Invalid filter")
        matches = []
        for key, record in self.records.items():
            self.checkpoint()
            value = self.staged.get(key, record.value)
            if kind and not contains_kind(value, kind) or model and model not in record.locator["ole_path"]:
                continue
            if text and not searchable(value, text.casefold()):
                continue
            if len(matches) >= cursor + limit + 1:
                break
            feature, preview = record_description(value)
            matches.append({"record": deepcopy(record.locator), "kind": value["kind"],
                            "feature": feature, "element_id": str(value.get("element_id", value.get("identity", {}).get("element_id", ""))),
                            "preview": preview, "access": "rw" if record.editable else "ro"})
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
            encoded(value)
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
        """Privately copy the original and capture staged workspace inputs in memory."""
        self.check_revision()
        with tempfile.TemporaryDirectory(prefix="dgn-explorer-snapshot-") as temporary:
            folder = Path(temporary) / "workspace"
            folder.mkdir(mode=0o700)
            shutil.copyfile(self.folder / "original.dgn", folder / "original.dgn")
            if codecs.file_digest(folder / "original.dgn") != self.source_hash:
                raise ConflictError("Original DGN changes during snapshot")
            yield folder, codecs.MemoryStore({name: self.pending.get(name, data) for name, data in self.files.items()})

    def pack_workspace(self, output: Path) -> dict:
        from .transactions import ownership

        output = Path(output).absolute()
        if output.exists() or output.is_symlink():
            raise ValueError("Output already exists")
        if output.resolve().is_relative_to(self.folder.resolve()):
            raise ValueError("Output must be outside the workspace")
        output.parent.mkdir(parents=True, exist_ok=True)
        with ownership(self.folder):
            report = self.validate_workspace()
            source_size = (self.folder / "original.dgn").stat().st_size
            for location, required in ((output.parent, source_size + report["decoded_bytes"]), (Path(tempfile.gettempdir()), source_size)):
                if shutil.disk_usage(location).free < required:
                    raise OSError(errno.ENOSPC, "Insufficient disk space for verified output")
            with self.snapshot() as (snapshot, store), tempfile.TemporaryDirectory(prefix=".dgn-output-", dir=output.parent) as temporary:
                provisional = Path(temporary) / "verified.dgn"
                count = codecs.rebuild(snapshot, provisional, self.limits.stream, cancel=self.cancel, store=store)
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

    def _check_record(self, record: Record, value: dict) -> None:
        original = self.original_records[locator_key(record.locator)].value
        allowed = deepcopy(original)
        for pointer in record.editable:
            replacement = get_pointer(value, pointer)
            if not compatible(get_pointer(original, pointer), replacement):
                raise ValueError("Saved property type/shape mismatch")
            replace_pointer(allowed, pointer, replacement)
        if allowed != value:
            raise ValueError("Read-only data or original snapshot changes")

    def _stream_view(self, names: tuple[str, ...], base: dict, values: dict[str, dict]) -> dict:
        stream = deepcopy(base)
        for key, value in values.items():
            record = self.records[key]
            if record.stream_pointer:
                replace_pointer(stream, record.stream_pointer, value)
            else:
                stream = deepcopy(value)
        return stream

    def _validate_baseline(self) -> None:
        """Validate saved workspace inputs against the trusted original once per load."""
        if set(self.records) != set(self.original_records):
            raise ValueError("Record identities change")
        by_stream: dict[tuple[str, ...], dict[str, dict]] = {}
        for key, record in self.records.items():
            self.checkpoint()
            self._check_record(record, record.value)
            by_stream.setdefault(tuple(record.locator["ole_path"]), {})[key] = record.value
        for entry in self.manifest["streams"]:
            self.checkpoint()
            names = tuple(entry["ole_path"])
            original = self.original_entries[names]
            if any(entry.get(field) != original[field] for field in ("codec", "raw_sha256", "payload_sha256")):
                raise ValueError("Manifest stream fingerprint/codec mismatch")
            for field in ("prefix", "suffix"):
                if (field in entry) != (field in original):
                    raise ValueError("Framing changes are not supported by the editor")
                if field in entry and codecs.digest(encoded(parse_json(self.files[entry[field]]))) != original[field + "_sha256"]:
                    raise ValueError("Framing changes are not supported by the editor")
            if self._stream_view(names, self.original_streams[names], by_stream.get(names, {})) != self.streams[names]:
                raise ValueError("Stream structure changes")
            size = len(encoded(self.streams[names]))
            if size > self.limits.stream:
                raise ValueError("Encoded stream limit exceeded")
            self._encoded_sizes[names] = size

    def validate_workspace(self) -> dict:
        """Validate staged replacements; unstaged inputs were verified when loaded."""
        if set(self.records) != set(self.original_records) or set(self.staged) - set(self.records):
            raise ValueError("Record identities change")
        staged_streams: dict[tuple[str, ...], dict[str, dict]] = {}
        for key, value in self.staged.items():
            self.checkpoint()
            record = self.records[key]
            self._check_record(record, value)
            staged_streams.setdefault(tuple(record.locator["ole_path"]), {})[key] = value
        total = 0
        for entry in self.manifest["streams"]:
            self.checkpoint()
            names = tuple(entry["ole_path"])
            if names in staged_streams:
                size = len(encoded(self._stream_view(names, self.streams[names], staged_streams[names])))
                if size > self.limits.stream:
                    raise ValueError("Encoded stream limit exceeded")
            else:
                size = self._encoded_sizes[names]
            total += size
            if total > self.limits.aggregate:
                raise ValueError("Aggregate encoded limit exceeded")
        return {"valid": True, "records": len(self.records), "decoded_bytes": total, "application_validation": "not performed"}


def open_workspace(folder: Path, limits: Limits | None = None, cancel=None) -> Workspace:
    return Workspace(folder, limits, cancel)