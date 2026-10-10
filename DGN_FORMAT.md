# Workspace Contract

Codec: [dgn_folder.py](dgn_folder.py). Tests:
[test_dgn_folder.py](test_dgn_folder.py), [test_application.py](test_application.py).
This is a **supported representation contract**, not a complete DGN specification.

## Files and Compatibility

| Path | Meaning |
|---|---|
| `original.dgn` | **Immutable** compound-file template; fingerprint checked before save/pack |
| `manifest.rw.json` | Stream paths/codecs/hashes and storage hierarchy; advanced codec input |
| `data/`, `framing/` | Stream schemas and retained prefix/suffix bytes |
| `objects/`, `attributes/`, `fields/` | Record schemas; identities/snapshots restricted |
| `content/` | Referenced text/XML/JSON stored as UTF-8, independent of wire encoding |
| `WRITABLE.ro.md`, `writable-index.ro.json`, other indexes/catalogues | Informational navigation; **not authority** |
| `.dgn-explorer/` | Application locks and recovery state; ignored by the codec packer |

- Current identifier: **`dgn-folder-v2`**. `dgn-folder-v1` remains supported.
  Prefer `manifest.rw.json`; fall back to `manifest.json`.
- Unmarked filenames are supported; do not remove/change the manifest's format identifier.
- Missing representation metadata means legacy binary semantics.
  The service editor requires **JSON-view** inputs; re-extract binary-only folders.
- Hex and escaped-byte workspaces remain reversible. Older opaque views and the
  old whole-stream uncompressed `Dgn~H` view remain usable without new edit permissions.
- Workspace references use relative forward-slash paths in JSON on every platform.
  Service object references stay in `data/objects/attributes/fields`; text references
  stay in `content`. Absolute/parent/drive escapes, links/reparse points and cycles reject.

## Editing Authority

`editing` lists `access`, `editable_fields` and `read_only_fields` as JSON pointers.
`.rw` means at least one supported input—not that every field is editable.
Markers do not grant OS permissions or trusted authority.

The service freshly extracts `original.dgn`, derives capabilities, and compares
identities/snapshots/structure. Modified labels cannot unlock fields.
Patches are **replace-only**; require a contextual record, revision, current
expected value and compatible typed/shape-preserving replacement.

**Protected:** IDs, snapshots, encodings/BOMs, framing, unknown bytes and unsupported
structures. Codec-owned sizes/counts/offsets are recalculated; native dependencies,
indexes, ranges and text metrics are not globally repaired.
Advanced direct codec mutations may fail stricter service validation.

## Reversible Bytes and Text

```json
{"kind":"byte-string","encoding":"latin-1","text":"Name\u0000\u00ff"}
```

- **Latin-1 maps octets one-to-one**, not semantic text; values above U+00FF reject.
- Recognized whole UTF-8/16/32 text retains byte order/BOM; UTF-32 BOMs are tested
  before UTF-16. BOM-less detection is conservative.
- Decoding/encoding must reproduce original bytes. Preserve terminators, padding
  and unknown tails; no replacement characters or competing editable hex/text copies.
- Content files use UTF-8; codecs restore the original wire encoding/terminators.
  XML/JSON edits validate syntax, not native semantics.
- Legacy `opaque-bytes` / `hex_rows` rebuild. Non-finite native numeric payloads
  are retained as opaque data rather than emitted as invalid JSON numbers.
- Editor Plain/Escaped/Hex/Base64 formats represent **strict UTF-8 string bytes**,
  not arbitrary DGN codepage conversion. Binary hex/Base64 inspection cannot unlock fields.

## Container Fidelity and Publication

- Input needs the CFB signature and unencrypted DGN V8 header; V7/encrypted DGN reject.
- Stored/decoded data and editable-file reads are bounded, including files growing
  during reads. Zlib requires EOF; unused trailing bytes remain preserved.
- `framed-raw` retains **20-byte `Dgn~H`** or **16-byte block** prefixes.
  Their different compressed/encrypted flag layouts are validated separately.
- Unchanged streams reuse original compressed bytes. **No-edit packing is byte-identical.**
- Extraction derives views from the retained `original.dgn` snapshot.
  Packing copies that original, applies supported streams, verifies every stream
  hash and storage hierarchy, then publishes a **new destination outside the workspace**.
- Changed compound storage requires Windows/pywin32; codec no-edit packing can
  operate without a writable non-Windows backend.
- Container verification does **not** prove native rendering/layout/domain integrity.
  Use approved isolated native checks. Targets/startup/embedded content are never activated.

## Transactions

`.dgn-explorer/` holds `writer.lock`, publication `transaction.json` and optional
UI `pending.json`. It is not DGN data or a workspace-version migration.

- OS locks coordinate cooperating operations; external changes conflict.
- Prepared saves retain before-images; reopen rolls back interrupted publication
  or verifies a completed commit before loading the workspace.
- Recovery targets must be reachable record/content namespaces; protected roots
  and unrelated files outside those namespaces reject.
- Failed recovery retains its journal. Imported/user workspaces are not deleted.
- Save As uses a staged snapshot and never implicitly saves workspace edits.

## Supported Format Boundary

| Family | Editing / inspection boundary |
|---|---|
| Text, text nodes, OLE properties, supported fixed metadata | Existing typed replacements; original codepages, IDs and structural constraints preserved |
| Selected geometry | Lines, point lists/shapes, ellipses/arcs/cells and existing pole arrays; service keeps array shapes; no dependency/layout repair |
| Headers and model index | Passive 1576-byte design header, 4096-byte model header plus retained data; bounded v2 index with cookie `0xAA00BA11`; file identity `Dgn~Mf` remains immutable |
| Metadata tables | Table-level routing and exceptions; **font names** replace UTF-16 with original terminator count; other cores passive |
| Tags | Graphic **version 3** Int16/Int32/double or supported ASCII strings; identities/codepage/options/extensions restrict edits |
| Linkages | Masks/dependency roots passive; **symbology weight 0–31**; DWG ASCII group 1000 and scalar groups 1040–1042/1070/1071 replace; app/handle/control/reference IDs stay read-only |
| XML fragments/linkages | Encoding 1 body or encoding 2 zlib; NUL-terminated UTF-16 despite inaccurate legacy declared counts; schema/app identities and unknown tails protected |
| XML/JSON metadata | ExtendedColors, lighting, DataGroup and Background Map content; EC schema XML read-only; DataGroup fragment structure/identity attributes protected |
| BECXML / ECX / ECXD | Passive tokens/headers, bounded tagged counts/strings/arrays/nesting; unknown versions/compression/tails preserved; schema paths never resolved |
| DgnStore / matrix / GCS / TFLabel / other native cores | Passive sequence/size/checksum assembly, allocated tails and selected fixed metadata; **no** repartitioning, provider fetching, topology or label regeneration |

Declared element/table/linkage names are inventory labels, not serializers.
BBES/ELCO registration matches are passive, not an electrical connection.
Full native authoring gaps remain in
[DGN_SPECIFICATION_GAPS.md](DGN_SPECIFICATION_GAPS.md); release/native-product
gates remain in [PLAN.md](PLAN.md).
