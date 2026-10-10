# DGN Explorer

**Local DGN V8 structure/metadata editor.** Unpack an unencrypted DGN, edit
supported records, then pack a **new verified copy**. Unknown bytes are preserved.
This is **not a CAD viewer or complete authoring API**.

- **Implemented:** CLI, service/worker, optional Qt desktop, AI skill and Windows portable preview.
- **Local only:** no telemetry, uploads, target/startup execution, SQLite, MCP or network service.
- **Development preview, not company release.** Remaining gates: [PLAN.md](PLAN.md).

## CLI

Use installed `dgn-explorer`, or substitute `python -m dgn_explorer` from this checkout.

```powershell
dgn-explorer unpack input.dgn workspace
dgn-explorer --json list workspace --limit 20
dgn-explorer --json search workspace --text example --limit 20
dgn-explorer --json show workspace --record LOCATOR_JSON
dgn-explorer --json apply workspace --patch edits.json --dry-run
dgn-explorer --json apply workspace --patch edits.json --approve
dgn-explorer diff workspace
dgn-explorer validate workspace
dgn-explorer pack workspace edited.dgn
dgn-explorer inspect edited.dgn
```

- Replace **`LOCATOR_JSON`** with returned locator JSON, quoted for your shell.
  An ID alone is not a locator. Follow `next_cursor`; `--model` / `--kind` filter.
- Search is **literal and case-insensitive**, over current values—not snapshots/JSON syntax.
- Patches: `dgn-explorer.patch-v1`, returned `workspace_revision`, replace operations
  containing `record`, `pointer`, `expected_value`, `value`. Use returned `editable_fields`.
- `pack workspace edited.dgn --patch edits.json` exports staged edits **without saving the workspace**.
- `extract`/`rebuild` alias `unpack`/`pack`; `dgn-workspace` remains compatible.
  Global options precede commands:
  `dgn-explorer --max-mib 64 unpack input.dgn workspace --bytes-mode hex`.

| Exit | Meaning |
|---|---|
| 0 / 2 | Success / usage error |
| 3 / 4 | Invalid or unsupported input / revision, value or ownership conflict |
| 5 / 6 / 7 | I/O failure / cancellation / verification or backend failure |

`--json` returns **`dgn-explorer.result-v1`**; usage errors have `operation: null`.
Defaults: **128 MiB/stream**, **2 GiB aggregate**, **100 operations/patch**.

## Desktop

