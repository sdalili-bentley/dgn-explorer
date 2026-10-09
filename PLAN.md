# DGN Explorer Implementation Plan

**State:** backend/service/CLI/worker and offline policy-checker implementation
exists. Desktop source/tests and the CLI skill exist. Thirteen dependencies,
including matched Qt 6.11.2, have scoped development admission, hash locks and
offline installation. All 23 Windows Qt tests pass. The corrected decision
and lesson are in [dependency evidence](DEPENDENCY_CANDIDATES.md). Desktop workflow
workflows and a relocated frozen portable development preview pass synthetic
verification. Company-release gates remain incomplete. This tracked checkout is
the source home; GitHub preview builds are automatic on main pushes and PRs.
[README.md](README.md) documents current commands; [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md)
is mandatory. Mark tasks complete only with evidence; keep gaps/status current.

Published-baseline evidence: all 31 codec/sample tests pass using the approved local reference
fixture; without it, 17 pass and 14 skip. A separate test covers renamed package
entry points. Setuptools 83.0.0 and PyInstaller 6.22.2 are available for local
development; an offline development wheel builds and its packaged CLI help
smoke test passes. Relocated portable packaging validation passes. This is source
and development-preview publication, not company release approval.

## Completion and GitHub Automation

User authorizes completion, local portable builds, automatic GitHub Actions
builds and publication to `sdalili-bentley/dgn-explorer`. The existing standalone
checkout is the source home; audit-parent changes are not part of this push.

| Work | State | Verification |
|------|-------|--------------|
| Rejected edits | Accepted property values restore after rejection | Focused real Qt regression passes |
| Desktop workflows | Verified | 23 Qt tests; retain drafts, asynchronous save/discard/cancel, private import/recents; real save/export/reimport |
| Portable package | Verified development preview | Offline GUI/backend one-folder build; minimal Windows plugins, licenses/receipt/inventory/checksum; relocated real CLI/GUI tests |
| GitHub Actions | Implemented; remote run pending | Immutable mature actions, exact signed Python, hash locks, fail-closed fresh advisory queries; tests/build/upload on push/PR/manual runs |
| GitHub synchronization | Pending | Fetch/reconcile without reverting local changes; review staged files, commit and push; confirm remote/workflow result |

Build artifacts are development previews, not company distribution approval.
Clean-machine/native application/DPI/signing gates require their own evidence.

## Implementation Checkpoint

| Task | Implementation State | Acceptance Gap |
|------|----------------------|----------------|
| T01 | Synthetic COM fixtures, regressions, scenario matrix; 70.50% in-process lines, 61.98% branches | Sample availability, subprocess coverage and uncovered-path review |
| T02 | Official Qt 6.11.2 Windows artifacts admitted; real binding/native match, XML mitigation and scoped native review | Distribution/license/native-notices approval and feature-change re-review |
| T03 | Offline checker, age/hash/exception/non-applicability tests, development-release boundary; thirteen actual admissions | Release approvals and complete policy/build integration |
| T04 | Exact runtime/build/dev locks including Qt, hash-verified wheels, offline resolution/install; pip check passes | Clean release build enforcement |
| T05 | Package/module entry, shared codecs, legacy aliases; offline wheel and packaged CLI smoke pass | Full sample/portable-packaging regression gates |
| T06 | Contextual records and bounded pages/search | Inventory still decodes all streams; lazy/large-fixture performance pending |
| T07,T08,T09 | Original-derived capabilities, strict replacements, revisions/staging/diff | Wider record/error-path coverage and coverage review |
| T10 | OS locks, journaled save/rollback/recovery; boundary fault tests | Real process/power-loss and filesystem-race stress |
| T11,T12 | JSON list/show/search/apply/diff/validate/pack | Broader protocol/exit/limit fixtures and coverage review |
| T13 | [CLI skill](skills/dgn-explorer/SKILL.md), real synthetic command tests | Client loading/pilot evidence |
| T14 | Optional desktop without CLI Qt imports; admitted Qt, Windows runtime and packaged entry pass | Clean Windows VM pilot |
| T15 | Bounded worker, cancellation, open-input shutdown regression; real Qt controller open/show passes | Controller fragmentation/crash and measured cancellation tests |
| T16,T17,T18,T19,T20 | Desktop browser/edit/undo/recovery/Save As; drafts and asynchronous close/switch; 23 Qt tests and frozen workflow pass | Native dialogs and larger fixtures |
| T21 | Aggregate/stream/reference checks and cancellation boundaries | Full-disk/races/worker-death stress and measured limits |
| T22 | Qt layout/keyboard test source | Real Windows DPI/accessibility/screenshots and complete workflows |
| T23,T25,T26 | Portable preview build and GitHub automation implemented | Clean VM/isolated native-product pilot, owners/signing/distribution approval |
| T24 | Short usage/AI/testing documentation | License notices, signing and colleague pilot |

