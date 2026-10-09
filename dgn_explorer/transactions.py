"""Exclusive workspace ownership and recoverable multi-file publication."""

from contextlib import contextmanager
import base64
import os
from pathlib import Path
import tempfile


def sidecar(folder: Path) -> Path:
    from .workspace import confined

    confined(folder, "original.dgn")
    path = folder / ".dgn-explorer"
    if path.is_symlink() or path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("Linked session directory")
    path.mkdir(mode=0o700, exist_ok=True)
    return path


@contextmanager
def ownership(folder: Path):
    from .workspace import ConflictError

    path = sidecar(folder) / "writer.lock"
    if path.is_symlink() or path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("Linked lock file")
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ConflictError("Workspace is owned by another operation") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write(path: Path, data: bytes):
    descriptor, temporary = tempfile.mkstemp(prefix=".dgn-save-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary_path.unlink(missing_ok=True)


def recover(folder: Path, limits):
    from . import codecs
    from .workspace import confined, parse_json

    journal = sidecar(folder) / "transaction.json"
    if not journal.exists():
        return False
    if journal.is_symlink():
        raise ValueError("Linked transaction journal")
    transaction = parse_json(codecs.read_limited(journal, limits.aggregate * 3))
    if set(transaction) != {"schema", "state", "source_sha256", "files"} or transaction["schema"] != "dgn-explorer.transaction-v1" or transaction["state"] not in ("prepared", "committed"):
        raise ValueError("Invalid transaction journal")
    if codecs.file_digest(confined(folder, "original.dgn")) != transaction["source_sha256"]:
        raise ValueError("Recovery original fingerprint mismatch")
    manifest_name = "manifest.rw.json" if (folder / "manifest.rw.json").exists() else "manifest.json"
    manifest = parse_json(codecs.read_limited(confined(folder, manifest_name), limits.stream))
    reachable = set()

    def references(node, depth=0):
        if depth > limits.depth:
            raise ValueError("Recovery reference depth exceeded")
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("file", "text_file") and isinstance(value, str):
                    if value not in reachable:
                        reachable.add(value)
                        data = codecs.read_limited(confined(folder, value), limits.stream)
                        if key == "file":
                            references(parse_json(data), depth + 1)
                else:
                    references(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                references(value, depth + 1)

    for entry in manifest["streams"]:
        references({"file": entry["file"]})
    replacements = []
    seen = set()
    for item in transaction["files"]:
        if set(item) != {"file", "before", "after_sha256"} or item["file"] not in reachable or item["file"] in seen:
            raise ValueError("Invalid recovery target")
        seen.add(item["file"])
        before = base64.b64decode(item["before"], validate=True)
        path = confined(folder, item["file"])
        current_hash = codecs.file_digest(path)
        if current_hash not in (codecs.digest(before), item["after_sha256"]):
            raise ValueError("Recovery target changes externally")
        if transaction["state"] == "committed":
            if current_hash != item["after_sha256"]:
                raise ValueError("Committed transaction is incomplete")
        else:
            replacements.append((path, before))
    for path, before in replacements:
        atomic_write(path, before)
    journal.unlink()
    return True


def publish(session, fault=None):
    from . import codecs
    from .workspace import confined, json_bytes

    session.check_revision()
    session.validate_workspace()
    if not session.pending:
        return 0
    journal = sidecar(session.folder) / "transaction.json"
    transaction = {
        "schema": "dgn-explorer.transaction-v1", "state": "prepared", "source_sha256": session.source_hash,
        "files": [{"file": name, "before": base64.b64encode(session.files[name]).decode("ascii"), "after_sha256": codecs.digest(data)} for name, data in sorted(session.pending.items())],
    }
    atomic_write(journal, json_bytes(transaction))
    if fault:
        fault("prepared")
    try:
        for index, (name, data) in enumerate(sorted(session.pending.items())):
            atomic_write(confined(session.folder, name), data)
            if fault:
                fault(f"published:{index}")
        transaction["state"] = "committed"
        atomic_write(journal, json_bytes(transaction))
        if fault:
            fault("committed")
        count = len(session.pending)
        journal.unlink()
        return count
    except Exception:
        recover(session.folder, session.limits)
        raise