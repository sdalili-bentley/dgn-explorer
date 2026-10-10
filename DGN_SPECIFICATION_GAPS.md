# DGN Specification and Implementation Gaps

Source review: 2026-10-10. Target: the current, locally modified
`C:\tools\dgn-explorer` checkout; not an assertion about a published build.

Implementation follow-up: the later source checkpoint adds bounded framing,
table routing, scalar/XML-fragment replacements and passive native/BECXML/ECXD
inspectors. See [DGN_FORMAT.md](DGN_FORMAT.md) and [TESTING.md](TESTING.md).
The baseline/gap tables below describe the initial review; unknown/versioned
layouts and native/provider/graph authoring gaps are not closed by this tranche.
Follow-up tracing confirms ECXD instance handler major `0xECDA`, minor 0
(`S21:14,158-159`), distinct from ECXAttributes major 22271.

## 1. Scope, evidence and interpretation

This is a source-backed implementation specification and gap catalogue, **not
a complete, vendor-approved DGN specification**. It describes the core V8
container, declared element families, attribute mechanisms and selected building
and electrical persistence implementations. Search coverage is not semantic
coverage: third-party serializers, conditional compilation, obsolete formats,
runtime-generated schemas and application-specific handlers require further
individual review. No finite keyword search can establish that nothing is missed.

Only local source inspection was performed. No source/document data was uploaded,
native application launched, embedded target activated or dependency installed.
Source declarations are summarized rather than reproduced wholesale.

Evidence classes:

- **W**: writer/reader establishes a persistent representation.
- **D**: declaration establishes an ID or structure; exact disk conversion,
  packing, version and variable-length layout still need writer confirmation.
- **A**: application semantics or API, not a disk structure.
- **U**: not established in the inspected persistence paths; retain opaque bytes.

All source references below use `Snn:line[-line]`. The source register in section
12 expands each reference to an **exact absolute Windows path**. Line numbers
refer to this local source snapshot and can drift. Symbol names are additional
anchors. A field list without explicit offsets is **not permission to use
`ctypes` or native `sizeof` as a disk serializer**. Pointer-bearing API objects
must never be mapped directly onto document bytes.

### Exploration method and boundary

1. Enumerated the four roots and their extensions.
2. Searched headers, C/C++/C#, resources and FDFs for storage names, element
   declarations, linkage IDs, XAttribute registries and persistent serializers.
3. Followed native V8 writer/reader, XML-fragment, EC, building and electrical
   persistence entry points; compared the actual Python codec functions.
4. Rechecked primary declarations against their serialization consumers, including
   contradictory comments and encoding/compression names.
5. Performed a bounded full text census, and a document-reference/ID review.

The roots contain 35,662 PowerPlatform, 16,272 PPBase, 30,635 OpenBuildings and
20,698 ElectricalSystems files at initial enumeration. These include assets,
fixtures, vendor dependencies and generated code, not just source. The text
census selects `.h`, `.hpp`, `.cpp`, `.c`, `.cxx`, `.cs`, `.fdf`, `.idl`, `.xml`,
`.xsd`, `.json`, `.r`, skips individual files larger than 4 MiB and records
encoding fallback. Lexical fallback is for **discovery only**, never a proposed
DGN decoding policy. Census results and remaining limitations are in section 13.

## 2. Current Explorer capability baseline

Implementation remains in `dgn_folder.py`; `dgn_explorer\codecs.py` re-exports it.
`DGN_FORMAT.md` specifies workspace behavior, not the complete native format.
`dgn_explorer\workspace.py` provides replacement-only editing derived from a fresh
extraction of immutable originals. An escaped byte string is reversible binary,
**not evidence of semantic support**.

| Area | Implemented | Still missing |
|---|---|---|
| CFB/OLE | Signature checking, passive stream/storage enumeration, original-template repack and hash/hierarchy verification | Typed native storage-role catalogue, block-chain and cross-stream consistency checks |
| Stream compression | `inflate`, `decode_stream`: bounded zlib, 20-byte `Dgn~H` prefix, 16-byte `$` block prefix, preserved suffix and unchanged compressed bytes | Flag/version-aware dispatch and diagnostics instead of only successful-inflate discovery; encrypted payload semantics |
| Element chunks | `element_chunks_view`, generic type/flags/size, IDs, level, modification time, graphic display metadata, opaque remainder | Full complex-element graph, semantic dependency/index/range/checksum repairs |
| Geometry | `geometry_view`: types 2, 3, 4, 6, 11, 13, 15, 16, 21; 2D/3D coordinates, limited transforms | Spline assembly, point-string rotations, cones, surfaces/solids, shared cells, multiline, dimensions, mesh/topology, application graphics |
| Text | `text_element_view`: types 7/17, font/placement/orientation/size/string metadata | Complete rich-text/run/paragraph/style/field dependency semantics and native metrics |
| Fixed records | `RECORD_LAYOUTS`: partial 12, 14, 94, 100, 106, 107; limited type-66 application/startup and database discovery | Most native metadata/table/application cores |
| Linkages | `linkages_view`, `LinkageUtil`-compatible size handling, ID/payload preservation, `0x56D2` string key decoding | All other registered linkage payload schemas; many string keys lack semantic validation |
| XAttributes | `attribute_sets_view`: set and attribute envelopes, archive/reserved fields, `attribute_payload_view`: reversible whole text, known compression envelope | Handler/version registry, ownership/cross-reference validation, binary EC and XML-fragment adapters |
| EC fields | `text_field_view`: handler `0x57050000`, attribute 0, selected dictionary/expression/link metadata | Generic EC instance/schema/relationship/Item Type authoring; computed-field evaluation |
| XML/JSON | `text_view`: conservative whole-payload strict reversible text and structural XML/JSON validation | Embedded sub-record discovery and schema-aware editing; generic parsing does not validate native semantics |
| OLE properties | `properties_view`/`properties_bytes`: selected property scalar types/codepages, offsets/counts reconstructed | Complete property-set type support and protected/signed property lifecycle |
| Service editing | Identity/snapshot protection, strict encodings, staged replacement edits, transactions, new-output publication | Safe record/element/stream creation/deletion and ID remapping through the service; native correctness guarantees |

Legacy low-level manifest capabilities do not imply service/UI support for
arbitrary creation/deletion. Current editable headers/geometry can produce
container-valid bytes without repairing native relationships. This document
does not broaden those capabilities or change any codec.

## 3. Container, storage paths and framing

### 3.1 Canonical storage catalogue

Evidence **W**, primarily `S01:41-78`, `S01:3530-3600`,
`S01:3934-4064`, `S01:4548-4633`; suffix `A` is constructed by
`DgnV8ElmListReader::Open`, not a separate hand-maintained list.

Here `M` denotes `Dgn-Md\#%06x` or `Dgn-Nd\#%06x`; `%06x` is a
minimum-width hexadecimal **model ID**, not a filename or element ID.

| Feature/path | Expected representation and identifiers | Missing integration |
|---|---|---|
| Root `Dgn~H` | 20-byte `V8FileHeader`, then design header; `S01:109-115`, `S01:1792-1796` establishes design header size 1576 | Type file-version/header flags; preserve reserved/encryption words; reject unsupported versions/encryption |
| Root `Dgn~Mf` | Manifest/file identity; `S01:1742-1770`, header-write commentary `S01:2003-2013` | Inspect identity without editing/reissuing it |
| Root `Dgn~S` | Session data; `S01:44`, `S01:2096`; volatile per `S03:6803` | Classify separately from authoritative model content |
| Root `Dgn^Nm` / `Dgn^NmA` | Dictionary elements and corresponding XAttributes; `S01:47`, `S01:2191`, `S01:3688` | Join dictionaries with typed tables, schemas, names and references |
| `Dgn-Md`, `Dgn-Nd` | Indexed/non-indexed model stores, not payload streams; `S01:42-43`, `S01:164` | Include both in model discovery; current inventory specifically tests `Dgn-Md` |
| `M\Dgn~Mh` | `V8ModelHeader`: 4096 bytes, block count, major/minor version and reserved words; `S02:872-894` | Validate block membership/count/version before edits; no model creation yet |
| `M\Dgn^C`, `M\Dgn^G` | Control/non-graphic and graphic element-block storages | Attribute/element ownership by list and model; avoid treating control data as graphic |
| `M\Dgn^CA`, `M\Dgn^GA` | XAttribute storages derived from corresponding element list | Join by element ID **and model/list/block context**, not globally by ID |
| Attribute store `^AH` | UInt32 highest attribute-block serial, `S01:3540-3554` | Bounded validation, holes/orphans reported without silent repair |
| Element/attribute `$%d` block streams | Decimal serial names supplied by `getBlockName`, `S01:335-348`, 16-byte `BlockHeader` | Validate sequence; preserve original names and block assignments |
| Root `Dgn^Ix\Dgn~Mix` | Model/cell catalogue, cookie `0xAA00BA11`; `S01:53,67`, `S02:794-843` | Typed index inspection, reconcile models/names/masks; regeneration prerequisite to structural editing |
| `M\Dgn^Thumbnails` | Named thumbnails, header and payload; `S01:6338-6379` | Passive bounds/type inspector; no image decoder/font/plugin admission implied |
| Root `Dgn~Fprov`, `M\Dgn~Mprov` | File/model provenance names, `S01:55-56` | Inventory and preserve; exact provenance schema remains U |
| Root `Dgn~Pr\<property-set>\<property>` | Protected property values, `S01:2272-2368` | Recognize protected content and do not expose it as editable clear properties |
| Root `.Embedded\.Index`, child embedded stores, `~Data` | Embedded DGN/foreign-file catalogue; signatures and IDs below | Passive catalogue, bounded raw export only after path checks; never recursively launch/open embedded targets |
| `.EmbeddedFonts` | Separate embedded-font catalogue, `S04:2725,2803` | Inventory bytes and metadata only; loading fonts is a separate dependency/security decision |
| `Dgn~ULC`, `Dgn~RLC`, `Dgn~RMC`, `Dgn~SKY` | Protection licenses/certificates/key material, `S03:49-54` | Encrypted/protected feature diagnostic, no key interpretation/editing in this scope |
| `.Logfile` / `.History` history contents | `.Admin`, `.Admin2`, revision `.Info`; model catalogs `%d`, `E%d`, `Y%d`, `X%d`, `S05:35-44` | Decode history only after revision/root/version semantics are traced; never treat history records as live elements |