Download an artifact from a successful
[Windows preview build](https://github.com/sdalili-bentley/dgn-explorer/actions/workflows/windows-build.yml).
Extract the **whole ZIP**; run `DGN-Explorer\dgn-explorer-gui.exe`.
Keep `dgn-explorer.exe` and `_internal\` beside it. No installed Python/VS Code/admin
installation is needed. Actions artifacts are **not GitHub Releases**.

1. **Open DGN** imports a retained workspace; **Open Workspace** opens an existing folder.
2. Browse/search; edit supported **Properties / Content**.
3. **Stage Content** validates drafts; **Save Workspace** commits edits.
4. **Save As DGN** verifies a new output, without implicitly saving the workspace.

Drafts survive record/field navigation; undo/redo covers staged edits.
Close/switch offers **Save / Discard / Cancel**. Invalid drafts stay editable;
unknown/raw records are read-only. Bytes shows **4 KiB pages**, offsets and ASCII.

Imports live in Qt's current-user local application-data location under
`DGN Explorer\DGN Explorer\workspaces\`. Workspaces/recents are **not auto-deleted**.
The title identifies the workspace; remove only your own.

### Strings and Files

- **Plain / Escaped / Hex / Base64** represent strict UTF-8 string bytes;
  original DGN encoding/BOM stays unchanged.
- Inline strings use escapes: `\u0000` / `\x00` = NUL, `\r` / `\n` / `\t` = controls,
  `\\` = backslash. Loaded controls unsafe for plain widgets display escaped.
- **Load File…** replaces a draft only, up to **64 KiB** decoded bytes.
  Non-UTF-8 binary data can be inspected/exported, not staged as a string.
- **Copy…** copies the whole safe representation. **Export File…** writes decoded
  bytes; **Export Page…** writes the raw page. Use new files outside the workspace.
- Shortcuts: Ctrl+S save; Ctrl+F search; Alt+P advanced property; Alt+L load;
  Alt+X export; Alt+C copy; Alt+T stage; Alt+B export page.

## Preservation and Coverage

**Never overwrite inputs.** Destinations must be new; outputs stay outside the workspace.
Do not edit `original.dgn`, identities, snapshots, encodings, framing or unknown bytes.

- **No-edit packing is byte-identical.** Packing verifies stream hashes/hierarchy,
  **not native rendering/layout/domain integrity**. Use approved isolated application checks.
- Saves use locks/recovery journals; external changes conflict.
  Permissions derive from the original DGN, not mutable `.rw` labels.
- JSON-view v1/v2/hex folders work; binary-only legacy folders need re-extraction
  for the editor. Advanced codec mutations can fail stricter service validation.
- Supported replacements cover selected text/properties/linkages/geometry,
  UTF-16 font names, version-3 Tag scalars and XML/JSON content.
  New headers/indexes, dependencies, DgnStore, TFLabel, GCS and BECXML/ECXD
  views are bounded/passive—not building/electrical authoring.

Exact boundaries and byte/text formats: [DGN_FORMAT.md](DGN_FORMAT.md).

## Develop and Build

Source requires **Python 3.11+**; application publication targets **Windows x64 + pywin32**.
Codec inspection/extraction/no-edit packing also work without a writable non-Windows
backend. Safe application import publication currently requires Windows.

Review [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md) first. Existing hash locks target
**Windows x64 CPython 3.14**; matched **Qt 6.11.2** admission is development-only.
With an already admitted wheelhouse:

```powershell
python -m dgn_explorer.policy dependency-approvals.json wheelhouse
python -m pip install --no-index --find-links wheelhouse --only-binary=:all: --require-hashes -r requirements-runtime.lock -r requirements-build.lock -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m dgn_explorer --help
python -m dgn_explorer gui
python -m unittest discover -s . -p 'test_*.py' -v
```

Qt is optional; missing Qt causes an explicit GUI error, never a download.
Tests use synthetic fixtures; absent sample/COM/Qt checks **skip**, not pass.
[TESTING.md](TESTING.md) covers fixtures, packaged verification and benchmarks.
Compatibility entry: `python dgn_folder.py --help`.

For a preview, use admitted **CPython 3.14.3**. Online evidence refresh stops on
changed advisories; installation/build consume offline approved inputs:

```powershell
python prepare_dependencies.py
python -m dgn_explorer.policy build\ci-dependency-approvals.json wheelhouse
python -m pip install --no-index --find-links wheelhouse --only-binary=:all: --require-hashes -r requirements-runtime.lock -r requirements-build.lock -r requirements-dev.lock
.\build-portable.ps1 -Python python -ApprovalManifest build\ci-dependency-approvals.json
```

Output: `dist\DGN-Explorer-windows-x64.zip`, checksum, receipts, inventory and notices.
The build verifies relocated frozen CLI/GUI save/export/reimport and a screenshot;
only Windows platform/native-style Qt plugins remain. CI runs on main pushes, PRs
and manual dispatch; a managed Actions host is **not** the clean-VM gate.

## API and AI

`dgn_explorer.codecs` re-exports the **single codec** in `dgn_folder.py`.
`editor_encode` / `editor_decode` / `editor_text` use `plain`, `escaped`, `hex`, `base64`.
Service/worker `load-field`, `export-field`, `export-bytes` are **not CLI subcommands**.

Load [the CLI skill](skills/dgn-explorer/SKILL.md) explicitly or via a supported client
directory; automatic `skills\` discovery is not assumed. [AGENTS.md](AGENTS.md) guides
changes. Do not commit DGN files, workspaces, backups, secrets or generated binaries.