Current verification uses the existing development environment and tiny synthetic
compound files, not customer data. Qt checks run on admitted Qt 6.11.2;
optional original sample checks skip without their local fixture. Reviewed Qt and
build/test tools are installed; portable previews are generated under `dist/`.
No customer fixture is distributed or installed into a Bentley product here.
The code is an implementation checkpoint, not completion of all release gates.

Available-suite result: `python -m unittest discover -s . -p 'test_*.py' -v`
runs 95 tests: 81 pass, 14 original-sample checks skip, no Qt checks skip.
The worker open-input shutdown regression also passes after its stdin type
assertion. Missing sample checks are not passing evidence. Line/branch
coverage are 70.50% in-process lines and 61.98% branches, respectively;
subprocess aggregation and approved build/application-pilot results remain pending.

## Commitments

- Windows x64 standalone PySide6 Qt Widgets app, standard user; portable folder
  initially, no installer or single-file self-extraction. Colleagues need no Python/admin/VS Code.
- Existing folder/JSON storage, shared codecs/service for GUI/CLI; no SQLite,
  MCP, web server, embedded AI/provider client, telemetry, upload or runtime downloads.
- Structure/metadata inspection, not 2D/3D rendering or complete domain authoring.
  No arbitrary object creation/deletion, guessed mixed-byte string schemas,
  dependency/layout repair, fuzzing runner or active content execution.
- Preserve originals, IDs, snapshots, reserved/unknown bytes and wire encodings.
  Support workspace v1/v2 and legacy CLI aliases; no silent migration.
- All owned backend, CLI, worker, policy/build and UI code has extensive reusable
  automated tests. Every change/fix carries focused tests and regression cases.
- Admit only established official dependencies/artifacts >=31 full days old;
  only documented official security fixes allow narrowly approved age exceptions.

## Architecture and State

| Layer | Responsibility |
|-------|----------------|
| Codec | Existing extraction/encoding/rebuild; no Qt or content execution |
| Service | Contextual records, trusted capabilities, typed edits, revisions/recovery |
| CLI/worker | JSON operations and progress/errors; independent of GUI |
| Qt UI | Native tree/properties/content/bytes/changes; never serializes DGN directly |

Wrap existing [dgn_folder.py](dgn_folder.py), split only at useful boundaries.
Current package: `dgn_explorer/`, with a facade over the single existing codec
module. Desktop lives in `desktop.py` behind the optional `ui.py` entry;
reuse current tests, adding shared helpers only when necessary. AI skill:
`skills/dgn-explorer/SKILL.md`. CLI keeps `dgn-workspace`, extract/rebuild aliases.

Import DGN into private restricted per-user storage; expose location/retention.
Temporary operation folders are removed; imported workspaces are retained after
save/discard. Crashes retain
recoverable state; user workspaces/backups are never cleaned. Hide framing and
snapshots by default. Open -> browse/search -> stage/preview -> save/Save As;
close prompts save/discard/cancel. Links stay data; plain XML/JSON/text, no HTML.
Use native accessible menus/controls, Qt/bundled icons, lazy models, typed editors,
read-only locks, encoding/BOM display, paged hex/escaped views and session undo/redo.
No workspace-controlled UI definitions/plugins/modules or third-party theme packs.

Optional owned `.dgn-explorer/` sidecar holds versioned session/recovery metadata;
test old packers ignore it. Saved authoritative files differ from staged typed
operations. Revision hashes manifest/object/content inputs, excluding indexes/
sidecar. Verify source hash/snapshots; derive capabilities from trusted originals
and codecs, never mutable `editing` labels/suffixes. Unsupported records stay readonly.
Use OS-backed writer locks and compatible read/pack ownership. External edits
invalidate conflicts; explicit reload/rebase, never silent replacement or stale-lock takeover.

