"""Data-driven policy boundary tests with synthetic artifacts, no downloads."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from dgn_explorer.codecs import digest
from dgn_explorer.policy import CANONICAL, check, utc
from prepare_dependencies import unchanged_advisories, verify_metadata


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        self.artifact = {"filename": "synthetic.bin", "sha256": digest(b"test"), "url": "https://files.pythonhosted.org/test/synthetic.bin", "version_published": (self.now - timedelta(days=40)).isoformat(), "artifact_published": (self.now - timedelta(days=31)).isoformat(), "version_evidence": "synthetic test metadata", "artifact_evidence": "synthetic test metadata"}
        (self.root / "synthetic.bin").write_bytes(b"test")
        review = {"approved": True, "by": "test-reviewer", "evidence": "synthetic test evidence"}
        self.component = {"name": "olefile", "version": "0.47", "scope": "runtime", "upstream": CANONICAL["olefile"], "established": True, "identity_evidence": "https://example.invalid/test", "security_contact": "synthetic", "purpose": "test", "platform": "test", "abi": "test", "withdrawn": False, "yanked": False, "dependencies": [], "artifacts": [self.artifact], "approval": {"decision": "approved", "by": "test-reviewer", "at": self.now.isoformat()}, "security": {"verdict": "clear", "by": "test-reviewer", "checked_at": self.now.isoformat(), "sources": ["https://example.invalid/upstream", "https://example.invalid/database"]}, "license": deepcopy(review), "provenance": deepcopy(review), "native_inventory": deepcopy(review)}
        self.manifest = {"schema": "dgn-explorer.approvals-v1", "components": [self.component]}

    def test_exact_boundary_and_younger_artifact(self):
        self.assertEqual(check(self.manifest, self.root, self.now)["admitted_components"], 1)
        for field in ("artifact_published", "version_published"):
            with self.subTest(field=field):
                original = self.artifact[field]
                self.artifact[field] = (self.now - timedelta(days=31) + timedelta(microseconds=1)).isoformat()
                with self.assertRaisesRegex(ValueError, "age gate"):
                    check(self.manifest, self.root, self.now)
                self.artifact[field] = original

    def test_missing_evidence_fork_hash_and_advisories(self):
        changes = [("upstream", "https://example.invalid/fork"), ("yanked", True), ("withdrawn", True), ("version", "0.48rc1"), ("dependencies", ["unapproved"])]
        for field, value in changes:
            manifest = deepcopy(self.manifest)
            manifest["components"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check(manifest, self.root, self.now)
        for review in ("license", "provenance", "native_inventory"):
            manifest = deepcopy(self.manifest)
            manifest["components"][0][review]["approved"] = False
            with self.subTest(review=review), self.assertRaises(ValueError):
                check(manifest, self.root, self.now)
        for field, value in (("verdict", "applicable"), ("checked_at", (self.now - timedelta(days=8)).isoformat()), ("sources", [])):
            manifest = deepcopy(self.manifest)
            manifest["components"][0]["security"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check(manifest, self.root, self.now)
        (self.root / "synthetic.bin").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            check(self.manifest, self.root, self.now)

    def test_non_applicability_requires_technical_evidence(self):
        security = self.component["security"]
        security["verdict"] = "not-applicable"
        security["advisories"] = ["synthetic-advisory"]
        security["justification"] = "Synthetic reviewed application has no affected input or sink."
        self.assertTrue(check(self.manifest, self.root, self.now)["artifacts_verified"])
        for field in ("advisories", "justification"):
            original = security.pop(field)
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                check(self.manifest, self.root, self.now)
            security[field] = original

    def test_narrow_official_security_exception(self):
        self.artifact["artifact_published"] = (self.now - timedelta(days=1)).isoformat()
        exception = {"kind": "official-security-fix", "official": True, "advisory": "synthetic", "affected_versions": "test", "fixed_version": "0.47", "fix_evidence": "synthetic", "relevance": "test", "narrowest_fix": True, "artifact_sha256": self.artifact["sha256"], "approver": "test-security-reviewer", "requester": "test-requester", "owner": "test-owner", "approved_at": self.now.isoformat(), "follow_up": (self.now + timedelta(days=31)).isoformat(), "reviewed_at": self.now.isoformat(), "regression_tests": "pass", "packaged_tests": "pass"}
        self.artifact["exception"] = exception
        self.assertTrue(check(self.manifest, self.root, self.now)["artifacts_verified"])
        for field, value in (("official", False), ("artifact_sha256", "0" * 64), ("approver", "test-requester"), ("packaged_tests", "blocked"), ("fixed_version", "0.48"), ("follow_up", (self.now + timedelta(days=32)).isoformat())):
            before = exception[field]
            exception[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check(self.manifest, self.root, self.now)
            exception[field] = before

    def test_no_admissions_timezone_and_release(self):
        for timestamp in ("2026-10-09", "2026-10-09T01:00:00+01:00"):
            with self.assertRaises(ValueError):
                utc(timestamp)
        with self.assertRaisesRegex(ValueError, "No components"):
            check({"schema": "dgn-explorer.approvals-v1", "components": []}, self.root, self.now)
        with self.assertRaisesRegex(ValueError, "CPython"):
            check(self.manifest, self.root, self.now, release=True)

    def test_exact_matched_qt_versions(self):
        self.component["name"] = "PySide6-Essentials"
        self.component["upstream"] = CANONICAL["pyside6-essentials"]
        self.component["version"] = "6.11.2"
        with self.assertRaisesRegex(ValueError, "match exactly"):
            check(self.manifest, self.root, self.now)

        runtime = deepcopy(self.component)
        runtime["name"] = "shiboken6"
        self.manifest["components"].append(runtime)
        self.assertEqual(check(self.manifest, self.root, self.now)["admitted_components"], 2)
        runtime["version"] = "6.11.1"
        with self.assertRaisesRegex(ValueError, "match exactly"):
            check(self.manifest, self.root, self.now)

    def test_development_admission_is_not_release_approval(self):
        self.manifest["admission_scope"] = "development-only"
        self.assertTrue(check(self.manifest, self.root, self.now)["artifacts_verified"])
        with self.assertRaisesRegex(ValueError, "Development-only"):
            check(self.manifest, self.root, self.now, release=True)
        self.manifest["admission_scope"] = "unknown"
        with self.assertRaisesRegex(ValueError, "Unknown admission scope"):
            check(self.manifest, self.root, self.now)

    def test_ci_refresh_rejects_changed_advisories(self):
        unchanged_advisories({}, {"vulns": []})
        advisory = {"id": "synthetic", "affected": ["test"]}
        unchanged_advisories({"vulns": [advisory]}, {"vulns": [deepcopy(advisory)]})
        with self.assertRaisesRegex(ValueError, "source review"):
            unchanged_advisories({}, {"vulns": [advisory]})
        with self.assertRaisesRegex(ValueError, "source review"):
            unchanged_advisories({"vulns": [advisory]}, {"vulns": [{"id": "synthetic", "affected": ["changed"]}]})

    def test_ci_registry_recheck_rejects_yanks_hashes_and_young_artifacts(self):
        artifact = self.artifact
        entry = {"filename": artifact["filename"], "url": artifact["url"], "digests": {"sha256": artifact["sha256"]}, "yanked": False, "upload_time_iso_8601": (self.now - timedelta(days=31)).isoformat()}
        metadata = {"info": {"version": self.component["version"]}, "urls": [entry]}
        verify_metadata(self.component, artifact, metadata, self.now)
        for field, value in (("yanked", True), ("digests", {"sha256": "0" * 64}), ("upload_time_iso_8601", self.now.isoformat())):
            changed = deepcopy(metadata)
            changed["urls"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_metadata(self.component, artifact, changed, self.now)


if __name__ == "__main__":
    unittest.main()