# Testing

Run from the repository with existing development dependencies:

```powershell
python -m unittest discover -s . -p 'test_*.py' -v
```

`test_support.create_workspace` builds tiny synthetic DGN V8 compound files
through Windows COM: two models with the same element ID, XML, opaque bytes and
framing. Extend these fixtures instead of copying setup. No customer data,
network, arbitrary sleeps or embedded-content activation is needed.
Missing Windows/COM integration tests skip explicitly. Original sample tests
need the specific `DGN_EXPLORER_SAMPLE` baseline, not any arbitrary DGN.

| Surface | Automated Evidence | Remaining Gate |
|---------|--------------------|----------------|
| Codecs | Existing representation tests, octets, Unicode, lengths, encoding | Original sample tests need local fixture |
| Service | Contextual IDs, labels/snapshots, typed edits, no-op, v1/hex | Large-workspace latency/memory and broader record fixtures |
| Transactions | Faults at prepared, every publish and committed; rollback; ownership | Real process/power-loss and filesystem-race stress |
| DGN output | Real synthetic no-op/edit pack, stream checks, original preservation | Approved isolated application pilot |
| CLI | Discovery, JSON, usage/errors, dry-run/approve, pack | Broader exit/argument and filtered pagination cases |
| Worker | Real subprocess, invalid/oversized messages, cancellation, open-input exit; frozen sibling worker | Qt partial-message/crash tests and measured cancellation latency |
| Policy | Age/hash/advisory/exception/matched-Qt tests, evidence-required non-applicability, source-boundary guard; thirteen actual admissions and offline installs | Feature-change advisory re-review, release approvals and complete build integration |
| Desktop | 23 Windows Qt tests pass: widgets/delegate/search/edit/undo/layout, draft navigation, rejected edits, asynchronous save/discard/cancel, private import/recents, real worker, version/XML checks | Native dialogs/DPI/accessibility and larger fixtures |
| Packaging | Real frozen GUI/CLI from a relocated folder; no-edit byte equality, edit/save/export/reimport, original preservation, nonblank screenshot, minimal plugins, receipts/hashes/licenses | Clean VM, isolated native-product pilot, full notices/signing/release owners |

Add normal/no-op, boundary, invalid and failure variants using unittest subtests.
Every bug fix gets a regression. Each editor needs real Qt interaction tests and
service acceptance cases; fake workers only cover UI state. Synchronize on Qt
signals/conditions, never sleeps or retries that hide failures.
`QT_QPA_PLATFORM=offscreen` supports headless tests after admission. Actual Windows
dialog/DPI/accessibility tests remain separate release gates. Use
`$env:QT_QPA_PLATFORM='windows'` for the Windows runtime suite; it uses system
fonts rather than adding font packages in response to offscreen-plugin warnings.

The available suite runs 95 tests: 81 pass and 14 optional original-sample checks
skip. No Qt test skips. With admitted coverage 7.10.6,
`python -m coverage run --branch --source=dgn_explorer,dgn_folder -m unittest discover -s . -p 'test_*.py' -v`
and `python -m coverage json -o build/coverage.json` measure 70.50% owned-code
line coverage and 61.98% branch coverage. The generated report retains full
counts and uncovered lines/branches; GitHub preview artifacts include it. This is
in-process measurement only: worker/CLI subprocess execution is not aggregated,
and broader fixtures, uncovered-path review and subprocess collection remain
required. These results are not exhaustive coverage or portable-release approval.
Remaining test gates belong to the project maintainer, not an implicit waiver.

For real packaged verification, use `python verify_portable.py dist/DGN-Explorer`.
The build invokes it automatically before ZIP publication. Reports and the actual
GUI screenshot are generated under `build/portable-*`; customer files are never
needed. A relocated/sanitized host is not evidence of a separate clean VM.

`prepare_dependencies.py` refreshes direct/vendored/native OSV queries and the
upstream Qt advisory list. Unchanged evidence preserves the recorded scoped
decision; any change stops for independent review. It rechecks registry yanks,
publication age and exact hashes. Its offline rejection boundaries are tested
in [test_policy.py](test_policy.py). Acquisition is online; install/build is offline.