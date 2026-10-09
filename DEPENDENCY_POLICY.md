# Dependency Policy

Applies to direct/transitive Python packages, CPython, bundled native libraries,
Qt plugins, build backends/hooks, test tools, CI actions and containers. Existing
pins are not grandfathered. The offline evidence/artifact checker and Windows
CPython 3.14 development locks exist; release approval and full build integration
remain pending. See
[candidate evidence](DEPENDENCY_CANDIDATES.md).

## Admission Rules

| Gate | Requirement |
|------|-------------|
| Upstream | Established official vendor/foundation/project, active maintenance, public history and security contact |
| Identity | Official docs confirm canonical source, package and publisher; review unexplained maintainer changes |
| Distribution | No unofficial forks, altered repackaging, lookalikes or arbitrary VCS installs; byte-identical approved caches are allowed |
| Necessity | Justify each component; prefer standard library/existing approved components and minimal Qt Widgets |
| Age | Version and exact artifact each qualify for at least 31 complete 24-hour days, UTC |
| Security | No unresolved applicable vulnerability, malware, withdrawal or provenance alert; scanner silence is not proof |
| Artifact | Exact name/version, filename, OS/architecture/ABI, source URL and SHA-256 approved |
| Provenance/license | Review signatures/attestations when available; record and approve gaps; licenses permit distribution |
| Build | Approved artifacts only, offline builds, no uncontrolled downloads/hooks or runtime installs |

Candidate families: official CPython, PySide6-Essentials with exactly matched
shiboken6, olefile, pywin32, PyInstaller and required official build/test tools.
This shortlist does not approve versions or transitive/native components. Addons,
WebEngine, third-party themes and extra plugins require demonstrated need and all
gates. Popularity, hashes, age and signing alone do not establish benign code.

## Age and Exceptions

`effective_publication = max(version_publication_utc, artifact_publication_utc)`.
Eligibility requires `evaluation_utc >= effective_publication + 31 days`.
Use authoritative release metadata and exact registry upload timestamps, not local
download/mirror times. Use the later verified conflicting timestamp and record
why; missing evidence blocks admission. Check each platform artifact, transitive
package and bundled native component independently. Rebuilds/reuploads need new
approval. Reject yanked, withdrawn and prerelease versions for production.

Do not mix incompatible Qt binding/runtime versions to satisfy age. If no eligible
compatible version exists, defer or use an approved alternative. Convenience,
deadlines, cosmetic/compatibility fixes and ordinary bug fixes are not exceptions.

The sole age exception is an official stable release fixing a known vulnerability.
All other gates still apply. Record advisory/affected/fixed versions, relevance,
reviewed fix evidence, narrowest supported fix, exact artifacts/hashes, regression
and packaged tests, named security approver, approval time, owner and follow-up.
The requester cannot silently self-approve. Necessary younger matched dependencies
need individual evidence/approval; unrelated resolver updates inherit nothing.
No fake advisory, unofficial patched wheel or moving branch qualifies.
Review exceptions weekly and follow up within 31 days; close with ordinary age
qualification or replacement. New bytes/versions require new admission.

## Vulnerabilities and Maintenance

Check upstream advisories plus recognized databases for every component, including
all bundled native modules, not only imported ones. Record sources, time and
affected/fixed evidence. Non-applicability requires technical justification and
security approval. If no usable fix exists, remove/replace or pause the feature;
never retain an applicable vulnerable version merely for age qualification.
Monitor deployed versions weekly; review dependency currency monthly and triage
relevant fixes immediately. Release evidence is at most seven days old, with a
same-day urgent-exception check. Failed/unavailable metadata is not a clean result.

## Locks and Builds

- Separate runtime/build/dev locks pin every resolved identity/version and approved
  SHA-256, including conditional Windows and native components; record target ABI.
- Acquire/review online, then admit only approved artifacts to the wheelhouse.
  Install offline with `--require-hashes --only-binary=:all: --no-index`.
- Use one approved source; never mix private/public indexes via `--extra-index-url`.
- Provision reviewed build tools explicitly; disable uncontrolled build isolation.
  Developer caches/environments are not approved release inputs. Source builds
  require separate approved reproducible-build evidence, not arbitrary hooks.
- Pin CI actions to reviewed immutable commits and images to digests. No mutable
  `latest` or silent Python/tool upgrades. Include publication-age evidence.
- Package minimal approved modules/plugins. Record source revision, lock digest,
  component inventory/SBOM, output hashes, signing and license notices. Retain
  approved rollback artifacts and distribute through an approved channel.

## Approval Records and Gate

The [JSON manifest](dependency-approvals.json) records thirteen development-only
admissions. Reviews are attributed to GitHub Copilot as automated technical checks
under the user's install authorization, not human security/legal sign-off.
`admission_scope: development-only` is rejected by the release gate. Distribution
license/notices review and independent release-owner approval remain required;
the official-security-fix age exception still needs an independent named approver.
For a matching advisory, record the affected bundled code and its input/sink
prerequisites separately from current application reachability. Presence alone
does not establish applicability. A `not-applicable` decision retains advisory
IDs, sources, technical justification and reviewer, plus feature-change re-review
requirements. Tests guard the reviewed boundary; they do not prove that the
library is patched or vulnerability-free. Vendor-supported mitigations need
actual runtime regression evidence. See the [Qt decision](DEPENDENCY_CANDIDATES.md).
The admission record needs canonical identity/type/upstream, scope/parents/
purpose, exact artifact/platform/ABI/URL/hash, both publication timestamps/evidence,
eligibility, vulnerability verdict/sources/time, provenance/license approvals,
approver/time/policy version/decision and any exception's covered artifacts/tests/
owner/deadline. Offline gates validate the approved evidence bundle and locks,
never resolve new packages. Any changed lock/artifact set requires fresh approval.

Fail on missing evidence, young artifacts without approved exceptions, applicable
vulnerabilities, forks, yanked releases, unpinned/unapproved components or wrong
hashes. Test age boundaries, timestamp disagreement, missing evidence, young
platform/transitive/native files, hashes, lookalikes and narrowly scoped exceptions.

Before shared release assign maintainer, security approver, license reviewer and
release owner. Release approvals and full build enforcement remain pending in
[PLAN.md](PLAN.md). `python -m dgn_explorer.policy dependency-approvals.json wheelhouse`
checks the recorded evidence and bytes offline; it does not discover or grant approval.