**Requested example names are not automatically real stream roles.**
`Dgn-Hd`, `Dgn-Cd` and `Dgn^A`, `Dgn^P`, `Dgn^S`, `Dgn^X`,
`Dgn^R`, `Dgn^L`, `Dgn^V`, `Dgn^D`, `Dgn^E` were not established
as canonical roles by the reviewed V8 naming definitions. `S03:6765-6767`
mentions `Dgn~Cix` and `Dgn-Cm` in integrity commentary, including an explicit
unresolved comment; this is weaker than an active writer. Retain/inventory any
observed unknown name rather than invent a layout. Actual levels/views/materials
often reside in **elements or XAttributes**, not one stream per feature.

### 3.2 Binary framing layouts

All explicit integer offsets below are bytes relative to the stated record.
Core V8 examples use little-endian storage; application payloads can override it.

| Record | Source | Proven/declarative layout |
|---|---|---|
| V8 file prefix | S01:109-115 | Offset 0 UInt16 flags; 2 UInt16 compression level; 4 four UInt32 encryption words; total 20 bytes |
| Element block prefix | S01:117-128 | 0 UInt32 entry count; 4 UInt32 flags; 8 two reserved UInt32; total 16. Last block `1`, compressed `2`, encrypted `4` |
| File flags | S06:388-389 | File compressed `1`, encrypted `2`; **different from block encryption bit 4** |
| Element chunk | S02:854-869 | 0 UInt32 signature; 4 UInt16 type; 6 UInt16 flags; 8 UInt32 element word-size. Signature 0 for element; next chunk begins at `4 + 2*word_size` |
| XAttribute set | S01:130-137, S01:3428-3468 | Signature `0xA11B`; UInt32 setSize/setType/reserved; UInt64 element ID; then UInt32 count and set payload. Array set type `0xAA` in S07:20-23 |
| Current array attributes | S56:2145-2175,2292-2327; Python `attribute_sets_view` | Four UInt32 per attribute: handler ID, attribute ID, size/archive-bit, reserved; payload bytes, then set flags. Size low 31 bits, archive high bit. Zero-count historical sets still have flags; count bounded to 65535 |
| Model index header | S02:794-800 | Cookie/version/itemCount/headerLength: four UInt32; extra headerLength bytes excluded from base struct |
| Model index v2 item | S02:822-843; S01:4622-4632 | 0 modelType UInt16; 2 flags UInt16; 4 modelID; 8 lastSavedTime double; 16 total byte length; 18 name length; 20 description length; 22 unused; 24 level-mask length; 26 cellType; 28 four padding bytes; base size 32 |
| Embedded-file list | S01:5216-5222 | Signature, nextId, nEntries and ten reserved UInt32, base 52 bytes; actual entry reader/writer remains prerequisite |
| Embedded magic IDs | S01:74-78 | C++ multichar constants `'EfLs'`, `'Embd'`, `'Alia'`, `'V8Dg'`. Treat as numeric/compiler-defined constants until emitted byte order is verified; **do not label spelling as on-disk byte sequence** |
| Thumbnail | S01:6338-6344 | UInt8 format, UInt16 width/height, UInt32 rawSize; **native alignment matters**, offsets/size not asserted by this declaration alone |

Integration: create read-only typed framing views using bounded cursors; verify
count, size, EOF and residual bytes. Keep block-count and identity fields
read-only. Preserve exact prefix/suffix/reserved data and original compressed
bytes on unchanged repack. Recalculate only owned sizes/counts after a fully
supported edit. No opportunistic inflation of encrypted blocks.

## 4. Element header, coordinates and all declared type numbers

### 4.1 Header and coordinate contract

`S08:259-327` (**D**, corroborated by reader `S01:2883-2933`) defines:

- `Elm_hdr`: type/flags UInt16; elementSize/attrOffset UInt32 in **16-bit
  words**; level ID; 64-bit unique ID; double lastModified. Base header is
  32 bytes in the supported V8 representation: type 0, flags 2, elementSize 4,
  attrOffset 8, level 12, uniqueId 16, lastModified 24.
- Flags: six reserved bits, two archive bits, obsolete bits, nonModel, locked,
  isGraphics, isComplexHeader, complex and deleted. Preserve unknown bits.
- Graphic elements add `Disp_hdr`: graphic group UInt32, priority Int32,
  properties/reserved UInt16, Symbology and ScanRange. Combined `Header`
  size **104** is asserted by `S01:2883`.
- Properties include element class, invisible, dynamicRange, new/modified,
  is3d, relative-to-screen, planar, nonsnappable and hole flags.
- **File range differs from in-memory range**: native reader adds stored
  low/origin to stored high/distance at `S01:2921-2933`. Explorer exposes raw
  six Int64 values. Do not label them as six independent min/max coordinates
  without conversion. Repack must invert any derived low/high presentation.
- Geometry declarations use double point/vector coordinates; 2D points have
  two doubles, 3D three. RotMatrix is a 3×3 transform where used; quaternion
  arrays are distinct from matrices. Coordinate values are generally stored
  units/UORs, **not automatically meters**.
- `ModelElement` carries globalOrigin, storage/master/sub-unit ratios,
  `uorPerStorage`, modelRange, ACS identity/origin/rotation, grid and scale:
  `S08:1781-1831`. Unit conversion must follow these ratios, not a global constant.

Implement an immutable `ElementLocator(model,list,block,element_id)` and explicit
stored-versus-derived range/unit views. Validate header extent, attrOffset,
flags/dimensionality, finite geometry and child boundaries. A decoded double
does not establish its physical meaning. Structural edits need identity,
range, dependency and index repair before typed editing is admitted.

### 4.2 Complete core enum coverage, including unassigned values

Authority: `MSElementTypes`, `S09:1970-2037`. The declared maximum is **113**,
not 128. Type **1 is Cell Library**, **2 is Cell Header**. Type 13 is the
private Conic declaration. All values 1–128 are accounted for below.

Support: **P** limited typed payload; **H** generic header/linkage with payload
opaque; **F** a small fixed-core subset; **N** missing enum label. Every row is
binary unless a linkage/application payload explicitly declares text.
All rows inherit section 10's decode/validate/repack requirements.

| Type(s) | Feature / native declaration | Explorer / integration gap |
|---|---|---|
| 1 | Cell Library, `S08:1014-1030` `cell_lib_hdr` | N; inspect legacy library header, preserve version fields; no library authoring |
| 2 | Cell Header, `S08:336-382` `cell_2d/cell_3d` | P; count/class/flags/range/transform/origin exposed. Build child tree, validate class/range and dependency propagation |
| 3 | Line, `S08:386-407` | P; two points. Repair graphic/cell/model ranges before semantic editing guarantee |
| 4, 6, 11, 13 | Line String, Shape, Curve, Conic, `S08:418-446`, enum S09 | P counted points; distinguish curve/conic interpolation semantics from a simple polyline; shape closure is not full geometric validity |
| 5 | Group Data/color table, `S08:449-455` `colorTable` | H; native palette interpretation and color-index mapping |
| 7 | Text Node, `S08:461-499` | P; text run/child hierarchy, node layout and field/style coordination still missing |
| 8 | Digitizer setup data, S09 enum | H; legacy payload writer not established, U; inspect only |
| 9 | Design-file header element, `S08:504-508` | H; distinguish legacy element form from root `Dgn~H` |
| 10 | Level symbology, S09 enum | H; legacy mappings not interchangeable with modern level tables |
| 12, 14 | Complex String/Shape, `S08:515-522` | F count only; ordered child assembly and geometric closure/topology |
| 15, 16 | Ellipse/Arc, `S08:528-586` | P; axes/origin/angle/quaternion; native range/angle/orientation invariants and full tails |
| 17 | Text, `S08:592-631` | P; strict character encoding and placement; rich runs/font metrics/annotation dependencies |
| 18, 19 | Surface/Solid, `S08:636-645` | H; componentCount, subtype/boundary/rule metadata; projection/revolution components and closure must be assembled |
| 21 | B-spline poles, `S08:651-675` | P points only; do not resize without parent pole/count/weight updates |
| 22 | Point String, `S08:679-702` | H; counted points **and per-point rotation data**, not same schema as type 4 |
| 23 | Cone, `S08:707-725` | H; centers/radii/orientation and cylindrical/conical semantics |
| 24 | B-spline Surface, `S08:768-782` | H; u/v pole/knot/rule counts, flags, boundaries and child assembly |
| 25 | B-spline surface boundary, `S08:789-795` | H; non-graphic boundary number/count and UV `DPoint2d` array |
| 26 | B-spline knots, `S08:828-832`, S09 enum | H; double knot vectors, multiplicity/order/closure validation |
| 27 | B-spline Curve, `S08:813-821` | H; componentCount, flags, pole/knot counts and children |
| 28 | B-spline weights, `S08:802-806`, S09 enum | H; double weights with parent pole cardinality |
| 33 | Dimension, `S08:1034-1289` | H; style IDs, version/subtype/view/count bytes, option blocks, flags, quaternions, `DimPoint`/`DimText`, computed checksums. Never infer all dimension layouts from one subtype |
| 34 | Shared Cell Definition, `S08:1461-1473` | H; child count, version/anonymous/class, rangeDiag, rotScale and origin |
| 35 | Shared Cell Instance, `S08:1479-1491` | H; freezeGroup, SCOverride/class, rangeDiag, rotScale and origin; resolve definition identity through native reference mechanism |
| 36 | Multiline, `S08:1508-1591` | H; points, joints, break tables, caps, profiles, parent style/scale/offset; all counts and associations validated together |
| 37 | Tag/Attribute, `S08:1595-1634` `AttributeElm` | H; version `0x0003`, flags, attribute-def/type IDs, dataBytes/newDataBytes, codepage, value union and display metadata |
| 38, 39 | DgnStore component/header, `S08:3927-3951` | H; sequence assembly, application ID, checksum and sizes; see section 7 |
| 44 | Type44, S09 enum | H; no specific payload declaration proven here, U; do not invent “geometry type 44” |
| 66 | Application element, `S08:925-933,3913-3919` | P selected signatures/startup/database fields; dispatch by graphics/level/signature/application version, not type alone |
| 87, 88 | Legacy Raster header/component, `S08:878-918` | H; format/flags/dimensions/payload and bounded legacy RLE |
| 90, 91 | Raster reference/header components, `S08:1964-2024,2063-2420` | H; versioned attachment, masks/clip/color/transparency/georeferencing/rendering/unit components |
| 92, 93 | Raster hierarchy/complex components, `S08:2028-2061` | H; component count and linkage to raster children |
| 94 | Raster Frame, `S08:2490-2615` | F version/count/flags/transform only; versions including v4, transparency/render flags/tails require exact separate adapters |
| 95, 96 | Table Entry/Table, `S08:2637-2678` | H; typed routing by level/table ID, section 5 |
| 97, 98 | View Group/View, `S08:1647-1703` | H; child counts, view flags, camera/rotation/clipping/level masks and XAttributes |
| 99 | Level Mask, `S08:2619-2630` | H; reference-level ownership and default-bit mask semantics |
| 100 | Reference Attachment, `S08:939-973` | F count/version/group/file/parent ID; transform, clipping, units, nesting, model/file/name/dependency metadata still missing |
| 101 | Matrix Header, `S08:3982-4000` | H; component count/version, numPerStruct/numPerRow, tag/indexFamily/indexedBy |
| 102, 103 | Matrix Integer/Double Data, `S08:4014-4053` | H; maxValue/numValue/transformType, row-major Int32/doubles; preserve allocated unused values |
| 105 | Mesh, `S08:4062-4069` | H; meshStyle plus child matrices; points/normals/UV/color/facet indexes, signed indices/base/terminators must not be conflated |
| 106, 107 | Extended graphic/non-graphic, `S08:977-1001` | F child count; handler-selected extended payload/XAttributes |
| 108 | Reference Override, `S08:3841-3855` | H; attachment/view/level overrides with qualified IDs |
| 110, 111 | Named Group header/component, `S08:3861-3899` | H; names/type flags/member paths; graph ownership and qualified far references |
| 112, 113 | Deprecated component instance/representation, S09 enum | H; existing files can contain these; no modern rewrite assumptions |
| 20, 29–32, 40–43, 45–65, 67–86, 89, 104, 109, 114–128 | Not assigned by this enum | Unknown, **not known invalid or universally reserved**; preserve and report. Do not add fabricated names |

