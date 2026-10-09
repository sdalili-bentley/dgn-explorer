# DGN Workspace Contract

Implementation: [dgn_folder.py](dgn_folder.py). Executable examples:
[test_dgn_folder.py](test_dgn_folder.py). This reference describes supported
representations, not a complete DGN specification.

## Files

| Path | Contract |
|------|----------|
| `original.dgn` | Immutable compound-file template; hash checked before packing |
| `manifest.rw.json` | Stream codecs/paths, hashes and storage hierarchy; advanced input |
| `WRITABLE.ro.md`, `writable-index.ro.json` | Informational edit navigation |
| `data/`, `framing/` | Stream and prefix/suffix schemas; supported/advanced fields only |
| `objects/`, `attributes/`, `fields/` | Supported record schemas; identity/snapshots restricted |
| `content/` | Referenced text/XML/JSON in UTF-8, independent of wire encoding |
| `*.ro` indexes/catalogues | Informational, not authoritative edit inputs |

Current identifier: `dgn-folder-v2`; `dgn-folder-v1` and unmarked legacy folders
remain readable. Prefer `manifest.rw.json`, falling back to `manifest.json`.
Do not rename format identifiers for product branding or migrate existing folders
silently. Legacy manifests without representation metadata retain binary semantics.

## Editing

Each schema's `editing` section lists `access`, `editable_fields` and
`read_only_fields` as JSON pointers; a read-only pointer covers its subtree.
`.rw` requires a supported editable input, but IDs, original snapshots and
structural values inside it can remain read-only. Empty/immutable views use `.ro`.
These markers do not set filesystem permissions or provide trusted authorization.
The shared editor derives capabilities from a fresh extraction of `original.dgn`,
compares records/snapshots/structure and ignores mutable `editing` labels. Its
replacement-only patches reject unsupported paths/types/shapes/encodings.
Read-only stream/framing schemas are retained for reconstruction and encoded
changes reject. Codec-owned sizes/counts/offsets are derived, not manually edited.

Object references carry `kind` and `file`. Hydration rejects unsupported kinds and
absolute, parent/drive or escaping symlink paths. Keep all referenced authoritative
files inside the workspace; indexes and snapshots are not alternative edit sources.

## Bytes and Text

```json
{"kind": "byte-string", "encoding": "latin-1", "text": "Name\u0000\u00ff"}
```

Latin-1 maps bytes one-to-one, not semantic text; code points above U+00FF reject.
Recognized whole UTF-8/16/32 payloads use their reversible encoding and optional
`bom_hex`. Decode/encode must reproduce every original byte. Test UTF-32 BOMs
before UTF-16; BOM-less detection is conservative. Preserve byte order, BOM,
terminators, padding and unknown tails. Human-facing content stays UTF-8; recognized
terminators are restored by the codec. XML/JSON replacements validate structurally.
No replacement characters, guessed mixed-record string schemas or competing
editable text/hex copies. Legacy `opaque-bytes`/`hex_rows` views also rebuild.

## Fidelity and Limits

Extraction requires the CFB signature and an unencrypted DGN header. Compression
and stored/decoded streams are bounded; zlib EOF is required and unused trailing
bytes are preserved. Unchanged streams reuse original compressed bytes; changed
streams use the existing codec. Unknown records stay opaque. Element identities,
reserved bits and dependent structural counts are not arbitrary authoring inputs.

Packing copies the original template, changes supported streams, verifies all
stream hashes and storage hierarchy, then publishes a new output. The Windows
writer uses pywin32; no writable non-Windows backend is provided. Existing output
or output inside the workspace rejects. Neither packing nor inspection activates
links, commands, applications, databases or embedded documents.

Geometry edits use stored units. They do not repair spatial indexes, cell ranges,
dependencies or text metrics. Container fidelity does not prove application-level
correctness. Use approved isolated application checks for edited outputs.

## Application Sidecar

`.dgn-explorer/` contains writer ownership, `transaction.json` during publication,
and optional `pending.json` for UI edit recovery. It is not a new workspace
version or editable DGN data. The old packer ignores it. Reopening recovers an
interrupted batch before validation; user-created notes/workspaces remain intact.
The shared editor supports JSON-view v1/v2, including unmarked/hex folders.
Binary-only legacy inputs remain a codec feature and need re-extraction for the
editor. Save As uses a staged disposable snapshot; it never implicitly saves the
workspace. New output is published only after verification, without clobbering an
existing destination. OS writer locks coordinate cooperating tool operations.