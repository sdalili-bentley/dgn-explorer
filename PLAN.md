# Remaining Work

**Implemented:** shared codecs/service, CLI, worker, native Qt desktop, multi-format
editors, transactional saves, dependency checks and Windows portable previews.
**Not approved:** company release or general native-product correctness.

Usage: [README.md](README.md). Tests: [TESTING.md](TESTING.md).
Dependencies: [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md).

## External and Manual Gates

| Gate | Required evidence |
|---|---|
| **Frozen cancellation** | Exercise cancellation/latency in actual frozen workers at scale; source-worker tests and the packaged save/export self-test do not establish this |
| **Clean Windows VM** | Offline, verified standard/non-admin account; no installed Python/VS Code; confirm native plugins, dialogs and retained workspace locations |
| **Native-product coverage** | Broader approved fixtures: text, properties, tables, geometry and application data; compare parsing/rendering/reopen and unchanged unrelated records |
| **Application isolation** | Verify startup/autoload/external-content suppression and offline isolation before opening edited copies; investigate the empty COM automation-startup failure |
| **Scale and resources** | Measure approved large-file open/search/edit/pack, peak memory/disk and cancellation; establish supported limits |
| **Accessibility and DPI** | Real screen reader, keyboard-only colleague workflow, native file dialogs, physical high-DPI/high-contrast screenshots |
| **Storage resilience** | Physical power-loss and network/removable-filesystem recovery; synthetic process-kill tests are not these gates |
| **AI-client pilot** | Confirm explicit skill loading, bounded discovery, patch preview and human-approved publication in a supported client |
| **Release approval** | Named maintainer/security/license/release owners; project/Qt/native notices, signing, release-eligible dependency evidence, offline build enforcement, distribution/support and rollback route |

No gate is waived by passing source tests or a development preview.
Dependency reviews remain weekly for advisories and monthly for currency.
Re-review native advisory decisions before font loading, print/PDF, image preview,
new Qt modules/plugins or wheel changes.

## Evidence Already Available

- **Synthetic source tests:** codecs, service, CLI, transaction faults, worker,
  policy and real Qt workflows; current results are in [TESTING.md](TESTING.md).
- **Current-source portable preview (2026-10-10):** source commit
  `3b180361c4175cc95628bd4295f3b061ebc857a0`,
  [Windows CI run #4](https://github.com/sdalili-bentley/dgn-explorer/actions/runs/38061800353),
  passed with admitted CPython 3.14.3 and Qt 6.11.2: 217 source tests passed,
  14 unavailable baseline checks skipped; coverage, relocated frozen CLI/GUI
  save/export/reimport, original preservation, ZIP/wheel packaging and upload
  succeeded. Artifact `11672953325` was hash-checked and its bundle reverified
  locally: `build\ci-preview-38061800353\local\portable-verification.json`.
  Receipts identify a clean source checkout. This is a development preview,
  not a signed/company release or frozen-cancellation result.
- **Previous VM preview:** passed relocated GUI/CLI in a separate VM.
  That VM had Python/VS Code; it was not the clean-machine gate.
- **One approved native text pilot:** OBD 24.00.03.31 read-only parsing, visible
  baseline/edited comparisons and reopen. Reports/screenshots remain in
  ignored `build/native-pilot-20261009/`.
- **Pilot limits:** complete external-content suppression/offline isolation were
  not established. The live original changed after the user's manual open,
  before the checks; the retained approved copy and checked disposable copies
  were preserved. Do not restore over the live original.
- **Source audit:** regression coverage now includes protected recovery targets,
  bounded reads during file growth, JSON numeric overflow, opaque non-finite
  native values, retained-snapshot extraction, current uncompressed `Dgn~H`
  packing and record-browser usability under constrained/scaled layouts.

## Format Expansion: Scope Decision Required

The bounded views in [DGN_FORMAT.md](DGN_FORMAT.md) are implemented.
Full geometry/option-block serializers, native schema/provider invariants,
dependency graphs, building/electrical authoring, BECXML writing and DgnStore
repartitioning are **not** implemented. Use
[the source-backed gap catalogue](DGN_SPECIFICATION_GAPS.md) to choose a justified
next tranche; a named header or linkage is not authoring support.

## Change Rules

- Keep **one codec**, v1/v2/alias compatibility and strict reversible encodings.
- Preserve originals, identities, snapshots, reserved/unknown bytes.
- Every code/UI change adds reusable tests; every fix adds a regression.
- Run the full suite; report missing fixture/platform checks as **skipped**.
- Keep document data local; never activate embedded targets/startup content.
- No new dependency, SQLite, MCP, network service or theme without a scope and
  admission decision. Do not commit DGN files, workspaces, secrets or binaries.