**Second-pass correction:** comments above `bspline_weight` and `bspline_knot`
in `S08:798-832` swap type numbers. The authoritative enum says **26 knots,
28 weights**. Use enum plus writer/handler behavior, not those comment captions.

### 4.3 Matrix/mesh and spline minimum decoder specification

Matrix header core: UInt32 componentCount; UInt16 version and 35 reserved shorts;
five UInt32 fields numPerStruct/numPerRow/tag/indexFamily/indexedBy. Integer
and double matrix cores instead begin version+35 reserved shorts followed by
maxValue/numValue/transformType/reserved2 and their arrays. `maxValue` is
allocation capacity, not used cardinality. Version-0 reserved bytes may be
uninitialized: preserve them rather than normalize to zero.

Integer index masks in `S08:4003-4012`: block `0x000F`, base `0x00F0`
(zero `0x0010`, one `0x0020`), pad `0x0F00` (none/zero/minus-one),
signed `0x1000`. Double transform masks `S08:4030-4038`: coordinate `0x00F`,
dimension `0x0F0`, unit-length preservation `0x100`. Do not expose generic
“mesh faces” until meshStyle/tag/indexFamily and child ordering are decoded.

Spline curve header core is componentCount, flags, num_poles, num_knots;
surface adds u/v counts/rules and num_bounds. Validate order and periodic/rational
flags from `Bspline_flags`/`Bsurf_flags`, monotonic knot sequences where required,
weight/pole compatibility and UV-boundary ownership. A geometry edit requires
parent/child counts, all ranges and trim/dependency data to remain consistent.

## 5. Models, levels, views and metadata tables

Tables are binary type 96 headers with type 95 entries, routed by table level,
not guessed OLE stream names. IDs below come from `S08:144-169` (**D**).
Every item is presently header/opaque or generic text only, not a typed table
editor. Integration for every row: decode a versioned entry, inspect ID/name
and foreign references, validate cardinality/cross-references, allow narrowly
supported scalar replacement, repack exact reserved/extension bytes.

| Table level | Feature | Source structure(s) and missing semantics |
|---|---|---|
| 1 | Levels | `S08:2665-2734`: `levelTableElm`, `levelEntryElm`, flags/flags2; ID, code, override/element symbology and access/visibility state |
| 2 | Fonts | `S08:2768-2776`: `fontTableEntryElm`; font type/identity/name, resource/SHX/TrueType distinctions; no glyph/font loading |
| 3 | Text Styles | `S08:2783-2790`; link font/text metadata to style, annotation and nested options |
| 4 | Filters | `S08:2738-2761`; members and expression strings, no expression execution |
| 5 | Dimension Styles | `S08:2797-2810,3138-3295,3455-3468`; style/default/override/option blocks and IDs |
| 6 | Multiline Styles | `S08:3474-3529`; profile offsets/caps/symbology and usage references |
| 7, 8 | Line Style Names/Definitions | `S08:3536-3612`; name-to-definition/component mapping; strokes, symbols and image data need their own serializers |
| 9 | Dictionary | `S08:3619-3640`; name/ID maps and nested references |
| 10 | Registered applications | `S08:3644-3661`; prerequisite for DWG-style XData application IDs |
| 11 | ColorBook table | `S08:3667-3684`; book/name/RGB identities, not just RGB palette slots |
| 12 | Custom render mode | `S08:156`; explicitly deprecated/never production-used; preserve, no default editor |
| 16 | Symbol styles | `S08:3690-3709`; detailing symbol/font/cell dependencies |
| 17 | ColorBook data | `S08:158`; color-book XAttribute content and aliases require dispatch |
| 18 | Material palettes | `S08:3715-3737`; internal/external palette/material mapping and texture references |
| 19 | Level-name dictionary | `S08:3770-3790`; name lookup must reconcile level IDs |
| 20, 21 | Animation parameters/schedules | `S08:161-162`; linkage/XAttribute-driven records, passive timeline inspection only |
| 22, 23 | Render/Light setups | `S08:163-164`; structured rendering data, section 8 |
| 24 | Named presentation | `S08:3743-3764`; conditions and geometry/presentation links |

Unassigned table levels must remain opaque; no assumption that gaps 13–15 are
unused in every application.

Additional metadata gaps:

- **Model settings**: `ModelElement`, `S08:1781-1831`; master/storage/sub-unit
  ratios, sheet/drawing/model type union, global/ACS origin, style/grid/background
  settings. Legacy `ModelElement_V0/V1`, `S01:3620-3654`, prevent one universal
  offset table. Decode model identity and units read-only first.
- **View/view group/level masks**: `S08:1647-1703,2619-2630`; route related
  XAttributes and per-view reference masks; camera vectors are not a DPoint3d
  geometry substitute. No camera/rendering execution is required for inspection.
- **ACS**: `aux_coordinate`, `S08:3797-3818`, linkage 20389; keep active model
  ACS ID/rotation consistent with named ACS entry.
- **References/update order/named groups**: `S08:3822-3899`; distinguish file,
  model, attachment and member IDs. Targets remain strings; do not resolve or
  fetch them during validation.
- **Geographic coordinate systems**: `S10:15-139`, signature **182/0x00B6**
  from `S08:196`. Master/alternate subsignatures **0x1000/0x2000**; versions
  2/4000 and 3/0 have different capabilities. Historical base/union split
  at **offset 858** is explicitly packed little-endian. Layout includes size,
  datum/ellipsoid/projection fields, fixed character names, transformParams[12],
  verticalDatum validity marker **0x8117**, EPSG and grid-file metadata. This is
  a versioned legacy contract, not a universal GCS XML/JSON stream. Expose passive
  source/units/datum metadata; grid files and reprojection remain out of scope.

## 6. Linkage registry and binary attribute gaps

### 6.1 Envelope and known string format

`LinkageHeader`, `S08:243-251`, has a UInt16 packed word (8-bit mantissa,
4-bit exponent, user/modified/remote/info bits) and UInt16 primary ID.
`LinkageUtil::GetWords/SetWords`, `S11:36-98`, establishes:

- Non-user DMRS linkage is exactly **four words/eight bytes**.
- User + non-remote: `mantissa + 1` words.
- User + remote: `mantissa * 2**exponent` words, bounded to native max.
- Payload padding/remote sizes are part of fidelity, not automatically strings.

Explorer already handles this envelope. Missing typed handlers must not replace
its raw-preserving fallback. Keep aliases and duplicate linkages in original
order; ID alone can be insufficient without key/version/application context.

`MSStringLinkageData`, `S09:1229-1240`: UInt16 key, UInt16 mustBeZero,
UInt32 byte length, variable character buffer; primary ID **22226/0x56D2**.
The Python `STRING_LINKAGE_KEYS` includes 0–64 plus selected 66–93 values;
keys are **not** primary IDs. A recognized name/URL/expression is not activation
permission. Preserve key, original byte encoding and unknown tail. EndField key
62 is structural, not arbitrary editable text.

### 6.2 Core registered primary IDs

Authority **D**: `S12:1193-1278`. All IDs below lack a general typed payload
codec except String; generic binary preservation is implemented. Prefix
`LINKAGEID_` is omitted. Each item inherits the integration policy after the table.