Multi-file saves stage same-volume replacements, validate, journal durably with
before-images, publish under lock and mark complete. Recover entirely completed
or rolled back before edits/packing. Per-file rename alone is not batch atomicity.
Save As validates staged edits in an owned disposable snapshot without implicitly
saving the workspace; reject existing output, original source or output inside
workspace. Verify all streams/hierarchy before publication; failures/cancel leave
no apparently successful DGN. Container verification is not rendering evidence.

## Service, CLI and Worker

Proposed service methods: `open_workspace`, `import_dgn`, `list_records`,
`get_record`, `search_records`, `validate_patch`, `stage_patch`, `save_workspace`,
`diff_workspace`, `validate_workspace`, `pack_workspace`. Use dataclasses/enums
and explicit validators, not a new schema framework without demonstrated need.
Immutable capability descriptors preserve source identity. Advanced raw-byte
edits require opt-in/warning/preview/new output, never weaker path/identity/limit checks.

Implemented CLI additions: list/show/search, apply (`--dry-run` or `--approve`), diff
and validate. Versioned `--json` envelopes carry operation,
success, result/warnings/errors; progress/diagnostics use stderr. Suggested exits:
0 success, 2 usage, 3 invalid/unsupported, 4 conflict, 5 I/O, 6 cancel, 7 verification.
Document old behavior changes; no content/patch values/sensitive paths logged by default.
The bundled skill documents bounded discovery/inspection, proposals, validation
and human approval before writes/packing; a flag is not consent. Document loading
in supported AI tools; no hosted-model testing or automatic skill-discovery assumption.

Patch example; substitute a returned record locator/revision and actual prior value:

```json
{"schema":"dgn-explorer.patch-v1","workspace_revision":"sha256:<revision>",
 "operations":[{"record":{"ole_path":["Dgn-Md","#000000","Dgn^G","$1"],"chunk_index":0},
 "pointer":"/string/text","expected_value":"Original text","value":"Edited text"}]}
```

Replacement only; locator must resolve a supported record. Include model/storage
and stream/chunk identity, not element ID alone. Attributes discriminate set/element/
handler/attribute; property sets include stream/section. Protocol 64-bit IDs use
decimal strings. Reject ambiguity, unknown keys, duplicates/conflicts, invalid
types/pointers, nonfinite numbers, missing expected values and unsupported encodings.
Content paths resolve through their owning record. No arbitrary expressions,
Python/SQL/templates or JSON Patch add/remove/move; sizes remain codec-owned.

One QProcess backend per long operation uses the same service, argument arrays,
COM initialization where needed and local bounded JSON stdio, never shell strings.
Use the CLI's hidden worker entry; UI+CLI are the two packaged executables.
Messages: protocol/request_id/event and bounded payload; progress/warning/validation/
completed/failed. Partial exit without completion fails. Use stage/unit progress,
percentages only with known totals. Cooperative cancel first, termination fallback;
protected publication completes or recovers. Process isolation is not a sandbox.

Initial configurable targets: 128 MiB stored/decoded per stream, 2 GiB aggregate
decoded workspace with disk checks, 100 patch operations/16 MiB input, tree pages
200, search default 100/max 1,000, protocol messages 16 MiB (larger content via
validated owned files/chunks), cancellation acknowledgment within 2 seconds at
safe boundaries. Also bound counts, recursion, text and UI buffers; quarantine
partial extraction. Measure memory/disk/navigation/time on agreed pilot VM;
no fixed import-time promise. Never parse/pack on the UI thread.

## Backlog

The checkpoint table records implemented slices and remaining acceptance gates;
no milestone is complete while its required evidence is missing. Every task
includes the mandatory test contract below.
M0=T01-T04, M1=T05-T10, M2=T11-T13, M3=T14-T17, M4=T18-T19,
M5=T20-T22, M6=T23-T25, M7=T26; dependencies, not grouping, determine order.

