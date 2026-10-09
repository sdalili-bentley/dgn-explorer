# DGN Explorer

DGN Structure and Metadata Editor. A local CLI that unpacks unencrypted DGN V8
files into editable folders and packs them into new, verified DGN files.
Supported metadata, text, XML, linkages and some geometry are editable. Unknown
bytes are preserved. This is not a graphical CAD viewer or complete authoring API.

**Status:** native desktop, shared service, structured CLI, worker and AI skill
are implemented. The Windows portable development preview passes relocated
CLI/GUI tests with Python/Qt environment overrides removed. The suite runs
95 tests: 81 pass and 14 optional sample checks skip, including 23 passing Qt
tests. Qt 6.11.2 has an application-scoped development advisory decision.
No SQLite, MCP, telemetry or cloud upload. This is not a signed company release.

## Desktop and Portable Preview

Extract the whole portable ZIP and run `DGN-Explorer/dgn-explorer-gui.exe`.
Keep its sibling `dgn-explorer.exe` and `_internal/` folder together. Python,
VS Code and an admin installation are not needed. Downloads are the artifacts
of successful [Windows preview builds](https://github.com/sdalili-bentley/dgn-explorer/actions/workflows/windows-build.yml), not GitHub Releases.

Open DGN imports into the current user's Qt local application-data location,
under `DGN Explorer/DGN Explorer/workspaces/`. Open Workspace uses an existing
extracted folder. Imports, saved workspaces and recent-workspace entries remain
on disk; the app does not automatically delete them. The window title identifies
the open workspace; retain originals and remove only workspaces you own.

Browse/search records, edit supported properties or plain-text content, then
stage changes and use Save or Save As. Drafts survive record navigation. Save
validates drafts and commits workspace edits; Save As creates a new DGN without
overwriting the input. Undo/redo applies to staged edits. Switching or closing
with pending changes offers Save, Discard and Cancel; invalid drafts remain
editable. Unknown/raw records are read-only.

Build a preview from admitted dependencies:

```powershell
python prepare_dependencies.py
python -m dgn_explorer.policy build/ci-dependency-approvals.json wheelhouse
python -m pip install --no-index --find-links wheelhouse --only-binary=:all: --require-hashes -r requirements-runtime.lock -r requirements-build.lock -r requirements-dev.lock
./build-portable.ps1 -Python python -ApprovalManifest build/ci-dependency-approvals.json
```

The portable build requires exact CPython 3.14.3. It writes
`dist/DGN-Explorer-windows-x64.zip`, checksum, component/source receipts, dependency
licenses and inventory. It verifies real frozen open/edit/save/export/reimport,
original preservation, byte-identical no-edit packing and a rendered screenshot
from a relocated folder. Only the Windows platform/native-style Qt plugins remain.
The [workflow](.github/workflows/windows-build.yml) runs automatically on main
pushes, pull requests and manual dispatch, builds a Python wheel and uploads
verified previews. Actions/runtime/dependencies are exact reviewed inputs;
changed or unavailable advisory evidence stops provisioning for source review.
GitHub's managed Windows host is recorded, not an immutable clean-machine image.
Clean-VM, native-product, DPI/accessibility, large-file and signing/license-owner
gates remain distinct in [PLAN.md](PLAN.md).

## Development Setup

Requires Python 3.11+. The application targets Windows x64 with pywin32.
Original codec APIs retain non-Windows inspection/extraction/no-edit packing;
the application's safe new-folder publication currently requires Windows.
Review [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md) before installing anything.
Windows x64 CPython 3.14 hash locks and development-only admission evidence exist;
they do not approve a release build. The build backend is setuptools 83.0.0.
Prepare a virtual environment with reviewed Python/pip, then check and install:

```powershell
python -m dgn_explorer.policy dependency-approvals.json wheelhouse
python -m pip install --no-index --find-links wheelhouse --only-binary=:all: --require-hashes -r requirements-runtime.lock -r requirements-build.lock -r requirements-dev.lock
python -m dgn_explorer --help
```

Run from this checkout with an existing development environment. After approved
offline provisioning, use `python -m pip install --no-deps --no-build-isolation -e .`.
Direct execution also works: `python dgn_folder.py --help`.
`dgn-workspace` remains a compatibility command.

## Use

```powershell
dgn-explorer unpack input.dgn workspace
dgn-explorer --json list workspace --limit 20
dgn-explorer --json search workspace --text example
dgn-explorer --json apply workspace --patch edits.json --dry-run
dgn-explorer --json apply workspace --patch edits.json --approve
dgn-explorer validate workspace
dgn-explorer pack workspace edited.dgn
dgn-explorer inspect edited.dgn
```

Use the installed command's full path if the environment is not activated.
`extract`/`rebuild` alias `unpack`/`pack`. Options precede the subcommand:
`dgn-explorer --max-mib 64 unpack input.dgn workspace --bytes-mode hex`.

Destinations must not exist; output DGN must be outside the workspace. Never edit
`original.dgn` or original snapshots. No-edit packing is byte-identical. Packing
verifies every stream and storage hierarchy, not application rendering or domain
integrity. Validate edited copies in an isolated application environment; linked
targets and embedded/startup content are never activated by this tool.

Use `show workspace --record LOCATOR_JSON` with a locator returned by `list`.
Patches use `dgn-explorer.patch-v1`, the returned revision and replace operations
with `record`, `pointer`, `expected_value`, `value`. Preview before approving.
`pack ... --patch edits.json` publishes staged edits without saving the workspace.
Saves use exclusive locks and a recovery journal; external changes reject.

`.rw` labels remain guidance. Service capabilities come from the original DGN,
not modified labels. IDs, snapshots, encodings, framing and unknown bytes stay
restricted. JSON-view v1/v2 and hex workspaces are supported; binary-only legacy
folders need re-extraction for the editor. Advanced codec edits may fail the
stricter service. Default stream limit is now 128 MiB, aggregate 2 GiB.

Escaped bytes are default: Latin-1 maps all 256 octets reversibly; recognized
whole text uses UTF-8/16/32 with preserved byte order, BOM and terminators.
Encoding is strict. `--bytes-mode hex` and legacy v1 workspaces remain supported.
See [DGN_FORMAT.md](DGN_FORMAT.md) for the workspace contract.

## Tests

```powershell
python -m unittest discover -s . -p 'test_*.py' -v
```

Synthetic tests need no DGN input. Optional sample tests need the specific baseline
fixture expected by `SampleTests`, not any arbitrary DGN; set `DGN_EXPLORER_SAMPLE`
to its approved local path, or place it at `sample.dgn`. No fixture is distributed.
These tests skip if absent; COM integration needs Windows. Qt tests run with the
admitted runtime and skip explicitly if it is absent. Outputs use temporary
folders. See [TESTING.md](TESTING.md).
The optional [dgn_fixture_catalog.py](dgn_fixture_catalog.py) targets an existing
Bentley source-fixture layout; it is not installed or a generic fixture generator.
Its marker links are passive data, never activation instructions.

## Development

Desktop entry: `python -m dgn_explorer gui`, or installed `dgn-explorer-gui` after
Qt admission. Without Qt it exits with an error, not a download. Source and frozen
desktop workflows have Windows synthetic regression evidence, not native-product
or company distribution approval. [Dependency evidence](DEPENDENCY_CANDIDATES.md) records
the corrected Qt decision, constraints and lesson learned.
The [AI skill](skills/dgn-explorer/SKILL.md) works with the CLI independently.
Load it explicitly or use the client's supported skill directory; ordinary
`skills/` discovery is not assumed.

[PLAN.md](PLAN.md) is the backlog, [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md)
governs every dependency, and [AGENTS.md](AGENTS.md) guides AI-assisted changes.
Every code/UI change needs extensible automated tests and relevant regression
cases. Do not commit DGN inputs, workspaces, backups, secrets or generated binaries.
Project licensing, release signing and distribution approvals remain pending.