| Category | Primary IDs and native names |
|---|---|
| External/business/reference | 13333 RefExtractor; 20285 DDE_LINK; 22244 XData; 22248 LevelLibrary; 22251 RasterMetadata; 22294 DGNECPlugin; 22299 ECOMConnection; 22527 DgnLinks; 22624 REFERENCE_PROVIDERID; 45086 OLE |
| Identity/association | 20357 Node; 20372 CellDef; 20389 ACS; 20394 AssociatedElements; 22224 Dependency; 22232 AssocRegion; 22234 SeedPoints; 22235 MultipleLevels; 22236 ClipBoundary; 22237 FilterMember; 22245 BoundaryAssociations; 22257 ElementIDArray; 22285 PersistentTopology; 22295 ModelID; 22296 ModelHandler; 22297 ComponentSet |
| Geometry/modeler | 20799 UvVertex; 20899 RenderVertex; 21033 Feature; 21038 EmbeddedBRep; 21041 Profile; 21047 Compression; 22228 Thickness; 22229 DoubleArray; 22247 LoopOEDCode; 22249 InfiniteLine; 22250 SharedCellFlags; 22301 GeotechnicalData; 22353 ByteArray; 22525 DwgToleranceData |
| Masks/symbology/tools | 22227 BitMask; 22230 ToolTemplate; 22241 Symbology; 22255 StandardsChecker; 22256 StandardsCheckerSettings; 22258 StdsCheckIgnoredError; 22267 CustomKeypoint; 22269 TestLinkage; 22288 MultiStateMask; 22289 MstnApplicationSetting; 22587 TemplateData; 22837 RibbonCustomizationDataHost; 22856 DgnlibLocalizationData |
| Text/dimension | 22220 TEXTNODE_Linkage; 22221 TEXT_Linkage; 22226 String; 22238 DimExtensionLinkage; 22259 TextAnnotation; 22529 TEXTSTYLE; 22544 TEXT_IndentationLinkage; 22551 TextRendering; 32980 TEXTATTR_ID |
| XML/EC | 22243 XML; 22271 ECXAttributes |
| Sheet/printing | 22253 SheetProperties; 22254 SheetScales; 22273 SheetPropertiesEx; 22298 PrintStyle; 22765 ReferenceRenderingPlot; 22876 SheetPropertiesEx2 |
| Animation/rendering | 20904 AnimatorCompressionCell; 22262 AnimationModel; 22263 AnimationScriptParameter; 22264 AnimationData; 22265 AnimationPlugins; 22266 AnimationEntryDescriptions; 22268 AnimationTimeElement; 22270 AnimationKeyFrameElement; 22284 AnimationElemOrch; 22287 ConflictRevisions; 22291 MaxwellMaterialMapping; 22300 LuxologyPresetMapping |

The table uses source names rather than assuming that numerically equal linkage,
XAttribute-major and application IDs share the same payload. Registry aliases and
deprecated/test IDs need explicit status in a future machine-readable catalogue.
The native registry itself explicitly says it is **not comprehensive**
(`S12:1280-1285`); listing all entries in it cannot close application coverage.

### 6.3 Specific missing payload schemas

| Feature | Layout/format and source | Python integration |
|---|---|---|
| Bit masks, primary 22227 | `MSBitMaskLinkageData`, S09:1242-1257: key, default/reserved bits, valid-bit count, short count and UInt16 array | Decode sparse/default bits, validate allocation/count, preserve unused bits |
| Multi-state masks, 22288 | S09:1259-1274: key, bits/state, default, reserved, state/short counts and packed shorts | Bounded packed-state view; unknown defaults and padding preserved |
| Symbology, 22241 | S09:1276-1284: key/override bitmask, Int32 style, UInt32 weight/color/level | Join color/style/level tables; typed scalar edits only with reference validation |
| Dependency, 22224 | S13:20-84: root types 0–8; element IDs, valued IDs, associative points, far IDs, path-valued and in-model IDs; copy options 0–3 | Read-only dependency graph; no callback or target resolution. ID-changing edits blocked until remap implementation |
| Dependency associations | S13:128-215: 40-byte AssocPoint constant; special Assoc1_I is 24 bytes with target hi/lo, subtype and linear/projection/arc/origin union | Choose root type before decoding; preserve far attachment paths and user values |
| XML, 22243 | `MSXMLLinkageData`, S09:1286-1299: UInt16 linkageType/appID/appType/reserved, UInt32 numBytes and buffer | Decode XML-fragment envelope in section 7, not plain XML at payload offset 0 |
| DWG XData, 22244 | S14:101-115: group 1000 string, 1001 app ID, 1002 control string, 1003 layer, 1004 binary, 1005 handle; 1010–1013 point/vector; 1040–1042 double; 1070 Int16, 1071 Int32 | Parse group records and registered app boundaries. **App/handle UInt64 byte order reversed** per native API; resolve via registration table, never fixed app IDs |
| Embedded BRep, 21038 | ID declaration S12:1203; application/modeler representation U | Passive bytes and qualified handler metadata first; no Parasolid/ACIS assumptions or kernel installation |
| Dimension extension, 22238 | ID S12:1219, dimension declarations S08:1034-1289 | Locate exact option/linkage subtype writer before offsets/checksum editing |
| OLE, 45086 | ID S12:1274; payload U | Classify as potentially active embedded/link content; no COM activation, preview or target access |

For every ID-only entry in section 6.2: register a **name and opaque inspection
view first**; trace native save/load/version rules before claiming a binary
layout; validate before enabling typed edits; preserve original bytes if the
schema is unknown. A universal “user data = XML” decoder is prohibited.

## 7. XAttributes, XML fragments and DgnStore

### 7.1 Handler identity and compression

`HandlerId`, `S15:22-49`: full handler ID is
`(UInt32(major) << 16) | minor`. Attribute ID is a **separate UInt32**.
Examples: ECField `(22277,0)` → `0x57050000`; ECXAttributes major
22271 → `0x56FF0000` for minor 0. A major ID value must not be compared
directly to a full handler word.

`CompressedXAttrHeader`, `S16:12-24` (**W**): UInt16 type,
UInt16 padding, UInt32 uncompressedSize, followed by payload.
Type 1 Disallowed and 2 Uncompressed both store plain bytes; type 3 has enum
name **LZW**, but the writer calls **DgnZLib::CompressData** at
`S16:100-103`, whose implementation calls `compress2`, `S17:519`.
It is zlib/DEFLATE here, not an independently implemented LZW codec.
Explorer already handles this envelope generically.

Missing: handler-scoped compression dispatch and bounded nesting depth.
Generic envelope sniffing can mistake arbitrary binary data for this header.
Identity/size/EOF/version tests should precede decoding; unsupported compression
or ambiguous binary stays opaque. Do not recursively reinterpret forever.

### 7.2 Legacy XML-fragment envelope

Authority **W**, `S18:147-158`, `S19:520-579,782-816`:

1. Outer Int32 encoding **1 BinaryCrossPlatform** or **2 gZip**;
   Int32 declared uncompressed stream size.
2. Compressible body: UInt32 total XML data size; Int32 declared schema string
   size; schema URN string; Int32 XML string size; XML string.
3. Encoding 2 calls DgnZLib (zlib wrapper), despite the `gZip` spelling.
4. XML strings are written via DataExternalizer; source has an explicit warning
   that declared locale-byte counts can disagree with actual UTF-16 strings
   (`S19:546-558`). Decode writer/reader string framing, **not a guessed
   fixed slice using those lengths alone**. Exact Unicode/tail behavior needs
   regression fixtures for the affected version.
5. Stored directly in linkage 22243 with appID/appType, or split into DgnStore
   header/components with ID `'XMLf'`, `S12:1292`, `S19:691,831-845`.
   Application IDs are combined/split by `XMLClass_extractIDandTypeFromDGNStoreApplicationID`.

Explorer currently exposes generic binary/text, not this schema-aware envelope.
Implement `xml_fragment_view/bytes` within the single codec module:
bounded read cursor, exact outer framing, strict original string encoding,
schema/app identities immutable; lossless content externalization to existing
UTF-8 workspace content. Validate XML without loading external DTD/schema/URI.
Unknown roots/namespaces/attributes remain preserved. Keep exact unchanged
buffers, counts/terminators/padding and compression policy.

### 7.3 DgnStore payload assembly

`S08:3927-3951` (**D**, consumed by S19) defines:

- Header core: seven UInt32 componentCount, sequenceNo, dgnStoreId,
  applicationId, checkSum, totalSize, dataSize; then byte payload.
- Component core: UInt32 dataSize and sequenceNo; then byte payload.
- Source describes generic DgnStore ID as `'dStr'`; XML uses `'XMLf'`.
  Numeric/multichar byte order still requires emitter validation.
- Additional DgnStore IDs in `S12:1288-1301`: `'BRep'` embedded BRep,
  `'BRpt'` partition, `'BRdt'` delta, `'Adfm'` embedded ADF, `'tSet'`
  TagSet, `'Ole '`/`'OleS'` OLE container/application storage, and
  `'MSet'`/`'Ver1'` settings/version. These distinguish blob roles; they
  do not establish the corresponding modeler, tag, COM or settings layouts.

Missing feature: aggregate blobs spanning elements, with checksums and
application-qualified payloads. Validate sequence/count/total/data extents and
checksum algorithm from its handler before enabling write. A partially decoded
component must never be rewritten as a complete logical blob. Preserve the
original component partitioning for no-edit repack; resizing/repartitioning
requires complete ownership and dependent count updates.

### 7.4 Core XAttribute major-ID catalogue

Authority **D**: `S09:792-888`. These are names/major IDs, **not layouts or
full handler IDs**. Minor IDs must be traced at each handler. All lack complete
typed codecs except the limited ECField case and whole-text/compression fallback.
The integration workflow is section 10; categories below remain binary unless
their concrete serializer establishes XML/JSON/text.

