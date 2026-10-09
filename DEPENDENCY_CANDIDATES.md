# Dependency Candidates

Candidates are not approvals. Thirteen packages, including matched Qt 6.11.2, are admitted and installed
in the existing Windows x64 CPython 3.14 development environment. The
[manifest](dependency-approvals.json) identifies the automated reviewer and
explicitly excludes release approval. Official metadata, exact wheel inventories,
bundled-file hashes and advisory responses are retained under `dependency-evidence/`.

## Installed Development Set

| Scope | Exact Versions | Hash Lock |
|-------|----------------|-----------|
| Runtime | olefile 0.47, pywin32 311, PySide6-Essentials 6.11.2, shiboken6 6.11.2 | [Runtime](requirements-runtime.lock) |
| Build | setuptools 83.0.0, wheel 0.46.2, PyInstaller 6.22.2, altgraph 0.17.4, packaging 25.0, pefile 2024.8.26, pyinstaller-hooks-contrib 2026.7, pywin32-ctypes 0.2.3 | [Build](requirements-build.lock) |
| Test | coverage 7.10.6 | [Development](requirements-dev.lock) |

The selected versions and exact artifacts each meet the 31-day UTC gate. All
thirteen retained PyPI/OSV queries report no matching package advisory. This does
not clear native reports; their scoped decisions appear below. Setuptools' twelve
vendored identities also have exact registry/advisory evidence. This is bounded
evidence, not proof of vulnerability absence. Official wheel hashes verify,
offline hash-locked resolution/install succeeds, and `pip check` reports no broken
requirements. Existing olefile/pywin32 are reinstalled from reviewed bytes.

Setuptools 80.9.0 and wheel 0.45.1 are excluded because registry/advisory evidence
reports known issues; the selected versions meet the recorded fix ranges.
PyInstaller 6.22.2 meets the fixed range for GHSA-9fxf-4qw3-ghmr; newer immature
artifacts are not needed. No age exception or automatic resolver upgrade applies.

## Qt 6.11.2 Development Admission

| Candidate | Official Registry Evidence | Exact Windows Artifact SHA-256 |
|-----------|----------------------------|--------------------------------|
| PySide6-Essentials 6.11.2 | [PyPI](https://pypi.org/pypi/PySide6-Essentials/6.11.2/json), upload `2026-08-18T06:36:54.038925Z` | `c8a29def77032773a30879f7f24415b5395ad08592d147c170824ef4c735dfc1` |
| shiboken6 6.11.2 | [PyPI](https://pypi.org/pypi/shiboken6/6.11.2/json), upload `2026-08-18T06:37:18.00296Z` | `6ab0eba1c904455df621f9a6df3ca2bb896bab8670572d2bc4e37804ae91f19a` |

Selected filenames are `*-6.11.2-cp310-abi3-win_amd64.whl`, not yanked, with
Python `>=3.10,<3.15`. This matches the development interpreter's 3.14 ABI and
satisfies artifact age at `2026-10-09T00:00:00Z`. Downloaded bytes match both
official registry hashes. Both wheels qualify and are installed without an age exception.

[Qt package details](https://doc.qt.io/qtforpython-6/package_details.html) confirms
Essentials includes native libraries and depends on matched shiboken6.
[Qt advisories](https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products)
include QtXml serialization CVE-2026-15037 before Qt 6.12. The
[official advisory](https://www.qt.io/blog/security-advisory-cve-2026-15037-xml-injection)
supports older Qt with `QDomImplementation.setInvalidDataPolicy(ReturnNullNode)`.
[Desktop startup](dgn_explorer/desktop.py) sets that policy; the
[regression](test_ui.py) checks rejected comment/CDATA/instruction terminators.
The regression passes on the actual Qt 6.11.2 runtime with both Windows and
offscreen plugins. The binding, shiboken and native Qt version regression also
passes. This application
does not currently serialize QDom documents, and the XML advisory alone does not
require Qt 6.12.

The exact Essentials inventory contains no VNC module, so the VNC advisory is
not treated as a blanket Qt blocker. It does contain QML/extra native libraries,
WebEngine stubs and a Designer plugin; a Widgets-only import list is not a full
bundled-component inventory.

Tagged Qt 6.11.2 source attribution identifies HarfBuzz 14.3.0. The retained
[OSV report](dependency-evidence/native-harfbuzz-14.3.0-osv.json) lists that version
as affected by OSV-2026-962. The tagged native build list includes
`hb-subset-instancer-iup.cc`, and its `iup_delta_optimize` source still uses
`count - 4` without the guard visible in the upstream fix. Those source snapshots
are retained as `qtbase-6.11.2-harfbuzz-source.txt` and
`qtbase-6.11.2-harfbuzz-iup-source.txt` in the evidence folder.
An affected bundled version is not proof of an applicable application defect.
[Desktop content](dgn_explorer/desktop.py) uses `QPlainTextEdit.setPlainText`;
the UI exposes no custom-font loading, font subsetting, printing or PDF export.
OSV-2026-962 concerns font-subsetting optimization, not normal text shaping.
The current DGN input flow does not supply font files to that operation. This
supports application-scoped non-applicability, not a claim that HarfBuzz 14.3.0
contains the upstream fix or that all Qt consumers are unaffected.

For [OSV-2026-1068](dependency-evidence/native-libjpeg-turbo-3.2.0-osv.json), the
reported stack uses `tj3Compress8`. The tagged
[Qt JPEG build](dependency-evidence/qtbase-6.11.2-jpeg-source.txt) contains the
libjpeg API sources, not the TurboJPEG `turbojpeg.c` wrapper. The desktop also
does not send DGN images to Qt image codecs or expose image preview/encoding.
The source-level [boundary regression](test_application.py) checks the reviewed
imports/calls and literal text views; it is a review tripwire, not a native
binary reachability proof. Re-review these decisions before adding font loading,
printing, PDF export, image previews, new Qt modules/plugins or changing wheels.

## Decision and Lesson

Treating OSV version matches and bundled source presence as an automatic block
is too broad for this application. The solution is to retain the advisories,
record exact prerequisites and current input-to-sink reachability, apply the
vendor-supported XML policy, and test the real Qt runtime. Qt 6.11.2 meets the
age/ABI/hash requirements; no HarfBuzz replacement, custom Qt build or age
exception is necessary for this plain-text, non-printing development profile.

Lesson: separate artifact age, affected-version identification and application
exploitability. Check vendor mitigations and available interfaces before blocking
work. Never equate this scoped decision or passing tests with a blanket claim
that the bundled library is patched, vulnerability-free or approved for release.

Exact PyPI queries for matched 6.11.3 and 6.8.9 packages return 404, not clean
security evidence or usable alternatives. Matched 6.11.2 admission/install succeeds
under the scoped decision above, and all 23 Windows Qt tests pass, including
the real worker integration. Distribution approval,
native notices and packaged application validation remain separate gates.

The [offline checker](dgn_explorer/policy.py) checks recorded evidence and exact
artifact hashes, not discovery or legal approval. Its `--release` mode rejects the
development-only manifest. Portable validation and full offline build enforcement
remain blocked. Do not install newest versions automatically.