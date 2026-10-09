"""Offline admission evidence checker. Never resolves or installs packages."""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

from .codecs import file_digest
from .workspace import json_bytes, parse_json


CANONICAL = {
    "cpython": "https://github.com/python/cpython",
    "pyside6-essentials": "https://code.qt.io/cgit/pyside/pyside-setup.git/",
    "shiboken6": "https://code.qt.io/cgit/pyside/pyside-setup.git/",
    "olefile": "https://github.com/decalage2/olefile",
    "pywin32": "https://github.com/mhammond/pywin32",
    "setuptools": "https://github.com/pypa/setuptools",
    "pip": "https://github.com/pypa/pip",
    "pyinstaller": "https://github.com/pyinstaller/pyinstaller",
    "qtbase": "https://code.qt.io/cgit/qt/qtbase.git/",
    "coverage": "https://github.com/nedbat/coveragepy",
    "wheel": "https://github.com/pypa/wheel",
    "altgraph": "https://github.com/ronaldoussoren/altgraph",
    "packaging": "https://github.com/pypa/packaging",
    "pefile": "https://github.com/erocarrera/pefile",
    "pyinstaller-hooks-contrib": "https://github.com/pyinstaller/pyinstaller-hooks-contrib",
    "pywin32-ctypes": "https://github.com/enthought/pywin32-ctypes",
}
ARTIFACT_HOSTS = {"files.pythonhosted.org", "www.python.org", "download.qt.io"}


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must include UTC timezone")
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def evidence_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None


def normalize(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def check(manifest: dict, wheelhouse: Path, now: datetime | None = None, release=False) -> dict:
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None and now.utcoffset() == timedelta(0), "Evaluation time must be UTC")
    require(manifest.get("schema") == "dgn-explorer.approvals-v1", "Unknown approval schema")
    admission_scope = manifest.get("admission_scope", "release-eligible")
    require(admission_scope in ("development-only", "release-eligible"), "Unknown admission scope")
    require(not release or admission_scope != "development-only", "Development-only evidence cannot approve a release")
    components = manifest.get("components")
    require(isinstance(components, list) and bool(components), "No components are admitted")
    identities = {}
    for component in components:
        name = normalize(component["name"])
        require(name not in identities, "Duplicate component")
        require(name in CANONICAL and component["upstream"] == CANONICAL[name], "Unrecognized canonical upstream; review policy extension first")
        require(component["established"] is True and evidence_url(component["identity_evidence"]) and component["security_contact"], "Missing upstream identity/security evidence")
        require(re.fullmatch(r"\d+(?:\.\d+)*(?:\.post\d+)?", component["version"]), "Prerelease or moving version is not admitted")
        require(component["scope"] in ("runtime", "build", "dev", "native"), "Unknown component scope")
        require(component["purpose"] and component["platform"] and component["abi"], "Missing necessity/platform/ABI")
        require(component["withdrawn"] is False and component["yanked"] is False, "Withdrawn/yanked release")
        approval = component["approval"]
        require(approval["decision"] == "approved" and approval["by"] and utc(approval["at"]) <= now, "Missing or future admission approval")
        for category in ("license", "provenance", "native_inventory"):
            review = component[category]
            require(review["approved"] is True and review["by"] and review["evidence"], f"Missing {category} review")
        security = component["security"]
        require(security["verdict"] in ("clear", "not-applicable") and security["by"], "Applicable or unknown vulnerability status")
        require(len(security["sources"]) >= 2 and all(evidence_url(url) for url in security["sources"]), "Upstream and recognized database evidence required")
        checked = utc(security["checked_at"])
        require(timedelta(0) <= now - checked <= timedelta(days=7), "Stale/future advisory evidence")
        if security["verdict"] == "not-applicable":
            require(security["justification"] and security["advisories"], "Missing technical non-applicability evidence")
        artifacts = component["artifacts"]
        require(isinstance(artifacts, list) and bool(artifacts), "Exact artifacts are required")
        for artifact in artifacts:
            filename = artifact["filename"]
            require(Path(filename).name == filename and not any(char in filename for char in ("/", "\\", ":")), "Unsafe artifact filename")
            require(re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]), "Invalid SHA-256")
            parsed = urlparse(artifact["url"])
            require(evidence_url(artifact["url"]) and parsed.hostname in ARTIFACT_HOSTS and parsed.path.endswith("/" + filename), "Unofficial artifact source")
            require(artifact["version_evidence"] and artifact["artifact_evidence"], "Publication evidence is missing")
            published = max(utc(artifact["version_published"]), utc(artifact["artifact_published"]))
            require(published <= now, "Future publication timestamp")
            if now < published + timedelta(days=31):
                exception = artifact.get("exception", {})
                require(exception.get("kind") == "official-security-fix" and exception.get("official") is True, "Artifact does not meet 31-full-day age gate")
                require(exception["advisory"] and exception["affected_versions"] and exception["fixed_version"] == component["version"] and exception["fix_evidence"] and exception["relevance"] and exception["narrowest_fix"] is True, "Missing security-fix evidence")
                require(exception["artifact_sha256"] == artifact["sha256"], "Exception does not cover this artifact")
                require(exception["approver"] and exception["approver"] != exception["requester"] and exception["owner"], "Independent security approver required")
                approved_at, follow_up = utc(exception["approved_at"]), utc(exception["follow_up"])
                require(approved_at <= now <= follow_up <= approved_at + timedelta(days=31), "Expired or excessive exception deadline")
                require(now.date() == checked.date() and timedelta(0) <= now - utc(exception["reviewed_at"]) <= timedelta(days=7), "Security exception review is stale")
                require(exception["regression_tests"] == "pass" and exception["packaged_tests"] == "pass", "Security exception lacks regression/packaged evidence")
            path = wheelhouse / filename
            require(path.is_file() and not path.is_symlink(), "Approved artifact is unavailable")
            require(file_digest(path) == artifact["sha256"], "Artifact SHA-256 mismatch")
        identities[name] = component
    for component in components:
        require(all(normalize(parent) in identities for parent in component["dependencies"]), "Unadmitted transitive/native dependency")
    if "pyside6-essentials" in identities:
        require("shiboken6" in identities and identities["pyside6-essentials"]["version"] == identities["shiboken6"]["version"], "Qt binding/runtime versions must match exactly")
    if release:
        require("cpython" in identities, "Release lacks approved CPython artifact")
        require(manifest.get("release_approval", {}).get("approved") is True and manifest["release_approval"].get("by"), "Release owner approval is missing")
    return {"admitted_components": len(components), "artifacts_verified": True, "release": release}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = parse_json(args.manifest.read_bytes())
        print(json_bytes(check(manifest, args.wheelhouse, release=args.release)).decode(), end="")
        return 0
    except Exception as error:
        print(f"Dependency admission blocked: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())