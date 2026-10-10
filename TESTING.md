# Testing

## Run

Use the existing admitted environment; do not install dependencies just to hide skips.
Keep test scratch files inside the ignored project build tree:

```powershell
$env:TEMP = Join-Path $PWD 'build\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
python -m unittest discover -s . -p 'test_*.py' -v
```

**Absent prerequisites are skipped, not passed:**

| Prerequisite | Checks affected |
|---|---|
| Windows + pywin32/COM | Synthetic compound-file service/CLI integration |
| Admitted PySide6-Essentials + shiboken6 + Qt 6.11.2 | Qt widgets, controller and real desktop workflows |
| Specific approved baseline DGN | 14 `SampleTests` checks |

For the baseline fixture, set `$env:DGN_EXPLORER_SAMPLE='C:\approved\baseline.dgn'`
or place it at `sample.dgn`. **An arbitrary DGN is not a substitute.**
No customer/baseline fixture is distributed.

**Audit result (2026-10-10):** **230 tests, 216 passed, 14 skipped** with existing
Qt 6.11.2; all 65 Qt checks passed. Only the unavailable baseline checks skipped.
Log: `build\audit-final-full-suite-qt.log`.
The host-only run passed 151 with 79 skips (14 baseline + 65 Qt).
The host is CPython 3.14.7, not the admitted 3.14.3 portable-build runtime.
Source verification does not approve a release.

**Publication verification (2026-10-10):** source commit
`3b180361c4175cc95628bd4295f3b061ebc857a0` passed the full local suite:
**231 tests, 217 passed, 14 baseline checks skipped**, including all 66 Qt
checks with Qt 6.11.2. Log: `build\push-verification-fixed-full-suite.log`.
Three targeted layout tests also passed with subprocess coverage/combination:
`build\push-verification-layout-coverage.log`.

