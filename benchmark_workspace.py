"""Measure synthetic workspace timings, peak Python memory and cancellation gaps.

Development evidence only: uses generated fixtures, never document data. Example:
    python benchmark_workspace.py --text-count 2000 --output build/benchmark.json
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc

from dgn_explorer.operations import execute
from dgn_explorer.workspace import Limits, Workspace, get_pointer


def measure(action, memory: bool = False) -> dict:
    """Time an action and its cancellation-poll gaps; optionally repeat it under tracemalloc."""
    polls = []

    def poll():
        polls.append(time.perf_counter())
        return False

    started = time.perf_counter()
    action(poll)
    finished = time.perf_counter()
    timeline = [started, *polls, finished]
    result = {"seconds": round(finished - started, 3), "checkpoints": len(polls),
              "max_checkpoint_gap_seconds": round(max(later - earlier for earlier, later in zip(timeline, timeline[1:])), 3)}
    if memory:
        tracemalloc.start()
        try:
            action(lambda: False)
            result["peak_python_mib"] = round(tracemalloc.get_traced_memory()[1] / 1024 / 1024, 1)
        finally:
            tracemalloc.stop()
    return result


def benchmark(root: Path, text_count: int) -> dict:
    from test_support import create_workspace

    started = time.perf_counter()
    folder = create_workspace(root, text_count=text_count)
    report = {"text_count": text_count, "fixture_seconds": round(time.perf_counter() - started, 3), "operations": {}}
    with Workspace(folder) as session:
        report["records"] = len(session.records)
        report["workspace_files"] = len(session.files)
        locator = {"ole_path": ["Dgn-Md", "#000002", "Dgn^G", "$1"], "chunk_index": max(text_count - 1, 0)}
        patch = {"schema": "dgn-explorer.patch-v1", "workspace_revision": session.revision, "operations": [
            {"record": locator, "pointer": "/string/text", "expected_value": get_pointer(session.get_record(locator)["value"], "/string/text"), "value": "Benchmark"},
        ]} if text_count else None
    operations = report["operations"]
    operations["open"] = measure(lambda cancel: Workspace(folder, Limits(), cancel).close(), memory=True)
    operations["search_absent"] = measure(lambda cancel: execute("search", {"folder": str(folder), "text": "absent text"}, Limits(), cancel))
    operations["validate"] = measure(lambda cancel: execute("validate", {"folder": str(folder)}, Limits(), cancel))
    if patch is not None:
        operations["stage_and_validate"] = measure(lambda cancel: execute("validate", {"folder": str(folder), "patch": patch}, Limits(), cancel))
        operations["pack_staged"] = measure(lambda cancel: execute("pack", {"folder": str(folder), "patch": patch, "output": str(root / "packed.dgn")}, Limits(), cancel))
    operations["import"] = measure(lambda cancel: execute("import", {"source": str(root / "input.dgn"), "folder": str(root / "imported")}, Limits(), cancel))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--text-count", type=int, default=2000, help="Text elements per model (records = 2 * count + 3)")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.text_count < 0:
        parser.error("--text-count must not be negative")
    if arguments.output and arguments.output.exists():
        parser.error(f"--output already exists: {arguments.output}")
    with tempfile.TemporaryDirectory(prefix="dgn-benchmark-") as temporary:
        report = {"python": sys.version.split()[0], "platform": sys.platform, **benchmark(Path(temporary), arguments.text_count)}
    text = json.dumps(report, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with arguments.output.open("x", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
