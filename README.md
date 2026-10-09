# DGN Explorer

DGN Structure and Metadata Editor. A local CLI that unpacks unencrypted DGN V8
files into editable folders and packs them into new, verified DGN files.
Supported metadata, text, XML, linkages and some geometry are editable. Unknown
bytes are preserved. This is not a graphical CAD viewer or complete authoring API.

**Status:** CLI available; PySide6 desktop UI, structured editing service and AI
skill are planned, not implemented. No SQLite, MCP, telemetry or cloud upload.

## Development Setup

Requires Python 3.11+. Modified-file packing requires Windows and pywin32;
inspection, extraction and unchanged-file packing also work without Windows.
Review [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md) before installing anything.
The pins are development inputs, not an approved hash lock or release build.
Prepare a virtual environment with reviewed pip and setuptools >=77 first.

```powershell
python -m venv .venv
# Provision reviewed build tools in this environment before editable installation.
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
& .\.venv\Scripts\dgn-explorer.exe --help
```

On other platforms use `.venv/bin/python` and `.venv/bin/dgn-explorer`.
Direct execution also works: `python dgn_folder.py --help`.
`dgn-workspace` remains a compatibility command.

## Use

```powershell
dgn-explorer unpack input.dgn workspace
# Read workspace/WRITABLE.ro.md; edit only supported fields/content.
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

`.rw` means at least one supported edit, not that every field is writable. Follow
the schema's `editing` pointers. `.ro` stream/framing changes reject; labels are
guidance, not an authorization boundary. IDs and structural fields stay restricted.

Escaped bytes are default: Latin-1 maps all 256 octets reversibly; recognized
whole text uses UTF-8/16/32 with preserved byte order, BOM and terminators.
Encoding is strict. `--bytes-mode hex` and legacy v1 workspaces remain supported.
See [DGN_FORMAT.md](DGN_FORMAT.md) for the workspace contract.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s . -p test_dgn_folder.py -v
```

Synthetic tests need no DGN input. Optional sample tests need the specific baseline
fixture expected by `SampleTests`, not any arbitrary DGN; set `DGN_EXPLORER_SAMPLE`
to its approved local path, or place it at `sample.dgn`. No fixture is distributed.
These tests skip if absent; some require Windows. Outputs use temporary folders.
The optional [dgn_fixture_catalog.py](dgn_fixture_catalog.py) targets an existing
Bentley source-fixture layout; it is not installed or a generic fixture generator.
Its marker links are passive data, never activation instructions.

## Development

[PLAN.md](PLAN.md) is the backlog, [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md)
governs every dependency, and [AGENTS.md](AGENTS.md) guides AI-assisted changes.
Every code/UI change needs extensible automated tests and relevant regression
cases. Do not commit DGN inputs, workspaces, backups, secrets or generated binaries.
Project licensing, release signing and distribution approvals remain pending.