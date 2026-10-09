"""Relocated, sanitized-environment smoke tests for the actual Windows bundle."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_support import create_workspace


def verify(bundle, report):
    bundle, report = Path(bundle).absolute(), Path(report).absolute()
    plugins = bundle / "_internal" / "PySide6" / "plugins"
    for path in plugins.rglob("*.dll"):
        relative = path.relative_to(plugins).as_posix()
        if relative != "platforms/qwindows.dll" and not relative.startswith("styles/"):
            raise AssertionError(f"Unreviewed optional Qt plugin: {relative}")
    report.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for name in list(environment):
        if name.startswith(("PYTHON", "QT_", "PYSIDE", "SHIBOKEN")):
            environment.pop(name)
    system_root = os.environ["SystemRoot"]
    environment["PATH"] = os.pathsep.join([str(Path(system_root) / "System32"), system_root])
    with tempfile.TemporaryDirectory(prefix="dgn-relocated-") as temporary:
        root = Path(temporary)
        moved = root / "relocated with spaces" / "DGN-Explorer"
        shutil.copytree(bundle, moved)
        source_workspace = create_workspace(root)
        source = source_workspace / "original.dgn"
        original = source.read_bytes()
        workspace, output = root / "unpacked", root / "unchanged.dgn"
        backend = moved / "dgn-explorer.exe"

        def run(*arguments):
            completed = subprocess.run([str(backend), *map(str, arguments)], cwd=root, env=environment, capture_output=True, text=True, timeout=90)
            if completed.returncode:
                raise RuntimeError(f"Packaged CLI fails: {completed.stderr}")
            return completed.stdout

        run("--help")
        run("unpack", source, workspace)
        run("validate", workspace)
        run("pack", workspace, output)
        if output.read_bytes() != original or source.read_bytes() != original:
            raise AssertionError("Packaged no-edit roundtrip is not byte-identical")
        gui_report = report.with_name(report.stem + "-gui.json")
        completed = subprocess.run([str(moved / "dgn-explorer-gui.exe"), "--self-test", str(gui_report)], cwd=root, env=environment, timeout=120)
        gui = json.loads(gui_report.read_text(encoding="utf-8")) if gui_report.exists() else {}
        if completed.returncode or not gui.get("success") or not gui.get("frozen"):
            raise RuntimeError(f"Packaged GUI fails: {gui}")
        result = {"success": True, "relocated": True, "python_path_removed": True, "no_edit_byte_identical": True, "original_preserved": True, "gui": gui}
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    inventory = [{"path": str(path.relative_to(bundle)).replace("\\", "/"), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(bundle.rglob("*")) if path.is_file()]
    report.with_name("portable-inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--report", type=Path, default=Path("build/portable-verification.json"))
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.bundle, arguments.report), indent=2))


if __name__ == "__main__":
    main()