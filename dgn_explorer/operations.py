"""Shared command dispatcher for CLI and backend workers."""

from pathlib import Path
import os
import shutil
import tempfile

from . import codecs
from .workspace import CancelledError, Limits, Workspace, get_pointer, json_bytes, locator_key, parse_json


def import_dgn(source: Path, folder: Path, limits: Limits, cancel=lambda: False, bytes_mode="escaped") -> dict:
    source, folder = Path(source).absolute(), Path(folder).absolute()
    if folder.exists() or folder.is_symlink():
        raise ValueError("Import destination already exists")
    folder.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with codecs.ole_reader().OleFileIO(str(source)) as ole:
        for names in ole.listdir():
            if cancel():
                raise CancelledError("Import cancelled")
            if ole.get_size(names) > limits.stream:
                raise ValueError("Stored stream limit exceeded")
            total += len(codecs.decode_stream(names, ole.openstream(names).read(), limits.stream)[1])
            if total > limits.aggregate:
                raise ValueError("Aggregate decoded limit exceeded")
    if shutil.disk_usage(folder.parent).free < source.stat().st_size * 2 + total * 8:
        raise OSError("Insufficient temporary disk space")
    with tempfile.TemporaryDirectory(prefix=".dgn-import-", dir=folder.parent) as temporary:
        staging = Path(temporary) / "workspace"
        manifest = codecs.extract(source, staging, limits.stream, bytes_mode, cancel=cancel)
        if cancel():
            raise CancelledError("Import cancelled")
        if sum(path.stat().st_size for path in staging.rglob("*") if path.is_file()) > limits.aggregate:
            raise ValueError("Extracted workspace input limit exceeded")
        if folder.exists():
            raise ValueError("Import destination appears during extraction")
        if os.name != "nt":
            raise ValueError("Safe new-folder publication currently requires Windows")
        staging.rename(folder)
    return {"streams": len(manifest["streams"]), "original_sha256": manifest["original_sha256"]}


def record_summary(session: Workspace, locator: dict, offset=0) -> dict:
    import json

    if type(offset) is not int or offset < 0:
        raise ValueError("Invalid byte offset")
    result = session.get_record(locator)
    record = session.records[locator_key(locator)]
    value = result["value"]
    fields = []

    def visit(node, pointer=""):
        if len(fields) >= 2000:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                if key not in ("original", "original_identity", "editing"):
                    visit(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(node, list) and pointer not in record.editable:
            for index, child in enumerate(node):
                visit(child, pointer + f"/{index}")
        else:
            bounded = len(json_bytes(node)) <= 64 * 1024
            fields.append({"pointer": pointer, "value": node if bounded else "<value exceeds editor limit>", "saved_value": get_pointer(record.value, pointer) if bounded else None, "editable": bounded and pointer in record.editable})

    visit(value)
    raw = codecs.view_bytes(value)
    page = raw[offset:offset + 4096]
    return {"record": locator, "kind": value["kind"], "fields": fields, "revision": session.revision,
            "bytes": {"offset": offset, "size": len(raw), "hex": page.hex(" "), "escaped": json.dumps(page.decode("latin-1"), ensure_ascii=True), "next_offset": offset + 4096 if offset + 4096 < len(raw) else None}}


def execute(operation: str, arguments: dict, limits: Limits | None = None, cancel=lambda: False) -> dict:
    limits = limits or Limits()
    if operation in ("unpack", "extract", "import"):
        return import_dgn(Path(arguments["source"]), Path(arguments["folder"]), limits, cancel, arguments.get("bytes_mode", "escaped"))
    if operation == "inspect":
        return codecs.inspect_dgn(Path(arguments["source"]), limits.stream)
    with Workspace(Path(arguments["folder"]), limits, cancel) as session:
        patch = arguments.get("patch")
        if patch is not None:
            session.stage_patch(patch)
        if operation in ("open", "list", "search"):
            result = session.list_records(arguments.get("cursor", 0), arguments.get("limit", 100 if operation == "search" else 200), arguments.get("text", ""), arguments.get("model", ""), arguments.get("kind", ""))
            if operation == "open":
                result["changes"] = session.diff_workspace()["changes"]
                from .transactions import sidecar

                recovery = sidecar(session.folder) / "pending.json"
                result["recovery_patch"] = parse_json(codecs.read_limited(recovery, session.limits.patch)) if recovery.exists() and not recovery.is_symlink() else None
            return result
        if operation == "show":
            if arguments.get("summary") is True:
                return record_summary(session, arguments["record"], arguments.get("offset", 0))
            return {**session.get_record(arguments["record"]), "revision": session.revision}
        if operation == "journal":
            from .transactions import atomic_write, ownership, sidecar

            with ownership(session.folder):
                session.check_revision()
                path = sidecar(session.folder) / "pending.json"
                if path.is_symlink():
                    raise ValueError("Linked recovery journal")
                if patch is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, json_bytes(patch))
            return {"journaled": patch is not None}
        if operation == "validate":
            session.check_revision()
            return {**session.validate_workspace(), "revision": session.revision}
        if operation == "diff":
            return session.diff_workspace()
        if operation == "apply":
            if patch is None:
                raise ValueError("Patch is required")
            preview = session.diff_workspace()
            if arguments.get("approve") is True:
                saved = session.save_workspace()
                from .transactions import sidecar

                (sidecar(session.folder) / "pending.json").unlink(missing_ok=True)
                return {**saved, "applied": True}
            return {**preview, "applied": False}
        if operation in ("pack", "rebuild"):
            return session.pack_workspace(Path(arguments["output"]))
        raise ValueError("Unknown operation")