| Category | Major IDs and source names |
|---|---|
| Small/private IDs | 100 CellIndexTool; 101 TabBasedViewGroup; 102 FilletChamferTool; 103 CameraNavigationSpeed; 104 ObjectStateID; 105 NamedViewDisplayElement; 106 RelationDictionary; 107 LevelMaskSubtree; 108 DynamicView; 109 ViewClipper; 110 PlacemarkHandler; 111 DisplayStyleListElement; 112 PolygonDwgExample; 1002 RELATIONID_GlobalVariable; 1003 RELATIONID_Reserved_1003; 1003 RightsToken |
| Strings/XML/handler selection | 22226 String; 22234 Constraint; 22239 MPTOOLSApplication; 22243 XML; 22252 ElementHandler; 22258 StdsCheckIgnoredError; 22275 Generic |
| EC/business links | 22260 Relationship; 22261 DesignLinks; 22271 ECXAttributes; 22277 ECField; 22294 DGNECPlugin; 22587 TemplateData; 22587 XDataTreeData; 22625 NamedExpressionData; 22627 NamedExpressionKeywordData; 22638 ComponentSetQuery |
| Styling/materials | 22272 SymbolSettings; 22274 AnnotationScale; 22276 ColorBook; 22279 MstnSettings; 22280 MaterialProperties; 22281 ExtendedColorTable; 22282 MaterialTable; 22630 DisplayStyle; 22633 DisplayStyleMap; 22634 DisplayStyleIndex; 22635 ActiveTextStyle |
| Views/references | 22293 MstnViewHandler; 22295 ViewInfo; 22297 PlacemarkData; 22624 REFERENCE_PROVIDERID; 22626 DynamicViewSettings; 22628 SectionGeometryGenerator; 22629 ViewDisplayOverrides; 22632 SectionGeometryCached; 22636 RefDynamicViewSettings; 22637 DynamicViewHandler; 22741 NamedViewCalloutProfile; 22856 ViewportDrawnCellHandler; 22860 AnnoElemOrientToLayoutInRef |
| Geometry/modeling | 22290 BSurfTrimCurve; 22296 XGraphics; 22631 StandardSurface; 22640 SmartModeling; 22641 RebisElementHandler; 22648 SpiralHandlerXAtrID; 22650 XGraphicsName; 22739 CIF; 22746 PointCloudHandler; 22913 QVXtraLargeOptimizedMesh |
| Rendering/lighting | 22643 LxoViewSettings; 22644 LxoSetupListElement; 22645 LxoSetup; 22646 LxoMaterialPreset; 22647 MaterialPreview; 22649 LightProperties; 22744 InsolationMesh; 22769 IlluminationMesh; 22858 RasterLineStyleImageData; 22859 AtmosphereFiles |
| Raster/media | 22278 IcoData; 22283 RasterFrame; 22286 GoogleEarthData |
| Review/history/printing | 22287 ConflictRevisions; 22298 PrintStyle; 22639 DesignReviewData; 22642 Markup; 22652 InterferenceJob; 22653 MarkupViewElementHandler; 22654 IModelProxy; 22745 HUDMarker; 22750 ScheduleLinker |
| Application/customization | 22826 CyestCorp; 22827 Mining; 22828 TextSnippetHandler; 22837 RibbonCustomizationDataHost; 22857 LabelHandler |
| DWG compatibility | 22861 ViewPortSymbologyOverrideDWG; 22862 TextFrameFlagDWG; 22864 DWGReferenceFrozenLevel |

Additional registries outside this enum:

- `S20:23`: ECSchema handler major **0xEC34** is locally declared.
- `S21:158-197`: ECXData and ECXDStructValue handler factories use named IDs;
  numeric definitions not established by this review. Do not assign the
  ECXAttributes major to them.
- CIF subranges and subtype aliases are in
  `S22:18-110,210-219`, terrain IDs in `S23`, building IDs section 9.
  These are application extensions, not new basic element type numbers.
- Public handler APIs for text tables, display rules, parametric connectors,
  placement points, solar paths and pick lists indicate further registered
  capabilities; exact disk schemas remain **U** until concrete serializers
  and their private registries are traced.

#### CIF and terrain extension catalogue

`S22:25-110`: CIF application/XAttribute major **22644** is distinct from
CIF element-handler major **22739**. Major 22644 also appears under an Lxo
name in the generic registry; context and minor IDs matter. Survey application
major **60000** and annotation element-handler majors **55555–55559** are
declared. XAttribute minors: SaveSettings 201; view-handler offsets 400–419
(profile/dynamic section/cross-section/super-elevation/regression/plan/scales);
3D ViewClipper 500; DisplayInfo 510, IsGraphicObject 511,
FeatureDisplayInfo 512; SyncID 520, ModelHierarchy 521,
VersionHistory 522, CurveSetInfo 524, TagInComplexInfo 525;
annotation point/cross-section 600/601, precooked value 610,
AnnotationBlock 611, LabelDefinitionName 612. Preserve aliases, including
cross-section-sheet sharing the exaggerated-sheet minor.

`S23:10-46`: terrain major **22764**, MrDTM major **22775**;
terrain element handlers 11/12/21 and MrDTM handler 0.
Terrain XAttribute minors: display style 1, reference 100, header 300,
feature/point/node/CList/FList arrays 301–305, display parameters 310,
level ID 311, feature-table map 320, reference count 331,
display-info/display-reference overrides 332/333, translation 334,
MrDTM/DTM details 350/351. `S23:49-90` adds display subelements
1001–1015 and MrDTM detail keys (min/max, clipping, file moniker,
density, scheduling, draping and triangulation).

All are missing typed Explorer adapters. Binary layout is U beyond the
registry: start with name/ownership inspection, trace array/header serializers,
validate terrain counts/topology/qualified references, then permit supported
scalar replacement. Preserve unknown arrays and do not load draped raster files.

## 8. Embedded XML/JSON, EC properties and Item Types

### 8.1 Proven structured sections

| Feature/category | Exact source and representation | Missing Python integration |
|---|---|---|
| ExtendedColors | `S24:214-246,276-345,460-470`: header XAttribute major 22281, minor 0, attr 0; CompressedXAttribute with UTF-16 XML root `ExtendedColors`, child `Entry`, `Color` attribute | Typed entry/book/color semantics and duplicate/unknown attributes; preserve XML lexically on unchanged save |
| SolarLightMap | `S25:12,128,2348-2510`: LightProperties major 22649, minor 1, UTF-16 XML; map flags/index/type/mode/wrap/units/angle/file/procedural nodes | Typed passive light-map inspector; no texture/procedural file loading |
| Light setup/advanced lights | `S25:988-1166,2181-2300,2658-2819`: XML attributes for flags, shadows, volume, solar date/time/temperature, intensities, brightness/gamma/tone mapping | Validate numeric/date/enum domains and element IDs. Preserve extension nodes. Native rendering is not part of codec validation |
| Display styles | `S26:63-184`: handler-specific compressed **binary** settings, fixed base plus UInt16 fragmentSize/subType and payload; other handlers may use XML | Distinguish binary settings from user-suggested “XML display styles”; bound fragments and preserve deprecated subtypes |
| Background map JSON | `S27:2452-2464,2556-2595,2926-2948`: StringXAttribute key **89**, attr 0; major String 22226 with minor key; UTF-16-facing persistence, UTF-8 in ViewInfo | Typed `providerName`, `groundBias`, `transparency`, `displayPlane`, `providerData.mapType/mapStyle`; preserve provider extensions and do not contact map services |
| Embedded EC schema | `S20:224-300`, `S28:399-406`: schema XML stored through SchemaElementHandler/XML-fragment ecosystem with StringXAttributes schema name/version/provider | Build local schema index; validate references/version consistency without fetching external schemas |
| Material/environment/render maps | `S29`: native XML material/map/environment consumers; major IDs 22280/22282/22645 etc. from registry | Candidate gap: trace exact persistence entry per material version. Texture paths passive; no universal environment XML root asserted |
| EC field expressions | Current `text_field_view` and native TextField implementation | Do not execute or silently “repair” formulas, links or placeholder field errors. Generic EC codec must be separate from existing limited ECField view |

XML/JSON structural validity is necessary, not sufficient. Generic reserialization
can lose whitespace, attribute order, comments, namespace prefixes, duplicate
keys and precision. Keep original text unchanged unless editing; reject edits
whose semantics/encoding cannot be represented safely, or preserve unsupported
regions explicitly. No external schema resolution or expression execution.

### 8.2 ECXAttributes binary token format

Authority **W/D** `S30:32-157`, `S31:1151-1201`.

- Subtypes/minors 0 stored schema, 1 external schema, 2 hidden stored,
  3 hidden external.
- Instance prefix UInt32 version **0x01010000**.
  Stored form appends `PersistentElementPath` to schema element; external form
  appends schema name and major/minor versions using DataExternalizer.
  A variable-length path/string cannot be skipped with a fixed guessed offset.
- Binary XML body has packed 17-byte `ECXAttributeHeader`.
  Identifier bytes **01 42 45 43 58 4D 4C 00 FF 0A 0D** (`BECXML`);
  three version bytes 1/0/0; flags1, flags2, compression byte.
- Flags1: endian `1`, character endian `2`, random-access `4`,
  strict-XML-string `8`, validated `16`.
- Compression enum None 0 / GZIP 1; **actual emission/reader path must be
  checked independently of the outer CompressedXAttribute and XMLFragment
  wrappers**.
- Token codes: empty/content element `00–03`, end `04`, attribute start/end
  `05/06`, character content/ref `10/11`, declaration `20`, string table `30`,
  trailer `32`.
- Typed values: Bool `F0`, Byte `F1`, Int16 `F2`, Int32 `F3`, Int64 `F4`,
  Point2d `F5`, Binary `F6`, Double `F7`, DateTime `F8`, Point3d `F9`,
  String8 `FA`, String16 `FB`, StringRef `FC`, Array `FD`, StringArray `FE`.
  Detailed token/value structs are `S30:159-333`.
- Counts are a **tagged-width encoding, not LEB128**:
  `S31:1567-1601`, `S52:253-280`. Values 0–239 use one byte;
  240–255 use `F1` + UInt8; 256–32767 use `F2` + little-endian Int16;
  larger nonnegative Int32 counts use `F3` + four little-endian bytes.
  Reject negative/truncated/unsupported codes and apply application limits.
- `S31:3070-3122`, `S52:295-337`: String8 is **low-byte Unicode
  code units**, not UTF-8 or a locale multibyte string. String16 uses
  two-byte code units; the encoded count is a **character/code-unit count**,
  despite the `byteCount` member name. Neither writes a trailing NUL;
  the reader adds one only in memory. Preserve exact original form and
  surrogate validity according to the supported version.
