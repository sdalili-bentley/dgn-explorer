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


class UsageError(Exception):
    def __init__(self, message: str, usage: str, prog: str):
        super().__init__(message)
        self.usage, self.prog = usage, prog


class Parser(argparse.ArgumentParser):
    """Raises usage errors so JSON callers receive a versioned envelope."""

    def error(self, message):
        raise UsageError(message, self.format_usage(), self.prog)


def bounded_int(minimum: int, maximum: int | None = None):
    def parse(text: str) -> int:
        try:
            value = int(text, 10)
        except ValueError:
            raise argparse.ArgumentTypeError("must be a decimal integer") from None
        if value < minimum or maximum is not None and value > maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}" if maximum is not None else f"must be at least {minimum}")
        return value
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(description="DGN Explorer: local structure and metadata editor")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--json", action="store_true", help="Versioned JSON result envelope")
    parser.add_argument("--max-mib", type=bounded_int(1, 1024 * 1024), default=128)
    parser.add_argument("--aggregate-mib", type=bounded_int(1, 1024 * 1024 * 1024), default=2048)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
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
            command.add_argument("--limit", type=bounded_int(1, 1000), default=100 if name == "search" else 200)
            command.add_argument("--cursor", type=bounded_int(0), default=0)
            command.add_argument("--model", default="")
            command.add_argument("--kind", default="", help="Exact record or nested payload kind, e.g. dgn-tag, dgn-table-entry, dgn-xml-fragment")
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
    try:
        arguments = parser.parse_args(argv)
    except UsageError as error:
        if machine:
            print(json.dumps(envelope(None, error={"code": 2, "message": "Usage error: " + str(error)}), ensure_ascii=True))
            return 2
        sys.stderr.write(error.usage)
        sys.stderr.write(f"{error.prog}: error: {error}\n")
        raise SystemExit(2) from None
    operation = arguments.command
    try:
        limits = Limits(stream=arguments.max_mib * 1024 * 1024, aggregate=arguments.aggregate_mib * 1024 * 1024)
        parameters = vars(arguments).copy()
        for key in ("command", "max_mib", "aggregate_mib", "dry_run", "json"):
            parameters.pop(key, None)
        if parameters.get("patch") is not None:
            with parameters["patch"].open("rb") as handle:
                data = handle.read(limits.patch + 1)
            if len(data) > limits.patch:
                raise ValueError("Patch input exceeds size limit")
            parameters["patch"] = parse_json(data)
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