"""Shared command dispatcher for CLI and backend workers."""

from pathlib import Path
import errno
import os
import shutil
from stat import S_ISREG
import tempfile

from . import codecs
from .workspace import CancelledError, Limits, Workspace, get_pointer, json_bytes, locator_key, parse_json, record_description


def load_payload(source: Path, limits: Limits | None = None) -> bytes:
    """Bounded passive file import; never interpret or activate file content."""
    limit = min((limits or Limits()).stream, codecs.EDITOR_LIMIT)
    source = Path(source)
    if not S_ISREG(source.stat().st_mode):
        raise ValueError("Load File requires a regular file")
    with source.open("rb") as stream:
        if not S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Load File requires a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"File exceeds editor limit ({limit:,} bytes)")
    return data


def export_payload(output: Path, data: bytes, limits: Limits | None = None, workspace: Path | None = None) -> dict:
    """Publish a new payload file exclusively, outside a protected workspace."""
    output = Path(output).absolute()
    if workspace is not None and output.resolve().is_relative_to(Path(workspace).resolve()):
        raise ValueError("Export destination must be outside the workspace")
    if len(data) > min((limits or Limits()).stream, codecs.EDITOR_LIMIT):
        raise ValueError("Export payload exceeds editor limit")
    if output.exists() or output.is_symlink():
        raise ValueError("Export destination already exists; choose a new file")
    with output.open("xb") as destination:
        identity = os.fstat(destination.fileno())
        try:
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
            destination.close()
        except BaseException:
            try:
                destination.close()
            finally:
                try:
                    current = output.stat()
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                        output.unlink()
            raise
    return {"output": str(output), "bytes": len(data)}


def import_dgn(source: Path, folder: Path, limits: Limits, cancel=lambda: False, bytes_mode="escaped") -> dict:
    source, folder = Path(source).absolute(), Path(folder).absolute()
    if folder.exists() or folder.is_symlink():
        raise ValueError("Import destination already exists")
    folder.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with codecs.open_dgn(source) as ole:
        for names in ole.listdir():
            if cancel():
                raise CancelledError("Import cancelled")
            if ole.get_size(names) > limits.stream:
                raise ValueError("Stored stream limit exceeded")
            total += len(codecs.decode_stream(names, ole.openstream(names).read(), limits.stream)[1])
            if total > limits.aggregate:
                raise ValueError("Aggregate decoded limit exceeded")
    if shutil.disk_usage(folder.parent).free < source.stat().st_size * 2 + total * 8:
        raise OSError(errno.ENOSPC, "Insufficient temporary disk space")
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
            bounded = len(node.encode("utf-8")) <= codecs.EDITOR_LIMIT if isinstance(node, str) else len(json_bytes(node)) <= codecs.EDITOR_LIMIT
            fields.append({"pointer": pointer, "value": node if bounded else "<value exceeds editor limit>", "saved_value": get_pointer(record.value, pointer) if bounded else None, "editable": bounded and pointer in record.editable})

    visit(value)
    for index, application in enumerate(result["registered_applications"]):
        fields.append({"pointer": f"/registered_applications/{index}", "value": application,
                       "saved_value": application, "editable": False})
    raw = codecs.view_bytes(value)
    page = raw[offset:offset + 4096]
    return {"record": locator, "kind": value["kind"], "feature": record_description(value)[0], "fields": fields, "revision": session.revision,
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
        if operation == "load-field":
            return session.load_field(arguments["record"], arguments["pointer"], Path(arguments["source"]))
        if operation == "export-field":
            return session.export_field(arguments["record"], arguments["pointer"], Path(arguments["output"]))
        if operation == "export-bytes":
            page = record_summary(session, arguments["record"], arguments.get("offset", 0))["bytes"]
            return export_payload(Path(arguments["output"]), bytes.fromhex(page["hex"]), limits, session.folder)
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