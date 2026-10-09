"""Verify installed build identities and record preview provenance/notices."""

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def write_receipt(manifest_path, bundle):
    root = Path(__file__).parent
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if sys.version_info[:3] != (3, 14, 3):
        raise ValueError("Portable builds require the reviewed CPython 3.14.3 runtime")
    components = []
    for component in manifest["components"]:
        actual = version(component["name"])
        if actual != component["version"]:
            raise ValueError(f"Installed {component['name']} differs from its approved version")
        components.append({"name": component["name"], "version": actual, "scope": component["scope"]})
    sources = sorted([*root.glob("*.py"), *root.glob("*.spec"), *root.glob("*.ps1"), *root.glob("requirements*.lock"), *root.glob("pyproject.toml"), *root.glob("dgn_explorer/*.py")])
    receipt = {"profile": "development-preview", "python": sys.version, "components": components, "runner_image": os.environ.get("ImageVersion"), "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root)), "inputs": {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}
    destination = Path(bundle)
    destination.mkdir(parents=True, exist_ok=True)
    notices = destination / "licenses"
    notices.mkdir(exist_ok=True)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", notices / "CPython-3.14.3-LICENSE.txt")
    (destination / "build-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("bundle", type=Path)
    arguments = parser.parse_args()
    write_receipt(arguments.manifest, arguments.bundle)