| Task | Depends | Deliverable and Completion Evidence |
|------|---------|-------------------------------------|
| T01 | None | Baseline tests, supported operations, fixture gaps and reusable backend/UI scenario matrix |
| T02 | None | Supported Python/Windows/Qt ABI combination; official age/advisory/license evidence |
| T03 | T02 | Approval manifest/checker; boundary, provenance/hash and security-exception tests |
| T04 | T03 | Exact runtime/build/dev locks, approved wheelhouse; clean offline resolution |
| T05 | T01 | Importable package and thin shim; codec/import/old-new CLI compatibility |
| T06 | T05 | Contextual locators/lazy inventory; duplicate IDs across models remain distinct |
| T07 | T06 | Trusted capabilities/identity; altered labels/snapshots cannot authorize edits |
| T08 | T07 | Replace-only typed validator/dry-run; invalid/conflicting operations reject |
| T09 | T08 | Staging/diff/revision/value checks; no-write preview and external conflicts |
| T10 | T09 | Locks/journaled saves/recovery; faults at every publication step stay coherent |
| T11 | T06 | Bounded list/show/search; JSON/pagination/locator/limit tests |
| T12 | T08,T10 | Apply/validate/diff/errors; dry-run stays readonly, approved batch commits once |
| T13 | T11,T12 | Skill/automation examples on synthetic fixtures, no AI service |
| T14 | T04,T05 | Optional approved desktop dependency/entry; CLI works without Qt |
| T15 | T10,T14 | Worker/controller; progress/errors/partial-output/cancellation tests |
| T16 | T06,T15 | Native window/tree/properties; automated selection/paging/locks/keyboard tests |
| T17 | T16 | Literal search/text/XML/paged bytes; encodings and huge-value limits |
| T18 | T08,T09,T17 | Typed editors; automated GUI/CLI valid-invalid acceptance parity |
| T19 | T10,T18 | Undo/preview/save/discard/recovery; cancel-close/reopen/interrupted-save tests |
| T20 | T12,T15,T19 | Save As staged snapshot; no implicit save, verify and re-extract |
| T21 | T20 | Aggregate limits/failures; full disk, worker death, path escape/output-race tests |
| T22 | T17,T19,T21 | Automated workflows/accessibility/keyboard and DPI/window screenshots |
| T23 | T04,T22 | Minimal portable build/native inventory; offline VM without Python/admin |
| T24 | T13,T23 | Short user/admin docs, notices/signing; colleague completes documented workflow |
| T25 | T20,T24 | Approved synthetic/sanitized isolated application pilot; visible edits or explicit gaps |
| T26 | T24,T25 | Release approvals/owners/distribution/rollback/security-review evidence in tracked home |

Policy automation can proceed independently, but no new dependency installs before
admission. Initial shared release needs project/Qt/native license approval, signing,
maintainer/security/release owners, support/distribution route and rollback artifacts.

## Mandatory Tests and Release Gates

- Unit/integration coverage spans codecs, service, CLI, worker, policy/build and
  Qt models/editors; end-to-end compares CLI/UI and packaged workflows.
- For every feature cover normal/empty/no-op, boundaries, invalid/read-only inputs,
  errors and relevant cancellation/concurrency/recovery. Every fix has a regression.
- Shared synthetic factories, temp directories and data-driven unittest subtests
  make new record/encoding/editor families easy to add. No customer data, developer
  paths, network, fragile private internals, arbitrary sleeps or unseeded randomness.
- Deterministic fake workers test UI states; real workers test integration.
  Approved Qt Test clicks/keys/focus/signals/model checks assert real behavior.
  Mock-only tests/screenshots do not replace automated UI workflows. Test every
  command/control/error/recovery state, read-only locks, prompts and undo/redo.
- Offscreen tests where supported plus real Windows native-dialog/plugin/DPI/
  accessibility/packaged checks. Fix/document flakes, never hide failures with retries.
- Record line/branch coverage and behavior matrix for all meaningful owned code;
  exclude generated/third-party code explicitly. Critical preservation, capability,
  encoding, transaction, cancellation and policy rules need positive/negative cases.
  Coverage tools require admission; percentages alone prove nothing; no UI exemption.
- Focused/affected integration/UI tests accompany each change; full release suite
  passes before release. Document commands and extending fixture/editor families.
  Missing fixtures/platform checks are skipped/blocked, not passed; uncovered
  meaningful paths need rationale/owner before task completion.
- Release requires byte-identical no-edit packs, re-extracted supported edits,
  unchanged unrelated data, preserved originals, full UTF-8/16/32/octet coverage,
  path/reparse/race checks, coherent crash recovery and bounded resources.
- Distinguish container checks from isolated application evidence; suppress
  startup/external activation and record gaps. Require approved hashes/locks/native
  inventory/SBOM, offline standard-user pilot, notices/signing, ownership and support.
- Weekly advisory review, monthly dependency review, immediate applicable-fix
  triage and regression/packaged checks per update. No automatic upgrade/age bypass.