"""One operation per process, bounded JSON stdio and cooperative cancellation."""

import json
import os
import sys
import threading

from .cli import error_details
from .operations import execute
from .workspace import Limits, parse_json


PROTOCOL = "dgn-explorer.worker-v1"
MESSAGE_LIMIT = 16 * 1024 * 1024
ARGUMENTS = {
    "import": {"source", "folder", "bytes_mode"}, "inspect": {"source"},
    "open": {"folder", "patch", "cursor", "limit", "text", "model", "kind"},
    "list": {"folder", "patch", "cursor", "limit", "text", "model", "kind"},
    "search": {"folder", "patch", "cursor", "limit", "text", "model", "kind"},
    "show": {"folder", "patch", "record", "summary", "offset"}, "validate": {"folder", "patch"},
    "load-field": {"folder", "record", "pointer", "source"},
    "export-field": {"folder", "patch", "record", "pointer", "output"},
    "export-bytes": {"folder", "patch", "record", "offset", "output"},
    "journal": {"folder", "patch"},
    "diff": {"folder", "patch"}, "apply": {"folder", "patch", "approve"},
    "pack": {"folder", "patch", "output"},
}


def validate_request(request: dict) -> None:
    if not isinstance(request, dict) or set(request) != {"protocol", "request_id", "operation", "arguments"} or request["protocol"] != PROTOCOL:
        raise ValueError("Invalid worker envelope")
    if not isinstance(request["request_id"], str) or not 1 <= len(request["request_id"]) <= 128:
        raise ValueError("Invalid worker request ID")
    operation = request["operation"]
    if operation not in ARGUMENTS or not isinstance(request["arguments"], dict) or not set(request["arguments"]) <= ARGUMENTS[operation]:
        raise ValueError("Invalid worker operation/arguments")


def run(request: dict, emit, cancel=lambda: False) -> int:
    request_id = request.get("request_id", "invalid") if isinstance(request, dict) else "invalid"
    def event(name, payload):
        message = {"protocol": PROTOCOL, "request_id": request_id, "event": name, "payload": payload}
        if len(json.dumps(message, ensure_ascii=True, allow_nan=False).encode()) > MESSAGE_LIMIT:
            raise ValueError("Worker message exceeds limit")
        emit(message)

    try:
        validate_request(request)
        event("progress", {"stage": "starting"})
        result = execute(request["operation"], request["arguments"], Limits(), cancel)
        event("completed", result)
        return 0
    except Exception as error:
        code, message = error_details(error)
        event("failed", {"code": code, "message": message})
        return code


def main() -> int:
    request_id = "invalid"
    com = None
    try:
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = sys.stdin.buffer.read1(min(65536, MESSAGE_LIMIT + 1 - len(buffer)))
            if not chunk:
                raise ValueError("Incomplete worker request")
            buffer.extend(chunk)
            if len(buffer) > MESSAGE_LIMIT and b"\n" not in buffer:
                raise ValueError("Oversized worker request")
        raw, _, remainder = buffer.partition(b"\n")
        if len(raw) + 1 > MESSAGE_LIMIT:
            raise ValueError("Oversized worker request")
        request = parse_json(raw)
        validate_request(request)
        request_id = request["request_id"]
        cancelled = threading.Event()

        def read_cancel():
            pending = bytearray(remainder)
            try:
                while b"\n" not in pending:
                    chunk = os.read(sys.stdin.fileno(), min(65536, MESSAGE_LIMIT + 1 - len(pending)))
                    if not chunk:
                        return
                    pending.extend(chunk)
                    if len(pending) > MESSAGE_LIMIT:
                        raise ValueError("Oversized cancellation message")
                signal = parse_json(pending.partition(b"\n")[0])
                if signal == {"protocol": PROTOCOL, "request_id": request_id, "event": "cancel"}:
                    cancelled.set()
            except Exception:
                cancelled.set()

        threading.Thread(target=read_cancel, daemon=True).start()
        if sys.platform == "win32":
            try:
                import pythoncom

                com = pythoncom
                com.CoInitialize()
            except ImportError:
                pass

        def emit(message):
            print(json.dumps(message, ensure_ascii=True, allow_nan=False), flush=True)

        return run(request, emit, cancelled.is_set)
    except Exception as error:
        code, message = error_details(error)
        print(json.dumps({"protocol": PROTOCOL, "request_id": request_id, "event": "failed", "payload": {"code": code, "message": message}}), flush=True)
        return code
    finally:
        if com is not None:
            com.CoUninitialize()