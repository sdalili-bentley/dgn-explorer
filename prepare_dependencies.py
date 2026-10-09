"""Acquire only reviewed wheels; fail closed on changed advisory evidence."""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def fetch(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"User-Agent": "DGN-Explorer-dependency-review", "Content-Type": "application/json"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def verify_metadata(component, artifact, metadata, now):
    files = metadata["urls"]
    selected = [entry for entry in files if entry["filename"] == artifact["filename"]]
    if len(selected) != 1:
        raise ValueError("Exact reviewed artifact is absent")
    entry = selected[0]
    if entry["yanked"] or entry["digests"]["sha256"] != artifact["sha256"] or entry["url"] != artifact["url"]:
        raise ValueError("Artifact is yanked or changed")
    if urlparse(entry["url"]).hostname != "files.pythonhosted.org":
        raise ValueError("Unofficial artifact host")
    publication = max(datetime.fromisoformat(item["upload_time_iso_8601"].replace("Z", "+00:00")) for item in files)
    if now - publication < timedelta(days=31):
        raise ValueError("Exact release/artifact is younger than 31 days")
    if metadata["info"]["version"] != component["version"]:
        raise ValueError("Wrong package version")
    return entry


def unchanged_advisories(baseline, current):
    def canonical(value):
        return sorted(value.get("vulns", []), key=lambda item: item["id"])
    if canonical(baseline) != canonical(current):
        raise ValueError("Advisory evidence changes; independent source review is required")


def prepare(root, now=None):
    now = now or datetime.now(timezone.utc)
    manifest = json.loads((root / "dependency-approvals.json").read_text(encoding="utf-8"))
    manifest = deepcopy(manifest)
    if manifest["admission_scope"] != "development-only":
        raise ValueError("This automation builds development previews only")
    evidence, generated = root / "dependency-evidence", root / "build" / "fresh-evidence"
    generated.mkdir(parents=True, exist_ok=True)
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir(exist_ok=True)
    for metadata_path in sorted(evidence.glob("*-pypi.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        identity = metadata["info"]
        osv_path = metadata_path.with_name(metadata_path.name.replace("-pypi.json", "-osv.json"))
        current = json.loads(fetch("https://api.osv.dev/v1/query", {"package": {"name": identity["name"], "ecosystem": "PyPI"}, "version": identity["version"]}))
        unchanged_advisories(json.loads(osv_path.read_text(encoding="utf-8-sig")), current)
        (generated / osv_path.name).write_text(json.dumps(current, indent=2), encoding="utf-8")
    for baseline_path in sorted(evidence.glob("native-*-osv.json")):
        identity, version = baseline_path.stem.removesuffix("-osv").removeprefix("native-").rsplit("-", 1)
        current = json.loads(fetch("https://api.osv.dev/v1/query", {"package": {"name": identity, "ecosystem": "OSS-Fuzz"}, "version": version}))
        unchanged_advisories(json.loads(baseline_path.read_text(encoding="utf-8-sig")), current)
        (generated / baseline_path.name).write_text(json.dumps(current, indent=2), encoding="utf-8")
    upstream = fetch("https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products").decode("utf-8")
    identifiers = sorted(set(re.findall(r"CVE-\d{4}-\d{4,}", upstream)))
    reviewed = json.loads((root / "ci-toolchain.json").read_text(encoding="utf-8"))
    if identifiers != reviewed["qt_upstream_advisories"]:
        raise ValueError("Qt upstream advisory list changes; source review is required")
    (generated / "qt-upstream-advisories.json").write_text(json.dumps(identifiers, indent=2), encoding="utf-8")
    for component in manifest["components"]:
        metadata = json.loads(fetch(component["identity_evidence"]))
        (generated / f"{component['name']}-{component['version']}-pypi.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        for artifact in component["artifacts"]:
            verify_metadata(component, artifact, metadata, now)
            destination = wheelhouse / artifact["filename"]
            data = destination.read_bytes() if destination.exists() else fetch(artifact["url"])
            if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise ValueError("Downloaded bytes differ from approved hash")
            if not destination.exists():
                destination.write_bytes(data)
        component["security"]["checked_at"] = now.isoformat()
        component["security"]["by"] = "Automated evidence refresh; unchanged prior scoped decision"
    manifest["evaluation_utc"] = now.isoformat()
    result = root / "build" / "ci-dependency-approvals.json"
    result.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    arguments = parser.parse_args()
    print(prepare(arguments.root))