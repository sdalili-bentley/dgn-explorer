---
name: dgn-explorer
description: "Inspect local DGN V8 workspaces, search contextual records, preview supported metadata/text replacements and publish approved new copies. Not CAD rendering, fuzzing or active-content execution."
---

# DGN Explorer

Use `dgn-explorer`, or `python -m dgn_explorer` from a trusted checkout.
Load this skill explicitly if undiscovered. No GUI/MCP/network/model credentials required.

## Workflow

1. Confirm input and scope. **Keep content local**; never upload, follow targets
   or execute embedded/startup commands.
2. Extract to a new folder:
   `dgn-explorer --json unpack INPUT.dgn WORKSPACE`.
3. Discover bounded records:
   `dgn-explorer --json list WORKSPACE --limit 20` or
   `dgn-explorer --json search WORKSPACE --text QUERY --limit 20`.
   Use `next_cursor`, `--model` and `--kind`; an ID alone is not a locator.
4. Inspect returned locator JSON, quoted for your shell:
   `dgn-explorer --json show WORKSPACE --record LOCATOR_JSON`.
   Trust returned `editable_fields` / `revision`, **not mutable `.rw` labels**.
5. Create `dgn-explorer.patch-v1` with returned `workspace_revision` and
   `operations`: `record`, `pointer`, current `expected_value`, typed `value`.
   **Replace only**; never alter identities, snapshots, encodings/BOMs, framing or unknown bytes.
6. Preview:
   `dgn-explorer --json apply WORKSPACE --patch PATCH.json --dry-run`.
   Explain changes and native-application limitations.
7. Obtain **explicit human consent** for workspace/file writes or DGN publication.
   A flag is not consent. Then:
   - Save: `dgn-explorer --json apply WORKSPACE --patch PATCH.json --approve`.
   - Export staged copy: `dgn-explorer --json pack WORKSPACE NEW.dgn --patch PATCH.json`.
     This does **not** save the workspace.
8. `dgn-explorer --json validate WORKSPACE`. Require a **new output outside the workspace**.
   Conflicts need a reloaded revision/value, never bypasses.
   Container verification is **not native rendering/domain validation**.

## Results

`--json`: **`dgn-explorer.result-v1`**, with `operation`, `success`, `result`,
`warnings`, `errors`. Usage errors have `operation: null`; human errors use stderr.

| Exit | Meaning |
|---|---|
| 0 / 2 | Success / usage error |
| 3 / 4 | Invalid or unsupported input / revision, expected-value or ownership conflict |
| 5 / 6 / 7 | I/O failure / cancellation / backend or verification failure |

- Unencodable/out-of-range/malformed replacements exit **3**.
- Search: **literal, case-insensitive**, current values only—not snapshots/JSON syntax.
- Pages: **1–1000**; keep requests small. Stop when `next_cursor` is `null`.
- Defaults: **128 MiB/stream**, **2 GiB aggregate**, **100 operations / 16 MiB patch**.
  Global limits precede commands.
- JSON-view v1/v2/hex work; binary-only legacy folders need re-extraction.
  Preserve originals; never silently migrate.

## Strings and Files

- CLI values are **decoded JSON strings** (`"A\u0000B"`), not literal hex/Base64
  unless those characters are intended.
- Desktop Plain/Escaped/Hex/Base64 represents strict UTF-8 bytes; wire encoding
  stays unchanged. `\\` = backslash; `\u0000` / `\x00` = NUL; `\r` / `\n` / `\t` = controls.
- Load File changes a **draft only**, up to **64 KiB** or a smaller service limit.
  Invalid/non-UTF-8 string drafts cannot be staged.
- Export File writes decoded bytes; Export Page writes the raw **4 KiB page**.
  Require consent/new files outside the workspace.
- Service/worker `load-field`, `export-field`, `export-bytes` are **not CLI commands**.
  Shared `codecs.editor_encode` / `editor_decode` / `editor_text` format keys:
  `plain`, `escaped`, `hex`, `base64`.