The [first publication run](https://github.com/sdalili-bentley/dgn-explorer/actions/runs/38061393251)
for `736604ca2981e66294589c8515375e5c9fcbdb21` failed the 200% scaling check:
the record browser narrowed to 77 pixels on the runner. Commit `3b18036`
sets a 160-logical-pixel minimum; the new constrained-splitter regression
failed before the fix and passed afterward. Scaled-process checks now include
640×480 windows without relaxing the existing assertions.

[Windows CI run #4](https://github.com/sdalili-bentley/dgn-explorer/actions/runs/38061800353)
for `3b180361c4175cc95628bd4295f3b061ebc857a0` completed successfully at
**2026-10-10 15:02:28 UTC** on `windows-2022`, with admitted CPython 3.14.3
and Qt 6.11.2. **231 tests: 217 passed, 14 baseline checks skipped**;
subprocess coverage/combination, actual portable verification, offline Python
wheel build and artifact upload all passed.
Local CI log: `build\push-verification-ci-38061800353.log`.

## Reusable Coverage

| File | Main checks |
|---|---|
| `test_dgn_folder.py` | Reversible encodings/octet preservation; framing, counts, lengths, passive views and supported scalar/geometry/XML codecs |
| `test_application.py` | Contextual identities, original-derived permissions, typed patches, revisions, paging/search, save/pack, CLI exits and real workers |
| `test_editors.py` | Plain/escaped/hex/Base64 roundtrips; controls/emoji/invalid input; payload limits, file races/cleanup and save/reimport |
| `test_ui.py` | Real Qt controls/keyboard/state, retained drafts, undo, Save/Discard/Cancel, worker failures/cancellation and GUI/CLI validation parity |
| `test_policy.py` | Age/hash/advisory/exception boundaries, non-applicability evidence, matched Qt, development/release separation and refresh rejection |
| `test_support.py` | Shared synthetic COM workspaces and bounded record/feature factories; fixture support, not a standalone test case |

Transaction tests kill child processes at prepared/publish/committed boundaries,
check cross-process lock release, inject disk-full/rollback failures and retain
invalid journals. Safety cases cover destination races, path/junction rejection,
bounded resources and unchanged originals.

**Audit regressions (2026-10-10):**

- Tampered recovery references cannot turn originals, manifests or user notes into write targets.
- Growing files cannot bypass bounded reads; tiny files do not allocate the whole
  stream limit. Exponent overflow cannot create non-finite JSON numbers.
- Non-finite native properties/geometry/text/fixed metadata remain opaque and reversible.
- Extraction views match the retained original snapshot, even when the source changes at copying.
- Current uncompressed 20-byte `Dgn~H` framing packs unchanged and with unrelated edits;
  compressed/encrypted flags and wrong header lengths reject.
- Record-browser width survives constrained windows and splitter compression;
  fresh Qt processes cover 125%, 150% and 200% scaling.

## Extend Tests

- Reuse `create_workspace`, `shared_workspace`, `feature_streams`, `element_chunk`,
  `user_linkage`, `xml_fragment` and `becxml_document`; keep shared fixtures read-only.
- Use `editor_test_root` for owned payload artifacts; it cleans up its project-local folder.
- Add **normal, empty/no-op, exact-boundary, invalid, read-only and failure** cases.
  Every bug fix needs a regression; every code/UI change needs reusable tests.
- Assert observable preservation, staging, saved bytes and reimport—not only helper output.
- Fake workers cover UI state; **real workers** cover integration. Synchronize on
  Qt signals/conditions, not sleeps/retries.
- Use `$env:QT_QPA_PLATFORM='windows'` for native Windows runtime tests.
  `offscreen` supports headless checks, not real dialogs/DPI/accessibility approval.

## Packaging and Performance

With admitted build inputs, [build-portable.ps1](build-portable.ps1) runs real
packaged verification automatically. To verify an existing bundle:

```powershell
python verify_portable.py dist\DGN-Explorer
python benchmark_workspace.py --text-count 2000 --output build\benchmark.json
```

Packaged checks relocate both executables and `_internal\` into a path with spaces,
remove Python/Qt environment overrides, then test no-edit byte equality, GUI
save/Save As/reimport, original preservation and a nonblank screenshot.
Reports/screenshots go under `build\portable-*`. Relocation is **not** a clean VM.

The benchmark uses synthetic files, reports timings/checkpoint gaps/peak Python
memory, and refuses to overwrite its report. Open memory remains linear in
workspace size; synthetic measurements are not native-file performance limits.

Optional admitted coverage:

```powershell
python -m coverage run -m unittest discover -s . -p 'test_*.py' -v
python -m coverage combine
python -m coverage json -o build\coverage.json
```

`pyproject.toml` enables owned-code branches and subprocess patching.
Historical coverage percentages are not current audit evidence.
`portable.py` is additionally exercised by actual frozen-package verification.
The audit also exercised its real **source** GUI save/export/reimport workflow
with existing Qt 6.11.2: `build\audit-portable-source-verification.json`
records success with `frozen: false`; its screenshot was visually inspected.
This is not a new frozen-build result.

The publication check also reran `verify_portable.py` against the existing
local frozen preview at commit `2f7a2ac8bdabc41d3ff270c1b7cb5fd28c1ccbfe`.
Relocated CLI/GUI no-edit equality, save/export/reimport, original preservation
and screenshot checks passed: `build\push-verification-existing-preview.json`.
This older preview does not verify the newly committed source. A fresh local
build was not attempted because the available host runtime is 3.14.7, while
the receipt gate requires admitted CPython 3.14.3.

The **current-source CI bundle** from run #4 also passed local
`verify_portable.py`: relocated frozen CLI/GUI, no-edit byte equality,
save/Save As/reimport, original preservation and nonblank screenshot.
Report: `build\ci-preview-38061800353\local\portable-verification.json`.
Its receipt records source `3b18036`, `source_dirty: false`, CPython 3.14.3
and Qt 6.11.2. Both download hashes were checked:

- Actions artifact `11672953325` (`DGN-Explorer-windows-x64-preview`, expires
  2026-10-24): SHA-256
  `46696a2dcde1bea685d8481505e92246eeaa07d7033271c0b277eb95c85d70be`.
- `DGN-Explorer-windows-x64.zip`: SHA-256
  `56958371c561f767881a79edf83afa0d7ff6223cded1bf1bf3491b40b6b902e6`.

`build\push-verification-benchmark.json` records a successful synthetic
2,000-text-per-model run: 4,003 records, 4,014 files and 109.1 MiB peak Python
memory for open. Open/search/validate/staged pack/import completed; this is
host-specific synthetic evidence, not a supported native-file limit.

## Evidence Limits

- Current-source Windows CI and local re-verification passed synthetic frozen
  workflows. Actual frozen-worker cancellation/latency still needs separate
  evidence; source-worker cancellation tests do not establish it.
- A previous separate VM passed synthetic frozen workflows but had installed
  Python/VS Code, so neither it nor the managed CI host is the clean-VM gate.
- One approved OBD 24.00.03.31 text fixture has read-only parsing/rendering/reopen
  evidence in `build\native-pilot-20261009\`; this is not broad domain correctness.
- Offline isolation, complete external-content suppression, clean/non-admin VM,
  broader/large native fixtures, physical power loss, screen reader/DPI/native
  dialogs, AI-client/colleague pilots, signing/notices and release-owner approval
  remain [open gates](PLAN.md).
- Keep document content local. Never execute embedded content, follow targets,
  load document fonts or upload fixtures during these tests.