- `WriteHeader`, `S31:3186-3192`, currently emits the constructor's
  Compression_None header. GZIP 1 is declared, but not emitted by this
  inspected writer path.

Explorer has **no general BECXML token reader/writer**. Implement bounded
token/string-table parsing and schema-qualified typed trees, retaining raw
token spans and unsupported flags. Strings are strict according to header and
native string semantics, not automatically UTF-8. Validate nesting, references,
arrays, null/value types, version and all offsets before editing. Begin with
read-only inspection; enable scalar replacements only when full serialization
and schema identity preserve byte fidelity and native provider invariants.

### 8.3 ECXData/ECXD is a separate representation

`ECXDInstanceHeader`, `S32:111-167`, is explicitly packed: schema/class indexes,
UInt16 provider ID, UInt8 flags/reserved, UInt32 schema-layout major/minor.
Flags: has-version `1`, read-only `2`, hidden `4`, has-private `8`, private `16`.
`S50:316-360` asserts an 8-byte base header and 16-byte versioned header.
`S51:24-25` defines both indexes as UInt16. Thus base offsets are schema index
0, class index 2, provider 4, flags 6, reserved 7; versioned major/minor are
8/12. `GetStorageSize/Extract` selects size from has-version flag. The rest
is still class-layout/provider-specific, not a fixed general instance struct.

`S21:158-197,263-410` establishes provider ownership, copy/remap hooks and
pointer-container/dependency behavior. ECXD can use class-layout binary buffers,
not BECXML. **Do not unify the two into a guessed XML payload.**
Read-only inspector needs schema/class cache mapping, layout version and embedded
string/array/null/struct buffers. Typed edits require rebuilding the class layout
and relationship pointers; unsupported providers stay opaque.

### 8.4 Schema and Item Type semantics

`S33:1659-1665,2175-2383` and `S34:696-980` establish ECXML 2.0 namespace
`http://www.bentley.com/schemas/Bentley.ECXML.2.0`, native UTF-8/UTF-16
read/write APIs, primitive/struct/array properties, inheritance, readonly,
custom attributes and calculated properties. These are schemas/APIs, not
proof that every `.ecschema.xml` file is embedded in a DGN.

`S35:17-41,309-310,892-959,2084,2482-2498`: Item Type schema prefix
**`DgnCustomItemTypes_`**, library-component custom attributes,
`ItemTypeWorkingUnit`, pick-list names/data sources/settings, labels and
upgraded TagSet metadata. Item Type restrictions are not identical to the
general EC class model. Explorer's string key 92 “ItemType” is not an Item Type
library/instance implementation.

Missing integration: local schema/library browser, property type/default/unit/
readonly/cardinality constraints, instance-to-schema/class binding, struct and
array values, relationships, calculated-property metadata and pick-list
references. Do not evaluate expressions or external pick-list data. Schema
renaming, library migration, class/property addition/deletion and dependency
remapping remain blocked until all affected instances/provider caches can be
rewritten and validated.

## 9. OpenBuildings and ElectricalSystems application persistence

### 9.1 Building classification and legacy labels

`LinkageDecoder::Decode`, `S36:76-198`, recognizes cells/shared cells using
TFLabel and application linkage presence: forms, frames, fixtures, mechanical
components, structural members, annotation, stairs, grouped holes, railings,
roofs and more. They are **not separate DGN core element type numbers**.

TFLabel primary **20343/0x4F77**, `S37:16`. `S38:770-863` decodes
versioned label layouts 7/6/5, with family/name locale-character arrays, time,
appId, functional bytes and subtype. `S39:19-31` TFLabel contains runtime
pointers and **must not be copied as a disk struct**. Native `LnkDataF...`
templates and on-disk maximum-name constants are the relevant next layout
anchors, not the in-memory object size.

`S53:19-20,260-279` supplies on-disk family/part capacities **9/41**
bytes and LnkDataF7 fields: 32-bit Windows long unused/id, short type,
byte version, family/name buffers, time, UInt16 appId, eight functional
bytes (`S55:223`) and trailing long subtype/unused. Versions 1/2 use
three-byte family capacity; versions 5/6 use nine bytes, with time and
later functional-byte fields (`S54:249-314`). Native reader computes offsets
from templates; alignment and conversion rules must be verified before
declaring packed offsets for all versions.

Implement passive building-family classification over existing generic
elements, then version-specific TFLabel decoders. Encoding depends on legacy
locale conversion; retain undecodable labels as raw. Preserve family/part IDs,
functional bytes and subclass/linkage dependencies. Classification is not
building regeneration or safe geometry authoring.

### 9.2 Building linkage/handler registry

Authority **D**, `S37:10-186`. Each family is currently generic raw in Explorer.
Entries below have binary/application-defined payloads; exact layout is **U**
unless separately traced. Integration: register names, inspect subtype/version,
then trace each writer before a typed editor; preserve unknown subtypes.

| Category | IDs / native feature names |
|---|---|
| Core building/annotation | 48640 TFVERSION; 48641 TMSVERSION; 48642 TFSMARTSECT_DATA; 48643 TFSMARTSECT_STREAM; 48644 TFPARTREF; 48645 TFIDUNIFYLIST; 48646 TFHATCHANGLE; 48647 TFDOCCONTEXT; 48648 TFENTITYREP; 48649 TFANNOTATION; 48650 TFHATCHCELLNAME; 48651 TFWALLSCHEDULEDATA; 48652 TFDOORSCHEDULEDATA; 48653 TFMASTERDEMDESCR; 48654 TFPERFORATOR; 48655 RBLDR; 48656 AUTOANNORULE; 48657 ROOF; 48658 TFANNOTATIONEXT; 48659 CURTAINWALL; 48660 COLUMNGRIDHANDLER; 48661 FLOORPICKERGRIDLIST; 48662 COMPOUNDSLAB; 48663 MODELMAPPED |
| IDs/cache/modeling | 48700 TFID; 48701 PICASSO; 48702 UNIFICATION_CACHE; 48742 TFTYPE66; XAttribute major 48743 ASMmodel; handler 22849 TFSMARTFEATUREHANDLER; handler 22756 TFPARAMETRICCELLHANDLER minor 6; handler 22606 TFSTRUCTURESHANDLER minors 1/10 |
| Architectural/spaces | 48750 ATFSPACES; 48751 ATFELEMENT; 48752 ATFELMCOMP; 48753 ATFSPACELEGEND; 48760 ATFFLOORS; 48770 ATFDGANNOTATION; 48780 ATFCEILING; 48781 ATFCEILINGFIXTURE; 48782 STAIRELEMENT; 48783 FLIGHTELEMENT; 48784 TREADELEMENT; 48785 RISERELEMENT; 48786 LANDINGELEMENT; 48787 STRINGERELEMENT; 48788 STAIRANNOTATIONELEMENT; 48789 COMPOUNDFORMELEMENT; 48790 ATFDGANNOTATIONCOMPONENTS; 48791 ATFANNOTATIONELEVATION; 48792 ATFANNOTATIONLABELCOORD |
| Mechanical | 48800 TMSDUCT; 48801 TMSPIPE; 48802 TMSGEOM; 48803 TMSSECTMRK; 48804 TMSDTAIL; 48805 TMSPCP; 48806 TMSTPCP; 48807 TMSHCP; 48808 TMSTHCP; 48809 TMSLBL; 48810 TMSWRKLN; 48811 TMSCONN; 48812 TMSDEV; 48813 TMSID; 48814 TMSOWN; 48815 TMSCONNTO; 48816 TMSSECT; 48817 TMSOVRRD; 48818 TMSINLINE; 48819 TMSPARA; 48820 TMSFLEX; 48821 TMSTYPETAG; 48822 TMSEQUIP; 48823 TMSFITTING; 48824 HVACENDDATA; 48825 MODIFYTEXT; 48826 MODIFYDIM; 48827 HVACVULCANDATA; 48828 MECHLABEL; 48829 STACKEDANNO |
| Structural | 48900 STFPROFLINE; 48901 STFNONLINEAR; 48902 STFNODE; 48903 STFBEAMELEMENT; 48904 STFMODELANNOTE; 48905 STFLOAD; 48906 STFLOADCASE; 48907 STFLOADCOMBINATION; 48908 STFPLATE2D; 48909 STFHOLE; 48910 STFEXPORTMAP_V2; 48911 STFGRIDSYSTEMDATA; 48912 STFGRIDSYSTEMLIST; 48913 STFSTORYDATA; 48914 ISMID; 48915 OPENING; 48916 MODIFIER; 48917 RAILINGELEMENT; 48918 HORIZONTALRAILELEMENT; 48919 POSTELEMENT; 48920 BALUSTERELEMENT; 48921 REBARREINFORCEMENT; 48922 JOIST; 48923 JOISTTOPCHORD; 48924 JOISTBOTTOMCHORD; 48925 JOISTWEB; 48926 STEELDECK; 48927 COMPOSITEDECK; 48928 JOISTENVELOPE; 48929 SUBSTRUCTURE; 48930 FIREPROOFING; 48931 FIREPROOFINGID |
| Structural XAttributes | 48932 COLUMNSCHEDULE_SETTINGS; 48933 COLUMNSCHEDULE_MODELSETTINGS; 48934 PROSTRUCTURES; 48935 STRUCTURAL_LEGACY; 48936 TEMPORARY_MODEL; 48937 STRUCTURAL_DATA_NONLINEAR |
| Grids/drawings | 48971 STFGRIDSYSTEMMODEL; 48972 STFDRAWINGDEPENDENCY; 48974 STFSTEELCOLUMNSCHEDULE; 48975 STFCONCRETECOLUMNSCHEDULE; 48976 STFMAP; 48977 STFGRIDSYSTEM; 48978 STFELEVATIONGRID; 48979 DRAWINGS_XATTRIBUTEID |
| Non-reserved/legacy | 5000 FM_BUILDING; 0 ATFSPACES_OLD; not a safe new-ID allocation pool |

Important compatibility notes from the same source: TMSVERSION minor IDs
2–100 are reserved for OpenPlant; TMSGEOM/TMSSECTMRK are marked unused/stolen
by another product; 48941 is stolen by ISM; reserved range endpoints are not
payload definitions. Never identify an OBD object solely by a colliding number.

