"""Versioned CLI entry point, independent of Qt."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .operations import execute
from .workspace import CancelledError, ConflictError, Limits, json_bytes, parse_json


def error_details(error: Exception) -> tuple[int, str]:
    if isinstance(error, (CancelledError, InterruptedError)):
        return 6, "Operation cancelled"
    if isinstance(error, ConflictError):
        return 4, str(error)
    if isinstance(error, OSError):
        return 5, "I/O failure; check file access and available disk space"
    if isinstance(error, (ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError)):
        return 3, "Invalid or unsupported input: " + (str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else type(error).__name__)
    return 7, "Verification or backend failure: " + type(error).__name__


def envelope(operation: str, result=None, error=None) -> dict:
    return {"protocol": "dgn-explorer.result-v1", "operation": operation, "success": error is None, "result": result, "warnings": [], "errors": [] if error is None else [error]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DGN Explorer: local structure and metadata editor")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--json", action="store_true", help="Versioned JSON result envelope")
    parser.add_argument("--max-mib", type=int, default=128)
    parser.add_argument("--aggregate-mib", type=int, default=2048)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, aliases in (("unpack", ["extract"]), ("pack", ["rebuild"]), ("inspect", []), ("list", []), ("show", []), ("search", []), ("validate", []), ("diff", []), ("apply", [])):
        command = commands.add_parser(name, aliases=aliases)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Versioned JSON result envelope")
        if name in ("unpack", "inspect"):
            command.add_argument("source")
        if name != "inspect":
            command.add_argument("folder")
        if name == "unpack":
            command.add_argument("--bytes-mode", choices=("escaped", "hex"), default="escaped")
        if name == "pack":
            command.add_argument("output")
            command.add_argument("--patch", type=Path)
        if name == "inspect":
            command.add_argument("--output", type=Path)
        if name in ("list", "search"):
            command.add_argument("--limit", type=int, default=100 if name == "search" else 200)
            command.add_argument("--cursor", type=int, default=0)
            command.add_argument("--model", default="")
            command.add_argument("--kind", default="")
        if name == "search":
            command.add_argument("--text", required=True)
        if name == "show":
            command.add_argument("--record", required=True)
        if name == "apply":
            command.add_argument("--patch", required=True, type=Path)
            mode = command.add_mutually_exclusive_group(required=True)
            mode.add_argument("--dry-run", action="store_true")
            mode.add_argument("--approve", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--worker"]:
        from .worker import main as worker_main

        return worker_main()
    if argv == ["gui"]:
        from .ui import main as desktop_main

        return desktop_main()
    machine = "--json" in argv
    parser = build_parser()
    arguments = parser.parse_args(argv)
    operation = arguments.command
    try:
        limits = Limits(stream=arguments.max_mib * 1024 * 1024, aggregate=arguments.aggregate_mib * 1024 * 1024)
        parameters = vars(arguments).copy()
        for key in ("command", "max_mib", "aggregate_mib", "dry_run", "json"):
            parameters.pop(key, None)
        if parameters.get("patch") is not None:
            path = parameters["patch"]
            if path.stat().st_size > limits.patch:
                raise ValueError("Patch input exceeds size limit")
            parameters["patch"] = parse_json(path.read_bytes())
        if "record" in parameters:
            parameters["record"] = parse_json(parameters["record"].encode("utf-8"))
        output = parameters.pop("output", None) if operation == "inspect" else None
        result = execute(operation, parameters, limits)
        if output is not None:
            with output.open("xb") as handle:
                handle.write(json_bytes(result))
        print(json.dumps(envelope(operation, result) if machine else result, ensure_ascii=True, allow_nan=False, indent=2))
        return 0
    except Exception as error:
        code, message = error_details(error)
        if machine:
            print(json.dumps(envelope(operation, error={"code": code, "message": message}), ensure_ascii=True))
        else:
            print(message, file=sys.stderr)
        return code