`S37:294-343` additionally declares building XAttribute **minor** IDs:
TFLabel-major DerivedBrepCache 300, DrawingDefinition 302, legacy plan
ceiling/enlarged/site/roof 303/305/306/307, ViewSeedOptions 308 and
ViewBuildingDefinition 309. ProStructures-major StructuralData 310,
FireproofingIdList 311 and ConcreteTaperingIdList 312.
Their attribute IDs include **0 DrawingDefinition**, **0 DerivedBrepCache**,
**0 ViewSeedOptions**, **0 ViewBuildingDefinition**: these zero-valued
`XATTRIBUTEID_...` symbols are **attribute IDs, not handler major IDs**.
Ceiling/fixture minor 1 uses their respective application majors.
ExtendedData document-context versions and extraction/cell-gathering tags
at `S37:250-289` are another versioned application namespace, not core types.

### 9.3 DataGroup XML and EC schemas

`S40:57-71` defines roots **DataGroupInstances**, **DataGroup**,
**ElementFragments**, and attributes **appType**, **catalogType**,
**catalogItem**, **Schema**.
`S41:60-79,108-136,226-323` constructs XML fragment lists, attaches to
elements, and strips/replaces fragments by root/schema. `S42:507-558,644-751`
manages DataGroup catalog metadata and per-schema property fragments.
`S43:60-74,118-132` explicitly bridges local EC schema lookup and legacy
TFLabel/XML-fragment DataGroup detection.

Missing feature: lossless grouping of catalogue instance identity and property
fragments with their schema association, rather than treating any XML blob as
an unrelated editable document. Preserve GUIDs, catalog/family/part/class
identity, fragment order and unknown properties. Typed property edits must
check the local DataGroup schema, engineering units and native synchronization
requirements. No automatic schema upgrades or catalog downloads.

Concrete schema examples (**D**, not proof of embedding):

| Schema/source | Confirmed semantics / expected format | Gap |
|---|---|---|
| `S44:2-45`, BentleyFloors 1.0 | ECXML 2.0; Building name/address/GrossArea/year; Floor FinishedFloorElevation, cut/view depths, typical-floor flags/heights; Wall element/file IDs | Local EC property inspector with strict strings, doubles, dateTime and source identities |
| `S45:2,36-54,155-156,377-379`, openBIM 1.0 | ECXML 2.0; IFC-oriented type hierarchy, measure values, array cardinalities and BuildingStorey Elevation | Generic schema parser, not hardcoded “all values strings”; imported IFC schema does not mean native IFC geometry support |
| `S46`, BuildingDataGroup schema resource | XML/property mapping candidate; search rendered encoding inconsistently | Re-read original BOM/bytes and validate XML before taking line-derived field descriptions as authoritative |

The OpenBuildings tree also has external IFC/COBie schemas and library code.
They are not DGN disk features merely because found beneath this root.

### 9.4 Electrical XData / DataGroup / dependency integration

**W** `ecIObject::ReadFromEntity`, `S47:3093-3184`:

- Resolve registered application **BBES**, fallback **ELCO**, using the DGN
  registered-app table; the assigned 64-bit application ID is file-local.
- Read XData group records and convert string values with `mbstowcs`.
  This is locale-facing text, **not proven UTF-8 or UTF-16 wire data**.
- `ecIObject::tagEED`, `S47:4423-4487`, writes application-name group then
  DWGXDATA_String values via `wcstombs` into a 133-byte buffer.
  Do not copy this native fixed-buffer strategy into Python.
- `S47:3969` and `S48:1359` use dependency links with BES_APPID;
  numeric BES_APPID definition is not established here.
- `S49:27-50,200-239` declares application/object/property-key strings;
  values such as `"023"`, `"0402"` and `"1004"` are business property keys,
  **not DGN element type or linkage primary IDs**.

Missing: app-qualified ordered XData property inspector, exact property
delimiter/key grammar traced from getter/setter implementation, passive CAD/
original-handle/IFC/class/catalog mappings, dependency and DataGroup links.
Expose known keys only after validating grammar and original codepage.
Preserve unknown groups, ordering, registration identity, buffer/padding bytes
and other apps' XData. Never convert ELCO to BBES or execute database/configuration
commands implicitly. DGN compatibility does not authorize a native electrical
object regeneration.

## 10. Python integration architecture and acceptance gates

These rules apply to **every missing feature listed above**, including
ID-only/application-defined entries:

1. **Decode:** add the adapter to the existing codec implementation, re-export
   only via `dgn_explorer\codecs.py`. Dispatch by storage context, element
   type/flags/version, linkage primary+key, full XAttribute major/minor+attribute
   ID, or application/schema identity. One bounded cursor and reversible
   representation; never a competing editable hex/text copy.
2. **Inspect:** include source-backed name, evidence level, locator, byte spans,
   version/encoding and capability state. Add unknown-feature inventory grouped
   by model/list/handler, including file-level/dictionary/history distinctions.
   Cross-reference targets passively; no shell, COM, file, DB, URL or schema access.
3. **Validate:** lengths/counts/offsets/flags and finite numeric values, schema
   type/cardinality/unit domains, local referential integrity, version gates,
   nesting/aggregate decompression limits. Ambiguous/malformed variants remain
   read-only with diagnostics and original bytes.
4. **Typed edit:** start with existing-record replacement of independently owned
   scalars. Extend `workspace.py` capability derivation and trusted-original
   checks; mutable labels never authorize edits. IDs, layout, versions,
   provider/class/schema identity and structural counts stay immutable until a
   complete rewrite/remap algorithm exists.
5. **Repack:** unchanged logical payload/stream reuses original bytes and
   compressed frame. Changed payload derives owned lengths/counts/checksum only
   from the validated serializer. Preserve unknown fields, padding, aliases,
   component partitioning and prefix/suffix bytes. Publish a new verified output,
   never modify input.
6. **Test:** reusable synthetic fixtures per version, 2D/3D, endian/encoding/BOM,
   padding/unknown tails, non-ASCII/control text, empty/max counts, truncated/
   malformed/oversized/nested data, duplicate IDs/keys and cross-model collisions.
   Assert byte-identical no-edit round trip and isolated changed spans. Add
   positive/negative capability, edit/reimport and transaction tests. No new
   dependency is required for read-only cataloguing.
7. **Native correctness:** geometry/dependency/range/checksum/index changes need
   approved isolated native open/render/edit/reopen evidence. Container equality
   and synthetic round trips are not that evidence. Optional baseline-fixture
   tests cannot be silently replaced by arbitrary files.

Priority:

| Stage | Deliverable | Gate |
|---|---|---|
| P0 | Source-backed storage/type/linkage/XAttribute names, unknown-feature report, qualified identities and range/unit labeling | Read-only, no format behavior changes without tests |
| P1 | Models/levels/fonts/styles/views/reference metadata and safe typed masks | Verified native layouts plus synthetic version/cross-reference coverage |
| P1 | XMLFragment/DgnStore assembly and lossless DataGroup/schema browsing | Exact strings/checksum/partition semantics; no external resolution |
| P2 | BECXML reader, schema binding, Item Types and Electrical XData inspector | Complete token/codepage/provider/version tests before edits |
| P2 | ECXD class-layout buffers and relationship inspection | Provider/schema-cache mapping, not reuse of BECXML decoder |
| P3 | Spline/surface/shared-cell/dimension/multiline/matrix/mesh typed editors | Full graph/range/dependency/index repair and native-product validation |
| Separate scope | V7, protected/signed editing, kernel geometry, raster/font/image rendering | Product/dependency/legal/security decisions, not implicit gap closure |

## 11. Compression and encoding findings

| Layer | Evidence | Implementation implication |
|---|---|---|
| Native stream zlib | S17:26,84,312,474,508,519-527 uses inflate/deflate/compress2/uncompress | Existing stdlib zlib appropriate; enforce EOF/size/aggregate bounds and preserve unused data |
| Compressed XAttribute | S16:12-24,100-103 | 8-byte envelope, misleading LZW label; no LZW package needed |
| XMLFragment | S19:520-579,782-816 | Encoding 2 named gZip but uses DgnZLib; distinguish this header from CompressedXAttribute |
| BECXML | S30:121-126 | Compression 0/1 declaration exists; actual gzip emission not proven in this review; separate layer/version gate |
| Legacy raster RLE | S08:204-211: BITMAP 1, BYTE_DATA 2, BINARY_RLE 9, BYTE_RLE 24 | RLE is a raster subtype, not generic DGN stream compression. Exact packet algorithm remains U |
| Packed masks/indexes | S09:1242-1274; S08:4003-4038 | Bit-packed states and mesh index semantics are not compression algorithms interchangeable with zlib |
| LZMA/run-length elsewhere | PPBase vendor compression implementations exist | Presence in a dependency source tree is not evidence DGN persistence uses them |

Strings vary by record: variable character/string linkage, explicit UTF-16 XML,
binary-token String8/String16, property-set codepage strings, legacy locale
arrays and opaque mixed binary/text records. Never apply BOM-less UTF-8 guessing
as a universal DGN rule. Preserve exact endian/BOM/NUL/padding and reversible
encodings; malformed original text is an inspectable raw payload, not a string
that can be rewritten with replacement characters.

## 12. Exact native source register

All references resolve beneath `C:\sources\`; no web source is needed.

| Ref | Absolute source path |
|---|---|
| S01 | `C:\sources\PowerPlatform\DgnPlatform\DgnFileIO\dgnv8fileio.cpp` |
| S02 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnFileIO\DgnV8FileIO.h` |
| S03 | `C:\sources\PowerPlatform\DgnPlatform\DgnFileIO\dgnv8protect.cpp` |
| S04 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\DgnFontManager\DgnFontManager.cpp` |
| S05 | `C:\sources\PowerPlatform\DgnPlatform\DgnFileIO\history\history.cpp` |
| S06 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnFile.h` |
| S07 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnFileIO\XAttribute.h` |
| S08 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnFileIO\DgnElements.h` |
| S09 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnPlatform.r.h` |
| S10 | `C:\sources\PowerPlatform\GeoCoord\DgnGeoCoord\GeoCoordElement.h` |
| S11 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\Linkage.cpp` |
| S12 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnPlatform.h` |
| S13 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DependencyManagerLinkage.h` |
| S14 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\Linkage.h` |
| S15 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\DgnCore.h` |
| S16 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\CompressedXAttribute.cpp` |
| S17 | `C:\sources\PowerPlatform\DgnPlatform\DgnFileIO\zipstream.cpp` |
| S18 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\XMLFragment.h` |
| S19 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\XMLFragment.cpp` |
| S20 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\SchemaElementHandler.cpp` |
| S21 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\ECXDInstanceXAttributeHandler.cpp` |
| S22 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\CIF\PersistentAppIDs.h` |
| S23 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\TerrainModel\TMPersistentAppIDs.h` |
| S24 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\ExtendedColors.cpp` |
| S25 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\Light.cpp` |
| S26 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\DisplayStyleHandler.cpp` |
| S27 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\ViewInfo.cpp` |
| S28 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\ECXAProvider.cpp` |
| S29 | `C:\sources\PowerPlatform\DgnPlatform\DgnCore\DgnMaterials.cpp` |
| S30 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\ECXAttributes.h` |
| S31 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\ECXAttributesWriter.cpp` |
| S32 | `C:\sources\PowerPlatform\DgnPlatform\PublicAPI\DgnPlatform\ECXDProviderBase.h` |
| S33 | `C:\sources\PPBase\ECObjects\src\ECSchema.cpp` |
| S34 | `C:\sources\PPBase\ECObjects\PublicApi\ECObjects\ECSchema.h` |
| S35 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\CustomItemType.cpp` |
| S36 | `C:\sources\OpenBuildings\Triforma\src\tfhandlers\tfenabler\include\publish\tflinkagedecoder.h` |
| S37 | `C:\sources\OpenBuildings\Triforma\src\include\publish\besig.h` |
| S38 | `C:\sources\OpenBuildings\Triforma\src\tfdecoding\src\tflabel.cpp` |
| S39 | `C:\sources\OpenBuildings\Triforma\src\include\publish\bsitflabel.h` |
| S40 | `C:\sources\OpenBuildings\Triforma\src\tfinstancedata\include\publish\instancedatadefs.h` |
| S41 | `C:\sources\OpenBuildings\Triforma\src\cataloginstancecollection\XmlFragmentPropertySerialization.cpp` |
| S42 | `C:\sources\OpenBuildings\Triforma\src\tfinstancedata\instancedata.cpp` |
| S43 | `C:\sources\OpenBuildings\Triforma\src\clr\datagroupextension\ECInstancePersistenceStrategy.cpp` |
| S44 | `C:\sources\OpenBuildings\Triforma\projectmanager\BuildingProjectManagerPlugin\BentleyFloors.01.00.ecschema.xml` |
| S45 | `C:\sources\OpenBuildings\Triforma\src\tfapp\tfasm\tfasmengine\openBIM.01.00.ecschema.xml` |
| S46 | `C:\sources\OpenBuildings\Triforma\src\clr\tools\walls\Resources\BuildingDataGroup.01.00.ecschema.xml` |
| S47 | `C:\sources\ElectricalSystems\BBES_ABD\src\BD_Electrical\src\besClassecIObject.cpp` |
| S48 | `C:\sources\ElectricalSystems\BBES_ABD\src\BD_Electrical\src\besV8.cpp` |
| S49 | `C:\sources\ElectricalSystems\BBES_ABD\src\BD_Electrical\src\besClassecIObject.h` |
| S50 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\ECXDProviderBase.cpp` |
| S51 | `C:\sources\PPBase\ECObjects\PublicApi\ECObjects\ECDBuffer.h` |
| S52 | `C:\sources\PowerPlatform\DgnPlatform\DgnHandlers\DgnEC\ECXAttributesReader.cpp` |
| S53 | `C:\sources\OpenBuildings\Triforma\src\include\publish\tfsaveloa3.r.h` |
| S54 | `C:\sources\OpenBuildings\Triforma\src\include\publish\tfsaveloa3.h` |
| S55 | `C:\sources\OpenBuildings\Triforma\src\include\publish\tfinfo.h` |
| S56 | `C:\sources\PowerPlatform\DgnPlatform\DgnFileIO\ElementRef.cpp` |

## 13. Second-pass review, evidence and remaining gates

The second pass checks path existence/ranges, the three core ID catalogues
against source declarations, enum coverage 1–128, and the specific magic/
compression/encoding claims against consumers rather than comments alone.

### Census results

Completed local census: **58,375 selected files; 58,345 read; 30 larger
than 4 MiB excluded; no OS read errors; 342 files needed lexical encoding
fallback**. Counts below are files with at least one match, not unique features.
Schema hits include XSD; EC-schema counts also include code/test literals.

| Root | Selected/read | Over limit | Encoding fallback | Storage | Elements | Linkages | XAttributes | Schema | Compression | EC-schema text |
|---|---|---|---|---|---|---|---|---|---|---|
| PowerPlatform | 27369/27366 | 3 | 101 | 180 | 472 | 298 | 627 | 202 | 137 | 209 |
| PPBase | 11875/11867 | 8 | 56 | 30 | 0 | 2 | 2 | 520 | 11 | 529 |
| OpenBuildings | 18891/18872 | 19 | 151 | 353 | 101 | 274 | 66 | 551 | 5 | 58 |
| ElectricalSystems | 240/240 | 0 | 34 | 0 | 1 | 3 | 0 | 0 | 0 | 0 |

Excluded files: 19 OpenBuildings energy catalog/HVAC XML resources; two
PowerPlatform AI transcript JSON files and
`C:\sources\PowerPlatform\DgnECPlugin\test\data\Bentley_Plant.05.00.ecschema.xml`;
eight PPBase OpenPlant supplemental modeling-view schema fixtures under
`C:\sources\PPBase\Ecf\sdk\tools\ECDeltaManager\Tests\Atp\Schema\OpenPlant\`.
These exclusions are a completeness limit, not evidence they contain no gaps.
Extensions outside the selection, generated/binary resources, conditional
code and runtime definitions are additional explicit limits.

Second-pass schema check: S44 BentleyFloors and S45 openBIM parse as ECXML
2.0 with version 1.0 (11 and 268 direct schema children respectively).
S46 has UTF-16 BOM but **fails XML parsing at line 1, column 40**.
It remains a malformed-source/encoding gap; its search output is not used
as a proven field specification.

Document verification checks **56 registered paths and 242 line/range spans**,
including comma-separated spans. The core element enum has **60 assigned
values**; the table accounts for all 128 requested values with **68 unassigned
in this enum**, no overlaps or omissions. Registry comparison accounts for all **78**
`LINKAGEID_` declarations in S12 and all **97** `XATTRIBUTEID_` declarations
in S09, preserving aliases. S37 primary/major declarations and separately
named minor/zero-valued attribute IDs were rechecked (127 non-endpoint
`LINKAGEID_`/`XATTRIBUTEID_` numeric declarations in that file). This is registry
coverage, **not all native handlers**, as the source itself warns.

Source suite on the current checkout: `python -m unittest discover -s . -p
'test_*.py' -v` ran **191 tests: 115 passed, 76 skipped**. The skips are
14 unavailable baseline-fixture checks and 62 policy-admitted Qt-dependent
checks. No dependency installation or native-product validation was performed.
These are existing-behavior tests, not tests of the proposed codecs.

### Reproducibility fingerprints

SHA-256 of the primary native evidence at review:

| Source | SHA-256 |
|---|---|
| S01 | `8770aed31f32eb96a6c9a32d25d6519bce6c7c45a96b96db97cc41b3f9e37c23` |
| S08 | `89c7e6f92a699353eaa4341163e669d02c09304a707498b0cd0d257d97e5716c` |
| S09 | `6dfd217b9af255e4acbfa670210a9d770c3d0a07a7de9af37448d5b555ec42e7` |
| S12 | `7772cb539f4acfd2e8bee7ac0fba340e4109d5fd9cc4c1e84ed1405fbf4451fa` |
| S30 | `cef07cd0c24310e62b96ddfe715aef654a92503b5b4c0f04892f3c2c7cd393ef` |
| S37 | `3d4337c8a99e3b208b325be5506c7d5a12f5dabcea78875c4cb715ef46042b92` |

Explorer baseline fingerprints, including pre-existing uncommitted changes:

| File | SHA-256 |
|---|---|
| `dgn_folder.py` | `913236916bd83980952934779884e8c25e031cb7e34b4289c27276346a86d643` |
| `dgn_explorer\codecs.py` | `3f1d2c9b28aa70af2e708e6f97f27990cf57a05f9562a07f63d216dceb5d39bb` |
| `dgn_explorer\workspace.py` | `d57e9103f9bbe4336c1cab034a13e9ba299c79134dae30005d8baf20fca3d65f` |

Confirmed corrections carried into this document:

- Cell Library 1 versus Cell Header 2; core maximum 113; unknown numbers retained.
- B-spline knot/weight comment inversion corrected using authoritative enum.
- XAttribute major/minor/attribute identity separated; linkage IDs not reused as
  full handler IDs.
- zlib versus misleading LZW/gZip names separated by serialization layer.
- Binary XML/ECXD not conflated with plain XML; DataGroup schema resources
  distinguished from embedded document evidence.
- In-memory range conversion and runtime TFLabel pointers explicitly excluded
  from naïve disk mapping.
- File encryption bit 2 versus block encryption bit 4 distinguished.
- Canonical storage roles separated from example/unproven names.

Remaining **unclosed** gates: every application/vendor-defined subtype writer,
private registries, generated/runtime schemas, legacy/V7 conversion, exact
DgnStore checksum and repartition rules, XMLFragment historical declared-length
anomalies, ECXD index/class-layout variants, BECXML compression variants,
history-root/revision integrity, signed/protected editing, kernel-specific BRep,
raster RLE packet layouts, font/resource loading and native-product correctness.

This document supplies an implementation roadmap, not evidence that these
features have been implemented or validated against native files.
